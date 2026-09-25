"""G8：OneBot 12 骨架适配器契约测试（NOT_REAL_DEVICE_VALIDATED）。

证据：[DOC] 官方规范 botuniverse/onebot（HEAD d533f0f）：
- specs/connect/data-protocol/event.md（事件必备字段与示例）
- specs/connect/data-protocol/action-response.md（status/retcode/data/message/echo）
- specs/interface/message/type.md（段数组 / alt_message 替代表示）
- specs/interface/message/segments.md（text/mention/mention_all/image/voice/audio/video/file/location/reply）

任务书 §10.2 允许在**没有真实 v12 客户端**时交付
「adapter skeleton + normalization mapping + fixture + contract tests」，但**不得**声称 fully supported。
"""
import json
import os

from src.adapters.onebot12_parser import (
    V12_ACTION_MAP,
    OneBot12EventParser,
    normalize_action_response,
)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
BOT = "10001"


def _parse(raw):
    return OneBot12EventParser(bot_qq=BOT).parse(raw)


def _msg(segments, **extra):
    raw = {"id": "evt-1", "time": 1632847927.599013, "type": "message",
           "detail_type": "group", "sub_type": "", "self": {"platform": "qq", "user_id": BOT},
           "message_id": "6283", "group_id": "123456", "user_id": "456789",
           "message": segments}
    raw.update(extra)
    return raw


# ---------- 事件信封 ----------

def test_v12_event_envelope_maps_to_domain_fields():
    ev = _parse(_msg([{"type": "text", "data": {"text": "hi"}}]))
    assert ev.kind == "message" and ev.scope == "group" and ev.scene == "group"
    assert ev.event_id == "evt-1"
    assert ev.timestamp == 1632847927
    assert ev.group_id == 123456 and ev.actor_id == 456789 and ev.message_id == 6283
    assert ev.text == "hi"


def test_v12_type_becomes_kind_and_unknown_type_kept():
    assert _parse({"id": "e", "time": 1.0, "type": "meta", "detail_type": "heartbeat"}).kind == "lifecycle"
    assert _parse({"id": "e", "time": 1.0, "type": "notice", "detail_type": "group_upload"}).kind == "notice"
    req = _parse({"id": "e", "time": 1.0, "type": "request", "detail_type": "group",
                  "sub_type": "", "user_id": "1", "group_id": "2", "comment": "c"})
    assert req.kind == "request" and req.comment == "c"
    unknown = _parse({"id": "e", "time": 1.0, "type": "future_type", "detail_type": "x"})
    assert unknown.kind == "future_type"


def test_v12_invalid_event_without_type_does_not_crash():
    ev = _parse({"time": 1.0})
    assert ev.kind == "unknown" and ev.event_id


# ---------- 消息段 ----------

def test_v12_mention_and_mention_all():
    ev = _parse(_msg([{"type": "mention", "data": {"user_id": BOT}},
                      {"type": "mention_all", "data": {}}]))
    assert ev.mentions == ["10001", "all"] and ev.is_mentioned is True


def test_v12_image_file_id():
    ev = _parse(_msg([{"type": "image", "data": {"file_id": "img-1"}}]))
    assert "file_id:img-1" in ev.images


def test_v12_voice_and_audio_both_map_to_records_with_kind():
    ev = _parse(_msg([{"type": "voice", "data": {"file_id": "v1", "url": "u1", "duration": 3}},
                      {"type": "audio", "data": {"file_id": "a1", "url": "u2"}}]))
    assert [r["kind"] for r in ev.records] == ["voice", "audio"]
    assert ev.records[0]["url"] == "u1" and ev.records[0]["duration"] == 3


def test_v12_video_and_file():
    ev = _parse(_msg([{"type": "video", "data": {"file_id": "vid", "url": "u"}},
                      {"type": "file", "data": {"file_id": "f1", "file_name": "a.zip"}}]))
    assert ev.videos[0]["url"] == "u" and ev.files[0]["file_id"] == "f1"


def test_v12_reply_keeps_string_id_and_int_view():
    ev = _parse(_msg([{"type": "reply", "data": {"message_id": "6000"}}]))
    assert ev.reply_id == 6000 and ev.reply_ref["message_id"] == "6000"


def test_v12_location_is_preserved_but_not_modeled():
    ev = _parse(_msg([{"type": "location", "data": {"latitude": 1.0, "longitude": 2.0}}]))
    assert ("location", {"latitude": 1.0, "longitude": 2.0}) in ev.segments_summary


def test_v12_unknown_segment_is_preserved():
    ev = _parse(_msg([{"type": "future_segment", "data": {"foo": "bar"}}]))
    assert ("future_segment", {"foo": "bar"}) in ev.segments_summary


def test_v12_alt_message_used_only_when_no_text_segment():
    ev = _parse(_msg([{"type": "image", "data": {"file_id": "x"}}], alt_message="[图片]"))
    assert ev.text == "[图片]"
    ev2 = _parse(_msg([{"type": "text", "data": {"text": "真实文本"}}], alt_message="替代"))
    assert ev2.text == "真实文本"


# ---------- 动作映射与响应 ----------

def test_v12_action_map_covers_core_actions():
    for v11 in ("send_group_msg", "send_private_msg", "delete_msg", "get_group_info",
                "get_group_member_list", "get_friend_list", "get_login_info"):
        assert v11 in V12_ACTION_MAP
    assert V12_ACTION_MAP["send_group_msg"] == "send_message"
    assert V12_ACTION_MAP["delete_msg"] == "delete_message"


def test_v12_action_response_normalization():
    ok = normalize_action_response({"status": "ok", "retcode": 0, "data": {"message_id": "1"},
                                    "message": "", "echo": "e1"})
    assert ok["ok"] is True and ok["data"] == {"message_id": "1"} and ok["echo"] == "e1"
    bad = normalize_action_response({"status": "failed", "retcode": 10101,
                                     "data": None, "message": "Who Am I"})
    assert bad["ok"] is False and "Who Am I" in bad["error"]


# ---------- 夹具 ----------

def test_v12_fixture_parses_with_provenance():
    path = os.path.join(FIXTURES, "onebot12", "message_group.json")
    if not os.path.exists(path):
        return
    raw = json.load(open(path, encoding="utf-8"))
    assert raw["_provenance"]["evidence"]
    ev = _parse({k: v for k, v in raw.items() if not k.startswith("_")})
    assert ev.kind == "message" and ev.is_mentioned is True
    assert ev.records and ev.images and ev.reply_id == 6000
