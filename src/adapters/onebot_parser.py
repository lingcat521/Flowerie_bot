"""OneBot → InternalEvent 解析器（Phase 3，Facade/Wrapper 风格）。

只做「机械转换」，组合现有已有实现，**不复制** WS/HTTP/Token 逻辑：
- 文本/at/图片/回复提取：与 `src/core/file_parser.extract_mention_and_text` /
  `src/core/message_assembler._scan_reply_and_at` 逻辑逐行等价（同一判定规则）
- 图片取值：url 优先、file 兜底（等价于 src/sdk/onebot/transformer.extract_images；
  与 assembler._describe_images 的差异 = 仅 file 路径图不描述——不影响当前行为）
- 不含任何网络调用；不 import 冻结业务层
"""
import json
import re
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


def _json_app(payload) -> str:
    """从 JSON/Ark 卡片负载里提取 app（NapCat 与 LLBot 都靠它区分卡片种类）。

    证据：NapCat SendMsg.ts L289-297 与 LLBot milky/transform/message/incoming.ts L210-235
    都判定 app === com.tencent.multimsg 才是合并转发；docs/message-model.md §3 / §4.5。
    """
    if isinstance(payload, dict):
        app = payload.get("app")
        return str(app) if app else ""
    if isinstance(payload, str):
        m = re.search(r'"app"\s*:\s*"([^"]*)"', payload)
        return m.group(1) if m else ""
    return ""


def _parse_json_payload(data: Dict[str, Any]):
    """json 段负载：dict / JSON 字符串 / 其它（原样保留，绝不丢内容）。"""
    payload = data.get("data")
    if payload is None:
        payload = data.get("content")
    if payload is None:
        payload = data.get("text")
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except (ValueError, TypeError):
            return payload
    return payload if payload is not None else ""


def _normalize_market_face(data: Dict[str, Any]) -> Dict[str, Any]:
    """商城表情：NapCat/LLBot 字段名不同但语义一致（见 docs/message-model.md §3）。"""
    return {
        "kind": "market_face",
        "emoji_id": str(data.get("emoji_id") or ""),
        "package_id": str(data.get("emoji_package_id") or ""),
        "key": str(data.get("key") or ""),
        "summary": str(data.get("summary") or ""),
        "url": str(data.get("url") or ""),
    }


def _normalize_file_segment(data: Dict[str, Any]) -> Dict[str, Any]:
    """文件段：各家字段集不同（LLBot 有 file_id/path；NapCat FileBase 没有 file_id），逐字段兜底。"""
    name = data.get("file") or data.get("name") or data.get("file_name") or ""
    return {
        "file_id": str(data.get("file_id") or data.get("id") or ""),
        "name": str(name),
        "size": data.get("file_size") or data.get("size"),
        "url": str(data.get("url") or ""),
        "path": str(data.get("path") or ""),
    }

