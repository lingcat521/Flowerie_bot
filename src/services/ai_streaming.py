"""流式分句（Layer B）：SSE 增量 + 句子缓冲，对齐 dsh-qq-bridge plugin.ts 的分句缓冲。

机制：模型按 token 生成增量 → 累积进缓冲区 → 命中句尾标点/换行且达到最小刷出长度，
或达到缓冲上限时，作为整段产出（flush）。兼顾「及时性」与「可读性」：
逐 token 发会在聊天框刷出单词；整轮等完又失去流式意义。

- StreamingSentenceBuffer：纯缓冲逻辑（不接触网络/协议）
- stream_chat_completion：OpenAI 兼容 SSE 流式请求（httpx stream）
两者独立可测，AIClient 只做轻量委托（ai_client.py 行数护栏 ≤430）。
"""
import json
import re
from typing import AsyncIterator, List, Optional

import httpx

from src.utils.logging_setup import get_logger

logger = get_logger(__name__)

# 句尾边界（对齐 dsh-qq-bridge sentenceBoundary = /[。！？!?；;\n]$/）
_SENTENCE_BOUNDARY = re.compile(r"[。！？!?；;\n]$")


class StreamingSentenceBuffer:
    """句子缓冲：push(token) → 达到边界刷出整段。

    - MIN_FLUSH：累积达此长度且命中句尾标点/换行才刷出（过短的单句并入下一段）
    - MAX_FLUSH：无边界时强制刷出的硬上限（避免无限增长）
    """

    def __init__(self, min_flush: int = 8, max_flush: int = 200):
        self.min_flush = max(1, int(min_flush))
        self.max_flush = max(self.min_flush, int(max_flush))
        self._buf = ""

    def push(self, token: str) -> Optional[str]:
        """写入一个增量；返回刷出的整段（None 表示继续累积）。"""
        if not token:
            return None
        self._buf += token
        if len(self._buf) >= self.max_flush:
            return self.flush()
        if len(self._buf) >= self.min_flush and _SENTENCE_BOUNDARY.search(self._buf):
            return self.flush()
        return None

    def flush(self) -> Optional[str]:
        """强制刷出剩余缓冲（流结束时调用）。"""
        if not self._buf.strip():
            self._buf = ""
            return None
        out, self._buf = self._buf, ""
        return out.strip() or None

    @property
    def pending(self) -> int:
        return len(self._buf)


async def stream_chat_completion(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    payload: dict,
) -> AsyncIterator[str]:
    """发起 OpenAI 兼容流式请求，yield 文本增量（delta.content）。

    payload 由调用方准备（加 stream=True 的责任在本函数内部完成）。
    网络错误 or 非 2xx 时抛出异常（调用方降级到非流式路径）。
    """
    stream_payload = dict(payload)
    stream_payload["stream"] = True
    timeout = httpx.Timeout(30.0, read=None)  # 流式读不设超时（依赖 keepalive）
    async with client.stream("POST", url, headers=headers, json=stream_payload, timeout=timeout) as resp:
        if resp.status_code != 200:
            body = await resp.aread()
            logger.error("stream api HTTP %s: %s", resp.status_code, body[:200])
            raise httpx.HTTPStatusError(
                "stream api returned %s" % resp.status_code, request=resp.request, response=resp)
        async for line in resp.aiter_lines():
            if not line or not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                return
            try:
                chunk = json.loads(data)
            except (json.JSONDecodeError, ValueError):
                continue
            delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
            text = delta.get("content")
            if text:
                yield text


async def stream_reply_segments(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    payload: dict,
    min_flush: int = 8,
    max_flush: int = 200,
) -> AsyncIterator[List[str]]:
    """完整流式分句管道：SSE 增量 → 句子缓冲 → 逐段 yield（每段是一段完整句子）。

    供 message_router 的流式路径使用：每 yield 一段即可发送一条 QQ 消息。
    """
    buf = StreamingSentenceBuffer(min_flush=min_flush, max_flush=max_flush)
    async for token in stream_chat_completion(client, url, headers, payload):
        segment = buf.push(token)
        if segment:
            yield [segment]
    tail = buf.flush()
    if tail:
        yield [tail]

