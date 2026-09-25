"""G4：Milky `reply.segments`（内联被引内容）回归。

证据：
- [DOC] Milky 规范 `common.ts` L327-333：`reply{message_seq, sender_id, sender_name?, time, segments[]}`
  —— 被引消息的**完整段数组内联**。
- [DOC] OneBot 11 `event/message.md` / [CODE] NapCat `types/message.ts` `OB11MessageReplySchema`：
  OneBot 的 reply 段**只有 id（+qq）**，没有内联段。
- 任务书 §6.2：**必须同时保留 message_seq**（引用目标的稳定标识），不能因为拿到内联内容就丢掉它。

修复前：`reply.segments` 只进 `segments_summary`，被引内容实际未被消费。
"""
import os

from src.adapters.milky_parser import MilkyEventParser
from src.adapters.onebot_parser import OneBotEventParser

BOT_QQ = 10001
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _milky(segments):
    return MilkyEventParser(bot_qq=BOT_QQ).parse(
        {"time": 1, "self_id": BOT_QQ, "event_type": "message_receive",
         "data": {"message_scene": "group", "peer_id": 123456, "sender_id": 456789,
                  "message_seq": 1, "segments": segments}})


def _onebot(segments, **extra):
    raw = {"post_type": "message", "message_type": "group", "group_id": 123456,
           "user_id": 456789, "message_id": 1, "time": 1, "message": segments}
    raw.update(extra)
    return OneBotEventParser(bot_qq=BOT_QQ).parse(raw)


def _reply(segs, **extra):
    data = {"message_seq": 900, "sender_id": 111222, "sender_name": "甲", "time": 123}
    if segs is not None:
        data["segments"] = segs
    data.update(extra)
    return {"type": "reply", "data": data}


# ---------- 任务书 §6.3 要求的四类 ----------

def test_reply_plus_text():
    ev = _milky([_reply([{"type": "text", "data": {"text": "被引文本"}}]),
                 {"type": "text", "data": {"text": "我的回复"}}])
    assert ev.reply_id == 900                      # message_seq 保留（§6.2）
    assert ev.reply_text == "被引文本"
    assert ev.text == "我的回复"                    # 内联内容不污染当前消息文本
    assert ev.reply_ref["sender_id"] == 111222 and ev.reply_ref["sender_name"] == "甲"
    assert ev.reply_ref["time"] == 123 and ev.reply_ref["id"] == 900


def test_reply_plus_image():
    ev = _milky([_reply([{"type": "image", "data": {"resource_id": "r", "temp_url": "https://x/i.jpg"}}])])
    assert ev.reply_segments and ev.reply_segments[0]["type"] == "image"
    assert ev.reply_text == ""                     # 无文本段 → 空，不编造摘要
    assert ev.reply_id == 900


def test_reply_plus_multiple_segments():
    ev = _milky([_reply([{"type": "text", "data": {"text": "前"}},
                         {"type": "image", "data": {"resource_id": "r"}},
                         {"type": "text", "data": {"text": "后"}}])])
    assert [s["type"] for s in ev.reply_segments] == ["text", "image", "text"]   # 顺序保真
    assert ev.reply_text == "前后"                  # 只拼接文本段


def test_reply_without_segments_keeps_reference():
    ev = _milky([_reply(None)])
    assert ev.reply_id == 900 and ev.reply_segments == [] and ev.reply_text == ""
    assert ev.reply_ref["id"] == 900
    assert ev.segments_summary == []                # 无内联段时不额外塞 summary


# ---------- OneBot：没有内联就如实为空 ----------

def test_onebot_reply_has_no_inline_content():
    ev = _onebot([{"type": "reply", "data": {"id": 991000, "qq": 10001}},
                  {"type": "text", "data": {"text": "回复"}}])
    assert ev.reply_id == 991000
    assert ev.reply_segments == [] and ev.reply_text == ""
    assert ev.reply_ref == {"id": 991000, "sender_id": 10001}
    assert ev.is_reply_to_bot is True               # 旧行为不回归


def test_old_reply_behavior_not_regressed():
    ev = _onebot([{"type": "reply", "data": {"id": 5, "qq": 999}}])
    assert ev.reply_id == 5 and ev.has_reply_to_other is True and ev.is_reply_to_bot is False


# ---------- Assembler ----------

def test_assembler_renders_inline_quote_only_when_present():
    from src.core.message_assembler import MessageAssembler

    class _Cfg:
        VISION_ENABLED = False

    asm = MessageAssembler(_Cfg(), None, object(), None)
    milky = _milky([_reply([{"type": "text", "data": {"text": "被引文本"}}])])
    onebot = _onebot([{"type": "reply", "data": {"id": 1}}])
    assert "引用的消息" in asm._assemble_quote(milky) and "被引文本" in asm._assemble_quote(milky)
    assert asm._assemble_quote(onebot) == ""        # OneBot 没有内联 → 不渲染、不编造


# ---------- 夹具 + round-trip ----------

def test_reply_fixtures_parse_with_provenance():
    import json
    seen = 0
    for rel, kind in (("milky/reply_with_inline_segments.json", "milky"),
                      ("onebot11/reply_segment.json", "onebot")):
        path = os.path.join(FIXTURES, rel)
        if not os.path.exists(path):
            continue
        raw = json.load(open(path, encoding="utf-8"))
        assert raw["_provenance"]["evidence"], rel
        ev = (_milky(raw["data"]["segments"]) if kind == "milky" else _onebot(raw["message"]))
        if kind == "milky":
            assert ev.reply_text == "原始消息内容" and len(ev.reply_segments) == 2
        else:
            assert ev.reply_id == 991000 and ev.reply_text == ""
        seen += 1
    assert seen == 2


def test_reply_roundtrip_stable():
    segs = [_reply([{"type": "text", "data": {"text": "被引"}},
                    {"type": "image", "data": {"resource_id": "r"}}]),
            {"type": "text", "data": {"text": "回复"}}]
    ev = _milky(segs)
    rebuilt = {"time": 1, "self_id": BOT_QQ, "event_type": "message_receive",
               "data": {"message_scene": "group", "peer_id": 123456, "sender_id": 456789,
                        "message_seq": 1, "segments": ev.message_segments}}
    ev2 = MilkyEventParser(bot_qq=BOT_QQ).parse(rebuilt)
    assert ev2.reply_id == ev.reply_id and ev2.reply_text == ev.reply_text
    assert ev2.reply_segments == ev.reply_segments and ev2.reply_ref == ev.reply_ref
