"""插件 HTML 安全边界（任务书第 1 份 §7/§8）。

旧架构的安全前提是"插件不能输出 HTML"；迁移后插件**提供 HTML 文件**，所以边界必须换成
"HTML 必须经过净化"。本模块只做两件事，都可单测：

1. `sanitize_plugin_html()`：**白名单**净化（基于标准库 `html.parser`，不引入依赖）
   - 标签白名单：结构/表单/表格/文本类；`script/iframe/object/embed/applet/meta/link/base/style` 一律丢弃
   - 属性白名单：按标签 + 全局属性；**任何 `on*` 事件属性一律丢弃**
   - URL 属性（href/src/action/poster）：只允许 http/https/mailto 与站内相对路径；
     `javascript:` / `vbscript:` / `data:` 一律拒绝（任务书 §8 明列）
   - `style` 属性：复用旧 DSL 的黑名单口径（expression/url(/javascript/@import/behavior）
   - 注释 / DOCTYPE / 处理指令 / 未知实体：丢弃或转义
   - 嵌套深度与输出长度双上限；**每次丢弃都记进 report**（测试与运维都看得到）
2. `render_plugin_template()`：受控变量替换 `{{ name }}`
   - 值一律 HTML escape（默认安全），键不存在 → 替换为空并记入 report
   - **不做**循环/条件/表达式/函数调用（禁止 `eval`/`exec`/任意对象访问；任务书 §7）
"""
import html
import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Tuple

# ---- 标签白名单（结构 / 表单 / 表格 / 文本；不含任何可执行或可外链资源加载的标签） ----
ALLOWED_TAGS = frozenset({
    "div", "span", "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "dl", "dt", "dd",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "colgroup", "col",
    "form", "label", "input", "select", "option", "optgroup", "textarea", "button", "fieldset", "legend",
    "a", "img", "pre", "code", "blockquote", "hr", "br", "strong", "em", "b", "i", "u", "s", "small",
    "nav", "section", "article", "header", "footer", "main", "aside", "figure", "figcaption",
    "details", "summary", "mark", "time", "abbr", "sup", "sub", "kbd", "samp", "var", "address",
})
VOID_TAGS = frozenset({"br", "hr", "img", "input", "col"})

# ---- 属性白名单 ----
GLOBAL_ATTRS = frozenset({"class", "id", "title", "style", "dir", "lang"})
TAG_ATTRS: Dict[str, frozenset] = {
    "a": frozenset({"href", "target", "rel"}),
    "img": frozenset({"src", "alt", "width", "height"}),
    "form": frozenset({"method", "action", "enctype"}),
    "input": frozenset({"type", "name", "value", "placeholder", "required", "checked", "disabled",
                        "readonly", "min", "max", "step", "maxlength", "size", "pattern", "accept"}),
    "select": frozenset({"name", "multiple", "required", "size"}),
    "option": frozenset({"value", "selected", "disabled", "label"}),
    "optgroup": frozenset({"label", "disabled"}),
    "textarea": frozenset({"name", "rows", "cols", "placeholder", "required", "readonly", "maxlength"}),
    "button": frozenset({"type", "name", "value", "disabled"}),
    "label": frozenset({"for"}),
    "table": frozenset({"summary"}),
    "th": frozenset({"colspan", "rowspan", "scope", "abbr"}),
    "td": frozenset({"colspan", "rowspan", "headers"}),
    "col": frozenset({"span"}),
    "colgroup": frozenset({"span"}),
    "details": frozenset({"open"}),
    "time": frozenset({"datetime"}),
    "img_": frozenset(),
}
URL_ATTRS = frozenset({"href", "src", "action", "poster", "formaction"})
SAFE_SCHEMES = ("http:", "https:", "mailto:")
SAFE_STYLE_BAD = ("expression(", "url(", "javascript", "@import", "behavior", "\\")
_ON_ATTR = re.compile(r"^on[a-z]+$", re.I)
_ATTR_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_:.-]{0,63}$")

#: 需要连内容一起丢弃的标签（必须成对出现，靠闭合标签退出抑制区）
SUPPRESS_TAGS = frozenset({"script", "style", "iframe", "object", "template", "svg",
                           "math", "noscript", "applet", "frameset"})
#: 只丢标签本身（void / 无内容区）：绝不能进抑制计数，否则后面的正文会被一起吞掉
DROP_TAGS = frozenset({"meta", "base", "frame", "param", "source", "track", "embed"})

MAX_DEPTH = 32
MAX_HTML_BYTES = 512 * 1024
MAX_OUT_CHARS = 1024 * 1024


class PluginHtmlError(ValueError):
    """净化阶段的硬错误（超大/不可解析）。"""


