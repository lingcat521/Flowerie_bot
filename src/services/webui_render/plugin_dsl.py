"""Plugin WebUI 受控 DSL 渲染器（零 JS 绝对红线——插件描述 UI，主进程渲染）。

安全原则：
  · 插件不得输出任意 HTML/JS——只允许结构化 dict DSL，由本模块渲染
  · 先 html.escape 再结构化标记；属性/文本/URL/样式全部受控
  · URL scheme 白名单（http/https/mailto/相对路径）；javascript:/data:/vbscript: 拒绝
  · markdown 走受限渲染（无 raw html/iframe/可执行 URL）；SVG 不出自插件
  · 组件全集（v1）：展示/表单/操作/数据/容器（见 _RENDERERS 注册表）
"""
import html
import re
from typing import Any, Dict

# 允许的 URL scheme（链接/图片 src/表单 action）
_SAFE_SCHEMES = ("http:", "https:", "mailto:")
_SAFE_ATTRS = {
    # 只允许这些表现类 attribute（内容必须 escape）
    "alt", "title", "placeholder", "min", "max", "step", "rows", "cols",
    "checked", "selected", "disabled", "readonly", "open", "href", "src",
    "value", "name", "method", "action", "type", "class", "id", "width", "height",
    "style",  # 仅渲染器受控输出（progress width 数值；值校验见 _safe_style）
}
_SAFE_STYLE_BAD = ("expression(", "url(", "javascript", "@import", "behavior")
# 明确禁止的任何以 on 开头的属性（事件处理器）
_on_attr = re.compile(r"^on[a-z]+$", re.I)


def render_plugin_dsl(dsl: Any) -> str:
    """渲染插件返回的 DSL（页面/组件树）→ HTML；任何非法/危险输入转为安全文本。"""
    if dsl is None:
        return ""
    if not isinstance(dsl, dict):
        return f"<p class=\"hint\">{html.escape(str(dsl))}</p>"
    return _render_node(dsl, depth=0)


def _render_node(node: dict, depth: int) -> str:
    if depth > 16:  # 深度防线（防递归炸弹）
        return '<p class="hint">组件嵌套过深</p>'
    ntype = str(node.get("type") or "")
    renderer = _RENDERERS.get(ntype)
    if renderer is None:
        return _text_node(ntype)
    try:
        return renderer(node, depth)
    except Exception:  # noqa: BLE001 - 渲染任何异常都降级为安全文本，绝不抛给浏览器
        return '<p class="hint">组件渲染失败</p>'


# ---------------- 安全工具 ----------------

def esc(s: Any) -> str:
    return html.escape("" if s is None else str(s))


def safe_url(u: Any, allow_relative: bool = True) -> str:
    """URL 安全校验：仅 http/https/mailto 或相对路径；危险 scheme 返回 ""。"""
    s = str(u or "").strip()
    if not s:
        return ""
    low = s.lower()
    for bad in ("javascript:", "data:", "vbscript:", "mocha:", "livescript:"):
        if low.startswith(bad):
            return ""
    if low.startswith("//"):  # protocol-relative——拒绝（可被重定向到危险协议）
        return ""
    if allow_relative and (s.startswith("/") or s.startswith("./") or s.startswith("../")
                           or "#" in s[:1] or s.startswith(".")):
        return s
    if low.startswith(_SAFE_SCHEMES):
        return s
    return ""


def safe_class(c: Any) -> str:
    """类名白名单：只允许 [a-zA-Z0-9_-] 空格分隔（禁 expression/on* 之类）。"""
    s = str(c or "")
    tokens = [t for t in re.split(r"\s+", s) if t and re.fullmatch(r"[\w\-]+", t)]
    return " ".join(tokens)


# ---------------- 展示组件 ----------------

def _text_node(txt: Any) -> str:
    return f"<p>{esc(txt)}</p>"


def _heading(node: dict, depth: int) -> str:
    lvl = min(max(int(node.get("level", 2) or 2), 1), 6)
    return f"<h{lvl + 2}>{esc(node.get('text', ''))}</h{lvl + 2}>"


def _text(node: dict, depth: int) -> str:
    return f"<p>{esc(node.get('text', ''))}</p>"


def _markdown(node: dict, depth: int) -> str:
    from src.services.webui_render.markdown_mini import render_md
    html = render_md(str(node.get("text", "") or ""))
    return html.replace('<article class="doc">', "").replace('</article>', "")


def _code(node: dict, depth: int) -> str:
    return f"<pre><code>{esc(node.get('text', ''))}</code></pre>"


def _badge(node: dict, depth: int) -> str:
    variant = node.get("variant", "info")
    v = variant if variant in ("info", "ok", "warn", "err") else "info"
    return f'<span class="badge {'info ok warn err'.split()[['info', 'ok', 'warn', 'err'].index(v)]}">{esc(node.get("text", ""))}</span>'


