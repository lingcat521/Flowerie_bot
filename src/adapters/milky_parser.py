"""Milky 协议事件解析（EventEnvelope → InternalEvent）。

Milky（OneBot 进化版）事件信封：
    {"time": ..., "self_id": ..., "event_type": "message_receive", "data": {...}}

与 OneBot 的关键差异（其余字段语义一致）：
- 顶层无 post_type，用 event_type（value 见 mapping）
- data.message_scene 替代 message_type（friend / group / stranger / group_temp）
- data.peer_id 替代 group_id/user_id（friend=对方；group=群号）
- 消息段数组格式与 OneBot 相同（type/data 结构）——段扫描逻辑可复用

段归一化（Milky → InternalEvent 新字段，与 OneBot 侧**同形**，Assembler 共用）：
- light_app  → json_cards{app,is_forward_card,payload}   [DOC] 规范 common.ts L373-376 / [CODE] LightAppSegment.cs
- market_face→ faces{kind:market_face,...}                [DOC] 规范 common.ts L366-372（作者实现无此类）
- forward    → forwards{id,inline,title,preview,summary}  [DOC] L360-364 / [CODE] ForwardSegment.cs
- file       → files{file_id,name,size,url,path}          [DOC] L354-358 / [CODE] FileSegment.cs
- face       → faces{kind:face,face_id,is_large}        [CODE] V2 ISegment.cs L9 + FaceSegment.cs / [DOC] 规范 L323-326
- markdown   → text（content）                           [DOC] 规范 L381-383（两份实现均未定义该段）
- record     → records{resource_id,url,file,name,duration,extra}   [CODE] NapCat types/message.ts L106-109 / [DOC] 规范 L342-346
- video      → videos{...同上 + width,height}                       [CODE] NapCat L112-115 / [DOC] 规范 L347-353
- xml        → xmls{service_id,raw_xml,extra}（**只保真，不解析**）   [CODE] NapCat L228-233 / [DOC] 规范 L377-380
未知字段：一律进各载体的 extra（§5.4 前向兼容，不丢原始信息）。

两份内嵌实现布局不同（均为 [CODE]，勿混用）：
- `LagrangeV2/Lagrange.Milky/Entity/Segment/`：15 个文件，13 种 incoming（含 face/market_face/xml）
- `Lagrange.Core/Lagrange.Milky/Models/Segments/`：11 个文件，10 种 incoming（无 face/market_face/xml/markdown）

约束：与 OneBot 解析器输出等价（message_router 现有消费方零改动）。
"""
import json
from typing import Any, Dict, List, Optional

from src.adapters.onebot_parser import (
    _json_app,
    _normalize_file_segment,
    _normalize_market_face,
    _normalize_record_segment,
    _normalize_video_segment,
    _normalize_xml_segment,
)
from src.adapters.proto import InternalEvent, as_event_dict, to_int

# Milky 顶层事件类型 → 归一化 kind。
# ⚠️ 规范（common.ts 的 Event 联合，实测 **21 种**）里**没有 notice_receive** —— 通知类事件各有
# 独立 event_type（message_recall / group_nudge / group_file_upload …）。旧实现把它当通用通知类型，
# 结果除 message_receive 外的事件全部落到 kind=<event_type>，连 notice 分支都进不去。
_NOTICE_EVENTS = frozenset({
    "message_recall", "peer_pin_change", "friend_file_upload", "group_admin_change",
    "group_essence_message_change", "group_member_increase", "group_member_decrease",
    "group_disband", "group_name_change", "group_message_reaction", "group_mute",
    "group_whole_mute", "group_nudge", "friend_nudge", "group_file_upload",
})
# 请求类（规范 common.ts L35-58）：event_type → (粗粒度 request_kind, 细粒度 request_scene)
_REQUEST_SCENES = {
    "friend_request": ("friend", "friend"),
    "group_join_request": ("group", "group_join"),
    "group_invited_join_request": ("group", "group_invited_join"),
    # group_invitation 属**请求类**（api/group.ts L104 accept_group_invitation）—— 旧实现归 notice 是错的
    "group_invitation": ("group", "group_invitation"),
}
_REQUEST_EVENTS = frozenset(_REQUEST_SCENES)
_NUDGE_EVENTS = ("group_nudge", "friend_nudge")


