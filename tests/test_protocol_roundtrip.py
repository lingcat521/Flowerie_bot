"""协议 round-trip / 跨客户端等价 / reverse 回归（任务书 §22 交付物⑤）。

三类断言，全部不依赖 aiohttp（可在无第三方依赖环境跑）：

A. **重解析稳定性（round-trip）**：fixture → parse → 用归一化结果重建协议原始负载 → 再 parse，
   两次归一化结果必须一致（归一化层不得有"一次性的信息损失"）。
B. **跨客户端等价（normalization）**：同一逻辑消息在不同客户端形态下 → 归一化核心字段必须相同
   —— 这是"归一化层独立于具体客户端"的直接证据。
C. **下游兼容层（reverse）**：InternalEvent → 旧 GroupMessage 字段零丢失；旧 dict 入口与
   parser 结果一致（旧调用方语义不变）。
D. **发送方向（reverse）静态核对**：Milky 发送必须转成段数组，且 action 名走统一映射表。
"""
import ast
import io
import json
import os

import pytest

from src.adapters.compat import build_group_message, convert_legacy
from src.adapters.milky_parser import MilkyEventParser
from src.adapters.onebot_parser import OneBotEventParser

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
BOT_QQ = 10001
SENDER = "src/services/sender.py"

# 归一化核心字段（跨客户端比较用；不含客户端专属附加信息）
CORE_FIELDS = ("kind", "scope", "group_id", "actor_id", "message_id", "text", "mentions",
               "images", "image_files", "reply_id", "is_mentioned", "has_at_others",
               "is_reply_to_bot", "has_reply_to_other")


def _core(ev) -> dict:
    out = {}
    for f in CORE_FIELDS:
        v = getattr(ev, f)
        out[f] = sorted(v) if isinstance(v, list) else v
    return out


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _fixture_paths():
    return sorted(
        os.path.join(FIXTURES, d, n)
        for d in os.listdir(FIXTURES) if os.path.isdir(os.path.join(FIXTURES, d))
        for n in os.listdir(os.path.join(FIXTURES, d)) if n.endswith(".json"))


def _parse(path: str):
    raw = _load(path)
    client = os.path.basename(os.path.dirname(path))
    if client == "milky":
        return MilkyEventParser(bot_qq=BOT_QQ).parse(raw), raw
    if client == "onebot12":
        from src.adapters.onebot12_parser import OneBot12EventParser
        return OneBot12EventParser(bot_qq=BOT_QQ).parse(raw), raw
    return OneBotEventParser(bot_qq=BOT_QQ).parse(raw), raw


# ---------- A. round-trip：归一化结果 → 重建原始负载 → 再解析 ----------

def _rebuild_onebot(ev) -> dict:
    return {"post_type": "message",
            "message_type": "group" if ev.scope == "group" else "private",
            "group_id": ev.group_id, "user_id": ev.actor_id, "self_id": BOT_QQ,
            "message_id": ev.message_id, "time": ev.timestamp,
            "message": ev.message_segments}


def _rebuild_milky(ev) -> dict:
    return {"time": ev.timestamp, "self_id": BOT_QQ, "event_type": "message_receive",
            "data": {"message_scene": "group" if ev.scope == "group" else "friend",
                     "peer_id": ev.group_id if ev.scope == "group" else ev.actor_id,
                     "sender_id": ev.actor_id, "message_seq": ev.message_id,
                     "segments": ev.message_segments}}


def _rebuild_onebot_notice(ev) -> dict:
    """通知类：只用归一化字段重建 OneBot 通知负载（不看原 raw）。"""
    if ev.notice_kind == "group_upload":
        return {"post_type": "notice", "notice_type": "group_upload",
                "group_id": ev.group_id, "user_id": ev.actor_id, "self_id": BOT_QQ,
                "time": ev.timestamp, "file": dict(ev.notice_file)}
    return {"post_type": "notice", "notice_type": "notify", "sub_type": ev.notice_kind,
            "group_id": ev.group_id, "user_id": ev.actor_id, "target_id": ev.target_id,
            "self_id": BOT_QQ, "time": ev.timestamp}


