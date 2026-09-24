"""Native Reply Tool：AI 自主决定条数与消息边界（任务书 Phase 2-10）。

覆盖 Phase 10 的 12 类断言：
1 工具 schema；2 Tool Call → ReplyPlan；3 单条；4 自动裁剪；5 开关关闭；
6 连续回复计数；7 历史记录；8 失败不重发；9 OneBot 路径；10 Milky 路径；
11 provider 不支持 tool calling → 降级；12 普通文本 / 旧 JSON / Native Tool 三路径共存。

协议无关：本文件与实现一样，不 import OneBot / Milky。
"""
import io
import os

import pytest

from src.core.ai_gateway import AiGateway
from src.core.reply_dispatch import ReplyDispatchMixin
from src.core.reply_plan import INTERVAL_NONE, first_text, plan_from_config
from src.services.reply_tool import (
    MAX_CAPTURE_MESSAGES,
    REPLY_TOOL_NAME,
    REPLY_TOOL_SCHEMA,
    ReplyToolCapture,
    make_tool_caller,
    parse_reply_args,
)


# ---------- fakes ----------
class FakeConfig:
    MULTI_REPLY_ENABLED = True
    MULTI_REPLY_MAX_MESSAGES = 3
    MULTI_REPLY_INTERVAL_MODE = INTERVAL_NONE
    MULTI_REPLY_MIN_INTERVAL = 0.0
    MULTI_REPLY_MAX_INTERVAL = 0.0
    AI_MAX_RETRIES = 0
    BUDGET_EXHAUSTED_NOTICE = False
    MCP_MAX_TOOL_CALLS = 5


class FakeBudget:
    def check(self, *a, **k):
        return True, "ok"


class FakePolicy:
    def __init__(self):
        self.replies = []
        self.context = []
        self.recent = []

    def record_bot_reply(self, target):
        self.replies.append(target)

    def add_context(self, group_id, user_id, text, is_bot=False):
        self.context.append((group_id, text, is_bot))

    def add_recent_reply(self, group_id, text):
        self.recent.append(text)


class FakeSender:
    """同时扮演 OneBot / Milky 的发送入口（两条协议走的是同一对方法）。"""

    def __init__(self, fail_at=None):
        self.sent = []
        self.fail_at = fail_at

    async def send_group_message(self, group_id, message):
        if self.fail_at is not None and len(self.sent) == self.fail_at:
            raise RuntimeError("send failed")
        self.sent.append(("group", group_id, message))
        return True

    async def send_private_message(self, user_id, message):
        self.sent.append(("private", user_id, message))
        return True


class Host(ReplyDispatchMixin):
    def __init__(self, config=None, fail_at=None):
        self.config = config or FakeConfig()
        self.sender = FakeSender(fail_at=fail_at)
        self.policy_engine = FakePolicy()


class ToolCallingAI:
    """模型：调用 reply 工具，然后收尾输出空文本（真实 tool loop 的收敛形态）。"""

    _retryable = True
    _api_backoff = 0.0

    def __init__(self, payload):
        self.payload = payload
        self.seen_tools = None

    async def chat_once(self, **kwargs):
        self.seen_tools = [t["function"]["name"] for t in kwargs.get("tools", [])]
        if REPLY_TOOL_NAME in self.seen_tools:
            await kwargs["tool_caller"](REPLY_TOOL_NAME, {"messages": self.payload})
        return "", None


class PlainAI:
    _retryable = True
    _api_backoff = 0.0

    def __init__(self, reply):
        self.reply = reply

    async def chat_once(self, **kwargs):
        return self.reply, None


class NoToolSupportAI:
    """不支持 tool calling 的 provider：带 tools 的请求 4xx（不可重试）。"""

    def __init__(self):
        self._retryable = True
        self._api_backoff = 0.0
        self.tools_seen = []

    async def chat_once(self, **kwargs):
        has_tools = bool(kwargs.get("tools"))
        self.tools_seen.append(has_tools)
        if has_tools:
            self._retryable = False
            return None, None
        self._retryable = True
        return "降级后的纯文本", None


def _gateway(ai, config=None):
    return AiGateway(config or FakeConfig(), ai, FakeBudget(), persona_manager=lambda: None)