def _event_kind(event_type: str) -> str:
    """event_type → 归一化 kind（未识别的一律原样返回，由上游按 unknown 忽略）。"""
    if event_type == "message_receive":
        return "message"
    if event_type in _REQUEST_EVENTS:
        return "request"
    if event_type in ("bot_offline", "lifecycle"):
        return "lifecycle"
    if event_type == "notice_receive" or event_type in _NOTICE_EVENTS:
        # notice_receive 仅为兼容旧样例（规范里不存在）
        return "notice"
    return event_type or "unknown"

_SCENE_SCOPE = {
    "friend": "private",
    "stranger": "private",
    "group": "group",
    # [DOC] 规范 common.ts L284-291 临时会话：peer_id=对端 QQ，group 为**可选** GroupEntity
    "temp": "private",
    # 旧样例别名：规范的 message_scene 枚举只有 friend / group / temp（L266-291），
    # 没有 group_temp —— 保留兼容但归一到规范值（见 _SCENE_ALIAS）
    "group_temp": "private",
}
# 规范里不存在的场景名 → 归一成规范值，避免下游见到两个名字
_SCENE_ALIAS = {"group_temp": "temp"}


def parse_milky_event(raw: Dict[str, Any], bot_qq: Optional[int] = None) -> InternalEvent:
    """Milky raw dict → InternalEvent（机械转换唯一入口；raw_data 隔离保留）。"""
    raw = as_event_dict(raw)
    ev = InternalEvent(raw_data=raw)
    ev.timestamp = raw.get("time") or raw.get("timestamp")

    event_type = str(raw.get("event_type") or "unknown")
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    ev.kind = _event_kind(event_type)
    _raw_scene = str(data.get("message_scene") or "")
    scene = _SCENE_ALIAS.get(_raw_scene, _raw_scene)
    ev.scene = scene
    ev.scope = _SCENE_SCOPE.get(scene, "")
    peer_id = data.get("peer_id")
    sender_id = data.get("sender_id")

    if ev.kind == "message":
        ev.actor_id = _int_or(sender_id)
        if scene == "friend":
            ev.group_id = None
            ev.actor_id = ev.actor_id or _int_or(peer_id)
        elif scene == "group":
            ev.group_id = _int_or(peer_id)
        elif scene == "temp":
            # 临时会话（QQ 群内发起）：私聊范围 + 来源群只做**上下文**，不冒充群会话
            # 证据：[DOC] 规范 L284-291（peer_id=对端，group=可选 GroupEntity L158-168 的 group_id）
            ev.group_id = None
            ev.actor_id = ev.actor_id or _int_or(peer_id)
            _grp = data.get("group") if isinstance(data.get("group"), dict) else {}
            _gid = _grp.get("group_id")
            if _gid is not None and str(_gid) != "":
                ev.context_group_id = _int_or(_gid)
        # 消息号：Milky 规范/实现**只有 message_seq**（无 message_id）
        # 证据：LLBot src/milky/transform/event.ts L80/L99/L118 均写 message_seq；
        #      Lagrange.Milky Models/Messages/IncomingMessageBase.cs L13 message_seq
        ev.message_id = (data.get("message_id") or data.get("msg_id")
                         or data.get("message_seq"))
        # Milky 段容器字段：segments（SDK 标准）；兼容 message（旧样例）
        _scan_segments(ev, data.get("segments", data.get("message")), bot_qq)
    elif ev.kind == "request":
        _fill_request(ev, event_type, data)
    elif ev.kind == "notice":
        if event_type in _NUDGE_EVENTS:
            # —— 戳一戳：Milky 是**独立事件**（不是消息段）→ 归一化成 OneBot notify/poke 语义 ——
            # 证据：[DOC] 规范 common.ts L127-134 group_nudge{group_id,sender_id,receiver_id,
            #       display_action,display_suffix,display_action_img_url}、L60-67 friend_nudge；
            #       [CODE] LagrangeV2 Entity/Event/GroupNudgeEvent.cs 六字段逐字对应；
            #       OneBot 侧等价物 = notice/notify/poke（路由 _handle_poke 读 actor/target/group）。
            is_group = event_type == "group_nudge"
            ev.scope = "group" if is_group else "private"
            ev.notice_kind = "poke"
            ev.actor_id = _int_or(sender_id)
            _recv = data.get("receiver_id") if is_group else data.get("user_id")
            ev.target_id = _int_or(_recv)
            if is_group:
                _g = data.get("group_id")
                ev.group_id = _int_or(_g, ev.group_id)
        elif event_type == "group_file_upload":
            # 群文件上传 → 与 OneBot notice/group_upload 同语义（路由 _handle_group_upload）
            # 证据：[DOC] 规范 common.ts L135-141 group_file_upload{group_id,user_id,file_id,file_name,file_size}；
            #       [CODE] NapCat OB11GroupUploadNoticeEvent.ts L4-9（file{id,name,size,busid}）
            ev.notice_kind = "group_upload"
            ev.actor_id = _int_or(sender_id)
            _g = data.get("group_id") or peer_id
            if _g is not None and str(_g) != "":
                ev.group_id = _int_or(_g, ev.group_id)
            ev.scope = "group"
            ev.notice_file = {"id": str(data.get("file_id") or ""),
                              "name": str(data.get("file_name") or ""),
                              "size": data.get("file_size")}
        else:
            ev.actor_id = _int_or(sender_id)
            ev.notice_kind = data.get("notice_type") or event_type
            if peer_id is not None:
                ev.target_id = _int_or(peer_id)
            if data.get("operator_id"):
                ev.operator_id = _int_or(data.get("operator_id"))
            if data.get("file"):
                ev.notice_file = dict(data["file"])
    # lifecycle / unknown 仅保留基础字段（上游按 kind 处理）

    # 稳定标识（与 OneBot 解析器同规）
    ev.event_id = _event_id(ev)
    return ev


