# -*- coding: utf-8 -*-
"""tests/webui/ 真链路夹具（任务书 §25/§26：禁止 Mock Core）。

**真组件清单**（一个都不能换成桩）：

| 组件 | 实体 |
| :--- | :--- |
| Web UI 服务器 | src/services/web_ui.py:WebUIServer，真 aiohttp，监听 127.0.0.1 的**随机端口** |
| 配置仓库 | src/repositories/settings_repository.py:SettingsRepository（真 SQLite 文件）|
| 插件管理器 | src/plugins/manager.py:PluginManager（真发现 / 真启用 / 真子进程运行时）|
| 插件进程 | examples/plugin-webui-test（A）与 examples/multilang-sdk/python（B，最小插件）+ B 的第二份部署（C）|
| 客户端 | http.client 黑盒 HTTP（不经任何会做路径归一化的客户端库，§18 需要原样发路径）|

**没有** FakeRouter / FakePluginManager / FakeCore / FakePlugin：插件都是仓库里的真插件，
由真引擎按 manifest 拉起独立子进程（python -I src/plugins/runner/python_runner.py）。

夹具是 **session 级**：一次启动服务器 + 三个真插件进程，全部用例共用（快且真实）。
用例自己负责恢复被自己改动的状态（权限 / 配置）。
"""
import asyncio
import http.client
import json
import os
import shutil
import tempfile
import threading
import time
import urllib.parse

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLES = os.path.join(ROOT, "examples")
SRC_A = os.path.join(EXAMPLES, "plugin-webui-test")
SRC_B = os.path.join(EXAMPLES, "multilang-sdk", "python")

ADMIN_USER = "webui_admin"
ADMIN_PASSWORD = "webui-test-pass"

#: Secret 泄漏扫描用的哨兵值（写进服务器进程环境；任何 WebUI 响应都不得出现）
SECRETS = {
    "TEST_SECRET": "TEST_SECRET-sentinel-9f3a-DO-NOT-LEAK",
    "TEST_API_KEY": "TEST_API_KEY-sentinel-77c1-DO-NOT-LEAK",
    "TEST_TOKEN": "TEST_TOKEN-sentinel-b41e-DO-NOT-LEAK",
}

#: 路径穿越用例（§18）：原样发送，不做任何归一化
TRAVERSAL_PATHS = (
    "..%2fmanifest.json",
    "%2e%2e%2fmanifest.json",
    "%2e%2e/%2e%2e/manifest.json",
    "..%252fmanifest.json",
    "%252e%252e%252fmanifest.json",
    "....//manifest.json",
    "%2fetc%2fpasswd",
    "..%5cmanifest.json",
)