# ---------- 1. Tool Schema ----------
def test_tool_schema_shape():
    fn = REPLY_TOOL_SCHEMA["function"]
    assert REPLY_TOOL_SCHEMA["type"] == "function"
    assert fn["name"] == "reply"
    params = fn["parameters"]
    assert params["required"] == ["messages"]
    assert params["additionalProperties"] is False
    messages = params["properties"]["messages"]
    assert messages["type"] == "array" and messages["items"]["type"] == "string"
    assert messages["minItems"] == 1


def test_parse_reply_args_rejects_invalid():
    assert parse_reply_args({"messages": ["A", "B"]}) == ["A", "B"]
    assert parse_reply_args({"messages": []}) is None          # 空数组
    assert parse_reply_args({"messages": ["  "]}) is None      # 全空白
    assert parse_reply_args({"messages": [1, 2]}) is None      # 非字符串
    assert parse_reply_args({"messages": "A"}) is None         # 不是数组
    assert parse_reply_args({}) is None                        # 缺字段
    assert parse_reply_args(None) is None


def test_capture_is_idempotent_and_reports_to_model():
    cap = ReplyToolCapture()
    first = cap.capture({"messages": ["A", "B", "C"]})
    second = cap.capture({"messages": ["X"]})
    assert cap.messages == ["A", "B", "C"]
    assert "已记录" in first and "勿重复" in second
    assert cap.calls == 2
    bad = ReplyToolCapture().capture({"messages": []})
    assert "无效" in bad


@pytest.mark.asyncio
async def test_tool_caller_delegates_non_reply_tools():
    calls = []

    async def mcp(name, args):
        calls.append((name, args))
        return "mcp-ok"

    cap = ReplyToolCapture()
    caller = make_tool_caller(cap, mcp)
    assert await caller("search", {"q": "x"}) == "mcp-ok"
    assert calls == [("search", {"q": "x"})]
    assert await caller(REPLY_TOOL_NAME, {"messages": ["hi"]}) != ""
    assert cap.messages == ["hi"]
    no_mcp = make_tool_caller(ReplyToolCapture(), None)
    assert "不可用" in await no_mcp("search", {})


# ---------- 2/3. Tool Call → ReplyPlan，单条 ----------
@pytest.mark.asyncio
async def test_tool_call_becomes_reply_plan():
    ai = ToolCallingAI(["第一句", "第二句", "第三句"])
    reply, _mem, denied = await _gateway(ai).guarded_chat(group_id=1, user_id=2, user_message="hi")
    assert denied is False
    assert reply == ["第一句", "第二句", "第三句"]
    assert ai.seen_tools == [REPLY_TOOL_NAME]
    plan = plan_from_config(reply, FakeConfig())
    assert list(plan.messages) == ["第一句", "第二句", "第三句"]


@pytest.mark.asyncio
async def test_single_message_tool_call_sends_one():
    ai = ToolCallingAI(["只有一条"])
    reply, _m, _d = await _gateway(ai).guarded_chat(group_id=1, user_id=2, user_message="hi")
    host = Host()
    assert await host._send_reply(reply, group_id=7) is True
    assert [m for _, _, m in host.sender.sent] == ["只有一条"]
    assert host.policy_engine.replies == [7]


# ---------- 4. 自动裁剪 ----------
@pytest.mark.asyncio
async def test_ten_messages_clamped_to_configured_max():
    ai = ToolCallingAI(["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"])
    reply, _m, _d = await _gateway(ai).guarded_chat(group_id=1, user_id=2, user_message="hi")
    host = Host()                       # MULTI_REPLY_MAX_MESSAGES = 3
    await host._send_reply(reply, group_id=7)
    assert [m for _, _, m in host.sender.sent] == ["1", "2", "3"]


def test_parse_caps_absurd_message_count():
    msgs = parse_reply_args({"messages": ["x"] * (MAX_CAPTURE_MESSAGES + 5)})
    assert len(msgs) == MAX_CAPTURE_MESSAGES


# ---------- 5. Multi-Reply disabled ----------
@pytest.mark.asyncio
async def test_switch_off_never_injects_tool():
    class Off(FakeConfig):
        MULTI_REPLY_ENABLED = False

    ai = ToolCallingAI(["A", "B", "C"])
    reply, _m, _d = await _gateway(ai, Off()).guarded_chat(group_id=1, user_id=2, user_message="hi")
    assert ai.seen_tools == []          # 工具根本不注入
    assert reply == ""


