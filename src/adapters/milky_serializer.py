"""Milky 出站序列化：内部段数组 → Milky `OutgoingSegment` 数组。

任务书 §十（Milky Adapter + Client Profile）/§十四（两个方向）/§十八（Round-trip）。

证据：
- `[DOC]` Milky 规范 `protocol/src/ir/common.ts L393-445` 的 `OutgoingSegment` 联合体：
  text{text} / mention{user_id} / mention_all{} / face{face_id,is_large=false} / reply{message_seq} /
  image{uri,sub_type∈{normal,sticker},summary?} / record{uri} / video{uri,thumb_uri?} /
  forward{messages:[OutgoingForwardedMessage],title?,preview?(1..4),summary?,prompt?} / light_app{json_payload}；
  `uri` 支持 `file://` / `http(s)://` / `base64://` 三种写法。
- `[CODE]` LLBot `src/milky/transform/message/outgoing.ts`：
  `mention` / `mention_all` **只在群聊生效**（`&& isGroup`，私聊下不产出元素）；
  `reply` 用 `message_seq` 且要求能查到被引消息（查不到直接 throw `被回复的消息未找到`）；
  `image` 先按 milky uri 取字节再上传。

与 OneBot 序列化器的差别（同一套 note 口径）：Milky 的段名与字段**完全不同**
（`mention` vs `at`、`face_id` vs `id`、`message_seq` vs `id`、`uri` vs `file`），
所以两侧各自一个模块，但共用"未知段原样传递 + 每次改动记 note"的规则。
"""
from typing import Any, Dict, List, Tuple

from src.adapters.client_profile import ClientProfile, MILKY_SPEC

NOTE_INVALID = "invalid_segment"
NOTE_UNKNOWN_SEGMENT = "unknown_segment_passthrough"
NOTE_UNSUPPORTED_SEGMENT = "segment_unsupported_by_profile"
NOTE_DROPPED_FIELD = "dropped_field"
NOTE_DROPPED_SEGMENT = "segment_dropped_by_client_rule"

#: 规范里存在的出站段（未知的一律原样传递 + note）
MILKY_OUTGOING_TYPES = ("text", "mention", "mention_all", "face", "reply", "image",
                        "record", "video", "forward", "light_app")