def _scene_of(kind: str, scope: str, raw: Dict[str, Any]) -> str:
    """会话类型归一化：group | friend | temp | stranger（跨协议同一套名字）。

    证据：
    - [DOC] OneBot 11 `event/message.md` L16：私聊 `sub_type` ∈ friend/group/other，
      其中 **group 表示群临时会话**；L52：群消息 sub_type ∈ normal/anonymous/notice。
    - [DOC] Milky 规范 `common.ts` L266-291：message_scene ∈ friend/group/temp。
    """
    if kind != "message":
        return scope or ""
    sub = str(raw.get("sub_type") or "")
    if scope == "group":
        return "group"
    if scope == "private":
        if sub == "group":
            return "temp"        # 群临时会话（QQ 群内发起）
        if sub == "friend":
            return "friend"
        if sub == "other":
            return "stranger"
    return scope or ""


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

        scene = _scene_of(kind, scope, raw)
        event = InternalEvent(
            event_id=self._event_id(kind, scope, group_id, actor_id, message_id, timestamp),
            kind=kind, scope=scope, scene=scene,
            group_id=group_id, actor_id=actor_id,
            message_id=message_id, timestamp=timestamp,
            raw_data=raw,
        )
        if scene == "temp" and group_id is not None:
            # 群临时会话：**规范未定义**私聊事件里的 group_id（event/message.md L10-22 无该字段），
            # 某些实现会额外带上 —— 有就记录为上下文群，没有就留空，绝不推断
            event.context_group_id = group_id
            event.group_id = None
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
            self._fill_request(event, raw)
        elif kind == "lifecycle":
            event.lifecycle_kind = str(raw.get("meta_event_type") or "")
            event.notice_kind = event.lifecycle_kind
        return event

    def _fill_request(self, event: InternalEvent, raw: Dict[str, Any]) -> None:
        """请求类事件（[DOC] OneBot 11 `event/request.md`）。

        - 好友请求（L10-18）：`request_type=friend`，字段 user_id / comment / flag；
        - 群请求（L31-41）：`request_type=group`，`sub_type ∈ add|invite`
          （add=加群请求，**invite=邀请登录号入群**），字段 group_id / user_id / comment / flag；
        - 规范**没有** initiator_uid / is_filtered / target_user_id（那是 Milky 的字段）→ 保持空值，
          绝不从别处挪用。
        """
        request_type = str(raw.get("request_type") or "")
        sub = str(raw.get("sub_type") or "")
        event.request_kind = request_type
        event.notice_kind = request_type          # 兼容旧行为：notice_kind 曾复用 request_kind
        event.comment = str(raw.get("comment") or "")
        event.text = event.comment[:500]
        event.request_id = str(raw.get("flag") or "")
        if request_type == "friend":
            event.request_scene = "friend"
        elif request_type == "group":
            # invite = 邀请登录号入群 ≡ Milky group_invitation（他人邀请自身入群）
            event.request_scene = "group_invitation" if sub == "invite" else "group_join"
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
        faces: List[Dict[str, Any]] = []
        pokes: List[Dict[str, Any]] = []
        files: List[Dict[str, Any]] = []
        json_cards: List[Dict[str, Any]] = []
        forwards: List[Dict[str, Any]] = []
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
                forwards.append({"id": str(data.get("id") or ""),
                                 "inline": bool(data.get("messages"))})
                summary.append(("forward", dict(data)))
            elif seg_type == "json":
                payload = _parse_json_payload(data)
                app = _json_app(payload)
                json_cards.append({
                    "app": app,
                    "is_forward_card": app == "com.tencent.multimsg",
                    "payload": payload if isinstance(payload, (dict, str)) else str(payload),
                })
                summary.append(("json", dict(data)))
            elif seg_type == "face":
                faces.append({"kind": "face", "face_id": str(data.get("id") or ""),
                              "result_id": str(data.get("resultId") or ""),
                              "chain_count": data.get("chainCount")})
                summary.append((seg_type, dict(data)))  # 旧通道保持：只做增量，不删信息
            elif seg_type == "mface":
                faces.append(_normalize_market_face(data))
                summary.append((seg_type, dict(data)))
            elif seg_type == "poke":
                pokes.append({"poke_type": str(data.get("type") or ""),
                              "poke_id": str(data.get("id") or ""), "target": None})
                summary.append((seg_type, dict(data)))
            elif seg_type == "shake":
                # LLBot 的 OneBot 实现把 face(faceType=Poke) 报成 shake{}，**不带目标**
                pokes.append({"poke_type": "shake", "poke_id": "", "target": None})
                summary.append((seg_type, dict(data)))
            elif seg_type == "file":
                files.append(_normalize_file_segment(data))
                summary.append((seg_type, dict(data)))
            elif seg_type == "markdown":
                # NapCat OB11 段词汇含 markdown（docs/client-compatibility.md §3.1）；
                # 内容是文本 → 并入 text，避免丢掉用户可见内容（与 Milky 侧对称）
                text_parts.append(str(data.get("content") or ""))
                summary.append((seg_type, dict(data)))
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
        event.faces = faces
        event.pokes = pokes
        event.files = files
        event.json_cards = json_cards
        event.forwards = forwards
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
