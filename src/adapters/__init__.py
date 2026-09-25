"""Flowerie 消息边界（Phase 3 起新增；旧 OneBot 文件原位保留）。

- proto.py：InternalEvent / EventParser / MessageSender（仅契约，无实现）
- onebot_parser.py：OneBotEventParser（机械转换；组合复用现有提取逻辑）
- milky_parser.py：MilkyEventParser（Milky 事件信封 → 同一 InternalEvent）
- container.py：make_adapters(protocol=onebot|milky) 组合根
- compat.py：InternalEvent → 旧 GroupMessage / 旧 dict → InternalEvent（下游零改动）

**依赖方向**：本包不 import 任何具体客户端实现，也不被 Core 反向 import。
"""
from src.adapters.compat import build_group_message, convert_legacy
from src.adapters.container import Adapters, make_adapters
from src.adapters.milky_parser import MilkyEventParser
from src.adapters.onebot_parser import OneBotEventParser
from src.adapters.proto import EventParser, InternalEvent, MessageSender

__all__ = ["InternalEvent", "EventParser", "MessageSender",
           "OneBotEventParser", "MilkyEventParser",
           "Adapters", "make_adapters",
           "build_group_message", "convert_legacy"]
