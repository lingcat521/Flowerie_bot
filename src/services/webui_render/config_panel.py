"""webui_render 配置页：分组表单 + MCP 卡片编辑器（零 JS）。"""

from src.services.webui_render.category_constants import (  # 单源
    CATEGORY_LABELS as _DEFAULT_LABELS,
)
from src.services.webui_render.category_constants import (
    CATEGORY_ORDER as _DEFAULT_ORDER,
)
from src.services.webui_render.util import _esc

# ---------- 花语记忆：模型配置链状态徽标（零 JS；未配置/缺配置/已配置） ----------
_BLOSSOM_MODEL_KEYS = {
    "BLOSSOM_MEMORY_EMBEDDING_MODEL": ("BLOSSOM_MEMORY_EMBEDDING_ENABLED",
                                       "BLOSSOM_MEMORY_EMBEDDING_API_URL"),
    "BLOSSOM_MEMORY_RERANKER_MODEL": ("BLOSSOM_MEMORY_RERANKER_ENABLED",
                                      "BLOSSOM_MEMORY_RERANKER_API_URL"),
}


def _blossom_model_status_badge(cfgs, c: dict) -> str:
    """模型/API 配置行的链状态：未启用 / ⚠️ 缺模型或地址 / 已配置。"""
    key = c["key"]
    if key not in _BLOSSOM_MODEL_KEYS:
        return ""
    sub_switch, url_key = _BLOSSOM_MODEL_KEYS[key]
    cur = {x["key"]: str(x.get("current") or "") for x in cfgs}
    enabled = cur.get(sub_switch, "false").lower() in ("true", "1")
    if not enabled:
        return '<span class="badge">未启用</span>'
    model_ok = bool(cur.get(key, "").strip())
    url_ok = bool(cur.get(url_key, "").strip())
    if model_ok and url_ok:
        return '<span class="badge ok">已配置</span>'
    return '<span class="badge warn">⚠️ 缺模型或地址</span>'


def render_config_sections(configs, active_cat: str = "all", mcp_edit=None, mcp_test_status=None, mcp_tool_counts=None,
                           category_order=None, category_labels=None) -> str:
    """按分类渲染配置分组表单，顶部带分类导航（点某个分类只看那一类，避免全部堆在一屏）。

    active_cat: "all" 显示全部分类；否则只显示该分类。纯 HTML + 链接跳转，零 JS。
    category_order/labels: 可选注入（测试解耦）；缺省用 ConfigService 常量（生产行为不变）。
    """
    order = category_order if category_order is not None else _DEFAULT_ORDER
    labels = category_labels if category_labels is not None else _DEFAULT_LABELS
    by_cat: dict = {}
    for c in configs:
        by_cat.setdefault(c["category"], []).append(c)
    # 有内容的分类（按固定顺序）
    cats = [cat for cat in order if by_cat.get(cat)]
    if active_cat not in ("all", "") and active_cat not in by_cat:
        active_cat = "all"
    nav = _render_cat_nav(active_cat, cats, labels)
    shown_cats = [active_cat] if active_cat in by_cat else cats
    sections = []
    for cat in shown_cats:
        label = labels.get(cat, cat)
        action = f"/panel/save?cat={_esc(active_cat)}" if active_cat in by_cat else "/panel/save"
        mcp_raw = None
        rows_html = []
        for c in by_cat[cat]:
            if c["key"] == "MCP_SERVERS":
                mcp_raw = c.get("current", "")  # MCP_SERVERS 单独渲染为表单编辑器
                continue
            # 高级记忆层级门控（零 JS）：
            # 总开关 OFF → 子开关与全部配置不渲染；子开关 OFF → 对应模型配置不渲染
            if c["key"] in _BLOSSOM_SUB_SWITCH_KEYS and not _blossom_on(by_cat[cat]):
                continue
            if c["key"] in _BLOSSOM_SUB_CONFIG_KEYS and not _blossom_sub_switch_on(by_cat[cat], c["key"]):
                continue
            extra = _blossom_model_status_badge(by_cat[cat], c)
            rows_html.append(_render_config_row(c, extra_badges=extra))

        body = (
            f'<form method="post" action="{action}">{"".join(rows_html)}'
            '<div class="group-actions"><button type="submit" class="btn">保存本组</button></div>'
            '</form>'
            + (render_mcp_editor(mcp_raw, edit_index=mcp_edit, mcp_test_status=mcp_test_status, mcp_tool_counts=mcp_tool_counts) if mcp_raw is not None else "")
        )
        # 折叠（<details>/<summary> 原生，零 JS）+ 开关状态徽标。
        # 全部默认展开（open）——配置开箱即见；用户可手动收起单个分组（details 原生）。
        # 花语记忆总开关 OFF 时子开关/模型配置由上方门控不渲染（qwq 不变）。
        summary_status = _cat_status_badge(by_cat[cat])
        section = (
            f'<details class="cfg-group" open>'
            f'<summary class="cfg-summary">{_esc(label)}{summary_status}</summary>'
            + body
            + '</details>'
        )
        sections.append(section)
    return nav + "\n" + "\n".join(sections)