def _read_manifest(src):
    path = os.path.join(src, "manifest.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _missing_examples():
    """返回缺失的示例插件路径列表（空 = 可以真跑）。"""
    missing = []
    for src in (SRC_A, SRC_B):
        if _read_manifest(src) is None:
            missing.append(os.path.join(src, "manifest.json"))
    if not missing:
        for page in ("index", "settings", "communication"):
            path = os.path.join(SRC_A, "webui", "pages", "%s.html" % page)
            if not os.path.isfile(path):
                missing.append(path)
        if not os.path.isfile(os.path.join(SRC_B, "plugin.py")):
            missing.append(os.path.join(SRC_B, "plugin.py"))
    return missing


class Resp:
    """黑盒 HTTP 响应（状态 / 头 / 原始字节 / 文本）。"""

    def __init__(self, status, headers, body):
        self.status = status
        self.headers = {str(k).lower(): str(v) for k, v in headers}
        self.body = body

    @property
    def text(self):
        return self.body.decode("utf-8", "replace")

    @property
    def content_type(self):
        return self.headers.get("content-type", "")

    def header(self, name, default=""):
        return self.headers.get(str(name).lower(), default)

    def json(self):
        return json.loads(self.body.decode("utf-8"))

    def __repr__(self):
        return "<Resp %s %s bytes=%d>" % (self.status, self.content_type, len(self.body))


class WebUIStack:
    """真 WebUIServer + 真 SettingsRepository + 真 PluginManager + 真插件进程。"""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="flowerie-webui-")
        self.plugin_dir = os.path.join(self.root, "plugins")
        self.data_dir = os.path.join(self.root, "webui-data")
        self.loop = None
        self.port = None
        self.cookie = ""
        self.plugin_a = ""
        self.plugin_b = ""
        self.plugin_c = ""
        self.src_a = SRC_A
        self.src_b = SRC_B
        self.manifest_a = {}
        self.manifest_b = {}
        self.deployed = {}          # plugin_id -> 部署目录
        self._thread = None
        self._ready = threading.Event()
        self._error = None

    # ---------------------------------------------------------------- 生命周期

    def start(self, timeout=180.0):
        self._thread = threading.Thread(target=self._thread_main, name="webui-stack", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("WebUI 夹具启动超时（%ss）：%s" % (timeout, self.root))
        if self._error is not None:
            raise self._error
        # 就绪探测必须在主线程（事件循环线程里同步发 HTTP 会把服务器自己堵死）
        self._wait_until_serving()

    def _thread_main(self):
        loop = asyncio.new_event_loop()
        self.loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._boot())
        except BaseException as exc:  # noqa: BLE001 - 启动失败要原样带回主线程
            self._error = exc
            self._ready.set()
            return
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                loop.run_until_complete(self._shutdown())
            except Exception:  # noqa: BLE001
                pass
            loop.close()

    def close(self):
        if self.loop is not None and not self.loop.is_closed():
            try:
                fut = asyncio.run_coroutine_threadsafe(self._shutdown(), self.loop)
                fut.result(60)
            except Exception:  # noqa: BLE001 - 关停失败不阻塞收尾
                pass
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=30)
        shutil.rmtree(self.root, ignore_errors=True)

    # ---------------------------------------------------------------- 启动

    async def _boot(self):
        from src.config import Settings
        from src.plugins.manager import PluginManager
        from src.repositories.settings_repository import SettingsRepository
        from src.services.config_service import ConfigService
        from src.services.web_ui import WebUIServer

        # Secret 哨兵：真的放进服务器进程环境（§20：响应里不得出现）
        for key, value in SECRETS.items():
            os.environ[key] = value

        os.makedirs(self.plugin_dir, exist_ok=True)
        self.manifest_a = _read_manifest(SRC_A) or {}
        self.manifest_b = _read_manifest(SRC_B) or {}
        self.plugin_a = str(self.manifest_a.get("id") or "plugin_webui_test")
        self.plugin_b = str(self.manifest_b.get("id") or "minimal_py")
        self.plugin_c = self.plugin_b + "_c"

        self._deploy(SRC_A, self.plugin_a)
        self._deploy(SRC_B, self.plugin_b)
        self._deploy(SRC_B, self.plugin_c)          # §22：三插件隔离

        # Settings 的两个必填字段（真 pydantic 校验；本机 pydantic 是 stub，CI 才是真闸门）
        cfg = Settings(DEEPSEEK_API_KEY="sk-webui-test-000000", BOT_QQ=10001)
        cfg.PLUGIN_DIR = self.plugin_dir
        cfg.SETTINGS_DB_PATH = os.path.join(self.root, "settings.db")
        cfg.WEB_UI_ENABLED = True
        cfg.WEB_UI_HOST = "127.0.0.1"
        cfg.WEB_UI_PORT = 0                          # 随机端口（真 TCP 监听）
        cfg.WEB_UI_USERNAME = ADMIN_USER
        cfg.WEB_UI_PASSWORD = ""
        cfg.WEB_UI_ALLOW_LAN = False
        cfg.WEB_UI_TOKEN_TTL_SECONDS = 3600
        self.config = cfg

        self.repo = SettingsRepository(cfg.SETTINGS_DB_PATH)
        self.config_service = ConfigService(cfg, self.repo,
                                            env_path=os.path.join(self.root, ".env"))
        self.manager = PluginManager(config=cfg, repository=self.repo)
        self.manager.discover()
        for plugin_id in (self.plugin_a, self.plugin_b, self.plugin_c):
            approved = list(self._deployed_manifest(plugin_id).get("permissions") or [])
            ok, why = await self.manager.enable(plugin_id, approved_permissions=approved)
            if not ok:
                raise RuntimeError("启用插件 %s 失败：%s" % (plugin_id, why))

        self.webui = WebUIServer(cfg, self.config_service, data_dir=self.data_dir,
                                 plugin_manager=self.manager)
        await self.webui.start()
        self.port = self.webui._site._server.sockets[0].getsockname()[1]

    async def _shutdown(self):
        try:
            await self.webui.stop()
        finally:
            await self.manager.shutdown()
        # 兜底：把本循环里仍未结束的任务收干净。loop.close() 时 asyncio 会对残留任务打印
        # "Task was destroyed but it is pending!"（本机实测 6 条，来自模块级重启插件派出的
        # 即发即忘 shutdown），任务被 destroy 意味着它自己的清理逻辑没跑完。
        current = asyncio.current_task()
        leftover = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
        for task in leftover:
            task.cancel()
        if leftover:
            await asyncio.gather(*leftover, return_exceptions=True)

    def _wait_until_serving(self, timeout=30.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                resp = self.request("GET", "/panel", auth=False)
                if resp.status in (200, 302):
                    return
            except OSError:
                pass
            time.sleep(0.1)
        raise RuntimeError("WebUI 端口 %s 未开始服务" % self.port)

    # ---------------------------------------------------------------- 部署

    def _deploy(self, src, plugin_id, permissions=None, extra_entry=""):
        dst = os.path.join(self.plugin_dir, plugin_id)
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        manifest_path = os.path.join(dst, "manifest.json")
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        manifest["id"] = plugin_id
        if permissions is not None:
            manifest["permissions"] = list(permissions)
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)
        if extra_entry:
            entry = os.path.join(dst, str(manifest.get("entry") or "plugin.py"))
            with open(entry, "a", encoding="utf-8") as fh:
                fh.write("\n\n" + extra_entry)
        self.deployed[plugin_id] = dst
        return dst

    def deploy_variant(self, src, plugin_id, permissions=None, extra_entry=""):
        """按需再部署一份真插件（改写 id / 声明权限）——用于权限与隔离用例。

        这不是 Mock：仍然是仓库里的真插件源码 + 真子进程，只是换一个 id / 权限声明，
        与 tests/sdk/harness.py 的 deploy(declared=...) 同一口径。
        """
        return self.call(self._deploy_and_enable(src, plugin_id, permissions, extra_entry))

    async def _deploy_and_enable(self, src, plugin_id, permissions, extra_entry=""):
        self._deploy(src, plugin_id, permissions=permissions, extra_entry=extra_entry)
        self.manager.discover()
        declared = list(self._deployed_manifest(plugin_id).get("permissions") or [])
        ok, why = await self.manager.enable(plugin_id, approved_permissions=declared)
        if not ok:
            raise RuntimeError("启用变体插件 %s 失败：%s" % (plugin_id, why))
        return self.deployed[plugin_id]

    def _deployed_manifest(self, plugin_id):
        path = os.path.join(self.plugin_dir, plugin_id, "manifest.json")
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def call(self, coro, timeout=120.0):
        """在服务器事件循环里跑一个协程（真引擎 API，例如 manager.enable）。"""
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    # ---------------------------------------------------------------- HTTP

    def request(self, method, path, data=None, *, body=None, content_type=None,
                headers=None, auth=True, timeout=30.0):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        hdrs = dict(headers or {})
        payload = body
        if data is not None:
            payload = urllib.parse.urlencode(data, doseq=True).encode()
            hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
        if content_type:
            hdrs["Content-Type"] = content_type
        if auth and self.cookie:
            hdrs["Cookie"] = self.cookie
        try:
            conn.request(method, path, body=payload, headers=hdrs)
            raw = conn.getresponse()
            return Resp(raw.status, raw.getheaders(), raw.read())
        finally:
            conn.close()

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, data=None, **kw):
        return self.request("POST", path, data=data, **kw)

    def multipart(self, fields, files):
        """构造 multipart/form-data（上传用例）。files: [(name, filename, bytes)]"""
        boundary = "----flowerie-webui-boundary"
        out = bytearray()
        for key, value in (fields or {}).items():
            out += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                    % (boundary, key, value)).encode("utf-8")
        for name, filename, blob in files:
            out += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                    "Content-Type: application/octet-stream\r\n\r\n"
                    % (boundary, name, filename)).encode("utf-8")
            out += blob
            out += b"\r\n"
        out += ("--%s--\r\n" % boundary).encode("utf-8")
        return bytes(out), "multipart/form-data; boundary=%s" % boundary

    # ---------------------------------------------------------------- 认证

    def authenticate(self):
        """真流程：Bootstrap 注册第一个管理员 → 登录 → 拿 fb_token cookie。"""
        if self.cookie:
            return self.cookie
        self.request("POST", "/panel/register",
                     data={"username": ADMIN_USER, "password": ADMIN_PASSWORD}, auth=False)
        resp = self.request("POST", "/panel/login",
                            data={"username": ADMIN_USER, "password": ADMIN_PASSWORD}, auth=False)
        cookie = resp.header("set-cookie")
        token = ""
        for part in cookie.split(";"):
            if part.strip().startswith("fb_token="):
                token = part.strip()
        if not token:
            raise RuntimeError("登录失败（HTTP %s）：%s" % (resp.status, resp.text[:200]))
        self.cookie = token
        return self.cookie

    # ---------------------------------------------------------------- URL 助手

    def page_url(self, plugin_id, page, query=None):
        url = "/panel/plugins/webui/%s/%s" % (plugin_id, page)
        if query:
            url += "?" + urllib.parse.urlencode(query)
        return url

    def static_url(self, plugin_id, path="style.css"):
        return "/panel/plugins/webui/%s/static/%s" % (plugin_id, path)

    def asset_url(self, plugin_id, path="theme.css"):
        return "/panel/plugins/webui/%s/asset/%s" % (plugin_id, path)

    def file_url(self, plugin_id, name):
        return "/panel/plugins/webui/files/%s/%s" % (plugin_id, name)

    def upload_url(self, plugin_id, page="index"):
        return "/panel/plugins/webui/upload/%s/%s" % (plugin_id, page)

    # ---------------------------------------------------------------- HTML 断言助手

    @staticmethod
    def strip_tags(value):
        import html as html_module
        import re
        return html_module.unescape(re.sub(r"<[^>]+>", "", value or "")).strip()

    def element_html(self, html, elem_id):
        import re
        ident = chr(92) + 'bid="%s"' % re.escape(elem_id)
        pattern = (r'<(?P<tag>[a-zA-Z0-9]+)[^>]*' + ident + r'[^>]*>'
                   r'(?P<body>.*?)</(?P=tag)>')
        match = re.search(pattern, html or "", re.S)
        return match.group("body") if match else ""

    def element_text(self, html, elem_id):
        return self.strip_tags(self.element_html(html, elem_id))

    @staticmethod
    def live_event_handlers(html):
        """响应里真正**存活**的内联事件属性（on* = 属性本身，不是文本里的同名字符串）。

        用真 HTML 解析器判定：属性值里出现 "onerror=" 是安全的（它只是文本），
        只有 <tag onerror=...> 这种**属性位**上出现才算注入成功。
        """
        import html as html_module
        from html.parser import HTMLParser

        found = []

        class _Scan(HTMLParser):
            def handle_starttag(self, tag, attrs):
                for name, _value in attrs:
                    low = str(name or "").lower()
                    if low.startswith("on"):
                        found.append("<%s %s=...>" % (tag, low))
                    if low in ("href", "src", "action", "formaction"):
                        raw = html_module.unescape(str(_value or "")).strip().lower()
                        if raw.startswith(("javascript:", "vbscript:", "data:text/html")):
                            found.append("<%s %s=%r>" % (tag, low, raw[:40]))

            def handle_startendtag(self, tag, attrs):
                self.handle_starttag(tag, attrs)

        try:
            _Scan(convert_charrefs=False).feed(html or "")
        except Exception:  # noqa: BLE001 - 解析失败时不做断言（交给别的用例）
            return []
        return found


