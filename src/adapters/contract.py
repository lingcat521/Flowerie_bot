"""Adapter 契约夹具（Adapter Contract Harness）—— 任务书 Gate D 的地基。

目的：让**同一组 12 项契约**对每个适配器各跑一遍，从而把"新增协议"变成"填空"：
新协议只需在 `all_adapters()` 里加一条登记（解析器 + 描述符 + 样本 + 源码标记），
12 项契约自动生效。这与 Gate E（新增协议成本 PEC=0）是配套的。

每一项都标注它**测什么**、以及**为什么这样测**：

| # | 契约项 | 本夹具提供的字段 |
| --- | :--- | :--- |
| 1 | descriptor | `descriptor` |
| 2 | protocol identity | `parser` + `identity_field`（原生判别字段名）|
| 3 | lifecycle | `parser` + `container_protocol`（组合根选择）|
| 4 | capability declaration | `descriptor.capabilities` |
| 5 | message normalization | `message_event`（协议原生样本）|
| 6 | event normalization | `notice_event` |
| 7 | send mapping | `send_markers` + `source_files` |
| 8 | action mapping | `action_markers` + `source_files` |
| 9 | unknown segment | `unknown_segment` |
| 10 | unknown event | `unknown_event` |
| 11 | raw preservation | 样本本身（断言 raw_data 与输入逐字段相等）|
| 12 | error handling | `malformed_inputs` |

说明：第 7/8 项是**静态契约探查**（源码里必须存在协议映射与不支持清单）。
真正的"发出去并被收到"属实机验证（缺口台账 G5/G6，当前 BLOCKED）。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Tuple

from src.adapters.capabilities import AdapterDescriptor, get_descriptor
from src.adapters.milky_parser import MilkyEventParser
from src.adapters.onebot12_parser import OneBot12EventParser
from src.adapters.onebot_parser import OneBotEventParser

BOT_QQ = 10001


@dataclass(frozen=True)
class AdapterUnderTest:
    protocol_id: str
    parser: Any
    descriptor: AdapterDescriptor
    identity_field: str
    container_protocol: str
    message_event: Dict[str, Any]
    notice_event: Dict[str, Any]
    unknown_segment: Dict[str, Any]
    unknown_event: Dict[str, Any]
    source_files: Tuple[str, ...]
    send_markers: Tuple[str, ...]
    action_markers: Tuple[str, ...]
    segment_path: Tuple[str, ...] = ("message",)   # 段容器在原生事件里的路径
    segment_type_key: str = "type"                # 段类型字段名（伪协议用 "t"）
    segment_value_key: str = "data"               # 段载荷字段名（伪协议用 "v"）
    container_wired: bool = True                  # 是否已接入生产组合根（未接入者须在 note 说明）
    malformed_inputs: Tuple[Any, ...] = field(default_factory=tuple)


def _onebot_malformed() -> Tuple[Any, ...]:
    return (None, {}, [], "string", 42, {"post_type": None},
            {"post_type": "message", "message": "not-a-list-but-string"},
            {"post_type": "message", "message": [None, 1, "x", {}]},
            {"post_type": "notice", "file": "not-a-dict"},
            {"post_type": "message", "message_type": "group", "user_id": "abc"})


def _milky_malformed() -> Tuple[Any, ...]:
    return (None, {}, [], "string", 42, {"event_type": None},
            {"event_type": "message_receive", "data": "not-a-dict"},
            {"event_type": "message_receive", "data": {"segments": "not-a-list"}},
            {"event_type": "message_receive", "data": {"segments": [None, 1, "x", {}]}},
            {"event_type": "message_receive", "data": {"message_scene": "group", "peer_id": "abc"}})


def onebot11_under_test() -> AdapterUnderTest:
    return AdapterUnderTest(
        protocol_id="onebot11",
        parser=OneBotEventParser(bot_qq=BOT_QQ),
        descriptor=get_descriptor("onebot11"),
        identity_field="post_type",
        container_protocol="onebot",
        message_event={
            "post_type": "message", "message_type": "group", "sub_type": "normal",
            "group_id": 123456, "user_id": 456789, "message_id": 1001, "time": 1700000000,
            "message": [{"type": "at", "data": {"qq": str(BOT_QQ)}},
                        {"type": "text", "data": {"text": " 契约测试"}},
                        {"type": "image", "data": {"file": "a.jpg", "url": "https://x/a.jpg"}}],
        },
        notice_event={"post_type": "notice", "notice_type": "notify", "sub_type": "poke",
                      "group_id": 123456, "user_id": 456789, "target_id": BOT_QQ,
                      "time": 1700000000},
        unknown_segment={"type": "future_segment", "data": {"foo": "bar", "n": [1, 2]}},
        unknown_event={"post_type": "future_event", "payload": {"a": 1}},
        source_files=("src/transport/action_channels.py",),
        send_markers=("send_group_msg", "send_private_msg", "OneBotWSChannel", "OneBotHTTPChannel"),
        action_markers=("_MILKY_ACTIONS", "delete_msg", "recall"),
        segment_path=("message",),
        malformed_inputs=_onebot_malformed(),
    )


def milky_under_test() -> AdapterUnderTest:
    return AdapterUnderTest(
        protocol_id="milky",
        parser=MilkyEventParser(bot_qq=BOT_QQ),
        descriptor=get_descriptor("milky"),
        identity_field="event_type",
        container_protocol="milky",
        message_event={
            "time": 1700000000, "self_id": BOT_QQ, "event_type": "message_receive",
            "data": {"message_scene": "group", "peer_id": 123456, "sender_id": 456789,
                     "message_seq": 2001,
                     "segments": [{"type": "mention", "data": {"user_id": str(BOT_QQ)}},
                                  {"type": "text", "data": {"text": " 契约测试"}},
                                  {"type": "image", "data": {"resource_id": "r1",
                                                             "temp_url": "https://x/a.jpg"}}]},
        },
        notice_event={"time": 1700000000, "self_id": BOT_QQ, "event_type": "group_nudge",
                      "data": {"group_id": 123456, "sender_id": 456789,
                               "receiver_id": BOT_QQ, "display_action": "拍了拍",
                               "display_suffix": "的肩", "display_action_img_url": ""}},
        unknown_segment={"type": "future_segment", "data": {"foo": "bar", "n": [1, 2]}},
        unknown_event={"time": 1700000000, "self_id": BOT_QQ, "event_type": "future_event",
                       "data": {"a": 1}},
        source_files=("src/transport/action_channels.py",),
        send_markers=("send_group_message", "send_private_message", "MilkyHTTPChannel",
                      "MILKY_ACCESS_TOKEN"),
        action_markers=("_MILKY_UNSUPPORTED", "recall_group_message", "recall_private_message"),
        segment_path=("data", "segments"),
        malformed_inputs=_milky_malformed(),
    )


def onebot12_under_test() -> AdapterUnderTest:
    return AdapterUnderTest(
        protocol_id="onebot12",
        parser=OneBot12EventParser(bot_qq=BOT_QQ),
        descriptor=get_descriptor("onebot12"),
        identity_field="type",
        container_protocol="",  # 骨架：暂未接入组合根（见 onebot12-research.md）
        container_wired=False,
        message_event={"id": "evt-1", "time": 1700000000.5, "type": "message",
                       "detail_type": "group", "sub_type": "",
                       "self": {"platform": "qq", "user_id": str(BOT_QQ)},
                       "message_id": "3001", "group_id": "123456", "user_id": "456789",
                       "message": [{"type": "mention", "data": {"user_id": str(BOT_QQ)}},
                                   {"type": "text", "data": {"text": " 契约测试"}}]},
        notice_event={"id": "evt-2", "time": 1700000000.0, "type": "notice",
                      "detail_type": "group_upload", "sub_type": "",
                      "self": {"platform": "qq", "user_id": str(BOT_QQ)},
                      "group_id": "123456", "user_id": "456789"},
        unknown_segment={"type": "future_segment", "data": {"foo": "bar"}},
        unknown_event={"id": "evt-3", "time": 1700000000.0, "type": "future_type",
                       "detail_type": "x", "self": {"platform": "qq", "user_id": str(BOT_QQ)}},
        source_files=("src/adapters/onebot12_parser.py",),
        send_markers=("normalize_action_response", "V12_ACTION_MAP"),
        action_markers=("send_message", "delete_message"),
        segment_path=("message",),
        malformed_inputs=(None, {}, [], "string", 42, {"time": 1.0},
                          {"time": 1.0, "type": "message", "message": "not-a-list"},
                          {"time": 1.0, "type": "message", "message": [None, 1, {}]}),
    )


def testproto_under_test() -> AdapterUnderTest:
    """Gate E/F 的虚拟协议：新增协议在契约夹具里就是这样「加一条」。

    注意：这里**不修改生产注册表**（capabilities.descriptors() 仍只含三个真实协议），
    伪协议只在测试侧登记 —— 这也是 PEC 测量的一部分（生产代码零改动）。
    """
    from src.adapters.testkit.test_protocol import TestProtocolEventParser, test_protocol_descriptor

    return AdapterUnderTest(
        protocol_id="testproto",
        parser=TestProtocolEventParser(bot_qq=BOT_QQ),
        descriptor=test_protocol_descriptor(),
        identity_field="kind",
        container_protocol="",   # 虚拟协议未接入组合根（不修改生产装配代码）
        container_wired=False,
        segment_type_key="t",
        segment_value_key="v",
        message_event={"kind": "msg", "chan": "group:123456", "from": 456789, "seq": 1001,
                       "ts": 1700000000,
                       "parts": [{"t": "at", "v": str(BOT_QQ)},
                                 {"t": "text", "v": " 契约测试"},
                                 {"t": "img", "url": "https://x/a.png", "name": "a.png"}]},
        notice_event={"kind": "notice", "evt": "poke", "chan": "group:123456",
                      "from": 456789, "to": BOT_QQ, "ts": 1700000000},
        unknown_segment={"t": "future_part", "v": {"foo": "bar"}},
        unknown_event={"kind": "future_kind", "chan": "group:1", "ts": 1700000000},
        source_files=("src/adapters/testkit/test_protocol.py",),
        send_markers=("async def post", "TestProtocolChannel"),
        action_markers=("async def recall", "recalled"),
        segment_path=("parts",),
        malformed_inputs=(None, {}, [], "string", 42, {"kind": None},
                          {"kind": "msg", "parts": "not-a-list"},
                          {"kind": "msg", "parts": [None, 1, "x", {}]},
                          {"kind": "msg", "chan": "group:abc", "from": "xyz"}),
    )


def all_adapters() -> Tuple[AdapterUnderTest, ...]:
    """新增协议只需在这里加一条 —— 12 项契约会自动对它生效（Gate D/E 的配套设计）。"""
    return (onebot11_under_test(), milky_under_test(), onebot12_under_test(),
            testproto_under_test())
