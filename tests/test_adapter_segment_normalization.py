"""Adapter 段归一化测试（P4/P5）：夹具形态全部来自真实客户端源码证据。

证据来源（见 docs/message-model.md §3 与 docs/protocol-reverse-engineering.md）：
- NapCat：napcat-onebot/types/message.ts（段 schema）、SendMsg.ts L289-297（app 分流）
- LLBot：onebot11/transform/message/incoming.ts（file 段带 file_id/path；face→shake）
- Milky 作者实现：Lagrange.Milky/Entity/Segment/*.cs（15 个段，无 poke 段）
- SnowLuma：packages/onebot/src/event-converter/element-codecs.ts（flash_file/inline_keyboard）
- MVP：/storage/emulated/0/bot.py（json 卡片黑名单、文件 base64 信封）
"""
from src.adapters.onebot_parser import OneBotEventParser


def _msg(segments, **extra):
    raw = {"post_type": "message", "message_type": "group", "group_id": 123,
           "user_id": 456, "message_id": 789, "time": 1700000000, "message": segments}
    raw.update(extra)
    return raw


def _parse(segments, **extra):
    return OneBotEventParser(bot_qq=10001).parse(_msg(segments, **extra))


# ---------- JSON / Ark 卡片：app 必须保留 ----------
def test_napcat_multimsg_card_is_forward():
    """NapCat SendMsg.ts L289-297：app=com.tencent.multimsg 才是合并转发卡片。"""
    payload = ({"app": "com.tencent.multimsg",
                "meta": {"detail": {"resid": "abc", "uniseq": "u1", "source": "群聊的聊天记录"}}})
    ev = _parse([{"type": "json", "data": {"data": __import__("json").dumps(payload, ensure_ascii=False)}}])
    assert len(ev.json_cards) == 1
    card = ev.json_cards[0]
    assert card["app"] == "com.tencent.multimsg"
    assert card["is_forward_card"] is True


def test_other_app_card_is_not_forward():
    """其它 app（小程序等）不是合并转发 —— NapCat 与 LLBot 独立互证。"""
    payload = {"app": "com.tencent.miniapp_01", "meta": {"detail_1": {"title": "小程序"}}}
    ev = _parse([{"type": "json", "data": {"data": payload}}])   # dict 形态也要吃
    assert ev.json_cards[0]["app"] == "com.tencent.miniapp_01"
    assert ev.json_cards[0]["is_forward_card"] is False


def test_json_payload_kept_verbatim_when_not_json():
    """非 JSON 的 json 段不得丢内容（任务书 §十八.9）。"""
    ev = _parse([{"type": "json", "data": {"data": "not-a-json"}}])
    assert ev.json_cards[0]["app"] == ""
    assert ev.json_cards[0]["payload"] == "not-a-json"


def test_json_app_extracted_from_raw_string():
    """LLBot 用正则从原始串里抠 app，这里同样支持（不做完整解析也能拿到 app）。"""
    ev = _parse([{"type": "json", "data": {"data": '{"app":"com.tencent.multimsg","x":1}'}}])
    assert ev.json_cards[0]["app"] == "com.tencent.multimsg"


# ---------- 表情 ----------
def test_napcat_face_fields():
    """NapCat face schema：{id, resultId?, chainCount?}。"""
    ev = _parse([{"type": "face", "data": {"id": "14", "resultId": "3", "chainCount": 2}}])
    assert ev.faces[0]["kind"] == "face"
    assert ev.faces[0]["face_id"] == "14"
    assert ev.faces[0]["chain_count"] == 2


def test_market_face_from_napcat_and_llbot_shapes():
    """商城表情：NapCat 无 url、LLBot 有 url —— 归一化后字段名统一。"""
    napcat = {"emoji_package_id": 5, "emoji_id": "abc", "key": "k", "summary": "[表情]"}
    llbot = dict(napcat, url = "https://gxh.vip.qq.com/x.gif")
    for data in (napcat, llbot):
        ev = _parse([{"type": "mface", "data": data}])
        f = ev.faces[0]
        assert f["kind"] == "market_face"
        assert f["emoji_id"] == "abc" and f["package_id"] == "5"
        assert f["summary"] == "[表情]"
    ev2 = _parse([{"type": "mface", "data": llbot}])
    assert ev2.faces[0]["url"].endswith(".gif")