def _fill_request(ev: InternalEvent, event_type: str, data: Dict[str, Any]) -> None:
    """请求类事件字段级映射（G2）。证据均来自 Milky 规范 [DOC]：

    - `friend_request`{initiator_id, initiator_uid, comment, via} —— 规范**没有请求标识**，
      同意/拒绝用 `initiator_uid`（api/friend.ts L22-29）→ `request_id` 保持空，**不伪造 flag**；
    - `group_join_request`{group_id, notification_seq, is_filtered, initiator_id, comment}；
    - `group_invited_join_request`{group_id, notification_seq, initiator_id, target_user_id}
      —— 群成员邀请**他人**入群（需管理员审批），与下面的 group_invitation 不同；
    - `group_invitation`{group_id, invitation_seq, initiator_id, source_group_id?}
      —— 他人邀请**自身**入群；属**请求类**（api/group.ts L104 `accept_group_invitation`），
      旧实现归入 notice 是错的（本 Gap 纠正）。
    """
    coarse, scene = _REQUEST_SCENES.get(event_type, ("", ""))
    ev.request_kind = coarse
    ev.request_scene = scene
    _init = data.get("initiator_id")
    ev.actor_id = _int_or(_init)
    _target = data.get("target_user_id")
    ev.target_id = _int_or(_target)
    ev.comment = str(data.get("comment") or "")
    ev.text = ev.comment[:500]          # 兼容既有行为：comment 曾放在 text
    ev.request_uid = str(data.get("initiator_uid") or "")
    ev.request_filtered = bool(data.get("is_filtered"))
    if data.get("group_id") is not None and str(data.get("group_id")) != "":
        ev.group_id = _int_or(data["group_id"], ev.group_id)
        ev.scope = "group"
    else:
        # [INFERENCE] 好友请求与群无关，归一化为私聊范围（规范未定义 scene 字段）
        ev.scope = "private" if scene == "friend" else ev.scope
    _rid = data.get("notification_seq")
    if _rid is None:
        _rid = data.get("invitation_seq")
    _rv = _int_or(_rid)
    ev.request_id = str(_rv) if _rv is not None else ""


def _scan_segments(ev: InternalEvent, segments: Any, bot_qq: Optional[int]) -> None:
    """Milky 消息段扫描（type/data 格式同 OneBot；解析结果与 OneBot 等价）。"""
    text_parts: List[str] = []
    bot = str(bot_qq) if bot_qq is not None else ""
