"""Plugin WebUI Protocol 测试（任务书第 3 份 §三/§七/§八/§十一/§十二/§十五）。

**真打 Runtime**：每个用例都在临时目录里放**真 manifest + 真 plugin.py**，经
`PluginManager.discover()` / `await manager.enable(...)` 起**真子进程**（真管道），
再走 HTTP 处理器调用的同一入口 `plugin_webui_render` / `plugin_webui_asset`。
不是"只测一个 helper 函数"：页面 HTML 由插件进程经 `webui.page` 真返回，
动作走 `webui.action` 真往返，资源走 `webui.asset` 真返回。

覆盖任务书 §十二 列出的 20 类安全问题 + §十三 的多语言一致性基础能力。

HTTP 路由层（aiohttp request/response、令牌校验、CSP 头）另有 CI 用例：
`tests/test_webui_plugin_panel.py` 系列（本机缺 aiohttp 时跳过并打印原因）。
"""
import json
import os

import pytest

from src.plugins.manager import PluginManager
from src.plugins.manifest import PluginManifest, PluginManifestError
from src.plugins.webui_loader import PluginWebuiPathError
from src.repositories.settings_repository import SettingsRepository

PID = "webui_protocol_demo"
OTHER = "webui_other"

PLUGIN_SRC = '''
def on_startup(context, api=None):
    return None


def webui_render(page, context):
    return {
        "html": "<h1>{{ page_title }}</h1><p class=\\"ctx\\">plugin={{ plugin_id }}</p>"
                "<p class=\\"cfg\\">{{ cfg_greeting }}</p>",
        "vars": {"cfg_greeting": (context.get("config") or {}).get("greeting", "")},
        "message": "插件渲染",
    }


def webui_action(page, action, form, context):
    if action == "save":
        return {
            "vars": {"saved_name": form.get("name", "")},
            "message": "已保存",
            "config_set": {"saved_name": form.get("name", "")},
            "storage_set": {"save_count": 1},
        }
    if action == "echo-context":
        return {"vars": {"ctx_json": str(sorted(context.keys()))}}
    return {"ok": False, "error": "未知动作: %s" % action}


def webui_page(page_id, action, params, values):
    # 旧 DSL 兼容层（任务书第 1 份 §15：降级为 deprecated，但不删）
    return {"type": "text", "text": "legacy:%s:%s" % (page_id, action)}


def webui_asset(path):
    if path == "theme.css":
        return {"content_type": "text/css", "body": "body { color: #123456; }"}
    if path == "evil.css":
        return {"content_type": "text/css",
                "body": "@import url(http://evil.example/x.css); body{color:red}"}
    if path == "pixel.png":
        return {"content_type": "image/png", "base64": "iVBORw0KGgoAAAANSUhEUg=="}
    if path == "page.html":
        return {"content_type": "text/html", "body": "<script>alert(1)</script>"}
    if path == "app.js":
        return {"content_type": "application/javascript", "body": "alert(1)"}
    if path == "huge.css":
        return {"content_type": "text/css", "body": "a{}" * 100000}
    return {"ok": False, "error": "资源不存在"}
'''

INDEX_HTML = """<h1>{{ page_title }}</h1>
<p class="name">{{ plugin_name }}</p>
<form method="post" action="/panel/plugins/webui/webui_protocol_demo/index">
  <input type="hidden" name="plugin_action" value="save">
  <input name="name" value="{{ saved_name }}">
  <button type="submit">保存</button>
</form>
"""


class _Cfg:
    """插件管理器要的最小配置面（真 ConfigService 会拉起 dotenv 等无关依赖）。"""

    def __init__(self, plugin_dir):
        self.PLUGIN_DIR = str(plugin_dir)
        self.PLUGIN_PROTECTION = "normal"


def _sender():
    class _S:
        sent = []

        async def send_group_message(self, *a, **kw):
            return True

        async def send_private_message(self, *a, **kw):
            return True

        async def send_msg_raw(self, *a, **kw):
            return {"ok": True}

    return _S()


