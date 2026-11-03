"""Reply dispatch: single / fragmented replies with overflow buffering.

Splitting rules (only these, see reply_parser.parse_reply_content):
- total > SPLIT_REPLY_DISABLE_AT (100): whole reply, no fragments
- total < SPLIT_REPLY_LOWER (40): fragment by spaces and punctuation
- otherwise: whole reply

Anti-flood: at most SPLIT_REPLY_MAX_MESSAGES (3) fragments per burst.
Overflow fragments are buffered and sent after a 4-6s delay each.
"""
import asyncio
import random
from typing import Optional

from src.core.reply_plan import plan_from_config
from src.core.reply_splitter import SplitSegments
from src.core.reply_sender import MultiReplyError, send_plan
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)

_OVERFLOW_MIN_DELAY = 4.0
_OVERFLOW_MAX_DELAY = 6.0


class ReplyDispatchMixin:
    """Hosts must provide sender / config / policy_engine."""

    async def _send_reply(self, reply, *, group_id: Optional[int] = None,
                         user_id: Optional[int] = None,
                         record_key: Optional[int] = None) -> bool:
        """Send a reply: string (single) or SplitSegments (fragments)."""
        # 结构化表情包指令（解析层剥离出的控制标记，不依赖文本正则）
        sticker_names = list(getattr(reply, "stickers", None) or [])
        plan = plan_from_config(reply, self.config)
        if not plan:
            # 只有表情包、没有文本：直接发图
            if sticker_names and group_id:
                return await self._send_sticker_files(group_id, sticker_names)
            return False
        # 溢出缓存：plan 已被 clamped 到 3 句，多余片段原样保留在 reply 里
        overflow = []
        if isinstance(reply, SplitSegments) and len(plan.messages) < len(reply):
            overflow = [m for m in list(reply)[len(plan.messages):] if m]

        target = record_key if record_key is not None else (group_id if group_id else user_id)

        async def send_one(msg, _idx):
            if group_id:
                return await self.sender.send_group_message(group_id, msg)
            return await self.sender.send_private_message(user_id, msg)

        def after_sent(_idx, _res):
            if plan.count_as_one:
                if _idx != 0:
                    return
                text = chr(10).join(m for m in plan.messages if m)[:200]
            else:
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
        ok = all(bool(r) for r in results) if results else False
        if overflow and ok:
            kwargs = {"group_id": group_id} if group_id else {"user_id": user_id}
            if record_key is not None:
                kwargs["record_key"] = record_key
            asyncio.create_task(self._send_overflow(overflow, **kwargs))
            logger.info("fragment_overflow count=%d", len(overflow))
        # 表情包：文本发完后再单独发一条纯图（框架内部指令 → 独立消息）
        if ok and sticker_names and group_id:
            await self._send_sticker_files(group_id, sticker_names)
        return ok

    async def _maybe_attach_random_sticker(self, group_id: int, *, summoned: bool) -> None:
        """被召唤回复后按概率附一张随机表情包（受群级冷却约束）。"""
        if not summoned:
            return
        sm = getattr(self, "sticker_manager", None)
        if sm is None or not sm.is_enabled():
            return
        prob = float(getattr(self.config, "STICKER_REPLY_PROBABILITY", 0.0) or 0.0)
        if prob <= 0 or random.random() >= prob or not sm.can_send(group_id):
            return
        stickers = sm.repository.list_ok(limit=200)
        if not stickers:
            return
        pick = random.choice(stickers)
        path = sm.extract_sticker("[STICKER:%s]" % pick["filename"])
        if not path:
            return
        sm.mark_sent(group_id)
        if await self.sender.send_group_message_with_image(group_id, None, path):
            logger.info("sticker_attached group=%s file=%s", group_id, pick["filename"],
                        extra={"event": "sticker_attached"})

    async def _send_sticker_files(self, group_id: int, names: list) -> bool:
        """只发表情包（无正文）：解析层产出「仅图」回复时走这里。"""
        _sm = getattr(self, "sticker_manager", None)
        if _sm is None or not _sm.is_enabled() or not names:
            return False
        ok_any = False
        for name in names[:1]:
            if not _sm.can_send(group_id):
                logger.debug("sticker cooldown, skip %s", name)
                break
            path = _sm.extract_sticker("[STICKER:%s]" % name)
            if not path:
                logger.warning("sticker not found: %s", name)
                continue
            _sm.mark_sent(group_id)
            if await self.sender.send_group_message_with_image(group_id, None, path):
                ok_any = True
                try:
                    self.policy_engine.record_bot_reply(group_id)
                    self.policy_engine.add_context(group_id, 0, "[表情包]", is_bot=True)
                    self.policy_engine.add_recent_reply(group_id, "[表情包]")
                except Exception:
                    logger.debug("record sticker reply failed")
                logger.info("sticker_sent_only group=%s file=%s", group_id, name,
                            extra={"event": "sticker_sent_only"})
        return ok_any

    async def _send_overflow(self, messages, *, group_id=None, user_id=None,
                             record_key=None) -> None:
        """Send buffered overflow fragments with a 4-6s delay before each."""
        target = record_key if record_key is not None else (group_id if group_id else user_id)
        for msg in messages:
            await asyncio.sleep(random.uniform(_OVERFLOW_MIN_DELAY, _OVERFLOW_MAX_DELAY))
            try:
                _sm = getattr(self, "sticker_manager", None)
                if _sm is not None and _sm.is_enabled() and "[STICKER:" in str(msg):
                    _path = _sm.extract_sticker(str(msg))
                    if _path and _sm.can_send(group_id or 0):
                        _txt = _sm.strip_sticker_marker(str(msg))
                        _sm.mark_sent(group_id or 0)
                        msg = (_txt or None, _path)  # 图片发送元组
                if isinstance(msg, tuple):
                    ok = await self.sender.send_group_message_with_image(
                        group_id, msg[0], msg[1]) if group_id else False
                elif group_id:
                    ok = await self.sender.send_group_message(group_id, msg)
                else:
                    ok = await self.sender.send_private_message(user_id, msg)
                if ok:
                    self.policy_engine.record_bot_reply(target)
                    self.policy_engine.add_context(target, 0, msg, is_bot=True)
                    self.policy_engine.add_recent_reply(target, msg)
            except Exception:
                logger.warning("overflow send failed: %s", str(msg)[:60])
