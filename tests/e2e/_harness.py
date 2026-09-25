"""浏览器 E2E 的可复用启动夹具（真 WebUI 服务器 + 真插件进程，不 Mock Core）。

三件事，三个层次，缺哪一层就**如实 BLOCKED**（绝不 PASS）：

1. **引擎层**（本机就能跑）：真 `PluginManager` + 真插件子进程 + 真 Core Router。
   见 `tests/e2e/test_plugin_chain_engine.py`。
2. **服务器层**：`_serve.py` 里真 `WebUIServer`（aiohttp，与 main.py 组装方式一致）监听
   127.0.0.1 的临时端口；本进程用 HTTP 访问（登录 / 页面 / 静态资源 / POST 表单）。
3. **浏览器层**：Python Playwright + Chromium。装不上 -> `BLOCKED BY ENVIRONMENT: ...`，
   skip 里写明缺什么（`pytest -rs` 会打印）。

被依赖的外部条件（缺任何一项，相关用例就以 BLOCKED 理由 skip，而不是失败、更不是假装通过）：

* `playwright` 包 + Chromium 浏览器（`pip install playwright && playwright install --with-deps chromium`）
* 服务端依赖：`aiohttp` / `pydantic` / `pydantic-settings` / `httpx` / `loguru` / `python-dotenv`
* 编译型语言工具链（Go / Rust / JDK / Node）：见 `tests/sdk/harness.py:missing_reason`（同一份口径）

页面契约（`tests/e2e/fixtures/plugins/webui_e2e_py`，也是给其它语言入口插件的最小契约）见
`tests/e2e/README.md`。
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

__all__ = ["BLOCKED", "CHAINS", "FIXTURE_PLUGIN_ID", "ServerHandle", "chain_blocked_reason",
           "chain_languages", "chain_plugin_ids", "copy_plugin", "language_blocked_reason",
           "launch_server", "playwright_status", "provision_plugins", "server_dependency_status",
           "temp_dir", "wait_for_page_text"]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """**不**自动跟随 3xx。

    本机 drill 抓到的真 bug：@POST /panel/login 成功@ 返回 302 + @Set-Cookie: fb_token@，
    urllib 默认跟随重定向后拿到的最终响应里没有 Set-Cookie，登录 cookie 就丢了。
    所以这里显式关掉重定向，让调用方看到真实的 3xx 与它的响应头。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
E2E_DIR = os.path.join(REPO_ROOT, "tests", "e2e")
FIXTURE_PLUGINS_DIR = os.path.join(E2E_DIR, "fixtures", "plugins")
SERVE_SCRIPT = os.path.join(E2E_DIR, "_serve.py")
MULTILANG_DIR = os.path.join(REPO_ROOT, "examples", "multilang-sdk")

#: 本仓库自带的 E2E 入口插件（页面 id 是断言契约，见 README）
FIXTURE_PLUGIN_ID = "webui_e2e_py"
#: 任务书 §4 要求的专用测试插件（落地后作为**额外的**入口插件一起跑）
CANONICAL_PLUGIN_DIR = os.path.join(REPO_ROOT, "examples", "plugin-webui-test")

ADMIN_USER = "e2e-admin"
ADMIN_PASSWORD = "e2e-secret-123"

BLOCKED = "BLOCKED BY ENVIRONMENT: "

PAGE_IDS = ("index", "settings", "communication")

#: 页面元素 id 契约（§8 断言 + 交互用）
REQUIRED_IDS = {
    "index": ("plugin-name", "plugin-status"),
    "settings": ("plugin-name", "plugin-status", "settings-form", "setting-greeting",
                 "setting-count", "setting-mode", "setting-notify", "settings-submit",
                 "settings-message", "settings-state"),
    "communication": ("plugin-name", "plugin-status", "communication-panel",
                      "communication-target", "communication-method", "communication-request",
                      "communication-route", "communication-submit", "communication-response",
                      "communication-target-runtime", "communication-request-id",
                      "communication-trace-id", "communication-message"),
}

#: 真实浏览器要加载的样式表（§7：不得 404）
STYLE_PATH = "/panel/plugins/webui/%s/static/style.css"

#: 服务器端依赖（缺一不可，缺什么写进 BLOCKED 理由）
SERVER_REQUIREMENTS = ("aiohttp", "pydantic", "pydantic_settings", "httpx", "loguru", "dotenv")

