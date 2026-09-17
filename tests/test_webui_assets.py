"""面板静态资产与模板：确保「CSS/模板是真实文件」这条路线不退化。

背景：面板的 CSS 与页面壳从 Python 字符串搬到了真实文件
（static/panel.css、templates/*.html）。这类改动最容易出的问题是
「文件没被打进发布包」或「模板占位符忘了替换」，所以单独用一组测试盯住。
"""
import re

from src.services.webui_render.assets import asset_path, read_asset, template_path
from src.services.webui_render.pages import (
    render_login_page,
    render_panel_page,
    render_register_page,
)
from src.services.webui_render.theme import PANEL_CSS, PANEL_CSS_REV, panel_asset_body


def test_static_css_exists_and_is_real_file():
    """CSS 必须是磁盘上的真实文件（不是 Python 字符串）。"""
    assert asset_path("panel.css").is_file()
    css = read_asset("panel.css")
    assert len(css) > 8000                      # 面板样式规模
    assert "{{THEME_VARS}}" in css               # 占位符保留在文件里，由 Python 注入主题变量


def test_panel_css_placeholder_is_substituted():
    """PANEL_CSS 里不能残留占位符（否则主题变量整块丢失）。"""
    assert "{{THEME_VARS}}" not in PANEL_CSS
    assert ".theme-default {" in PANEL_CSS        # 主题变量已注入（theme_css_block 输出）
    assert PANEL_CSS_REV and len(PANEL_CSS_REV) == 8


def test_panel_css_has_key_layout_rules():
    """曾经踩过的布局坑，规则必须还在。"""
    for rule in (
        "grid-template-columns:minmax(180px,260px)",   # .row 自适应两列
        "table{width:100%",                            # 表格不再塌缩
        "pre{white-space:pre-wrap",                    # 示例文本不溢出
        ".nick-grid{",                                 # 群昵称卡片网格
        "w-gid",                                       # 宽度工具类
        "@media (max-width:860px)",                    # 平板断点
    ):
        assert rule in PANEL_CSS, rule


def test_templates_exist():
    for name in ("panel.html", "login.html", "register.html", "register_closed.html"):
        assert template_path(name).is_file(), name


def test_pages_link_stylesheet_and_leave_no_placeholder():
    """页面必须外链 CSS，且占位符全部替换完毕。"""
    pages = {
        "login": render_login_page("用户名或密码错误"),
        "register": render_register_page("ok"),
        "register_closed": render_register_page("", closed=True),
        "panel": render_panel_page(theme_class="theme-dark", bg_rules="body{background:#121417}",
                                   msg_html="", body_html="<p>hi</p>", active_tab="nicknames",
                                   panel_bg_css="rgba(24,27,31,0.9)"),
    }
    for name, html in pages.items():
        assert "/panel/static/panel.css?v=" + PANEL_CSS_REV in html, name
        assert not re.search(r"\{\{[a-z_]+\}\}", html), name
        assert "<!DOCTYPE html>" in html, name


def test_panel_page_keeps_dynamic_bits():
    """模板化之后，动态内容仍要正确注入。"""
    html = render_panel_page(theme_class="theme-sakura", bg_rules="body{background:#FDEEF3}",
                             msg_html="<div class='msg'>提示</div>", body_html="<p>正文</p>",
                             active_tab="account", panel_bg_css="rgba(255,255,255,0.82)", glass=True)
    assert "theme-sakura" in html and "pglass" in html
    assert 'style="--panel-bg:rgba(255,255,255,0.82)"' in html
    assert "body{background:#FDEEF3}" in html
    assert "<div class='msg'>提示</div>" in html and "<p>正文</p>" in html
    assert "用户状态" in html and 'class="tab active"' in html
    assert "panel-foot" in html


# ---------- 分辨率自适应（PC / 平板 / 手机）----------

def _css_without_media_blocks(css: str) -> str:
    """去掉 @media 块后的基础 CSS（用于检查「无条件的固定宽度」）。"""
    out, i = [], 0
    while True:
        at = css.find("@media", i)
        if at < 0:
            out.append(css[i:])
            break
        out.append(css[i:at])
        brace = css.find("{", at)
        depth, j = 1, brace + 1
        while j < len(css) and depth:
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
            j += 1
        i = j
    return "".join(out)


def test_no_fixed_width_can_overflow_a_phone():
    """无条件的固定宽度不得 ≥320px —— 否则 360px 宽的手机必然横向溢出。"""
    import re
    base = _css_without_media_blocks(PANEL_CSS)
    offenders = [(m.group(1), int(m.group(2)))
                 for m in re.finditer(r"(?<![a-z-])(width|min-width)\s*:\s*(\d+)px", base)
                 if int(m.group(2)) >= 320]
    assert offenders == [], offenders


def test_has_all_responsive_breakpoints():
    """四档断点必须齐全：宽屏 PC / 平板横屏 / 平板竖屏 / 手机 / 小屏手机。"""
    for bp in ("min-width:1440px", "max-width:1023px", "max-width:980px",
               "max-width:860px", "max-width:720px", "max-width:420px"):
        assert bp in PANEL_CSS, bp


def test_layout_stacks_on_narrow_screens():
    """窄屏必须堆叠：.row / .rule-add / .form-inline / .nick-add 变单列。"""
    narrow = PANEL_CSS[PANEL_CSS.find("@media (max-width:860px)"):]
    assert ".row{grid-template-columns:minmax(0,1fr)" in narrow
    assert ".rule-add{grid-template-columns:minmax(0,1fr)}" in narrow
    assert ".form-inline{grid-template-columns:minmax(0,1fr)}" in narrow
    assert ".nick-add{grid-template-columns:minmax(0,1fr)}" in narrow
    assert ".w-sm,.w-gid,.w-md,.w-lg{max-width:none}" in narrow


def test_templates_declare_viewport():
    """没有 viewport meta，手机上会按 980px 缩放渲染 —— 必查。"""
    for name in ("panel.html", "login.html", "register.html", "register_closed.html"):
        html = template_path(name).read_text(encoding="utf-8")
        assert 'name="viewport"' in html and "width=device-width" in html, name


def test_static_css_route_serves_injected_css():
    """回归：静态路由必须返回**注入主题变量后**的 CSS。

    直接回文件内容会残留 {{THEME_VARS}} 占位符 → .theme-default{--input-bg:...} 整段失效
    → 输入框「透明无边框」、按钮白底白字（导致登录页看不到输入框，线上真实踩过）。
    """
    body = panel_asset_body("panel.css")
    assert body == PANEL_CSS
    assert "{{THEME_VARS}}" not in body
    assert "--input-bg:" in body and "--accent:" in body and ".theme-default" in body
    assert "input[type=text]" in body
    # 不存在的资源要返回 None（路由据此 404），不能抛异常
    assert panel_asset_body("does-not-exist.css") is None