def test_switch_off_clamps_even_if_plan_has_many():
    class Off(FakeConfig):
        MULTI_REPLY_ENABLED = False

    plan = plan_from_config(["A", "B", "C"], Off())
    assert list(plan.messages) == ["A"]


# ---------- 6/7. 连续回复计数与历史 ----------
@pytest.mark.asyncio
async def test_each_message_counts_once_for_consecutive_limit():
    host = Host()
    await host._send_reply(["a", "b", "c"], group_id=42)
    assert host.policy_engine.replies == [42, 42, 42]


@pytest.mark.asyncio
async def test_history_has_each_message_once():
    host = Host()
    await host._send_reply(["你好", "今天怎么样", "感觉你有点奇怪"], group_id=9)
    assert [t for _, t, _ in host.policy_engine.context] == ["你好", "今天怎么样", "感觉你有点奇怪"]
    assert host.policy_engine.recent == ["你好", "今天怎么样", "感觉你有点奇怪"]
    assert all(is_bot for _, _, is_bot in host.policy_engine.context)


# ---------- 8. 失败不重发 ----------
@pytest.mark.asyncio
async def test_failure_does_not_resend_first_message():
    host = Host(fail_at=1)              # 第二条失败
    ok = await host._send_reply(["一", "二", "三"], group_id=5)
    assert ok is False
    assert [m for _, _, m in host.sender.sent] == ["一"]
    assert host.policy_engine.replies == [5]


# ---------- 9/10. 协议无关 ----------
def test_tool_module_has_no_protocol_imports():
    """AST 级检查：真实 import 里不得出现协议 / 网络依赖（文档字符串里提到不算）。"""
    import ast

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "src", "services", "reply_tool.py")
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    banned = ("onebot", "milky", "napcat", "websocket", "aiohttp", "httpx", "sender")
    for mod in imported:
        for word in banned:
            assert word not in mod.lower(), "Native Reply Tool 不得依赖 %s（实际 import %s）" % (word, mod)


@pytest.mark.asyncio
async def test_same_path_for_group_and_private():
    """群聊（OneBot/Milky 群消息）与私聊走同一套分发：只有 sender 的方法不同。"""
    host = Host()
    await host._send_reply(["x", "y"], group_id=1)
    assert [c[0] for c in host.sender.sent] == ["group", "group"]
    host2 = Host()
    await host2._send_reply(["x", "y"], user_id=2)
    assert [c[0] for c in host2.sender.sent] == ["private", "private"]


# ---------- 11. provider 不支持 tool calling ----------
@pytest.mark.asyncio
async def test_provider_without_tool_support_downgrades():
    ai = NoToolSupportAI()
    reply, _m, denied = await _gateway(ai).guarded_chat(group_id=1, user_id=2, user_message="hi")
    assert denied is False
    assert reply == "降级后的纯文本"
    assert ai.tools_seen == [True, False]   # 第一次带工具被拒，第二次纯文本


# ---------- 12. 三路径共存 ----------
@pytest.mark.asyncio
async def test_plain_legacy_and_native_coexist():
    cfg = FakeConfig()
    plain = await _gateway(PlainAI("你好呀"), cfg).guarded_chat(group_id=1, user_id=2, user_message="hi")
    legacy = await _gateway(PlainAI(["你好", "今天怎么样"]), cfg).guarded_chat(
        group_id=1, user_id=2, user_message="hi")
    native = await _gateway(ToolCallingAI(["A", "B"]), cfg).guarded_chat(
        group_id=1, user_id=2, user_message="hi")
    assert [first_text(plain[0]), len(legacy[0]), len(native[0])] == ["你好呀", 2, 2]
    for reply in (plain[0], legacy[0], native[0]):
        host = Host()
        await host._send_reply(reply, group_id=3)
        assert host.sender.sent, reply


def test_plain_text_helper_handles_all_shapes():
    assert first_text(" x ") == "x"
    assert first_text(["", "y"]) == "y"
    assert first_text(()) == ""
    assert first_text(None) == ""