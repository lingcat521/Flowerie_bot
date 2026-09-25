"""OneBot 12 事件/动作解析（**骨架**，状态：NOT_REAL_DEVICE_VALIDATED）。

证据：[DOC] 官方规范仓库 botuniverse/onebot（HEAD d533f0f，文档站 12.onebot.dev）：
- specs/connect/data-protocol/event.md：事件必备 id / time(float64 秒) / type(meta|message|notice|request) /
  detail_type / sub_type + self{platform,user_id}；缺任一字段即**不是有效事件**。
- specs/connect/data-protocol/action-request.md：{action, params, echo?, self?}，动作名如 send_message。
- specs/connect/data-protocol/action-response.md：{status(ok|failed), retcode(int64), data, message, echo?}，
  retcode 有分段规范（0 成功 / 1xxxx 请求错误 / 2xxxx 处理器错误 / 3xxxx 执行错误 …）。
- specs/interface/message/type.md：消息段 {type, data}；请求里可为字符串；事件里必须段数组；
  另有 alt_message 纯文本替代表示。
- specs/interface/message/segments.md：text / mention / mention_all / image / voice / audio /
  video / file / location / reply …
- 传输四种：websocket / websocket-reverse / http / http-webhook（specs/connect/communication/）。

与 OneBot 11 的关键差异（详见 docs/onebot12-research.md）：
- 事件判别从 post_type+message_type/notice_type 变为 type + detail_type + sub_type；
- 所有 ID 都是字符串（user_id/group_id/message_id），时间戳是 float64；
- 动作是 action+params（send_msg → send_message），响应多一个 status 与人类可读 message；
- @ 用 mention（v11 是 at）；语音/音频分成 voice / audio 两种段（v11 只有 record）。

原则（任务书 §10.2/§23）：没有真实 v12 实现可联调 → 只做规格级映射，未定义处一律不猜。
"""
from typing import Any, Dict, List, Optional

from src.adapters.onebot_parser import (
    _normalize_file_segment,
    _normalize_record_segment,
    _normalize_video_segment,
)
from src.adapters.proto import InternalEvent

# v12 事件 type → 领域 kind（[DOC] event.md：必须是 meta/message/notice/request 之一）
_V12_KIND = {"message": "message", "notice": "notice", "request": "request", "meta": "lifecycle"}

# v12 动作名（[DOC] interface/*/actions.md）：Flowerie 现有 OneBot11 端点 → v12 动作。
# 只登记已在规范里逐字核对过的映射；未列出的端点表示尚未核对（保持 [UNKNOWN]）
V12_ACTION_MAP = {
    "send_msg": "send_message",
    "send_group_msg": "send_message",
    "send_private_msg": "send_message",
    "delete_msg": "delete_message",
    "get_group_info": "get_group_info",
    "get_group_list": "get_group_list",
    "get_group_member_info": "get_group_member_info",
    "get_group_member_list": "get_group_member_list",
    "get_friend_list": "get_friend_list",
    "get_login_info": "get_self_info",
    "get_status": "get_status",
    "get_msg": "get_message",
    "get_group_msg_history": "get_latest_events",
}


def _to_int(value: Any) -> Optional[int]:
    """v12 的 ID 是字符串；Flowerie 内部仍是 int（QQ 号数字）。无法转换时返回 None，不猜。"""
    if value is None or str(value) == "":
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


