"""Legacy Compatibility Layer（Phase 5）：InternalEvent → 现有 GroupMessage。

- GroupMessage 字段全部保留（message_array/raw_message/clean_text/full_text/
  is_mentioned/is_reply_to_bot/has_reply_to_other/has_at_others/time）
- 下游（context/AI/记忆/人格…）零修改；不删除 message_array，不改变语义
- raw_data 不在转换中使用（只读语义字段 + message_segments）
"""
import copy
from typing import Optional

from src.adapters.proto import InternalEvent
from src.models import GroupMessage


def build_group_message(
    event: InternalEvent,
    *,
    clean_text: str = "",
    full_text: str = "",
    is_mentioned: Optional[bool] = None,
    is_reply_to_bot: Optional[bool] = None,
    has_reply_to_other: Optional[bool] = None,
    has_at_others: Optional[bool] = None,
    message_array: Optional[list] = None,
) -> GroupMessage:
    """InternalEvent → 现有 GroupMessage（字段语义与 router 现有产出一致）。"""
    arr = message_array if message_array is not None else copy.deepcopy(event.message_segments)
    return GroupMessage(
        group_id=event.group_id,
        user_id=event.actor_id,
        message_id=event.message_id,
        raw_message=full_text,
        message_array=arr,
        time=event.timestamp or 0,
        clean_text=clean_text,
        is_mentioned=is_mentioned if is_mentioned is not None else event.is_mentioned,
        is_reply_to_bot=(is_reply_to_bot if is_reply_to_bot is not None else event.is_reply_to_bot),
        has_reply_to_other=(has_reply_to_other if has_reply_to_other is not None
                            else event.has_reply_to_other),
        has_at_others=(has_at_others if has_at_others is not None else event.has_at_others),
        full_text=full_text,
    )


def convert_legacy(raw: dict, bot_qq: int) -> InternalEvent:
    """Legacy OneBot dict → InternalEvent（入口单点转换；供旧调用方/旧测试复用）。"""
    from src.adapters.onebot_parser import OneBotEventParser

    return OneBotEventParser(bot_qq=bot_qq).parse(raw)
