"""§8 浏览器真实渲染 / §9 零 JS 策略（浏览器侧）/ §7 CSS 真实加载。

真 Chromium（Playwright）+ 真 WebUI 服务器（子进程）+ 真插件进程；没有 Mock。
浏览器装不上时本文件的浏览器用例 `BLOCKED BY ENVIRONMENT` skip（写清缺什么，绝不 PASS）；
只依赖服务器、不依赖浏览器的用例（HTTP 契约 / 登录前置）仍然会跑。
"""
import os

import pytest

from tests.e2e import _harness as H

PLUGIN_ID = H.FIXTURE_PLUGIN_ID


def _url(server, page_id, plugin_id=PLUGIN_ID):
    return server.page_url(plugin_id, page_id)


def _goto(session, server, page_id, plugin_id=PLUGIN_ID):
    session.goto(_url(server, page_id, plugin_id))
    return session.page


# --------------------------------------------------------------------- HTTP 层（不需要浏览器）

def test_pages_serve_html_and_contract_ids(webui_server):
    """真服务器把三个页面渲染成 HTML，且每一页都带契约里的元素 id（不需要浏览器）。"""
    cookie = webui_server.cookie
    for page_id in H.PAGE_IDS:
        status, headers, body, _c = webui_server.request(
            "/panel/plugins/webui/%s/%s" % (PLUGIN_ID, page_id), cookie=cookie)
        assert status == 200, "%s 返回 HTTP %s" % (page_id, status)
        assert "text/html" in headers.get("Content-Type", ""), headers
        assert "Traceback" not in body and "Internal Server Error" not in body
        assert "<script" not in body.lower(), "零 JS 红线：%s 里出现了 <script>" % page_id
        for el_id in H.REQUIRED_IDS[page_id]:
            assert ('id="%s"' % el_id) in body, "%s 缺少 #%s" % (page_id, el_id)


def test_plugin_page_requires_login(browser_provider, webui_server):
    """未登录访问插件页面 -> 回登录页（先登录是硬前置，不是测试的技巧）。"""
    session = browser_provider.new_session()
    try:
        session.goto(_url(webui_server, "index"))
        assert session.page.locator('form[action="/panel/login"]').count() == 1, (
            "未登录访问插件页面应当被重定向到 /panel 登录页，实际 URL=%s" % session.page.url)
    finally:
        session.close()


# --------------------------------------------------------------------- 浏览器层（§8）

def test_index_page_renders_plugin_name_and_status(logged_in, webui_server):
    page = _goto(logged_in, webui_server, "index")
    assert page.locator("#plugin-name").is_visible()
    assert "WebUI E2E" in page.locator("#plugin-name").inner_text()
    assert page.locator("#plugin-status").is_visible()
    assert "running" in page.locator("#plugin-status").inner_text()
    # 页面上的运行时/版本不是硬编码文案，而是插件进程里查到的真值
    assert page.locator("#plugin-runtime").inner_text().strip() == "python"
    assert page.locator("#plugin-sdk-version").inner_text().strip()
    assert page.locator("script").count() == 0
    assert logged_in.page_errors == []


def test_settings_form_visible_with_required_controls(logged_in, webui_server):
    page = _goto(logged_in, webui_server, "settings")
    assert page.locator("#settings-form").is_visible()
    assert page.locator('input[type="text"]#setting-greeting').is_visible()
    assert page.locator('input[type="number"]#setting-count').is_visible()
    assert page.locator('input[type="checkbox"]#setting-notify').is_visible()
    assert page.locator('select#setting-mode').is_visible()
    assert page.locator("#settings-submit").is_visible()
    # select 里真的有可选模式（select_option 交互依赖它）
    assert page.locator('select#setting-mode option').count() >= 3


def test_communication_panel_visible(logged_in, webui_server):
    page = _goto(logged_in, webui_server, "communication")
    assert page.locator("#communication-panel").is_visible()
    for el_id in ("communication-target", "communication-method", "communication-request",
                  "communication-route", "communication-submit", "communication-response"):
        assert page.locator("#" + el_id).count() == 1, "缺 #%s" % el_id


