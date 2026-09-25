"""G3：Milky `record` / `video` / `xml` 类型化 Segment 回归。

证据：
- [DOC] Milky 规范 `common.ts` L342-346（record{resource_id,temp_url,duration}）、
  L347-353（video{...+width,height}）、L377-380（xml{service_id,xml_payload}）。
- [CODE] NapCat `napcat-onebot/types/message.ts` L80-86（FileBaseDataSchema{file,path?,url?,name?,thumb?}）、
  L106-109（record 段 data=FileBaseData）、L112-115（video 同上）、L228-233（xml{data}）。
  注意 NapCat 枚举里 `voice = 'record'`（L8）——**线上值是 record**。
- 任务书 §5.3：XML **不得**直接塞进 text，也不得擅自解析成业务模型；§5.4：未知字段不得导致解析失败。

修复前：三种段只进 `segments_summary`，信息没进正式 Message Model（Task Book G3 的原话）。
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


def _onebot(segments):
    return OneBotEventParser(bot_qq=BOT_QQ).parse(
        {"post_type": "message", "message_type": "group", "group_id": 123456,
         "user_id": 456789, "message_id": 1, "time": 1, "message": segments})


# ---------- Milky ----------

def test_milky_record_segment():
    ev = _milky([{"type": "record", "data": {"resource_id": "r1", "temp_url": "https://x/a.amr",
                                             "duration": 3}}])
    assert ev.records and ev.records[0]["resource_id"] == "r1"
    assert ev.records[0]["url"] == "https://x/a.amr" and ev.records[0]["duration"] == 3
    assert ev.text == ""                                  # 不污染文本
    assert ("record", {"resource_id": "r1", "temp_url": "https://x/a.amr", "duration": 3}) \
        in ev.segments_summary                            # 旧通道仍在（不删信息）


def test_milky_video_segment_keeps_size():
    ev = _milky([{"type": "video", "data": {"resource_id": "v1", "temp_url": "https://x/v.mp4",
                                            "width": 640, "height": 480, "duration": 12}}])
    v = ev.videos[0]
    assert (v["resource_id"], v["url"], v["width"], v["height"], v["duration"]) == \
           ("v1", "https://x/v.mp4", 640, 480, 12)


def test_milky_xml_is_preserved_not_parsed():
    payload = '<msg serviceID="60"><item/></msg>'
    ev = _milky([{"type": "xml", "data": {"service_id": 60, "xml_payload": payload}}])
    assert ev.xmls[0]["service_id"] == "60"
    assert ev.xmls[0]["raw_xml"] == payload               # 保真
    assert payload not in ev.text and ev.text == ""       # 不塞进 text（§5.3）


def test_unknown_fields_are_kept_in_extra():
    ev = _milky([{"type": "record", "data": {"resource_id": "r2", "temp_url": "u",
                                             "future_field": {"a": 1}}}])
    assert ev.records[0]["extra"] == {"future_field": {"a": 1}}    # §5.4 前向兼容


# ---------- OneBot / NapCat ----------

def test_napcat_record_uses_filebase():
    ev = _onebot([{"type": "record", "data": {"file": "file:///d/v.amr", "path": "/d/v.amr",
                                              "name": "v.amr"}}])
    r = ev.records[0]
    assert r["file"] == "file:///d/v.amr" and r["path"] == "/d/v.amr" and r["name"] == "v.amr"
    assert r["resource_id"] == "" and r["duration"] is None


def test_napcat_video_and_xml():
    ev = _onebot([{"type": "video", "data": {"file": "https://x/v.mp4", "url": "https://x/v.mp4"}},
                  {"type": "xml", "data": {"data": "<msg/>"}}])
    assert ev.videos[0]["url"] == "https://x/v.mp4"
    assert ev.xmls[0]["raw_xml"] == "<msg/>" and ev.xmls[0]["service_id"] == ""


def test_record_equivalent_semantics_across_protocols():
    milky = _milky([{"type": "record", "data": {"resource_id": "r", "temp_url": "https://m/a",
                                                "duration": 5}}]).records[0]
    napcat = _onebot([{"type": "record", "data": {"file": "https://n/a", "url": "https://n/a"}}]).records[0]
    assert milky["url"] and napcat["url"]                  # 两侧都给出可取的 URL
    assert milky["duration"] == 5 and napcat["duration"] is None   # 缺失就是 None，不编造


# ---------- Assembler 渲染 ----------

def test_assembler_renders_media_hint():
    from src.core.message_assembler import MessageAssembler

    class _FP:
        pass

    class _Cfg:
        VISION_ENABLED = False

    ev = _milky([{"type": "record", "data": {"resource_id": "r", "temp_url": "u", "duration": 3}},
                 {"type": "video", "data": {"resource_id": "v", "temp_url": "u2", "width": 64,
                                            "height": 48, "duration": 9}},
                 {"type": "xml", "data": {"service_id": 1, "xml_payload": "<a/>"}}])
    asm = MessageAssembler(_Cfg(), None, _FP(), None)
    out = asm._assemble_media(ev)
    assert "语音" in out and "3 秒" in out
    assert "视频" in out and "64x48" in out
    assert "XML" in out and "未解析" in out
    assert asm._assemble_media(_milky([])) == ""


# ---------- 夹具 ----------

def test_media_fixtures_parse_with_provenance():
    import json
    seen = 0
    for rel in ("milky/segment_record.json", "milky/segment_video.json",
                "milky/segment_xml.json", "napcat/message_media_segments.json"):
        path = os.path.join(FIXTURES, rel)
        if not os.path.exists(path):
            continue
        raw = json.load(open(path, encoding="utf-8"))
        assert raw["_provenance"]["evidence"], rel
        ev = (_milky(raw["data"]["segments"]) if rel.startswith("milky") else _onebot(raw["message"]))
        assert ev.records or ev.videos or ev.xmls, rel
        seen += 1
    assert seen >= 4


def test_napcat_media_fixture_has_all_three():
    import json
    path = os.path.join(FIXTURES, "napcat", "message_media_segments.json")
    if not os.path.exists(path):
        return
    raw = json.load(open(path, encoding="utf-8"))
    ev = _onebot(raw["message"])
    assert len(ev.records) == 1 and len(ev.videos) == 1 and len(ev.xmls) == 1
