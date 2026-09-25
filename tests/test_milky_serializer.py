"""Milky 出站序列化 + 响应模型 + 往返（任务书 §十/§十四/§十七/§十八）。

被测代码：`src/adapters/milky_serializer.py`（出站）、`src/transport/milky_response.py`（响应）。
语料：`tests/fixtures/milky/`（入站事件，带 provenance）。

往返规则同 OneBot 侧：**不能往返的必须说明原因**（每条都对应一个 note 断言）。
"""
import glob
import json
import os

import pytest

from src.adapters.client_profile import LLBOT_MILKY, MILKY_SPEC
from src.adapters.milky_parser import MilkyEventParser
from src.adapters.milky_serializer import (
    NOTE_DROPPED_FIELD,
    NOTE_DROPPED_SEGMENT,
    NOTE_INVALID,
    NOTE_UNSUPPORTED_SEGMENT,
    NOTE_UNKNOWN_SEGMENT,
    serialize_milky_segments,
)
from src.transport.milky_response import parse_milky_response

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "milky")
BOT_QQ = 10001


def _reasons(notes):
    return [n["reason"] for n in notes]


def _load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------- 单元：规范段

@pytest.mark.parametrize("segment,expected", [
    ({"type": "text", "data": {"text": "hi"}}, {"type": "text", "data": {"text": "hi"}}),
    ({"type": "mention", "data": {"user_id": 10001}},
     {"type": "mention", "data": {"user_id": 10001}}),
    ({"type": "mention_all", "data": {}}, {"type": "mention_all", "data": {}}),
    ({"type": "face", "data": {"face_id": "14", "is_large": False}},
     {"type": "face", "data": {"face_id": "14", "is_large": False}}),
    ({"type": "reply", "data": {"message_seq": 77123}},
     {"type": "reply", "data": {"message_seq": 77123}}),
    ({"type": "image", "data": {"uri": "file:///tmp/a.jpg", "sub_type": "normal"}},
     {"type": "image", "data": {"uri": "file:///tmp/a.jpg", "sub_type": "normal"}}),
    ({"type": "record", "data": {"uri": "base64://AAAA"}},
     {"type": "record", "data": {"uri": "base64://AAAA"}}),
    ({"type": "video", "data": {"uri": "https://x/v.mp4", "thumb_uri": "https://x/t.jpg"}},
     {"type": "video", "data": {"uri": "https://x/v.mp4", "thumb_uri": "https://x/t.jpg"}}),
])
def test_outgoing_segment_shapes(segment, expected):
    """每个出站段的字段名与规范 OutgoingSegment 一致（[DOC] common.ts L393-445）。"""
    wire, notes = serialize_milky_segments([segment], profile=MILKY_SPEC)
    assert wire == [expected]
    assert notes == [], notes


def test_forward_with_messages_is_supported():
    """Milky **可以自造合并转发**（go-cqhttp 只能按 id 下载）→ messages[] 必填。"""
    wire, notes = serialize_milky_segments([{"type": "forward", "data": {
        "messages": [{"user_id": 1, "sender_name": "n", "segments": [
            {"type": "text", "data": {"text": "x"}}]}], "title": "t"}}], profile=MILKY_SPEC)
    assert wire[0]["type"] == "forward" and wire[0]["data"]["messages"]
    assert notes == []


# ---------------------------------------------------------------- 单元：客户端规则

def test_llbot_drops_mention_in_private_chat():
    """LLBot：mention/mention_all 只在群聊产出元素（outgoing.ts 的 && isGroup）[CODE]。"""
    wire, notes = serialize_milky_segments([{"type": "mention", "data": {"user_id": 1}}],
                                           profile=LLBOT_MILKY, is_group=False)
    assert wire == [] and NOTE_DROPPED_SEGMENT in _reasons(notes)
    grouped, _ = serialize_milky_segments([{"type": "mention", "data": {"user_id": 1}}],
                                          profile=LLBOT_MILKY, is_group=True)
    assert grouped == [{"type": "mention", "data": {"user_id": 1}}]


def test_reply_id_is_renamed_with_note():
    """OneBot 的 reply.id 到 Milky 要变成 message_seq，且必须记 note（命名空间不同）。"""
    wire, notes = serialize_milky_segments([{"type": "reply", "data": {"id": 42}}],
                                           profile=MILKY_SPEC)
    assert wire == [{"type": "reply", "data": {"message_seq": 42}}]
    assert NOTE_DROPPED_FIELD in _reasons(notes)


