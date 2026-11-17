"""Web UI 网页搜索域处理器（独立 tab）：引擎状态 / 试搜 / 连通性自检。

零 JS 服务端渲染（与 mcp_panel 同模式）：表单 POST → 重定向回 msg。
搜索服务由 main 注入 router.ai_tools.search；未注入或未开时只展示提示。
"""
import asyncio
import time
from typing import Optional
from urllib.parse import quote

from aiohttp import web

from src.services.web_search import ENGINE_IDS, ENGINE_LABELS
from src.services.webui_render.graphics import empty_state
from src.services.webui_render.util import _esc

#: 试搜/自检用的固定查询（避免空查询白跑回退链）
_PROBE_QUERY = "Flowerie bot"


class SearchPanelMixin:
    """「网页搜索」tab：引擎卡片 + 配置开关 + 试搜 + 自检。"""

    def _search_service(self):
        """取搜索服务（main 注入 WebUIServer，与 AI 工具层共享同一实例；未注入返回 None）。"""
        return getattr(self, "_search_service_ref", None) or None

    def _render_search_page(self, msg: str = "", err: bool = False,
                            probe: Optional[dict] = None) -> str:
        svc = self._search_service()
        enabled = bool(svc is not None and svc.enabled())
        engine_order = svc._engine_order() if svc is not None else ()
        last_tests = getattr(self, "_search_test_cache", None) or {}
        overview = _overview(svc, engine_order, last_tests) if svc is not None else (
            '<div class="alert warn">搜索服务未接入。</div>')
        state_hint = (
            '<p class="hint">AI 搜索已开启，模型可自主调用 web_search / web_fetch。</p>'
            if enabled else
            '<p class="hint">AI 搜索未开启，可在「自动化」页打开 AI_SEARCH_ENABLED。</p>')
        native_usable = svc is not None and svc.deepseek_native_usable()
        engine_options = "".join(
            f'<option value="{eng}"{" disabled" if eng == "deepseek-native" and not native_usable else ""}'
            f'>{eng}</option>' for eng in ENGINE_IDS)
        # 试搜结果（不可信外部输入：仅文本回显，不做任何渲染）
        probe = probe if probe is not None else getattr(self, "_search_probe_cache", None)
        probe_html = ""
        if probe:
            if probe.get("ok"):
                items = "".join(
                    f'<article class="search-result"><h3>{_t(s.get("title", ""))}</h3>'
                    f'<div class="row-key">{_t(s.get("url", ""))}</div>'
                    f'<p>{_t(s.get("snippet", ""))}</p></article>'
                    for s in (probe.get("sources") or [])[:5])
                empty_hint = empty_state("search", "无结果，可尝试其他关键词。")
                probe_html = (
                    f'<details class="cfg-group" open><summary class="cfg-summary">'
                    f'<span class="cfg-caret" aria-hidden="true"></span>试搜结果'
                    f'（实际命中引擎 {_t(probe.get("engine", ""))}，'
                    f'{len(probe.get("sources") or [])} 条{"，缓存" if probe.get("cached") else ""}）</summary>'
                    + (items or empty_hint) + "</details>")
            else:
                probe_html = (
                    '<details class="cfg-group" open><summary class="cfg-summary">'
                    '<span class="cfg-caret" aria-hidden="true"></span>试搜失败</summary>'
                    f'<div class="hint">{_t(probe.get("error", ""))}</div></details>')
        # 自检结果
        test_html = ""
        if last_tests:
            items = []
            for eng, res in last_tests.items():
                ok = res.get("ok")
                badge = '<span class="badge ok">通过</span>' if ok else '<span class="badge warn">失败</span>'
                detail = f'{res["results"]} 条结果' if ok else _t(res.get("error"))
                if "budget" in res:
                    detail += f' · 本次耗时 {res["seconds"]:g} 秒 · 预算 {res["budget"]:g} 秒'
                if eng == "deepseek-native":
                    detail += '（完整模型回合，使用较长预算）'
                items.append(
                    f'<div class="row"><div class="row-info">'
                    f'<span class="row-title">{_t(ENGINE_LABELS.get(eng, eng))}</span>'
                    f'<span class="row-key">{_t(eng)}</span>{badge}</div>'
                    f'<div class="row-control"><span class="hint">{detail}</span></div></div>')
            test_html = (
                '<details class="cfg-group" open><summary class="cfg-summary">'
                '<span class="cfg-caret" aria-hidden="true"></span>引擎自检结果</summary>'
                f'{"".join(items)}</details>')
        return (
            f'<section aria-label="网页搜索">{overview}{state_hint}'
            '<details class="cfg-group" open><summary class="cfg-summary">'
            '<span class="cfg-caret" aria-hidden="true"></span>试搜 / 自检</summary>'
            '<form method="post" action="/panel/search/probe" class="search-probe">'
            '<label for="search-query">试搜关键词</label>'
            f'<input type="text" name="query" id="search-query" value="{_PROBE_QUERY}">'
            '<label for="search-engine">优先引擎</label>'
            '<select name="engine" id="search-engine" aria-describedby="search-probe-hint">'
            f'<option value="">自动（按当前顺序）</option>{engine_options}</select>'
            '<button type="submit" class="btn">试搜</button>'
            '<p id="search-probe-hint" class="hint">指定引擎失败时会按当前顺序回退。</p></form>'
            '<form method="post" action="/panel/search/test">'
            '<div class="row"><div class="row-info"><span class="row-title">逐引擎自检</span>'
            '<span class="hint">逐个试搜当前顺序中的引擎。DeepSeek 原生搜索会产生费用。</span></div>'
            '<div class="row-control"><button type="submit" class="btn">开始自检</button></div>'
            '</div></form></details>'
            f'{probe_html}{test_html}</section>')

    async def _handle_panel_search_probe(self, request: web.Request) -> web.Response:
        """试搜：用当前配置跑一次真实搜索（结果以 msg 与区块回显）。"""
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        svc = self._search_service()
        if svc is None:
            return web.HTTPFound("/panel?tab=search&err=1&msg=" + quote("搜索服务未注入（需重启）"))
        form = await request.post()
        query = str(form.get("query", "") or "").strip() or _PROBE_QUERY
        engine = str(form.get("engine", "") or "").strip()
        if engine and engine not in ENGINE_IDS:
            return web.HTTPFound("/panel?tab=search&err=1&msg=" + quote("不支持的搜索引擎"))
        if engine == "deepseek-native" and not svc.deepseek_native_usable():
            return web.HTTPFound("/panel?tab=search&err=1&msg=" + quote(_native_status(svc)[1]))
        try:
            probe = await svc.search(query, max_results=5, engine=engine or None)
        except Exception as e:  # noqa: BLE001 - 试搜失败即结果
            probe = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        self._search_probe_cache = probe
        msg = quote("试搜完成") if probe.get("ok") else quote("试搜失败：" + str(probe.get("error", ""))[:80])
        return web.HTTPFound(f"/panel?tab=search&msg={msg}&err={'1' if not probe.get('ok') else ''}")

    async def _handle_panel_search_test(self, request: web.Request) -> web.Response:
        """逐引擎连通性自检（手动触发；不给自动跑，避免给公共实例压力）。"""
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        svc = self._search_service()
        if svc is None:
            return web.HTTPFound("/panel?tab=search&err=1&msg=" + quote("搜索服务未注入（需重启）"))
        free_budget = max(40.0, svc._timeout() * 4)
        native_budget = free_budget + 5.0
        signal = asyncio.Event()
        results = {}
        for eng in dict.fromkeys(svc._engine_order()):
            if eng == "deepseek-native" and not svc.deepseek_native_usable():
                continue
            budget = native_budget if eng == "deepseek-native" else free_budget
            started = time.monotonic()
            try:
                # 自检直接调用单个引擎，避开搜索缓存和自动回退。
                async with asyncio.timeout(budget):
                    sources = await svc._dispatch(eng, _PROBE_QUERY, 2, None, signal)
                result = {"ok": True, "results": len(sources)} if sources else {
                    "ok": False, "error": "未返回搜索结果"}
            except TimeoutError:
                result = {"ok": False, "error": "超过该引擎的自检预算"}
            except Exception as e:  # noqa: BLE001 - 逐引擎记录失败
                result = {"ok": False, "error": f"{type(e).__name__}: {e}"[:160]}
            results[eng] = dict(result, budget=budget, seconds=round(time.monotonic() - started, 1))
        self._search_test_cache = results
        return web.HTTPFound("/panel?tab=search&msg=" + quote("自检完成"))


