"""流式回复编排（Layer B router 侧）：从 AiGateway.guarded_stream 收集分段。

独立模块目的：保持 message_router.py 行数护栏（≤650）。router 只保留 3 行调用。
流式成功 → List[str]（每段是完整句子，经句子缓冲刷出）；
任何异常 → 抛回 router，由其降级到 guarded_chat 整轮请求（复用重试体系）。
"""
from typing import List, Optional

from src.utils.logging_setup import get_logger

logger = get_logger(__name__)


async def collect_stream_segments(gateway, group_id: int, user_id: int,
                                  user_message: str, context: str,
                                  is_mentioned: bool) -> Optional[List[str]]:
    """跑一遍流式分句；返回全部分段（None 表示开关未开或网关层拒绝）。

    异常透传：网络/HTTP/解析错误由调用方降级处理，本函数不吞错。
    """
    segments: List[str] = []
    async for chunk in gateway.guarded_stream(
            group_id, user_id,
            user_message=user_message,
            context=context,
            is_mentioned=is_mentioned):
        if chunk:
            segments.extend(chunk)
    if not segments:
        return None
    logger.info("stream_reply_done group=%s segments=%d", group_id, len(segments),
                extra={"event": "stream_reply_done", "segments": len(segments)})
    return segments

