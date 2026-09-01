"""Plugin WebUI 页面渲染（受控 shell：breadcrumb + 页面头 + DSL 区域）。

渲染器（plugin_dsl）负责组件安全；本模块只组织页面壳——同样零 JS。
"""
from src.services.webui_render.util import _esc


def render_plugin_webui_page(plugin_name: str, page_title: str, page_desc: str,
                             dsl_html: str, error: str = "", plugin_id: str = "",
                             plugin_tabs: list = None) -> str:
    """插件 WebUI 页面壳（插件 tab 区内）。

    plugin_tabs: [{"id":..., "title":..., "active":bool}]——同插件多页导航（零 JS 链接）。
    """
    tabs = ""
    for t in plugin_tabs or []:
        cls = ' class="cat active"' if t.get("active") else ' class="cat"'
        tabs += (f'<a href="/panel/plugins/webui/{_esc(plugin_id)}/{_esc(t["id"])}"{cls}>'
                 f'{_esc(t["title"])}</a>')
    tabs_html = f'<nav class="cats">{tabs}</nav>' if tabs else ""
    error_html = f'<div class="alert err">{_esc(error)}</div>' if error else ""
    content = error_html if error else dsl_html
    return (
        '<div class="page">'
        f'<nav class="breadcrumb"><a href="/panel?tab=plugins" class="doc-link">插件</a>'
        f' <span>›</span> <span class="crumb-here">{_esc(plugin_name)}</span></nav>'
        f'<h1 class="page-title">{_esc(page_title)}</h1>'
        + (f'<p class="hint">{_esc(page_desc)}</p>' if page_desc else "")
        + tabs_html
        f'<div class="plugin-page">{content}</div>'
        '</div>'
    )
