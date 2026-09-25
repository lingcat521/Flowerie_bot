"""出站序列化 + Round-trip（任务书 §十四/§十七/§十八）。

被测代码：`src/adapters/onebot_serializer.py` + `src/adapters/client_profile.py`（生产路径）。
往返链路：客户端 fixture →（inbound parser）→ 内部段数组 →（serializer）→ 客户端可接受的 wire 段数组。

诚实规则（§十八）：**不能 round-trip 的必须说明原因** —— 每条丢失/降级都对应一个 note 断言，
不允许"看起来一样"就算通过。
"""
import glob
import json
import os

import pytest

from src.adapters.client_profile import GO_CQHTTP, ONEBOT11_SPEC, profile_for
from src.adapters.onebot_parser import OneBotEventParser
from src.adapters.onebot_serializer import (
    NOTE_DROPPED_FIELD,
    NOTE_INVALID,
    NOTE_REPLY_HOISTED,
    NOTE_UNSUPPORTED_SEGMENT,
    NOTE_VALUE_OUT_OF_RANGE,
    serialize_segments,
)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "go-cqhttp")
BOT_QQ = 10001


def _fixture(name: str) -> dict:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)


def _types(segments):
    return [s["type"] for s in segments]


def _reasons(notes):
    return [n["reason"] for n in notes]


# ---------------------------------------------------------------- 单元

def test_text_at_image_roundtrip_fields():
    wire, notes = serialize_segments([
        {"type": "text", "data": {"text": "hi"}},
        {"type": "at", "data": {"qq": "10001"}},
        {"type": "image", "data": {"file": "file:///tmp/a.jpg", "type": "flash"}},
    ], profile=GO_CQHTTP)
    assert wire == [
        {"type": "text", "data": {"text": "hi"}},
        {"type": "at", "data": {"qq": "10001"}},
        {"type": "image", "data": {"file": "file:///tmp/a.jpg", "type": "flash"}},
    ]
    assert notes == [], notes


def test_reply_is_hoisted_and_only_one_kept():
    wire, notes = serialize_segments([
        {"type": "text", "data": {"text": "x"}},
        {"type": "reply", "data": {"id": 42}},
        {"type": "reply", "data": {"id": 43}},
    ], profile=GO_CQHTTP)
    assert _types(wire)[0] == "reply" and wire[0]["data"]["id"] == "42"
    assert NOTE_REPLY_HOISTED in _reasons(notes)
    assert any(n["reason"].endswith("extra_reply_dropped") for n in notes), notes


def test_file_segment_drops_foreign_namespace_field():
    """go-cqhttp 的 file 段用 path/name/size/busid；file_id 是别家命名空间 → 必须丢并记 note。"""
    wire, notes = serialize_segments([
        {"type": "file", "data": {"path": "/f1", "name": "a.pdf", "size": "1", "busid": "102",
                                  "file_id": "fid-9"}}], profile=GO_CQHTTP)
    assert wire[0]["data"] == {"path": "/f1", "name": "a.pdf", "size": "1", "busid": "102"}
    assert any(n["reason"] == NOTE_DROPPED_FIELD and n.get("field") == "file_id" for n in notes)


def test_unknown_segment_is_passed_through_with_note():
    """未登记段：原样传递 + note（不伪造支持，也不丢用户内容）。"""
    wire, notes = serialize_segments([{"type": "markdown", "data": {"content": "**x**"}}],
                                     profile=GO_CQHTTP)
    assert wire == [{"type": "markdown", "data": {"content": "**x**"}}]
    # go-cqhttp 档案里 markdown 是**有证据的 UNSUPPORTED**（发送侧 case 表里没有）
    assert NOTE_UNSUPPORTED_SEGMENT in _reasons(notes)


def test_out_of_range_values_are_refused():
    """go-cqhttp 的 dice 0..6 / rps 0..2 越界会直接报错 → 这里拒绝并给出理由。"""
    wire, notes = serialize_segments([{"type": "dice", "data": {"value": "9"}}], profile=GO_CQHTTP)
    assert wire == [] and NOTE_VALUE_OUT_OF_RANGE in _reasons(notes)


def test_spec_profile_does_not_claim_client_extensions():
    """规范基线没有 poke/dice 段：序列化必须标成未验证，而不是当作支持。"""
    assert ONEBOT11_SPEC.state("poke") == "UNSUPPORTED"
    assert profile_for("onebot11", "unknown-client").state("text") == "UNKNOWN"


def test_invalid_segments_do_not_crash():
    wire, notes = serialize_segments([None, {"data": {}}, {"type": "at", "data": {}}],
                                     profile=GO_CQHTTP)
    assert wire == []
    assert _reasons(notes) == [NOTE_INVALID] * 3, notes


# ---------------------------------------------------------------- Round-trip

@pytest.mark.parametrize("name", sorted(os.path.basename(p) for p in glob.glob(
    os.path.join(FIXTURES, "*.json"))))
def test_roundtrip_go_cqhttp_fixtures(name):
    """fixture → parser → serializer：类型序列必须保持；丢失字段必须出现在 notes 里。"""
    raw = _fixture(name)
    event = OneBotEventParser(bot_qq=BOT_QQ).parse(raw)
    wire, notes = serialize_segments(event.message_segments, profile=GO_CQHTTP)

    inbound = [s.get("type") for s in (raw.get("message") or []) if isinstance(s, dict)]
    # reply 会被提到最前（go-cqhttp 行为），其余保持原顺序
    outbound = _types(wire)
    assert sorted(outbound) == sorted(inbound), (inbound, outbound)

    dropped = {(n.get("type"), n.get("field")) for n in notes if n["reason"] == NOTE_DROPPED_FIELD}
    if name == "group_message_media_array.json":
        # record/video 的 url 只在**上报**里有；go-cqhttp 发送侧只读 file（voice() L532-550）
        assert ("record", "url") in dropped and ("video", "url") in dropped, notes
        image = next(s for s in wire if s["type"] == "image")
        assert image["data"]["file"] and image["data"]["subType"] == "0"
    if name == "group_message_file_segment.json":
        assert wire[0]["data"] == {"path": "/f1f2f3a4-5678", "name": "报告.pdf",
                                   "size": "20480", "busid": "102"}
        assert not dropped, notes
    if name in ("group_message_service_xml.json", "group_message_service_json_keeps_resid.json"):
        # resid 是 go-cqhttp 自己读的字段（xml/json 都 ParseInt resid）→ 不应丢
        assert "resid" in wire[0]["data"], wire
        assert not dropped, notes
    if name == "group_message_anonymous.json":
        assert wire == [{"type": "text", "data": {"text": "匿名发言"}}]
