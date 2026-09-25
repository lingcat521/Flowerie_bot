"""多实例（Gate S）：协议实例的独立生命周期与注册表。

任务书 Gate S 要求：**OneBot11 #1 / OneBot11 #2 / Milky #1 同时存在**，各自独立
（独立连接 / 独立配置 / 独立生命周期 / 独立发送 / 独立接收），
**Instance Cross-talk = 0**，且不得依赖单例（`current_protocol` / `current_ws` / `global_adapter`）。

本模块的立场：**没有全局态**。

- `InstanceRegistry` 是普通对象（由组合根持有、按需注入），不是模块级单例；
- `AdapterInstance` 把"自己的解析器 / 描述符 / 发送出口 / 配置"绑在一起，
  **不共享任何可变状态**：两个实例即使协议相同（OneBot11 #1 与 #2），
  解析器、通道、发送记录也是各自的；
- 未接线发送出口的实例，发送时**明确失败**，绝不借用别的实例的通道（这正是串台的来源）。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.adapters.capabilities import get_descriptor
from src.adapters.container import make_parser

# 生命周期状态（Gate S：独立生命周期）
STATE_CREATED = "created"
STATE_CONNECTED = "connected"
STATE_CLOSED = "closed"
VALID_STATES = (STATE_CREATED, STATE_CONNECTED, STATE_CLOSED)


@dataclass
class AdapterInstance:
    """一个协议实例：解析器 + 描述符 + 发送出口 + 配置（全部是自己的）。"""

    instance_id: str
    protocol: str
    parser: Any
    descriptor: Any = None
    channel: Any = None
    config: Any = None
    bot_qq: Optional[int] = None
    state: str = STATE_CREATED
    #: 本实例发出的消息（诊断/审计用；**只属于自己**，跨实例不可见）
    sent: List[Dict[str, Any]] = field(default_factory=list)
    #: 本实例解析过的事件条数
    received: int = 0

    @property
    def connected(self) -> bool:
        return self.state == STATE_CONNECTED

    # ---------- 独立接收 ----------
    def parse(self, raw: Dict[str, Any]) -> Any:
        """解析**本实例**收到的事件（调用方按连接路由，注册表不做隐式分发）。"""
        self.received += 1
        return self.parser.parse(raw)

    # ---------- 独立生命周期 ----------
    async def connect(self) -> bool:
        self.state = STATE_CONNECTED
        return True

    async def disconnect(self) -> bool:
        self.state = STATE_CLOSED
        return True

    # ---------- 独立发送 ----------
    async def send(self, payload: Dict[str, Any], endpoint: str = "send_group_msg") -> Dict[str, Any]:
        if self.state != STATE_CONNECTED:
            return {"ok": False, "error": "instance %s 未连接（state=%s）" % (self.instance_id, self.state)}
        if self.channel is None:
            return {"ok": False, "error": "instance %s 未接线发送出口" % self.instance_id}
        res = await self.channel.post(endpoint, payload)
        if not isinstance(res, dict):
            res = {"ok": False, "error": "通道返回了非 dict：%r" % (res,)}
        self.sent.append({"endpoint": endpoint, "payload": dict(payload), "ok": bool(res.get("ok"))})
        return res

    def snapshot(self) -> Dict[str, Any]:
        """实例状态快照（诊断 / Dashboard 用；不含原始消息内容）。"""
        return {
            "instance_id": self.instance_id,
            "protocol": self.protocol,
            "bot_qq": self.bot_qq,
            "state": self.state,
            "received": self.received,
            "sent": len(self.sent),
            "capabilities": getattr(self.descriptor, "protocol_id", None),
        }


class InstanceRegistry:
    """实例注册表：重名即报错，按 id 精确取用；**不是单例**（谁持有谁负责生命周期）。"""

    def __init__(self) -> None:
        self._instances: Dict[str, AdapterInstance] = {}

    def register(self, instance: AdapterInstance) -> AdapterInstance:
        if instance.instance_id in self._instances:
            raise ValueError("实例 id 重复：%s" % instance.instance_id)
        self._instances[instance.instance_id] = instance
        return instance

    def get(self, instance_id: str) -> AdapterInstance:
        inst = self._instances.get(str(instance_id))
        if inst is None:
            raise KeyError("未注册的实例：%s" % instance_id) from None
        return inst

    def find(self, instance_id: str) -> Optional[AdapterInstance]:
        return self._instances.get(str(instance_id))

    def unregister(self, instance_id: str) -> bool:
        return self._instances.pop(str(instance_id), None) is not None

    def ids(self) -> List[str]:
        return sorted(self._instances)

    def all(self) -> List[AdapterInstance]:
        return [self._instances[k] for k in self.ids()]

    async def connect_all(self) -> int:
        count = 0
        for inst in self.all():
            if await inst.connect():
                count += 1
        return count

    async def disconnect_all(self) -> int:
        count = 0
        for inst in self.all():
            if await inst.disconnect():
                count += 1
        return count

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        return {inst.instance_id: inst.snapshot() for inst in self.all()}

    def __len__(self) -> int:
        return len(self._instances)

    def __contains__(self, instance_id: object) -> bool:
        return str(instance_id) in self._instances


def make_instance(instance_id: str, config: Any, *, channel: Any = None,
                  protocol: Optional[str] = None, bot_qq: Optional[int] = None,
                  session: Any = None, ws_sender: Any = None) -> AdapterInstance:
    """按**该实例自己的配置**装配实例（协议 / Bot QQ / 发送出口都取自这一个 config 对象）。

    - `protocol` 缺省取 `config.QQ_PROTOCOL`；`bot_qq` 缺省取 `config.BOT_QQ`；
    - `channel` 未给且传了 `session` 时，用动作通道工厂按该实例的配置构造（唯一读协议开关处）；
    - 不给 session 也不给 channel → 该实例**没有**发送出口：发送会明确失败，绝不借用别人的。
    """
    proto = str(protocol or getattr(config, "QQ_PROTOCOL", "onebot") or "onebot").lower()
    proto = "milky" if proto == "milky" else "onebot"
    qq = bot_qq if bot_qq is not None else getattr(config, "BOT_QQ", None)
    if channel is None and session is not None:
        # 懒 import：本模块不依赖 aiohttp
        from src.transport.action_channels import make_action_channel

        channel = make_action_channel(config, session, ws_sender)
    return AdapterInstance(
        instance_id=str(instance_id),
        protocol=proto,
        parser=make_parser(proto, qq),
        descriptor=get_descriptor("milky" if proto == "milky" else "onebot11"),
        channel=channel,
        config=config,
        bot_qq=qq,
    )
