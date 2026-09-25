"""G1：Milky `message_scene=temp`（临时会话）归一化回归。

证据：
- [DOC] Milky 规范 `common.ts` L266-291：IncomingMessage 以 `message_scene` 判别
  friend / group / **temp**；temp 变体字段 peer_id / message_seq / sender_id / time / segments
  + **可选** `group` 实体（L158-168：GroupEntity.group_id）。
- [CODE] LLBot `src/milky/transform/event.ts` L78-80：temp 场景 peer_id = data.peerUin。
- [DOC] OneBot 11 `event/message.md` L16：私聊 sub_type=group 即群临时会话；**规范无 group_id**。

Flowerie Core 现状（本测试同时钉住这个边界）：`message_router._handle_message`
首行是 `if event.scope != "group": return` —— **Core 只处理群会话**，所以 temp 必须归一化成
"私聊范围 + temp 会话类型 + 来源群作为上下文"，既不能 `scope=""`（丢失），也不能冒充群会话。
"""
import os

from src.adapters.milky_parser import MilkyEventParser
from src.adapters.onebot_parser import OneBotEventParser

BOT_QQ = 10001
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _milky(data):
    return MilkyEventParser(bot_qq=BOT_QQ).parse(
        {"time": 1, "self_id": BOT_QQ, "event_type": "message_receive", "data": data})


def _onebot(raw):
    return OneBotEventParser(bot_qq=BOT_QQ).parse(raw)


def test_milky_temp_with_group_entity():
    ev = _milky({"message_scene": "temp", "peer_id": 456789, "message_seq": 770001,
                 "sender_id": 456789, "segments": [{"type": "text", "data": {"text": "hi"}}],
                 "group": {"group_id": 123456, "group_name": "测试群"}})
    assert ev.kind == "message"
    assert ev.scope == "private" and ev.scene == "temp"
    assert ev.actor_id == 456789 and ev.message_id == 770001
    assert ev.group_id is None
    assert ev.context_group_id == 123456
    assert ev.text == "hi"


def test_milky_temp_without_group_entity_is_optional():
    ev = _milky({"message_scene": "temp", "peer_id": 456789, "message_seq": 770002,
                 "sender_id": 456789, "segments": []})
    assert ev.scope == "private" and ev.scene == "temp"
    assert ev.context_group_id is None


def test_milky_group_temp_alias_normalized_to_temp():
    ev = _milky({"message_scene": "group_temp", "peer_id": 456789, "sender_id": 456789,
                 "message_seq": 3, "segments": []})
    assert ev.scene == "temp" and ev.scope == "private"


def test_milky_friend_and_group_scene_unchanged():
    friend = _milky({"message_scene": "friend", "peer_id": 456789, "sender_id": 456789,
                     "message_seq": 4, "segments": []})
    group = _milky({"message_scene": "group", "peer_id": 123456, "sender_id": 456789,
                    "message_seq": 5, "segments": []})
    assert (friend.scope, friend.scene) == ("private", "friend")
    assert (group.scope, group.scene) == ("group", "group")
    assert group.group_id == 123456 and group.context_group_id is None


def test_onebot_private_group_subtype_is_temp():
    ev = _onebot({"post_type": "message", "message_type": "private", "sub_type": "group",
                  "user_id": 456789, "message_id": 880001, "time": 1,
                  "message": [{"type": "text", "data": {"text": "hi"}}]})
    assert ev.scope == "private" and ev.scene == "temp"
    assert ev.actor_id == 456789 and ev.group_id is None
    assert ev.context_group_id is None


def test_onebot_private_with_impl_group_id_becomes_context():
    ev = _onebot({"post_type": "message", "message_type": "private", "sub_type": "group",
                  "user_id": 456789, "message_id": 880002, "time": 1, "group_id": 123456,
                  "message": []})
    assert ev.scene == "temp" and ev.context_group_id == 123456 and ev.group_id is None


def test_onebot_friend_private_and_group_scene():
    friend = _onebot({"post_type": "message", "message_type": "private", "sub_type": "friend",
                      "user_id": 1, "message_id": 1, "time": 1, "message": []})
    group = _onebot({"post_type": "message", "message_type": "group", "sub_type": "normal",
                     "group_id": 2, "user_id": 1, "message_id": 2, "time": 1, "message": []})
    assert (friend.scope, friend.scene) == ("private", "friend")
    assert (group.scope, group.scene, group.group_id) == ("group", "group", 2)


