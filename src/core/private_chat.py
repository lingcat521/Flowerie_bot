"""私聊会话（v2.14.0）：按 QQ 号隔离的上下文 / 记忆 / 人格 / AI 对话。

隔离设计：私聊用「虚拟群号」 -user_id 作为上下文、记忆、人格、预算、冷却的 key。
QQ 群号恒为正数，负 key 不会与真实群冲突；用户之间、用户与群之间天然隔离。
消息出站走 sender.send_private_message，入库与预算记账仍用虚拟 key（不串号）。
"""
import time

from src.core.memory_hook import apply_memory_update
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)


def private_key(user_id: int) -> int:
    """私聊的虚拟会话 key（负数，永不与真实群号冲突）。"""
    return -int(user_id)


def allowed_qqs(config) -> set:
    """允许私聊的 QQ 集合：PRIVATE_CHAT_ALLOWED_QQS ∪ ADMIN_QQ_IDS（管理员总能私聊）。"""
    ids = set()
    for raw in list(getattr(config, "PRIVATE_CHAT_ALLOWED_QQS", None) or []) + \
            list(getattr(config, "ADMIN_QQ_IDS", None) or []):
        try:
            ids.add(int(raw))
        except (TypeError, ValueError):
            continue
    return ids


def is_allowed(config, user_id: int) -> bool:
    return int(user_id) in allowed_qqs(config)


def _cooldown_ok(host, user_id: int, seconds: int) -> bool:
    """每人独立冷却（放在 host 上，避免模块级全局状态影响多实例测试）。"""
    store = getattr(host, "_private_last_ts", None)
    if store is None:
        store = {}
        setattr(host, "_private_last_ts", store)
    now = time.monotonic()
    if seconds > 0 and now - float(store.get(user_id, 0.0)) < seconds:
        return False
    store[user_id] = now
    if len(store) > 2000:
        store.clear()
    return True


async def handle_private_event(host, event) -> None:
    """私聊消息入口（由 MessageRouter.process_event 分派）。"""
    config = host.config
    if not getattr(config, "PRIVATE_CHAT_ENABLED", False):
        return
    if event.kind != "message":
        return
    user_id = int(event.actor_id or 0)
    if user_id <= 0:
        return
    scene = str(getattr(event, "scene", "") or "friend")
    if scene in ("temp", "stranger") and not getattr(config, "PRIVATE_CHAT_ALLOW_STRANGERS", False):
        logger.info("private_rejected user=%s reason=scene:%s", user_id, scene,
                    extra={"event": "private_rejected"})
        return
    if not is_allowed(config, user_id):
        logger.info("private_rejected user=%s reason=not_allowed", user_id,
                    extra={"event": "private_rejected"})
        return
    if not _cooldown_ok(host, user_id, int(getattr(config, "PRIVATE_CHAT_COOLDOWN_SECONDS", 3) or 0)):
        logger.debug("private_cooldown user=%s", user_id)
        return
    key = private_key(user_id)
    state = host.policy_engine.get_group_state(key)
    msg_id = event.message_id
    if msg_id is not None:
        if msg_id in state.processed_msg_ids:
            return
        state.processed_msg_ids.append(msg_id)
    raw_time = event.timestamp or int(time.time())
    full_text, image_descriptions, *_ = await host.assembler.assemble(event, user_id, key, raw_time)
    if full_text:
        host.policy_engine.add_context(key, user_id, full_text[:200], is_bot=False, digest_text=full_text)
    text = str(event.text or "").strip()
    if text.startswith("/") and await host.commands.handle(text, user_id, key, private_user_id=user_id):
        return
    if not text and not image_descriptions:
        return
    if not await host.ai_gateway.precheck_allowed(key, user_id):
        logger.info("private_budget_rejected user=%s", user_id, extra={"event": "budget_rejected"})
        return
    context_text = host.policy_engine.get_context_text(
        key, max_messages=max(1, int(getattr(config, "PRIVATE_CHAT_CONTEXT_SIZE", 40) or 40)))
    user_prompt = full_text.strip()
    if not user_prompt and image_descriptions:
        user_prompt = "用户刚刚发了一张图片，图片内容：%s" % "; ".join(image_descriptions)
    if not user_prompt:
        return
    reply, memory_update, denied = await host.guarded_chat(
        key, user_id, user_message=user_prompt, context=context_text, is_mentioned=False)
    if denied:
        logger.info("private_budget_rejected user=%s", user_id, extra={"event": "budget_rejected"})
        return
    await apply_memory_update(
        host.memory_manager, host.policy_engine, memory_update, user_id, key, str(msg_id or ""),
        not bool(getattr(config, "PRIVATE_CHAT_MEMORY_ENABLED", True)))
    if not reply:
        return
    ok = await host._send_reply(reply, user_id=user_id, record_key=key)
    logger.info("private_reply_sent user=%s ok=%s len=%d", user_id, ok, len(str(reply)),
                extra={"event": "private_reply_sent"})
