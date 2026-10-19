"""记忆更新 hook（从 MessageRouter 抽出，保持其行数护栏 ≤650）。

P1 权限边界：target 恒为当前用户；P3 隐私：禁用群不写记忆；
代码层闸门：写入前过 validate_memory_content（长度/QQ号/指令句式）。
"""
from typing import Optional

from src.core.sanitizer import validate_memory_content
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)


async def apply_memory_update(memory_manager, policy_engine, memory_update: Optional[str],
                              user_id: Optional[int], group_id: int, msg_id: str,
                              memory_disabled: bool) -> None:
    """处理一次回复携带的记忆更新；无记忆或被拒则静默跳过。"""
    if not memory_update or not user_id or memory_disabled:
        return
    target_uid, mem_content = policy_engine.parse_memory_update(memory_update, user_id)
    if not mem_content:
        return
    # 代码层闸门：校验记忆内容（长度/QQ号/指令句式），拒绝即丢弃并记日志
    mem_content = validate_memory_content(mem_content)
    if mem_content is None:
        logger.warning("记忆写入被代码层校验拒绝（疑似注入）: %s", (memory_update or "")[:60])
        return
    await memory_manager.append_memory_text(
        target_uid, group_id, mem_content,
        source_user=user_id,
        source_group=group_id,
        source_message_id=msg_id,
        confidence="model",
    )
    logger.info("memory_updated user=%s group=%s len=%d", target_uid, group_id, len(mem_content or ""),
                extra={"event": "memory_updated"})

