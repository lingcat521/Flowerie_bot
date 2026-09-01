"""Plugin WebUI 访问 gate（manager 级）：未启用/未批准/未声明/未知页/异常降级。"""
import asyncio
import json

from src.plugins.manager import PluginManager
from src.plugins.manifest import PluginManifest


class _Cfg:
    PLUGIN_DIR = "/tmp/pw_gate_plugins"


class _Repo:
    def list_plugins(self):
        return []


def _manifest_row(approved=("web_ui",), enabled=True, with_webui=True):
    base = {"id": "abc", "name": "ABC", "version": "1.0.0", "runtime": "python",
            "entry": "p.py", "api_version": "1", "permissions": ["web_ui"]}
    if with_webui:
        base["web_ui"] = {"pages": [{"id": "home", "title": "总览"}]}
    m = PluginManifest.from_dict(base)
    return {"id": "abc", "name": "ABC", "enabled": enabled,
            "approved_permissions": list(approved), "manifest_json": m.to_json(),
            "install_source": "test", "status": "running"}


class _FakeRuntime:
    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc

    def _call_hook(self, *args, **kwargs):
        if self._exc:
            raise self._exc
        return self._result

    async def request(self, method, params=None, timeout=None):
        """模拟 runtime 同步通道（测试桩：直接走 _call_hook 语义）。"""
        if self._exc:
            return {"error": f"RuntimeError: {self._exc}"}
        name = (params or {}).get("name", "")
        args = (params or {}).get("args", [])
        if callable(name):
            return {"result": self._call_hook(name, *args)}
        return {"result": self._call_hook(*args)}


def _manager(row=None, runtime=None):
    if row is None:
        row = _manifest_row()
    mgr = PluginManager(config=_Cfg(), repository=_Repo())
    mgr._runtimes["abc"] = runtime or _FakeRuntime({"type": "text", "text": "ok"})
    mgr.get_plugin = lambda pid: row if pid == "abc" else None
    mgr._manifest_of = lambda r: PluginManifest.from_dict(json.loads(r["manifest_json"]))
    return mgr


def test_enabled_approved_returns_dsl():
    mgr = _manager()
    result, err = asyncio.run(mgr.plugin_webui_page("abc", "home"))
    assert err == "" and isinstance(result, dict) and result["dsl"]["type"] == "text"


def test_disabled_rejected():
    mgr = _manager(_manifest_row(enabled=False))
    _r, err = asyncio.run(mgr.plugin_webui_page("abc", "home"))
    assert "未启用" in err


def test_not_approved_rejected():
    mgr = _manager(_manifest_row(approved=("send_message",)))
    _r, err = asyncio.run(mgr.plugin_webui_page("abc", "home"))
    assert "web_ui" in err and "未批准" in err


def test_unknown_plugin_rejected():
    mgr = _manager()
    _r, err = asyncio.run(mgr.plugin_webui_page("nope", "home"))
    assert "未启用或不存在" in err


def test_unknown_page_rejected():
    mgr = _manager()
    _r, err = asyncio.run(mgr.plugin_webui_page("abc", "nope"))
    assert "页面不存在" in err


def test_no_webui_declared_rejected():
    mgr = _manager(_manifest_row(with_webui=False))
    _r, err = asyncio.run(mgr.plugin_webui_page("abc", "home"))
    assert "未声明 web_ui" in err


def test_hook_exception_falls_back_to_error():
    mgr = _manager(runtime=_FakeRuntime(exc=RuntimeError("boom")))
    _r, err = asyncio.run(mgr.plugin_webui_page("abc", "home"))
    assert err and "boom" in err


def test_hook_non_dict_rejected():
    mgr = _manager(runtime=_FakeRuntime("not a dict"))
    _r, err = asyncio.run(mgr.plugin_webui_page("abc", "home"))
    assert "非法响应" in err