def _rebuild_milky_notice(ev) -> dict:
    if ev.notice_kind == "group_upload":
        return {"time": ev.timestamp, "self_id": BOT_QQ, "event_type": "group_file_upload",
                "data": {"group_id": ev.group_id, "user_id": ev.actor_id,
                         "file_id": ev.notice_file.get("id", ""),
                         "file_name": ev.notice_file.get("name", ""),
                         "file_size": ev.notice_file.get("size")}}
    return {"time": ev.timestamp, "self_id": BOT_QQ, "event_type": "group_nudge",
            "data": {"group_id": ev.group_id, "sender_id": ev.actor_id,
                     "receiver_id": ev.target_id, "display_action": "", "display_suffix": "",
                     "display_action_img_url": ""}}


def _rebuild_onebot12(ev) -> dict:
    """G8：只用归一化字段重建 OneBot 12 消息事件负载（规范 event.md 字段）。"""
    return {"id": ev.event_id or "rebuild", "time": float(ev.timestamp or 0),
            "type": "message",
            "detail_type": "group" if ev.scope == "group" else "private",
            "sub_type": "group" if ev.scene == "temp" else "",
            "self": {"platform": "qq", "user_id": str(BOT_QQ)},
            "message_id": str(ev.message_id or ""),
            "group_id": str(ev.group_id or ""), "user_id": str(ev.actor_id or ""),
            "message": ev.message_segments}


def _rebuild_onebot_request(ev) -> dict:
    """请求类：只用归一化字段重建 OneBot 请求负载。"""
    raw = {"post_type": "request", "request_type": ev.request_kind, "user_id": ev.actor_id,
           "comment": ev.comment, "flag": ev.request_id, "time": ev.timestamp, "self_id": BOT_QQ}
    if ev.request_kind == "group":
        raw["sub_type"] = "invite" if ev.request_scene == "group_invitation" else "add"
        raw["group_id"] = ev.group_id
    return raw


def _rebuild_milky_request(ev) -> dict:
    """请求类：只用归一化字段重建 Milky 请求负载（scene → event_type）。"""
    event_type = _MILKY_EVENT_OF.get(ev.request_scene, "")
    data = {}
    if ev.request_scene == "friend":
        data = {"initiator_id": ev.actor_id, "initiator_uid": ev.request_uid,
                "comment": ev.comment}
    elif ev.request_scene == "group_join":
        data = {"group_id": ev.group_id, "notification_seq": int(ev.request_id or 0),
                "is_filtered": ev.request_filtered, "initiator_id": ev.actor_id,
                "comment": ev.comment}
    elif ev.request_scene == "group_invited_join":
        data = {"group_id": ev.group_id, "notification_seq": int(ev.request_id or 0),
                "initiator_id": ev.actor_id, "target_user_id": ev.target_id}
    elif ev.request_scene == "group_invitation":
        data = {"group_id": ev.group_id, "invitation_seq": int(ev.request_id or 0),
                "initiator_id": ev.actor_id}
    return {"time": ev.timestamp, "self_id": BOT_QQ, "event_type": event_type, "data": data}


_MILKY_EVENT_OF = {"friend": "friend_request", "group_join": "group_join_request",
                   "group_invited_join": "group_invited_join_request",
                   "group_invitation": "group_invitation"}


@pytest.mark.parametrize("path", _fixture_paths(), ids=[os.path.basename(p) for p in _fixture_paths()])
def test_roundtrip_reparse_is_stable(path):
    client = os.path.basename(os.path.dirname(path))
    ev1, _raw = _parse(path)
    milky = client == "milky"
    if client == "onebot12" and ev1.kind == "message":
        rebuilt = _rebuild_onebot12(ev1)          # G8：v12 语料单独走 v12 重建
    elif ev1.kind == "message":
        rebuilt = _rebuild_milky(ev1) if milky else _rebuild_onebot(ev1)
    elif ev1.kind == "notice":
        rebuilt = _rebuild_milky_notice(ev1) if milky else _rebuild_onebot_notice(ev1)
    elif ev1.kind == "request":
        rebuilt = _rebuild_milky_request(ev1) if milky else _rebuild_onebot_request(ev1)
    else:
        pytest.skip("round-trip 只覆盖 message / notice / request：%s" % ev1.kind)
    if client == "onebot12":
        from src.adapters.onebot12_parser import OneBot12EventParser
        parser = OneBot12EventParser(bot_qq=BOT_QQ)
    else:
        parser = (MilkyEventParser(bot_qq=BOT_QQ) if milky
                  else OneBotEventParser(bot_qq=BOT_QQ))
    ev2 = parser.parse(rebuilt)
    assert _core(ev1) == _core(ev2), "%s：重解析后归一化结果不一致" % path
    assert ev1.notice_kind == ev2.notice_kind
    assert ev1.notice_file == ev2.notice_file
    if ev1.kind == "message":
        # G4：内联引用（Milky 有 / OneBot 为空）也必须 round-trip 稳定
        assert ev1.reply_ref == ev2.reply_ref and ev1.reply_text == ev2.reply_text
        assert ev1.reply_segments == ev2.reply_segments
    if ev1.kind == "request":
        for field in ("request_kind", "request_scene", "request_id", "request_uid",
                      "request_filtered", "comment", "actor_id", "target_id", "group_id"):
            assert getattr(ev1, field) == getattr(ev2, field), (path, field)
    # 段级通道同样必须稳定（含 faces/pokes/files/json_cards/forwards/records/videos/xmls）
    for field in ("faces", "pokes", "files", "json_cards", "forwards",
                  "records", "videos", "xmls"):
        assert getattr(ev1, field) == getattr(ev2, field), field


