"""webui_render 页面壳：登录 / 注册 / 面板页。

HTML 本体在 templates/*.html（真实文件，标准 HTML，改结构不用碰 Python）；
本模块只负责准备数据并做 {{占位符}} 替换。
"""
from src.services.webui_render.assets import render_template
from src.services.webui_render.theme import PANEL_ASSET_VER
from src.services.webui_render.util import _esc

_TABS = [
    ("config", "/panel", "配置"),
    ("persona", "/panel?tab=persona", "人格"),
    ("knowledge", "/panel?tab=knowledge", "群聊知识"),
    ("nicknames", "/panel?tab=nicknames", "群昵称"),
    ("plugins", "/panel?tab=plugins", "插件"),
    ("appearance", "/panel?tab=appearance", "外观"),
    ("logs", "/panel?tab=logs", "日志"),
    ("account", "/panel?tab=account", "用户状态"),
]

_TITLES = {
    "config": "配置管理", "appearance": "外观美化", "logs": "日志",
    "persona": "人格管理", "knowledge": "群聊知识管理", "account": "用户状态",
    "plugins": "插件管理", "nicknames": "群特色昵称",
}


def render_login_page(msg: str = "") -> str:
    msg_html = (f'<div class="err" style="color:var(--err);font-size:13px;margin-bottom:10px">'
                f'{_esc(msg)}</div>') if msg else ""
    return render_template("login.html", css_rev=PANEL_ASSET_VER, msg_html=msg_html)


def render_register_page(msg: str = "", ok: bool = True, closed: bool = False) -> str:
    cls = "ok" if ok else "err"
    style = "color:var(--ok)" if ok else "color:var(--err)"
    msg_html = f'<div class="{cls}" style="{style};font-size:13px;margin:10px 0">{_esc(msg)}</div>' if msg else ""
    # Bootstrap Lock：系统已初始化 → 公开注册入口永久关闭（对应模板不含表单，防绕过）
    name = "register_closed.html" if closed else "register.html"
    return render_template(name, css_rev=PANEL_ASSET_VER, msg_html=msg_html)


def render_panel_page(*, theme_class: str, bg_rules: str, msg_html: str,
                      body_html: str, active_tab: str, panel_bg_css: str = "", glass: bool = False) -> str:
    tab_html = "".join(
        f'<a class="tab{" active" if tab == active_tab else ""}" href="{url}">{label}</a>'
        for tab, url, label in _TABS
    )
    # panel_bg_css：服务端算好的具体 rgba(r,g,b,a) 卡片背景（保证兼容）；为空则由 CSS 主题接管
    inline_style = f' style="--panel-bg:{panel_bg_css}"' if panel_bg_css else ""
    body_class = theme_class + (" pglass" if glass else "")
    return render_template(
        "panel.html",
        css_rev=PANEL_ASSET_VER,
        bg_rules=bg_rules or "",
        body_class=body_class,
        inline_style=inline_style,
        tabs=tab_html,
        page_title=_TITLES.get(active_tab, "配置管理"),
        msg_html=msg_html,
        body_html=body_html,
    )
