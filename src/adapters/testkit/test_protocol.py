"""TestProtocolAdapter：Gate E/F 的**虚拟协议**（无真实网络，仅供实验与契约测试）。

存在意义（任务书 §6/§7）：用一个"尚未真正实现的伪协议"验证——
**新增一个协议时，是否真的只需要增加 Adapter，而不修改 Core / Services / SDK / 既有插件**。
因此本模块刻意做成**自包含**：只依赖 `src/adapters/proto.py` 的契约，不 import 任何业务层。

发明出来的线格式（虚构，但形状贴近真实协议，便于覆盖各种能力）：

```json
{
  "kind": "msg",
  "chan": "group:123456",
  "from": 456789,
  "seq": 5,
  "ts": 1700000000,
  "parts": [
    {"t": "text", "v": "hello"},
    {"t": "at", "v": 10001},
    {"t": "img", "url": "https://example/a.png", "name": "a.png"},
    {"t": "unknown-thing", "v": {"a": 1}}
  ]
}
```

事件：`{"kind": "notice", "evt": "poke", "chan": "group:123456", "from": 456789, "to": 10001, "ts": ...}`。

**本模块不进入生产路径**：只在 `tests/` 与契约夹具里被引用。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.adapters.capabilities import AdapterDescriptor, Capability, CapabilitySet, CapState
from src.adapters.proto import InternalEvent, as_event_dict, to_int


def _split_chan(chan: str) -> Tuple[str, Optional[int]]:
    """chan 形如 group:123456 / dm:456789 -> (scope, id)。"""
    raw = str(chan or "")
    if ":" not in raw:
        return "", None
    prefix, _, sid = raw.partition(":")
    scope = {"group": "group", "dm": "private"}.get(prefix, "")
    return scope, to_int(sid)


class TestProtocolEventParser:
    """虚构线格式 -> InternalEvent（EventParser 契约的实现之一）。"""

    # pytest 会把这个以 Test 开头的类当测试类收集（本模块被 import 进 tests/ 命名空间后），
    # 故显式声明非测试（pytest 官方机制），避免收集噪音与 PytestCollectionWarning。
    __test__ = False

    def __init__(self, bot_qq: Optional[int] = None, note: str = ""):
        self._bot_qq = str(bot_qq) if bot_qq is not None else ""
        self._note = note

    def parse(self, raw: Dict[str, Any]) -> InternalEvent:
        raw = as_event_dict(raw)
        ev = InternalEvent(raw_data=raw)
        ev.timestamp = to_int(raw.get("ts"))
        kind = str(raw.get("kind") or "")
        scope, chan_id = _split_chan(str(raw.get("chan") or ""))
        ev.scope = scope
        ev.actor_id = to_int(raw.get("from"))
        ev.event_id = "testproto:%s:%s:%s" % (kind, raw.get("chan"), raw.get("seq") or raw.get("ts"))
        if kind == "msg":
            ev.kind = "message"
            if scope == "group":
                ev.group_id = chan_id
            ev.message_id = to_int(raw.get("seq"))
            self._scan_parts(ev, raw.get("parts"))
        elif kind == "notice":
            ev.kind = "notice"
            if scope == "group":
                ev.group_id = chan_id
            ev.target_id = to_int(raw.get("to"))
            evt = str(raw.get("evt") or "")
            ev.notice_kind = "poke" if evt == "poke" else evt
        elif kind:
            ev.kind = kind          # 未知事件类型原样保留（Gate K）
        else:
            ev.kind = "unknown"
        return ev

    def _scan_parts(self, ev: InternalEvent, parts: Any) -> None:
        if not isinstance(parts, list):
            return
        ev.message_segments = [dict(p) for p in parts if isinstance(p, dict)]
        texts: List[str] = []
        for part in ev.message_segments:
            ptype = str(part.get("t") or "")
            if ptype == "text":
                texts.append(str(part.get("v") or ""))
            elif ptype == "at":
                uid = str(part.get("v") or "")
                if uid:
                    ev.mentions.append(uid)
                    if uid == self._bot_qq:
                        ev.is_mentioned = True
                    else:
                        ev.has_at_others = True
            elif ptype == "img":
                url = str(part.get("url") or "")
                if url:
                    ev.images.append(url)
                name = str(part.get("name") or "")
                if name:
                    ev.image_files.append(name)
            elif ptype == "face":
                # 表情段：与 OneBot/Milky 同形（kind/face_id/...），Gate M 的等价类需要它
                ev.faces.append({"kind": "face", "face_id": str(part.get("v") or ""),
                                 "result_id": "", "chain_count": None})
            elif ptype == "market_face":
                ev.faces.append({"kind": "market_face", "emoji_id": str(part.get("v") or ""),
                                 "summary": str(part.get("name") or "")})
            elif ptype == "file":
                payload = part.get("v") if isinstance(part.get("v"), dict) else {}
                ev.files.append({"file_id": str(payload.get("id") or ""),
                                 "name": str(payload.get("name") or part.get("name") or ""),
                                 "size": to_int(payload.get("size")), "url": "", "path": ""})
            elif ptype == "reply":
                seq = to_int(part.get("v"))
                ev.reply_id = seq
                ev.reply_ref = {"id": seq}
            elif ptype == "forward":
                ev.forwards.append({"id": str(part.get("v") or ""),
                                    "inline": bool(part.get("inline"))})
            else:
                # 与真实解析器同一约定：segments_summary 存 (段类型, 载荷值)，
                # 载荷不是 dict 时统一包成 {"value": ...}，保证结构一致
                payload = part.get("v")
                ev.segments_summary.append((ptype, dict(payload) if isinstance(payload, dict)
                                            else {"value": payload}))
        ev.text = "".join(texts).strip()


@dataclass
class TestProtocolChannel:
    """自包含的"发送通道"：不联网，只记录调用（用于 Gate F 的发送/撤回实验）。"""

    __test__ = False  # 同上：避免被 pytest 当作测试类收集

    sent: List[Tuple[str, Dict[str, Any]]] = field(default_factory=list)
    recalled: List[Tuple[int, str]] = field(default_factory=list)

    async def post(self, endpoint: str, payload: Dict[str, Any], timeout: float = 10.0) -> Dict[str, Any]:
        self.sent.append((endpoint, dict(payload)))
        return {"ok": True, "data": {"message_id": len(self.sent)}}

    async def recall(self, message_id: int, scope: str = "group") -> bool:
        self.recalled.append((message_id, scope))
        return True


def test_protocol_descriptor() -> AdapterDescriptor:
    """伪协议的能力声明（Gate F 第 7 项实验：能力查询）。"""
    supported = (Capability.MESSAGE_SEND, Capability.MESSAGE_RECEIVE, Capability.MESSAGE_RECALL,
                 Capability.IMAGE_RECEIVE, Capability.IMAGE_SEND, Capability.FACE_RECEIVE,
                 Capability.FILE_RECEIVE, Capability.FORWARD_RECEIVE, Capability.CARD_RECEIVE,
                 Capability.POKE_RECEIVE, Capability.GROUP_UPLOAD_RECEIVE,
                 Capability.MARKDOWN_RECEIVE, Capability.LIGHT_APP_RECEIVE)
    unsupported = (Capability.FACE_SEND, Capability.MARKET_FACE_RECEIVE,
                   Capability.MARKET_FACE_SEND, Capability.FILE_SEND, Capability.FORWARD_SEND)
    states = {}
    for c in supported:
        states[c] = CapState.SUPPORTED
    for c in unsupported:
        states[c] = CapState.UNSUPPORTED
    return AdapterDescriptor(
        protocol_id="testproto",
        version="0",
        transports=("inproc",),
        capabilities=CapabilitySet(states=states,
                                   notes={c: "虚拟协议未实现该能力（Gate E 实验用）" for c in unsupported}),
        note="Gate E/F 虚拟协议（src/adapters/testkit/test_protocol.py）：不联网、不进生产路径",
    )


# 名字以 test_ 开头是为了对齐任务书的 "TestProtocolAdapter"；对 pytest 而言它是普通工厂函数，
# 必须显式排除，否则被 import 到 tests/ 里就会被当成用例收集（并因返回值触发警告）。
test_protocol_descriptor.__test__ = False