def test_document_title_contract(logged_in, webui_server):
    """§8 要求断言 document.title。

    实测现状：插件页面路由返回的是**面板壳片段** —— 响应里没有 <html>/<head>/<title>
    （净化器把插件文件里的这些标签全部丢弃，drop 报告见 tests/e2e 报告），所以浏览器标题是空串。
    这里断言三件事，任何一件变了都会红：
      1) 插件页面文件里写的 <title> 文本**不会**变成浏览器标题（插件不能控制标签页）；
      2) 若面板壳将来补上 <title>，在 CI 里设置 E2E_EXPECT_DOCUMENT_TITLE 后必须完全相等；
      3) 用户可见的页面标题（壳的 h1.page-title）必须存在且是当前页 —— 标题信息不缺失。
    """
    page = _goto(logged_in, webui_server, "index")
    title = page.title()
    expected = os.environ.get("E2E_EXPECT_DOCUMENT_TITLE")
    if expected is not None:
        assert title == expected, "document.title=%r，期望 %r" % (title, expected)
    else:
        assert title == "", (
            "面板壳当前不输出 <title>（片段响应），document.title 应为空串，实际 %r；"
            "如果壳已经补上 <title>，请设置环境变量 E2E_EXPECT_DOCUMENT_TITLE 并更新 tests/e2e/README.md"
            % title)
    assert "总览" not in title, "插件页面文件里的 <title> 不应成为浏览器标题"
    assert page.locator("h1.page-title").inner_text().strip().startswith("总览")


def test_zero_javascript_policy_in_real_browser(logged_in, webui_server):
    """§9：页面不许有 JS，且 CSP `default-src 'none'` 让注入的脚本也无法执行（浏览器侧实证）。"""
    page = _goto(logged_in, webui_server, "index")
    assert page.locator("script").count() == 0
    html = page.content().lower()
    assert "<script" not in html
    assert "javascript:" not in html
    # 注入一个 <script>：CSP 应拦下它（全局变量不会被赋值）
    page.add_script_tag(content="window.__e2e_injected = 42;")
    assert page.evaluate("window.__e2e_injected") is None, (
        "CSP 没有拦住注入的内联脚本：零 JS 策略在浏览器里失效了")
    assert logged_in.page_errors == []


def test_css_stylesheet_is_loaded_and_applied(logged_in, webui_server):
    """§7：插件样式表真加载（HTTP 200 + text/css），并且真的作用到了 DOM 上（不是只下载了）。"""
    page = logged_in.page
    seen = []
    page.on("response", lambda r: seen.append(r) if "style.css" in r.url else None)
    page.goto(_url(webui_server, "index"), wait_until="domcontentloaded")
    css = [r for r in seen if r.url.endswith("/static/style.css")]
    assert css, "页面没有请求插件样式表 (style.css)"
    assert css[-1].status == 200, "样式表 HTTP %s" % css[-1].status
    assert "text/css" in (css[-1].headers.get("content-type") or "")
    weight = page.eval_on_selector("#plugin-status", "el => getComputedStyle(el).fontWeight")
    assert weight == "600", "插件 CSS 没有生效（font-weight=%r）" % weight
    assert logged_in.failed_responses == [], logged_in.failed_responses


def test_settings_form_roundtrip_without_js(logged_in, webui_server):
    """无 JS 约束下的交互：只允许 fill / select_option / check / click（浏览器原生表单行为）。

    提交后由**服务器**重新渲染（插件进程里真的保存了状态），断言页面把状态读回来了。
    """
    page = _goto(logged_in, webui_server, "settings")
    page.fill("#setting-greeting", "来自浏览器的问候")
    page.fill("#setting-count", "7")
    page.check("#setting-notify")
    page.select_option("#setting-mode", "c")
    page.click("#settings-submit")
    page.wait_for_load_state("domcontentloaded")

    assert page.url.endswith("/settings"), page.url
    assert page.locator("#settings-message").inner_text().strip() == "设置已保存"
    assert page.locator("#state-greeting").inner_text().strip() == "来自浏览器的问候"
    assert page.locator("#state-count").inner_text().strip() == "7"
    assert page.locator("#state-mode").inner_text().strip() == "c"
    assert page.locator("#state-notify").inner_text().strip() == "on"
    assert page.locator("#state-saved-at").inner_text().strip() not in ("", "（尚未保存）")
    assert page.locator("script").count() == 0
    assert logged_in.page_errors == []