MULTILANG_IDS = {"python": "minimal_py", "typescript": "minimal_ts", "go": "minimal_go",
                 "rust": "minimal_rust", "java": "minimal_java"}

_WORK_ROOT = None


# --------------------------------------------------------------------- 环境探测

def missing_modules(names=SERVER_REQUIREMENTS):
    return [n for n in names if importlib.util.find_spec(n) is None]


def server_dependency_status():
    """(ok, reason)：真 WebUI 服务器 + 真引擎能不能在本机装起来。"""
    missing = missing_modules()
    if missing:
        hint = ""
        if "pydantic" in missing or "pydantic_settings" in missing:
            hint = ("（pydantic v2 依赖 pydantic-core 的 Rust 扩展；Android/aarch64 上 PyPI 没有匹配 "
                    "wheel，本机也没有编译器 —— CI 用 pip install -r requirements.txt 即可）")
        return False, "缺 Python 服务端依赖：%s%s" % (", ".join(missing), hint)
    return True, ""


def playwright_status():
    """(ok, reason_or_path)：Playwright 包 + 浏览器可执行文件是否真的可用。

    注意：import playwright 成功并不代表能跑 —— Playwright 的驱动是自带的 Node 可执行文件，
    Android/bionic 上无法执行（ELF 需要 /lib/ld-linux-aarch64.so.1，且是非 PIE 的 ET_EXEC）。
    所以这里真的去问一次 chromium.executable_path，把真实错误带回来。
    """
    try:
        import playwright  # noqa: F401
    except Exception as exc:  # noqa: BLE001 - 装不上就是环境阻塞，不是测试失败
        return False, "未安装 Playwright Python 包（pip install playwright）：%s: %s" % (
            type(exc).__name__, exc)
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        return False, "Playwright 导入失败：%s: %s" % (type(exc).__name__, exc)
    try:
        with sync_playwright() as pw:
            path = pw.chromium.executable_path
    except Exception as exc:  # noqa: BLE001 - 驱动（自带 node）跑不起来
        return False, ("Playwright 驱动无法启动（%s: %s）——驱动是 Playwright 自带的 Linux/glibc "
                       "Node 可执行文件，Android/bionic 上无法执行" % (type(exc).__name__, exc))
    if not path or not os.path.exists(path):
        return False, "Chromium 未下载：先跑 playwright install --with-deps chromium（期望路径 %s）" % path
    return True, path


def sdk_harness():
    """复用 tests/sdk/harness.py 的工具链口径（单一事实来源）；不可用时返回 None。"""
    try:
        from tests.sdk import harness as sdk
        return sdk
    except Exception:  # noqa: BLE001 - 缺文件时降级为明确理由
        return None


def language_blocked_reason(lang):
    """多语言最小插件能不能真跑；None = 可以。"""
    sdk = sdk_harness()
    if sdk is None:
        return "tests/sdk/harness.py 不可用（多语言构建口径缺失）"
    return sdk.missing_reason(lang)


# --------------------------------------------------------------------- 工作目录

def work_root():
    """可执行位 + 可写的工作根目录（Android /storage 是 FUSE，不支持执行位）。

    顺序：E2E_WORK_ROOT 环境变量 -> 系统临时目录 -> 仓库内 .e2e-work（兜底）。
    """
    global _WORK_ROOT
    if _WORK_ROOT:
        return _WORK_ROOT
    candidates = [os.environ.get("E2E_WORK_ROOT"), tempfile.gettempdir(),
                  os.path.join(REPO_ROOT, ".e2e-work")]
    for cand in candidates:
        if not cand:
            continue
        try:
            os.makedirs(cand, exist_ok=True)
            probe = os.path.join(cand, ".exec-probe.sh")
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write("#!/bin/sh\nexit 0\n")
            os.chmod(probe, 0o755)
            executable = os.access(probe, os.X_OK)
            os.remove(probe)
            if executable:
                _WORK_ROOT = cand
                return _WORK_ROOT
        except OSError:
            continue
    raise RuntimeError("找不到同时可写且支持执行位的工作目录（可用 E2E_WORK_ROOT 指定）")


def temp_dir(prefix="flowerie-e2e-"):
    return tempfile.mkdtemp(prefix=prefix, dir=work_root())


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# --------------------------------------------------------------------- 插件铺设

