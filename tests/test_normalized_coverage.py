"""Gate I：Normalized Message 覆盖率（Typed Coverage ≥ 80%）。

台账：`tests/fixtures/segment_inventory.json` —— 两个**生产协议**的段类型全集
（OneBot 11 家族 24 个 + Milky 14 个），每个条目带来源证据。

覆盖率 = 已有 typed model 的段 / 已知段。本文件用四类断言防止"表格达标、代码没实现"：

1. **覆盖率 ≥ 80%**：数字直接从台账算，打印出来（不手填）；
2. **台账不缩水**：必须逐条覆盖两个协议枚举里的每一个类型 ——
   任务书明令"不能通过删除不支持的 segment 来提高覆盖率"；
3. **typed 声明必须真解析**：每个 typed 条目都用**最小样本喂真解析器**，
   断言它落到承诺的归一化载体（不是"台账写了就算"）；
4. **未 typed 的必须被 UnknownSegment 安全承载**：不抛异常、原样进 `segments_summary`、
   `raw_data` 逐字段保真。
"""
import json
import os

import pytest

from src.adapters.milky_parser import MilkyEventParser
from src.adapters.onebot_parser import OneBotEventParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT_QQ = 10001

# 协议枚举的**完整**类型清单（[CODE] 来源见台账 _provenance）——
# 这里再写一份字面量，是为了让"删条目提高覆盖率"必须同时改两处并被 review 看见。
ONEBOT_TYPES = (
    "text", "image", "music", "video", "record", "file", "at", "reply", "json", "face", "mface",
    "markdown", "node", "forward", "xml", "poke", "dice", "rps", "miniapp", "contact", "location",
    "onlinefile", "flashtransfer",   # NapCat OB11MessageDataType（23）
    "shake",                          # LLBot 等价上报（face(faceType=Poke)）
)
MILKY_TYPES = (
    "text", "mention", "mention_all", "image", "face", "market_face", "file", "forward",
    "record", "video", "xml", "light_app", "reply",   # LagrangeV2 Entity/Segment/（13 incoming）
    "markdown",                                        # [DOC] 规范 since 1.3
)
PARSER_SOURCE = {
    "onebot11": os.path.join(ROOT, "src/adapters/onebot_parser.py"),
    "milky": os.path.join(ROOT, "src/adapters/milky_parser.py"),
}


