"""能力模型（Capability Model）—— 任务书 §7/§8/§9/§10 与 Gate G/H。

三条硬规则（直接来自任务书）：
1. **Capability 与 Message Segment 不是一回事**：能收图片 ≠ 能发图片，能解析 ≠ 能发送。
   故 receive / send / action 分开声明（§9）。
2. **状态必须显式**：supported / partial / emulated / unsupported / unknown；
   `unknown` **不得**被当成 `unsupported`（Gate H：不能留空、也不能自动降级）。
3. **协议只声明自己有的能力**，不强迫所有协议实现所有方法（§7 禁止"万能协议接口"）。

判定口径（本模块自己先写清楚，避免各处理解不一）：
- `supported`：Flowerie 有明确代码路径，且客户端侧有源码/规范证据；
- `partial`：通路存在但需要调用方自己拼装，或只覆盖部分形态（如只能发段数组、没有专用封装）；
- `unsupported`：当前没有可用路径（含"协议端明确不支持"）；
- `unknown`：**没有足够证据**（例如规范里没定义、实现可能扩展）；不等于不支持。

证据标注沿用仓库惯例：[CODE] 客户端源码 / [DOC] 规范 / [CODE]×N 多客户端互证。
"""
from dataclasses import dataclass, field
from typing import Dict, Mapping, Tuple


class Capability:
    """规范能力名（Gate G 的 18 项；命名用 点分层级，便于未来扩展）。"""

    MESSAGE_SEND = "message.send"
    MESSAGE_RECEIVE = "message.receive"
    MESSAGE_RECALL = "message.recall"
    IMAGE_RECEIVE = "image.receive"
    IMAGE_SEND = "image.send"
    FACE_RECEIVE = "face.receive"
    FACE_SEND = "face.send"
    MARKET_FACE_RECEIVE = "market_face.receive"
    MARKET_FACE_SEND = "market_face.send"
    FILE_RECEIVE = "file.receive"
    FILE_SEND = "file.send"
    FORWARD_RECEIVE = "forward.receive"
    FORWARD_SEND = "forward.send"
    CARD_RECEIVE = "card.receive"
    POKE_RECEIVE = "poke.receive"
    GROUP_UPLOAD_RECEIVE = "group_upload.receive"
    MARKDOWN_RECEIVE = "markdown.receive"
    LIGHT_APP_RECEIVE = "light_app.receive"


CANONICAL_CAPABILITIES: Tuple[str, ...] = (
    Capability.MESSAGE_SEND, Capability.MESSAGE_RECEIVE, Capability.MESSAGE_RECALL,
    Capability.IMAGE_RECEIVE, Capability.IMAGE_SEND,
    Capability.FACE_RECEIVE, Capability.FACE_SEND,
    Capability.MARKET_FACE_RECEIVE, Capability.MARKET_FACE_SEND,
    Capability.FILE_RECEIVE, Capability.FILE_SEND,
    Capability.FORWARD_RECEIVE, Capability.FORWARD_SEND,
    Capability.CARD_RECEIVE, Capability.POKE_RECEIVE,
    Capability.GROUP_UPLOAD_RECEIVE, Capability.MARKDOWN_RECEIVE,
    Capability.LIGHT_APP_RECEIVE,
)


class CapState:
    SUPPORTED = "supported"
    PARTIAL = "partial"
    EMULATED = "emulated"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"
    ALL = (SUPPORTED, PARTIAL, EMULATED, UNSUPPORTED, UNKNOWN)
    VALID = frozenset(ALL)


@dataclass(frozen=True)
class CapabilitySet:
    """一个协议/客户端的能力声明：能力名 -> 状态（+ 可选说明）。"""

    states: Mapping[str, str]
    notes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self):
        bad = {k: v for k, v in self.states.items() if v not in CapState.VALID}
        if bad:
            raise ValueError("非法能力状态: %s" % bad)

    def state(self, capability: str) -> str:
        """未声明的能力返回 unknown（调用方须自行决定是否视为不支持 —— 不要自动降级）。"""
        return self.states.get(capability, CapState.UNKNOWN)

    def declared(self, capability: str) -> bool:
        return capability in self.states

    def supports(self, capability: str) -> bool:
        return self.state(capability) == CapState.SUPPORTED

    def note(self, capability: str) -> str:
        return self.notes.get(capability, "")

    def as_dict(self) -> Dict[str, Dict[str, str]]:
        return {c: {"state": self.state(c), "note": self.note(c)} for c in self.states}


