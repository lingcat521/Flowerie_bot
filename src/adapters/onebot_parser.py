"""OneBot → InternalEvent 解析器（Phase 3，Facade/Wrapper 风格）。

只做「机械转换」，组合现有已有实现，**不复制** WS/HTTP/Token 逻辑：
- 文本/at/图片/回复提取：与 `src/core/file_parser.extract_mention_and_text` /
  `src/core/message_assembler._scan_reply_and_at` 逻辑逐行等价（同一判定规则）
- 图片取值：url 优先、file 兜底（等价于 src/sdk/onebot/transformer.extract_images；
  与 assembler._describe_images 的差异 = 仅 file 路径图不描述——不影响当前行为）
- 不含任何网络调用；不 import 冻结业务层
"""
import time
from typing import Any, Dict, List, Optional

from src.adapters.proto import InternalEvent


def _normalize_array(raw: Any) -> List[Dict[str, Any]]:
    """OneBot11 兼容：消息数组可能为字符串（转 text 段）或非法类型（空数组）。"""
    if isinstance(raw, str):
        return [{"type": "text", "data": {"text": raw}}]
    if isinstance(raw, list):
        return [seg for seg in raw if isinstance(seg, dict)]
    return []


class OneBotEventParser:
    """OneBot raw dict → InternalEvent（转换唯一入口；raw_data 隔离保留）。"""

    def __init__(self, bot_qq: Optional[int] = None, note: str = ""):
        self._bot_qq = str(bot_qq) if bot_qq is not None else ""
        self._note = note

    def parse(self, raw: Dict[str, Any]) -> InternalEvent:
        raw = dict(raw or {})
        post_type = str(raw.get("post_type") or "unknown")
        kind = {"message": "message", "notice": "notice",
                "request": "request", "meta_event": "lifecycle"}.get(post_type, "unknown")
        message_type = raw.get("message_type")
        group_id = raw.get("group_id")
        if kind == "message":
            scope = "group" if message_type == "group" else ("private" if message_type == "private" else "")
        else:
            scope = "group" if group_id is not None else ""
        actor_id = raw.get("user_id")
        message_id = raw.get("message_id")
        timestamp = raw.get("time")
        if timestamp is None:
            timestamp = int(time.time())

        event = InternalEvent(
            event_id=self._event_id(kind, scope, group_id, actor_id, message_id, timestamp),
            kind=kind, scope=scope,
            group_id=group_id, actor_id=actor_id,
            message_id=message_id, timestamp=timestamp,
            raw_data=raw,
        )
        event.operator_id = raw.get("operator_id") or actor_id
        event.target_id = raw.get("target_id")
        if kind == "notice" and str(raw.get("notice_type") or "") == "group_upload":
            file_raw = raw.get("file")
            event.notice_file = dict(file_raw) if isinstance(file_raw, dict) else {}
        elif kind == "notice" and raw.get("file") is not None:
            file_raw = raw.get("file")
            event.notice_file = dict(file_raw) if isinstance(file_raw, dict) else {}
        if kind == "message":
            self._fill_message(event, raw)
        elif kind == "notice":
            self._fill_notice(event, raw)
        elif kind == "request":
            event.request_kind = str(raw.get("request_type") or "")
            event.notice_kind = event.request_kind
            event.text = str(raw.get("comment") or "")[:500]
        elif kind == "lifecycle":
            event.lifecycle_kind = str(raw.get("meta_event_type") or "")
            event.notice_kind = event.lifecycle_kind
        return event

    # ---------- 各类型 ----------
    def _fill_message(self, event: InternalEvent, raw: Dict[str, Any]) -> None:
        arr = _normalize_array(raw.get("message"))
        text_parts: List[str] = []
        mentions: List[str] = []
        images: List[str] = []
        image_files: List[str] = []
        reply_id: Optional[int] = None
        is_reply_to_bot = has_reply_to_other = has_at_others = False
        summary: List[tuple] = []
        for seg in arr:
            seg_type = str(seg.get("type") or "")
            data = seg.get("data") if isinstance(seg.get("data"), dict) else {}
            if seg_type == "text":
                text_parts.append(str(data.get("text") or ""))
            elif seg_type == "at":
                qq = str(data.get("qq") or "")
                mentions.append(qq)
                # 等价格：旧行为（file_parser.extract_mention_and_text）仅 qq==bot_qq
                # 视为 @机器人；@all 记录在 mentions（"all"）但不置 is_mentioned
                if qq == self._bot_qq:
                    event.is_mentioned = True
                elif qq != self._bot_qq:
                    has_at_others = True
            elif seg_type == "image":
                url = str(data.get("url") or data.get("file") or "")
                if url:
                    images.append(url)
                fp = str(data.get("file") or "").strip()
                if fp:
                    _f = fp[len("file://"):] if fp.startswith("file://") else fp
                    if _f:
                        image_files.append(_f)
            elif seg_type == "reply":
                try:
                    reply_id = int(data.get("id"))
                except (TypeError, ValueError):
                    reply_id = None
                replied_qq = str(data.get("qq") or "")
                if replied_qq == self._bot_qq:
                    is_reply_to_bot = True
                elif replied_qq:
                    has_reply_to_other = True
            elif seg_type == "forward":
                summary.append(("forward", dict(data)))
            elif seg_type == "json":
                summary.append(("json", dict(data)))
            elif seg_type:
                summary.append((seg_type, dict(data)))
        event.message_segments = [dict(seg) for seg in arr]  # 段浅拷贝（兼容组装）
        event.text = "".join(text_parts).strip()
        event.mentions = mentions
        event.images = images
        event.image_files = image_files
        event.reply_id = reply_id
        event.is_reply_to_bot = is_reply_to_bot
        event.has_reply_to_other = has_reply_to_other
        event.has_at_others = has_at_others
        event.segments_summary = summary

    def _fill_notice(self, event: InternalEvent, raw: Dict[str, Any]) -> None:
        notice_type = str(raw.get("notice_type") or "")
        sub_type = str(raw.get("sub_type") or "")
        if notice_type == "notify" and sub_type == "poke":
            event.notice_kind = "poke"
            event.actor_id = raw.get("user_id") or raw.get("target_id")
        else:
            event.notice_kind = notice_type or sub_type
            event.actor_id = raw.get("user_id") or raw.get("operator_id")

    @staticmethod
    def _event_id(kind: str, scope: str, group_id, actor_id, message_id, timestamp) -> str:
        parts = ["kind", kind, "scope", scope]
        if group_id is not None:
            parts += ["group", str(group_id)]
        if actor_id is not None:
            parts += ["actor", str(actor_id)]
        if message_id is not None:
            parts += ["msg", str(message_id)]
        parts += ["t", str(timestamp)]
        return ":".join(parts)
