"""Layer B 流式分句单元测试。

覆盖：句子缓冲（边界/最小刷出/强制刷出）、SSE 解析、真流式编排（W1 边生成边发、
W4 三态、C1 整轮一次记账、C4 记忆剥离、C6 逐段查重/表情包）。
全部用假对象（无真实网络/协议），符合 CI 单元层口径。
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


# ---------- handle_stream_reply（假 gateway/sender/policy/sticker） ----------
# 真流式时序（W1）：段到即发；三态结果（W4）；C1 整轮一次记账；C4 记忆剥离。

import types

from src.core.stream_reply import handle_stream_reply


class _FakePolicy:
    """策略引擎替身：查重 / 记账收集（不依赖真实 PolicyEngine/SQLite）。"""

    def __init__(self, duplicates=()):
        self._duplicates = set(duplicates)
        self.replies, self.contexts, self.recent = [], [], []

    def is_duplicate_reply(self, group_id, reply):
        return reply in self._duplicates

    def record_bot_reply(self, group_id):
        self.replies.append(group_id)

    def add_context(self, group_id, user_id, message, is_bot=False):
        self.contexts.append(message)

    def add_recent_reply(self, group_id, reply):
        self.recent.append(reply)


class _FakeSender:
    """sender 替身：记录发出的文本与图片对。"""

    def __init__(self):
        self.sent, self.images = [], []

    async def send_group_message(self, group_id, message, retries=2):
        self.sent.append(message)
        return True

    async def send_group_message_with_image(self, group_id, text, image_path, retries=2):
        self.images.append((text, image_path))
        return True


class _FakeStickers:
    def __init__(self, path=None):
        self._path = path
        self.marks = 0

    def is_enabled(self):
        return True

    def extract_sticker(self, text):
        return self._path

    def strip_sticker_marker(self, text):
        return text.replace("[STICKER:x.png]", " ").strip()

    def can_send(self, group_id):
        return True

    def mark_sent(self, group_id):
        self.marks += 1


class _StreamGateway:
    """受控 guarded_stream：按给定片段序列逐段 yield；fail_at=N 时在第 N 段前抛异常。"""

    def __init__(self, chunks, fail_at=None):
        self._chunks = chunks
        self._fail_at = fail_at
        self.kwargs_seen = None

    async def guarded_stream(self, group_id, user_id, **kwargs):
        self.kwargs_seen = kwargs
        for i, c in enumerate(self._chunks):
            if self._fail_at is not None and i == self._fail_at:
                raise ConnectionError("mid-stream boom")
            yield c


class _ErrorGateway:
    """guarded_stream 立即抛异常（未产出任何段）的假网关。"""

    async def guarded_stream(self, *a, **kw):
        raise ConnectionError("boom")
        yield  # pragma: no cover


async def _run(chunks, *, mentioned=True, duplicates=(), sticker_path=None, fail_at=None, gateway=None):
    gw = gateway or _StreamGateway(chunks, fail_at=fail_at)
    sender = _FakeSender()
    stickers = _FakeStickers(sticker_path)
    policy = _FakePolicy(duplicates=duplicates)
    result = await handle_stream_reply(
        gateway=gw, sender=sender, config=types.SimpleNamespace(),
        policy_engine=policy, sticker_manager=stickers,
        group_id=1, user_id=2, user_message="hi", context="ctx",
        is_mentioned=mentioned)
    return result, gw, sender, stickers, policy


@pytest.mark.asyncio
async def test_segments_sent_immediately_in_order():
    """W1：段到了就发（handle 返回时已全部发出），而不是攒完再发。"""
    result, _, sender, _, _ = await _run([["第一段。"], ["第二段。"], ["第三段。"]])
    assert sender.sent == ["第一段。", "第二段。", "第三段。"]
    assert result == (None, None, True)


@pytest.mark.asyncio
async def test_gateway_receives_prompt_and_context():
    _, gw, _, _, _ = await _run([["x。"]])
    assert gw.kwargs_seen["user_message"] == "hi"
    assert gw.kwargs_seen["context"] == "ctx"
    assert gw.kwargs_seen["is_mentioned"] is True


@pytest.mark.asyncio
async def test_records_one_turn_with_merged_text():
    """C1：整轮一次记账（连续回复/上下文/最近回复），上下文为合并文本一条。"""
    result, _, _, _, policy = await _run([["第一段。"], ["第二段。"]])
    assert policy.replies == [1]
    assert policy.contexts == ["第一段。" + chr(10) + "第二段。"]
    assert policy.recent == ["第一段。" + chr(10) + "第二段。"]


@pytest.mark.asyncio
async def test_memory_json_line_never_sent():
    """C4/W3：MEMORY_JSON 行剥离不发送，记忆写回（流式路径不再泄漏记忆指令）。"""
    chunks = [["说正事。" + chr(10) + 'MEMORY_JSON:{"text":"喜欢奶茶"}']]
    result, _, sender, _, _ = await _run(chunks)
    assert sender.sent == ["说正事。"]
    assert result[1] == "喜欢奶茶"


@pytest.mark.asyncio
async def test_chinese_memory_prefix_stripped():
    chunks = [["说正事。" + chr(10) + "【记忆】怕黑"]]
    result, _, sender, _, _ = await _run(chunks)
    assert sender.sent == ["说正事。"]
    assert result[1] == "【记忆】怕黑"


@pytest.mark.asyncio
async def test_memory_only_segment_sends_nothing():
    """整段都是记忆行：不发送，记忆仍写回（empty 态由 is_mentioned 决定兜底）。"""
    result, _, sender, _, _ = await _run([['MEMORY_JSON:{"text":"怕黑"}']], mentioned=False)
    assert sender.sent == []
    assert result == (None, "怕黑", True)


@pytest.mark.asyncio
async def test_sticker_only_segment_sent_as_image():
    """C6：表情包标记不一定出现在首段 —— 逐段识别，标记段发图片。"""
    result, _, sender, stickers, _ = await _run([["[STICKER:x.png]"]], sticker_path="x.png")
    assert sender.sent == []
    assert sender.images == [(None, "x.png")]
    assert stickers.marks == 1


@pytest.mark.asyncio
async def test_sticker_with_text_sends_image_plus_text():
    result, _, sender, stickers, _ = await _run([["配文[STICKER:x.png]"]], sticker_path="x.png")
    assert sender.images == [("配文", "x.png")]
    assert stickers.marks == 1


@pytest.mark.asyncio
async def test_duplicate_segment_skipped_but_new_one_sent():
    """C6：逐段查重；重复段跳过，新段照发。"""
    result, _, sender, _, _ = await _run([["复读。"], ["新内容。"]], duplicates=("复读。",))
    assert sender.sent == ["新内容。"]


@pytest.mark.asyncio
async def test_error_before_any_send_falls_back():
    """W4/error：未发出任何段 → handled=False，router 降级到 guarded_chat。"""
    sender = _FakeSender()
    policy = _FakePolicy()
    result = await handle_stream_reply(
        gateway=_ErrorGateway(), sender=sender, config=types.SimpleNamespace(),
        policy_engine=policy, sticker_manager=_FakeStickers(),
        group_id=1, user_id=2, user_message="hi", context="ctx", is_mentioned=True)
    assert result == (None, None, False)
    assert policy.replies == []  # 降级路径的记账由 guarded_chat 承担


@pytest.mark.asyncio
async def test_partial_send_does_not_re_fall_back():
    """W1 关键：已发出部分段后异常 → 只补记账，不降级重发（否则重复刷屏）。"""
    result, _, sender, _, policy = await _run([["第一段。"], ["第二段。"]], fail_at=1)
    assert sender.sent == ["第一段。"]
    assert result[2] is True
    assert policy.replies == [1]
    assert policy.contexts == ["第一段。"]


@pytest.mark.asyncio
async def test_empty_stream_mentioned_gets_fallback_reply():
    """W4：流式成功但空产出 → @场景给兜底回复，不再二次请求（双倍预算）。"""
    result, _, sender, _, _ = await _run([["   "]])
    assert result == ("喵？", None, True)
    assert sender.sent == []


@pytest.mark.asyncio
async def test_empty_stream_not_mentioned_stays_silent():
    result, _, sender, _, _ = await _run([["   "]], mentioned=False)
    assert result == (None, None, True)
    assert sender.sent == []


def test_stream_outcome_status_constants():
    """W5 的 budget refund 在网关层（ai_gateway.guarded_stream）；编排层只暴露三态。"""
    from src.core.stream_reply import STREAM_EMPTY, STREAM_ERROR, STREAM_OK
    assert (STREAM_OK, STREAM_EMPTY, STREAM_ERROR) == ("ok", "empty", "error")
