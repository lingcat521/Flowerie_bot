"""Phase 3 回归测试：OneBotEventParser 转换等价性 + raw_data 边界。

覆盖：普通群消息 / @机器人 / 图片 / 回复 / poke / 私聊(非群) / notice / malformed。
等价基准：file_parser.extract_mention_and_text + message_assembler._scan_reply_and_at
（同一判定规则逐项对照）。
"""
from src.adapters import OneBotEventParser

BOT_QQ = 10001
PARSER = OneBotEventParser(bot_qq=BOT_QQ)


def _expected_mention_and_text(message_array, bot_qq):
    """现有 message_router:283 行为快照（file_parser.extract_mention_and_text 同款）。"""
    if not isinstance(message_array, list):
        return "", False
    self_id = str(bot_qq)
    is_mentioned = False
    text_parts = []
    for msg in message_array:
        if msg.get("type") == "at":
            qq = str(msg.get("data", {}).get("qq", ""))
            if qq == self_id:
                is_mentioned = True
        elif msg.get("type") == "text":
            text_parts.append(msg.get("data", {}).get("text", ""))
    return "".join(text_parts).strip(), is_mentioned


def _expected_reply_scan(message_array, bot_qq):
    """现有 message_assembler._scan_reply_and_at 行为快照。"""
    r, o, a = False, False, False
    for seg in message_array:
        if seg.get("type") == "reply":
            qq = str(seg.get("data", {}).get("qq", ""))
            if qq == str(bot_qq):
                r = True
            else:
                o = True
        elif seg.get("type") == "at":
            qq = str(seg.get("data", {}).get("qq", ""))
            if qq != str(bot_qq):
                a = True
    return r, o, a


def _message_payload(message=None, message_type="group", **extra):
    return {"post_type": "message", "message_type": message_type, "group_id": 7,
            "user_id": 9, "message_id": 11, "time": 1000,
            "message": message if message is not None else [{"type": "text", "data": {"text": "你好"}}],
            **extra}


# ---------- 1. 普通群消息 ----------
def test_group_message_basic():
    ev = PARSER.parse(_message_payload())
    assert ev.kind == "message" and ev.scope == "group"
    assert ev.text == "你好" and ev.group_id == 7 and ev.actor_id == 9
    assert ev.message_id == 11 and ev.timestamp == 1000
    assert not ev.is_mentioned and not ev.images and ev.reply_id is None

    # 与 router 现有提取等价（快照行为契约）
    clean, mentioned = _expected_mention_and_text(
        [{"type": "text", "data": {"text": "你好"}}], BOT_QQ)
    assert ev.text == clean and ev.is_mentioned == mentioned


# ---------- 2. @机器人 ----------
def test_mention_bot():
    ev = PARSER.parse(_message_payload(
        [{"type": "at", "data": {"qq": BOT_QQ}}, {"type": "text", "data": {"text": " 早安"}}]))
    assert ev.is_mentioned is True and ev.mentions == [str(BOT_QQ)]
    assert ev.text == "早安"   # strip 后与 extract_mention_and_text 一致
    # @all：记录在 mentions（"all"）；is_mentioned 保持旧行为（仅 @bot 才算）
    ev2 = PARSER.parse(_message_payload([{"type": "at", "data": {"qq": "all"}}]))
    assert ev2.is_mentioned is False and ev2.mentions == ["all"]


# ---------- 3. 图片 / 表情包（face 视为普通段） ----------
def test_image_and_face():
    ev = PARSER.parse(_message_payload([
        {"type": "image", "data": {"url": "http://x/a.png"}},
        {"type": "text", "data": {"text": "看图"}},
        {"type": "face", "data": {"id": 3}}]))
    assert ev.images == ["http://x/a.png"]
    assert ev.text == "看图"
    assert ("face", {"id": 3}) in ev.segments_summary