@dataclass(frozen=True)
class AdapterDescriptor:
    """Adapter 描述符（任务书 §19）：id / version / transports / capabilities。"""

    protocol_id: str
    version: str
    transports: Tuple[str, ...]
    capabilities: CapabilitySet
    note: str = ""


def _onebot11() -> AdapterDescriptor:
    caps = CapabilitySet(
        states={
            Capability.MESSAGE_SEND: CapState.SUPPORTED,
            Capability.MESSAGE_RECEIVE: CapState.SUPPORTED,
            Capability.MESSAGE_RECALL: CapState.SUPPORTED,
            Capability.IMAGE_RECEIVE: CapState.SUPPORTED,
            Capability.IMAGE_SEND: CapState.SUPPORTED,
            Capability.FACE_RECEIVE: CapState.SUPPORTED,
            Capability.FACE_SEND: CapState.PARTIAL,
            Capability.MARKET_FACE_RECEIVE: CapState.SUPPORTED,
            Capability.MARKET_FACE_SEND: CapState.PARTIAL,
            Capability.FILE_RECEIVE: CapState.SUPPORTED,
            Capability.FILE_SEND: CapState.PARTIAL,
            Capability.FORWARD_RECEIVE: CapState.SUPPORTED,
            Capability.FORWARD_SEND: CapState.UNSUPPORTED,
            Capability.CARD_RECEIVE: CapState.SUPPORTED,
            Capability.POKE_RECEIVE: CapState.SUPPORTED,
            Capability.GROUP_UPLOAD_RECEIVE: CapState.SUPPORTED,
            Capability.MARKDOWN_RECEIVE: CapState.SUPPORTED,
            Capability.LIGHT_APP_RECEIVE: CapState.SUPPORTED,
        },
        notes={
            Capability.FACE_SEND: "只能由调用方自拼 face 段数组，无专用封装 [CODE] NapCat types/message.ts",
            Capability.MARKET_FACE_SEND: "同上（mface 段直通）",
            Capability.FILE_SEND: "upload_group_file 未接线（client-compatibility.md §4 标待核对）",
            Capability.FORWARD_SEND: "未接线：无 send_group_forward_msg 路径",
        })
    return AdapterDescriptor("onebot11", "11", ("websocket-reverse", "websocket", "http"), caps,
                             "NapCat/LLBot/go-cqhttp 等 OneBot 11 实现共用；证据见 client-compatibility.md §1-§3")


def _milky() -> AdapterDescriptor:
    caps = CapabilitySet(
        states={
            Capability.MESSAGE_SEND: CapState.SUPPORTED,
            Capability.MESSAGE_RECEIVE: CapState.SUPPORTED,
            Capability.MESSAGE_RECALL: CapState.SUPPORTED,
            Capability.IMAGE_RECEIVE: CapState.SUPPORTED,
            Capability.IMAGE_SEND: CapState.UNSUPPORTED,
            Capability.FACE_RECEIVE: CapState.SUPPORTED,
            Capability.FACE_SEND: CapState.PARTIAL,
            Capability.MARKET_FACE_RECEIVE: CapState.SUPPORTED,
            Capability.MARKET_FACE_SEND: CapState.PARTIAL,
            Capability.FILE_RECEIVE: CapState.SUPPORTED,
            Capability.FILE_SEND: CapState.UNSUPPORTED,
            Capability.FORWARD_RECEIVE: CapState.SUPPORTED,
            Capability.FORWARD_SEND: CapState.UNSUPPORTED,
            Capability.CARD_RECEIVE: CapState.SUPPORTED,
            Capability.POKE_RECEIVE: CapState.SUPPORTED,
            Capability.GROUP_UPLOAD_RECEIVE: CapState.SUPPORTED,
            Capability.MARKDOWN_RECEIVE: CapState.SUPPORTED,
            Capability.LIGHT_APP_RECEIVE: CapState.SUPPORTED,
        },
        notes={
            Capability.IMAGE_SEND: "需先 upload 取 resource_id，管道未接线（缺口台账 G5，BLOCKED）[DOC] 规范 api",
            Capability.FILE_SEND: "上传动作未接线 [DOC] 规范 api/file",
            Capability.FORWARD_SEND: "send_group_forward_msg / send_private_forward_msg 在 Milky 明确不支持",
            Capability.FACE_SEND: "段数组直通；作者实现 ISegment 含 face [CODE] Entity/Segment",
            Capability.MARKET_FACE_SEND: "段数组直通；作者实现含 market_face（仅 url）[CODE] ISegment.cs L16",
            Capability.POKE_RECEIVE: "戳一戳是**事件** group_nudge，不是消息段 [CODE]×2",
        })
    return AdapterDescriptor("milky", "1", ("http", "websocket"), caps,
                             "Lagrange.Milky（两份内嵌副本）+ LLBot Milky 实现互证；见 milky-protocol.md")