# 只保留 dict 元素：段数组里混入 None/数字时不得抛异常（Gate K/§33），也不丢其它段
    ev.message_segments = ([dict(s) for s in segments if isinstance(s, dict)]
                           if isinstance(segments, list) else [])
    for seg in ev.message_segments:
        seg_type = str(seg.get("type") or "")
        data = seg.get("data") if isinstance(seg.get("data"), dict) else {}
        if seg_type == "text":
            text_parts.append(str(data.get("text") or ""))
        elif seg_type in ("mention", "at"):
            # Milky: mention/data.user_id；OneBot 兼容: at/data.qq
            qq = str(data.get("user_id") or data.get("qq") or "")
            if qq:
                ev.mentions.append(qq)
                if qq == bot:
                    ev.is_mentioned = True
                elif qq != "all":
                    ev.has_at_others = True
        elif seg_type in ("mention_all",):
            ev.mentions.append("all")   # @全体（与 OneBot at qq=all 等价：不置 is_mentioned）
        elif seg_type == "image":
            # Milky: data.temp_url（临时 URL）+ resource_id；OneBot 兼容: data.url/file
            url = str(data.get("temp_url") or data.get("url") or "")
            if url:
                ev.images.append(url)
            fp = str(data.get("file") or "").strip()
            if fp:
                fp = fp[len("file://"):] if fp.startswith("file://") else fp
                if fp:
                    ev.image_files.append(fp)
            elif data.get("resource_id") and not url:
                # 无 URL 时记录资源 id（由上层按 resource_id 后续获取）
                ev.images.append("resource:" + str(data.get("resource_id")))
        elif seg_type == "reply":
            # Milky: data.message_seq；OneBot 兼容: data.id（脏数据 -> None）
            ev.reply_id = _int_or(data.get("message_seq") or data.get("id"))
            _fill_reply(ev, data)          # G4：内联被引段进入 Reply 模型
            if data.get("segments"):
                ev.segments_summary.append((seg_type, dict(data)))
        elif seg_type == "light_app":
            # 小程序卡片 → json_cards（与 OneBot json 段同形，Assembler 共用一条通路）
            # 证据：Milky 规范 common.ts L373-376 light_app{app_name,json_payload}
            #       + 作者实现 Lagrange.Milky/Models/Segments/LightAppSegment.cs L5-10（字段集一致）
            payload = _parse_light_app_payload(data.get("json_payload"))
            app = _json_app(payload) or str(data.get("app_name") or "")
            ev.json_cards.append({
                "app": app,
                "is_forward_card": app == "com.tencent.multimsg",
                "payload": payload if isinstance(payload, (dict, str)) else str(payload),
            })
            ev.segments_summary.append((seg_type, dict(data)))
        elif seg_type == "record":
            # 语音 → records（与 OneBot 侧同形：复用 _normalize_record_segment）
            ev.records.append(_normalize_record_segment(data))
            ev.segments_summary.append((seg_type, dict(data)))
        elif seg_type == "video":
            ev.videos.append(_normalize_video_segment(data))
            ev.segments_summary.append((seg_type, dict(data)))
        elif seg_type == "xml":
            # XML：保真保存，不解析成业务模型（任务书 §5.3）
            ev.xmls.append(_normalize_xml_segment(data))
            ev.segments_summary.append((seg_type, dict(data)))
        elif seg_type == "face":
            # 表情 → faces（与 OneBot face 段同形：kind/face_id/result_id/chain_count）
            # 证据：LagrangeV2 Entity/Segment/ISegment.cs L9 "face" + FaceSegment.cs{face_id}；
            #      规范 common.ts L323-326 另有 is_large（since 1.1）——实现比规范窄，逐字段兜底
            ev.faces.append({"kind": "face", "face_id": str(data.get("face_id") or ""),
                             "result_id": "", "chain_count": None,
                             "is_large": bool(data.get("is_large"))})
            ev.segments_summary.append((seg_type, dict(data)))
        elif seg_type == "markdown":
            # Markdown 消息段（规范 common.ts L381-383 markdown{content}）：内容即文本 → 并入 text
            # 注意：两份内嵌实现（V2 Entity/Segment 与 Core Models/Segments）**都没有** markdown 段
            text_parts.append(str(data.get("content") or ""))
            ev.segments_summary.append((seg_type, dict(data)))
        elif seg_type == "market_face":
            # 商城表情 → faces（复用 OneBot 归一化函数，保证键名同形）
            # 证据：LagrangeV2 Entity/Segment/ISegment.cs L16 "market_face" + MarketFaceSegment.cs{url}（仅 url）；
            #      规范 common.ts L366-372 另有 emoji_package_id/emoji_id/key/summary —— 实现比规范窄
            ev.faces.append(_normalize_market_face(data))
            ev.segments_summary.append((seg_type, dict(data)))
        elif seg_type == "forward":
            # 合并转发 → forwards（OneBot 同形 id/inline + 附加 Milky 独有 title/preview/summary）
            # 证据：规范 common.ts L360-364 + 作者实现 ForwardSegment.cs L7-14
            preview = data.get("preview")
            ev.forwards.append({
                "id": str(data.get("forward_id") or data.get("id") or ""),
                "inline": bool(data.get("messages")),
                "title": str(data.get("title") or ""),
                "preview": list(preview) if isinstance(preview, list) else [],
                "summary": str(data.get("summary") or ""),
            })
            ev.segments_summary.append((seg_type, dict(data)))
        elif seg_type == "file":
            # 文件段 → files（复用 OneBot 归一化：file_id/file_name/file_size 兜底一致）
            # 证据：规范 common.ts L354-358 + 作者实现 FileSegment.cs L5-11
            ev.files.append(_normalize_file_segment(data))
            ev.segments_summary.append((seg_type, dict(data)))
        elif seg_type:
            ev.segments_summary.append((seg_type, dict(data)))
    ev.text = "".join(text_parts).strip()


