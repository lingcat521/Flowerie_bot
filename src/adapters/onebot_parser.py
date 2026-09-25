"""OneBot → InternalEvent 解析器（Phase 3，Facade/Wrapper 风格）。

只做「机械转换」，组合现有已有实现，**不复制** WS/HTTP/Token 逻辑：
- 文本/at/图片/回复提取：与 `src/core/file_parser.extract_mention_and_text` /
  `src/core/message_assembler._scan_reply_and_at` 逻辑逐行等价（同一判定规则）
- 图片取值：url 优先、file 兜底（等价于 src/adapters/onebot/transformer.extract_images；
  与 assembler._describe_images 的差异 = 仅 file 路径图不描述——不影响当前行为）
- 不含任何网络调用；不 import 冻结业务层
"""
import json
import re
import time
from typing import Any, Dict, List, Optional

from src.adapters.proto import InternalEvent, as_event_dict
from src.adapters.resource import attach_resource


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

def _notice_file(raw: Any, origin: str) -> Dict[str, Any]:
    """上传通知里的文件对象：保持原字段不变，**新增**统一 ResourceRef（Gate R）。

    Core 只读 `resource`（协议中立），因此"OneBot 用 file{id,name,size}"与
    "Milky 用 file_id/file_name/file_size"的差异被挡在 Adapter 层。
    """
    return attach_resource(dict(raw), origin) if isinstance(raw, dict) else {}


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


def _extra_fields(data: Dict[str, Any], known: tuple) -> Dict[str, Any]:
    """§5.4 前向兼容：已知字段之外的原始字段一律**保真保留**（不丢信息，也不参与语义）。"""
    return {k: v for k, v in data.items() if k not in known}


def _normalize_record_segment(data: Dict[str, Any]) -> Dict[str, Any]:
    """语音段（G3）。证据：

    - [CODE] NapCat `napcat-onebot/types/message.ts` L106-109：`record` 段的 data 就是
      `FileBaseDataSchema{file, path?, url?, name?, thumb?}`（L80-86）；
    - [DOC] Milky 规范 `common.ts` L342-346：`record{resource_id, temp_url, duration}`。
    """
    known = ("resource_id", "temp_url", "url", "file", "name", "duration", "path", "thumb")
    return {
        "resource_id": str(data.get("resource_id") or ""),
        "url": str(data.get("temp_url") or data.get("url") or ""),
        "file": str(data.get("file") or ""),
        "path": str(data.get("path") or ""),
        "name": str(data.get("name") or ""),
        "duration": data.get("duration"),
        "extra": _extra_fields(data, known),
    }


def _normalize_video_segment(data: Dict[str, Any]) -> Dict[str, Any]:
    """视频段（G3）。证据：

    - [CODE] NapCat 同文件 L112-115：`video` 段 data = `FileBaseDataSchema`（与 record 同）；
    - [DOC] Milky 规范 L347-353：`video{resource_id, temp_url, width, height, duration}`。
    """
    known = ("resource_id", "temp_url", "url", "file", "name", "duration", "path", "thumb",
             "width", "height")
    out = _normalize_record_segment(data)
    out["width"] = data.get("width")
    out["height"] = data.get("height")
    out["extra"] = _extra_fields(data, known)
    return out


def _normalize_xml_segment(data: Dict[str, Any]) -> Dict[str, Any]:
    """XML 段（G3）：**只保真保存，不解析**（任务书 §5.3）。证据：

    - [CODE] NapCat 同文件 L228-233：`xml` 段 data = `{data: string}`（XML 数据）；
    - [DOC] Milky 规范 L377-380：`xml{service_id, xml_payload}`。
    """
    return {
        "service_id": str(data.get("service_id") or ""),
        "raw_xml": str(data.get("xml_payload") or data.get("data") or data.get("xml") or ""),
        "extra": _extra_fields(data, ("service_id", "xml_payload", "data", "xml")),
    }


