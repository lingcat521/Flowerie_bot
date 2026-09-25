"""Gate S：多实例 —— OneBot11 #1 / OneBot11 #2 / Milky #1 同时存在，Cross-talk = 0。

任务书要求 3/3：独立连接、独立配置、独立生命周期、独立发送、独立接收；不得依赖单例
（`current_protocol` / `current_ws` / `global_adapter`）。本文件用**三个真解析器 +
三个独立通道**并发跑，逐条断言隔离性。
"""
import ast
import asyncio
import os
import re

import pytest

from src.adapters.instance import (
    STATE_CLOSED,
    STATE_CONNECTED,
    STATE_CREATED,
    InstanceRegistry,
    make_instance,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORBIDDEN_SINGLETONS = ("current_protocol", "current_ws", "global_adapter")


class FakeConfig:
    """每个实例自己的配置对象（协议 / Bot QQ / 接口地址都不同）。"""

    def __init__(self, protocol="onebot", bot_qq=10001, api_base="http://onebot.local"):
        self.QQ_PROTOCOL = protocol
        self.BOT_QQ = bot_qq
        self.HTTP_API_BASE = api_base
        self.MILKY_API_BASE = "http://milky.local"


class FakeChannel:
    """实例自己的动作通道：只记录**本实例**的调用。"""

    def __init__(self, name):
        self.name = name
        self.posts = []

    async def post(self, endpoint, payload, timeout=10.0):
        self.posts.append((endpoint, dict(payload)))
        return {"ok": True, "data": {"message_id": len(self.posts), "via": self.name}}


def _ob_message(text, user_id=456789, group_id=123456, message_id=1001, at_qq="10001"):
    return {"post_type": "message", "message_type": "group", "sub_type": "normal",
            "group_id": group_id, "user_id": user_id, "message_id": message_id,
            "time": 1700000000,
            "message": [{"type": "at", "data": {"qq": at_qq}},
                        {"type": "text", "data": {"text": text}}]}


def _milky_message(text, sender_id=456789, group_id=123456, seq=1001):
    return {"time": 1700000000, "self_id": 30003, "event_type": "message_receive",
            "data": {"message_scene": "group", "peer_id": group_id, "sender_id": sender_id,
                     "message_seq": seq,
                     "segments": [{"type": "text", "data": {"text": text}}]}}


def _three_instances():
    """OneBot11 #1 / OneBot11 #2 / Milky #1：三套配置、三个解析器、三个通道。"""
    registry = InstanceRegistry()
    channels = {}
    spec = (("ob-1", "onebot", 10001, "http://ob1.local"),
            ("ob-2", "onebot", 20002, "http://ob2.local"),
            ("mk-1", "milky", 30003, "http://mk1.local"))
    for instance_id, protocol, bot_qq, api_base in spec:
        channels[instance_id] = FakeChannel(instance_id)
        registry.register(make_instance(instance_id, FakeConfig(protocol, bot_qq, api_base),
                                        channel=channels[instance_id]))
    return registry, channels


# ---------------------------------------------------------------- 3/3 并存

def test_three_instances_coexist_with_independent_config_and_capabilities():
    registry, channels = _three_instances()
    assert registry.ids() == ["mk-1", "ob-1", "ob-2"]
    assert registry.get("ob-1").bot_qq == 10001
    assert registry.get("ob-2").bot_qq == 20002
    assert registry.get("mk-1").bot_qq == 30003
    assert registry.get("ob-1").descriptor.protocol_id == "onebot11"
    assert registry.get("ob-2").descriptor.protocol_id == "onebot11"
    assert registry.get("mk-1").descriptor.protocol_id == "milky"
    # 即使协议相同（ob-1 / ob-2），解析器与通道也是各自的实例
    assert registry.get("ob-1").parser is not registry.get("ob-2").parser
    assert registry.get("ob-1").channel is channels["ob-1"]
    assert registry.get("ob-2").channel is channels["ob-2"]
    snapshot = registry.snapshot()
    assert set(snapshot) == {"mk-1", "ob-1", "ob-2"}
    assert snapshot["ob-1"]["state"] == STATE_CREATED and snapshot["ob-1"]["sent"] == 0


def test_mentions_are_resolved_against_each_instance_own_bot_qq():
    registry, _ = _three_instances()
    raw = _ob_message(" 在吗")
    ev1 = registry.get("ob-1").parse(raw)
    ev2 = registry.get("ob-2").parse(raw)
    assert ev1.is_mentioned is True and ev2.is_mentioned is False
    assert registry.get("ob-1").received == 1 and registry.get("ob-2").received == 1
    assert registry.get("mk-1").received == 0


# ---------------------------------------------------------------- Cross-talk = 0

@pytest.mark.asyncio
async def test_instance_cross_talk_is_zero_under_concurrency():
    registry, channels = _three_instances()
    assert await registry.connect_all() == 3
    rounds = 20
    ids = ("ob-1", "ob-2", "mk-1")

    async def drive(instance_id):
        inst = registry.get(instance_id)
        for i in range(rounds):
            marker = "%s-%d" % (instance_id, i)
            if inst.protocol == "milky":
                raw = _milky_message(marker, sender_id=500000 + i, group_id=200000 + i, seq=1000 + i)
            else:
                raw = _ob_message(marker, user_id=400000 + i, group_id=100000 + i, message_id=2000 + i)
            event = inst.parse(raw)
            assert marker in event.text
            res = await inst.send({"message": marker})
            assert res["ok"] is True and res["data"]["via"] == instance_id

    await asyncio.gather(*(drive(i) for i in ids))

    for instance_id in ids:
        assert len(channels[instance_id].posts) == rounds
        assert len(registry.get(instance_id).sent) == rounds
        for _endpoint, payload in channels[instance_id].posts:
            assert payload["message"].startswith(instance_id), "串台：别的实例的消息进了本通道"
        for entry in registry.get(instance_id).sent:
            assert entry["payload"]["message"].startswith(instance_id)
        assert registry.get(instance_id).received == rounds
    # 可变状态互不共享（同一对象被两个实例引用 = 隐式单例）
    assert channels["ob-1"].posts is not channels["ob-2"].posts
    assert registry.get("ob-1").sent is not registry.get("ob-2").sent
    assert registry.get("ob-1").sent is not registry.get("mk-1").sent


# ---------------------------------------------------------------- 独立生命周期 / 发送

@pytest.mark.asyncio
async def test_lifecycle_is_independent_and_instances_never_borrow_a_channel():
    registry, channels = _three_instances()
    await registry.connect_all()
    assert registry.get("ob-2").state == STATE_CONNECTED

    assert await registry.get("ob-2").disconnect() is True
    assert registry.get("ob-2").state == STATE_CLOSED
    bad = await registry.get("ob-2").send({"message": "should-not-be-sent"})
    assert bad["ok"] is False and "未连接" in bad["error"]
    assert channels["ob-2"].posts == []

    # 其它实例不受影响
    assert (await registry.get("ob-1").send({"message": "alive"}))["ok"] is True
    assert (await registry.get("mk-1").send({"message": "alive"}))["ok"] is True
    assert len(channels["ob-1"].posts) == 1 and len(channels["mk-1"].posts) == 1
    assert channels["ob-2"].posts == []

    # 未接线发送出口的实例：明确失败，绝不借用别人的通道
    orphan = registry.register(make_instance("orphan", FakeConfig("onebot", 40004)))
    await orphan.connect()
    res = await orphan.send({"message": "no-channel"})
    assert res["ok"] is False and "未接线" in res["error"]

    # 重新连接后恢复可用（生命周期各自独立）
    await registry.get("ob-2").connect()
    assert (await registry.get("ob-2").send({"message": "back"}))["ok"] is True
    assert await registry.disconnect_all() == 4


def test_registry_is_a_plain_object_not_a_singleton():
    registry_a, _ = _three_instances()
    registry_b, _ = _three_instances()
    assert registry_a.unregister("ob-1") is True
    assert registry_a.ids() == ["mk-1", "ob-2"]
    assert registry_b.ids() == ["mk-1", "ob-1", "ob-2"]      # 另一个注册表不受影响
    assert registry_a.unregister("ob-1") is False
    with pytest.raises(ValueError):
        registry_a.register(registry_a.get("ob-2"))          # 重名即报错
    with pytest.raises(KeyError):
        registry_a.get("nope")
    assert registry_a.find("nope") is None
    assert "ob-2" in registry_a and "ob-1" not in registry_a


# ---------------------------------------------------------------- 静态检查

def _referenced_names(tree):
    """收集代码里**真正被引用**的名字：变量/属性名 + 非文档字符串的字面量。

    只扫源码文本会把"文档里提到过 current_protocol"也算成违规（我们自己的 docstring 就写了），
    所以走 AST：文档字符串剔除，但 getattr(obj, "current_protocol") 这类字面量仍然会被抓到。
    """
    names = set()
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in docstrings:
            names.add(node.value)
    return names


def test_no_forbidden_singleton_names_anywhere_in_src():
    pattern = re.compile("|".join(FORBIDDEN_SINGLETONS))
    hits = []
    for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "src")):
        if "__pycache__" in dirpath:
            continue
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for ref in sorted(_referenced_names(tree)):
                if pattern.search(ref):
                    hits.append("%s -> %s" % (os.path.relpath(path, ROOT), ref))
    assert hits == [], "出现禁止的单例：%s" % hits
    # 反向对照：正则确实抓得到这些词（避免"扫描永远为空"的假绿）
    assert pattern.search("x = current_protocol")
    assert pattern.search("global_adapter = None")
    assert pattern.search("self.current_ws = ws")


def test_instance_module_keeps_no_module_level_mutable_state():
    path = os.path.join(ROOT, "src/adapters/instance.py")
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    offenders = []
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and not target.id.isupper():
                offenders.append("src/adapters/instance.py:%d %s" % (node.lineno, target.id))
    assert offenders == [], "模块级可变状态会造成隐式单例：%s" % offenders