def test_roundtrip_keeps_face_file_card_forward_for_milky():
    path = os.path.join(FIXTURES, "milky", "group_message_segments.json")
    if not os.path.exists(path):
        pytest.skip("语料缺失")
    ev1, _ = _parse(path)
    ev2 = MilkyEventParser(bot_qq=BOT_QQ).parse(_rebuild_milky(ev1))
    assert ev2.faces == ev1.faces and ev2.forwards == ev1.forwards and ev2.files == ev1.files
    assert ev2.json_cards[0]["is_forward_card"] is True


# ---------- B. 跨客户端等价：同一逻辑消息 → 同一归一化结果 ----------

def _onebot_msg(segments, **extra):
    raw = {"post_type": "message", "message_type": "group", "group_id": 123456,
           "user_id": 456789, "self_id": BOT_QQ, "message_id": 777,
           "time": 1756000000, "message": segments}
    raw.update(extra)
    return raw


def test_same_message_napcat_vs_llbot_normalizes_equally():
    # NapCat：at 带 name、image 带 file/url/file_size（types/message.ts）
    napcat = _onebot_msg([
        {"type": "at", "data": {"qq": "10001", "name": "花璃"}},
        {"type": "text", "data": {"text": " 你好"}},
        {"type": "image", "data": {"file": "a.jpg", "url": "http://h/a.jpg", "file_size": 10}}])
    # LLBot：at 只有 qq、image 带 file/subType/url/file_size（onebot11 incoming.ts）
    llbot = _onebot_msg([
        {"type": "at", "data": {"qq": "10001"}},
        {"type": "text", "data": {"text": " 你好"}},
        {"type": "image", "data": {"file": "a.jpg", "subType": 0, "url": "http://h/a.jpg",
                                   "file_size": 10}}])
    ev_n = OneBotEventParser(bot_qq=BOT_QQ).parse(napcat)
    ev_l = OneBotEventParser(bot_qq=BOT_QQ).parse(llbot)
    assert _core(ev_n) == _core(ev_l)
    assert ev_n.is_mentioned is True and ev_n.text == "你好"


def test_poke_semantics_equivalent_across_three_shapes():
    # 形态 1：NapCat 通知（notice/notify/poke + target_id）
    napcat = OneBotEventParser(bot_qq=BOT_QQ).parse({
        "post_type": "notice", "notice_type": "notify", "sub_type": "poke",
        "group_id": 123456, "user_id": 456789, "target_id": BOT_QQ, "time": 1756000000})
    # 形态 2：Milky 独立事件 group_nudge（receiver_id 才是被戳者）
    milky = MilkyEventParser(bot_qq=BOT_QQ).parse({
        "time": 1756000000, "self_id": BOT_QQ, "event_type": "group_nudge",
        "data": {"group_id": 123456, "sender_id": 456789, "receiver_id": BOT_QQ,
                 "display_action": "拍了拍", "display_suffix": "的肩",
                 "display_action_img_url": ""}})
    for ev in (napcat, milky):
        assert ev.kind == "notice" and ev.notice_kind == "poke"
        assert ev.actor_id == 456789 and ev.target_id == BOT_QQ and ev.group_id == 123456
    assert (napcat.kind, napcat.notice_kind, napcat.actor_id, napcat.target_id) == \
           (milky.kind, milky.notice_kind, milky.actor_id, milky.target_id)


