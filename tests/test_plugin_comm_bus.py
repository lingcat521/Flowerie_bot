"""Plugin-to-Plugin 通信总线（任务书《通信》§五–§二十三）：真子进程、真管道、真 Core Router。

**不起 Mock**：每个插件都是真实的 Python 插件进程（python -I python_runner.py），调用真的
穿过 Core：身份（按连接）→ 环保护 → 路由 → 权限 → 投递 → 超时/取消 → 事件广播。
跨语言路径另见 tests/test_plugin_comm_paths.py。
"""
import asyncio
import json
import os

import pytest

from src.plugins import comm
from src.plugins.manager import PluginManager
from src.plugins.manifest import PluginManifest

#: 真插件源码：暴露方法、订阅事件、并用 SDK 发起调用（reverse op 路径）
PLUGIN_TEMPLATE = '''"""测试用真插件：把插件间通信的每条路径都跑一遍。"""
import os
import time

STATE = {"calls": [], "events": [], "cancelled": []}
API = {"api": None}


def on_startup(context, api=None):
    API["api"] = api
    api.plugin.expose("get_status", _get_status)
    api.plugin.expose("seen", _seen)
    api.plugin.expose("slow", _slow)
    api.plugin.expose("boom", _boom)
    api.plugin.expose("lang_object", _lang_object)
    api.plugin.expose("ping", _ping)
    api.plugin.expose("pong", _pong)
    api.plugin.on("weather.updated", _on_event)
    return None


def _where():
    return os.path.basename(os.path.dirname(os.path.abspath(__file__)))


def _get_status(req):
    STATE["calls"].append(req.get("params"))
    return {"plugin_id": "__PLUGIN_NAME__", "dir": _where(), "runtime": "python",
            "trace_id": req.get("trace_id"), "hop_count": req.get("hop_count"),
            "echo": req.get("params")}


def _seen(req):
    return {"calls": len(STATE["calls"]), "events": list(STATE["events"]),
            "cancelled": API["api"].plugin.cancelled_requests()}


def _slow(req):
    time.sleep(1.5)
    return {"slept": True}


def _boom(req):
    raise RuntimeError("插件内部炸了")


def _lang_object(req):
    class OnlyHere:
        pass

    return {"bad": OnlyHere()}


def _ping(req):
    """回弹给来源插件：A -> B -> A -> ... 用来验证 §二十二 环保护真的在真实链路上生效。"""
    return {"bounced": API["api"].plugin.call(req["source"]["plugin_id"], "pong", {})}


def _pong(req):
    return {"bounced": API["api"].plugin.call(req["source"]["plugin_id"], "ping", {})}


def _on_event(req):
    STATE["events"].append({"name": req.get("name"), "payload": req.get("payload")})
    return {"ok": True}


def comm_call(target, method, params=None, timeout=None):
    """hook：让测试真实驱动本插件走一次 plugin.call（反向 op -> Core -> 目标）。"""
    try:
        kwargs = {} if timeout is None else {"timeout": timeout}
        return {"ok": True, "result": API["api"].plugin.call(target, method, params or {}, **kwargs)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "code": getattr(e, "code", "PLUGIN_ERROR"), "message": str(e)}


def comm_emit(name, payload=None):
    return API["api"].plugin.emit(name, payload or {})


def comm_cancel(request_id, reason=""):
    return API["api"].plugin.cancel(request_id, reason)
'''


class _Repo:
    """最小插件仓库桩：只提供引擎真正读的几个字段（不是 Mock 通信，通信全是真的）。"""

    def __init__(self):
        self.rows = {}

    def get_plugin(self, plugin_id):
        return self.rows.get(plugin_id)

    def list_plugins(self):
        return list(self.rows.values())

    def upsert_plugin(self, row):
        self.rows[row["id"]] = row


class _Cfg:
    def __init__(self, plugin_dir):
        self.PLUGIN_DIR = plugin_dir