# ---------- 戳一戳（三种形态）----------
def test_poke_segment():
    """OneBot 规范段（NoneBot adapter 有工厂）+ NapCat/SnowLuma 都支持。"""
    ev = _parse([{"type": "poke", "data": {"type": "1", "id": "-1"}}])
    assert ev.pokes[0]["poke_type"] == "1"
    assert ev.pokes[0]["poke_id"] == "-1"
    assert ev.pokes[0]["target"] is None      # 段里本来就没有目标，不许猜


def test_shake_segment_from_llbot_has_no_target():
    """LLBot 把 face(faceType=Poke) 报成 shake{}，不带任何目标信息。"""
    ev = _parse([{"type": "shake", "data": {}}])
    assert ev.pokes[0]["poke_type"] == "shake"
    assert ev.pokes[0]["target"] is None


# ---------- 文件段 ----------
def test_file_segment_llbot_shape():
    """LLBot：file{file,url(file://),file_id,path,file_size}。"""
    ev = _parse([{"type": "file", "data": {"file": "a.txt", "url": "file:///tmp/a.txt",
                                          "file_id": "fid-1", "path": "/tmp/a.txt",
                                          "file_size": "12"}}])
    f = ev.files[0]
    assert f["file_id"] == "fid-1" and f["name"] == "a.txt"
    assert f["path"] == "/tmp/a.txt" and f["size"] == "12"


def test_file_segment_napcat_filebase_shape():
    """NapCat FileBase 没有 file_id —— 归一化后是空串而不是 None（显式缺失）。"""
    ev = _parse([{"type": "file", "data": {"file": "/path/b.pdf", "url": "http://x/b.pdf"}}])
    f = ev.files[0]
    assert f["file_id"] == "" and f["name"] == "/path/b.pdf"
    assert f["url"] == "http://x/b.pdf"


# ---------- 合并转发 ----------
def test_forward_segment_inline_and_id_only():
    inline = _parse([{"type": "forward", "data": {"messages": [{"sender": {"user_id": 1}}]}}])
    assert inline.forwards[0]["inline"] is True
    idonly = _parse([{"type": "forward", "data": {"id": "resid-9"}}])
    assert idonly.forwards[0]["id"] == "resid-9" and idonly.forwards[0]["inline"] is False


# ---------- 回归：原有语义不变 ----------
def test_regression_text_at_reply_image():
    ev = _parse([
        {"type": "text", "data": {"text": "你好 "}},
        {"type": "at", "data": {"qq": "10001"}},
        {"type": "image", "data": {"file": "file:///tmp/i.png", "url": "http://x/i.png"}},
        {"type": "reply", "data": {"id": "777", "qq": "10001"}},
    ])
    assert ev.text == "你好"
    assert ev.mentions == ["10001"] and ev.is_mentioned is True
    assert ev.images == ["http://x/i.png"] and ev.image_files == ["/tmp/i.png"]
    assert ev.reply_id == 777 and ev.is_reply_to_bot is True


def test_unknown_segment_still_summarized():
    """未建模的段不丢：进 summary（未来建 model 时不会漏消息）。"""
    ev = _parse([{"type": "flash_transfer", "data": {"fileSetId": "fs-1"}}])
    assert ("flash_transfer", {"fileSetId": "fs-1"}) in ev.segments_summary
    assert ev.faces == [] and ev.files == [] and ev.json_cards == []


def test_onlinefile_and_inline_keyboard_do_not_crash():
    """NapCat onlinefile / SnowLuma inline_keyboard：至少不崩、进 summary。"""
    ev = _parse([
        {"type": "onlinefile", "data": {"msgId": "1", "elementId": "2", "fileName": "a", "fileSize": "3", "isDir": False}},
        {"type": "inline_keyboard", "data": {"rows": []}},
    ])
    kinds = [k for k, _ in ev.segments_summary]
    assert "onlinefile" in kinds and "inline_keyboard" in kinds
