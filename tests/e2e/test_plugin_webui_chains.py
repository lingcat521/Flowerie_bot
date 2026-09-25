"""§28 三条最低 E2E 链路（真浏览器）：

    E2E-1  Browser -> Python WebUI -> Python 插件 -> Go 插件    -> 回 Browser
    E2E-2  Browser -> TS WebUI     -> TS 插件     -> Java 插件  -> 回 Browser
    E2E-3  Browser -> Go WebUI     -> Go 插件     -> Rust 插件  -> 回 Browser

每一步都是真的：真 Chromium -> 真 aiohttp 服务器 -> 真插件进程 -> 真 Core Router -> 另一个
真插件进程（**不同语言**，因此在不同的子进程里），结果再渲染回浏览器。

环境不足（缺工具链 / 入口插件没有 communication 页面）时按 `BLOCKED BY ENVIRONMENT: …` skip，
理由里写明缺什么 —— 绝不 PASS（任务书 §31）。可用 env 覆盖插件对：
`E2E_CHAIN{1,2,3}_ENTRY` / `E2E_CHAIN{1,2,3}_TARGET`。
"""
import os

import pytest

from tests.e2e import _harness as H

#: 目标插件跑起来之后的 runtime 自报值（插件进程自己说的，不是我们猜的）
TARGET_RUNTIME = {"go": "go", "java": "java", "rust": "rust", "typescript": "typescript",
                  "python": "python"}


def _screenshot(session, chain):
    out_dir = os.environ.get("E2E_SCREENSHOT_DIR")
    if not out_dir:
        return ""
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "e2e-chain-%d.png" % chain)
    try:
        session.page.screenshot(path=path, full_page=True)
    except Exception:  # noqa: BLE001 - 截图失败不影响断言
        return ""
    return path


@pytest.mark.parametrize("chain", sorted(H.CHAINS))
def test_e2e_chain(chain, chain_runner, browser_provider):
    spec = H.CHAINS[chain]
    handle, ids = chain_runner(chain)
    if handle is None:
        pytest.skip("%s%s 不可跑 —— %s" % (H.BLOCKED, spec["name"], ids))

    session = browser_provider.new_session(viewport={"width": 1180, "height": 900})
    try:
        H.form_login(session, handle)                       # 真表单登录（fill + click）
        page = session.page
        page.goto(handle.page_url(ids["entry"], "communication"), wait_until="domcontentloaded")

        assert page.locator("#communication-panel").count() == 1, (
            "入口插件 %s 的 communication 页面不满足 E2E 页面契约（缺 #communication-panel）"
            % ids["entry"])
        page.fill("#communication-target", ids["target"])
        page.select_option("#communication-method", spec["method"])
        page.fill("#communication-request", spec["request"])
        page.select_option("#communication-route", "auto")
        page.click("#communication-submit")
        page.wait_for_load_state("domcontentloaded")

        response = page.locator("#communication-response").inner_text()
        trace = page.locator("#communication-trace-id").inner_text().strip()
        runtime = page.locator("#communication-target-runtime").inner_text().strip()
        request_id = page.locator("#communication-request-id").inner_text().strip()
        error = page.locator("#communication-error").inner_text().strip()
        ok_flag = page.locator("#communication-response-ok").inner_text().strip()
        _screenshot(session, chain)

        assert error == "", "链路报错：%s" % error
        assert ok_flag == "ok", "response_ok=%r（response=%s）" % (ok_flag, response)
        assert '"hello"' in response and '"world"' in response, (
            "回包不是目标插件对请求的原样回应：%s" % response)
        assert trace, "trace_id 为空（关联 id 没生成）"
        assert trace in response, (
            "关联 id 没有从目标插件原样回来 —— 说明回包不是目标进程产生的：trace=%s response=%s"
            % (trace, response))
        assert request_id, "request_id 为空"
        assert runtime == TARGET_RUNTIME[spec["target_lang"]], (
            "目标插件自报 runtime=%r，期望 %r —— 说明调用没有真的到达 %s 插件进程"
            % (runtime, TARGET_RUNTIME[spec["target_lang"]], spec["target_lang"]))
        assert session.page_errors == [], session.page_errors
        assert session.failed_responses == [], session.failed_responses
    finally:
        session.close()
