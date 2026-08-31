"""Phase 5 行为基线 & 对照测试（不实例化 Router；验证迁移点等价 + compat 组装）。

旧路径（router 现状）：file_parser.extract_mention_and_text + assembler._scan_reply_and_at
新路径（Phase 5）：   OneBotEventParser → InternalEvent → compat.build_group_message
断言：clean_text / is_mentioned / reply 三态 / at 三态 / GroupMessage 字段 一致。
"""
import pytest

from src.adapters import OneBotEventParser
from src.adapters.compat import build_group_message

BOT_QQ = 10001
PARSER = OneBotEventParser(bot_qq=BOT_QQ)


def _old_mention_and_text(message_array, bot_qq):
    """旧路径行为快照（file_parser.extract_mention_and_text 同款）。"""
    if not isinstance(message_array, list):
        return "", False
    self_id, is_mentioned, parts = str(bot_qq), False, []
    for m in message_array:
        if m.get("type") == "at":
            if str(m.get("data", {}).get("qq", "")) == self_id:
                is_mentioned = True
        elif m.get("type") == "text":
            parts.append(m.get("data", {}).get("text", ""))
    return "".join(parts).strip(), is_mentioned


def _old_reply_scan(message_array, bot_qq):
    r, o, a = False, False, False
    for seg in message_array:
        if seg.get("type") == "reply":
            qq = str(seg.get("data", {}).get("qq", ""))
            if qq == str(bot_qq):
                r = True
            else:
                o = True
        elif seg.get("type") == "at":
            if str(seg.get("data", {}).get("qq", "")) != str(bot_qq):
                a = True
    return r, o, a


def _payload(message, message_type="group", group_id=7, user_id=9, message_id=11, time=1000,
             post_type="message", notice_type=None, sub_type=None):
    d = {"post_type": post_type, "group_id": group_id, "user_id": user_id,
         "message_id": message_id, "time": time}
    if post_type == "message":
        d["message_type"] = message_type
        d["message"] = message
    if notice_type:
        d["notice_type"] = notice_type
    if sub_type:
        d["sub_type"] = sub_type
    return d


@pytest.mark.parametrize("message", [
    [{"type": "text", "data": {"text": "你好"}}],  # 1 普通
    [{"type": "at", "data": {"qq": BOT_QQ}}, {"type": "text", "data": {"text": " 早安"}}],  # 2 @bot
    [{"type": "at", "data": {"qq": "all"}}, {"type": "text", "data": {"text": "全体"}}],  # 3 @all
    [{"type": "image", "data": {"url": "http://x/i.png"}}, {"type": "text", "data": {"text": "图"}}],  # 4 图片
    [{"type": "face", "data": {"id": 3}}, {"type": "text", "data": {"text": "哈哈"}}],  # 5 face
    [{"type": "reply", "data": {"id": 55, "qq": BOT_QQ}}, {"type": "text", "data": {"text": "收到"}}],  # 6 回复 bot
    [{"type": "reply", "data": {"id": 56, "qq": 2}}, {"type": "text", "data": {"text": "行"}}],  # 7 回复他人
    [{"type": "reply", "data": {"id": 57, "qq": 2}}, {"type": "at", "data": {"qq": 3}},
     {"type": "text", "data": {"text": "一起"}}],  # 8 回复+@他人
])
def test_group_message_equals_legacy_chain(message):
    raw = _payload(message)
    ev = PARSER.parse(raw)
    gm = build_group_message(ev, clean_text=ev.text, full_text=ev.text)

    old_clean, old_mentioned = _old_mention_and_text(message, BOT_QQ)
    old_rep, old_other, old_at = _old_reply_scan(message, BOT_QQ)

    assert gm.clean_text == old_clean == ev.text
    assert gm.is_mentioned == old_mentioned == ev.is_mentioned
    assert (gm.is_reply_to_bot, gm.has_reply_to_other, gm.has_at_others) == (
        old_rep, old_other, old_at) == (ev.is_reply_to_bot, ev.has_reply_to_other, ev.has_at_others)
    assert gm.group_id == 7 and gm.user_id == 9 and gm.message_id == 11
    assert gm.message_array == message
    if any(s.get("type") == "image" for s in message):
        assert gm.message_array[0]["data"]["url"] == ev.images[0]