def _safe_url(value: Any, *, allow_relative: bool = True, allow_absolute: bool = True) -> str:
    """URL 属性校验：危险 scheme 一律返回 ""。

    `allow_absolute=False` 用于**表单提交地址**（action/formaction）：只允许站内相对路径，
    防止插件把面板表单（含登录态/token）提交到外部站点。
    """
    s = html.unescape(str(value or "")).strip()
    if not s:
        return ""
    low = s.lower().replace("\t", "").replace("\n", "").replace("\r", "")
    # 去掉控制字符后仍以危险 scheme 开头 → 拒绝（含 "java\tscript:" 这类绕过）
    for bad in ("javascript:", "vbscript:", "data:", "file:", "blob:"):
        if low.startswith(bad):
            return ""
    if low.startswith(("http:", "https:", "mailto:")):
        return html.escape(s, quote=True) if allow_absolute else ""
    if allow_relative and (s.startswith("/") or s.startswith("#") or s.startswith("?")) and not s.startswith("//"):
        return html.escape(s, quote=True)
    if allow_relative and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", s):
        return html.escape(s, quote=True)   # 相对路径（pages/x.html）
    return ""


def _safe_style(value: Any) -> str:
    s = str(value or "")
    low = s.lower()
    if any(bad in low for bad in SAFE_STYLE_BAD):
        return ""
    if "{" in s or "}" in s or "<" in s or ">" in s:
        return ""
    return html.escape(s, quote=True)


class _Sanitizer(HTMLParser):
    def __init__(self, style_prefix: str = "") -> None:
        super().__init__(convert_charrefs=False)
        self.style_prefix = style_prefix
        self.out: List[str] = []
        self.report: List[str] = []
        self.depth = 0
        self._open: List[str] = []
        self._suppress_depth = 0     # 丢弃 <script>/<style> 等标签时，连内容一起丢

    # ---- 标签 ----
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in SUPPRESS_TAGS:
            # 连内容一起丢：靠对应的闭合标签退出抑制区（void 标签绝不能走这里）
            self._suppress_depth += 1
            self.report.append("drop_tag:%s" % tag)
            return
        if tag == "link":
            rendered = self._render_stylesheet_link(attrs)
            if rendered:
                self.out.append(rendered)
            return
        if tag in DROP_TAGS:
            self.report.append("drop_tag:%s" % tag)
            return
        if tag not in ALLOWED_TAGS:
            self.report.append("drop_tag:%s" % tag)
            return
        if self.depth >= MAX_DEPTH:
            self.report.append("depth_limit:%s" % tag)
            return
        rendered = self._render_attrs(tag, attrs)
        self.out.append("<%s%s>" % (tag, rendered))
        if tag not in VOID_TAGS:
            self._open.append(tag)
            self.depth += 1

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if tag in ALLOWED_TAGS and tag not in VOID_TAGS:
            if self.depth >= MAX_DEPTH:
                return
            self.out.append("<%s%s>" % (tag, self._render_attrs(tag, attrs)))
            return
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in SUPPRESS_TAGS:
            if self._suppress_depth:
                self._suppress_depth -= 1
            return
        if tag not in ALLOWED_TAGS or tag in VOID_TAGS:
            return
        if tag in self._open:
            while self._open:
                top = self._open.pop()
                self.depth = max(0, self.depth - 1)
                self.out.append("</%s>" % top)
                if top == tag:
                    break

    def _render_stylesheet_link(self, attrs) -> str:
        """<link> 特例：只放行"本插件 static 下的样式表"，其余（外链/其他 rel）一律丢弃。

        为什么需要它：任务书 §13 允许插件自带 CSS；但外链样式表是数据外泄面，
        所以既要求同源、又要求落在 **本插件** 的 /static/ 前缀下。
        """
        rel = href = ""
        for name, value in attrs:
            key = str(name or "").lower()
            if key == "rel":
                rel = str(value or "").lower().strip()
            elif key == "href":
                href = str(value or "").strip()
        if rel != "stylesheet":
            self.report.append("drop_tag:link(rel=%s)" % (rel or "?"))
            return ""
        safe = _safe_url(href, allow_relative=True, allow_absolute=False)
        prefix = self.style_prefix
        if not safe or not prefix or not safe.startswith(prefix):
            self.report.append("drop_url:href@link")
            return ""
        return '<link rel="stylesheet" href="%s">' % safe

    def _render_attrs(self, tag, attrs) -> str:
        allowed = GLOBAL_ATTRS | TAG_ATTRS.get(tag, frozenset())
        parts = []
        for name, value in attrs:
            name = str(name or "").lower()
            if not _ATTR_NAME.match(name):
                self.report.append("drop_attr:%s@%s" % (name, tag))
                continue
            if _ON_ATTR.match(name):
                self.report.append("drop_event_attr:%s@%s" % (name, tag))
                continue
            if name not in allowed:
                self.report.append("drop_attr:%s@%s" % (name, tag))
                continue
            if name == "style":
                safe = _safe_style(value)
                if not safe:
                    self.report.append("drop_style@%s" % tag)
                    continue
                parts.append('style="%s"' % safe)
                continue
            if name in URL_ATTRS:
                # 表单提交地址只允许站内（防把带登录态的表单 POST 到外部站点）
                safe = _safe_url(value, allow_relative=True,
                                 allow_absolute=name not in ("action", "formaction"))
                if not safe:
                    self.report.append("drop_url:%s@%s" % (name, tag))
                    continue
                parts.append('%s="%s"' % (name, safe))
                continue
            parts.append('%s="%s"' % (name, html.escape(html.unescape(str(value or "")), quote=True)))
        return (" " + " ".join(parts)) if parts else ""

    # ---- 文本与其它 ----
    def handle_data(self, data):
        if self._suppress_depth:
            return
        self.out.append(html.escape(data, quote=False))

    def handle_entityref(self, name):
        if self._suppress_depth:
            return
        self.out.append(html.escape(html.unescape("&%s;" % name), quote=False))

    def handle_charref(self, name):
        if self._suppress_depth:
            return
        self.out.append(html.escape(html.unescape("&#%s;" % name), quote=False))

    def handle_comment(self, data):
        self.report.append("drop_comment")

    def handle_decl(self, decl):
        self.report.append("drop_decl")

    def handle_pi(self, data):
        self.report.append("drop_pi")

    def unknown_decl(self, data):
        self.report.append("drop_unknown_decl")


