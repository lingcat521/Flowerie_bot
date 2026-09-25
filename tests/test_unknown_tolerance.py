"""Gate J/K/L：Unknown Segment / Unknown Event 容错与原始数据保真。

任务书 B 部分要求（硬门槛）：
- Gate J：至少 10 个未知 Segment —— 不崩溃、不丢 type、不丢 payload、可进入归一化消息、可被日志观察
- Gate K：至少 10 个未知 Event —— 不崩溃、保留 event type、保留 raw payload、进入统一事件管道
- Gate L：Raw Preservation —— type 100% 保留、payload 100% 保留（允许加 metadata，不得静默删字段）

三者共同回答一句话：**遇到没见过的东西，Flowerie 不能崩、也不能悄悄丢信息。**
"""
import copy

import pytest

from src.adapters.milky_parser import MilkyEventParser
from src.adapters.onebot_parser import OneBotEventParser

BOT_QQ = 10001

# 10 个未知段：名字故意取得像未来的东西，payload 各不相同（含嵌套、数组、特殊字符）
UNKNOWN_SEGMENTS = [
    ("future_image", {"file_id": "f-1", "url": "https://x/1.png", "ai_generated": True}),
    ("future_sticker", {"pack_id": "p-1", "sticker_id": 42}),
    ("future_card", {"app": "com.example.future", "meta": {"detail": {"resid": "r"}}}),
    ("future_attachment", {"files": [{"id": "a"}, {"id": "b"}], "count": 2}),
    ("future_location", {"latitude": 31.2, "longitude": 121.5, "name": "上海"}),
    ("future_poll", {"question": "选哪个？", "options": ["A", "B"], "multi": False}),
    ("future_reaction", {"emoji": "👍", "count": 3}),
    ("future_thread", {"root_id": "900", "depth": 2}),
    ("future_music", {"provider": "netEase", "id": "12345"}),
    ("future_unknown_<>&\"", {"nested": {"deep": [1, 2, {"x": None}]}, "text": "<script>"}),
]

# 10 个未知事件（OneBot 侧：post_type 未知；Milky 侧：event_type 未知）
UNKNOWN_ONEBOT_EVENTS = [
    {"post_type": "future_event", "sub_type": "alpha"},
    {"post_type": "future_event", "sub_type": "beta", "extra": {"n": 1}},
    {"post_type": "message", "message_type": "future_chat", "message_id": 1, "user_id": 2},
    {"post_type": "notice", "notice_type": "future_notice", "group_id": 3},
    {"post_type": "request", "request_type": "future_request", "user_id": 4},
    {"post_type": "meta_event", "meta_event_type": "future_meta"},
    {"post_type": "future_event", "payload": [1, 2, 3]},
    {"post_type": "future_event", "unicode": "emoji 🎉 中文"},
    {"post_type": "future_event", "deep": {"a": {"b": {"c": ["d"]}}}},
    {"post_type": "future_event", "null_field": None, "empty_list": [], "empty_obj": {}},
]

UNKNOWN_MILKY_EVENTS = [
    {"event_type": "future_event", "data": {"a": 1}},
    {"event_type": "future_notice", "data": {"b": [1, 2]}},
    {"event_type": "future_request", "data": {"c": {"d": "e"}}},
    {"event_type": "future_lifecycle", "data": {}},
    {"event_type": "group_future_thing", "data": {"group_id": 123}},
    {"event_type": "peer_future_change", "data": {"peer_id": 456}},
    {"event_type": "future_event", "data": {"unicode": "🎉", "nil": None}},
    {"event_type": "future_event", "data": {"nested": [{"x": 1}, {"y": 2}]}},
    {"event_type": "future_event", "data": {"long": "x" * 500}},
    {"event_type": "future_event", "data": {"escape": '<b>&"\''}},
]


def _onebot_msg(segments, **extra):
    raw = {"post_type": "message", "message_type": "group", "group_id": 123456,
           "user_id": 456789, "message_id": 1, "time": 1700000000, "message": segments}
    raw.update(extra)
    return raw


def _milky_msg(segments):
    return {"time": 1700000000, "self_id": BOT_QQ, "event_type": "message_receive",
            "data": {"message_scene": "group", "peer_id": 123456, "sender_id": 456789,
                     "message_seq": 1, "segments": segments}}


