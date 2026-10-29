"""Web UI 网页搜索域处理器（独立 tab）：引擎状态 / 试搜 / 连通性自检。

零 JS 服务端渲染（与 mcp_panel 同模式）：表单 POST → 重定向回 msg。
搜索服务由 main 注入 router.ai_tools.search；未注入或未开时只展示提示。
"""
from typing import Optional
from urllib.parse import quote

from aiohttp import web

from src.services.web_search import ENGINE_IDS, ENGINE_LABELS
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)

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
        engine_order = svc._engine_order() if svc is not None else list(ENGINE_IDS)
        rows = []
        for eng in ENGINE_IDS:
            label = ENGINE_LABELS.get(eng, eng)
            in_order = eng in engine_order
            badge = ('<span class="badge ok">已启用</span>' if in_order else
                     '<span class="badge">停用</span>')
            rows.append(
                f'<div class="row"><label class="row-info">'
                f'<span class="row-title">{label}</span>'
                f'<span class="row-key">{eng}</span>{badge}</label></div>')
        engines_html = "".join(rows)
        state_hint = (
            '<div class="hint">AI 搜索已开启：模型在需要实时信息时可自主调用 web_search / web_fetch。</div>'
            if enabled else
            '<div class="hint">AI 搜索未开启：在「配置管理 → 网页搜索」打开 AI_SEARCH_ENABLED 后，模型才能使用搜索工具。</div>')
        # 试搜结果（不可信外部输入：仅文本回显，不做任何渲染）
        probe = probe if probe is not None else getattr(self, "_search_probe_cache", None)
        probe_html = ""
        if probe:
            if probe.get("ok"):
                items = "".join(
                    f'<div class="row"><label class="row-info">'
                    f'<span class="row-title">{_t(s.get("title", ""))}</span>'
                    f'<span class="row-key">{_t(s.get("url", ""))}</span></label>'
                    f'<div class="row-control"><span class="hint">{_t(s.get("snippet", ""))}</span></div></div>'
                    for s in (probe.get("sources") or [])[:5])
                empty_hint = '<div class="hint">无结果</div>'
                probe_html = (
                    f'<details class="cfg-group" open><summary class="cfg-summary">'
                    f'<span class="cfg-caret" aria-hidden="true"></span>试搜结果'
                    f'（引擎 {_t(probe.get("engine", ""))}，{len(probe.get("sources") or [])} 条）</summary>'
                    + (items or empty_hint) + "</details>")
            else:
                probe_html = (
                    '<details class="cfg-group" open><summary class="cfg-summary">'
                    '<span class="cfg-caret" aria-hidden="true"></span>试搜失败</summary>'
                    f'<div class="hint">{_t(probe.get("error", ""))}</div></details>')
        # 自检结果
        test_html = ""
        if hasattr(self, "_search_test_cache") and self._search_test_cache:
            items = []
            for eng, res in self._search_test_cache.items():
                ok = res.get("ok")
                badge = '<span class="badge ok">OK</span>' if ok else '<span class="badge warn">失败</span>'
                detail = (f'{_t(res.get("error", ""))}' if not ok else
                          f'{res.get("results", 0)} 条 · {res.get("seconds", 0)}s')
                items.append(
                    f'<div class="row"><label class="row-info">'
                    f'<span class="row-title">{ENGINE_LABELS.get(eng, eng)}</span>'
                    f'<span class="row-key">{eng}</span>{badge}</label>'
                    f'<div class="row-control"><span class="hint">{detail}</span></div></div>')
            test_html = (
                '<details class="cfg-group" open><summary class="cfg-summary">'
                '<span class="cfg-caret" aria-hidden="true"></span>引擎自检结果</summary>'
                f'{"".join(items)}</details>')
        return (
            f'<h2>网页搜索（免 key 引擎）</h2>{state_hint}'
            f'<details class="cfg-group" open><summary class="cfg-summary">'
            f'<span class="cfg-caret" aria-hidden="true"></span>引擎状态</summary>'
            f'{engines_html}</details>'
            f'<details class="cfg-group"><summary class="cfg-summary">'
            f'<span class="cfg-caret" aria-hidden="true"></span>试搜 / 自检</summary>'
            '<form method="post" action="/panel/search/probe">'
            '<div class="row"><label class="row-info"><span class="row-title">试搜关键词</span></label>'
            f'<div class="row-control"><input type="text" name="query" value="{_PROBE_QUERY}">'
            '<button type="submit" class="btn">试搜</button></div></div></form>'
            '<form method="post" action="/panel/search/test">'
            '<div class="row"><label class="row-info"><span class="row-title">逐引擎自检</span>'
            '<span class="hint">（请求公共实例，勿频繁点）</span></label>'
            '<div class="row-control"><button type="submit" class="btn">开始自检</button></div>'
            '</div></form></details>'
            f'{probe_html}{test_html}')

    async def _handle_panel_search_probe(self, request: web.Request) -> web.Response:
        """试搜：用当前配置跑一次真实搜索（结果以 msg 与区块回显）。"""
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        svc = self._search_service()
        if svc is None:
            return web.HTTPFound("/panel?tab=search&err=1&msg=" + quote("搜索服务未注入（需重启）"))
        form = await request.post()
        query = str(form.get("query", "") or "").strip() or _PROBE_QUERY
        try:
            probe = await svc.search(query, max_results=5)
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
        try:
            self._search_test_cache = await svc.test_engines(_PROBE_QUERY, limit=2)
        except Exception as e:  # noqa: BLE001
            self._search_test_cache = {"all": {"ok": False, "error": f"{type(e).__name__}: {e}"}}
        return web.HTTPFound("/panel?tab=search&msg=" + quote("自检完成"))


def _t(s) -> str:
    """试搜结果文本转义（不可信外部输入，防 XSS 注入）。"""
    from src.services.webui_render.util import _esc
    return _esc(str(s or ""))
