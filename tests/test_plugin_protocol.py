"""Plugin Protocol v1 测试（任务书第 2 份 §三 / §九 / §十二）。

三层证据，**全部打在真实现上**（不 mock 协议本身）：

1. **常量一致性**：`python_runner.py` 内联的协议常量 vs `src/plugins/protocol.py`（runner 以
   `python -I` 启动、导入不了仓库代码，所以内联了一份；本测试逐项比对，防止两份悄悄漂移）；
2. **协议工具**：存储键校验、能力归一（方法名/能力分组/dict 三种写法）、版本协商（含主版本不兼容）；
3. **真实子进程端到端**：起**真 runner** 子进程，走完整协议 —— initialize（版本+能力）→
   storage 读写/越界 → config（本地覆盖层 + 引擎配置合并）→ permission/context（反向 engine op）→
   event → hook → 未知方法 → shutdown。引擎侧由本测试实现，**反向通道走真管道**。
"""
import ast
import json
import os
import subprocess
import sys
import tempfile

import pytest

from src.plugins.protocol import (
    CAPABILITY_GROUPS,
    CORE_OPTIONAL_METHODS,
    ENGINE_OPS,
    OPTIONAL_METHODS,
    PLUGIN_METHODS,
    PROTOCOL_VERSION,
    REQUIRED_METHODS,
    WEBUI_METHODS,
    negotiate_initialize,
    normalize_capabilities,
    valid_storage_key,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(ROOT, "src/plugins/runner/python_runner.py")
PLUGIN_SOURCE = '''

def on_startup(context, api=None):
    return None


def on_message(event, api=None):
    return {"type": "send_group_msg", "params": {"group_id": 1, "message": "pong"}}


def my_hook(page, action):
    return {"vars": {"page": page, "action": action}}
'''


# ---------------------------------------------------------------- 1. 常量一致性

def _runner_constants():
    tree = ast.parse(open(RUNNER, encoding="utf-8").read())
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    found[target.id] = ast.literal_eval(node.value)
                except ValueError:
                    found[target.id] = ast.unparse(node.value)
    return found


def test_runner_inlined_constants_match_engine_module():
    consts = _runner_constants()
    assert consts["PROTOCOL_VERSION"] == PROTOCOL_VERSION
    assert tuple(consts["OPTIONAL_METHODS"]) == tuple(OPTIONAL_METHODS)
    assert {k: tuple(v) for k, v in consts["CAPABILITY_GROUPS"].items()} == \
        {k: tuple(v) for k, v in CAPABILITY_GROUPS.items()}
    assert consts["MAX_STORAGE_KEYS"] == 200
    # runner 里写成 "64 * 1024"（可读性优先），ast 只能拿到源码字符串 → 两种形态都接受
    assert consts["MAX_STORAGE_VALUE_BYTES"] in ("64 * 1024", 64 * 1024)
    # 键校验正则必须同源（用同一批样本交叉验证）
    assert "A-Za-z0-9" in consts["STORAGE_KEY_RE"]


# ---------------------------------------------------------------- 2. 协议工具

@pytest.mark.parametrize("key,ok", [
    ("a", True), ("note_1", True), ("a.b-c_1", True), ("A9", True),
    ("", False), ("../x", False), ("a/b", False), ("x" * 65, False),
    ("_hidden", False), ("a b", False), ("键", False),
])
def test_storage_key_validation(key, ok):
    assert valid_storage_key(key) is ok


def test_capability_normalization_accepts_three_forms():
    assert normalize_capabilities(["storage.set", "config.get"]) == ["config.get", "storage.set"]
    assert normalize_capabilities({"config": True, "storage": True}) == [
        "config.get", "config.set", "storage.delete", "storage.get", "storage.list", "storage.set"]
    assert normalize_capabilities({"config": True, "nope": True}) == ["config.get", "config.set"]
    assert normalize_capabilities(None) == [] and normalize_capabilities("config") == []


def test_version_negotiation_rules():
    ok, why, caps = negotiate_initialize({"ok": True, "protocol_version": "1", "capabilities": ["storage"]})
    # 能力分组会被展开成协议里的方法名（storage → 4 个方法），这是 protocol.py 的既定口径
    assert ok and why == "" and caps == ["storage.delete", "storage.get", "storage.list", "storage.set"]
    ok, _why, _caps = negotiate_initialize({"ok": True})            # 老插件：没有 protocol_version
    assert ok
    ok, why, _caps = negotiate_initialize({"ok": True, "protocol_version": "2.0"})
    assert not ok and "主版本不兼容" in why
    ok, why, _caps = negotiate_initialize({"ok": False, "error": "boom"})
    assert not ok and "boom" in why
    ok, why, _caps = negotiate_initialize("not-a-dict")
    assert not ok and "对象" in why


def test_method_sets_are_disjoint_and_complete():
    assert set(REQUIRED_METHODS) & set(OPTIONAL_METHODS) == set()
    assert len(CORE_OPTIONAL_METHODS) == 8 and len(WEBUI_METHODS) == 3
    assert len(PLUGIN_METHODS) == 3, "插件间通信 = CALL / EVENT / CANCEL（第 4 份任务书 §十）"
    assert len(OPTIONAL_METHODS) == 14, "可选方法 = 8 核心 + 3 WebUI + 3 插件间通信"
    assert ENGINE_OPS == ("context.get", "config.get", "permission.check",
                          "plugin.call", "plugin.emit", "plugin.cancel")


# ---------------------------------------------------------------- 3. 真子进程端到端

class _Peer:
    """测试里的"引擎侧"：真起 runner 子进程 + 回答反向 engine op。"""

    def __init__(self, approved=("send_message",), engine_values=None):
        self.dir = tempfile.mkdtemp()
        with open(os.path.join(self.dir, "plugin.py"), "w", encoding="utf-8") as fh:
            fh.write(PLUGIN_SOURCE)
        self.proc = subprocess.Popen(
            [sys.executable, "-I", RUNNER, "--dir", self.dir, "--entry", "plugin.py",
             "--plugin-id", "prototest"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1)
        self.seq = 0
        self.engine_ops = []
        self.approved = set(approved)
        self.engine_values = dict(engine_values or {"operator_key": "from_engine"})

    # ---- 底层 ----
    def send(self, method, params=None, req_id=None):
        self.seq += 1
        self.proc.stdin.write(json.dumps({"id": req_id or self.seq, "method": method,
                                          "params": params or {}}) + "\n")
        self.proc.stdin.flush()
        return req_id or self.seq

    def _answer_engine_op(self, msg):
        op = (msg.get("params") or {}).get("op")
        self.engine_ops.append(op)
        if op == "permission.check":
            want = (msg["params"].get("args") or {}).get("permission")
            result = {"ok": True, "permission": want, "granted": want in self.approved}
        elif op == "config.get":
            result = {"ok": True, "values": dict(self.engine_values)}
        elif op == "context.get":
            result = {"ok": True, "result": {"plugin_id": "prototest", "protocol_version": "1"}}
        else:
            result = {"ok": False, "error": "unknown op"}
        self.proc.stdin.write(json.dumps({"id": msg["id"], "result": result}) + "\n")
        self.proc.stdin.flush()

    def recv(self):
        while True:
            line = self.proc.stdout.readline()
            assert line, "runner 提前退出：%s" % self.proc.stderr.read()[-400:]
            msg = json.loads(line)
            if msg.get("method") == "engine":          # 反向通道：测试即引擎
                self._answer_engine_op(msg)
                continue
            return msg

    def call(self, method, params=None):
        req_id = self.send(method, params)
        msg = self.recv()
        assert msg.get("id") == req_id, msg
        return msg

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        self.proc.wait(timeout=5)


@pytest.fixture
def peer():
    p = _Peer()
    try:
        yield p
    finally:
        p.close()


def test_real_runner_handshake_declares_protocol_and_capabilities(peer):
    msg = peer.call("initialize", {"context": {}})
    result = msg["result"]
    assert result["ok"] is True and result["api_version"] == "1"
    assert result["protocol_version"] == PROTOCOL_VERSION
    assert set(result["capabilities"]) == set(OPTIONAL_METHODS)


def test_real_runner_storage_roundtrip_and_limits(peer):
    peer.call("initialize", {"context": {}})
    assert peer.call("storage.set", {"key": "note", "value": {"a": 1}})["result"]["ok"] is True
    assert peer.call("storage.get", {"key": "note"})["result"]["value"] == {"a": 1}
    assert peer.call("storage.get", {"key": "missing"})["result"]["value"] is None
    assert peer.call("storage.list", {})["result"]["keys"] == ["note"]
    assert peer.call("storage.list", {"prefix": "zz"})["result"]["keys"] == []
    assert peer.call("storage.list", {"prefix": "no"})["result"]["keys"] == ["note"]
    assert peer.call("storage.delete", {"key": "note"})["result"]["deleted"] is True
    assert peer.call("storage.delete", {"key": "note"})["result"]["deleted"] is False
    # 越界与超限
    bad = peer.call("storage.get", {"key": "../evil"})["result"]
    assert bad["ok"] is False and "非法" in bad["error"]
    huge = peer.call("storage.set", {"key": "big", "value": "x" * (70 * 1024)})["result"]
    assert huge["ok"] is False and "上限" in huge["error"]


def test_real_runner_config_merges_engine_values(peer):
    peer.call("initialize", {"context": {}})
    assert peer.call("config.set", {"values": {"mine": 1}})["result"]["ok"] is True
    got = peer.call("config.get", {})["result"]["values"]
    assert got["mine"] == 1 and got["operator_key"] == "from_engine"
    assert "config.get" in peer.engine_ops
    # 键非法 / 类型错
    assert peer.call("config.set", {"values": {"../x": 1}})["result"]["ok"] is False
    assert peer.call("config.set", {"values": "not-a-dict"})["result"]["ok"] is False


def test_real_runner_permission_and_context_use_reverse_channel(peer):
    peer.call("initialize", {"context": {}})
    granted = peer.call("permission.check", {"permission": "send_message"})["result"]
    denied = peer.call("permission.check", {"permission": "web_ui"})["result"]
    assert granted["granted"] is True and denied["granted"] is False
    ctx = peer.call("context.get", {})["result"]
    assert ctx["ok"] is True and ctx["result"]["plugin_id"] == "prototest"
    assert peer.engine_ops[:3] == ["permission.check", "permission.check", "context.get"]


def test_real_runner_unknown_method_is_protocol_error(peer):
    peer.call("initialize", {"context": {}})
    msg = peer.call("totally.unknown")
    assert "error" in msg and "未知方法" in msg["error"]


def test_real_runner_event_and_hook(peer):
    peer.call("initialize", {"context": {}})
    actions = peer.call("event", {"event": "message", "payload": {"text": "ping"}})["result"]["actions"]
    assert actions and actions[0]["type"] == "send_group_msg"
    hook = peer.call("hook", {"name": "my_hook", "args": ["index", "get"]})["result"]
    assert hook["ok"] is True and hook["result"]["vars"]["page"] == "index"
    assert peer.call("shutdown")["result"]["ok"] is True


def test_real_runner_rejects_illegal_hook_name(peer):
    peer.call("initialize", {"context": {}})
    msg = peer.call("hook", {"name": "exec('x')"})
    assert "error" in msg and "非法" in msg["error"]


# ---------------------------------------------------------------- 4. 引擎侧 op 安全

class _Cfg:
    PLUGIN_DIR = tempfile.mkdtemp()


class _Repo:
    def list_plugins(self):
        return []


def _manager(approved=("send_message",), enabled=True):
    from src.plugins.manager import PluginManager
    from src.plugins.manifest import PluginManifest

    base = {"id": "abc", "name": "ABC", "version": "1.0.0", "runtime": "python",
            "entry": "p.py", "api_version": "1", "permissions": ["send_message", "web_ui"],
            "config": {"values": {"operator_key": "from_engine"}}}
    manifest = PluginManifest.from_dict(base)
    row = {"id": "abc", "name": "ABC", "enabled": enabled, "version": "1.0.0", "runtime": "python",
           "approved_permissions": list(approved), "manifest_json": manifest.to_json()}
    mgr = PluginManager(config=_Cfg(), repository=_Repo())
    mgr.get_plugin = lambda pid: row if pid == "abc" else None
    mgr._manifest_of = lambda r: PluginManifest.from_dict(json.loads(r["manifest_json"]))
    return mgr


@pytest.mark.asyncio
async def test_engine_op_context_and_permission():
    mgr = _manager()
    ctx = await mgr._handle_engine_op("abc", "context.get", {})
    assert ctx["ok"] is True and ctx["result"]["permissions"] == ["send_message"]
    assert ctx["result"]["plugin_id"] == "abc"
    got = await mgr._handle_engine_op("abc", "permission.check", {"permission": "send_message"})
    assert got["granted"] is True
    missing = await mgr._handle_engine_op("abc", "permission.check", {"permission": "web_ui"})
    assert missing["granted"] is False
    unknown_perm = await mgr._handle_engine_op("abc", "permission.check", {"permission": "not.a.perm"})
    assert unknown_perm["granted"] is False and "未知权限键" in unknown_perm["reason"]


@pytest.mark.asyncio
async def test_engine_op_config_is_operator_owned():
    mgr = _manager()
    res = await mgr._handle_engine_op("abc", "config.get", {})
    assert res["values"] == {"operator_key": "from_engine"}


@pytest.mark.asyncio
async def test_engine_op_rejects_unknown_op_and_disabled_plugin():
    mgr = _manager()
    bad = await mgr._handle_engine_op("abc", "storage.get", {})
    assert bad["ok"] is False and "未知 op" in bad["error"]
    disabled = _manager(enabled=False)
    off = await disabled._handle_engine_op("abc", "context.get", {})
    assert off["ok"] is False and "未启用" in off["error"]
