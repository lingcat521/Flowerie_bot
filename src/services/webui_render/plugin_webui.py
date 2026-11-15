"""宿主管理插件 Web UI 的文档、主题和导航。"""
from src.services.webui_render.assets import render_template
from src.services.webui_render.graphics import heading_art
from src.services.webui_render.pages import render_message
from src.services.webui_render.theme import PANEL_ASSET_VER, theme_body_class
from src.services.webui_render.util import _esc


def render_plugin_webui_page(plugin_name: str, page_title: str, page_desc: str,
                            dsl_html: str, error: str = "", plugin_id: str = "",
                            plugin_tabs: list = None, hook_error: str = "",
                            *, theme: str = "default") -> str:
    """将已净化的 HTML 或已转义的 DSL 放入零 JS 主题外壳。"""
    tabs = []
    for tab in plugin_tabs or []:
        active = ' class="cat active" aria-current="page"' if tab.get("active") else ' class="cat"'
        tabs.append(
            f'<a href="/panel/plugins/webui/{_esc(plugin_id)}/{_esc(tab["id"])}"{active}>'
            f'{_esc(tab["title"])}</a>'
        )
    feedback = error or (f"插件数据钩子异常：{hook_error}" if hook_error else "")
    return render_template(
        "plugin.html", css_rev=PANEL_ASSET_VER, theme_class=theme_body_class(theme),
        document_title=f"花璃 · {_esc(plugin_name)} · {_esc(page_title)}",
        plugin_name=_esc(plugin_name), page_title=_esc(page_title),
        description=f'<p class="page-description">{_esc(page_desc)}</p>' if page_desc else "",
        heading_art=heading_art("plugins"),
        tabs=f'<nav class="cats plugin-page-nav" aria-label="插件页面">{"".join(tabs)}</nav>' if tabs else "",
        feedback=render_message(feedback, False),
        content="" if error else dsl_html,
    )
