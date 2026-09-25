"""tests/e2e 的夹具：真 WebUI 服务器 + 真插件进程 + 真浏览器。

缺什么就 `BLOCKED BY ENVIRONMENT: …` skip（`pytest -rs` 会打印原因），**绝不 PASS**：

* 浏览器（Playwright + Chromium）缺失 -> 浏览器用例 skip；
* 服务端依赖（aiohttp / pydantic …）缺失 -> 服务器用例 skip；
* 编译型语言工具链（Go / Rust / JDK / Node）缺失 -> 对应链路 skip，理由里写明缺哪个可执行文件。

引擎层（真 PluginManager + 真插件进程，不需要服务器和浏览器）见
`test_plugin_chain_engine.py` —— 那一层在最小环境里也能真跑。
"""
import os
import shutil

import pytest

from tests.e2e import _harness as H

# --------------------------------------------------------------------- 工作目录 / 服务器


@pytest.fixture(scope="session")
def e2e_root():
    """会话级临时根目录（可执行位必须可用：编译型插件的 run.sh 要能 exec）。"""
    root = H.temp_dir("flowerie-e2e-session-")
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="session")
def webui_server(e2e_root):
    """§8 用的真服务器：只装 tests/e2e 自带夹具入口插件（+ 已落地的 canonical 示例插件）。"""
    ok, reason = H.server_dependency_status()
    if not ok:
        pytest.skip(H.BLOCKED + "本机跑不起真 WebUI 服务器 —— " + reason)
    provision = H.provision_plugins(e2e_root, langs=())
    enable = [provision["ids"]["fixture"]]
    if os.path.isdir(H.CANONICAL_PLUGIN_DIR):
        try:
            pid, _dest = H.copy_plugin(H.CANONICAL_PLUGIN_DIR, provision["plugins_root"])
            enable.append(pid)
        except Exception:  # noqa: BLE001 - 示例插件坏掉不影响夹具插件
            pass
    handle = H.launch_server(provision["plugins_root"], enable=enable)
    try:
        yield handle
    finally:
        handle.stop()


@pytest.fixture(scope="session")
def canonical_plugin_id(webui_server):
    """examples/plugin-webui-test 的插件 id（未落地时为 None）。"""
    if not os.path.isdir(H.CANONICAL_PLUGIN_DIR):
        return None
    try:
        return str(H.read_manifest(H.CANONICAL_PLUGIN_DIR).get("id") or "")
    except (OSError, ValueError):
        return None


@pytest.fixture(scope="session")
def chain_runner(e2e_root):
    """按链路惰性拉起真服务器；返回 callable(chain) -> (ServerHandle, ids) 或 (None, reason)。"""
    cache = {}

    def run(chain):
        if chain in cache:
            return cache[chain]
        # 每条链路一个独立插件目录：链路的构建/铺开互不干扰（也不会动到别的链路正在跑的进程）
        chain_root = os.path.join(e2e_root, "chain-%d" % chain)
        os.makedirs(chain_root, exist_ok=True)
        provision = H.provision_plugins(chain_root, langs=H.chain_languages(chain))
        reason = H.chain_blocked_reason(chain, provision)
        if reason:
            cache[chain] = (None, reason)
            return cache[chain]
        ids = H.chain_plugin_ids(chain)
        handle = H.launch_server(provision["plugins_root"],
                                 enable=[ids["entry"], ids["target"]])
        cache[chain] = (handle, ids)
        return cache[chain]

    try:
        yield run
    finally:
        for handle, _ids in cache.values():
            if handle is not None:
                handle.stop()


# --------------------------------------------------------------------- 浏览器


class BrowserProvider(object):
    """惰性启动的 Chromium：**第一次真正用到**时才启动，装不上就 BLOCKED skip。

    惰性是有意的：链路用例先判断工具链/入口插件（skip 理由更准确），只有真要开浏览器时才需要浏览器。
    """

    def __init__(self):
        self._playwright = None
        self._browser = None

    def browser(self):
        if self._browser is None:
            ok, info = H.playwright_status()
            if not ok:
                pytest.skip(H.BLOCKED + "浏览器不可用 —— " + info)
            from playwright.sync_api import sync_playwright
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                args=["--no-sandbox", "--disable-dev-shm-usage"])
        return self._browser

    def new_session(self, **kwargs):
        context = self.browser().new_context(**kwargs)
        return H.BrowserSession(context.new_page(), context=context)

    def close(self):
        try:
            if self._browser is not None:
                self._browser.close()
        finally:
            if self._playwright is not None:
                self._playwright.stop()
        self._browser = None
        self._playwright = None


@pytest.fixture(scope="session")
def browser_provider():
    """浏览器提供者（session 级；惰性启动，见 BrowserProvider 注释）。"""
    provider = BrowserProvider()
    try:
        yield provider
    finally:
        provider.close()


@pytest.fixture
def browser_session(browser_provider, webui_server):
    session = browser_provider.new_session(viewport={"width": 1180, "height": 900},
                                           ignore_https_errors=True)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def logged_in(browser_session, webui_server):
    """已登录的浏览器会话（登录走真表单 POST）。"""
    H.form_login(browser_session, webui_server)
    return browser_session


@pytest.fixture
def rig_ctx():
    """引擎层夹具（真 PluginManager + 真插件进程）；tests/sdk/harness.py 不可用时 BLOCKED。"""
    sdk = H.sdk_harness()
    if sdk is None:
        pytest.skip(H.BLOCKED + "tests/sdk/harness.py 不可用（多语言构建/装载口径缺失）")
    return sdk.RigCtx
