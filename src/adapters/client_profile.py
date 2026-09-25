"""客户端档案（ClientProfile）：**只描述已验证事实**的客户端差异容器。

任务书 `/storage/emulated/0/协议.txt` §九/§十/§十二/§十一：
- 不为每个客户端复制一整套 Adapter；差异集中在 ClientProfile + Normalization；
- Profile 只能写**源码/文档/实机验证过**的事实，禁止用它伪造支持；
- Core / Services / SDK / Plugins **不得** import 客户端名 —— 本模块属于 Adapter 层，
  上层只通过 `capability_state()` 这类中性查询使用，不出现 `if client == "xxx"`。

四态词汇与 Capability Matrix 一致：SUPPORTED / PARTIAL / UNSUPPORTED / UNKNOWN。
证据等级：`[CODE]` 源码 / `[DOC]` 规范 / `[MVP]` 本仓库实现 / `[INFERENCE]` 推断 / `[UNKNOWN]` 无证据
（`[INFERENCE]` 不能单独作为"支持"的依据，只能用于 PARTIAL/UNKNOWN 的说明）。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

SUPPORTED = "SUPPORTED"
PARTIAL = "PARTIAL"
UNSUPPORTED = "UNSUPPORTED"
UNKNOWN = "UNKNOWN"
STATES = (SUPPORTED, PARTIAL, UNSUPPORTED, UNKNOWN)


@dataclass(frozen=True)
class ClientProfile:
    """一个客户端（或规范基线）的已验证行为集合。"""

    protocol: str                     # onebot11 | milky
    client: str                       # go-cqhttp | napcat | llbot | lagrange | spec ...
    version: str = ""                 # 核对过的版本 / 提交
    evidence: str = "[UNKNOWN]"       # 本档案整体的证据等级
    source: str = ""                  # 证据位置（仓库 + 文件:行）
    capabilities: Mapping[str, str] = field(default_factory=dict)
    #: 只放**有证据**的行为差异；键名是中性事实名，不是客户端名
    quirks: Mapping[str, Any] = field(default_factory=dict)

    def state(self, capability: str) -> str:
        """能力状态；未登记 = UNKNOWN（**不猜**）。"""
        value = self.capabilities.get(capability)
        return value if value in STATES else UNKNOWN

    def supports(self, capability: str) -> bool:
        return self.state(capability) == SUPPORTED

    def quirk(self, name: str, default: Any = None) -> Any:
        return self.quirks.get(name, default)


#: 规范基线（OneBot 11 spec；只有规范条文支持的能力）
ONEBOT11_SPEC = ClientProfile(
    protocol="onebot11", client="spec", version="botuniverse/onebot-11 d4456ee",
    evidence="[DOC]", source="~/proto_src/OneBot11-spec/（message/segment.md、api/public.md）",
    capabilities={
        # 逐节核对 ~/proto_src/OneBot11-spec/message/segment.md 的标题清单后填的：
        "text": SUPPORTED, "face": SUPPORTED, "image": SUPPORTED, "record": SUPPORTED,
        "video": SUPPORTED, "at": SUPPORTED, "rps": SUPPORTED, "dice": SUPPORTED,
        "shake": SUPPORTED, "poke": SUPPORTED, "anonymous": SUPPORTED,
        "share": SUPPORTED, "contact": SUPPORTED, "location": SUPPORTED,
        "music": SUPPORTED, "reply": SUPPORTED, "forward_segment": PARTIAL,
        "json": SUPPORTED, "xml": SUPPORTED,
        # 规范里**确实不存在**的：明确 UNSUPPORTED（不是 UNKNOWN —— 不能把不存在写成"没查"）
        "mface": UNSUPPORTED, "markdown": UNSUPPORTED, "file": UNSUPPORTED,
    },
    quirks={
        "response_status_values": ["ok", "async", "failed"],
        "segment_doc_sections": ["纯文本", "QQ 表情", "图片", "语音", "短视频", "@某人",
                                 "猜拳魔法表情", "掷骰子魔法表情", "窗口抖动（戳一戳）",
                                 "戳一戳", "匿名发消息", "链接分享", "推荐好友", "推荐群",
                                 "位置", "音乐分享", "音乐自定义分享", "回复", "合并转发",
                                 "合并转发节点", "合并转发自定义节点", "XML 消息", "JSON 消息"],
        "forward_is_receive_only": True,     # 合并转发（收）；发送用 节点/自定义节点
    },
)

#: go-cqhttp：本仓库已逐行核对（见 docs/reverse-engineering/onebot11/go-cqhttp.md）
GO_CQHTTP = ClientProfile(
    protocol="onebot11", client="go-cqhttp", version="a5923f1（archived）",
    evidence="[CODE]", source="~/proto_src/go-cqhttp coolq/cqcode.go L404-900（发送侧）/ L62-280（上报侧）",
    capabilities={
        "text": SUPPORTED, "at": SUPPORTED, "image": SUPPORTED, "reply": SUPPORTED,
        "face": SUPPORTED, "record": SUPPORTED, "video": SUPPORTED, "json": SUPPORTED,
        "xml": SUPPORTED, "share": SUPPORTED, "music": SUPPORTED,
        # go-cqhttp 有自己的 poke 段（字段是 qq，与 NapCat 的 {type,id} 不同）
        "poke": SUPPORTED,
        # 发送侧没有 mface 分支；未知段会按 ~IgnoreInvalidCQCode~ 回退成字面 CQ 文本
        "mface": UNSUPPORTED,
        "dice": SUPPORTED, "rps": SUPPORTED,
        # 发送侧 case 表（cqcode.go L608-880）里没有 mface / markdown / cardimage(有)：
        "file": SUPPORTED, "cardimage": SUPPORTED,
        "markdown": UNSUPPORTED,                    # 无 case → 落到 default 的 unsupported
        "forward_segment": PARTIAL,                 # 只能按 id 下载已存在的转发，不能自造
    },
    quirks={
        # 发送侧字段（[CODE] cqcode.go L608-880 / L883-1010）
        "image_file_schemes": ["http", "file", "base64", "base16384", "hex", "path"],
        "image_type_values": ["flash", "show"],     # show 需要 id（40000..40005 区间外会被夹到 40000）
        "record_send_fields": ["file"],             # 上报侧才有 url；发送侧只吃 file（voice() L532-550）
        "video_send_fields": ["file", "cover", "cache"],
        "file_send_fields": ["path", "name", "size", "busid"],
        "at_fields": ["qq", "target", "name"],
        "at_all_value": "all",
        "cardimage_fields": ["source", "icon", "brief", "minwidth", "maxwidth", "minheight", "maxheight", "file"],
        "reply_id_required": True,                  # reply 必须含 id 或 text
        "reply_max_count": 1,                       # 第二个 reply 只记 warning 并丢弃
        "reply_hoisted_first": True,
        "reply_custom_fields": ["text", "user_id", "qq", "time", "seq"],
        "poke_segment_fields": ["qq"],
        "xml_fields": ["data", "resid"],            # resid 会被 ParseInt
        "json_fields": ["data", "resid"],
        "dice_value_fields": ["value"],
        "rps_value_fields": ["value"],
        "dice_value_range": [0, 6],
        "rps_value_range": [0, 2],
        "face_extra_fields": ["type"],
        "unknown_segment_fallback": "literal_cq_text",   # IgnoreInvalidCQCode=false 时
        "text_url_split": True,                     # base.SplitURL 打开时 URL 会被拆成单独 text 段
        "message_accepts": ["string_cq", "array"],
        "post_format": ["string", "array"],
        "reply_id_namespace": "db_global_id",       # 与上报的 message_seq（客户端 seq）不同
        "report_message_seq_field": "message_seq",
        "temp_source_group_field": "sender.group_id",
    },
)

#: NapCat：本仓库 Phase 1 已逆向（client-compatibility.md §1-§3 / protocol-reverse-engineering.md §3）
NAPCAT = ClientProfile(
    protocol="onebot11", client="napcat", version="0b4cfe6",
    evidence="[CODE]", source="~/proto_src/NapCatQQ packages/napcat-onebot/（详见 docs/client-compatibility.md §1-§3）",
    capabilities={
        "text": SUPPORTED, "at": SUPPORTED, "image": SUPPORTED, "reply": SUPPORTED,
        "face": SUPPORTED, "mface": SUPPORTED,          # NapCat 有真正的 mface 段
        "record": SUPPORTED, "video": SUPPORTED, "json": SUPPORTED, "xml": SUPPORTED,
        "file": SUPPORTED,                             # 文件段（file_id 命名空间）
        "poke": SUPPORTED,                             # poke{type,id}（另见 GreyTip=8）
        "forward_segment": SUPPORTED,
        # 以下由 types/message.ts 的段枚举 + schema 逐条核对（[CODE] L3-27 / L30-340）
        "dice": SUPPORTED, "rps": SUPPORTED,           # data 字段是 result（不是 value）
        "music": SUPPORTED,
        "markdown": SUPPORTED, "miniapp": SUPPORTED,
        "contact": SUPPORTED, "location": SUPPORTED,
        "share": UNSUPPORTED,                          # 段枚举里没有 share
        "onlinefile": UNKNOWN, "flashtransfer": UNKNOWN,
    },
    quirks={
        "poke_segment_fields": ["type", "id"],
        "has_mface_segment": True,
        "file_id_namespace": "client_file_id",
        # 取值字段名与 go-cqhttp 不同（[CODE] types/message.ts L186-207）
        "dice_value_fields": ["result"],
        "rps_value_fields": ["result"],
        # 没有范围证据 → **不登记** range（序列化器因此原样传递，不做校验）
        "face_extra_fields": ["resultId", "chainCount"],
    },
)

#: LLBot：OneBot 11 + Milky 双实现（protocol-reverse-engineering.md §4）
LLBOT = ClientProfile(
    protocol="onebot11", client="llbot", version="9f374f6",
    evidence="[CODE]", source="~/proto_src/LLBot src/onebot11/transform/message/incoming.ts（327 行）",
    capabilities={
        "text": SUPPORTED, "at": SUPPORTED, "image": SUPPORTED, "reply": SUPPORTED,
        "face": SUPPORTED, "file": SUPPORTED,
        # 上报侧有 shake（戳一戳段）—— 与 NapCat 的 poke / go-cqhttp 的 poke 都不完全一样
        "poke": SUPPORTED,
        "record": UNKNOWN, "video": UNKNOWN, "json": SUPPORTED, "xml": UNKNOWN,
        "mface": UNKNOWN, "dice": UNKNOWN, "rps": UNKNOWN,
    },
    quirks={"poke_segment_type": "shake"},
)

#: Lagrange：OneBot 11 实现源码不可得（source-acquisition.md C4）→ 只有官方文档 [DOC]，且页面自称过时
LAGRANGE_ONEBOT = ClientProfile(
    protocol="onebot11", client="lagrange", version="Lagrange.Doc 98e96e5（文档）",
    evidence="[DOC]", source="~/proto_src/Lagrange.Doc docs/v1/Lagrange.OneBot/（页面标注已过时）",
    capabilities={
        # 文档只给了"参考 OneBot V11 规范"+"并非所有 API 都已实现"，且给出了 Extend 段的字段表
        "text": UNKNOWN, "image": UNKNOWN, "face": UNKNOWN, "at": UNKNOWN, "reply": UNKNOWN,
        "file": SUPPORTED,      # Extend/Segment 文档有 File 字段表
        "forward_segment": SUPPORTED,   # Extend/Segment 文档有 Node 字段表
    },
    quirks={"onebot_impl_source": "SOURCE_UNAVAILABLE", "doc_outdated": True},
)

PROFILES: Dict[Tuple[str, str], ClientProfile] = {
    (p.protocol, p.client): p
    for p in (ONEBOT11_SPEC, GO_CQHTTP, NAPCAT, LLBOT, LAGRANGE_ONEBOT)
}


#: 渲染矩阵用的能力顺序（与 docs/client-compatibility.md §4.2 一致；加能力要同步文档）
#: markdown 行内代码用的反引号（写成常量，避免生成器里出现裸反引号）
TICK = chr(96)

#: 渲染矩阵用的能力顺序（与 docs/client-compatibility.md §4.2 一致；加能力要同步文档）
MATRIX_CAPABILITIES = (
    "text", "face", "image", "record", "video", "at", "reply", "json", "xml",
    "share", "music", "poke", "dice", "rps", "mface", "file", "markdown",
    "forward_segment",
)


def render_matrix(protocol: str = "onebot11") -> str:
    """把档案渲染成 markdown 表格（文档与代码同源，防止文档漂移）。"""
    rows = [c for (p, c) in sorted(PROFILES) if p == protocol]
    head = "| 能力 | " + " | ".join(rows) + " |"
    sep = "| :--- | " + " | ".join(":---" for _ in rows) + " |"
    lines = [head, sep]
    for cap in MATRIX_CAPABILITIES:
        cells = [PROFILES[(protocol, c)].state(cap) for c in rows]
        lines.append("| %s%s%s | %s |" % (TICK, cap, TICK, " | ".join(cells)))
    return "\n".join(lines)


def profile_for(protocol: str, client: str = "spec") -> ClientProfile:
    """取档案；没有档案 → 规范基线（并保持 UNKNOWN 语义，不假装支持）。"""
    key = (str(protocol), str(client))
    if key in PROFILES:
        return PROFILES[key]
    base = PROFILES.get((str(protocol), "spec"))
    if base is not None and str(client) == "spec":
        return base
    return ClientProfile(protocol=str(protocol), client=str(client),
                         evidence="[UNKNOWN]", source="未调查")


def known_clients(protocol: Optional[str] = None):
    return sorted(c for (p, c) in PROFILES if protocol is None or p == protocol)
