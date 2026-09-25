"""G2：请求类事件（RequestEvent）字段级映射回归。

证据：
- [DOC] Milky 规范 `common.ts` L35-58：friend_request{initiator_id,initiator_uid,comment,via} /
  group_join_request{group_id,notification_seq,is_filtered,initiator_id,comment} /
  group_invited_join_request{group_id,notification_seq,initiator_id,target_user_id} /
  group_invitation{group_id,invitation_seq,initiator_id,source_group_id?}。
  **规范里没有 request_id / flag**：群请求的标识是 `notification_seq`，好友请求没有标识
  （api/friend.ts L22-29 用 `initiator_uid` 同意/拒绝）—— 所以不许给它编一个 flag。
- [DOC] Milky `api/group.ts` L104 `accept_group_invitation` → `group_invitation` 属**请求类**
  （旧实现归 notice，本 Gap 纠正）。
- [DOC] OneBot 11 `event/request.md` L10-18 / L31-41：friend{user_id,comment,flag}、
  group{sub_type ∈ add|invite, group_id, user_id, comment, flag}；**规范没有** initiator_uid /
  is_filtered / target_user_id。
"""
import os

from src.adapters.milky_parser import MilkyEventParser
from src.adapters.onebot_parser import OneBotEventParser

BOT_QQ = 10001
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
MILKY_EVENT_OF_SCENE = {
    "friend": "friend_request",
    "group_join": "group_join_request",
    "group_invited_join": "group_invited_join_request",
    "group_invitation": "group_invitation",
}


def _milky(event_type, data):
    return MilkyEventParser(bot_qq=BOT_QQ).parse(
        {"time": 7, "self_id": BOT_QQ, "event_type": event_type, "data": data})


def _onebot(raw):
    return OneBotEventParser(bot_qq=BOT_QQ).parse(raw)


# ---------- Milky：三种事件 + 邀请 ----------

def test_milky_friend_request_fields():
    ev = _milky("friend_request", {"initiator_id": 456789, "initiator_uid": "u_x",
                                   "comment": "求加好友", "via": "qq"})
    assert ev.kind == "request"
    assert (ev.request_kind, ev.request_scene) == ("friend", "friend")
    assert ev.actor_id == 456789 and ev.request_uid == "u_x"
    assert ev.comment == "求加好友" and ev.text == "求加好友"
    assert ev.request_id == ""          # 规范没有标识 → 不伪造 flag
    assert ev.scope == "private"        # [INFERENCE] 好友请求与群无关


def test_milky_group_join_request_fields():
    ev = _milky("group_join_request", {"group_id": 123456, "notification_seq": 555001,
                                       "is_filtered": True, "initiator_id": 456789,
                                       "comment": "求入群"})
    assert (ev.request_kind, ev.request_scene) == ("group", "group_join")
    assert ev.request_id == "555001" and ev.request_filtered is True
    assert ev.group_id == 123456 and ev.scope == "group"
    assert ev.actor_id == 456789 and ev.comment == "求入群"


def test_milky_group_invited_join_request_keeps_target():
    ev = _milky("group_invited_join_request", {"group_id": 123456, "notification_seq": 555002,
                                               "initiator_id": 456789, "target_user_id": 456790})
    assert ev.request_scene == "group_invited_join"
    assert ev.actor_id == 456789 and ev.target_id == 456790      # 邀请者 / 被邀请者
    assert ev.request_id == "555002" and ev.comment == ""


def test_milky_group_invitation_is_request_not_notice():
    ev = _milky("group_invitation", {"group_id": 123456, "invitation_seq": 555003,
                                     "initiator_id": 456789})
    assert ev.kind == "request" and ev.request_scene == "group_invitation"
    assert ev.request_id == "555003" and ev.group_id == 123456


# ---------- OneBot ----------

def test_onebot_friend_request_fields():
    ev = _onebot({"post_type": "request", "request_type": "friend", "user_id": 456789,
                  "comment": "加个好友", "flag": "flag-1", "time": 7})
    assert (ev.request_kind, ev.request_scene) == ("friend", "friend")
    assert ev.request_id == "flag-1" and ev.actor_id == 456789 and ev.comment == "加个好友"
    assert ev.request_uid == "" and ev.request_filtered is False   # Milky 专有字段不得挪用