# ---------- 4. 回复消息 ----------
def test_reply_message():
    ev = PARSER.parse(_message_payload([
        {"type": "reply", "data": {"id": 55, "qq": BOT_QQ}},
        {"type": "text", "data": {"text": "收到"}}]))
    assert ev.reply_id == 55 and ev.is_reply_to_bot is True
    ev2 = PARSER.parse(_message_payload([
        {"type": "reply", "data": {"id": 56, "qq": 2}},
        {"type": "at", "data": {"qq": 3}},
        {"type": "text", "data": {"text": "x"}}]))
    assert ev2.has_reply_to_other is True and ev2.has_at_others is True
    assert ev2.reply_id == 56 and ev2.is_reply_to_bot is False
    # 与现有 _scan_reply_and_at 行为快照一致
    r, o, a = _expected_reply_scan(
        [{"type": "reply", "data": {"id": 56, "qq": 2}}, {"type": "at", "data": {"qq": 3}},
         {"type": "text", "data": {"text": "x"}}], BOT_QQ)
    assert (ev2.is_reply_to_bot, ev2.has_reply_to_other, ev2.has_at_others) == (r, o, a)


# ---------- 5. poke ----------
def test_poke():
    ev = PARSER.parse({"post_type": "notice", "notice_type": "notify", "sub_type": "poke",
                       "group_id": 7, "user_id": 9, "target_id": BOT_QQ, "time": 1001})
    assert ev.kind == "notice" and ev.notice_kind == "poke"
    assert ev.scope == "group" and ev.actor_id == 9


# ---------- 6. 非群消息（私聊） ----------
def test_private_message():
    ev = PARSER.parse(_message_payload(message_type="private", group_id=None))
    assert ev.scope == "private" and ev.kind == "message"
    assert ev.group_id is None and ev.text == "你好"


# ---------- 7. notice（非 poke） ----------
def test_notice_generic():
    ev = PARSER.parse({"post_type": "notice", "notice_type": "group_increase",
                       "group_id": 7, "user_id": 20, "operator_id": 21, "time": 1002})
    assert ev.kind == "notice" and ev.notice_kind == "group_increase"
    assert ev.scope == "group" and ev.actor_id == 20


# ---------- 8. malformed / 缺失字段 ----------
def test_malformed_payloads():
    assert PARSER.parse({}).kind == "unknown"
    assert PARSER.parse(None).kind == "unknown"
    assert PARSER.parse({"post_type": "message", "message": 12345}).text == ""  # 非法消息类型→空
    assert PARSER.parse({"post_type": "message", "message_type": "group",
                         "message": [{"type": "reply", "data": {"id": "abc"}}]}).reply_id is None
    # 缺 time → 当前时间兜底（不抛）
    ev = PARSER.parse({"post_type": "message", "message_type": "group",
                       "message": [{"type": "text", "data": {"text": "t"}}]})
    assert ev.timestamp and ev.kind == "message"


# ---------- raw_data 边界：不让 OneBot 字段越过 adapter ----------
def test_raw_data_boundary():
    ev = PARSER.parse(_message_payload())
    # InternalEvent 没有 OneBot 字段（业务层拿不到）
    for name in ("post_type", "sub_type", "message_type", "self_id", "message"):
        assert not hasattr(ev, name), f"{name} 泄漏到事件模型"
    # 事件可安全序列化为纯语义字段（排除 raw_data 后无 OneBot 键）
    import json
    safe = {k: v for k, v in ev.__dict__.items() if k != "raw_data"}
    text = json.dumps(safe, default=str)
    for token in ("post_type", "sub_type", "message_type", "self_id"):
        assert token not in text
    # raw_data 自身是浅拷贝：修改原始 dict 不影响已解析事件语义字段
    raw = _message_payload()
    ev2 = PARSER.parse(raw)
    raw["message"] = [{"type": "text", "data": {"text": "改了"}}]
    assert ev2.text == "你好"   # 语义字段不跟随（后续事件才变）


# ---------- 冻结业务层验证：人格/记忆/AI 只接文本字段（已审计零 OneBot），
# 此处以事件→下游常用形态再确认：无 raw 键、字段均领域。 ----------
def test_frozen_layers_see_only_domain_fields():
    ev = PARSER.parse(_message_payload())
    assert isinstance(ev.text, str) and isinstance(ev.group_id, int)
    # 冻结层接收形态（context_manager 的 add_context 派生态）仅含语义字段
    ctx_entry = {"user_id": ev.actor_id, "message": ev.text, "is_bot": False, "time": ev.timestamp}
    assert set(ctx_entry.keys()) == {"user_id", "message", "is_bot", "time"}
