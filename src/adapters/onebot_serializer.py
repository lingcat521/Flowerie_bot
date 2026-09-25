"""OneBot 11 出站序列化：内部段数组 → **客户端真正接受**的 wire 段数组。

任务书 §十四（两个方向都要研究）/§十八（Round-trip）/§九（差异集中在 ClientProfile）。

为什么需要它：今天 `Sender.send_msg_raw()` 把调用方给的段数组**原样**发给协议端，
于是"某个客户端不接受的字段"只能等协议端报错或静默忽略。这里把每个段的字段收敛到
`ClientProfile` 里**有证据**接受的那一组，并把每一次改动记成 note（**不静默改语义**）。

发送侧证据（全部 [CODE]，见 docs/reverse-engineering/onebot11/go-cqhttp.md）：
- `coolq/cqcode.go L608-900 ConvertElement()`：text/at/image/reply/forward/poke/tts/face/share/music/
  dice/rps/xml/json 各分支读取的字段名；
- `L434-466 ConvertElements()`：未知段/转换失败 → `IgnoreInvalidCQCode=false` 时**回退成字面 CQ 文本**；
  reply 会被**提到最前**，且一条消息只接受一个 reply；
- `L467-530 reply()`：`id` 走客户端自己的 DB（global id），自定义回复用 `text` + `user_id/qq` + 可选 `time/seq`；
- `L532-550 voice()`：只读 `file`（本地文件），**发送侧没有 url**；
- `L883-935 makeImageOrVideoElem()`：`file` 支持 http / file:// / base64 / hex；`c`、`cache` 是客户端扩展。
"""
from typing import Any, Dict, List, Tuple

from src.adapters.client_profile import ONEBOT11_SPEC, ClientProfile

#: note 里出现的固定原因串（测试直接断言这些，避免文案漂移）
NOTE_UNKNOWN_SEGMENT = "unknown_segment_passthrough"
NOTE_DROPPED_FIELD = "dropped_field"
NOTE_INVALID = "invalid_segment"
NOTE_REPLY_HOISTED = "reply_hoisted_first"
NOTE_REPLY_EXTRA = "extra_reply_dropped"
NOTE_UNSUPPORTED_SEGMENT = "segment_unsupported_by_profile"
NOTE_VALUE_OUT_OF_RANGE = "value_out_of_range"