def test_onebot_group_add_request_is_group_join():
    ev = _onebot({"post_type": "request", "request_type": "group", "sub_type": "add",
                  "group_id": 123456, "user_id": 456789, "comment": "求入群",
                  "flag": "flag-2", "time": 7})
    assert ev.request_scene == "group_join" and ev.group_id == 123456
    assert ev.request_id == "flag-2"


def test_onebot_group_invite_maps_to_group_invitation():
    ev = _onebot({"post_type": "request", "request_type": "group", "sub_type": "invite",
                  "group_id": 123456, "user_id": 456789, "comment": "一起来",
                  "flag": "flag-3", "time": 7})
    assert ev.request_scene == "group_invitation"


# ---------- 跨协议等价 + 不伪造 ----------

def test_friend_request_equivalent_across_protocols():
    milky = _milky("friend_request", {"initiator_id": 456789, "initiator_uid": "u",
                                      "comment": "hi"})
    onebot = _onebot({"post_type": "request", "request_type": "friend", "user_id": 456789,
                      "comment": "hi", "flag": "f", "time": 7})
    assert (milky.kind, milky.request_kind, milky.request_scene, milky.actor_id, milky.comment) == \
           (onebot.kind, onebot.request_kind, onebot.request_scene, onebot.actor_id, onebot.comment)


def test_group_join_equivalent_semantics_across_protocols():
    milky = _milky("group_join_request", {"group_id": 123456, "notification_seq": 1,
                                          "initiator_id": 456789, "comment": "hi"})
    onebot = _onebot({"post_type": "request", "request_type": "group", "sub_type": "add",
                      "group_id": 123456, "user_id": 456789, "comment": "hi",
                      "flag": "f", "time": 7})
    for field in ("kind", "request_kind", "request_scene", "actor_id", "group_id", "comment"):
        assert getattr(milky, field) == getattr(onebot, field), field
    # 标识按各自协议：Milky=notification_seq，OneBot=flag —— 不能强行统一成同一个值
    assert milky.request_id == "1" and onebot.request_id == "f"


def test_absent_fields_are_not_fabricated():
    # Milky 事件里没有 OneBot 的 flag；OneBot 事件里没有 Milky 的 initiator_uid/is_filtered
    m = _milky("group_join_request", {"group_id": 1, "notification_seq": 2, "initiator_id": 3,
                                      "comment": ""})
    o = _onebot({"post_type": "request", "request_type": "group", "sub_type": "add",
                 "group_id": 1, "user_id": 3, "flag": "f", "time": 7})
    assert m.request_uid == "" and m.request_filtered is False
    assert o.request_uid == "" and o.request_filtered is False


# ---------- 夹具 + round-trip ----------

def test_request_fixtures_parse_with_provenance():
    import json
    seen = 0
    for rel in ("milky/friend_request.json", "milky/group_join_request.json",
                "milky/group_invited_join_request.json", "onebot11/friend_request.json",
                "onebot11/group_request_invite.json"):
        path = os.path.join(FIXTURES, rel)
        if not os.path.exists(path):
            continue
        raw = json.load(open(path, encoding="utf-8"))
        assert raw["_provenance"]["evidence"], rel
        ev = (_milky(raw["event_type"], raw["data"]) if rel.startswith("milky") else _onebot(raw))
        assert ev.kind == "request" and ev.request_scene, rel
        seen += 1
    assert seen >= 5


def test_request_roundtrip_is_stable():
    for event_type, data in (
            ("friend_request", {"initiator_id": 456789, "initiator_uid": "u", "comment": "a"}),
            ("group_join_request", {"group_id": 123456, "notification_seq": 9,
                                    "is_filtered": False, "initiator_id": 456789,
                                    "comment": "b"}),
            ("group_invited_join_request", {"group_id": 123456, "notification_seq": 10,
                                            "initiator_id": 456789, "target_user_id": 456790}),
            ("group_invitation", {"group_id": 123456, "invitation_seq": 11,
                                  "initiator_id": 456789})):
        ev = _milky(event_type, data)
        rebuilt = {"time": ev.timestamp, "self_id": BOT_QQ, "event_type": event_type,
                   "data": dict(data)}
        ev2 = MilkyEventParser(bot_qq=BOT_QQ).parse(rebuilt)
        for field in ("kind", "request_kind", "request_scene", "request_id", "actor_id",
                      "target_id", "group_id", "comment", "request_uid", "request_filtered"):
            assert getattr(ev, field) == getattr(ev2, field), (event_type, field)
