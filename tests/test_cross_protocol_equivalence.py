"""Gate M：跨协议等价测试（7 类逻辑消息 × OneBot 11 / Milky / TestProtocol）。

任务书 §14 要求：三种协议表达**同一个逻辑消息**，归一化后必须等价（7/7 PASS）。

做法：每一类消息准备三份"协议原生样本"（各自是最小但合法的线格式），
分别喂真解析器，再投影到**协议中立的比较元组**（只比语义，不比字段名），断言三者相等。
TestProtocol 是 Gate E/F 的虚拟协议（src/adapters/testkit/），它存在的意义之一就是当"第三方协议"。
"""
import pytest

from src.adapters.milky_parser import MilkyEventParser
from src.adapters.onebot_parser import OneBotEventParser
from src.adapters.testkit import TestProtocolEventParser

BOT_QQ = 10001
GROUP = 123456
USER = 456789
IMG = "https://example.com/a.png"
FWD_ID = "fwd-1"
REPLY_SEQ = 1001


def _onebot(segments):
    return {"post_type": "message", "message_type": "group", "sub_type": "normal",
            "group_id": GROUP, "user_id": USER, "message_id": 1001, "time": 1700000000,
            "message": segments}


def _milky(segments):
    return {"time": 1700000000, "self_id": BOT_QQ, "event_type": "message_receive",
            "data": {"message_scene": "group", "peer_id": GROUP, "sender_id": USER,
                     "message_seq": 1001, "segments": segments}}


def _testproto(parts):
    return {"kind": "msg", "chan": "group:%d" % GROUP, "from": USER, "seq": 1001,
            "ts": 1700000000, "parts": parts}


# 每一类：三份协议原生样本 + 协议中立的投影函数（只读归一化字段）
CLASSES = {
    "text": {
        "onebot11": _onebot([{"type": "text", "data": {"text": "你好世界"}}]),
        "milky": _milky([{"type": "text", "data": {"text": "你好世界"}}]),
        "testproto": _testproto([{"t": "text", "v": "你好世界"}]),
        "project": lambda ev: ev.text,
        "expected": "你好世界",
    },
    "at": {
        "onebot11": _onebot([{"type": "text", "data": {"text": " "}},
                             {"type": "at", "data": {"qq": str(BOT_QQ)}}]),
        "milky": _milky([{"type": "text", "data": {"text": " "}},
                         {"type": "mention", "data": {"user_id": BOT_QQ}}]),
        "testproto": _testproto([{"t": "text", "v": " "}, {"t": "at", "v": str(BOT_QQ)}]),
        "project": lambda ev: (ev.is_mentioned, sorted(ev.mentions)),
        "expected": (True, [str(BOT_QQ)]),
    },
    "reply": {
        "onebot11": _onebot([{"type": "reply", "data": {"id": str(REPLY_SEQ)}},
                             {"type": "text", "data": {"text": "回复你"}}]),
        "milky": _milky([{"type": "reply", "data": {"message_seq": REPLY_SEQ}},
                         {"type": "text", "data": {"text": "回复你"}}]),
        "testproto": _testproto([{"t": "reply", "v": REPLY_SEQ}, {"t": "text", "v": "回复你"}]),
        "project": lambda ev: (ev.reply_id, ev.text),
        "expected": (REPLY_SEQ, "回复你"),
    },
    "image": {
        "onebot11": _onebot([{"type": "image", "data": {"file": "a.png", "url": IMG}}]),
        "milky": _milky([{"type": "image", "data": {"temp_url": IMG, "resource_id": "r1"}}]),
        "testproto": _testproto([{"t": "img", "url": IMG, "name": "a.png"}]),
        "project": lambda ev: ev.images,
        "expected": [IMG],
    },
    "face": {
        "onebot11": _onebot([{"type": "face", "data": {"id": "14"}}]),
        "milky": _milky([{"type": "face", "data": {"face_id": 14}}]),
        "testproto": _testproto([{"t": "face", "v": "14"}]),
        "project": lambda ev: [(f.get("kind"), f.get("face_id")) for f in ev.faces],
        "expected": [("face", "14")],
    },
    "file": {
        "onebot11": _onebot([{"type": "file", "data": {"file_id": "f1", "file": "报.zip", "file_size": 2048}}]),
        "milky": _milky([{"type": "file", "data": {"file_id": "f1", "file_name": "报.zip",
                                                   "file_size": 2048}}]),
        "testproto": _testproto([{"t": "file", "v": {"id": "f1", "name": "报.zip", "size": 2048}}]),
        "project": lambda ev: [(f.get("file_id"), f.get("name")) for f in ev.files],
        "expected": [("f1", "报.zip")],
    },
    "forward": {
        "onebot11": _onebot([{"type": "forward", "data": {"id": FWD_ID}}]),
        "milky": _milky([{"type": "forward", "data": {"forward_id": FWD_ID}}]),
        "testproto": _testproto([{"t": "forward", "v": FWD_ID}]),
        "project": lambda ev: [f.get("id") for f in ev.forwards],
        "expected": [FWD_ID],
    },
}

PARSERS = {
    "onebot11": lambda: OneBotEventParser(bot_qq=BOT_QQ),
    "milky": lambda: MilkyEventParser(bot_qq=BOT_QQ),
    "testproto": lambda: TestProtocolEventParser(bot_qq=BOT_QQ),
}


@pytest.mark.parametrize("name", sorted(CLASSES))
def test_logical_message_is_equivalent_across_three_protocols(name):
    case = CLASSES[name]
    results = {}
    for protocol in ("onebot11", "milky", "testproto"):
        raw = case[protocol]
        event = PARSERS[protocol]().parse(raw)
        assert event.kind == "message", "%s 未识别为消息事件" % protocol
        assert event.group_id == GROUP and event.actor_id == USER, "%s 会话字段不对" % protocol
        results[protocol] = case["project"](event)
    assert results["onebot11"] == case["expected"], results
    assert results["milky"] == case["expected"], results
    assert results["testproto"] == case["expected"], results
    assert results["onebot11"] == results["milky"] == results["testproto"]


def test_matrix_covers_seven_classes_and_three_protocols():
    assert sorted(CLASSES) == ["at", "face", "file", "forward", "image", "reply", "text"]
    assert len(CLASSES) == 7
    for case in CLASSES.values():
        assert set(case) >= {"onebot11", "milky", "testproto", "project", "expected"}