class Rig:
    """一套真插件运行环境：真 PluginManager + 真子进程 + 真 Core Router。"""

    def __init__(self, tmp_path):
        self.root = str(tmp_path)
        self.plugin_dir = os.path.join(self.root, "plugins")
        os.makedirs(self.plugin_dir, exist_ok=True)
        self.repo = _Repo()
        self.mgr = PluginManager(config=_Cfg(self.plugin_dir), repository=self.repo, sender=None)
        self.manifests = {}
        self.runtimes = {}
        self.approved = {}
        self.mgr._manifest_of = lambda row: self.manifests.get(row["id"])

    def make_plugin(self, plugin_id, permissions=("plugin.call.*", "plugin.emit"),
                    dir_name=None, source=None, web_ui=None):
        directory = os.path.join(self.plugin_dir, dir_name or plugin_id)
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, "plugin.py"), "w", encoding="utf-8") as fh:
            fh.write(source if source is not None else
                     PLUGIN_TEMPLATE.replace("__PLUGIN_NAME__", plugin_id))
        manifest = {"id": plugin_id, "name": plugin_id, "version": "1.0.0", "runtime": "python",
                    "entry": "plugin.py", "api_version": "1", "permissions": list(permissions)}
        if web_ui:
            manifest["web_ui"] = web_ui
        with open(os.path.join(directory, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)
        return directory

    async def start(self, plugin_id, approved=None, permissions=("plugin.call.*", "plugin.emit"),
                    dir_name=None, source=None, web_ui=None):
        directory = self.make_plugin(plugin_id, permissions, dir_name, source, web_ui)
        manifest_path = os.path.join(directory, "manifest.json")
        manifest = PluginManifest.load(manifest_path)
        with open(manifest_path, encoding="utf-8") as fh:
            raw_manifest = json.load(fh)
        self.manifests[plugin_id] = manifest
        # 仓库行与真实 SettingsRepository 同形：approved_permissions 是 CSV 字符串
        self.approved[plugin_id] = list(approved if approved is not None else permissions)
        self.repo.rows[plugin_id] = {
            "id": plugin_id, "manifest_json": json.dumps(raw_manifest),
            "enabled": True, "approved_permissions": ",".join(self.approved[plugin_id]),
            "protection": "normal", "status": "running", "install_source": "test",
        }
        rt = self.mgr._start_runtime(plugin_id, manifest,
                                     list(approved if approved is not None else permissions),
                                     "normal")
        await rt.start()
        self.runtimes[plugin_id] = rt
        return rt

    async def hook(self, plugin_id, name, *args):
        """经真协议调用插件的 hook（引擎侧同一条通道）。"""
        return await PluginManager._runtime_hook_call(self.runtimes[plugin_id], name, *args)

    async def call(self, caller_id, target, method, params=None, **kw):
        request = comm.make_request(target, method, params or {}, **kw)
        return await self.mgr._comm_bus.call(caller_id, request,
                                             approved=self.approved.get(caller_id, []))

    async def close(self):
        for rt in list(self.runtimes.values()):
            try:
                await rt.shutdown()
            except Exception:  # noqa: BLE001
                pass
        self.runtimes.clear()


class _RigCtx:
    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.rig = None

    async def __aenter__(self):
        self.rig = Rig(self.tmp_path)
        return self.rig

    async def __aexit__(self, *exc):
        await self.rig.close()
        return False


# ---------------------------------------------------------------- §五/§六/§七 基本调用

@pytest.mark.asyncio
async def test_python_to_python_call_through_core(tmp_path):
    async with _RigCtx(tmp_path) as rig:
        await rig.start("comm_a")
        await rig.start("comm_b")
        out = await rig.hook("comm_a", "comm_call", "comm_b", "get_status", {"q": 1})
        assert out["ok"] is True, out
        result = out["result"]
        assert result["plugin_id"] == "comm_b" and result["runtime"] == "python"
        assert result["echo"] == {"q": 1}
        assert result["hop_count"] == 1, "引擎转发时必须 hop+1（§二十二）"
        assert isinstance(result["trace_id"], str) and result["trace_id"]
        stats = rig.mgr.comm_snapshot()
        assert stats["calls"] >= 1 and stats["calls_ok"] >= 1 and stats["by_route"] == {"core": 1}


@pytest.mark.asyncio
async def test_trace_id_is_propagated_end_to_end(tmp_path):
    async with _RigCtx(tmp_path) as rig:
        await rig.start("comm_a")
        await rig.start("comm_b")
        resp = await rig.call("comm_a", "comm_b", "get_status", {"q": 2}, trace_id="trace-abc")
        assert resp["ok"] is True
        assert resp["result"]["trace_id"] == "trace-abc"
        assert resp["result"]["hop_count"] == 1


@pytest.mark.asyncio
async def test_caller_identity_is_decided_by_core_not_by_the_plugin(tmp_path):
    """§四 安全不变式：插件自报的 source 一律被引擎覆盖，不能冒充别人。"""
    async with _RigCtx(tmp_path) as rig:
        await rig.start("comm_a")
        await rig.start("comm_b")
        forged = comm.make_request("comm_b", "get_status", {"forged": True},
                                   source={"plugin_id": "someone.else", "runtime": "go"})
        resp = await rig.mgr._comm_bus.call("comm_a", forged,
                                            approved=rig.approved["comm_a"])
        assert resp["ok"] is True
        # 目标看到的来源是 comm_a（真实连接身份），不是被伪造的 someone.else
        assert resp["result"]["trace_id"] == forged["trace_id"]
        forced = await rig.hook("comm_a", "comm_call", "comm_b", "get_status", {"forged2": 1})
        assert forced["ok"] is True


# ---------------------------------------------------------------- §十四/§十五 权限

@pytest.mark.asyncio
async def test_call_without_permission_is_denied_and_not_delivered(tmp_path):
    async with _RigCtx(tmp_path) as rig:
        await rig.start("comm_a")
        await rig.start("comm_b")
        await rig.start("comm_c", approved=[], permissions=[])      # 没有任何调用权限
        out = await rig.hook("comm_c", "comm_call", "comm_b", "get_status", {})
        assert out["ok"] is False and out["code"] == "PERMISSION_DENIED", out
        seen = await rig.call("comm_a", "comm_b", "seen")
        assert seen["result"]["calls"] == 0, "权限拒绝时目标插件绝不能收到调用"
        assert rig.mgr.comm_snapshot()["denied"] >= 1


@pytest.mark.asyncio
async def test_fine_grained_permission_allows_one_method_only(tmp_path):
    async with _RigCtx(tmp_path) as rig:
        await rig.start("comm_b")
        await rig.start("comm_a", approved=["plugin.call.comm_b.get_status"],
                        permissions=["plugin.call.comm_b.get_status"])
        ok = await rig.hook("comm_a", "comm_call", "comm_b", "get_status", {})
        assert ok["ok"] is True, ok
        denied = await rig.hook("comm_a", "comm_call", "comm_b", "seen", {})
        assert denied["ok"] is False and denied["code"] == "PERMISSION_DENIED", denied


@pytest.mark.asyncio
async def test_emit_requires_emit_permission(tmp_path):
    async with _RigCtx(tmp_path) as rig:
        await rig.start("comm_a")
        await rig.start("comm_b")
        await rig.start("comm_c", approved=[], permissions=[])
        out = await rig.hook("comm_c", "comm_emit", "weather.updated", {"city": "上海"})
        assert out["ok"] is False and out["error"]["code"] == "PERMISSION_DENIED", out


# ---------------------------------------------------------------- §十七 生命周期与寻址

@pytest.mark.asyncio
async def test_unknown_target_is_structured_not_found(tmp_path):
    async with _RigCtx(tmp_path) as rig:
        await rig.start("comm_a")
        resp = await rig.call("comm_a", "nobody.here", "get_status")
        assert resp["ok"] is False and resp["error"]["code"] == "PLUGIN_NOT_FOUND"
        assert resp["error"]["data"]["plugin_id"] == "nobody.here"


@pytest.mark.asyncio
async def test_unknown_method_is_method_not_found(tmp_path):
    async with _RigCtx(tmp_path) as rig:
        await rig.start("comm_a")
        await rig.start("comm_b")
        out = await rig.hook("comm_a", "comm_call", "comm_b", "no_such_method", {})
        assert out["ok"] is False and out["code"] == "METHOD_NOT_FOUND", out


@pytest.mark.asyncio
async def test_stopped_plugin_is_unavailable_not_missing(tmp_path):
    async with _RigCtx(tmp_path) as rig:
        await rig.start("comm_a")
        await rig.start("comm_b")
        rig.mgr._stop_runtime("comm_b")
        await asyncio.sleep(0.2)
        resp = await rig.call("comm_a", "comm_b", "get_status")
        assert resp["ok"] is False
        assert resp["error"]["code"] == comm.LIFECYCLE_ERROR_CODE, resp


@pytest.mark.asyncio
async def test_plugin_internal_exception_becomes_plugin_error(tmp_path):
    async with _RigCtx(tmp_path) as rig:
        await rig.start("comm_a")
        await rig.start("comm_b")
        out = await rig.hook("comm_a", "comm_call", "comm_b", "boom", {})
        assert out["ok"] is False and out["code"] == "PLUGIN_ERROR", out


@pytest.mark.asyncio
async def test_language_object_return_is_serialization_error(tmp_path):
    async with _RigCtx(tmp_path) as rig:
        await rig.start("comm_a")
        await rig.start("comm_b")
        out = await rig.hook("comm_a", "comm_call", "comm_b", "lang_object", {})
        assert out["ok"] is False and out["code"] == "SERIALIZATION_ERROR", out


# ---------------------------------------------------------------- §十六 实例寻址

@pytest.mark.asyncio
async def test_instance_addressing_and_any_healthy_instance(tmp_path):
    async with _RigCtx(tmp_path) as rig:
        await rig.start("comm_a")
        await rig.start("comm_b")
        # 第二个真实实例：同一个 plugin_id，不同目录（内容可区分）
        second_dir = rig.make_plugin("comm_b", dir_name="comm_b.instance1")
        manifest = PluginManifest.load(os.path.join(second_dir, "manifest.json"))
        from src.plugins.permissions import PermissionManager
        from src.plugins.runtime import PluginRuntime
        rt2 = PluginRuntime("comm_b", manifest, second_dir, protection="normal")
        rt2.instance_id = "instance1"
        rt2.permissions = PermissionManager(["plugin.call.*", "plugin.emit"], "normal")
        rt2.set_action_handler(rig.mgr._handle_action)
        rt2.set_engine_op_handler(rig.mgr._handle_engine_op)
        await rt2.start()
        rig.mgr._comm_router.register("comm_b", rt2, runtime_name="python",
                                      instance_id="instance1")
        try:
            any_instance = await rig.call("comm_a", "comm_b", "get_status")
            assert any_instance["result"]["dir"] == "comm_b"
            specific = await rig.call("comm_a", "comm_b#instance1", "get_status")
            assert specific["result"]["dir"] == "comm_b.instance1", specific
            missing = await rig.call("comm_a", "comm_b#nope", "get_status")
            assert missing["error"]["code"] == "PLUGIN_NOT_FOUND"
            assert missing["error"]["data"]["available"] == ["0", "instance1"]
            # 主实例停掉后，"任意健康实例" 必须落到还活着的那个
            rig.mgr._stop_runtime("comm_b")
            await asyncio.sleep(0.2)
            fallback = await rig.call("comm_a", "comm_b", "get_status")
            assert fallback["ok"] is True and fallback["result"]["dir"] == "comm_b.instance1"
        finally:
            await rt2.shutdown()


# ---------------------------------------------------------------- §十八 超时与取消

@pytest.mark.asyncio
async def test_timeout_returns_timeout_and_sends_cancel(tmp_path):
    async with _RigCtx(tmp_path) as rig:
        await rig.start("comm_a")
        await rig.start("comm_b")
        out = await rig.hook("comm_a", "comm_call", "comm_b", "slow", {}, 200)
        assert out["ok"] is False and out["code"] == "TIMEOUT", out
        assert out["message"].find("200") >= 0
        await asyncio.sleep(2.0)                    # 目标跑完 sleep 后才会读到 CANCEL
        seen = await rig.call("comm_a", "comm_b", "seen")
        assert seen["result"]["cancelled"], "超时后必须向目标发 CANCEL（§十八）"
        stats = rig.mgr.comm_snapshot()
        assert stats["timeouts"] >= 1 and stats["cancels_sent"] >= 1
        assert not rig.mgr._comm_bus._inflight, "超时后不能留下在途请求"


# ---------------------------------------------------------------- §九 事件广播

@pytest.mark.asyncio
async def test_event_broadcast_reaches_other_plugins_only(tmp_path):
    async with _RigCtx(tmp_path) as rig:
        await rig.start("comm_a")
        await rig.start("comm_b")
        out = await rig.hook("comm_a", "comm_emit", "weather.updated", {"city": "上海"})
        assert out["ok"] is True and out["delivered"] == 1, out
        seen_b = await rig.call("comm_a", "comm_b", "seen")
        assert seen_b["result"]["events"] == [{"name": "weather.updated",
                                               "payload": {"city": "上海"}}]
        seen_a = await rig.call("comm_b", "comm_a", "seen")
        assert seen_a["result"]["events"] == [], "广播不回给发送者自己"
        assert rig.mgr.comm_snapshot()["events_delivered"] >= 1


# ---------------------------------------------------------------- §二十二 循环保护

@pytest.mark.asyncio
async def test_call_loop_is_stopped_with_plugin_call_loop(tmp_path):
    async with _RigCtx(tmp_path) as rig:
        await rig.start("comm_a")
        await rig.start("comm_b")
        out = await rig.hook("comm_b", "comm_call", "comm_a", "ping", {})
        assert out["ok"] is False, out
        assert out["code"] == "PLUGIN_CALL_LOOP", out
        assert rig.mgr.comm_snapshot()["loop_aborted"] >= 1
        assert not rig.mgr._comm_bus._inflight


@pytest.mark.asyncio
async def test_hop_count_at_limit_is_refused_before_delivery(tmp_path):
    """引擎侧直接构造一个已达上限的请求：必须立刻 PLUGIN_CALL_LOOP，不得投递。"""
    async with _RigCtx(tmp_path) as rig:
        await rig.start("comm_a")
        await rig.start("comm_b")
        request = comm.make_request("comm_b", "get_status", {},
                                    hop_count=comm.MAX_HOP_COUNT, trace_id="t-loop")
        resp = await rig.mgr._comm_bus.call("comm_a", request, approved=["plugin.call.*"])
        assert resp["error"]["code"] == "PLUGIN_CALL_LOOP"
        seen = await rig.call("comm_a", "comm_b", "seen")
        assert seen["result"]["calls"] == 0


# ---------------------------------------------------------------- §二十五 WebUI 建立在同一协议上

WEBUI_PLUGIN = '''"""插件渲染页 + WebUI Action 里调用另一个插件（任务书第 4 份 §二十五）。"""

API = {"api": None}


def on_startup(context, api=None):
    API["api"] = api
    api.plugin.expose("get_status", _get_status)
    return None


def _get_status(req):
    return {"runtime": "python", "who": "__PLUGIN_NAME__", "echo": req.get("params")}


def webui_render(page, context):
    return "<html><body><p>ok</p></body></html>"


def webui_action(page, action, form, context):
    """WebUI Action -> Plugin SDK -> Plugin Router -> 另一个插件（不另造机制）。"""
    target = str(form.get("target") or "")
    result = API["api"].plugin.call(target, "get_status", {"from": "webui", "action": action})
    return {"ok": True, "vars": {"other_runtime": result["runtime"],
                                 "other_plugin": result["plugin_id"],
                                 "other_echo": result["echo"]}}
'''


@pytest.mark.asyncio
async def test_webui_action_drives_plugin_to_plugin_call(tmp_path):
    """§二十五：WebUI Action 直接建立在插件间通信协议之上，没有第二套机制。"""
    async with _RigCtx(tmp_path) as rig:
        await rig.start("comm_b")
        await rig.start(
            "comm_ui", source=WEBUI_PLUGIN,
            permissions=["plugin.call.*", "plugin.emit", "webui.view", "webui.action"],
            web_ui={"pages": [{"id": "home", "title": "Home", "render": "plugin"}]})
        result, err = await rig.mgr.plugin_webui_render("comm_ui", "home", "refresh",
                                                        values={"target": "comm_b"})
        assert err == "", err
        assert result["vars"]["other_runtime"] == "python", result["vars"]
        assert result["vars"]["other_plugin"] == "comm_b", result["vars"]
        assert result["vars"]["other_echo"] == {"from": "webui", "action": "refresh"}
