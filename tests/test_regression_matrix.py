"""Gate U：真实现有功能零回归（18 项能力回归矩阵）。

任务书 §22 要求列出的能力（text/at/reply/image/face/market_face/file/group_upload/forward/
JSON-Ark/poke/markdown/light_app/recall）都必须建立 regression matrix，**至少 15 项、15/15 PASS**，
"不能因为架构重构导致已有能力下降"。

本矩阵每一项：
- 给出**协议原生最小样本**喂真解析器，断言归一化载体（不是看文档说"支持"）；
- 标注它在重构**之前**就由哪些既有测试/夹具覆盖（`baseline`）—— 这才是"回归"而不是"新功能"；
- 两项运行期证据：解析结果 + raw_data 保真。

矩阵 18 项（任务书列举的 14 项 + G1–G4 期间补齐的 temp/record/video/xml），全部 PASS。
"""
import pytest

from src.adapters.milky_parser import MilkyEventParser
from src.adapters.onebot_parser import OneBotEventParser

BOT_QQ = 10001
GROUP = 123456
USER = 456789
IMG = "https://example.com/a.png"


def _ob_message(segments, **over):
    raw = {"post_type": "message", "message_type": "group", "sub_type": "normal", "group_id": GROUP,
           "user_id": USER, "message_id": 1001, "time": 1700000000, "message": segments}
    raw.update(over)
    return raw


def _ob_notice(**over):
    raw = {"post_type": "notice", "group_id": GROUP, "user_id": USER, "time": 1700000000}
    raw.update(over)
    return raw


def _mk(data, event_type="message_receive"):
    return {"time": 1700000000, "self_id": BOT_QQ, "event_type": event_type, "data": data}


def _mk_msg(segments, **over):
    data = {"message_scene": "group", "peer_id": GROUP, "sender_id": USER, "message_seq": 1001,
            "segments": segments}
    data.update(over)
    return _mk(data)


OB = lambda raw: OneBotEventParser(bot_qq=BOT_QQ).parse(raw)      # noqa: E731
MK = lambda raw: MilkyEventParser(bot_qq=BOT_QQ).parse(raw)       # noqa: E731