def test_navigation_between_plugin_pages_by_links(logged_in, webui_server):
    """零 JS 的多页导航：靠 <a href> 在三个页面之间走（没有前端路由）。"""
    page = _goto(logged_in, webui_server, "index")
    page.click("#nav-settings")
    page.wait_for_load_state("domcontentloaded")
    assert page.url.endswith("/settings")
    page.click("#nav-communication")
    page.wait_for_load_state("domcontentloaded")
    assert page.url.endswith("/communication")
    page.click("#nav-index")
    page.wait_for_load_state("domcontentloaded")
    assert page.url.endswith("/index")
    assert logged_in.page_errors == []


# --------------------------------------------------------------------- §4 canonical 插件（若已落地）

def test_canonical_example_plugin_pages(webui_server, canonical_plugin_id):
    """examples/plugin-webui-test（任务书 §4 的专用测试插件）落地后，必须满足同一套页面契约。

    只需要服务器，不需要浏览器：这样"插件页面契约"在最小环境里也能被检查。
    """
    if not canonical_plugin_id:
        pytest.skip("examples/plugin-webui-test 尚未落地（本轮由 tests/e2e 自带夹具插件提供入口）")
    server = webui_server
    cookie = server.cookie
    # 任务书要求的四个元素 id（canonical 插件的 settings/communication 页只保证自己的那几个）
    expected = {"index": ("plugin-name", "plugin-status"),
                "settings": ("settings-form",),
                "communication": ("communication-panel",)}
    for page_id, ids in expected.items():
        status, headers, body, _c = server.request(
            "/panel/plugins/webui/%s/%s" % (canonical_plugin_id, page_id), cookie=cookie)
        assert status == 200, "canonical 插件 %s 返回 HTTP %s" % (page_id, status)
        for el_id in ids:
            assert ('id="%s"' % el_id) in body, (
                "canonical 插件 %s 缺少 #%s（E2E 页面契约见 tests/e2e/README.md）" % (page_id, el_id))


def test_canonical_plugin_communication_calls_other_plugin(logged_in, webui_server, canonical_plugin_id):
    """§12/§28（无工具链依赖的那条）：canonical 测试插件的调用页 -> plugin.call -> 我们的夹具插件。

    这条链路只依赖 Python 运行时，因此在 CI（以及任何装了浏览器的机器）上都会真跑：
    浏览器填表单 -> 服务器 -> canonical 插件进程 -> Core Router -> 夹具插件进程 -> 回浏览器。
    """
    if not canonical_plugin_id:
        pytest.skip("examples/plugin-webui-test 尚未落地")
    page = _goto(logged_in, webui_server, "communication", canonical_plugin_id)
    assert page.locator("#communication-panel").count() == 1
    page.fill('#call-form input[name="target"]', PLUGIN_ID)
    page.fill('#call-form input[name="method"]', "echo")
    page.fill('#call-form textarea[name="params"]', '{"hello": "world"}')
    page.select_option('#call-form select[name="route"]', "auto")
    page.click('#call-form button[name="plugin_action"][value="call"]')
    page.wait_for_load_state("domcontentloaded")

    status = page.locator("#call-status").inner_text()
    assert "OK" in status, "调用状态：%s（%s）" % (status, page.locator("#call-message").inner_text())
    assert page.locator("#call-target").inner_text().strip() == PLUGIN_ID
    response = page.locator("#call-response").inner_text()
    assert "hello" in response and "world" in response, response
    assert page.locator("#call-request").inner_text().strip(), "request 区为空"
    # 引擎侧 request_id / trace_id：被调方（夹具插件）按互操作约定平铺回传，页面必须显示真值
    request_id = page.locator("#call-request-id").inner_text().strip()
    trace_id = page.locator("#call-trace-id").inner_text().strip()
    assert request_id and "未回传" not in request_id, "引擎 request_id 没显示出来：%r" % request_id
    assert trace_id and "未回传" not in trace_id, "引擎 trace_id 没显示出来：%r" % trace_id
    assert logged_in.page_errors == [], logged_in.page_errors