def _inline_text(segments: List[dict], limit: int = 200) -> str:
    """内联被引段的纯文本摘要（只取 text 段，不递归展开、不二次解析）。"""
    parts = []
    for seg in segments or []:
        if str(seg.get("type") or "") != "text":
            continue
        d = seg.get("data") if isinstance(seg.get("data"), dict) else {}
        parts.append(str(d.get("text") or ""))
    return "".join(parts).strip()[:limit]


def _fill_reply(ev: InternalEvent, data: Dict[str, Any]) -> None:
    """引用段（G4）：message reference + **内联被引段**。

    证据：[DOC] Milky 规范 `common.ts` L327-333
    `reply{message_seq, sender_id, sender_name?, time, segments[]}` —— 被引消息的**完整段数组内联**；
    对比 OneBot 只给 `id`（`event/message.md` / NapCat `types/message.ts` 的 `reply{id,qq?}`）。
    任务书 §6.2：**必须同时保留 message_seq**（引用目标的稳定标识），不能因为拿到内联内容就丢掉它。
    """
    ev.reply_ref["id"] = ev.reply_id
    for key, cast in (("sender_id", int), ("time", int)):
        val = data.get(key)
        if val is not None and str(val) != "":
            try:
                ev.reply_ref[key] = cast(val)
            except (TypeError, ValueError):
                pass
    if data.get("sender_name"):
        ev.reply_ref["sender_name"] = str(data["sender_name"])
    segs = data.get("segments")
    if isinstance(segs, list) and segs:
        ev.reply_segments = [dict(s) for s in segs if isinstance(s, dict)]
        ev.reply_text = _inline_text(ev.reply_segments)


def _parse_light_app_payload(raw: Any):
    """light_app.json_payload：JSON 字符串优先解析为 dict，失败原样保留（绝不丢内容）。"""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return raw
    return raw if raw is not None else ""


def _int_or(value: Any, default: Any = None) -> Any:
    """容错转换：能转成 int 就用它，否则用 default（脏数据不打断解析）。"""
    v = to_int(value)
    return v if v is not None else default


def _event_id(ev: InternalEvent) -> str:
    g = ev.group_id if ev.group_id is not None else ""
    a = ev.actor_id if ev.actor_id is not None else ""
    m = ev.message_id if ev.message_id is not None else ""
    t = ev.timestamp if ev.timestamp is not None else ""
    return f"{ev.kind}:{ev.scope}:{g}:{a}:{m}:{t}"


class MilkyEventParser:
    """Milky raw dict → InternalEvent（EventParser 契约实现）。"""

    def __init__(self, bot_qq: Optional[int] = None, note: str = ""):
        self._bot_qq = bot_qq
        self._note = note

    def parse(self, raw: Dict[str, Any]) -> InternalEvent:
        return parse_milky_event(raw, self._bot_qq)