def _note(kind: str, reason: str, **extra: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {"type": kind, "reason": reason}
    out.update(extra)
    return out


def serialize_milky_segments(segments: Any, *, profile: ClientProfile = MILKY_SPEC,
                             is_group: bool = True) -> Tuple[List[dict], List[dict]]:
    """内部段数组 → (Milky 出站段数组, notes)。

    `is_group=False` 时按 LLBot 的实测规则处理 `mention`（私聊下客户端不产出元素）——
    这种情况下我们**明确丢弃并记 note**，而不是发出去等客户端静默忽略。
    """
    wire: List[dict] = []
    notes: List[dict] = []
    if not isinstance(segments, (list, tuple)):
        return [], [_note(str(segments), NOTE_INVALID, detail="段数组必须是 list")]

    for seg in segments:
        if not isinstance(seg, dict):
            notes.append(_note(str(seg), NOTE_INVALID, detail="段必须是对象"))
            continue
        seg_type = str(seg.get("type") or "")
        if not seg_type:
            notes.append(_note("(no type)", NOTE_INVALID, detail="段缺少 type"))
            continue
        data = seg.get("data")
        data = dict(data) if isinstance(data, dict) else {}
        state = profile.state(seg_type) if seg_type in profile.capabilities else None

        if seg_type == "text":
            wire.append({"type": "text", "data": {"text": str(data.get("text") or "")}})
            continue

        if seg_type in ("mention", "mention_all"):
            if not is_group:
                notes.append(_note(seg_type, NOTE_DROPPED_SEGMENT,
                                   detail="LLBot：私聊下 mention/mention_all 不产出元素（[CODE] outgoing.ts）"))
                continue
            if seg_type == "mention_all":
                wire.append({"type": "mention_all", "data": {}})
            else:
                uid = data.get("user_id")
                if uid is None:
                    notes.append(_note("mention", NOTE_INVALID, detail="mention 需要 user_id"))
                    continue
                wire.append({"type": "mention", "data": {"user_id": uid}})
            continue

        if seg_type == "face":
            fid = data.get("face_id", data.get("id"))
            if fid is None:
                notes.append(_note("face", NOTE_INVALID, detail="face 需要 face_id"))
                continue
            out: Dict[str, Any] = {"face_id": str(fid)}
            if data.get("is_large") is not None:
                out["is_large"] = bool(data["is_large"])
            elif "is_large" in (profile.quirk("face_fields") or []):
                out["is_large"] = False
            wire.append({"type": "face", "data": out})
            continue

        if seg_type == "reply":
            seq = data.get("message_seq", data.get("id"))
            if seq is None:
                notes.append(_note("reply", NOTE_INVALID, detail="reply 需要 message_seq"))
                continue
            wire.append({"type": "reply", "data": {"message_seq": seq}})
            if "message_seq" not in data:
                notes.append(_note("reply", NOTE_DROPPED_FIELD, field="id→message_seq",
                                   detail="Milky 用 message_seq（与 OneBot 的 id 不同命名空间）"))
            continue

        if seg_type in ("image", "record", "video"):
            # 出站规范要 uri（file:// / http(s):// / base64://）；入站段给的是 resource_id/temp_url。
            # 因此：uri/file/url 直接用；temp_url 是**临时**地址（会过期）→ 用并记 note；
            # 只有 resource_id 而没有可发送地址时**不能**编一个 uri 出来 → 丢段 + 说明。
            uri = data.get("uri") or data.get("file") or data.get("url")
            fallback = None
            if not uri and data.get("temp_url"):
                uri, fallback = data["temp_url"], "temp_url（临时地址，可能已过期）"
            if not uri:
                notes.append(_note(seg_type, NOTE_INVALID,
                                   detail="入站段只有 resource_id，出站需要 uri（二者不可互推）"))
                continue
            out = {"uri": str(uri)}
            if fallback:
                notes.append(_note(seg_type, NOTE_DROPPED_FIELD, field="resource_id→temp_url",
                                   detail=fallback))
            if seg_type == "image":
                sub = data.get("sub_type", data.get("subType"))
                if sub is not None:
                    out["sub_type"] = str(sub)
                if data.get("summary") is not None:
                    out["summary"] = str(data["summary"])
            if seg_type == "video" and data.get("thumb_uri") is not None:
                out["thumb_uri"] = str(data["thumb_uri"])
            wire.append({"type": seg_type, "data": out})
            continue

        if seg_type == "forward":
            messages = data.get("messages")
            if not isinstance(messages, list) or not messages:
                # 入站 forward 只有 forward_id/title/preview/summary；出站要构造 messages。
                # **不能**由 forward_id 反推内容（那要再走一次接口）→ 明确不往返 + 说明原因。
                notes.append(_note("forward", NOTE_INVALID,
                                   detail="入站 forward 只有 forward_id，出站需要 messages[]；"
                                          "不可互推（需另走 get_forwarded_messages 才能构造）"))
                continue
            out = {"messages": messages}
            for key in ("title", "preview", "summary", "prompt"):
                if data.get(key) is not None:
                    out[key] = data[key]
            wire.append({"type": "forward", "data": out})
            continue

        # 未在规范出站联合体里出现、或该客户端未验证：原样传递 + note（不伪造支持、不丢内容）
        wire.append({"type": seg_type, "data": data})
        notes.append(_note(seg_type, NOTE_UNKNOWN_SEGMENT if state is None
                           else NOTE_UNSUPPORTED_SEGMENT,
                           profile_state=state or "UNREGISTERED"))
    return wire, notes