def test_unknown_segment_passthrough():
    wire, notes = serialize_milky_segments([{"type": "future_seg", "data": {"a": 1}}],
                                           profile=MILKY_SPEC)
    assert wire == [{"type": "future_seg", "data": {"a": 1}}]
    assert NOTE_UNKNOWN_SEGMENT in _reasons(notes)


# ---------------------------------------------------------------- 响应模型

def test_milky_response_fixtures_via_production_code():
    """响应包封语料（tests/fixtures/milky/actions/）必须能被生产解析器读通。"""
    ok = parse_milky_response(_load(os.path.join("actions", "action_send_group_message_ok.json")))
    assert ok["ok"] is True and ok["data"]["message_seq"] == 77130
    bad = parse_milky_response(_load(os.path.join("actions", "action_failed_response.json")))
    assert bad["ok"] is False and "被回复的消息未找到" in bad["error"]


def test_milky_response_envelope():
    assert parse_milky_response({"status": "ok", "retcode": 0, "data": {"x": 1}}) == \
        {"ok": True, "data": {"x": 1}}
    failed = parse_milky_response({"status": "failed", "retcode": 1, "message": "boom"})
    assert failed["ok"] is False and "boom" in failed["error"]
    assert parse_milky_response(None)["ok"] is False


# ---------------------------------------------------------------- 往返

def test_roundtrip_milky_fixtures():
    """入站 fixture → 出站段：**不许静默消失** —— 每个消失/改写的段都要有 note。

    与 OneBot 侧不同：Milky 的入站/出站段联合体**本来就不对称**
    （入站有 market_face/xml/markdown/forward_id，出站只有 light_app 与构造式 forward），
    所以这里断言的是"消失必有说明"，而不是"类型必须一一对应"。
    """
    total = kept_total = unverified = 0
    lines = []
    for path in sorted(glob.glob(os.path.join(FIXTURES, "*.json"))):
        name = os.path.basename(path)
        raw = _load(name)
        ev = MilkyEventParser(bot_qq=BOT_QQ).parse(raw)
        inbound = [s.get("type") for s in (ev.message_segments or []) if isinstance(s, dict)]
        wire, notes = serialize_milky_segments(ev.message_segments, profile=MILKY_SPEC,
                                               is_group=(ev.scope == "group"))
        outbound = [s["type"] for s in wire]
        assert set(outbound) <= set(inbound), (name, inbound, outbound)
        for missing in set(inbound) - set(outbound):
            assert any(n["type"] == missing for n in notes),                 "%s：段 %s 消失但没有 note（不允许静默丢）" % (name, missing)
        for note in notes:
            assert note.get("reason"), note
        total += len(inbound)
        kept_total += len(outbound)
        unverified += sum(1 for n in notes if n["reason"] == NOTE_UNSUPPORTED_SEGMENT
                          or n["reason"] == NOTE_UNKNOWN_SEGMENT)
        lines.append("  %-38s 入站 %-3d 出站 %-3d 消失 %s" % (
            name, len(inbound), len(outbound), sorted(set(inbound) - set(outbound))))
    print("Milky 往返（segment 级）：%d/%d 可出站（其中 %d 段是**未验证**的原样传递）"
          % (kept_total, total, unverified))
    print("\n".join(lines))
    assert total > 0


def test_incoming_media_needs_uri_and_says_so():
    """入站图片段只有 resource_id/temp_url：temp_url 可发但要说明，只有 resource_id 就只能丢并说明。"""
    wire, notes = serialize_milky_segments(
        [{"type": "image", "data": {"resource_id": "r1", "temp_url": "https://t/x.jpg"}}],
        profile=MILKY_SPEC)
    assert wire[0]["data"]["uri"] == "https://t/x.jpg"
    assert NOTE_DROPPED_FIELD in _reasons(notes)

    wire2, notes2 = serialize_milky_segments(
        [{"type": "image", "data": {"resource_id": "r1"}}], profile=MILKY_SPEC)
    assert wire2 == [] and NOTE_INVALID in _reasons(notes2)


def test_incoming_forward_cannot_roundtrip():
    """入站 forward 只有 forward_id；出站要 messages[] —— 明确不往返并给出原因。"""
    wire, notes = serialize_milky_segments(
        [{"type": "forward", "data": {"forward_id": "fwd-1", "title": "t"}}], profile=MILKY_SPEC)
    assert wire == []
    assert NOTE_INVALID in _reasons(notes)
    assert "forward_id" in notes[0]["detail"]