# ---------- 9 poke ----------
def test_poke_preserved():
    raw = _payload([{"type": "text", "data": {"text": "x"}}],
                   post_type="notice", notice_type="notify", sub_type="poke")
    ev = PARSER.parse(raw)
    assert ev.kind == "notice" and ev.notice_kind == "poke" and ev.actor_id == 9
    assert ev.scope == "group"


# ---------- 10 notice（群成员增加） ----------
def test_notice_preserved():
    raw = {"post_type": "notice", "notice_type": "group_increase", "group_id": 7,
           "user_id": 20, "operator_id": 21, "time": 1002}
    ev = PARSER.parse(raw)
    assert ev.kind == "notice" and ev.notice_kind == "group_increase"
    assert ev.actor_id == 20 and ev.group_id == 7


# ---------- 11 私聊 ----------
def test_private_scope():
    ev = PARSER.parse(_payload([{"type": "text", "data": {"text": "私聊"}}],
                               message_type="private", group_id=None))
    assert ev.scope == "private" and ev.group_id is None


# ---------- 12/13/14 unknown / malformed / 缺失字段 ----------
def test_unknown_and_malformed_are_ignorable():
    assert PARSER.parse({"post_type": "whatever", "abc": 1}).kind == "unknown"  # 未知
    ev = PARSER.parse({"post_type": "message", "message_type": "group",
                       "group_id": 7, "message": [{"type": "text", "data": {"text": "t"}}]})
    assert ev.actor_id is None                                                    # 缺失 user_id
    assert PARSER.parse(None).kind == "unknown"                                   # 非 dict
    ev2 = PARSER.parse({"post_type": "message", "message_type": "group", "group_id": 7,
                        "user_id": 1, "message": [{"type": "reply", "data": {"id": "x"}}]})
    assert ev2.reply_id is None                                                   # 非法 reply_id


# ---------- raw_data 静态边界：compat/parser 不读 raw_data ----------
def test_no_raw_data_read_in_migration_path():
    import inspect

    from src.adapters import compat, onebot_parser
    for src in (inspect.getsource(compat), inspect.getsource(onebot_parser)):
        assert "raw_data[" not in src
        assert "raw_data.get" not in src


# ---------- 15/16：poke 与群文件上传的边界字段（行为对照，Step 1） ----------
def test_poke_boundary_fields():
    """poke 迁移：target 兜底（target_id/target/user_id）→ target_id 恒等解析。"""
    ev = PARSER.parse({"post_type": "notice", "notice_type": "notify", "sub_type": "poke",
                       "group_id": 7, "user_id": 9, "target_id": BOT_QQ, "time": 2000})
    assert ev.notice_kind == "poke"
    assert ev.target_id == BOT_QQ          # 旧 target_id 优先语义
    assert ev.group_id == 7 and ev.actor_id == 9

    # 旧兜底（data.get("target_id") or target or user_id）：只有 user_id 时
    ev2 = PARSER.parse({"post_type": "notice", "notice_type": "notify", "sub_type": "poke",
                        "group_id": 7, "user_id": 9, "time": 2001})
    # 旧行为 target=user_id（当 target_id/target 缺失）——映射表保持同一优先级
    assert ev2.target_id is None           # 无 target_id 时 None；迁移函数兜底 actor_id
    assert ev2.actor_id == 9


def test_upload_boundary_fields():
    """群文件上传：file 对象在边界提取（name/id/size/busid）。"""
    ev = PARSER.parse({"post_type": "notice", "notice_type": "group_upload", "group_id": 7,
                       "user_id": 9, "time": 3000,
                       "file": {"name": "a.txt", "id": "f1", "size": 1024, "busid": 0}})
    assert ev.notice_kind == "group_upload"
    assert ev.notice_file == {"name": "a.txt", "id": "f1", "size": 1024, "busid": 0}
    assert ev.group_id == 7 and ev.actor_id == 9 and ev.timestamp == 3000