MATRIX = [
    {"item": "text", "baseline": "test_adapters.py / test_router_migration.py", "checks": [
        ("onebot11", _ob_message([{"type": "text", "data": {"text": "hi"}}]), OB, lambda ev: ev.text == "hi"),
        ("milky", _mk_msg([{"type": "text", "data": {"text": "hi"}}]), MK, lambda ev: ev.text == "hi")]},
    {"item": "at", "baseline": "test_adapters.py / test_name_mention_reply.py", "checks": [
        ("onebot11", _ob_message([{"type": "at", "data": {"qq": str(BOT_QQ)}}]), OB,
         lambda ev: ev.is_mentioned is True),
        ("milky", _mk_msg([{"type": "mention", "data": {"user_id": BOT_QQ}}]), MK,
         lambda ev: ev.is_mentioned is True)]},
    {"item": "reply", "baseline": "test_reply_inline.py / test_name_mention_reply.py", "checks": [
        ("onebot11", _ob_message([{"type": "reply", "data": {"id": "1001"}}]), OB,
         lambda ev: ev.reply_id == 1001),
        ("milky", _mk_msg([{"type": "reply", "data": {"message_seq": 1001}}]), MK,
         lambda ev: ev.reply_ref.get("id") == 1001)]},
    {"item": "image", "baseline": "test_image_source_compat.py / test_adapter_segment_normalization.py",
     "checks": [
         ("onebot11", _ob_message([{"type": "image", "data": {"file": "a.png", "url": IMG}}]), OB,
          lambda ev: ev.images == [IMG] and ev.image_files == ["a.png"]),
         ("milky", _mk_msg([{"type": "image", "data": {"temp_url": IMG, "resource_id": "r1"}}]), MK,
          lambda ev: ev.images == [IMG])]},
    {"item": "face", "baseline": "test_face_context.py", "checks": [
        ("onebot11", _ob_message([{"type": "face", "data": {"id": "14"}}]), OB,
         lambda ev: ev.faces[0]["face_id"] == "14"),
        ("milky", _mk_msg([{"type": "face", "data": {"face_id": 14}}]), MK,
         lambda ev: ev.faces[0]["face_id"] == "14")]},
    {"item": "market_face", "baseline": "test_milky_segment_normalization.py", "checks": [
        ("onebot11", _ob_message([{"type": "mface", "data": {"emoji_id": "e1", "summary": "[猫]"}}]), OB,
         lambda ev: ev.faces[0]["kind"] == "market_face" and ev.faces[0]["summary"] == "[猫]"),
        ("milky", _mk_msg([{"type": "market_face", "data": {"url": IMG}}]), MK,
         lambda ev: ev.faces[0]["kind"] == "market_face")]},
    {"item": "file", "baseline": "test_adapter_segment_normalization.py / test_router_migration.py",
     "checks": [
         ("onebot11", _ob_message([{"type": "file", "data": {"file_id": "f1", "file": "a.zip",
                                                             "file_size": 9}}]), OB,
          lambda ev: ev.files[0]["file_id"] == "f1" and ev.files[0]["name"] == "a.zip"),
         ("milky", _mk_msg([{"type": "file", "data": {"file_id": "f1", "file_name": "a.zip",
                                                      "file_size": 9}}]), MK,
          lambda ev: ev.files[0]["name"] == "a.zip")]},
    {"item": "group_upload", "baseline": "test_router_migration.py / test_milky_event_kinds.py", "checks": [
        ("onebot11", _ob_notice(notice_type="group_upload",
                                file={"id": "f1", "name": "a.zip", "size": 9, "busid": 0}), OB,
         lambda ev: ev.kind == "notice" and ev.notice_kind == "group_upload"
         and ev.notice_file["resource"].ref == "f1"),
        ("milky", _mk({"group_id": GROUP, "user_id": USER, "file_id": "f1", "file_name": "a.zip",
                       "file_size": 9}, event_type="group_file_upload"), MK,
         lambda ev: ev.notice_kind == "group_upload" and ev.notice_file["resource"].origin == "milky")]},
    {"item": "forward", "baseline": "test_multimsg_card.py / test_milky_event_kinds.py", "checks": [
        ("onebot11", _ob_message([{"type": "forward", "data": {"id": "fwd1"}}]), OB,
         lambda ev: ev.forwards[0]["id"] == "fwd1"),
        ("milky", _mk_msg([{"type": "forward", "data": {"forward_id": "fwd1"}}]), MK,
         lambda ev: ev.forwards[0]["id"] == "fwd1")]},
    {"item": "json_ark", "baseline": "test_multimsg_card.py", "checks": [
        ("onebot11", _ob_message([{"type": "json", "data": {"data": '{"app":"com.tencent.multimsg"}'}}]), OB,
         lambda ev: ev.json_cards[0]["app"] == "com.tencent.multimsg"
         and ev.json_cards[0]["is_forward_card"] is True),
        ("milky", _mk_msg([{"type": "light_app",
                            "data": {"app_name": "com.tencent.multimsg", "json_payload": "{}"}}]), MK,
         lambda ev: ev.json_cards[0]["is_forward_card"] is True)]},
    {"item": "poke", "baseline": "test_adapter_segment_normalization.py / test_milky_event_kinds.py",
     "checks": [
         ("onebot11", _ob_message([{"type": "poke", "data": {"type": "1", "id": "2"}}]), OB,
          lambda ev: ev.pokes[0]["poke_id"] == "2"),
         ("milky", _mk({"group_id": GROUP, "sender_id": USER, "receiver_id": BOT_QQ,
                        "display_action": "戳了戳"}, event_type="group_nudge"), MK,
          lambda ev: ev.kind == "notice" and ev.notice_kind == "poke")]},
    {"item": "markdown", "baseline": "test_markdown_mini.py / test_milky_segment_normalization.py",
     "checks": [
         ("onebot11", _ob_message([{"type": "markdown", "data": {"content": "# 标题"}}]), OB,
          lambda ev: "# 标题" in ev.text),
         ("milky", _mk_msg([{"type": "markdown", "data": {"content": "# 标题"}}]), MK,
          lambda ev: "# 标题" in ev.text)]},
    {"item": "light_app", "baseline": "test_milky_segment_normalization.py", "checks": [
        ("onebot11", _ob_message([{"type": "miniapp", "data": {"data": '{"app":"com.tencent.miniapp"}'}}]),
         OB, lambda ev: ev.json_cards[0]["app"] == "com.tencent.miniapp"),
        ("milky", _mk_msg([{"type": "light_app",
                            "data": {"app_name": "com.tencent.miniapp", "json_payload": "{}"}}]), MK,
         lambda ev: ev.json_cards[0]["app"] == "com.tencent.miniapp")]},
    {"item": "recall", "baseline": "test_milky_event_kinds.py / test_router_regression.py", "checks": [
        ("onebot11", _ob_notice(notice_type="group_recall", operator_id=USER, message_id=1001), OB,
         lambda ev: ev.kind == "notice" and ev.notice_kind == "group_recall"),
        ("milky", _mk({"message_scene": "group", "peer_id": GROUP, "message_seq": 1001,
                       "sender_id": USER, "operator_id": USER}, event_type="message_recall"), MK,
         lambda ev: ev.kind == "notice" and ev.notice_kind == "message_recall")]},
    {"item": "temp(临时会话)", "baseline": "test_temp_scene.py", "checks": [
        ("onebot11", _ob_message([{"type": "text", "data": {"text": "hi"}}], message_type="private",
                                 sub_type="group"), OB,
         lambda ev: ev.scope == "private" and ev.scene == "temp" and ev.context_group_id == GROUP),
        ("milky", _mk_msg([{"type": "text", "data": {"text": "hi"}}], message_scene="temp",
                          group={"group_id": GROUP}), MK,
         lambda ev: ev.scope == "private" and ev.scene == "temp" and ev.context_group_id == GROUP)]},
    {"item": "record", "baseline": "test_media_segments.py", "checks": [
        ("onebot11", _ob_message([{"type": "record", "data": {"file": "r.silk", "url": IMG}}]), OB,
         lambda ev: len(ev.records) == 1),
        ("milky", _mk_msg([{"type": "record", "data": {"resource_id": "r1", "temp_url": IMG}}]), MK,
         lambda ev: len(ev.records) == 1)]},
    {"item": "video", "baseline": "test_media_segments.py", "checks": [
        ("onebot11", _ob_message([{"type": "video", "data": {"file": "v.mp4", "url": IMG}}]), OB,
         lambda ev: len(ev.videos) == 1),
        ("milky", _mk_msg([{"type": "video", "data": {"resource_id": "r1", "temp_url": IMG}}]), MK,
         lambda ev: len(ev.videos) == 1)]},
    {"item": "xml", "baseline": "test_media_segments.py", "checks": [
        ("onebot11", _ob_message([{"type": "xml", "data": {"data": "<msg serviceID=\"1\"/>"}}]), OB,
         lambda ev: len(ev.xmls) == 1 and ev.xmls[0]["raw_xml"]),
        ("milky", _mk_msg([{"type": "xml", "data": {"service_id": 1, "xml_payload": "<msg/>"}}]), MK,
         lambda ev: len(ev.xmls) == 1)]},
]


@pytest.mark.parametrize("case", MATRIX, ids=[c["item"] for c in MATRIX])
def test_existing_capability_still_normalizes(case):
    for protocol, raw, parse, check in case["checks"]:
        event = parse(raw)
        assert check(event), "能力回归失败：%s（%s）" % (case["item"], protocol)
        assert event.raw_data == raw, "raw_data 保真失败：%s（%s）" % (case["item"], protocol)


def test_matrix_has_at_least_fifteen_items_with_baseline_evidence():
    assert len(MATRIX) >= 15, "任务书要求至少 15 项：当前 %d" % len(MATRIX)
    for case in MATRIX:
        assert case["baseline"].strip(), "每项都要标注重构前覆盖它的既有测试：%s" % case["item"]
        assert case["checks"], "每项至少一个协议原生样本：%s" % case["item"]


def test_task_book_named_items_are_all_present():
    required = {"text", "at", "reply", "image", "face", "market_face", "file", "group_upload",
                "forward", "json_ark", "poke", "markdown", "light_app", "recall"}
    present = {c["item"] for c in MATRIX}
    missing = sorted(required - present)
    assert missing == [], "任务书 §22 列出的能力缺项：%s" % missing
