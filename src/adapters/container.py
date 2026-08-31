"""组合根（Composition Root）：Adapters 容器（Phase 4）。

依赖关系（明确标注，无隐藏路径）：

    Settings(config)
      └─ Sender(config)                  # 现有实现（HTTP/Token/超时/重试/熔断 全部不变）
           └─ make_adapters(BOT_QQ, sender)
                ├─ OneBotEventParser(bot_qq=BOT_QQ)   # 新：OneBot raw → InternalEvent
                └─ Adapters{parser, sender}           # 容器（组合根，供未来 Router 接入）

- sender 复用 main 已创建的共享实例（不重复构造、不复制 HTTP/Token 逻辑）
- parser 在组合根构造（生命周期与 sender 同步；Phase 5 接入 router 消费）
- 业务层（core/services/repositories）不 import 本模块（反向依赖测试保障）
"""
import inspect
from dataclasses import dataclass, field
from typing import Any, Optional

from src.adapters.proto import EventParser, MessageSender


@dataclass
class Adapters:
    """已组装的消息边界（parser 供事件接入；sender 即现有出口）。"""

    parser: EventParser
    sender: MessageSender = field(repr=False)
    bot_qq: Optional[int] = None
    # 预留：未来 adapter 实现（QQ 官方/Telegram 等）在此注册
    transport: str = "onebot"


def _missing_sender_methods(sender: Any) -> list:
    """MessageSender 契约方法面逐一核对（Python 3.9 兼容；不用 runtime_checkable）。"""
    missing = []
    for name, _vv in inspect.getmembers(MessageSender):
        if name.startswith("_"):
            continue
        if not hasattr(sender, name):
            missing.append(name)
    return missing


def make_adapters(bot_qq: Optional[int], sender: Any) -> Adapters:
    """组装组合根：解析器 + 现有 Sender（不重复构造任何网络资源）。

    - sender 必须满足 MessageSender 契约（启动期校验，失败即 RuntimeError）
    - parser 为 OneBotEventParser（未来 adapter 时替换 make_adapters 内部实现即可）
    """
    from src.adapters.onebot_parser import OneBotEventParser

    missing = _missing_sender_methods(sender)
    if missing:
        raise RuntimeError(f"sender 不满足 MessageSender 契约（缺 {missing}）")
    parser: EventParser = OneBotEventParser(bot_qq=bot_qq)
    return Adapters(parser=parser, sender=sender, bot_qq=bot_qq, transport="onebot")
