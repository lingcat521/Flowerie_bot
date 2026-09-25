"""Plugin WebUI 页面壳（受控：breadcrumb + 页面头 + 内容区）。

两种内容都经过这里：
- **HTML 页面**（新）：内容已由 `webui_security.sanitize_plugin_html` 净化、模板变量已 escape；
- **DSL 页面**（旧，兼容层）：内容由 `plugin_dsl.render_plugin_dsl` 渲染（同样是受控输出）。

本模块只组织页面壳，零 JS；内容统一包在 <div class="flowerie-plugin-webui"> 作用域里，
插件 CSS 的隔离约定见 docs/plugin-webui.md（选择器应写在该类之下）。
"""
from src.services.webui_render.util import _esc


def render_plugin_webui_page(plugin_name: str, page_title: str, page_desc: str,
                             dsl_html: str, error: str = "", plugin_id: str = "",
                             plugin_tabs: list = None, hook_error: str = "",
                             mode: str = "dsl") -> str:
    """插件 WebUI 页面壳（插件 tab 区内）。

    plugin_tabs: [{"id":..., "title":..., "active":bool}]——同插件多页导航（零 JS 链接）。
    mode: "html"（真实 HTML 页面）| "dsl"（旧 DSL 兼容层）——只影响一个提示性标记。
    """
    tabs = ""
    for t in plugin_tabs or []:
        cls = ' class="cat active"' if t.get("active") else ' class="cat"'
        tabs += (f'<a href="/panel/plugins/webui/{_esc(plugin_id)}/{_esc(t["id"])}"{cls}>'
                 f'{_esc(t["title"])}</a>')
    tabs_html = f'<nav class="cats">{tabs}</nav>' if tabs else ""
    error_html = f'<div class="alert err">{_esc(error)}</div>' if error else ""
    warn_html = f'<div class="alert err">插件数据钩子异常：{_esc(hook_error)}</div>' if hook_error else ""
    badge = ('<span class="hint" title="manifest 声明了 HTML 页面文件">HTML 页面</span>'
             if mode == "html" and not error else "")
    content = error_html if error else (warn_html + dsl_html)
    return (
        '<div class="page">'
        f'<nav class="breadcrumb"><a href="/panel?tab=plugins" class="doc-link">插件</a>'
        f' <span>›</span> <span class="crumb-here">{_esc(plugin_name)}</span></nav>'
        f'<h1 class="page-title">{_esc(page_title)} {badge}</h1>'
        + (f'<p class="hint">{_esc(page_desc)}</p>' if page_desc else "")
        + tabs_html
        + f'<div class="plugin-page flowerie-plugin-webui">{content}</div>'
        '</div>'
    )