def _native_status(svc):
    if not svc.paid_search_enabled():
        return "已禁用", "付费搜索已关闭"
    if svc.deepseek_native_usable():
        return "可用", ""
    if not svc._deepseek_search_conf()[2].strip():
        return "未配置", "未配置 Key，将使用当前顺序中的免费引擎"
    return "模板值", "Key 仍是模板值，请填真实 Key"


def _overview(svc, order, last_tests) -> str:
    paid = svc.paid_search_enabled()
    native_state, native_hint = _native_status(svc)
    auto = svc._auto_deepseek_priority()
    configured = str(svc._cfg("SEARCH_ENGINES", "")).split(",")
    explicit_native = any(engine.strip() == "deepseek-native" for engine in configured)
    source = "字面配置" if not auto or explicit_native else "自动编排"
    if not paid:
        reason = "付费搜索已关闭，执行链只使用免费引擎。"
    elif native_state == "未配置":
        reason = "未配置 DeepSeek 搜索凭据，执行链只使用免费引擎。"
    elif native_state == "模板值":
        reason = "DeepSeek 搜索 Key 仍是模板值，已跳过原生搜索。"
    elif source == "自动编排":
        reason = "付费搜索已开启，凭据可用，自动优先使用 DeepSeek 原生搜索。"
    else:
        reason = "付费搜索已开启，按 SEARCH_ENGINES 设置引擎顺序。"
    chain = "".join(
        f'<strong><code>{_t(eng)}</code></strong>' if index == 0 else
        f'<span><span aria-hidden="true">→</span> <code>{_t(eng)}</code></span>'
        for index, eng in enumerate(order)
    )
    cards = []
    now = time.monotonic()
    for eng in ("deepseek-native", *(engine for engine in ENGINE_IDS if engine != "deepseek-native")):
        in_order = eng in order
        state, hint = (native_state, native_hint) if eng == "deepseek-native" else ("可用", "")
        tone = "" if state != "可用" else " ok"
        if state == "可用" and svc._cooldowns.get(eng, 0.0) > now:
            state, tone = "冷却中", " warn"
        elif state == "可用" and last_tests.get(eng, {}).get("ok") is False:
            state, tone = "上次失败", " err"
        native = eng == "deepseek-native"
        cost = '<p class="hint">每次搜索消耗一个模型回合（按 token 计费）</p>' if native else ""
        chain_status = "✓ 在执行链中" if in_order else "未加入执行链"
        cards.append(
            f'<article class="mcp-card search-engine{" search-engine-native" if native else ""}'
            f'{" search-engine-inactive" if not in_order else ""}">'
            f'<h3>{_t(ENGINE_LABELS[eng])}</h3><div class="row-key">{eng}</div>'
            f'<div class="badges"><span class="badge{tone}">{state}</span>'
            f'<span class="badge search-membership">{chain_status}</span></div>'
            + (f'<p class="hint">{_t(hint)}</p>' if hint else "") + cost + '</article>')
    return (
        '<section class="group search-overview" aria-labelledby="search-order">'
        '<h2 id="search-order">当前执行顺序</h2>'
        f'<p class="search-chain">{chain}</p><p class="hint">{source} · {_t(reason)}</p></section>'
        '<section class="group search-paid" aria-labelledby="search-paid-title">'
        '<div><h2 id="search-paid-title">付费搜索</h2>'
        f'<span class="badge{" ok" if paid else ""}">{"已启用" if paid else "已关闭"}</span>'
        f'<p class="hint">{"关闭后，自动搜索与试搜只使用免费引擎。" if paid else "当前只使用免费引擎。"}'
        '</p></div>'
        '<form method="post" action="/panel/save?cat=Search">'
        '<input type="hidden" name="key" value="SEARCH_PAID_ENABLED">'
        f'<button type="submit" name="value" value="{str(not paid).lower()}" class="btn">'
        f'{"关闭" if paid else "启用"}付费搜索</button></form></section>'
        '<details class="cfg-group" open><summary class="cfg-summary">'
        '<span class="cfg-caret" aria-hidden="true"></span>引擎状态</summary>'
        f'<div class="search-engine-grid">{"".join(cards)}</div></details>')


def _t(value) -> str:
    return _esc(str(value or ""))