def _inventory():
    with open(os.path.join(ROOT, "tests/fixtures/segment_inventory.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _parse_onebot(segment):
    raw = {"post_type": "message", "message_type": "group", "group_id": 123456, "user_id": 456789,
           "message_id": 1001, "time": 1700000000, "message": [segment]}
    return OneBotEventParser(bot_qq=BOT_QQ).parse(raw), raw


def _parse_milky(segment):
    raw = {"time": 1700000000, "self_id": BOT_QQ, "event_type": "message_receive",
           "data": {"message_scene": "group", "peer_id": 123456, "sender_id": 456789,
                    "message_seq": 1001, "segments": [segment]}}
    return MilkyEventParser(bot_qq=BOT_QQ).parse(raw), raw


def _parse(protocol, segment):
    return _parse_onebot(segment) if protocol == "onebot11" else _parse_milky(segment)


# 每个 typed 条目一条最小样本 + 它承诺的归一化结果（Gate I 的核心证据）
TYPED_SAMPLES = {
    ("onebot11", "text"): ({"type": "text", "data": {"text": "hi"}},
                           lambda ev: ev.text == "hi"),
    ("onebot11", "image"): ({"type": "image", "data": {"file": "a.jpg", "url": "https://x/a.jpg"}},
                            lambda ev: ev.images == ["https://x/a.jpg"] and ev.image_files == ["a.jpg"]),
    ("onebot11", "video"): ({"type": "video", "data": {"file": "v.mp4", "url": "https://x/v.mp4"}},
                            lambda ev: len(ev.videos) == 1),
    ("onebot11", "record"): ({"type": "record", "data": {"file": "r.silk", "url": "https://x/r.silk"}},
                             lambda ev: len(ev.records) == 1),
    ("onebot11", "file"): ({"type": "file", "data": {"file_id": "f1", "file": "a.zip", "file_size": 10}},
                           lambda ev: ev.files and ev.files[0]["file_id"] == "f1"),
    ("onebot11", "at"): ({"type": "at", "data": {"qq": str(BOT_QQ)}},
                         lambda ev: ev.is_mentioned is True and str(BOT_QQ) in ev.mentions),
    ("onebot11", "reply"): ({"type": "reply", "data": {"id": "1001"}},
                            # 归一化后 reply_id / reply_ref["id"] 是 int（解析器统一 to_int/int()）
                            lambda ev: ev.reply_id == 1001 and ev.reply_ref.get("id") == 1001),
    ("onebot11", "json"): ({"type": "json", "data": {"data": '{"app":"com.tencent.miniapp"}'}},
                           lambda ev: ev.json_cards and ev.json_cards[0]["app"] == "com.tencent.miniapp"),
    ("onebot11", "face"): ({"type": "face", "data": {"id": "14"}},
                           lambda ev: ev.faces and ev.faces[0]["face_id"] == "14"),
    ("onebot11", "mface"): ({"type": "mface", "data": {"emoji_id": "e1", "summary": "[猫]"}},
                            lambda ev: ev.faces and ev.faces[0]["kind"] == "market_face"),
    ("onebot11", "markdown"): ({"type": "markdown", "data": {"content": "# 标题"}},
                               lambda ev: "# 标题" in ev.text),
    ("onebot11", "node"): ({"type": "node", "data": {"id": "n1", "nickname": "某人",
                                                     "content": [{"type": "text", "data": {"text": "hi"}}]}},
                           lambda ev: ev.forwards and ev.forwards[0]["inline"] is True),
    ("onebot11", "forward"): ({"type": "forward", "data": {"id": "fwd1"}},
                              lambda ev: ev.forwards and ev.forwards[0]["id"] == "fwd1"),
    ("onebot11", "xml"): ({"type": "xml", "data": {"data": "<msg serviceID=\"1\"/>"}},
                          lambda ev: len(ev.xmls) == 1),
    ("onebot11", "poke"): ({"type": "poke", "data": {"type": "1", "id": "2"}},
                           lambda ev: ev.pokes and ev.pokes[0]["poke_id"] == "2"),
    ("onebot11", "miniapp"): ({"type": "miniapp", "data": {"data": '{"app":"com.tencent.miniapp"}'}},
                              lambda ev: ev.json_cards and ev.json_cards[0]["app"] == "com.tencent.miniapp"),
    ("onebot11", "onlinefile"): ({"type": "onlinefile",
                                  "data": {"msgId": "m1", "fileName": "a.zip", "fileSize": 10}},
                                 lambda ev: ev.files and ev.files[0].get("sub_type") == "onlinefile"),
    ("onebot11", "flashtransfer"): ({"type": "flashtransfer",
                                     "data": {"fileSetId": "fs1", "fileName": "b.zip"}},
                                    lambda ev: ev.files and ev.files[0].get("sub_type") == "flash_transfer"),
    ("onebot11", "shake"): ({"type": "shake", "data": {}},
                            lambda ev: ev.pokes and ev.pokes[0]["poke_type"] == "shake"),
    ("milky", "text"): ({"type": "text", "data": {"text": "hi"}},
                        lambda ev: ev.text == "hi"),
    ("milky", "mention"): ({"type": "mention", "data": {"user_id": BOT_QQ, "name": "花璃"}},
                           lambda ev: ev.is_mentioned is True and str(BOT_QQ) in ev.mentions),
    ("milky", "mention_all"): ({"type": "mention_all", "data": {}},
                               lambda ev: "all" in ev.mentions),
    ("milky", "image"): ({"type": "image", "data": {"temp_url": "https://x/a.png", "resource_id": "r1"}},
                         lambda ev: ev.images == ["https://x/a.png"]),
    ("milky", "face"): ({"type": "face", "data": {"face_id": 14}},
                        lambda ev: ev.faces and ev.faces[0]["face_id"] == "14"),
    ("milky", "market_face"): ({"type": "market_face", "data": {"url": "https://x/m.png"}},
                               lambda ev: ev.faces and ev.faces[0]["kind"] == "market_face"),
    ("milky", "file"): ({"type": "file", "data": {"file_id": "f1", "file_name": "a.zip", "file_size": 9}},
                        lambda ev: ev.files and ev.files[0]["name"] == "a.zip"),
    ("milky", "forward"): ({"type": "forward", "data": {"forward_id": "fwd1", "title": "聊天记录"}},
                           lambda ev: ev.forwards and ev.forwards[0]["id"] == "fwd1"),
    ("milky", "record"): ({"type": "record", "data": {"resource_id": "r1", "temp_url": "https://x/r.silk"}},
                          lambda ev: len(ev.records) == 1),
    ("milky", "video"): ({"type": "video", "data": {"resource_id": "r1", "temp_url": "https://x/v.mp4"}},
                         lambda ev: len(ev.videos) == 1),
    ("milky", "xml"): ({"type": "xml", "data": {"service_id": 1, "xml_payload": "<msg/>"}},
                       lambda ev: len(ev.xmls) == 1),
    ("milky", "light_app"): ({"type": "light_app",
                              "data": {"app_name": "com.tencent.miniapp", "json_payload": '{"app":"x"}'}},
                             lambda ev: ev.json_cards and ev.json_cards[0]["app"]),
    ("milky", "reply"): ({"type": "reply", "data": {"message_seq": 998}},
                         lambda ev: ev.reply_ref.get("id") == "998" or ev.reply_id == 998),
    ("milky", "markdown"): ({"type": "markdown", "data": {"content": "**粗体**"}},
                            lambda ev: "**粗体**" in ev.text),
}

UNTYPED_SAMPLES = {
    "music": {"type": "music", "data": {"type": "qq", "id": "1"}},
    "dice": {"type": "dice", "data": {"result": "6"}},
    "rps": {"type": "rps", "data": {"result": "2"}},
    "contact": {"type": "contact", "data": {"type": "qq", "id": "10001"}},
    "location": {"type": "location", "data": {"lat": "1.0", "lon": "2.0", "title": "某地"}},
}


# ---------------------------------------------------------------- 覆盖率本身

def test_typed_coverage_is_at_least_80_percent():
    entries = _inventory()["segments"]
    typed = [e for e in entries if e["typed"]]
    coverage = len(typed) / len(entries)
    print("Gate I：typed %d / known %d = %.1f%%" % (len(typed), len(entries), coverage * 100))
    assert coverage >= 0.80, "Typed Coverage 不足：%.1f%%（阈值 80%%）" % (coverage * 100)


def test_inventory_covers_every_known_type_without_deletion():
    entries = _inventory()["segments"]
    got = {(e["protocol"], e["wire_type"]) for e in entries}
    expected = {("onebot11", t) for t in ONEBOT_TYPES} | {("milky", t) for t in MILKY_TYPES}
    missing = sorted(expected - got)
    extra = sorted(got - expected)
    assert missing == [], "台账漏了已知段类型（不能靠删条目提高覆盖率）：%s" % missing
    assert extra == [], "台账出现未登记来源的类型：%s" % extra
    assert len(entries) >= 38, "台账规模缩水：%d" % len(entries)


def test_every_entry_cites_evidence():
    bad = [e for e in _inventory()["segments"]
           if not str(e.get("evidence", "")).startswith(("[CODE]", "[DOC]"))]
    assert bad == [], "条目必须标来源证据（[CODE]/[DOC]）：%s" % bad


def test_typed_entries_are_backed_by_parser_source():
    """台账里声称 typed 的类型，解析器源码里必须真的出现该线格式类型名。"""
    cache = {}
    for entry in _inventory()["segments"]:
        if not entry["typed"]:
            continue
        path = PARSER_SOURCE[entry["protocol"]]
        if path not in cache:
            with open(path, encoding="utf-8") as fh:
                cache[path] = fh.read()
        assert entry["wire_type"] in cache[path], "解析器里找不到段类型 %s（%s）" % (
            entry["wire_type"], entry["protocol"])


# ---------------------------------------------------------------- typed 声明逐条实测

@pytest.mark.parametrize("key", sorted(TYPED_SAMPLES))
def test_typed_claim_is_actually_normalized(key):
    protocol, wire_type = key
    segment, check = TYPED_SAMPLES[key]
    event, raw = _parse(protocol, segment)
    assert check(event), "归一化结果与台账不符：%s.%s" % (protocol, wire_type)
    assert event.raw_data == raw, "raw_data 必须保真：%s.%s" % (protocol, wire_type)


def test_every_typed_entry_has_a_sample():
    typed = {(e["protocol"], e["wire_type"]) for e in _inventory()["segments"] if e["typed"]}
    assert typed == set(TYPED_SAMPLES), "typed 条目与实测样本不一致：缺 %s / 多 %s" % (
        sorted(typed - set(TYPED_SAMPLES)), sorted(set(TYPED_SAMPLES) - typed))


# ---------------------------------------------------------------- 未 typed 的安全承载

@pytest.mark.parametrize("wire_type", sorted(UNTYPED_SAMPLES))
def test_untyped_entries_are_safely_carried_by_unknown_segment(wire_type):
    """未 typed 的类型：不抛异常、原样进 segments_summary、raw_data 保真（UnknownSegment 承载）。"""
    segment = UNTYPED_SAMPLES[wire_type]
    event, raw = _parse_onebot(segment)
    assert (wire_type, segment["data"]) in event.segments_summary, \
        "未知段必须原样进入 segments_summary：%s" % wire_type
    assert event.raw_data == raw
    # 不能因为不认识的段就丢掉同一消息里的已知内容
    known = {"post_type": "message", "message_type": "group", "group_id": 1, "user_id": 2,
             "message_id": 3, "time": 1,
             "message": [segment, {"type": "text", "data": {"text": "仍然可见"}}]}
    event2 = OneBotEventParser(bot_qq=BOT_QQ).parse(known)
    assert "仍然可见" in event2.text
    assert (wire_type, segment["data"]) in event2.segments_summary


def test_untyped_entries_are_declared_as_not_typed_in_inventory():
    untyped = {e["wire_type"] for e in _inventory()["segments"]
               if e["protocol"] == "onebot11" and not e["typed"]}
    assert untyped == set(UNTYPED_SAMPLES), "未 typed 清单与样本不一致：%s" % sorted(untyped)