@pytest.fixture(scope="session")
def stack():
    """session 级：真服务器 + 真仓库 + 真管理器 + 真插件进程（只启动一次）。"""
    missing = _missing_examples()
    if missing:
        pytest.skip("BLOCKED BY DEPENDENCY：示例插件尚未落地/不完整 → %s" % ", ".join(missing))
    s = WebUIStack()
    s.start()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(scope="session")
def web(stack):
    """已登录的黑盒客户端（真 cookie 会话）。"""
    stack.authenticate()
    return stack


@pytest.fixture(scope="module", autouse=True)
def fresh_plugin_runtimes(stack):
    """每个测试模块开始前重启一次真插件运行时。

    为什么需要（实测，不是猜测）：插件运行时的 stdout 预算是**累计**的
    （PermissionManager.limits("normal")["max_output_bytes"] = 256 KiB），WebUI 每渲染
    一个页面都要经协议回一次 HTML —— 长会话会把预算耗尽，引擎按设计终止插件并记账为
    plugin_output_overflow（实测 bytes=267444 时被杀，之后所有页面报「插件未启动」）。
    夹具因此按模块重启（真 enable → 真子进程重启），既保持默认保护级别最真实，
    又不让后面的用例看到上一个模块把预算花光的结果。释放的额度也是真实数字。
    """
    for plugin_id in (stack.plugin_a, stack.plugin_b, stack.plugin_c):
        manifest_path = os.path.join(stack.plugin_dir, plugin_id, "manifest.json")
        if not os.path.isfile(manifest_path):
            continue
        approved = list(stack._deployed_manifest(plugin_id).get("permissions") or [])
        ok, why = stack.call(stack.manager.enable(plugin_id, approved_permissions=approved))
        assert ok, "重启插件 %s 失败：%s" % (plugin_id, why)
    yield
