"""Plugin WebUI 访问 gate（manager 级）：未启用/未批准/未声明/未知页/异常降级。"""
import asyncio
import sys

import pytest

sys.path.insert(0, "tests/plugins/webui_example")

from src.plugins.manager import PluginManager


class _Cfg:
    PLUGIN_DIR = "/tmp/pw_gate_plugins"


class _Repo:
    def __init__(self, row=None):
        self._row = row

    def list_plugins(self):
        return []


def _manifest_row(approved=("web_ui",), enabled=True, with_webui=True, manifest=None):
    import json
    from src.plugins.manifest import PluginManifest
    if manifest is None:
        manifest = ("web_ui" if with_webui else None)
    base = {"id": "abc", "name": "ABC", "version": "1.0.0", "runtime": "python",
            "entry": "p.py", "api_version": "1",
            "permissions": list(approved) + ["web_ui"] if with_webui else ["web_ui"],
            }
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

    def _call_hook(self, *a, **k):
        if self._exc:
            raise self._exc
        return self._result


def _manager(row=None, runtime=None):
    if row is None:
        row = _manifest_row()
    repo = _Repo()
    mgr = PluginManager(config=_Cfg(), repository=repo)
    mgr._runtimes["abc"] = runtime or _FakeRuntime({"type": "text", "text": "ok"})
    # monkeypatch get_plugin/_manifest_of
    mgr.get_plugin = lambda pid: row if pid == "abc" else None
    mgr._manifest_of = lambda r: __import__("src.plugins.manifest", fromlist=["PluginManifest"]).PluginManifest.from_json(r["manifest_json"]) if False else _parse(r)
    return mgr


def _parse(row):
    from src.plugins.manifest import PluginManifest
    import json
    return PluginManifest.from_dict(json.loads(row["manifest_json"]))


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
