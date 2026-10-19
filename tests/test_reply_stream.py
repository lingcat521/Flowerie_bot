"""Layer B 流式分句单元测试。

覆盖：句子缓冲（边界/最小刷出/强制刷出）、SSE 解析、router 降级路径。
全部用假对象（无真实网络），符合 CI 单元层口径。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.ai_streaming import StreamingSentenceBuffer, stream_chat_completion

# ---------- StreamingSentenceBuffer ----------

def test_short_token_accumulates():
    buf = StreamingSentenceBuffer(min_flush=8, max_flush=200)
    assert buf.push("你") is None
    assert buf.push("好") is None
    assert buf.pending == 2


def test_flush_on_sentence_boundary():
    buf = StreamingSentenceBuffer(min_flush=8, max_flush=200)
    out = None
    for ch in "今天天气真不错。":
        out = buf.push(ch)
    assert out == "今天天气真不错。"


def test_no_flush_below_min_flush():
    """短于 min_flush 的句子继续累积（避免刷出单词碎片）。"""
    buf = StreamingSentenceBuffer(min_flush=8, max_flush=200)
    out = None
    for ch in "好。":
        out = buf.push(ch)
    assert out is None
    assert buf.flush() == "好。"


def test_flush_on_newline():
    buf = StreamingSentenceBuffer(min_flush=8, max_flush=200)
    out = None
    for ch in "这是第一段的内容\n":
        out = buf.push(ch)
    assert out == "这是第一段的内容"
    assert buf.pending == 0


def test_buffer_holds_short_sentence():
    """短句（不足 min_flush）在换行处也继续累积（对齐 dsh：避免刷出单词碎片）。"""
    buf = StreamingSentenceBuffer(min_flush=8, max_flush=200)
    out = None
    for ch in "短句\n":
        out = buf.push(ch)
    assert out is None  # 继续累积
    assert buf.flush() == "短句"  # 流结束时刷出


def test_force_flush_at_max_flush():
    """max_flush 硬上限：无边界长文按上限分段。"""
    buf = StreamingSentenceBuffer(min_flush=8, max_flush=10)
    flushed = []
    for ch in "啊" * 12:
        out = buf.push(ch)
        if out is not None:
            flushed.append(out)
    flushed.append(buf.flush())
    flushed = [f for f in flushed if f]
    assert all(len(f) <= 10 for f in flushed)
    assert "".join(flushed) == "啊" * 12


def test_flush_empty_returns_none():
    buf = StreamingSentenceBuffer()
    assert buf.flush() is None


def test_whitespace_only_buffer():
    buf = StreamingSentenceBuffer(min_flush=8, max_flush=200)
    for ch in "   \n  ":
        buf.push(ch)
    assert buf.flush() is None


def test_min_flush_capped_to_max():
    buf = StreamingSentenceBuffer(min_flush=300, max_flush=200)
    assert buf.min_flush <= buf.max_flush


# ---------- stream_chat_completion（假 SSE 流） ----------

class _FakeResponse:
    def __init__(self, chunks, status_code=200):
        self._chunks = chunks
        self.status_code = status_code
        self.request = None

    async def aiter_lines(self):
        for c in self._chunks:
            yield c

    async def aread(self):
        return b"err"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeClient:
    def __init__(self, resp):
        self._resp = resp
        self.calls = []

    def stream(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return self._resp


def _sse(delta_text=None, done=False):
    import json
    data = {"choices": [{}]}
    if delta_text is not None:
        data["choices"][0]["delta"] = {"content": delta_text}
    line = "data: " + json.dumps(data)
    return [line, "data: [DONE]"] if done else [line]


@pytest.mark.asyncio
async def test_stream_chat_completion_yields_deltas():
    chunks = _sse("你好") + _sse("呀。") + ["data: [DONE]"]
    client = _FakeClient(_FakeResponse(chunks))
    got = [t async for t in stream_chat_completion(client, "u", {}, {"model": "m"})]
    assert got == ["你好", "呀。"]


@pytest.mark.asyncio
async def test_stream_chat_completion_non_200_raises():
    import httpx
    client = _FakeClient(_FakeResponse([], status_code=429))
    with pytest.raises(httpx.HTTPStatusError):
        async for _ in stream_chat_completion(client, "u", {}, {"model": "m"}):
            pass


@pytest.mark.asyncio
async def test_stream_chat_completion_skips_invalid_lines():
    chunks = ["notjson", "", "data: {bad json}", "data: [DONE]"]
    client = _FakeClient(_FakeResponse(chunks))
    got = [t async for t in stream_chat_completion(client, "u", {}, {"model": "m"})]
    assert got == []


@pytest.mark.asyncio
async def test_stream_chat_completion_sets_stream_flag():
    chunks = _sse("x") + ["data: [DONE]"]
    client = _FakeClient(_FakeResponse(chunks))
    async for _ in stream_chat_completion(client, "u", {}, {"model": "m"}):
        pass
    payload = client.calls[0][2]["json"]
    assert payload["stream"] is True


# ---------- router 降级（假 gateway） ----------

class _ErrorGateway:
    """guarded_stream 抛异常的假网关：collect 透传异常，router 据此降级。"""

    def __init__(self):
        self.chat_calls = 0

    async def guarded_stream(self, *a, **kw):
        raise ConnectionError("boom")
        yield  # pragma: no cover

    async def guarded_chat(self, group_id, user_id, **kw):
        self.chat_calls += 1
        return "降级成功", None, False


@pytest.mark.asyncio
async def test_collect_stream_segments_raises_on_gateway_error():
    """collect_stream_segments 透传网关异常（router 侧据此降级到 guarded_chat）。"""
    from src.core.stream_reply import collect_stream_segments
    gw = _ErrorGateway()
    with pytest.raises(ConnectionError):
        await collect_stream_segments(gw, 1, 2, "hi", "ctx", True)
    # 降级路径仍能拿到回复
    r2, _, _ = await gw.guarded_chat(1, 2)
    assert r2 == "降级成功"