def _onebot12() -> AdapterDescriptor:
    caps = CapabilitySet(
        states={
            Capability.MESSAGE_RECEIVE: CapState.PARTIAL,
            Capability.MESSAGE_SEND: CapState.UNSUPPORTED,
            Capability.MESSAGE_RECALL: CapState.UNSUPPORTED,
            Capability.IMAGE_RECEIVE: CapState.PARTIAL,
            Capability.IMAGE_SEND: CapState.UNSUPPORTED,
            Capability.FACE_RECEIVE: CapState.UNKNOWN,
            Capability.FACE_SEND: CapState.UNSUPPORTED,
            Capability.MARKET_FACE_RECEIVE: CapState.UNKNOWN,
            Capability.MARKET_FACE_SEND: CapState.UNSUPPORTED,
            Capability.FILE_RECEIVE: CapState.PARTIAL,
            Capability.FILE_SEND: CapState.UNSUPPORTED,
            Capability.FORWARD_RECEIVE: CapState.UNKNOWN,
            Capability.FORWARD_SEND: CapState.UNSUPPORTED,
            Capability.CARD_RECEIVE: CapState.UNKNOWN,
            Capability.POKE_RECEIVE: CapState.UNKNOWN,
            Capability.GROUP_UPLOAD_RECEIVE: CapState.UNKNOWN,
            Capability.MARKDOWN_RECEIVE: CapState.UNKNOWN,
            Capability.LIGHT_APP_RECEIVE: CapState.UNKNOWN,
        },
        notes={
            Capability.MESSAGE_RECEIVE: "骨架可解析信封与段；未实机验证（NOT_REAL_DEVICE_VALIDATED）",
            Capability.IMAGE_RECEIVE: "骨架把 file_id 映射成 images；v12 无普通 URL 字段，未接下载",
            Capability.FILE_RECEIVE: "骨架映射 file_id/file_name；下载动作未接线",
            Capability.FACE_RECEIVE: "规范 incoming 段未见 face；实现可扩展 -> unknown，不当作 unsupported",
            Capability.FORWARD_RECEIVE: "规范中未定位等价段 -> unknown",
        })
    return AdapterDescriptor("onebot12", "12", ("websocket", "websocket-reverse", "http", "http-webhook"), caps,
                             "骨架适配器（src/adapters/onebot12_parser.py）；研究见 onebot12-research.md")


_FACTORIES = (_onebot11, _milky, _onebot12)


def descriptors() -> Dict[str, AdapterDescriptor]:
    """所有已登记协议的描述符（注册表最小实现，Gate 18）。"""
    return {d.protocol_id: d for d in (f() for f in _FACTORIES)}


def get_descriptor(protocol_id: str) -> AdapterDescriptor:
    try:
        return descriptors()[protocol_id]
    except KeyError:
        raise KeyError("未登记的协议: %s（已登记：%s）" % (protocol_id, sorted(descriptors()))) from None


def coverage_for_descriptor(descriptor: AdapterDescriptor) -> float:
    """与 capability_coverage 同口径，但直接作用于描述符 —— 供未登记进生产注册表的
    适配器（例如 Gate E 的虚拟协议）使用。"""
    caps = descriptor.capabilities
    declared = sum(1 for c in CANONICAL_CAPABILITIES if caps.declared(c))
    return declared / float(len(CANONICAL_CAPABILITIES))


def capability_coverage(protocol_id: str) -> float:
    """Gate G 口径：该协议**已显式声明**的能力 / 规范能力总数。"""
    return coverage_for_descriptor(get_descriptor(protocol_id))