# ---------- Gate J：未知 Segment ----------

@pytest.mark.parametrize("name,payload", UNKNOWN_SEGMENTS, ids=[s[0] for s in UNKNOWN_SEGMENTS])
def test_unknown_segment_onebot_does_not_crash_and_preserves(name, payload):
    seg = {"type": name, "data": copy.deepcopy(payload)}
    ev = OneBotEventParser(bot_qq=BOT_QQ).parse(
        _onebot_msg([{"type": "text", "data": {"text": "前后都有文字"}}, seg]))
    # 1) 不崩溃、消息仍然被解析（已知部分照常）
    assert ev.kind == "message" and ev.text == "前后都有文字"
    # 2) type 与 payload 100% 保留（Gate L）
    assert (name, payload) in ev.segments_summary
    # 3) 原始段也在（可被调试/日志观察）
    assert any(isinstance(s, dict) and s.get("type") == name for s in ev.message_segments)


@pytest.mark.parametrize("name,payload", UNKNOWN_SEGMENTS, ids=[s[0] for s in UNKNOWN_SEGMENTS])
def test_unknown_segment_milky_does_not_crash_and_preserves(name, payload):
    seg = {"type": name, "data": copy.deepcopy(payload)}
    ev = MilkyEventParser(bot_qq=BOT_QQ).parse(_milky_msg([seg]))
    assert ev.kind == "message"
    assert (name, payload) in ev.segments_summary
    assert any(isinstance(s, dict) and s.get("type") == name for s in ev.message_segments)


def test_unknown_segments_do_not_block_known_media_segments():
    # 已知段（图/文件/表情…）与多个未知段混在一起时，已知信息不能丢
    segs = [{"type": "future_a", "data": {"x": 1}},
            {"type": "image", "data": {"file": "a.jpg", "url": "https://x/a.jpg"}},
            {"type": "future_b", "data": {"y": 2}},
            {"type": "face", "data": {"id": "14"}},
            {"type": "future_c", "data": {"z": 3}}]
    ev = OneBotEventParser(bot_qq=BOT_QQ).parse(_onebot_msg(segs))
    assert ev.images and ev.image_files == ["a.jpg"]
    assert ev.faces and ev.faces[0]["face_id"] == "14"
    assert len([t for t, _ in ev.segments_summary if t.startswith("future_")]) == 3


# ---------- Gate K：未知 Event ----------

@pytest.mark.parametrize("raw", UNKNOWN_ONEBOT_EVENTS, ids=[str(i) for i in range(len(UNKNOWN_ONEBOT_EVENTS))])
def test_unknown_event_onebot_keeps_type_and_raw(raw):
    ev = OneBotEventParser(bot_qq=BOT_QQ).parse(copy.deepcopy(raw))
    assert ev.kind  # 不崩、有 kind（未知类型原样保留）
    assert ev.raw_data == raw          # Gate L：raw 100% 保留


@pytest.mark.parametrize("raw", UNKNOWN_MILKY_EVENTS, ids=[str(i) for i in range(len(UNKNOWN_MILKY_EVENTS))])
def test_unknown_event_milky_keeps_type_and_raw(raw):
    full = {"time": 1700000000, "self_id": BOT_QQ}
    full.update(copy.deepcopy(raw))
    ev = MilkyEventParser(bot_qq=BOT_QQ).parse(full)
    assert ev.kind and ev.kind != "unknown"     # 未知 event_type 原样保留为 kind
    assert ev.raw_data == full


def test_unknown_event_type_is_visible_not_swallowed():
    ev = OneBotEventParser(bot_qq=BOT_QQ).parse({"post_type": "future_event", "x": 1})
    assert ev.kind == "future_event"
    ev2 = MilkyEventParser(bot_qq=BOT_QQ).parse({"event_type": "future_event", "data": {}})
    assert ev2.kind == "future_event"


# ---------- 组合：未知段 + 未知事件 ----------

def test_unknown_segment_inside_unknown_event_still_safe():
    raw = {"post_type": "future_event", "message": [{"type": "future_seg", "data": {"k": "v"}}]}
    ev = OneBotEventParser(bot_qq=BOT_QQ).parse(raw)
    assert ev.raw_data == raw and ev.kind == "future_event"