def test_temp_equivalent_across_protocols():
    milky = _milky({"message_scene": "temp", "peer_id": 456789, "sender_id": 456789,
                    "message_seq": 9, "segments": [{"type": "text", "data": {"text": "x"}}],
                    "group": {"group_id": 123456}})
    onebot = _onebot({"post_type": "message", "message_type": "private", "sub_type": "group",
                      "user_id": 456789, "message_id": 9, "time": 1, "group_id": 123456,
                      "message": [{"type": "text", "data": {"text": "x"}}]})
    assert (milky.scope, milky.scene, milky.context_group_id) == \
           (onebot.scope, onebot.scene, onebot.context_group_id)


def test_temp_fixtures_parse_and_keep_provenance():
    import json
    for rel in ("milky/temp_message_scene.json", "onebot11/private_group_temp.json"):
        path = os.path.join(FIXTURES, rel)
        if not os.path.exists(path):
            continue
        raw = json.load(open(path, encoding="utf-8"))
        assert raw["_provenance"]["evidence"]
        ev = (_milky(raw["data"]) if rel.startswith("milky") else _onebot(raw))
        assert ev.scope == "private" and ev.scene == "temp" and ev.scope != ""


def test_temp_roundtrip_stable():
    ev = _milky({"message_scene": "temp", "peer_id": 456789, "sender_id": 456789,
                 "message_seq": 11, "segments": [{"type": "text", "data": {"text": "t"}}],
                 "group": {"group_id": 123456}})
    rebuilt = {"time": ev.timestamp, "self_id": BOT_QQ, "event_type": "message_receive",
               "data": {"message_scene": "temp", "peer_id": 456789, "sender_id": ev.actor_id,
                        "message_seq": ev.message_id, "segments": ev.message_segments,
                        "group": {"group_id": ev.context_group_id}}}
    ev2 = MilkyEventParser(bot_qq=BOT_QQ).parse(rebuilt)
    assert (ev2.scope, ev2.scene, ev2.context_group_id, ev2.text) == \
           (ev.scope, ev.scene, ev.context_group_id, ev.text)


# ---- 多客户端等价（任务书：OneBot 11 / Milky 多客户端协议级兼容）----

def test_onebot_gocqhttp_temp_uses_sender_group_id():
    """go-cqhttp 把临时会话的来源群放在 sender.group_id（coolq/event.go L136-172）[CODE]。

    与顶层 group_id 形态（另一些实现）必须归一到同一个 context_group_id ——
    这是跨客户端等价，不是"看起来兼容"。
    """
    ev = _onebot({"post_type": "message", "message_type": "private", "sub_type": "group",
                  "user_id": 456789, "message_id": 77129, "time": 1, "temp_source": 0,
                  "message": [{"type": "text", "data": {"text": "临时会话"}}],
                  "sender": {"user_id": 456789, "group_id": 123456, "nickname": "群友",
                             "sex": "unknown", "age": 0}})
    assert ev.scene == "temp" and ev.group_id is None
    assert ev.context_group_id == 123456, "go-cqhttp 的 sender.group_id 未被识别为上下文群"


def test_gocqhttp_fixture_matches_top_level_shape():
    """同一语义的两种客户端形态，归一化结果必须完全一致（跨客户端等价性）。"""
    import json
    import os
    root = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(root, "fixtures/go-cqhttp/private_temp_message.json"),
              encoding="utf-8") as fh:
        fixture = json.load(fh)
    from_top = _onebot({"post_type": "message", "message_type": "private", "sub_type": "group",
                        "user_id": 456789, "message_id": 77129, "time": 1, "group_id": 123456,
                        "message": [{"type": "text", "data": {"text": "临时会话"}}]})
    from_sender = _onebot(fixture)
    assert (from_top.scope, from_top.scene, from_top.context_group_id) == \
           (from_sender.scope, from_sender.scene, from_sender.context_group_id)
    assert from_sender.context_group_id == 123456