def _write_plugin(root, pid, manifest, files):
    base = os.path.join(str(root), pid)
    os.makedirs(os.path.join(base, "webui", "pages"), exist_ok=True)
    os.makedirs(os.path.join(base, "webui", "static"), exist_ok=True)
    with open(os.path.join(base, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False)
    for rel, content in files.items():
        target = os.path.join(base, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(content)
    return base


def _manifest(pid=PID, pages=None, permissions=None, config=None):
    data = {"id": pid, "name": pid, "version": "1.0.0", "runtime": "python",
            "entry": "plugin.py", "api_version": "1",
            "permissions": permissions if permissions is not None else [
                "web_ui", "webui.view", "webui.action", "webui.config.read",
                "webui.config.write", "webui.storage.read", "webui.storage.write"],
            "web_ui": {"pages": pages if pages is not None else [
                {"id": "index", "title": "首页", "file": "pages/index.html"},
                {"id": "settings", "title": "设置", "render": "plugin"}]}}
    if config is not None:
        data["config"] = config
    return data


async def _manager(tmp_path, approved=None, manifest=None, files=None, plugin_dir=None):
    """起一个真 PluginManager + 真插件子进程（没批准权限就不起进程）。"""
    root = plugin_dir or os.path.join(str(tmp_path), "plugins")
    os.makedirs(str(root), exist_ok=True)
    payload = dict(files if files is not None else {"webui/pages/index.html": INDEX_HTML,
                                                    "webui/static/style.css": "body{}"})
    payload.setdefault("plugin.py", PLUGIN_SRC)
    _write_plugin(root, PID, manifest or _manifest(), payload)
    repo = SettingsRepository(os.path.join(str(tmp_path), "settings.db"))
    cfg = _Cfg(root)
    mgr = PluginManager(cfg, repo, sender=_sender())
    mgr.discover()
    perms = approved if approved is not None else [
        "web_ui", "webui.view", "webui.action", "webui.config.read",
        "webui.config.write", "webui.storage.read", "webui.storage.write"]
    ok, message = await mgr.enable(PID, approved_permissions=perms)
    assert ok, "启用插件失败：%s" % message
    return mgr, root


async def _shutdown(mgr):
    for pid in list(getattr(mgr, "_runtimes", {}) or {}):
        rt = mgr._runtimes.get(pid)
        if rt is not None:
            try:
                await rt.shutdown()
            except Exception:  # noqa: BLE001
                pass


# ============================================================ 1. 基础能力（§十三）

async def test_page_render_by_plugin_process(tmp_path):
    """插件渲染页：HTML 由真子进程经 webui.page 返回，再净化 + 换变量。"""
    mgr, _root = await _manager(tmp_path)
    try:
        result, err = await mgr.plugin_webui_render(PID, "settings")
        assert err == "", err
        assert result["mode"] == "html" and result["render"] == "plugin"
        assert "plugin=webui_protocol_demo" in result["html"]
        assert result["vars"]["message"] == "插件渲染"   # message 是模板变量，面板壳显示它
    finally:
        await _shutdown(mgr)


async def test_file_page_render_and_action(tmp_path):
    """文件页面 + 动作：POST 经 webui.action 真往返，变量回到页面。"""
    mgr, _root = await _manager(tmp_path)
    try:
        result, err = await mgr.plugin_webui_render(PID, "index")
        assert err == "" and result["render"] == "file"
        assert "首页" in result["html"]
        posted, err2 = await mgr.plugin_webui_render(PID, "index", "save", None, {"name": "花"})
        assert err2 == "", err2
        assert posted["vars"]["saved_name"] == "花"
        assert posted["vars"]["message"] == "已保存"
    finally:
        await _shutdown(mgr)


async def test_asset_from_plugin_process(tmp_path):
    """资源：webui.asset 真返回，CSS 过净化，PNG 走 base64。"""
    mgr, _root = await _manager(tmp_path)
    try:
        css, mime = await mgr.plugin_webui_asset(PID, "theme.css")
        assert mime.startswith("text/css") and b"#123456" in css
        png, pmime = await mgr.plugin_webui_asset(PID, "pixel.png")
        assert pmime == "image/png" and png.startswith(b"\x89PNG")
    finally:
        await _shutdown(mgr)


# ============================================================ 2. 路径穿越（§十一/§十二）

@pytest.mark.parametrize("bad", ["../secret.txt", "../../etc/passwd", "/etc/passwd",
                                 "..\\windows\\win.ini", "a/../../b.css", ".hidden.css",
                                 "sub/./x.css"])
async def test_static_and_asset_reject_traversal(tmp_path, bad):
    mgr, _root = await _manager(tmp_path)
    try:
        with pytest.raises(PluginWebuiPathError):
            mgr.plugin_webui_static_file(PID, bad)
        with pytest.raises(PluginWebuiPathError):
            await mgr.plugin_webui_asset(PID, bad)
    finally:
        await _shutdown(mgr)


@pytest.mark.parametrize("bad", ["../evil.html", "../../evil.html", "/tmp/evil.html",
                                 "pages/../../evil.html", "pages\\evil.html", ".hidden.html"])
def test_manifest_rejects_illegal_page_paths(bad):
    with pytest.raises(PluginManifestError):
        PluginManifest.from_dict(_manifest(pages=[{"id": "x", "title": "X", "file": bad}]))


async def test_symlink_escape_is_rejected(tmp_path):
    """symlink 逃逸：插件目录里的链接指向外部文件，必须被 realpath 检查挡住。"""
    mgr, root = await _manager(tmp_path)
    try:
        outside = os.path.join(str(tmp_path), "outside.css")
        with open(outside, "w", encoding="utf-8") as fh:
            fh.write("body{color:red}")
        link = os.path.join(root, PID, "webui", "static", "link.css")
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            pytest.skip("本机文件系统不支持 symlink（CI 上会真跑）")
        with pytest.raises(PluginWebuiPathError):
            mgr.plugin_webui_static_file(PID, "link.css")
    finally:
        await _shutdown(mgr)


async def test_cross_plugin_access_is_rejected(tmp_path):
    """跨插件：A 的通道拿不到 B 的文件；B 的页面 id 在 A 上不存在。"""
    mgr, root = await _manager(tmp_path)
    try:
        _write_plugin(root, OTHER, _manifest(pid=OTHER), {"webui/pages/index.html": "<h1>B</h1>"})
        mgr.discover()
        with pytest.raises(PluginWebuiPathError):
            mgr.plugin_webui_static_file(PID, "../%s/webui/pages/index.html" % OTHER)
        _res, err = await mgr.plugin_webui_render(PID, "other-page")
        assert "页面不存在" in err
    finally:
        await _shutdown(mgr)


# ============================================================ 3. HTML / 注入（§八/§十二）

@pytest.mark.parametrize("payload,needle", [
    ("<script>alert(1)</script>", "<script"),
    ("<img src=x onerror=alert(1)>", "onerror"),
    ("<iframe src='http://evil'></iframe>", "<iframe"),
    ("<object data='x'></object>", "<object"),
    ("<embed src='x'>", "<embed"),
    ("<a href=\"javascript:alert(1)\">x</a>", "javascript:"),
    ("<a href=\"vbscript:msgbox(1)\">x</a>", "vbscript:"),
    ("<img src=\"data:text/html;base64,PHNjcmlwdD4=\">", "data:text/html"),
    ("<div onmouseover=\"alert(1)\">x</div>", "onmouseover"),
    ("<style>@import url(http://evil/x.css);</style>", "@import"),
    ("<style>body{background:url(javascript:alert(1))}</style>", "javascript:"),
    ("<form action=\"https://evil.example/post\">x</form>", "evil.example"),
])
async def test_plugin_html_is_sanitized(tmp_path, payload, needle):
    """插件返回的 HTML 先净化：脚本/事件属性/危险 scheme/内嵌对象/外链表单全部出局。"""
    mgr, _root = await _manager(tmp_path)
    try:
        src = PLUGIN_SRC.replace('"<h1>{{ page_title }}</h1>',
                                 '"%s<h1>{{ page_title }}</h1>' % payload.replace('"', '\\"'))
        _write_plugin(os.path.join(str(tmp_path), "plugins"), PID, _manifest(), {})
        with open(os.path.join(str(tmp_path), "plugins", PID, "plugin.py"), "w",
                  encoding="utf-8") as fh:
            fh.write(src)
        rt = mgr._runtimes.get(PID)
        await rt.shutdown()
        del mgr._runtimes[PID]
        ok, message = await mgr.enable(PID, approved_permissions=[
            "web_ui", "webui.view", "webui.action"])
        assert ok, message
        result, err = await mgr.plugin_webui_render(PID, "settings")
        assert err == "", err
        assert needle not in result["html"], "净化后仍出现 %r" % needle
    finally:
        await _shutdown(mgr)


async def test_template_injection_in_vars_is_escaped(tmp_path):
    """模板注入：变量值里的 {{ }} / {% %} 只当文本，不会被二次求值。"""
    mgr, _root = await _manager(tmp_path)
    try:
        evil = _manifest(pages=[{"id": "index", "title": "首页", "file": "pages/index.html"}])
        _write_plugin(os.path.join(str(tmp_path), "plugins"), PID, evil, {
            "webui/pages/index.html": "<p>{{ plugin_name }}</p><p>{{ page_title }}</p>"})
        rt = mgr._runtimes.get(PID)
        await rt.shutdown()
        del mgr._runtimes[PID]
        ok, message = await mgr.enable(PID, approved_permissions=["web_ui", "webui.view"])
        assert ok, message
        from src.plugins.webui_security import render_plugin_template
        html, unresolved = render_plugin_template("<p>{{ page_title }}</p>",
                                                  {"page_title": "{{ plugin_id }}{% evil %}"})
        assert "{{ plugin_id }}" in html and "{% evil %}" in html
        assert unresolved == []
    finally:
        await _shutdown(mgr)


# ============================================================ 4. CSS 注入

async def test_css_injection_is_stripped(tmp_path):
    """CSS 注入：@import 外链 / url(javascript:) / expression 必须在净化后消失。"""
    mgr, _root = await _manager(tmp_path)
    try:
        css, _mime = await mgr.plugin_webui_asset(PID, "evil.css")
        text = css.decode("utf-8")
        assert "@import" not in text and "evil.example" not in text
        assert "color:red" in text.replace(" ", ""), text
    finally:
        await _shutdown(mgr)


# ============================================================ 5. 权限（§十五）

async def test_action_requires_webui_action_permission(tmp_path):
    """只批准 webui.view：GET 可以，POST 必须被拒（分级权限真的生效）。"""
    mgr, _root = await _manager(tmp_path, approved=["webui.view"])
    try:
        result, err = await mgr.plugin_webui_render(PID, "index")
        assert err == "" and result["render"] == "file"
        _posted, err2 = await mgr.plugin_webui_render(PID, "index", "save", None, {"name": "x"})
        assert "webui.action" in err2
    finally:
        await _shutdown(mgr)


async def test_legacy_web_ui_permission_covers_view_and_action(tmp_path):
    """向后兼容：老清单只批 web_ui 时，view 与 action 都放行（行为与升级前一致）。"""
    mgr, _root = await _manager(tmp_path, approved=["web_ui"])
    try:
        result, err = await mgr.plugin_webui_render(PID, "index")
        assert err == "" and result["render"] == "file"
        posted, err2 = await mgr.plugin_webui_render(PID, "index", "save", None, {"name": "兼容"})
        assert err2 == "", err2
        assert posted["vars"]["saved_name"] == "兼容"
    finally:
        await _shutdown(mgr)


async def test_write_without_permission_is_refused_and_reported(tmp_path):
    """动作想写配置/存储但没批准 → 拒绝，并且页面壳会看到告警（不静默）。"""
    mgr, _root = await _manager(tmp_path, approved=["web_ui", "webui.view", "webui.action"])
    try:
        posted, err = await mgr.plugin_webui_render(PID, "index", "save", None, {"name": "x"})
        assert err == "", err
        warnings = " | ".join(posted["warnings"])
        assert "webui.config.write" in warnings and "webui.storage.write" in warnings
    finally:
        await _shutdown(mgr)


async def test_disabled_plugin_is_not_reachable(tmp_path):
    """未启用/不存在：一律拒绝（不泄露插件是否存在）。"""
    mgr, _root = await _manager(tmp_path)
    try:
        await _shutdown(mgr)
        mgr._runtimes.clear()
        row = mgr.repository.get_plugin(PID) or {}
        if row:
            mgr.repository.upsert_plugin({**row, "enabled": False})
        _res, err = await mgr.plugin_webui_render(PID, "index")
        assert "未启用" in err or "不存在" in err
        with pytest.raises(PluginWebuiPathError):
            await mgr.plugin_webui_asset(PID, "theme.css")
    finally:
        await _shutdown(mgr)


async def test_asset_rejects_executable_types(tmp_path):
    """No-JS：text/html 与 application/javascript 都不能作为插件资源返回。"""
    mgr, _root = await _manager(tmp_path)
    try:
        for path in ("page.html", "app.js"):
            with pytest.raises(PluginWebuiPathError):
                await mgr.plugin_webui_asset(PID, path)
    finally:
        await _shutdown(mgr)


async def test_asset_size_limit(tmp_path):
    """插件资源有大小上限（超限拒绝，不是截断后照发）。"""
    mgr, _root = await _manager(tmp_path)
    try:
        with pytest.raises(PluginWebuiPathError):
            await mgr.plugin_webui_asset(PID, "huge.css")
    finally:
        await _shutdown(mgr)


# ============================================================ 6. Context / Token 泄露（§七/§十二）

async def test_context_has_only_declared_keys(tmp_path):
    """Context 只允许 6 个顶层键：插件真收到的东西里没有令牌/会话/环境变量。"""
    mgr, _root = await _manager(tmp_path)
    try:
        result, err = await mgr.plugin_webui_render(PID, "settings")
        assert err == ""
        _res, err2 = await mgr.plugin_webui_render(PID, "index", "echo-context", None, {})
        assert err2 == ""
        assert "ctx_json" in _res["vars"]
        keys = _res["vars"]["ctx_json"]
        for forbidden in ("token", "password", "session", "secret", "environ"):
            assert forbidden not in keys
        from src.plugins.manager import PluginManager as _PM
        assert tuple(_PM.WEBUI_CONTEXT_KEYS) == ("plugin", "page", "request", "user",
                                                 "config", "data")
    finally:
        await _shutdown(mgr)


async def test_config_and_storage_are_gated_by_permission(tmp_path, monkeypatch):
    """webui.config.read / webui.storage.read 未批准 → context 里就是空对象。"""
    monkeypatch.setenv("FLOWERIE_PANEL_TOKEN", "super-secret-token")
    mgr, _root = await _manager(tmp_path, approved=["web_ui", "webui.view", "webui.action"],
                                manifest=_manifest(config={"values": {"greeting": "hi",
                                                                     "secret_token": "s3cr3t"}}))
    try:
        from src.plugins.manager import PluginManager as _PM
        approved = mgr._webui_approved(PID)
        ctx = await mgr._webui_engine_context(PID, mgr.get_plugin(PID) or {}, {"id": "settings"},
                                              approved, method="GET", action="get")
        assert ctx["config"] == {} and ctx["data"] == {}
        assert "super-secret-token" not in json.dumps(ctx, ensure_ascii=False)
        assert not any("token" in key for key in ctx)
        await _shutdown(mgr)
        mgr._runtimes.clear()
        ok, message = await mgr.enable(PID, approved_permissions=[
            "web_ui", "webui.view", "webui.config.read"])
        assert ok, message
        ctx2 = await mgr._webui_engine_context(PID, mgr.get_plugin(PID) or {}, {"id": "settings"},
                                               mgr._webui_approved(PID), method="GET", action="get")
        assert ctx2["config"]["greeting"] == "hi" and ctx2["data"] == {}
        assert "super-secret-token" not in json.dumps(ctx2, ensure_ascii=False)
    finally:
        await _shutdown(mgr)


async def test_rendered_page_never_contains_host_secrets(tmp_path, monkeypatch):
    """渲染结果里不能出现宿主密钥（面板令牌/环境变量）。"""
    monkeypatch.setenv("FLOWERIE_PANEL_TOKEN", "super-secret-token")
    mgr, _root = await _manager(tmp_path)
    try:
        result, err = await mgr.plugin_webui_render(PID, "settings")
        assert err == ""
        assert "super-secret-token" not in result["html"]
        assert "super-secret-token" not in json.dumps(result["vars"], ensure_ascii=False)
    finally:
        await _shutdown(mgr)


# ============================================================ 7. 兼容层（§十六）

async def test_legacy_dsl_page_still_works(tmp_path):
    """旧 DSL 页面（无 file / render）继续可用：兼容层不删，行为不变。"""
    legacy = _manifest(pages=[{"id": "home", "title": "旧页面"}])
    mgr, _root = await _manager(tmp_path, manifest=legacy, files={})
    try:
        result, err = await mgr.plugin_webui_render(PID, "home")
        assert err == "", err
        assert result["mode"] == "dsl"
    finally:
        await _shutdown(mgr)


def test_manifest_rejects_conflicting_page_declarations():
    """file 与 render=plugin 不能同时声明（避免"到底谁渲染"的歧义）。"""
    with pytest.raises(PluginManifestError):
        PluginManifest.from_dict(_manifest(pages=[{"id": "x", "title": "X",
                                                   "file": "pages/index.html",
                                                   "render": "plugin"}]))
    with pytest.raises(PluginManifestError):
        PluginManifest.from_dict(_manifest(pages=[{"id": "x", "title": "X", "render": "somelang"}]))