def _alert(node: dict, depth: int) -> str:
    variant = node.get("variant", "info")
    v = variant if variant in ("info", "ok", "warn", "err") else "info"
    return f'<div class="alert {v}">{esc(node.get("text", ""))}</div>'


def _progress(node: dict, depth: int) -> str:
    try:
        pct = max(0.0, min(100.0, float(node.get("value", 0) or 0)))
    except (TypeError, ValueError):
        pct = 0.0
    st = f'width:{pct:.0f}%'
    return (f'<div class="progress"><div class="progress-bar" style="{st}"></div>'
            f'<span class="progress-label">{pct:.0f}%</span></div>')


def _image(node: dict, depth: int) -> str:
    src = safe_url(node.get("src", ""))
    if not src:
        return '<p class="hint">图片地址不受支持</p>'
    return f'<img class="plugin-img" src="{esc(src)}" alt="{esc(node.get("alt", ""))}">'


def _divider(node: dict, depth: int) -> str:
    return "<hr>"


# ---------------- 操作组件 ----------------

def _button(node: dict, depth: int) -> str:
    # action 按钮 = 提交一个只含 action 的表单（零 JS：POST 刷新）
    action = esc(node.get("action", ""))
    if not action:
        return f'<button type="button" class="btn" disabled>{esc(node.get("text", ""))}</button>'
    kw = ""
    confirm = str(node.get("confirm", "") or "")
    if confirm:
        kw = f' title="{esc(confirm)}"'
    post = safe_url(node.get("post", "/panel/plugin-actions"), allow_relative=True) or "/panel/plugin-actions"
    return (f'<form method="post" action="{esc(post)}" '
            f'class="inline-form"{kw}>'
            f'<input type="hidden" name="plugin_action" value="{action}">'
            f'<button type="submit" class="btn">{esc(node.get("text", ""))}</button></form>')


def _link(node: dict, depth: int) -> str:
    href = safe_url(node.get("href", ""))
    if not href:
        return f'<span class="hint">{esc(node.get("text", ""))}</span>'
    return f'<a class="doc-link" href="{esc(href)}">{esc(node.get("text", ""))}</a>'


# ---------------- 数据组件 ----------------

def _table(node: dict, depth: int) -> str:
    rows = node.get("rows") or []
    if not isinstance(rows, list):
        rows = []
    headers = node.get("headers") or []
    heads = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = ""
    for r in rows:
        if isinstance(r, dict):
            body += "<tr>" + "".join(f"<td>{esc(r.get(str(h), ''))}</td>" for h in headers) + "</tr>"
        elif isinstance(r, (list, tuple)):
            body += "<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>"
    return f'<div class="table-wrap"><table class="plugin-table"><thead><tr>{heads}</tr></thead><tbody>{body}</tbody></table></div>'


def _stats(node: dict, depth: int) -> str:
    items = node.get("items") or []
    cells = "".join(
        f'<div class="stat"><div class="stat-value">{esc(i.get("value", ""))}</div>'
        f'<div class="stat-label">{esc(i.get("label", ""))}</div></div>'
        for i in items if isinstance(i, dict))
    return f'<div class="stats-grid">{cells}</div>'


def _log_lines(node: dict, depth: int) -> str:
    lines = node.get("lines") or []
    out = "".join(f'<div class="log-line">{esc(l)}</div>' for l in lines if isinstance(l, (str, int, float)))
    return f'<div class="log-box">{out}</div>'


# ---------------- 表单组件 ----------------

_FORM_DESCRIPTORS = {
    "text": ("input", "text"), "number": ("input", "number"), "password": ("input", "password"),
    "date": ("input", "date"), "color": ("input", "color"),
    "textarea": ("textarea", ""),
}
_option_re = re.compile(r"^\s*([^|]+?)\s*(?:\|(.+))?\s*$")


