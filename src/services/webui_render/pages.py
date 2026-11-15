"""Serve the built-in panel shell and the three authentication pages."""
from src.services.webui_render.assets import render_template
from src.services.webui_render.graphics import auth_art, flower, heading_art, icon
from src.services.webui_render.theme import PANEL_ASSET_VER
from src.services.webui_render.util import _esc

_NAV_GROUPS = (
    ("运行配置", (("config", "配置"),)),
    ("对话与记忆", (("persona", "人格"), ("knowledge", "群聊知识"),
                   ("profiles", "群友画像"), ("private", "私聊"))),
    ("QQ 与社群", (("admin", "群管理"), ("nicknames", "群昵称"), ("qzone", "QQ空间"))),
    ("工具与扩展", (("files", "文件解析"), ("search", "网页搜索"),
                   ("automation", "自动化"), ("plugins", "插件"))),
    ("面板与诊断", (("appearance", "外观"), ("logs", "日志"), ("account", "用户状态"))),
)
_TABS = tuple((key, "/panel" if key == "config" else f"/panel?tab={key}", label)
              for _, items in _NAV_GROUPS for key, label in items)
_PAGES = {
    "config": ("配置管理", "Configuration", "管理模型、连接及功能参数。"),
    "persona": ("人格管理", "Persona Studio", "编辑人格、提示词与群聊发言规则。"),
    "knowledge": ("群聊知识管理", "Knowledge Library", "按群查阅、搜索和维护梗与黑话。"),
    "profiles": ("群友画像", "Member Atlas", "查看和维护各群成员的画像。"),
    "admin": ("群管理（Bot 管理员）", "Group Guard", "向指定群或成员发起管理操作。"),
    "qzone": ("QQ空间", "Qzone Gallery", "发表说说并查看本机发布历史。"),
    "private": ("私聊", "Private Conversations", "管理私聊允许名单与用户记忆。"),
    "nicknames": ("群特色昵称", "Nameplate Workshop", "按群与人格设置机器人的称呼。"),
    "plugins": ("插件管理", "Extension Bay", "安装、配置和管理插件与扩展权限。"),
    "files": ("文件解析", "File Parsing", "控制群文件处理，或上传文件预览提取结果。"),
    "search": ("网页搜索", "Search Observatory", "配置搜索服务并测试可用性。"),
    "automation": ("自动化", "Automation Flow", "配置 AI 自动化能力及其执行条件。"),
    "appearance": ("外观美化", "Appearance Lab", "选择主题，调整背景与面板材质。"),
    "logs": ("日志", "Event Stream", "查阅页面加载时的运行日志。"),
    "account": ("用户状态", "Account Identity", "管理管理员账号并查看加载时的服务状态。"),
}


def _navigation(active):
    links = {}
    for key, url, label in _TABS:
        selected = ' aria-current="page"' if key == active else ""
        css_class = "tab active" if key == active else "tab"
        links[key] = f'<a class="{css_class}" href="{url}"{selected}>{icon(key)}<span>{label}</span></a>'
    groups = "".join(
        f'<div class="nav-group"><p class="nav-label">{label}</p>'
        f'<ul>{"".join(f"<li>{links[key]}</li>" for key, _ in items)}</ul></div>'
        for label, items in _NAV_GROUPS
    )
    return (
        f'<nav class="tabs" aria-label="管理导航">{groups}</nav>'
        f'<div class="nav-logout"><a class="tab danger" href="/panel/logout">{icon("logout")}退出</a></div>'
    )


def render_message(msg, ok):
    cls, role, symbol = ("ok", "status", "ok") if ok else ("err", "alert", "error")
    return (
        f'<div class="msg {cls}" role="{role}">{icon(symbol, "message-icon")}<span>{_esc(msg)}</span></div>'
        if msg else ""
    )


def _auth_page(page, msg, ok):
    return render_template(
        f"{page}.html", css_rev=PANEL_ASSET_VER, brand=flower(),
        decoration=auth_art(page), lock=icon("lock", "auth-lock"), msg_html=render_message(msg, ok),
    )


def render_login_page(msg: str = "") -> str:
    return _auth_page("login", msg, False)


def render_register_page(msg: str = "", ok: bool = True, closed: bool = False) -> str:
    return _auth_page("register_closed" if closed else "register", msg, ok)


def render_panel_page(*, theme_class: str, bg_rules: str, msg_html: str,
                      body_html: str, active_tab: str, panel_bg_css: str = "", glass: bool = False) -> str:
    tab = active_tab if active_tab in _PAGES else "config"
    title, eyebrow, description = _PAGES[tab]
    inline_style = f' style="--panel-bg:{panel_bg_css}"' if panel_bg_css else ""
    return render_template(
        "panel.html", css_rev=PANEL_ASSET_VER, bg_rules=bg_rules or "",
        body_class=theme_class + (" pglass" if glass else ""), inline_style=inline_style,
        brand=flower(), navigation=_navigation(tab),
        nav_current=next(label for key, _, label in _TABS if key == tab),
        page_title=title, page_eyebrow=eyebrow, page_description=description,
        page_art=heading_art(tab), page_icon=icon(tab, "heading-icon"),
        page_key=tab, msg_html=msg_html, body_html=body_html,
    )
