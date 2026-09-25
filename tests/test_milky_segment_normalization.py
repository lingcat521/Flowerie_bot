"""Milky 段归一化测试（P4）：夹具形态来自 Milky 规范与作者实现源码，不凭印象构造。

证据来源：
- 规范 `protocol/src/ir/common.ts` 的 IncomingSegment 联合（**14 种**）：
  text / mention / mention_all / face / reply / image / record / video / file /
  forward / market_face / light_app / xml / markdown
- 作者实现有**两份布局不同**的内嵌副本（均为 [CODE]）：
  `LagrangeV2/Lagrange.Milky/Entity/Segment/`（15 个文件 = 13 种 incoming + 基类/接口，
  **含** face / market_face / xml，**无** markdown）与
  `Lagrange.Core/Lagrange.Milky/Models/Segments/`（11 个文件 = 10 种 incoming，
  无 face / market_face / xml / markdown）—— 见 docs/protocol-reverse-engineering.md §6.1
- 字段宽度也不同：V2 的 market_face 只有 `url`、face 只有 `face_id`，规范另有 emoji_id/summary/is_large
- 映射后的键名与 OneBot 侧同形（复用 onebot_parser 的归一化函数），Assembler 共用一条通路
"""
from src.adapters.milky_parser import MilkyEventParser


def _msg(segments, scene="group", **extra):
    data = {"message_scene": scene, "peer_id": 123, "sender_id": 456,
            "message_id": 789, "segments": segments}
    data.update(extra)
    return {"time": 1700000000, "self_id": 10001,
            "event_type": "message_receive", "data": data}


def _parse(segments, **extra):
    return MilkyEventParser(bot_qq=10001).parse(_msg(segments, **extra))


# ---------- light_app → json_cards ----------

def test_light_app_multimsg_detected_as_forward_card():
    payload = '{"app":"com.tencent.multimsg","meta":{"detail":{"resid":"abc"}}}'
    ev = _parse([{"type": "light_app",
                  "data": {"app_name": "com.tencent.multimsg", "json_payload": payload}}])
    assert ev.json_cards[0]["app"] == "com.tencent.multimsg"
    assert ev.json_cards[0]["is_forward_card"] is True
    assert isinstance(ev.json_cards[0]["payload"], dict)


def test_light_app_falls_back_to_app_name_when_payload_not_json():
    ev = _parse([{"type": "light_app",
                  "data": {"app_name": "某小程序", "json_payload": "not-json"}}])
    assert ev.json_cards[0]["app"] == "某小程序"
    assert ev.json_cards[0]["is_forward_card"] is False
    assert ev.json_cards[0]["payload"] == "not-json"


# ---------- face / market_face → faces ----------

def test_market_face_normalized_like_onebot():
    ev = _parse([{"type": "market_face",
                  "data": {"emoji_package_id": 1, "emoji_id": "9", "key": "k",
                           "summary": "[表情]", "url": "http://example/x"}}])
    f = ev.faces[0]
    assert f["kind"] == "market_face"
    assert f["emoji_id"] == "9" and f["package_id"] == "1"
    assert f["summary"] == "[表情]" and f["url"] == "http://example/x"


def test_face_segment_spec_shape():
    ev = _parse([{"type": "face", "data": {"face_id": "14", "is_large": True}}])
    f = ev.faces[0]
    assert f["kind"] == "face" and f["face_id"] == "14" and f["is_large"] is True


# ---------- forward / file ----------

def test_forward_segment_fields():
    ev = _parse([{"type": "forward",
                  "data": {"forward_id": "fid", "title": "t", "preview": ["a", "b"],
                           "summary": "s"}}])
    fw = ev.forwards[0]
    assert fw["id"] == "fid" and fw["inline"] is False
    assert fw["title"] == "t" and fw["preview"] == ["a", "b"] and fw["summary"] == "s"


def test_file_segment_fields():
    ev = _parse([{"type": "file",
                  "data": {"file_id": "x", "file_name": "a.zip", "file_size": 10,
                           "file_hash": "h"}}])
    f = ev.files[0]
    assert f["file_id"] == "x" and f["name"] == "a.zip" and f["size"] == 10


# ---------- markdown → text ----------

def test_markdown_content_joins_text():
    ev = _parse([{"type": "text", "data": {"text": "看这个 "}},
                 {"type": "markdown", "data": {"content": "**公告**"}}])
    assert ev.text == "看这个 **公告**"


# ---------- 旧通道不回归 ----------

def test_summary_channel_still_populated():
    ev = _parse([{"type": "market_face", "data": {"emoji_id": "9"}},
                 {"type": "xml", "data": {"service_id": 1, "xml_payload": "<x/>"}}])
    kinds = [t for t, _ in ev.segments_summary]
    assert "market_face" in kinds and "xml" in kinds


def test_reply_message_seq_and_inline_segments_kept():
    ev = _parse([{"type": "reply", "data": {"message_seq": 555, "sender_id": 1,
                                            "time": 1, "segments": [{"type": "text", "data": {"text": "旧"}}]}}])
    assert ev.reply_id == 555
    assert ev.segments_summary and ev.segments_summary[0][0] == "reply"