def _form_field(node: dict, depth: int = 0) -> str:
    ftype = str(node.get("field", "text"))
    name = str(node.get("name", ""))
    label = esc(node.get("label") or name)
    value = esc(node.get("value", ""))
    ph = esc(node.get("placeholder", ""))
    hints = f'<span class="hint">{esc(node.get("hint", ""))}</span>' if node.get("hint") else ""
    if ftype in _FORM_DESCRIPTORS:
        tag, typ = _FORM_DESCRIPTORS[ftype]
        if tag == "textarea":
            ctrl = f'<textarea name="{esc(name)}" rows="{int(node.get("rows", 4))}" placeholder="{ph}">{value}</textarea>'
        else:
            ctrl = f'<input type="{typ}" name="{esc(name)}" value="{value}" placeholder="{ph}">'
        return f'<div class="row"><label class="row-info">{label}</label><div class="row-control">{ctrl}{hints}</div></div>'
    if ftype == "select":
        opts = ""
        for o in node.get("options") or []:
            if isinstance(o, dict):
                ov, otxt = o.get("value", ""), o.get("label", o.get("value", ""))
                sel = " selected" if str(ov) == str(node.get("value", "")) else ""
            else:
                m = _option_re.match(str(o))
                ov, otxt = (m.group(1), m.group(2)) if m else (o, o)
                sel = " selected" if str(ov) == str(node.get("value", "")) else ""
            opts += f'<option value="{esc(ov)}"{sel}>{esc(otxt)}</option>'
        return f'<div class="row"><label class="row-info">{label}</label><div class="row-control"><select name="{esc(name)}">{opts}</select>{hints}</div></div>'
    if ftype == "checkbox":
        checked = " checked" if str(node.get("value", "")).lower() in ("true", "1") else ""
        return (f'<div class="row"><label class="row-info">{label}</label><div class="row-control">'
                f'<input type="hidden" name="{esc(name)}" value="false">'
                f'<input type="checkbox" name="{esc(name)}" value="true"{checked}>{hints}</div></div>')
    if ftype == "radio":
        opts = ""
        for idx, o in enumerate(node.get("options") or []):
            ov, otxt = (o.get("value"), o.get("label", o.get("value", ""))) if isinstance(o, dict) else (o, o)
            sel = " checked" if str(ov) == str(node.get("value", "")) else ""
            opts += (f'<label class="opt"><input type="radio" name="{esc(name)}" '
                     f'value="{esc(ov)}"{sel}>{esc(otxt)}</label>')
        return f'<div class="row"><label class="row-info">{label}</label><div class="row-control">{opts}{hints}</div></div>'
    if ftype in ("switch", "slider"):
        return _form_field({**node, "field": "checkbox" if ftype == "switch" else "number"}, depth)
    # 未知字段类型 → 纯文本展示（不渲染控件，安全降级）
    return f'<div class="row"><label class="row-info">{label}</label><div class="row-control"><span class="hint">未知字段类型</span></div></div>'


def _form(node: dict, depth: int) -> str:
    fields = node.get("fields") or []
    action = safe_url(node.get("action", "/panel/plugin-actions"), allow_relative=True) or "/panel/plugin-actions"
    method = "post" if str(node.get("method", "post")).lower() == "post" else "get"
    body = "".join(_form_field(f, depth + 1) for f in fields if isinstance(f, dict))
    buttons = ""
    for b in node.get("buttons") or []:
        if isinstance(b, dict) and b.get("type") in ("submit", "reset"):
            cls = "btn" + (" warn" if str(b.get("variant", "")) == "danger" else "")
            buttons += (f'<button type="{b["type"]}" class="{cls}">{esc(b.get("text", "提交"))}</button>')
    return f'<form method="{method}" action="{esc(action)}" class="plugin-form">{body}<div class="group-actions">{buttons}</div></form>'


# ---------------- 容器组件 ----------------

def _children(node: dict, depth: int) -> str:
    return "".join(_render_node(c, depth + 1) for c in (node.get("children") or []) if isinstance(c, dict))


def _container(node: dict, depth: int):
    kind = str(node.get("kind", "card"))
    inner = _children(node, depth)
    if kind == "card":
        title = esc(node.get("title", ""))
        head = f'<div class="card-title">{title}</div>' if title else ""
        return f'<div class="plugin-card">{head}{inner}</div>'
    if kind == "section":
        title = esc(node.get("title", ""))
        head = f'<h5>{title}</h5>' if title else ""
        return f'<section class="plugin-section">{head}{inner}</section>'
    if kind == "grid":
        cols = max(1, min(4, int(node.get("columns", 2) or 2)))
        return f'<div class="plugin-grid cols-{cols}">{inner}</div>'
    if kind == "stack":
        return f'<div class="plugin-stack">{inner}</div>'
    if kind == "columns":
        return f'<div class="plugin-columns">{inner}</div>'
    if kind == "accordion":
        title = esc(node.get("title", ""))
        return (f'<details class="cfg-group"><summary class="cfg-summary">{title}</summary>{inner}</details>')
    if kind == "tabs":
        # 零 JS tabs = 各 tab 区块（服务端）或锚点导航；v1 渲染为分区列表
        return f'<div class="plugin-tabs">{inner}</div>'
    return f'<div class="plugin-card">{inner}</div>'


def _card(node: dict, depth: int) -> str:
    return _container({**node, "kind": "card"}, depth)


def _tabs(node: dict, depth: int) -> str:
    return _container({**node, "kind": "tabs"}, depth)


def _grid(node: dict, depth: int) -> str:
    return _container({**node, "kind": "grid"}, depth)


_RENDERERS: Dict[str, Any] = {
    "text": _text, "heading": _heading, "markdown": _markdown, "code": _code,
    "badge": _badge, "alert": _alert, "progress": _progress, "image": _image,
    "divider": _divider,
    "button": _button, "link": _link,
    "table": _table, "stats": _stats, "log": _log_lines,
    "field": _form_field, "form": _form,
    "card": _card, "tabs": _tabs, "grid": _grid, "container": _container,
}
