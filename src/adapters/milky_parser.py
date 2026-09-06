"""Milky 协议事件解析（EventEnvelope → InternalEvent）。

Milky（OneBot 进化版）事件信封：
    {"time": ..., "self_id": ..., "event_type": "message_receive", "data": {...}}

与 OneBot 的关键差异（其余字段语义一致）：
- 顶层无 post_type，用 event_type（value 见 mapping）
- data.message_scene 替代 message_type（friend / group / stranger / group_temp）
- data.peer_id 替代 group_id/user_id（friend=对方；group=群号）
- 消息段数组格式与 OneBot 相同（type/data 结构）——段扫描逻辑可复用

约束：与 OneBot 解析器输出等价（message_router 现有消费方零改动）。
"""
from typing import Any, Dict, List, Optional

from src.adapters.proto import InternalEvent

# event_type → 语义 kind（未列出的原样保留，由上游按 unknown 忽略）
_EVENT_KIND = {
    "message_receive": "message",
    "notice_receive": "notice",
    "lifecycle": "lifecycle",
}

_SCENE_SCOPE = {
    "friend": "private",
    "stranger": "private",
    "group": "group",
    "group_temp": "group",
}


def parse_milky_event(raw: Dict[str, Any], bot_qq: Optional[int] = None) -> InternalEvent:
    """Milky raw dict → InternalEvent（机械转换唯一入口；raw_data 隔离保留）。"""
    raw = dict(raw or {})
    ev = InternalEvent(raw_data=raw)
    ev.timestamp = raw.get("time") or raw.get("timestamp")
    if bot_qq is not None:
        ev.raw_data["self_id"] = raw.get("self_id")

    event_type = str(raw.get("event_type") or "unknown")
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    ev.kind = _EVENT_KIND.get(event_type, event_type if event_type else "unknown")
    scene = str(data.get("message_scene") or "")
    ev.scope = _SCENE_SCOPE.get(scene, "")
    peer_id = data.get("peer_id")
    sender_id = data.get("sender_id")

    if ev.kind == "message":
        ev.actor_id = int(sender_id) if sender_id else None
        if scene == "friend":
            ev.group_id = None
            ev.actor_id = ev.actor_id or (int(peer_id) if peer_id else None)
        elif scene == "group":
            ev.group_id = int(peer_id) if peer_id else None
        ev.message_id = data.get("message_id") or data.get("msg_id")
        _scan_segments(ev, data.get("message"), bot_qq)
    elif ev.kind == "notice":
        ev.actor_id = int(sender_id) if sender_id else None
        ev.notice_kind = data.get("notice_type") or event_type.replace("notice_", "")
        if peer_id is not None:
            ev.target_id = int(peer_id)
        if data.get("operator_id"):
            ev.operator_id = int(data.get("operator_id"))
        if data.get("file"):
            ev.notice_file = dict(data["file"])
    # lifecycle / unknown 仅保留基础字段（上游按 kind 处理）

    # 稳定标识（与 OneBot 解析器同规）
    ev.event_id = _event_id(ev)
    return ev


def _scan_segments(ev: InternalEvent, segments: Any, bot_qq: Optional[int]) -> None:
    """Milky 消息段扫描（type/data 格式同 OneBot；解析结果与 OneBot 等价）。"""
    text_parts: List[str] = []
    bot = str(bot_qq) if bot_qq is not None else ""
    ev.message_segments = [dict(s) for s in segments] if isinstance(segments, list) else []
    for seg in ev.message_segments:
        seg_type = str(seg.get("type") or "")
        data = seg.get("data") if isinstance(seg.get("data"), dict) else {}
        if seg_type == "text":
            text_parts.append(str(data.get("text") or ""))
        elif seg_type == "at":
            qq = str(data.get("qq") or "")
            ev.mentions.append(qq)
            if qq == bot:
                ev.is_mentioned = True
            elif qq != "all":
                ev.has_at_others = True
        elif seg_type == "image":
            url = str(data.get("url") or data.get("file") or "")
            if url:
                ev.images.append(url)
            fp = str(data.get("file") or "").strip()
            if fp:
                fp = fp[len("file://"):] if fp.startswith("file://") else fp
                if fp:
                    ev.image_files.append(fp)
        elif seg_type == "reply":
            try:
                ev.reply_id = int(data.get("id"))
            except (TypeError, ValueError):
                ev.reply_id = None
        elif seg_type:
            ev.segments_summary.append((seg_type, dict(data)))
        if seg_type and seg_type in ("forward", "json", "face", "sticker"):
            pass  # 已进 segments_summary
    ev.text = "".join(text_parts).strip()


def _event_id(ev: InternalEvent) -> str:
    g = ev.group_id if ev.group_id is not None else ""
    a = ev.actor_id if ev.actor_id is not None else ""
    m = ev.message_id if ev.message_id is not None else ""
    t = ev.timestamp if ev.timestamp is not None else ""
    return f"{ev.kind}:{ev.scope}:{g}:{a}:{m}:{t}"