class OneBotEventParser:
    """OneBot raw dict → InternalEvent（转换唯一入口；raw_data 隔离保留）。"""

    def __init__(self, bot_qq: Optional[int] = None, note: str = ""):
        self._bot_qq = str(bot_qq) if bot_qq is not None else ""
        self._note = note

    def parse(self, raw: Dict[str, Any]) -> InternalEvent:
        raw = as_event_dict(raw)
        post_type = str(raw.get("post_type") or "unknown")
        # 未知 post_type **原样保留为 kind**（与 MilkyEventParser / OneBot12EventParser 一致，Gate K）：
        # 这样插件与日志能直接看出"遇到了哪种没见过的上报"，而不是只看到笼统的 unknown；
        # 缺 post_type 时 post_type 已是字符串 "unknown" -> kind 仍为 unknown（旧行为不变）。
        kind = {"message": "message", "notice": "notice",
                "request": "request", "meta_event": "lifecycle"}.get(post_type, post_type or "unknown")
        message_type = raw.get("message_type")
        group_id = raw.get("group_id")
        # message_sent = 机器人自己发出的消息：NapCat（api/msg.ts L1136）与 go-cqhttp
        # （coolq/event.go L84-87 / converter.go L70-73）都用这个 post_type [CODE]。
        # kind 原样保留（上层按 kind 分派：message_router 只把 "message" 送进回复链路），
        # 但**内容照常解析** —— 否则"自己说了什么"在归一化层直接消失。
        if kind in ("message", "message_sent"):
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
        if scene == "temp":
            # 群临时会话：**规范未定义**私聊事件里的 group_id（event/message.md L10-22 无该字段），
            # 客户端各写各的 —— 有就记录为上下文群，没有就留空，绝不推断：
            #   * go-cqhttp：sender.group_id（coolq/event.go L136-172，另带 temp_source）[CODE]
            #   * 另一些实现：顶层 group_id（见 tests/test_temp_scene.py::test_onebot_private_with_impl_group_id_becomes_context）
            ctx_gid = group_id
            if ctx_gid is None:
                sender = raw.get("sender")
                if isinstance(sender, dict):
                    ctx_gid = sender.get("group_id")
            if ctx_gid is not None:
                event.context_group_id = ctx_gid
                event.group_id = None
        event.operator_id = raw.get("operator_id") or actor_id
        event.target_id = raw.get("target_id")
        if kind == "notice" and str(raw.get("notice_type") or "") == "group_upload":
            event.notice_file = _notice_file(raw.get("file"), "onebot11")
        elif kind == "notice" and raw.get("file") is not None:
            event.notice_file = _notice_file(raw.get("file"), "onebot11")
        if kind in ("message", "message_sent"):
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
        reply_ref: Dict[str, Any] = {}
        is_reply_to_bot = has_reply_to_other = has_at_others = False
        summary: List[tuple] = []
        faces: List[Dict[str, Any]] = []
        records: List[Dict[str, Any]] = []
        videos: List[Dict[str, Any]] = []
        xmls: List[Dict[str, Any]] = []
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
                # G4：OneBot 的 reply 段**只有 id（+qq）**，没有内联段 —— 如实记录，
                # reply_segments/reply_text 保持空，不做任何填充（不是所有协议都给内联）
                reply_ref = {"id": reply_id}
                if replied_qq:
                    try:
                        reply_ref["sender_id"] = int(replied_qq)
                    except ValueError:
                        pass
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
            elif seg_type == "record":
                records.append(_normalize_record_segment(data))
                summary.append((seg_type, dict(data)))
            elif seg_type == "video":
                videos.append(_normalize_video_segment(data))
                summary.append((seg_type, dict(data)))
            elif seg_type == "xml":
                xmls.append(_normalize_xml_segment(data))
                summary.append((seg_type, dict(data)))
            elif seg_type == "markdown":
                # NapCat OB11 段词汇含 markdown（docs/client-compatibility.md §3.1）；
                # 内容是文本 → 并入 text，避免丢掉用户可见内容（与 Milky 侧对称）
                text_parts.append(str(data.get("content") or ""))
                summary.append((seg_type, dict(data)))
            elif seg_type == "miniapp":
                # NapCat OB11MessageDataType 注释：miniapp 是"json类"（小程序卡片）
                payload = _parse_json_payload(data)
                app = _json_app(payload)
                json_cards.append({
                    "app": app,
                    "is_forward_card": app == "com.tencent.multimsg",
                    "payload": payload if isinstance(payload, (dict, str)) else str(payload),
                })
                summary.append((seg_type, dict(data)))
            elif seg_type == "node":
                # 合并转发消息节点：[CODE] NapCat OB11MessageDataType.node（"合并转发消息节点"）
                forwards.append({"id": str(data.get("id") or ""),
                                 "inline": bool(data.get("content")),
                                 "title": str(data.get("nickname") or "")})
                summary.append((seg_type, dict(data)))
            elif seg_type == "onlinefile":
                # 在线文件/文件夹：[CODE] NapCat OB11MessageDataType.onlinefile
                files.append({"file_id": str(data.get("msgId") or data.get("elementId") or ""),
                              "name": str(data.get("fileName") or ""),
                              "size": data.get("fileSize"), "url": "", "path": "",
                              "sub_type": "onlinefile"})
                summary.append((seg_type, dict(data)))
            elif seg_type == "flashtransfer":
                # QQ 闪传：[CODE] NapCat OB11MessageDataType.flashtransfer
                files.append({"file_id": str(data.get("fileSetId") or ""),
                              "name": str(data.get("fileName") or ""),
                              "size": data.get("fileSize"), "url": "", "path": "",
                              "sub_type": "flash_transfer"})
                summary.append((seg_type, dict(data)))
            elif seg_type:
                summary.append((seg_type, dict(data)))
        event.message_segments = [dict(seg) for seg in arr]  # 段浅拷贝（兼容组装）
        event.text = "".join(text_parts).strip()
        event.mentions = mentions
        event.images = images
        event.image_files = image_files
        event.reply_id = reply_id
        event.reply_ref = reply_ref
        event.is_reply_to_bot = is_reply_to_bot
        event.has_reply_to_other = has_reply_to_other
        event.has_at_others = has_at_others
        event.faces = faces
        event.records = records
        event.videos = videos
        event.xmls = xmls
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