# 子开关（总开关 ON 时渲染）
_BLOSSOM_SUB_SWITCH_KEYS = {
    "BLOSSOM_MEMORY_EMBEDDING_ENABLED", "BLOSSOM_MEMORY_RERANKER_ENABLED",
    "BLOSSOM_MEMORY_EXTRACT_ENABLED", "BLOSSOM_MEMORY_RETRIEVAL_ENABLED",
}
# 子开关 → 其专属配置键（子开关 OFF 时不渲染）
# 模型/API 配置：始终渲染（用户需先看见模型才能启用功能——不随子开关隐藏）
_BLOSSOM_SUB_CONFIG_KEYS = {}
# 总开关配置键（始终渲染）
_BLOSSOM_ADVANCED_KEYS = frozenset()


def _blossom_on(cfgs) -> bool:
    """高级记忆总开关（渲染门控）。"""
    for c in cfgs:
        if c["key"] == "BLOSSOM_MEMORY_ENABLED":
            return str(c.get("current") or "").lower() in ("true", "1")
    return False


def _blossom_sub_switch_on(cfgs, config_key: str) -> bool:
    """子开关状态（渲染门控）：未列出归属的键仅受总开关控制。"""
    sw = _BLOSSOM_SUB_CONFIG_KEYS.get(config_key)
    if sw is None:
        return True
    for c in cfgs:
        if c["key"] == sw:
            return str(c.get("current") or "").lower() in ("true", "1")
    return False


def _cat_status_badge(cfgs) -> str:
    """分类内 *_ENABLED 开关徽标（ON/OFF；无开关分类无徽标）。"""
    badges = []
    for c in cfgs:
        if c["key"].endswith("_ENABLED") and c.get("type") == "bool":
            on = str(c.get("current") or "").lower() in ("true", "1")
            badges.append(f'<span class="badge{" warn" if not on else ""}">{_esc(c["key"].replace("_", " ").lower())}: {"ON" if on else "OFF"}</span>')
    return f'<span class="badges">{"".join(badges)}</span>' if badges else ""

