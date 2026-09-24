"""回复分发 mixin：统一处理「单条 / 多条」回复的发送（防上帝类：从 MessageRouter 拆出）。

任务书 §7/§9/§10：条数与间隔由 Core 配置决定，AI 无权绕过；每条都计一次连续回复，
于是 MAX_CONSECUTIVE_REPLIES 依然生效。协议无关：只调用 sender 的既有方法。
"""
from typing import Optional

from src.core.reply_plan import plan_from_config
from src.core.reply_sender import MultiReplyError, send_plan
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)


class ReplyDispatchMixin:
    """宿主需提供 sender / config / policy_engine。"""

    async def _send_reply(self, reply, *, group_id: Optional[int] = None,
                         user_id: Optional[int] = None) -> bool:
        """发送回复：字符串（单条）与列表（多条）都走这里。"""
        plan = plan_from_config(reply, self.config)
        if not plan:
            return False

        async def send_one(msg, _idx):
            if group_id:
                return await self.sender.send_group_message(group_id, msg)
            return await self.sender.send_private_message(user_id, msg)

        def after_sent(_idx, _res):
            """每条都记一次：连续回复计数 + 上下文 + 最近回复（任务书 §10/§11）。

            只在成功发出后记录，且**一条记一次** —— 调用点不要再重复记录，
            否则连续回复会被双倍计数、冷却提前触发。
            """
            target = group_id if group_id else user_id
            text = plan.messages[_idx] if _idx < len(plan.messages) else ""
            try:
                self.policy_engine.record_bot_reply(target)
                self.policy_engine.add_context(target, 0, text, is_bot=True)
                self.policy_engine.add_recent_reply(target, text)
            except Exception:
                logger.debug("record reply failed for %s", target)

        try:
            results = await send_plan(plan, send_one, on_sent=after_sent)
        except MultiReplyError as exc:
            logger.warning("multi_reply_partial sent=%d failed_at=%d", len(exc.sent), exc.failed_index)
            return False
        return all(bool(r) for r in results) if results else False
