# -*- coding: utf-8 -*-
"""§7 CSS / 静态资源测试：真 HTTP 取 style.css，并证明页面**真的引用**它。

覆盖：HTTP 200 / 正确 Content-Type / 非空 / 页面实际引用 / 无 JS 资源 /
CSS 净化（@import、外链 url()、expression 剔除）/ 动态资源通道 webui.asset。
（浏览器 Console 无 404 需要真浏览器 —— 见 tests/e2e，本文件只做 HTTP 层证据。）
"""
import pytest


def test_style_css_served_with_css_content_type(web):
    resp = web.get(web.static_url(web.plugin_a, "style.css"))
    assert resp.status == 200, "HTTP %s：%s" % (resp.status, resp.text[:200])
    assert resp.content_type.split(";")[0].strip() == "text/css", resp.content_type
    assert len(resp.body) > 64, "CSS 过短（%d 字节）" % len(resp.body)
    assert ".flowerie-plugin-webui" in resp.text, "CSS 内容不符合插件作用域约定"
    assert resp.header("x-content-type-options") == "nosniff"


@pytest.mark.parametrize("page", ("index", "settings", "communication"))
def test_pages_reference_the_stylesheet(web, page):
    """§7「页面实际加载」：HTML 里必须出现该 CSS 的 URL（否则浏览器不会有这次请求）。"""
    resp = web.get(web.page_url(web.plugin_a, page))
    url = web.static_url(web.plugin_a, "style.css")
    assert url in resp.text, "页面 %s 没有引用 %s" % (page, url)
    assert ('<link rel="stylesheet" href="%s">' % url) in resp.text, "样式表链接被净化器丢弃"


def test_css_is_sanitized(web):
    """引擎必须剔除能外链/执行的构造（任务书 §8/§13）。"""
    text = web.get(web.static_url(web.plugin_a, "style.css")).text
    lowered = text.lower()
    assert "@import" not in lowered, "CSS 里的 @import 未被剔除"
    assert "url(http" not in lowered.replace(" ", ""), "CSS 里的外链 url() 未被剔除"
    assert "expression(" not in lowered, "CSS 里的 expression() 未被剔除"


def test_unknown_static_file_is_404(web):
    resp = web.get(web.static_url(web.plugin_a, "no_such_file.css"))
    assert resp.status == 404, resp.status


@pytest.mark.parametrize("name", ("app.js", "main.js", "style.js"))
def test_javascript_is_not_served(web, name):
    """零 JavaScript 策略：静态通道没有 .js 白名单。"""
    resp = web.get(web.static_url(web.plugin_a, name))
    assert resp.status == 404, "%s 竟然可访问（HTTP %s）" % (name, resp.status)


def test_dynamic_asset_css(web):
    """webui.asset 通道：插件进程现场生成的 CSS。"""
    resp = web.get(web.asset_url(web.plugin_a, "theme.css"))
    assert resp.status == 200, "HTTP %s：%s" % (resp.status, resp.text[:200])
    assert resp.content_type.split(";")[0].strip() == "text/css", resp.content_type
    assert ".flowerie-plugin-webui" in resp.text


def test_dynamic_asset_json(web):
    resp = web.get(web.asset_url(web.plugin_a, "info.json"))
    assert resp.status == 200, resp.status
    assert resp.content_type.split(";")[0].strip() == "application/json", resp.content_type
    payload = resp.json()
    assert payload.get("plugin_id") == web.plugin_a, payload
    assert payload.get("runtime") == "python", payload


def test_dynamic_asset_text(web):
    resp = web.get(web.asset_url(web.plugin_a, "logo.txt"))
    assert resp.status == 200, resp.status
    assert resp.content_type.split(";")[0].strip() == "text/plain", resp.content_type
    assert resp.body


def test_unknown_asset_is_404(web):
    resp = web.get(web.asset_url(web.plugin_a, "nope.css"))
    assert resp.status == 404, resp.status


def test_static_requires_authentication(web):
    resp = web.get(web.static_url(web.plugin_a, "style.css"), auth=False)
    assert resp.status in (302, 401), resp.status
