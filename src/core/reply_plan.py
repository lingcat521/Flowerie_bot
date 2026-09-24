"""ReplyPlan：一次回复产生的「多条消息 + 发送策略」（核心层，协议无关）。

设计要点（对齐任务书 §2/§3/§7/§9）：
- 单条回复 100% 向后兼容：ReplyPlan.of("你好") 自动包装成单条计划；
- AI 只能决定「发几条、每条说什么」，间隔/上限/限流一律由 Core 配置决定；
- 本文件里不出现 OneBot / Milky / WebSocket / HTTP —— 协议细节在适配层之下。
"""
import random
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

# 间隔模式
INTERVAL_NONE = "none"       # 不留间隔，连续发（仍受连续回复限制约束）
INTERVAL_FIXED = "fixed"     # 固定间隔（min_interval 秒）
INTERVAL_RANDOM = "random"   # 随机间隔（min~max 秒之间均匀取值）

VALID_INTERVAL_MODES = (INTERVAL_NONE, INTERVAL_FIXED, INTERVAL_RANDOM)


@dataclass
class ReplyPlan:
    """一次回复的发送计划。messages 至少 1 条（空计划等于不发）。"""

    messages: List[str] = field(default_factory=list)
    interval_mode: str = INTERVAL_RANDOM
    min_interval: float = 1.5
    max_interval: float = 4.0
    # 供上层记录/审计：本条计划是否来自 AI 的多条结构化输出
    from_ai: bool = False

    # ---------- 构造 ----------
    @classmethod
    def of(cls, reply, interval_mode: str = INTERVAL_RANDOM,
           min_interval: float = 1.5, max_interval: float = 4.0, from_ai: bool = False) -> "ReplyPlan":
        """把任意形态的回复统一成计划：str / None / 单个对象 / 可迭代。

        单条字符串 → 单条计划（向后兼容的关键：旧代码无需改动）。
        """
        if reply is None:
            msgs: List[str] = []
        elif isinstance(reply, ReplyPlan):
            return reply
        elif isinstance(reply, str):
            msgs = [reply] if reply.strip() else []
        elif isinstance(reply, Iterable):
            msgs = [m for m in (str(x) for x in reply) if m.strip()]
        else:
            msgs = [str(reply)]
        return cls(messages=msgs, interval_mode=interval_mode,
                   min_interval=min_interval, max_interval=max_interval, from_ai=from_ai)

    # ---------- 策略 ----------
    def clamped(self, max_messages: Optional[int]) -> "ReplyPlan":
        """按配置裁剪条数（AI 无权绕过上限：超出部分直接丢弃）。"""
        if max_messages is None or max_messages <= 0 or len(self.messages) <= max_messages:
            return self
        return ReplyPlan(messages=self.messages[:max_messages], interval_mode=self.interval_mode,
                         min_interval=self.min_interval, max_interval=self.max_interval,
                         from_ai=self.from_ai)

    def delay_before(self, index: int, rng: Optional[random.Random] = None) -> float:
        """第 index 条（0 基）发送前的等待秒数；第 0 条不等待。"""
        if index <= 0 or self.interval_mode == INTERVAL_NONE:
            return 0.0
        r = rng or random
        if self.interval_mode == INTERVAL_FIXED:
            return max(0.0, float(self.min_interval))
        lo, hi = float(self.min_interval), float(self.max_interval)
        if hi < lo:
            lo, hi = hi, lo
        return max(0.0, r.uniform(lo, hi) if hi > lo else lo)

    # ---------- 便捷 ----------
    def normalize_mode(self) -> "ReplyPlan":
        """非法模式回退为随机间隔（配置写错不炸运行）。"""
        if self.interval_mode not in VALID_INTERVAL_MODES:
            self.interval_mode = INTERVAL_RANDOM
        return self

    @property
    def is_single(self) -> bool:
        return len(self.messages) == 1

    def __len__(self) -> int:
        return len(self.messages)

    def __bool__(self) -> bool:
        return bool(self.messages)

    def __iter__(self):
        return iter(self.messages)


def first_text(reply) -> str:
    """回复的首条文本（str / list / tuple / None 都安全）。

    多条回复在查重、表情包标记、兜底与日志处都只看首条；这些地方此前直接
    .strip() / 正则搜索，遇到 list 会 AttributeError / TypeError
    （Native Reply Tool 与旧式 JSON 多条都走这条路径）。
    """
    if isinstance(reply, (list, tuple)):
        for m in reply:
            text = str(m or "").strip()
            if text:
                return text
        return ""
    return str(reply or "").strip()


def plan_from_config(reply, config, *, from_ai: bool = False) -> ReplyPlan:
    """按配置把回复包装成计划（统一入口，避免各处自己读配置）。"""
    max_messages = int(getattr(config, "MULTI_REPLY_MAX_MESSAGES", 3) or 3)
    enabled = bool(getattr(config, "MULTI_REPLY_ENABLED", False))
    mode = str(getattr(config, "MULTI_REPLY_INTERVAL_MODE", INTERVAL_RANDOM) or INTERVAL_RANDOM)
    lo = float(getattr(config, "MULTI_REPLY_MIN_INTERVAL", 1.5) or 0.0)
    hi = float(getattr(config, "MULTI_REPLY_MAX_INTERVAL", 4.0) or 0.0)
    plan = ReplyPlan.of(reply, interval_mode=mode, min_interval=lo, max_interval=hi, from_ai=from_ai)
    plan.normalize_mode()
    if not enabled:
        # 未启用：只发第一条（多条能力对现有行为零影响）
        plan = plan.clamped(1)
    return plan.clamped(max_messages)