def sanitize_plugin_html(raw: Any, *, style_prefix: str = "") -> Tuple[str, List[str]]:
    """净化插件 HTML：返回 (安全 HTML, 丢弃项报告)。任何异常都降级为空串 + 报告。

    style_prefix：允许出现的 <link rel="stylesheet"> 前缀（通常是
    /panel/plugins/webui/<pid>/static/）。为空则任何样式表链接都会被丢弃。
    插件 HTML 可以是整页（<html>/<head>/<body> 会被剥掉，只保留内容）或片段。
    """
    text = "" if raw is None else str(raw)
    if len(text.encode("utf-8", errors="ignore")) > MAX_HTML_BYTES:
        raise PluginHtmlError("HTML 超过 %d KB 上限" % (MAX_HTML_BYTES // 1024))
    parser = _Sanitizer(style_prefix=style_prefix)
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:  # noqa: BLE001 - 解析异常不允许把原文交出去
        return "", ["parse_error:%s" % type(exc).__name__]
    out = "".join(parser.out)
    if len(out) > MAX_OUT_CHARS:
        return out[:MAX_OUT_CHARS], parser.report + ["truncated"]
    return out, parser.report


_VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]{0,63})\s*\}\}")


def render_plugin_template(template: str, context: Dict[str, Any]) -> Tuple[str, List[str]]:
    """受控变量替换：`{{ key }}` → HTML escape 后的值；未知键替换为空并记入报告。

    只做**扁平字典**查值：不支持表达式、循环、条件、函数调用或属性链以外的访问。
    """
    missing: List[str] = []
    ctx = {str(k): ("" if v is None else str(v)) for k, v in (context or {}).items()}

    def _sub(match: re.Match) -> str:
        key = match.group(1)
        if key in ctx:
            return html.escape(ctx[key], quote=True)
        missing.append(key)
        return ""

    return _VAR_RE.sub(_sub, template or ""), missing


# ---------------------------------------------------------------- 插件 CSS（任务书 §13）
MAX_CSS_BYTES = 256 * 1024
_CSS_IMPORT_RE = re.compile(r"@import[^;]*;?", re.I)
_CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)([^)'\"]*)\1\s*\)", re.I)
_CSS_DANGEROUS = ("expression(", "javascript:", "vbscript:", "behavior:", "-moz-binding")


def sanitize_plugin_css(raw: Any) -> Tuple[str, List[str]]:
    """插件 CSS 净化：去掉能外链/执行/越界的构造，返回 (css, 报告)。

    规则（任务书 §8/§13）：
    - 删除 `@import`（外部样式加载 → 数据外泄面）
    - `url(...)` 只允许**站内相对路径**（禁止 http(s)://、//、data:、javascript:）
    - 删除 `expression(` / `javascript:` / `behavior:` / `-moz-binding` 等历史执行面
    - 大小上限；不做语法解析（CSS 由浏览器解释，本函数只做危险构造剔除）
    """
    text = "" if raw is None else str(raw)
    if len(text.encode("utf-8", errors="ignore")) > MAX_CSS_BYTES:
        raise PluginHtmlError("CSS 超过 %d KB 上限" % (MAX_CSS_BYTES // 1024))
    report: List[str] = []
    css = _CSS_IMPORT_RE.sub(lambda m: (report.append("drop_import"), "")[1], text)

    def _url_sub(match: "re.Match") -> str:
        url = (match.group(2) or "").strip()
        low = url.lower()
        if (not url or low.startswith(("http:", "https:", "//", "data:", "javascript:", "vbscript:", "file:"))
                or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url)):
            report.append("drop_url:%s" % low[:24])
            return "none"
        return "url('%s')" % url.replace("'", "")

    css = _CSS_URL_RE.sub(_url_sub, css)
    for bad in _CSS_DANGEROUS:
        if bad in css.lower():
            report.append("drop_css_construct:%s" % bad)
            css = re.sub(re.escape(bad), "", css, flags=re.I)
    if "</style" in css.lower():
        report.append("drop_style_close")
        css = re.sub(r"</style", "", css, flags=re.I)
    return css, report
