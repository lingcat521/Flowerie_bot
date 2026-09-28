
"""旧插件通信通道加固（fix.txt 第一优先）：hop 环保护 + 可配置超时 + 可观测。

覆盖：正常调用与信封字段 / 默认 timeout=3.0 与配置覆盖 / 自递归拒绝 /
A→B→A 环被拦 / 正常 A→B→C 通过 / 超时走配置 / 复用 comm 同一套 hop 判定 / metrics。
"""
import asyncio
import json
import sys
from pathlib import Path

# 仅在需要 SDK 的测试内局部加载（与其它 gap 测试一致，避免全局 path 污染）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin_sdk"))

from src.plugins import comm
from src.plugins.manager import PluginManager


class _Cfg:
    PLUGIN_DIR = "/tmp/legacy_plugins"


class _Repo:
    def list_plugins(self):
        return []


class _Sender:
    pass


class _Rt:
    """假 runtime：实现 request() 走 hook 通道，handler 可 await 任意协程。"""

    def __init__(self, handler=None):
        self.handler = handler
        self.seen = []

    async def request(self, method, params):
        assert method == "hook"
        ev = params["args"][0]
        self.seen.append(ev)
        if self.handler is None:
            return {"result": {"ok": True}}
        return {"result": await self.handler(ev)}


def _mgr(cfg=None):
    return PluginManager(config=cfg or _Cfg(), repository=_Repo(), sender=_Sender())


def _enable(mgr, *pids):
    mgr.get_plugin = lambda pid: {"id": pid, "enabled": True} if pid in pids else None


# ---------- 1) 正常调用：信封带 trace_id / hop_count，在途表用完即清 ----------
def test_legacy_call_normal_and_envelope():
    mgr = _mgr()
    _enable(mgr, "target")
    rt = _Rt()
    mgr._runtimes["target"] = rt
    r = asyncio.run(mgr._run_action("p", "plugin_call",
                                    {"target": "target", "name": "ping", "data": {"a": 1}}))
    assert r["ok"] and r["delivered"] == "target"
    ev = rt.seen[0]
    assert ev["caller"] == "p" and ev["action"] == "plugin_call"
    assert ev["data"] == {"a": 1} and ev["name"] == "ping"
    assert ev["hop_count"] == 1 and ev["trace_id"]
    assert mgr._legacy_hop == {}


# ---------- 2) timeout：默认 3 秒语义，配置可覆盖且被上限夹住 ----------
def test_legacy_call_timeout_default_and_config():
    mgr = _mgr()
    assert mgr._legacy_call_timeout({}) == 3.0
    assert mgr._legacy_call_timeout({"timeout": 5}) == 5.0
    assert mgr._legacy_call_timeout({"timeout": 999}) == 30.0
    assert mgr._legacy_call_timeout({"timeout": "x"}) == 3.0
    cfg = _Cfg()
    cfg.PLUGIN_LEGACY_CALL_TIMEOUT = 7
    cfg.PLUGIN_LEGACY_CALL_TIMEOUT_MAX = 10
    mgr2 = _mgr(cfg)
    assert mgr2._legacy_call_timeout({}) == 7.0
    assert mgr2._legacy_call_timeout({"timeout": 100}) == 10.0


# ---------- 3) 自递归仍然按原样拒绝（行为不变） ----------
def test_legacy_call_self_target_rejected():
    mgr = _mgr()
    r = asyncio.run(mgr._run_action("p", "plugin_call", {"target": "p"}))
    assert not r["ok"] and "自身" in r["error"]


# ---------- 4) A→B→A 环被 hop 保护拦下 ----------
def test_legacy_call_loop_is_blocked():
    mgr = _mgr()
    _enable(mgr, "a", "b")
    hops = []

    async def hook_b(ev):
        hops.append(ev["hop_count"])
        return await mgr._run_action("b", "plugin_call", {"target": "a", "name": "back"})

    async def hook_a(ev):
        hops.append(ev["hop_count"])
        return await mgr._run_action("a", "plugin_call", {"target": "b", "name": "again"})

    mgr._runtimes["a"] = _Rt(hook_a)
    mgr._runtimes["b"] = _Rt(hook_b)

    async def scenario():
        return await mgr._run_action("a", "plugin_call", {"target": "b", "name": "start"})

    res = asyncio.run(asyncio.wait_for(scenario(), timeout=10))
    assert hops and max(hops) == comm.MAX_HOP_COUNT      # 深度累计到阈值
    assert len(hops) == comm.MAX_HOP_COUNT               # 到阈值就不再往下投
    assert "hop 保护" in json.dumps(res, ensure_ascii=False)
    assert mgr._legacy_hop == {}                          # 递归结束后在途表回到干净状态


# ---------- 5) 正常 A→B→C 不受影响 ----------
def test_legacy_call_normal_chain_ok():
    mgr = _mgr()
    _enable(mgr, "a", "b", "c")
    mgr._runtimes["b"] = _Rt(lambda ev: mgr._run_action("b", "plugin_call", {"target": "c"}))
    mgr._runtimes["c"] = _Rt()
    res = asyncio.run(mgr._run_action("a", "plugin_call", {"target": "b"}))
    assert res["ok"] and res["response"]["delivered"] == "c"
    assert "hop 保护" not in json.dumps(res, ensure_ascii=False)
    assert mgr._legacy_hop == {}


# ---------- 6) 超时走配置（1 秒）并如实报错 ----------
def test_legacy_call_timeout_uses_config():
    cfg = _Cfg()
    cfg.PLUGIN_LEGACY_CALL_TIMEOUT = 1
    mgr = _mgr(cfg)
    _enable(mgr, "target")

    async def slow_hook(ev):
        await asyncio.sleep(5)
        return {"ok": True}

    mgr._runtimes["target"] = _Rt(slow_hook)
    r = asyncio.run(mgr._run_action("p", "plugin_call", {"target": "target"}))
    assert not r["ok"] and "超时" in r["error"]
    assert mgr._legacy_hop == {}


# ---------- 7) 新旧通道对照：旧通道复用 comm 的同一套 hop 判定 ----------
def test_legacy_channel_reuses_comm_hop_guard(monkeypatch):
    mgr = _mgr()
    _enable(mgr, "target")
    mgr._runtimes["target"] = _Rt()
    seen = []
    real = comm.hop_exceeded

    def spy(hop_count):
        seen.append(hop_count)
        return real(hop_count)

    monkeypatch.setattr(comm, "hop_exceeded", spy)
    r = asyncio.run(mgr._run_action("p", "plugin_call", {"target": "target"}))
    assert r["ok"] and seen == [0]        # 走的就是新通道那套判定，不是第二套实现


# ---------- 8) 可观测：metrics 记录投递结果 ----------
def test_legacy_call_metrics_recorded():
    from src.utils.metrics import registry
    mgr = _mgr()
    _enable(mgr, "target")
    mgr._runtimes["target"] = _Rt()
    assert asyncio.run(mgr._run_action("p", "plugin_call", {"target": "target"}))["ok"]
    snapshot = json.dumps(registry.snapshot(), ensure_ascii=False)
    assert "plugin_legacy_calls_total" in snapshot

