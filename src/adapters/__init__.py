"""Flowerie 消息边界（Phase 3 起新增；旧 OneBot 文件原位保留）。

- proto.py：InternalEvent / EventParser / MessageSender（仅契约，无实现）
- onebot_parser.py：OneBotEventParser（机械转换；组合复用现有提取逻辑）
"""
from src.adapters.container import Adapters, make_adapters
from src.adapters.onebot_parser import OneBotEventParser
from src.adapters.proto import EventParser, InternalEvent, MessageSender

__all__ = ["InternalEvent", "EventParser", "MessageSender", "OneBotEventParser",
           "Adapters", "make_adapters"]