class OneBot12EventParser:
    """OneBot 12 raw dict → InternalEvent（骨架，未实机验证）。"""

    def __init__(self, bot_qq: Optional[Any] = None, note: str = ""):
        self._bot_qq = str(bot_qq) if bot_qq is not None else ""
        self._note = note

    def parse(self, raw: Dict[str, Any]) -> InternalEvent:
        raw = dict(raw or {})
        ev = InternalEvent(raw_data=raw)
        ev.event_id = str(raw.get("id") or "")
        if isinstance(raw.get("time"), (int, float)):
            try:
                ev.timestamp = int(float(raw["time"]))
            except (TypeError, ValueError):
                ev.timestamp = None
        vtype = str(raw.get("type") or "")
        ev.kind = _V12_KIND.get(vtype, vtype or "unknown")
        detail = str(raw.get("detail_type") or "")
        sub = str(raw.get("sub_type") or "")
        if ev.kind == "message":
            self._fill_message(ev, raw, detail, sub)
        elif ev.kind == "notice":
            ev.notice_kind = detail or sub
            ev.actor_id = _to_int(raw.get("user_id"))
            ev.group_id = _to_int(raw.get("group_id"))
        elif ev.kind == "request":
            ev.request_kind = "group" if detail in ("group", "guild") else (detail or "")
            ev.request_scene = detail or ""
            ev.actor_id = _to_int(raw.get("user_id"))
            ev.group_id = _to_int(raw.get("group_id"))
            ev.comment = str(raw.get("comment") or "")
        elif ev.kind == "lifecycle":
            ev.lifecycle_kind = detail or sub
        if not ev.event_id:
            ev.event_id = "v12:%s:%s:%s:%s" % (ev.kind, ev.scope, ev.group_id, ev.actor_id)
        return ev

    def _fill_message(self, ev: InternalEvent, raw: Dict[str, Any], detail: str, sub: str) -> None:
        if detail == "private":
            ev.scope = "private"
            ev.scene = "temp" if sub == "group" else ("stranger" if sub == "other" else "friend")
            ev.actor_id = _to_int(raw.get("user_id"))
        elif detail == "group":
            ev.scope = "group"
            ev.scene = "group"
            ev.group_id = _to_int(raw.get("group_id"))
            ev.actor_id = _to_int(raw.get("user_id"))
        else:
            ev.scope = detail
        ev.message_id = _to_int(raw.get("message_id"))
        self._scan_segments(ev, raw.get("message"))
        alt = raw.get("alt_message")
        if isinstance(alt, str) and not ev.text:
            ev.text = alt.strip()

    def _scan_segments(self, ev: InternalEvent, segments: Any) -> None:
        if isinstance(segments, str):
            segments = [{"type": "text", "data": {"text": segments}}]
        if not isinstance(segments, list):
            return
        ev.message_segments = [dict(s) for s in segments if isinstance(s, dict)]
        text_parts: List[str] = []
        for seg in ev.message_segments:
            stype = str(seg.get("type") or "")
            data = seg.get("data") if isinstance(seg.get("data"), dict) else {}
            if stype == "text":
                text_parts.append(str(data.get("text") or ""))
            elif stype == "mention":
                uid = str(data.get("user_id") or "")
                if uid:
                    ev.mentions.append(uid)
                    if uid == self._bot_qq:
                        ev.is_mentioned = True
                    else:
                        ev.has_at_others = True
            elif stype == "mention_all":
                ev.mentions.append("all")
            elif stype == "image":
                url = str(data.get("url") or "")
                if url:
                    ev.images.append(url)
                fid = str(data.get("file_id") or "")
                if fid:
                    ev.images.append("file_id:" + fid)
                ev.segments_summary.append((stype, dict(data)))
            elif stype in ("voice", "audio"):
                rec = _normalize_record_segment(data)
                rec["kind"] = stype
                ev.records.append(rec)
                ev.segments_summary.append((stype, dict(data)))
            elif stype == "video":
                ev.videos.append(_normalize_video_segment(data))
                ev.segments_summary.append((stype, dict(data)))
            elif stype == "file":
                ev.files.append(_normalize_file_segment(data))
                ev.segments_summary.append((stype, dict(data)))
            elif stype == "reply":
                ev.reply_id = _to_int(data.get("message_id"))
                ev.reply_ref = {"id": ev.reply_id,
                                "message_id": str(data.get("message_id") or ""),
                                "user_id": str(data.get("user_id") or "")}
                ev.segments_summary.append((stype, dict(data)))
            elif stype:
                ev.segments_summary.append((stype, dict(data)))
        ev.text = "".join(text_parts).strip()


def normalize_action_response(raw: Dict[str, Any]) -> Dict[str, Any]:
    """v12 动作响应 → Flowerie 统一 ok/data/error（骨架）。

    [DOC] action-response.md：{status(ok|failed), retcode, data, message, echo?}；
    retcode 0 成功，1xxxx/2xxxx/3xxxx 分别表示请求/处理器/执行错误。
    """
    raw = dict(raw or {})
    status = str(raw.get("status") or "")
    retcode = raw.get("retcode")
    ok = status == "ok" and (retcode in (0, None))
    err = "" if ok else (str(raw.get("message") or "") or ("retcode=%s" % retcode))
    return {"ok": ok, "data": raw.get("data"), "error": err,
            "retcode": retcode, "echo": raw.get("echo")}