def _note(kind: str, reason: str, **extra: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {"type": kind, "reason": reason}
    out.update(extra)
    return out


def _as_int(value: Any):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def serialize_segments(segments: Any, *, profile: ClientProfile = ONEBOT11_SPEC
                       ) -> Tuple[List[dict], List[dict]]:
    """内部段数组 → (wire 段数组, notes)。

    - 未知段类型**原样传递**并记 note（不丢数据；是否被接受由客户端决定，我们不猜）；
    - profile 未验证支持的段同样原样传递 + note（**不伪造支持**，也不偷偷删掉用户内容）；
    - 只有"证据表明客户端会拒绝/误解"的字段才被移除，并且一定记 note。
    """
    wire: List[dict] = []
    notes: List[dict] = []
    replies: List[dict] = []
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

        if seg_type == "at":
            # go-cqhttp：qq 缺失时回退读 target；qq=="all" → AtAll（cqcode.go L563-580）
            qq = data.get("qq")
            if qq is None:
                for fallback in (profile.quirk("at_fields") or []):
                    if fallback not in ("qq", "name") and data.get(fallback) is not None:
                        qq = data[fallback]
                        notes.append(_note("at", NOTE_DROPPED_FIELD, field="%s→qq" % fallback,
                                           detail="客户端按 fallback 字段读取"))
                        break
            if qq is None:
                notes.append(_note("at", NOTE_INVALID, detail="at 段缺少 qq"))
                continue
            out = {"qq": str(qq)}
            if "name" in data:
                out["name"] = str(data["name"])
            wire.append({"type": "at", "data": out})
            continue

        if seg_type in ("image", "record", "video"):
            src = data.get("file")
            if not src and data.get("url"):
                # go-cqhttp 的 makeImageOrVideoElem 只读 file；但 file 允许是 http URL
                src, url_as_file = data.get("url"), True
            else:
                url_as_file = False
            if not src:
                notes.append(_note(seg_type, NOTE_INVALID, detail="缺少 file/url"))
                continue
            out = {"file": str(src)}
            if url_as_file:
                notes.append(_note(seg_type, NOTE_DROPPED_FIELD, field="url→file",
                                   detail="客户端发送侧只读 file；url 已作为 file 传入"))
            allowed = profile.quirk(seg_type + "_send_fields")
            if isinstance(allowed, (list, tuple)):
                for key in ("url", "path", "name", "cache", "c", "thumb"):
                    if key in data and key not in allowed:
                        notes.append(_note(seg_type, NOTE_DROPPED_FIELD, field=key,
                                           detail="该客户端发送侧不读此字段"))
                    elif key in data:
                        out[key] = data[key]
            if seg_type == "image":
                tp = data.get("type")
                values = profile.quirk("image_type_values")
                if tp:
                    if isinstance(values, (list, tuple)) and tp in values:
                        out["type"] = tp
                        if tp == "show" and data.get("id") is not None:
                            out["id"] = str(data["id"])
                    else:
                        notes.append(_note("image", NOTE_DROPPED_FIELD, field="type",
                                           detail="该客户端未验证支持此 type"))
                if "subType" in data and "subType" not in out:
                    out["subType"] = data["subType"]
            wire.append({"type": seg_type, "data": out})
            continue

        if seg_type == "reply":
            rid = _as_int(data.get("id"))
            if rid is None:
                notes.append(_note("reply", NOTE_INVALID, detail="reply 需要数字 id"))
                continue
            if len(replies) >= int(profile.quirk("reply_max_count", 1) or 1):
                notes.append(_note("reply", NOTE_REPLY_EXTRA, detail="一条消息只保留第一个 reply"))
                continue
            out = {"id": str(rid)}
            for key in profile.quirk("reply_custom_fields", []) or []:
                if key != "id" and key in data:
                    out[key] = data[key]
            replies.append({"type": "reply", "data": out})
            continue

        if seg_type == "file":
            fields = profile.quirk("file_send_fields")
            if isinstance(fields, (list, tuple)) and fields:
                out = {k: str(data[k]) for k in fields if k in data}
                if "path" not in out and "name" not in out:
                    notes.append(_note("file", NOTE_INVALID,
                                       detail="该客户端需要 path/name（file_id 命名空间不同）"))
                    continue
                for key in data:
                    if key not in out:
                        notes.append(_note("file", NOTE_DROPPED_FIELD, field=key,
                                           detail="该客户端发送侧不读此字段"))
                wire.append({"type": "file", "data": out})
            else:
                wire.append({"type": "file", "data": data})
                notes.append(_note("file", NOTE_UNSUPPORTED_SEGMENT,
                                   detail="该客户端未验证 file 段字段，原样传递"))
            continue

        if seg_type in ("json", "xml"):
            if not data.get("data"):
                notes.append(_note(seg_type, NOTE_INVALID, detail="缺少 data"))
                continue
            out = {"data": str(data["data"])}
            if "resid" in data:
                if "resid" in (profile.quirk(seg_type + "_fields") or []):
                    out["resid"] = str(data["resid"])
                else:
                    notes.append(_note(seg_type, NOTE_DROPPED_FIELD, field="resid",
                                       detail="该客户端未验证支持 resid"))
            wire.append({"type": seg_type, "data": out})
            continue

        if seg_type == "face":
            fid = _as_int(data.get("id"))
            if fid is None:
                notes.append(_note("face", NOTE_INVALID, detail="face 需要数字 id"))
                continue
            out = {"id": str(fid)}
            if data.get("type") and profile.quirk("face_type_values"):
                out["type"] = data["type"]
            elif data.get("type"):
                notes.append(_note("face", NOTE_DROPPED_FIELD, field="type",
                                   detail="该客户端未验证 face.type"))
            wire.append({"type": "face", "data": out})
            continue

        if seg_type in ("dice", "rps"):
            value = _as_int(data.get("value"))
            lo_hi = profile.quirk(seg_type + "_value_range")
            if value is None or not isinstance(lo_hi, (list, tuple)) or not (lo_hi[0] <= value <= lo_hi[1]):
                notes.append(_note(seg_type, NOTE_VALUE_OUT_OF_RANGE,
                                   detail="客户端会拒绝该取值", value=data.get("value")))
                continue
            wire.append({"type": seg_type, "data": {"value": str(value)}})
            continue

        if seg_type == "poke":
            fields = profile.quirk("poke_segment_fields")
            if isinstance(fields, (list, tuple)) and fields:
                out = {k: data[k] for k in fields if k in data}
                if not out:
                    notes.append(_note("poke", NOTE_INVALID,
                                       detail="poke 段缺少该客户端需要的字段"))
                    continue
                wire.append({"type": "poke", "data": out})
            else:
                wire.append({"type": "poke", "data": data})
                notes.append(_note("poke", NOTE_UNSUPPORTED_SEGMENT,
                                   detail="该客户端未验证 poke 段字段，原样传递"))
            continue

        # 其余：规范/该客户端未验证 —— 原样传递 + note（不伪造支持，也不丢用户内容）
        wire.append({"type": seg_type, "data": data})
        if state in ("UNSUPPORTED", "UNKNOWN", None):
            # 原样传递：客户端自己的兜底行为（go-cqhttp: IgnoreInvalidCQCode=false 时
            # 回退成字面 CQ 文本）由它决定 —— 我们不在这里复刻客户端转义规则
            fallback = profile.quirk("unknown_segment_fallback")
            notes.append(_note(seg_type, NOTE_UNKNOWN_SEGMENT if state is None
                               else NOTE_UNSUPPORTED_SEGMENT,
                               profile_state=state or "UNREGISTERED",
                               detail=("客户端回退行为: %s" % fallback) if fallback else ""))

    if replies:
        wire = replies + wire
        notes.append(_note("reply", NOTE_REPLY_HOISTED, detail="reply 必须在消息最前"))
    return wire, notes


def build_message_payload(segments: Any, *, profile: ClientProfile = ONEBOT11_SPEC
                          ) -> Tuple[List[dict], List[dict]]:
    """发送用：段数组（含 reply 前置）→ wire 段数组 + notes。"""
    return serialize_segments(segments, profile=profile)
