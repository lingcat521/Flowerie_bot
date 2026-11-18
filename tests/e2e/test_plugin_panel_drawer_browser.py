"""面板窄屏导航的真实浏览器回归（v2.19.0 夜间控制台）。

文件名刻意排在 test_plugin_chain_engine.py 之后：Playwright 的同步 API 会占用主线程的
事件循环，若它早于 pytest-asyncio 的 async 用例启动，那些用例会报
"Runner.run() cannot be called from a running event loop"（本仓库真实踩过）。

v2.19.0 把旧的“☰ + 遮罩抽屉”（需要 JS 控制 checkbox）换成了**原生 >details> 折叠导航**：

    <header class="mobile-header">
      <details class="mobile-navigation">
        <summary>导航 <span>当前：…</span></summary>
        <nav>…页签链接…</nav>

  v2.19.3 起导航按用途分组，details.mobile-navigation 里有 1 个总 summary
  + 4 个分组 summary，所以定位必须用 .first（总开关）而不是裸 locator。

  于是这里改用用户真实路径验证：窄屏点 summary 展开 → 页签可见且可点 →
  确实发生跳转；再点 summary 能收起。全程不需要 JavaScript。
"""
from tests.e2e import _harness as H

NAV = "details.mobile-navigation"


def _narrow_session(browser_provider):
    return browser_provider.new_session(viewport={"width": 390, "height": 844})


def _is_open(page):
    return page.evaluate(
        "document.querySelector('%s') ? document.querySelector('%s').open : null" % (NAV, NAV)
    )


def test_mobile_navigation_expands_and_links_clickable(browser_provider, webui_server):
    session = _narrow_session(browser_provider)
    try:
        H.form_login(session, webui_server)
        page = session.page
        page.goto(webui_server.base_url + "/panel", wait_until="domcontentloaded")

        nav = page.locator(NAV)
        assert nav.is_visible(), "窄屏应显示折叠导航（details.mobile-navigation）"
        assert _is_open(page) is False, "折叠导航默认应收起"

        nav.locator("summary").first.click()
        page.wait_for_timeout(200)
        assert _is_open(page) is True, "点 summary 应展开导航"

        link = nav.locator('a[href="/panel?tab=appearance"]')
        assert link.is_visible(), "展开后页签应可见"
        box = link.bounding_box()
        assert box, "导航里的页签没有渲染出来"
        hit = page.evaluate(
            "([x, y]) => { const el = document.elementFromPoint(x, y);"
            " return el ? (el.tagName + '|' + (el.getAttribute('href') || '') + '|' + el.className) : 'null'; }",
            [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2],
        )
        assert hit.startswith("A|/panel?tab=appearance"), (
            "导航里的页签被其它层挡住（点到的是 %r）" % hit)

        link.click()
        page.wait_for_load_state("domcontentloaded")
        assert "tab=appearance" in page.url, "点导航页签后应真的跳转，实际 URL=%s" % page.url
    finally:
        session.close()


def test_mobile_navigation_collapses_on_second_tap(browser_provider, webui_server):
    session = _narrow_session(browser_provider)
    try:
        H.form_login(session, webui_server)
        page = session.page
        page.goto(webui_server.base_url + "/panel", wait_until="domcontentloaded")

        nav = page.locator(NAV)
        nav.locator("summary").first.click()
        page.wait_for_timeout(200)
        assert _is_open(page) is True

        nav.locator("summary").first.click()
        page.wait_for_timeout(200)
        assert _is_open(page) is False, "再点 summary 应收起导航"
        assert not nav.locator('a[href="/panel?tab=appearance"]').is_visible()
    finally:
        session.close()