def read_manifest(plugin_dir):
    with open(os.path.join(plugin_dir, "manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)


def copy_plugin(source_dir, plugins_root, plugin_id=None):
    """把插件铺到 <plugins_root>/<id>（目录名必须等于 manifest id：引擎按 id 拼路径）。"""
    manifest = read_manifest(source_dir)
    pid = plugin_id or str(manifest["id"])
    dest = os.path.join(plugins_root, pid)
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    shutil.copytree(source_dir, dest)
    return pid, dest


def deploy_language(lang, plugins_root):
    """真编译（有工具链时）+ 铺进插件目录；返回 (plugin_id, 目录)。

    构建失败**不**降级为 skip：有工具链却编不过，是真的红（与 tests/sdk 口径一致）。
    """
    sdk = sdk_harness()
    if sdk is None:
        raise RuntimeError("tests/sdk/harness.py 不可用")
    built = sdk.build_minimal(lang)           # 真 build.sh（编译型语言），失败即 AssertionError
    source = built.get("dir") or os.path.join(MULTILANG_DIR, lang)
    return copy_plugin(source, plugins_root)


def provision_plugins(root, langs=(), include_fixture=True):
    """建插件目录：E2E 夹具插件 + 需要参与链路的多语言最小插件（真构建产物）。

    返回 {"plugins_root":…, "ids":{lang: plugin_id}, "errors":{lang: reason}}
    """
    plugins_root = os.path.join(root, "plugins")
    os.makedirs(plugins_root, exist_ok=True)
    ids = {}
    errors = {}
    if include_fixture:
        ids["fixture"] = copy_plugin(os.path.join(FIXTURE_PLUGINS_DIR, FIXTURE_PLUGIN_ID),
                                     plugins_root)[0]
    for lang in langs:
        reason = language_blocked_reason(lang)
        if reason:
            errors[lang] = reason
            continue
        pid, _dest = deploy_language(lang, plugins_root)
        ids[lang] = pid
    return {"plugins_root": plugins_root, "ids": ids, "errors": errors}


# --------------------------------------------------------------------- 服务器

class ServerHandle(object):
    """真 WebUIServer 子进程句柄（HTTP 层的可复用夹具）。"""

    def __init__(self, proc, port, work_dir, log_path, info):
        self.proc = proc
        self.port = int(port)
        self.work_dir = work_dir
        self.log_path = log_path
        self.info = info or {}
        self.base_url = "http://127.0.0.1:%d" % self.port
        self.admin_user = ADMIN_USER
        self.admin_password = ADMIN_PASSWORD
        self._cookie = None

    # ---- 生命周期 ----
    def stop(self, timeout=20):
        if self.proc is None or self.proc.poll() is not None:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=timeout)
        except Exception:  # noqa: BLE001 - 收尾尽力而为
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass

    def logs(self, limit=4000):
        try:
            with open(self.log_path, encoding="utf-8", errors="replace") as fh:
                return fh.read()[-limit:]
        except OSError:
            return ""

    # ---- HTTP ----
    def url(self, path):
        return self.base_url + path

    def page_url(self, plugin_id, page_id):
        return "%s/panel/plugins/webui/%s/%s" % (self.base_url, plugin_id, page_id)

    def request(self, path, data=None, cookie=None, method=None, timeout=30):
        """极简 HTTP 客户端（stdlib）：返回 (status, headers, body_text, set_cookie)。"""
        url = self.url(path)
        body = None
        headers = {"Accept": "text/html"}
        if data is not None:
            body = urllib.parse.urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if cookie:
            headers["Cookie"] = cookie
        req = urllib.request.Request(url, data=body, headers=headers,
                                     method=method or ("POST" if body else "GET"))
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
                return resp.status, dict(resp.headers), raw, resp.headers.get("Set-Cookie", "")
        except urllib.error.HTTPError as exc:                     # 4xx/5xx 也要能断言
            raw = exc.read().decode("utf-8", "replace")
            return exc.code, dict(exc.headers or {}), raw, (exc.headers or {}).get("Set-Cookie", "")

    def login(self):
        """表单登录（与浏览器完全同一条路径：POST /panel/login + fb_token Cookie）。"""
        status, _headers, body, set_cookie = self.request(
            "/panel/login", data={"username": self.admin_user, "password": self.admin_password})
        token = ""
        for part in str(set_cookie or "").split(";"):
            if part.strip().startswith("fb_token="):
                token = part.strip()
        if not token:
            raise AssertionError("登录失败（HTTP %s，期望 302 + Set-Cookie: fb_token）：页面片段 %r；"
                                 "服务器日志尾部：\n%s" % (status, body[:200], self.logs(1500)))
        self._cookie = token
        return token

    @property
    def cookie(self):
        return self._cookie or self.login()


def launch_server(plugins_root, enable=(), work_dir=None, admin_user=ADMIN_USER,
                  admin_password=ADMIN_PASSWORD, timeout=120):
    """拉起真 WebUIServer 子进程；返回 ServerHandle（失败时抛 AssertionError 带日志尾部）。"""
    work_dir = work_dir or temp_dir("flowerie-e2e-srv-")
    data_dir = os.path.join(work_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    port = free_port()
    ready_path = os.path.join(work_dir, "ready.json")
    log_path = os.path.join(work_dir, "server.log")
    cmd = [sys.executable, SERVE_SCRIPT,
           "--plugin-dir", plugins_root,
           "--data-dir", data_dir,
           "--port", str(port),
           "--ready-file", ready_path,
           "--admin-user", admin_user,
           "--admin-password", admin_password]
    for pid in enable:
        cmd += ["--enable", pid]
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    log = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(cmd, cwd=work_dir, stdout=log, stderr=subprocess.STDOUT, env=env)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise AssertionError("WebUI 服务器子进程提前退出（exit=%s）：\n%s"
                                 % (proc.returncode, _tail(log_path)))
        if os.path.isfile(ready_path):
            try:
                with open(ready_path, encoding="utf-8") as fh:
                    info = json.load(fh)
            except ValueError:
                info = {}
            if info.get("ok"):
                handle = ServerHandle(proc, info.get("port") or port, work_dir, log_path, info)
                if _wait_http(handle, deadline):
                    return handle
        time.sleep(0.2)
    proc.terminate()
    raise AssertionError("WebUI 服务器启动超时（%ss）：\n%s" % (timeout, _tail(log_path)))


def _wait_http(handle, deadline):
    while time.time() < deadline:
        try:
            status, _h, _b, _c = handle.request("/panel", timeout=5)
            if status in (200, 302, 303):
                return True
        except Exception:  # noqa: BLE001 - 还没起来
            time.sleep(0.2)
    return False


def _tail(path, limit=4000):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()[-limit:]
    except OSError:
        return "（没有日志）"


# --------------------------------------------------------------------- 链路编排

#: §28 三条最低 E2E 链路：入口插件（提供 WebUI 页面）-> 目标插件（另一个真进程）
CHAINS = {
    1: {"name": "E2E-1 Browser -> Python WebUI -> Python 插件 -> Go 插件 -> 回 Browser",
        "entry_lang": None,          # None = 用 tests/e2e 自带夹具入口插件
        "entry_env": "E2E_CHAIN1_ENTRY",
        "target_lang": "go", "target_env": "E2E_CHAIN1_TARGET",
        "method": "echo", "request": '{"hello": "world"}'},
    2: {"name": "E2E-2 Browser -> TypeScript WebUI -> TypeScript 插件 -> Java 插件 -> 回 Browser",
        "entry_lang": "typescript", "entry_env": "E2E_CHAIN2_ENTRY",
        "target_lang": "java", "target_env": "E2E_CHAIN2_TARGET",
        "method": "echo", "request": '{"hello": "world"}'},
    3: {"name": "E2E-3 Browser -> Go WebUI -> Go 插件 -> Rust 插件 -> 回 Browser",
        "entry_lang": "go", "entry_env": "E2E_CHAIN3_ENTRY",
        "target_lang": "rust", "target_env": "E2E_CHAIN3_TARGET",
        "method": "echo", "request": '{"hello": "world"}'},
}


def chain_plugin_ids(chain):
    """链路用到的入口/目标插件 id（env 可覆盖，便于对接到别的插件包）。"""
    spec = CHAINS[chain]
    ids = {}
    entry_env = os.environ.get(spec["entry_env"])
    if entry_env:
        ids["entry"] = entry_env
    elif spec["entry_lang"]:
        ids["entry"] = MULTILANG_IDS[spec["entry_lang"]]
    else:
        ids["entry"] = FIXTURE_PLUGIN_ID
    ids["target"] = os.environ.get(spec["target_env"]) or MULTILANG_IDS[spec["target_lang"]]
    return ids


def chain_languages(chain):
    """该链路需要真构建/真启动的语言列表。"""
    spec = CHAINS[chain]
    langs = []
    for key in ("entry_lang", "target_lang"):
        lang = spec[key]
        if lang and lang not in langs:
            langs.append(lang)
    return langs


def plugin_webui_pages(plugin_dir):
    """插件 manifest 声明的 WebUI 页面 id 列表（没有 WebUI 就是空列表）。"""
    try:
        manifest = read_manifest(plugin_dir)
    except (OSError, ValueError):
        return []
    web_ui = manifest.get("web_ui") or {}
    return [str(p.get("id")) for p in (web_ui.get("pages") or []) if isinstance(p, dict)]


def chain_blocked_reason(chain, provision):
    """链路能不能跑；None = 可以。理由必须写清**缺什么**。"""
    spec = CHAINS[chain]
    missing = []
    for lang in chain_languages(chain):
        reason = language_blocked_reason(lang)
        if reason:
            missing.append("%s：%s" % (lang, reason))
        elif lang in (provision.get("errors") or {}):
            missing.append("%s：%s" % (lang, provision["errors"][lang]))
    if missing:
        return "；".join(missing)
    ids = chain_plugin_ids(chain)
    if spec["entry_lang"]:
        entry_dir = os.path.join(MULTILANG_DIR, spec["entry_lang"])
        pages = plugin_webui_pages(entry_dir)
        if "communication" not in pages:
            return ("入口插件 %s（%s）没有声明 communication 页面（当前 pages=%s）—— %s 需要入口"
                    "插件自带 WebUI 页面，契约见 tests/e2e/README.md"
                    % (ids["entry"], entry_dir, pages or "无", spec["name"]))
    return None


# --------------------------------------------------------------------- 浏览器会话 / 登录

class BrowserSession(object):
    """一个浏览器上下文 + 页面，外加控制台/脚本错误/响应失败的收集器（断言"零 JS"用）。"""

    def __init__(self, page, context=None):
        self.page = page
        self.context = context
        self.page_errors = []
        self.console_messages = []
        self.failed_responses = []
        page.on("pageerror", lambda exc: self.page_errors.append(str(exc)))
        page.on("console", lambda msg: self.console_messages.append("%s: %s" % (msg.type, msg.text)))
        page.on("response", self._on_response)

    def _on_response(self, response):
        try:
            if response.status >= 400:
                self.failed_responses.append("%s %s" % (response.status, response.url))
        except Exception:  # noqa: BLE001 - 浏览器关闭时的竞态，忽略
            pass

    def goto(self, url):
        self.page.goto(url, wait_until="domcontentloaded")
        return self.page

    def close(self):
        if self.context is not None:
            try:
                self.context.close()
            except Exception:  # noqa: BLE001 - 浏览器已关时忽略
                pass
            self.context = None


def form_login(session, server):
    """先用登录页表单登录（fill + click，不是注入 Cookie）—— 这就是真实用户路径。"""
    session.goto(server.base_url + "/panel")
    page = session.page
    page.fill('input[name="username"]', server.admin_user)
    page.fill('input[name="password"]', server.admin_password)
    page.click('form[action="/panel/login"] button[type="submit"]')
    page.wait_for_load_state("domcontentloaded")
    assert page.locator('form[action="/panel/login"]').count() == 0, (
        "登录失败：仍然停留在登录页（URL=%s）" % page.url)
    return page


def wait_for_page_text(handle, plugin_id, page_id, needle, timeout=30):
    """轮询页面直到出现某段文本（插件进程启动有延迟时用）。"""
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        _status, _headers, body, _cookie = handle.request(
            "/panel/plugins/webui/%s/%s" % (plugin_id, page_id), cookie=handle.cookie)
        last = body
        if needle in body:
            return body
        time.sleep(0.5)
    raise AssertionError("等待 %s/%s 出现 %r 超时；页面片段：\n%s"
                         % (plugin_id, page_id, needle, last[:1200]))
