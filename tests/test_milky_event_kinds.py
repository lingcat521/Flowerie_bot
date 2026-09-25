"""Milky 顶层事件类型归一化（P4）：规范 21 种事件 → message/notice/request/lifecycle。

背景：规范 `protocol/src/ir/common.ts` 的 Event 联合**没有 notice_receive**（实测 0 次出现），
通知类事件各有独立 event_type。修复前除 message_receive 外，其余事件 kind 直接等于 event_type，
连 notice 分支都进不去（路由只认 notice_kind=group_upload/poke）。
"""
from src.adapters.milky_parser import MilkyEventParser, _event_kind


def _ev(event_type, data=None):
    return MilkyEventParser(bot_qq=10001).parse(
        {"time": 1, "self_id": 10001, "event_type": event_type, "data": data or {}})


def test_no_notice_receive_in_spec_but_still_accepted():
    # 旧样例兼容：notice_receive 仍映射成 notice（真实协议不会发这个 event_type）
    assert _event_kind("notice_receive") == "notice"


def test_all_spec_notice_events_map_to_notice():
    for et in ("message_recall", "group_member_increase", "group_member_decrease",
               "group_admin_change", "group_mute", "group_whole_mute", "group_name_change",
               "group_disband", "group_essence_message_change", "group_message_reaction",
               "peer_pin_change", "friend_file_upload", "group_file_upload",
               "group_nudge", "friend_nudge"):
        assert _event_kind(et) == "notice", et


def test_request_events_map_to_request():
    # group_invitation 亦属请求类：Milky api/group.ts L104 accept_group_invitation 可对其操作
    for et in ("friend_request", "group_join_request", "group_invited_join_request",
               "group_invitation"):
        assert _event_kind(et) == "request", et


def test_lifecycle_and_message_and_unknown():
    assert _event_kind("message_receive") == "message"
    assert _event_kind("bot_offline") == "lifecycle"
    assert _event_kind("something_new") == "something_new"   # 未知原样保留，不臆造


def test_group_nudge_fields_normalized():
    ev = _ev("group_nudge", {"group_id": 123456, "sender_id": 456789, "receiver_id": 10001,
                             "display_action": "拍了拍", "display_suffix": "的肩",
                             "display_action_img_url": ""})
    assert ev.kind == "notice" and ev.notice_kind == "poke" and ev.scope == "group"
    assert ev.group_id == 123456 and ev.actor_id == 456789 and ev.target_id == 10001


def test_friend_nudge_has_no_group_and_target_from_user_id():
    ev = _ev("friend_nudge", {"user_id": 10001, "is_self_send": False,
                              "is_self_receive": True, "display_action": "拍了拍",
                              "display_suffix": "", "display_action_img_url": ""})
    assert ev.kind == "notice" and ev.notice_kind == "poke" and ev.scope == "private"
    assert ev.target_id == 10001 and ev.group_id is None


def test_group_file_upload_normalized_like_onebot():
    ev = _ev("group_file_upload", {"group_id": 123456, "user_id": 456789, "file_id": "f1",
                                   "file_name": "a.zip", "file_size": 2048})
    assert ev.kind == "notice" and ev.notice_kind == "group_upload"
    assert ev.group_id == 123456 and ev.notice_file == {"id": "f1", "name": "a.zip", "size": 2048}


def test_message_recall_keeps_specific_notice_kind():
    ev = _ev("message_recall", {"message_scene": "group", "peer_id": 123456,
                                "message_seq": 5, "sender_id": 456789,
                                "operator_id": 1, "display_suffix": ""})
    assert ev.kind == "notice" and ev.notice_kind == "message_recall"
    assert ev.operator_id == 1


def test_request_event_sets_request_kind():
    ev = _ev("friend_request", {"initiator_id": 456789, "initiator_uid": "u1",
                                "comment": "hi", "via": "qq"})
    assert ev.kind == "request" and ev.request_kind == "friend"
