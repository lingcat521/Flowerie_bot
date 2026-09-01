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

# v2.1 缺口 SDK（分面/上下文/任务/组合器/明确 NS）
from flowerie_sdk.gap_sdk import (
    MessageSegment, MessageFilter, FriendContext, GroupMemberContext, ReactionContext,
    SessionContext, Conversation, FriendRequest, GroupRequest, FileContext, MediaContext,
    TaskManager, TaskHandle, I18n, PluginFeatureError, build_sdk,
)
from flowerie_sdk.matcher import rule_or, rule_all, rule_not
