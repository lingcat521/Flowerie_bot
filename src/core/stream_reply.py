"""流式回复编排（Layer B router 侧）：真·流式 —— 边生成边发送。

独立模块目的：保持 message_router.py 行数护栏（≤650）。router 只保留极简调用。

与 dsh-qq-bridge 对齐的时序（v2.7.0 修复链路审计 W1/C1/C4/C5/C6）：
- guarded_stream 每刷出一段（句子缓冲 flush）→ 立即发送（零段间隔，C5）
- 记忆行（MEMORY_JSON: / 记忆: / 【记忆】）逐段剥离，绝不发给用户（C4/W3）
- 整轮只记一次连续回复/上下文/最近回复，合并文本一条（C1/C6）
- 三态结果（W4）：ok（至少发出一段）/ empty（成功但无产出）/ error（异常，调用方降级）

router 侧约定：handle_stream_reply 返回 (reply, memory_update, handled)。
handled=True 表示流式分支已自行完成发送（或兜底），不应再走 guarded_chat。
"""
from typing import Any, List, NamedTuple, Optional, Tuple

from src.services.reply_parser import split_memory_lines
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)

STREAM_OK = "ok"        # 流式成功且至少发出一段（含表情包）
STREAM_EMPTY = "empty"  # 流式成功但无可发送产出
STREAM_ERROR = "error"  # 流式异常（可能已有部分段发出，见 StreamOutcome.segments）


class StreamOutcome(NamedTuple):
    """流式一轮的结果。"""

    status: str
    segments: List[str]           # 实际已发出的文本段
    memory_update: Optional[str] = None
    error: Optional[BaseException] = None


def _process_segment(segment: str, *, policy_engine, sticker_manager, group_id: int):
    """一段刚刷出的文本 → (可发送文本, 表情包路径, 记忆更新)。

    - 记忆行剥离（split_memory_lines）：整段都是记忆行时无需发送
    - 表情包标记 [STICKER:文件名] 命中 → 返回图片路径并从文本剥离标记
    - 查重：与最近回复重复的段跳过（recent_reply 只在整轮结束记一条合并文本，C6）
    返回 (None, None, mem) 表示本段无需发送（含解析出的记忆）。
    """
    text, memory_update = split_memory_lines(segment)
    if not text or not text.strip():
        return None, None, memory_update
    sticker_path = None
    if sticker_manager is not None and sticker_manager.is_enabled():
        sticker_path = sticker_manager.extract_sticker(text)
        if sticker_path:
            text = sticker_manager.strip_sticker_marker(text)
    if not text or not text.strip():
        return None, sticker_path, memory_update
    if policy_engine is not None and policy_engine.is_duplicate_reply(group_id, text):
        logger.debug("stream segment duplicate, skip")
        return None, None, memory_update
    return text, sticker_path, memory_update


async def stream_reply_turn(gateway, group_id: int, user_id: int, user_message: str,
                            context: str, is_mentioned: bool, *,
                            sender, config, policy_engine,
                            sticker_manager=None) -> StreamOutcome:
    """跑一遍真·流式：每就绪一段立即发送；返回 StreamOutcome（不抛异常）。

    - error 态携带已发出的段（partial）：调用方据此决定「降级重发」还是「只补记账」
      —— 已发部分段后异常，降级重发整轮会造成重复刷屏（W1 修复点）
    - 记账不在本函数内：由 handle_stream_reply 在整轮结束后一次性完成（C1）
    """
    memory_update: Optional[str] = None
    sent: List[str] = []
    sticker_sent = False
    try:
        async for chunk in gateway.guarded_stream(
                group_id, user_id,
                user_message=user_message,
                context=context,
                is_mentioned=is_mentioned):
            for raw in chunk or []:
                if not raw:
                    continue
                text, sticker_path, mem = _process_segment(
                    raw, policy_engine=policy_engine,
                    sticker_manager=sticker_manager, group_id=group_id)
                if mem:
                    memory_update = mem
                if text is None and sticker_path is None:
                    continue
                if sticker_path is not None:
                    if sticker_manager is not None and sticker_manager.can_send(group_id):
                        sticker_manager.mark_sent(group_id)
                        ok = await sender.send_group_message_with_image(
                            group_id, text or None, sticker_path)
                    else:
                        logger.debug("Sticker cooldown, stream segment text only")
                        ok = await sender.send_group_message(group_id, text) if text else False
                    sticker_sent = sticker_sent or bool(ok)
                else:
                    ok = await sender.send_group_message(group_id, text)
                if ok and text:
                    sent.append(text)
    except Exception as e:  # noqa: BLE001 - 部分段可能已发出：交给调用方区分降级/补记账
        logger.warning("stream_reply_error group=%s sent=%d err=%s", group_id, len(sent), e,
                       extra={"event": "stream_reply_error", "sent": len(sent)})
        return StreamOutcome(STREAM_ERROR, sent, memory_update, e)
    if not sent and not sticker_sent:
        return StreamOutcome(STREAM_EMPTY, [], memory_update, None)
    logger.info("stream_reply_done group=%s segments=%d", group_id, len(sent),
                extra={"event": "stream_reply_done", "segments": len(sent)})
    return StreamOutcome(STREAM_OK, sent, memory_update, None)


def _record_turn(policy_engine, group_id: int, segments: List[str]) -> None:
    """整轮记账（C1/C6）：一次逻辑发言 = 一次连续回复 + 一条合并上下文 + 一条最近回复。"""
    merged = chr(10).join(s for s in segments if s)[:200]
    try:
        policy_engine.record_bot_reply(group_id)
        policy_engine.add_context(group_id, 0, merged, is_bot=True)
        policy_engine.add_recent_reply(group_id, merged)
    except Exception:  # noqa: BLE001 - 记账失败不影响已发送消息
        logger.debug("record stream turn failed for %s", group_id)


async def handle_stream_reply(*, gateway, sender, config, policy_engine, sticker_manager,
                              group_id: int, user_id: int, user_message: str, context: str,
                              is_mentioned: bool) -> Tuple[Any, Optional[str], bool]:
    """router 的流式分支：返回 (reply, memory_update, handled)。

    - error 且未发出任何段 → handled=False：router 降级到 guarded_chat（预算已由网关 refund）
    - error 但已发出部分段 → handled=True：只补记账，绝不降级重发（避免重复刷屏）
    - 成功有段 → (None, memory_update, True)：段已逐段即时发出
    - 成功但空 → ("喵？"或None, memory_update, True)：W4 兜底，不再二次请求
    """
    outcome = await stream_reply_turn(gateway, group_id, user_id, user_message, context,
                                      is_mentioned, sender=sender, config=config,
                                      policy_engine=policy_engine,
                                      sticker_manager=sticker_manager)
    if outcome.status == STREAM_ERROR:
        if outcome.segments:
            _record_turn(policy_engine, group_id, outcome.segments)
            logger.warning("stream_reply_partial group=%s sent=%d（不降级重发）",
                           group_id, len(outcome.segments),
                           extra={"event": "stream_reply_partial", "sent": len(outcome.segments)})
            return None, outcome.memory_update, True
        logger.warning("stream_reply_fallback group=%s err=%s", group_id, outcome.error,
                       extra={"event": "stream_reply_fallback"})
        return None, None, False
    if outcome.segments:
        _record_turn(policy_engine, group_id, outcome.segments)
        return None, outcome.memory_update, True
    # W4：流式成功但空产出 —— 不再触发 guarded_chat 二次请求；@场景给兜底回复
    if is_mentioned:
        return "喵？", outcome.memory_update, True
    return None, outcome.memory_update, True

