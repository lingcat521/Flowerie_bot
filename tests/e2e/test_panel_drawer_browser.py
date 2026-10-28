"""面板导航抽屉的真实浏览器回归（v2.14.3 修复）。

Bug 背景：遮罩曾是 <header> 的兄弟节点，z-index:50 压在 .topbar（z-index:1）整层之上，
于是窄屏打开抽屉后：① 点抽屉里的页签，实际点到的是遮罩；② 整个抽屉被遮罩压暗。
这里用真 Chromium 走用户路径：窄屏点 ☰ → 点「外观」→ 必须真的跳转；
并用 elementFromPoint 证明点击坐标命中的是 <a> 而不是遮罩。
"""
from tests.e2e import _harness as H


def _narrow_session(browser_provider):
    return browser_provider.new_session(viewport={"width": 390, "height": 844})


def test_drawer_link_receives_click(browser_provider, webui_server):
    session = _narrow_session(browser_provider)
    try:
        H.form_login(session, webui_server)
        page = session.page
        page.goto(webui_server.base_url + "/panel", wait_until="domcontentloaded")
        assert page.locator(".nav-btn").is_visible(), "窄屏应显示 ☰"
        page.locator(".nav-btn").click()
        page.wait_for_timeout(350)   # 等抽屉滑出动画
        assert page.evaluate("document.getElementById('nav-toggle').checked") is True
        assert page.locator(".nav-overlay").is_visible(), "遮罩应出现"
        link = page.locator('#nav a[href="/panel?tab=appearance"]')
        box = link.bounding_box()
        assert box, "抽屉里的页签没有渲染出来"
        hit = page.evaluate(
            "([x, y]) => { const el = document.elementFromPoint(x, y);"
            " return el ? (el.tagName + '|' + (el.getAttribute('href') || '') + '|' + el.className) : 'null'; }",
            [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2],
        )
        assert hit.startswith("A|/panel?tab=appearance"), (
            "抽屉里的页签被其它层挡住（点到的是 %r）" % hit)
        link.click()
        page.wait_for_load_state("domcontentloaded")
        assert "tab=appearance" in page.url, "点抽屉页签后应真的跳转，实际 URL=%s" % page.url
        assert page.evaluate("document.getElementById('nav-toggle').checked") is False, (
            "跳转后抽屉应关闭")
    finally:
        session.close()


def test_drawer_overlay_closes_on_tap(browser_provider, webui_server):
    session = _narrow_session(browser_provider)
    try:
        H.form_login(session, webui_server)
        page = session.page
        page.goto(webui_server.base_url + "/panel", wait_until="domcontentloaded")
        page.locator(".nav-btn").click()
        page.wait_for_timeout(350)
        assert page.evaluate("document.getElementById('nav-toggle').checked") is True
        # 点抽屉右侧的空白处（遮罩区域）应关闭抽屉
        page.mouse.click(365, 760)
        page.wait_for_timeout(250)
        assert page.evaluate("document.getElementById('nav-toggle').checked") is False
        assert not page.locator(".nav-overlay").is_visible()
    finally:
        session.close()