def render_mcp_editor(raw: str, default_timeout: int = 15, edit_index=None, mcp_test_status=None, mcp_tool_counts=None) -> str:
    """把 MCP_SERVERS 的 JSON 渲染成卡片式列表（每个 server 一张卡，零 JS）。

    默认显示摘要卡 + 按钮（启用/停用、测试、编辑、删除）；点"编辑"（?cat=MCP&edit=i）
    时该 server 渲染为编辑表单。添加服务器表单始终在底部。
    """
    import json
    servers = []
    raw = (raw or "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                servers = [x for x in data if isinstance(x, dict)]
        except json.JSONDecodeError:
            servers = []
    blocks = []
    for i, s in enumerate(servers):
        if edit_index is not None and i == edit_index:
            blocks.append(_mcp_server_form(i, s, "编辑", default_timeout))
        else:
            blocks.append(_mcp_server_card(i, s, (mcp_test_status or {}).get(s.get("name")), tool_count=(mcp_tool_counts or {}).get(s.get("name"))))
    blocks.append(_mcp_server_form(None, {}, "添加", default_timeout))
    return '<div class="mcp-editor">' + "".join(blocks) + "</div>"

def _mcp_server_card(i, s, test_status=None, tool_count=None) -> str:
    """服务器摘要卡 + 操作按钮（启用/停用、测试、编辑、删除）。"""
    name = _esc(s.get("name", ""))
    url = _esc(s.get("url", ""))
    # 工具数量：优先运行时已同步数；无则用配置白名单数；留空=放行所有
    tools_allow = str(s.get("allowed_tools", "") or "").strip()
    if tool_count is not None:
        tools_label = f"{tool_count} 个工具"
    elif tools_allow:
        tools_label = f"{len([t for t in tools_allow.split(',') if t.strip()])} 个工具"
    else:
        tools_label = "全部工具"
    transport = "sse" if url.lower().startswith("sse://") or "/sse" in url.lower() else "streamable-http"
    enabled = bool(s.get("enabled", True))
    status = '<span class="badge">已启用</span>' if enabled else '<span class="badge warn">已停用</span>'
    toggle = "停用" if enabled else "启用"
    return (
        '<div class="mcp-card">'
        f'<div class="mcp-card-head"><b>{_esc(name)}</b>{status}</div>'
        f'<div class="mcp-card-meta">{_esc(transport)} · {_esc(tools_label)}</div>'
        f'<div class="mcp-card-url">{_esc(url)}</div>'
        + (_mcp_test_status_html(test_status) if test_status else "")
        + '<div class="actions-row">'
        # 每个操作是独立、紧凑的按钮（toggle 与 test 不再塞进同一个 form），窄屏也横向不竖排
        + '<form method="post" action="/panel/mcp/edit" class="inline-form">'
        + f'<input type="hidden" name="mcp_index" value="{i}">'
        + f'<button type="submit" name="mcp_action" value="toggle" class="btn small">{toggle}</button>'
        + '</form>'
        + '<form method="post" action="/panel/mcp/edit" class="inline-form">'
        + f'<input type="hidden" name="mcp_index" value="{i}">'
        + '<button type="submit" name="mcp_action" value="test" class="btn small">测试</button>'
        + '</form>'
        + f'<a class="btn small" href="/panel?cat=MCP&edit={i}">编辑</a>'
        + '<form method="post" action="/panel/mcp/edit" class="inline-form">'
        + f'<input type="hidden" name="mcp_index" value="{i}">'
        + '<button type="submit" name="mcp_action" value="delete" class="btn small danger">删除</button>'
        + '</form>'
        + '</div></div>'
    )

def _mcp_test_status_html(test_status) -> str:
    ok, msg = test_status
    cls = "ok" if ok else "err"
    mark = "✔" if ok else "✖"
    return f'<div class="mcp-card-test {cls}">{mark} {_esc(msg)}</div>'

def _mcp_server_form(index, s, title, default_timeout: int = 15) -> str:
    idx = "" if index is None else str(index)
    name = _esc(s.get("name", ""))
    url = _esc(s.get("url", ""))
    tools = _esc(s.get("allowed_tools", ""))
    timeout = _esc(s.get("timeout", default_timeout))
    checked = " checked" if s.get("enabled", True) else ""
    hint = '<span class="hint">名称唯一；地址支持 http(s)/SSE；工具白名单逗号分隔（留空=放行所有工具）；超时秒</span>'
    delete_btn = ('<button type="submit" name="mcp_action" value="delete" class="btn danger">删除</button>'
                  if index is not None else "")
    submit_label = "保存" if index is not None else "添加服务器"
    return (
        f'<fieldset class="group"><legend>{_esc(title)} MCP 服务器</legend>'
        '<form method="post" action="/panel/mcp/edit">'
        f'<input type="hidden" name="mcp_index" value="{idx}">'
        '<div class="row"><label class="row-info"><span class="row-title">名称</span><span class="row-key">name</span></label>'
        f'<div class="row-control"><input type="text" name="mcp_name" value="{name}" placeholder="如 github" required></div></div>'
        '<div class="row"><label class="row-info"><span class="row-title">地址</span><span class="row-key">url</span></label>'
        f'<div class="row-control"><input type="text" name="mcp_url" value="{url}" placeholder="https://mcp.example.com/mcp" required></div></div>'
        '<div class="row"><label class="row-info"><span class="row-title">工具白名单</span><span class="row-key">allowed_tools</span></label>'
        f'<div class="row-control"><input type="text" name="mcp_tools" value="{tools}" placeholder="web_search, fetch_page（逗号分隔，留空=放行所有）"></div></div>'
        '<div class="row"><label class="row-info"><span class="row-title">超时（秒）</span><span class="row-key">timeout</span></label>'
        f'<div class="row-control"><div class="range-row"><input type="number" name="mcp_timeout" min="1" max="3600" value="{timeout}" style="max-width:140px"></div></div></div>'
        '<div class="row"><label class="row-info"><span class="row-title">启用</span><span class="row-key">enabled</span></label>'
        f'<div class="row-control"><input type="checkbox" name="mcp_enabled" value="1"{checked}></div></div>'
        f'<p class="hint">{hint}</p>'
        '<div class="group-actions">'
        f'<button type="submit" name="mcp_action" value="save" class="btn">{submit_label}</button>'
        + delete_btn +
        '</div></form></fieldset>'
    )

def _render_cat_nav(active: str, cats, labels) -> str:
    """顶部分类导航（pill 链接，响应式换行）。"""
    links = [f'<a class="cat{" active" if active in ("all", "") else ""}" href="/panel?cat=all">全部</a>']
    for cat in cats:
        label = labels.get(cat, cat)
        active_cls = " active" if cat == active else ""
        links.append(f'<a class="cat{active_cls}" href="/panel?cat={_esc(cat)}">{_esc(label)}</a>')
    return '<nav class="cats">' + "".join(links) + '</nav>'

def _render_config_row(c: dict, extra_badges: str = "") -> str:
    key = c["key"]
    cur = c.get("current") or ""
    badges = []
    if extra_badges:
        badges.append(extra_badges)
    if c.get("secret"):
        badges.append('<span class="badge">密钥</span>')
    if not c.get("hot_reload"):
        badges.append('<span class="badge warn">需重启</span>')
    badges_html = f'<span class="badges">{"".join(badges)}</span>' if badges else ""
    # 模型/API 行内联「测」按钮（零 JS：独立表单 POST → 结果经 msg 回显）
    ping_target = {"BLOSSOM_MEMORY_EMBEDDING_MODEL": "embedding",
                   "BLOSSOM_MEMORY_RERANKER_MODEL": "reranker"}.get(key)
    if ping_target:
        control_suffix = (
            f'<form method="post" action="/panel/test/model" class="inline-form">'
            f'<input type="hidden" name="target" value="{ping_target}">'
            f'<button type="submit" class="btn-mini">测</button></form>')
    else:
        control_suffix = ""
    ctype = c["type"]
    if ctype == "bool":
        checked = ' checked' if str(cur).lower() in ("true", "1") else ""
        control = (f'<input type="hidden" name="{key}" value="false">'
                   f'<input type="checkbox" name="{key}" value="true"{checked}>')
    elif ctype == "secret":
        control = (f'<input type="password" name="{key}" placeholder="留空 = 不修改" autocomplete="new-password">'
                   f'<span class="masked">当前：{_esc(cur) if cur else "未设置"}（不显示明文）</span>')
    elif ctype in ("int", "float"):
        attrs = ""
        if c.get("min") is not None:
            attrs += f' min="{c["min"]}"'
        if c.get("max") is not None:
            attrs += f' max="{c["max"]}"'
        attrs += f' step="{c.get("step", 1)}"'
        control = f'<input type="number" name="{key}" value="{_esc(cur)}"{attrs}>'
    elif ctype in ("textarea", "json"):
        rows = c.get("rows", 6)
        control = f'<textarea name="{key}" rows="{rows}">{_esc(cur)}</textarea>'
    elif c.get("options"):
        opts = "".join(
            f'<option value="{_esc(o)}"{" selected" if str(o).lower() == str(cur).lower() else ""}>{_esc(o)}</option>'
            for o in c["options"]
        )
        control = f'<select name="{key}">{opts}</select>'
    else:
        control = f'<input type="text" name="{key}" value="{_esc(cur)}">'
    hint = ""
    if ctype == "secret":
        hint = '<span class="hint">密钥不显示明文；留空提交不会覆盖现有值</span>'
    elif not c.get("hot_reload"):
        hint = '<span class="hint">已保存到 .env，部分配置将在服务器重启后生效</span>'
    return (
        '<div class="row">'
        f'<label class="row-info"><span class="row-title">{_esc(c["description"])}</span>'
        f'<span class="row-key">{_esc(key)}</span>{badges_html}</label>'
        f'<div class="row-control">{control}{control_suffix}{hint}</div>'
        '</div>'
    )

