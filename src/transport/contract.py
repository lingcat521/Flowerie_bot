"""TransportContract：传输层 8 项契约（任务书 B 部分 Gate Q §18）。

问题：传输层现状是"每种连接方式自己长一套 API"——反向 WS（WebSocketServer）、正向 WS
（NapCatForwardClient）、Milky WS（MilkyClient）、HTTP 动作通道（OneBotHTTPChannel /
MilkyHTTPChannel）各自为政。调用方无法用同一套语义驱动它们，只能按类型分支。

本模块定义 **8 项**语义契约，任何传输实现都必须逐项交代：

    connect / disconnect / send / receive / request / authentication / error / reconnect

对某种传输**天然不适用**的项（例如 HTTP 没有服务端推送），必须显式标 `N/A` 并在 `NA_REASONS`
里写明理由——"没写"（missing）与"明确说明不适用"（N/A）是两件不同的事，本模块把二者分开统计。

依赖：只依赖标准库（不 import aiohttp / websockets），因此"传输契约"本身不绑定任何网络库。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

# 8 项契约（名字即方法名；顺序固定，Dashboard 与测试按此顺序展示）
TRANSPORT_CONTRACT_ITEMS: Tuple[str, ...] = (
    "connect", "disconnect", "send", "receive",
    "request", "authentication", "error", "reconnect",
)

STATUS_IMPLEMENTED = "implemented"
STATUS_NA = "N/A"
STATUS_MISSING = "missing"


@dataclass(frozen=True)
class ContractItem:
    """单项契约：名字 + 一句话摘要 + 语义（实现者必须满足的行为）。"""

    name: str
    summary: str
    semantics: str


CONTRACT_ITEMS: Tuple[ContractItem, ...] = (
    ContractItem("connect", "建立连接",
                 "成功返回 True 并进入可用状态；失败返回 False 且 error() 记录原因（不抛给调用方）"),
    ContractItem("disconnect", "断开连接",
                 "幂等：未连接时调用也返回 True；断开后 send/request 必须失败而不是静默丢弃"),
    ContractItem("send", "单向发送",
                 "把载荷交给对端，不等待业务响应；失败返回 False 且 error() 记录原因"),
    ContractItem("receive", "接收事件",
                 "返回下一条事件（dict）；超时返回 None；无推送通道的传输标 N/A 并说明由谁提供"),
    ContractItem("request", "请求-响应",
                 "发送并等待配对响应：返回 {'ok': bool, 'data': ..., 'error': ...}；超时/未连接都不抛异常"),
    ContractItem("authentication", "鉴权材料",
                 "返回本次连接应使用的鉴权信息（headers/payload）；无鉴权配置时返回空 dict"),
    ContractItem("error", "错误可观测",
                 "返回最近一次错误描述（str）或 None；错误必须可被上层读到，不能只写日志"),
    ContractItem("reconnect", "断线重连",
                 "按退避策略重试连接；返回是否成功；无长连接的传输标 N/A 并给出等价能力"),
)


class TransportContract:
    """8 项契约的基类：默认实现一律抛 NotImplementedError，逼实现者逐项交代。

    - 实现项：直接覆盖基类方法；
    - 不适用项：不覆盖，改在 `NA_REASONS` 里写明理由（理由为空的 N/A 视为未交代）。

    **刻意不继承 `abc.ABC` / 不用 `@abstractmethod`**：本契约允许实现者把某项标成 N/A
    （例如 HTTP 没有 `receive`），而 `@abstractmethod` 会让"不实现某几项"的子类无法实例化 ——
    两者语义冲突。是否交代齐全由 `check_transport_contract()` 统一核对（含 N/A 必须有理由）。
    （另：ruff 的 B024 也会直接指出"ABC 里没有抽象方法"。）
    """

    #: 传输名（用于报告）
    name = "transport"

    #: 明确声明"天然不适用"的契约项 -> 理由（必须非空）
    NA_REASONS: Dict[str, str] = {}

    @classmethod
    def contract_items(cls) -> Tuple[str, ...]:
        return TRANSPORT_CONTRACT_ITEMS

    @classmethod
    def na_reasons(cls) -> Dict[str, str]:
        return dict(cls.NA_REASONS)

    # ---- 8 项（默认未实现；覆盖即为承诺） ----
    async def connect(self) -> bool:
        raise NotImplementedError

    async def disconnect(self) -> bool:
        raise NotImplementedError

    async def send(self, payload: Dict[str, Any]) -> bool:
        raise NotImplementedError

    async def receive(self, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    async def request(self, action: str, params: Optional[Dict[str, Any]] = None,
                      timeout: Optional[float] = None) -> Dict[str, Any]:
        raise NotImplementedError

    def authentication(self) -> Dict[str, Any]:
        raise NotImplementedError

    def error(self) -> Optional[str]:
        raise NotImplementedError

    async def reconnect(self) -> bool:
        raise NotImplementedError


@dataclass
class ContractReport:
    """一次契约核对的结果（数值都可由 `as_dict()` 直接进 Dashboard）。"""

    transport: str
    statuses: Dict[str, str] = field(default_factory=dict)
    reasons: Dict[str, str] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(TRANSPORT_CONTRACT_ITEMS)

    @property
    def implemented(self) -> int:
        return sum(1 for v in self.statuses.values() if v == STATUS_IMPLEMENTED)

    @property
    def na(self) -> int:
        return sum(1 for v in self.statuses.values() if v == STATUS_NA)

    @property
    def missing(self) -> Tuple[str, ...]:
        return tuple(k for k in TRANSPORT_CONTRACT_ITEMS if self.statuses.get(k) == STATUS_MISSING)

    @property
    def undocumented_na(self) -> Tuple[str, ...]:
        """标了 N/A 却没写理由（不算交代）。"""
        return tuple(k for k, v in self.statuses.items() if v == STATUS_NA and not self.reasons.get(k))

    @property
    def covered(self) -> int:
        """已交代的项数 = implemented + N/A（Gate Q 的 8/8 指这一项）。"""
        return self.implemented + self.na

    @property
    def ok(self) -> bool:
        return self.covered == self.total and not self.undocumented_na and not self.missing

    def as_dict(self) -> Dict[str, Any]:
        return {
            "transport": self.transport,
            "total": self.total,
            "implemented": self.implemented,
            "na": self.na,
            "missing": list(self.missing),
            "covered": self.covered,
            "ok": self.ok,
            "statuses": dict(self.statuses),
            "reasons": dict(self.reasons),
        }

    def summary(self) -> str:
        return "%s: %d/%d（implemented %d, N/A %d%s）" % (
            self.transport, self.covered, self.total, self.implemented, self.na,
            "" if not self.missing else ", missing: " + ",".join(self.missing))


def check_transport_contract(transport: Any) -> ContractReport:
    """逐项核对一个传输实例：覆盖=implemented，声明不适用=N/A，其余=missing。

    注意：只认**类上真实覆盖**的方法——继承基类占位实现（NotImplementedError）算 missing，
    避免"看起来有方法其实没实现"的假通过。
    """
    cls = type(transport)
    na = dict(getattr(cls, "NA_REASONS", {}) or {})
    statuses: Dict[str, str] = {}
    reasons: Dict[str, str] = {}
    for item in TRANSPORT_CONTRACT_ITEMS:
        if item in na:
            statuses[item] = STATUS_NA
            reasons[item] = str(na.get(item) or "").strip()
            continue
        impl = getattr(cls, item, None)
        base = getattr(TransportContract, item, None)
        if impl is None or not callable(impl) or impl is base:
            statuses[item] = STATUS_MISSING
        else:
            statuses[item] = STATUS_IMPLEMENTED
    return ContractReport(transport=str(getattr(transport, "name", cls.__name__)),
                          statuses=statuses, reasons=reasons)
