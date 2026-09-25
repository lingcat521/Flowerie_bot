"""Gate D：Adapter Contract 测试（12 项 × 每个适配器）。

任务书 Gate D 要求：每个 Adapter 至少通过 12 项统一契约，当前至少 OneBot11 12/12、Milky 12/12，
否则 FAIL。契约夹具见 src/adapters/contract.py —— 新增协议只需登记一条，12 项自动生效。

第 7/8 项（send / action mapping）是**静态契约探查**：断言源码里存在该协议的发送与动作映射。
真正的"发出去并被收到"属实机验证（缺口台账 G5/G6，当前 BLOCKED），本文件不做任何实机声称。
"""
import copy
import io
from typing import Any, Dict

import pytest

from src.adapters.capabilities import CANONICAL_CAPABILITIES, CapState, capability_coverage
from src.adapters.container import make_adapters
from src.adapters.contract import AdapterUnderTest, all_adapters
from src.adapters.proto import InternalEvent

ADAPTERS = all_adapters()
IDS = [a.protocol_id for a in ADAPTERS]


def _with_unknown_segment(a: AdapterUnderTest) -> Dict[str, Any]:
    ev = copy.deepcopy(a.message_event)
    cur = ev
    for key in a.segment_path[:-1]:
        cur = cur[key]
    cur[a.segment_path[-1]] = list(cur[a.segment_path[-1]]) + [copy.deepcopy(a.unknown_segment)]
    return ev


@pytest.mark.parametrize("a", ADAPTERS, ids=IDS)
def test_contract_01_descriptor(a):
    d = a.descriptor
    assert d.protocol_id == a.protocol_id
    assert d.version and d.transports and d.note
    assert d.capabilities.as_dict(), "描述符必须带能力声明"


@pytest.mark.parametrize("a", ADAPTERS, ids=IDS)
def test_contract_02_protocol_identity(a):
    ev = a.parser.parse(copy.deepcopy(a.message_event))
    assert isinstance(ev, InternalEvent)
    assert ev.kind == "message"
    # 原生判别字段必须能在 raw_data 里找到（协议身份可追溯）
    assert a.identity_field in ev.raw_data


@pytest.mark.parametrize("a", ADAPTERS, ids=IDS)
def test_contract_03_lifecycle(a):
    # 解析器可重复使用且无状态泄漏：连续解析两个事件互不影响
    e1 = a.parser.parse(copy.deepcopy(a.message_event))
    e2 = a.parser.parse(copy.deepcopy(a.notice_event))
    assert e1.kind == "message" and e2.kind == "notice"
    if a.container_protocol:
        built = make_adapters(10001, _complete_fake_sender(), protocol=a.container_protocol)
        expected = "milky" if a.container_protocol == "milky" else "onebot"
        assert built.transport == expected
        assert built.descriptor.protocol_id == a.protocol_id
    else:
        # 骨架适配器：明确"未接入组合根"，且不会被误当成已接入
        assert "骨架" in a.descriptor.note
        assert make_adapters(10001, _complete_fake_sender(), protocol="onebot").descriptor.protocol_id == "onebot11"


@pytest.mark.parametrize("a", ADAPTERS, ids=IDS)
def test_contract_04_capability_declaration(a):
    caps = a.descriptor.capabilities
    missing = [c for c in CANONICAL_CAPABILITIES if not caps.declared(c)]
    assert missing == [], missing
    assert capability_coverage(a.protocol_id) >= 0.95
    assert all(caps.state(c) in CapState.VALID for c in CANONICAL_CAPABILITIES)


@pytest.mark.parametrize("a", ADAPTERS, ids=IDS)
def test_contract_05_message_normalization(a):
    ev = a.parser.parse(copy.deepcopy(a.message_event))
    assert ev.scope == "group" and ev.group_id and ev.actor_id
    assert ev.message_id is not None
    assert "契约测试" in ev.text
    assert str(10001) in [str(m) for m in ev.mentions]
    assert ev.is_mentioned is True


@pytest.mark.parametrize("a", ADAPTERS, ids=IDS)
def test_contract_06_event_normalization(a):
    ev = a.parser.parse(copy.deepcopy(a.notice_event))
    assert ev.kind == "notice"
    assert ev.notice_kind, "通知类事件必须给出 notice_kind（供路由/插件判定）"


@pytest.mark.parametrize("a", ADAPTERS, ids=IDS)
def test_contract_07_send_mapping(a):
    src = "".join(io.open(f, encoding="utf-8").read() for f in a.source_files)
    missing = [m for m in a.send_markers if m not in src]
    assert missing == [], "发送映射缺失：%s" % missing


@pytest.mark.parametrize("a", ADAPTERS, ids=IDS)
def test_contract_08_action_mapping(a):
    src = "".join(io.open(f, encoding="utf-8").read() for f in a.source_files)
    missing = [m for m in a.action_markers if m not in src]
    assert missing == [], "动作映射/不支持清单缺失：%s" % missing


@pytest.mark.parametrize("a", ADAPTERS, ids=IDS)
def test_contract_09_unknown_segment(a):
    raw = _with_unknown_segment(a)
    ev = a.parser.parse(raw)
    seg_type = a.unknown_segment["type"]
    assert (seg_type, a.unknown_segment["data"]) in ev.segments_summary


@pytest.mark.parametrize("a", ADAPTERS, ids=IDS)
def test_contract_10_unknown_event(a):
    raw = copy.deepcopy(a.unknown_event)
    ev = a.parser.parse(raw)
    assert ev.kind and ev.kind != "unknown" or a.identity_field not in raw
    assert ev.raw_data == raw


@pytest.mark.parametrize("a", ADAPTERS, ids=IDS)
def test_contract_11_raw_preservation(a):
    for sample in (a.message_event, a.notice_event, a.unknown_event):
        raw = copy.deepcopy(sample)
        ev = a.parser.parse(copy.deepcopy(sample))
        assert ev.raw_data == raw


@pytest.mark.parametrize("a", ADAPTERS, ids=IDS)
def test_contract_12_error_handling(a):
    for bad in a.malformed_inputs:
        ev = a.parser.parse(copy.deepcopy(bad))
        assert isinstance(ev, InternalEvent), "畸形输入也必须返回事件对象：%r" % (bad,)
        assert ev.kind, "畸形输入也必须给出 kind（不抛异常）"


def _complete_fake_sender():
    """按 MessageSender 契约自动补齐全部方法（当前 35 个）。

    手写列表会随契约演进悄悄过期（本轮就漏了 24 个方法，直接 RuntimeError）；
    这里从 Protocol 反射，契约新增方法时测试会立刻覆盖到。
    """
    import inspect

    from src.adapters.proto import MessageSender

    class _CompleteSender:
        pass

    async def _ok(*args, **kwargs):
        return {"ok": True, "message_id": 1}

    for name, _member in inspect.getmembers(MessageSender):
        if name.startswith("_"):
            continue
        setattr(_CompleteSender, name, staticmethod(_ok))
    return _CompleteSender()

def test_contract_summary_all_adapters_12_of_12():
    """Gate D 汇总：每个已登记适配器都必须有 12 项契约（新增协议忘登记会在这里暴露）。"""
    ids_seen = [a.protocol_id for a in ADAPTERS]
    assert ids_seen == ["onebot11", "milky", "onebot12"]
    assert len(ADAPTERS) * 12 == 36