def test_group_upload_equivalent_napcat_vs_milky():
    napcat = OneBotEventParser(bot_qq=BOT_QQ).parse({
        "post_type": "notice", "notice_type": "group_upload", "group_id": 123456,
        "user_id": 456789, "time": 1,
        "file": {"id": "f1", "name": "a.zip", "size": 2048, "busid": 102}})
    milky = MilkyEventParser(bot_qq=BOT_QQ).parse({
        "time": 1, "self_id": BOT_QQ, "event_type": "group_file_upload",
        "data": {"group_id": 123456, "user_id": 456789, "file_id": "f1",
                 "file_name": "a.zip", "file_size": 2048}})
    assert napcat.notice_kind == milky.notice_kind == "group_upload"
    assert napcat.notice_file["name"] == milky.notice_file["name"] == "a.zip"
    assert napcat.notice_file["size"] == milky.notice_file["size"] == 2048


def test_file_segment_shapes_agree_on_common_fields():
    # NapCat FileBase 没有 file_id；LLBot 有 file_id/path —— 共同字段必须一致可用
    napcat = OneBotEventParser(bot_qq=BOT_QQ).parse(_onebot_msg([
        {"type": "file", "data": {"file": "资料.zip", "file_size": 1024}}]))
    llbot = OneBotEventParser(bot_qq=BOT_QQ).parse(_onebot_msg([
        {"type": "file", "data": {"file_id": "fid-9", "file": "资料.zip", "file_size": 1024,
                                  "path": "/data/x.zip"}}]))
    assert napcat.files[0]["name"] == llbot.files[0]["name"] == "资料.zip"
    assert napcat.files[0]["size"] == llbot.files[0]["size"] == 1024
    assert napcat.files[0]["file_id"] == "" and llbot.files[0]["file_id"] == "fid-9"


# ---------- C. 下游兼容层（reverse：归一化结果 → 既有 GroupMessage） ----------

@pytest.mark.parametrize("path", _fixture_paths(), ids=[os.path.basename(p) for p in _fixture_paths()])
def test_internal_event_converts_to_legacy_group_message(path):
    ev, raw = _parse(path)
    gm = build_group_message(ev, clean_text=ev.text, full_text=ev.text)
    assert gm.group_id == ev.group_id and gm.user_id == ev.actor_id
    assert gm.message_id == ev.message_id and gm.time == (ev.timestamp or 0)
    assert gm.is_mentioned == ev.is_mentioned
    assert gm.is_reply_to_bot == ev.is_reply_to_bot
    # 段数组必须是深拷贝（下游改它不能污染事件）
    if gm.message_array:
        gm.message_array.append({"type": "x", "data": {}})
        assert len(ev.message_segments) == len(gm.message_array) - 1


def test_convert_legacy_matches_parser():
    for path in _fixture_paths():
        if os.path.basename(os.path.dirname(path)) == "milky":
            continue
        raw = _load(path)
        assert _core(convert_legacy(raw, BOT_QQ)) == _core(OneBotEventParser(bot_qq=BOT_QQ).parse(raw))


# ---------- D. 发送方向（reverse）静态核对 ----------

def _sender_src() -> str:
    return io.open(SENDER, encoding="utf-8").read()


def _func_src(name: str) -> str:
    src = _sender_src()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError("sender.py 里找不到 %s" % name)


def test_milky_post_converts_string_message_to_segment_array():
    body = _func_src("_post")
    assert '"type": "text"' in body and '"data": {"text": _m}' in body
    assert "MILKY_ACCESS_TOKEN" in body          # Bearer 鉴权
    assert "_MILKY_ACTIONS.get" in body          # action 名统一映射


def test_send_msg_raw_accepts_segment_array_and_reply_segment():
    body = _func_src("send_msg_raw")
    assert 'segments.extend(message[:40])' in body       # 段数组直通（限长）
    assert '"type": "reply"' in body                     # 引用回复自动加 reply 段
    assert '"type": "text"' in body                      # 字符串自动转 text 段


def test_send_response_handles_both_message_id_and_message_seq():
    body = _func_src("send_msg_raw")
    assert "message_id" in body and "message_seq" in body
