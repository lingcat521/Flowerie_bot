"""Flowerie 插件 SDK（插件自带副本，零依赖）。

插件只需：
    from flowerie_sdk import FlowerieBot, command, keyword, regex, prefix, exact, rule

（见 docs/sdk.md 最小示例）
"""
from flowerie_sdk.bot import BotAPIError, FlowerieBot
from flowerie_sdk.event import BotEvent
from flowerie_sdk.matcher import (
    command,
    exact,
    keyword,
    prefix,
    regex,
    require_permission,
    rule,
)
from flowerie_sdk.message import BotMessage

__all__ = ["FlowerieBot", "BotEvent", "BotMessage",
           "command", "keyword", "regex", "prefix", "exact", "rule",
           "require_permission", "BotAPIError"]

# v2.1 缺口 SDK（分面/上下文/任务/组合器/明确 NS）——重导出（显式别名满足 F401/可移植）
from flowerie_sdk.gap_sdk import Conversation as Conversation
from flowerie_sdk.gap_sdk import FileContext as FileContext
from flowerie_sdk.gap_sdk import FriendContext as FriendContext
from flowerie_sdk.gap_sdk import FriendRequest as FriendRequest
from flowerie_sdk.gap_sdk import GroupMemberContext as GroupMemberContext
from flowerie_sdk.gap_sdk import GroupRequest as GroupRequest
from flowerie_sdk.gap_sdk import I18n as I18n
from flowerie_sdk.gap_sdk import MediaContext as MediaContext
from flowerie_sdk.gap_sdk import MessageFilter as MessageFilter
from flowerie_sdk.gap_sdk import MessageSegment as MessageSegment
from flowerie_sdk.gap_sdk import PluginFeatureError as PluginFeatureError
from flowerie_sdk.gap_sdk import ReactionContext as ReactionContext
from flowerie_sdk.gap_sdk import SessionContext as SessionContext
from flowerie_sdk.gap_sdk import TaskHandle as TaskHandle
from flowerie_sdk.gap_sdk import TaskManager as TaskManager
from flowerie_sdk.gap_sdk import build_sdk as build_sdk
from flowerie_sdk.matcher import rule_all as rule_all
from flowerie_sdk.matcher import rule_not as rule_not
from flowerie_sdk.matcher import rule_or as rule_or
