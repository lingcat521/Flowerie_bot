"""Multi-Reply：发送分发 mixin 的行为测试（防重复计数 / 逐条记历史）。"""
import pytest

from src.core.reply_dispatch import ReplyDispatchMixin
from src.core.reply_plan import INTERVAL_NONE


class FakePolicy:
    def __init__(self):
        self.replies = []      # record_bot_reply 的调用（连续回复计数）
        self.context = []      # add_context
        self.recent = []       # add_recent_reply

    def record_bot_reply(self, target):
        self.replies.append(target)

    def add_context(self, group_id, user_id, text, is_bot=False):
        self.context.append((group_id, text, is_bot))

    def add_recent_reply(self, group_id, text):
        self.recent.append(text)


class FakeSender:
    def __init__(self):
        self.sent = []

    async def send_group_message(self, group_id, message):
        self.sent.append(("group", group_id, message))
        return True

    async def send_private_message(self, user_id, message):
        self.sent.append(("private", user_id, message))
        return True


class FakeConfig:
    MULTI_REPLY_ENABLED = True
    MULTI_REPLY_MAX_MESSAGES = 3
    MULTI_REPLY_INTERVAL_MODE = INTERVAL_NONE
    MULTI_REPLY_MIN_INTERVAL = 0.0
    MULTI_REPLY_MAX_INTERVAL = 0.0


class Host(ReplyDispatchMixin):
    def __init__(self):
        self.config = FakeConfig()
        self.sender = FakeSender()
        self.policy_engine = FakePolicy()


@pytest.mark.asyncio
async def test_multi_reply_records_each_message_once():
    h = Host()
    ok = await h._send_reply(["第一句", "第二句", "第三句"], group_id=777)
    assert ok is True
    assert [m for _, _, m in h.sender.sent] == ["第一句", "第二句", "第三句"]
    # 每条记一次（不是一次，也不是每条两次）
    assert h.policy_engine.replies == [777, 777, 777]
    assert [t for _, t, _ in h.policy_engine.context] == ["第一句", "第二句", "第三句"]
    assert h.policy_engine.recent == ["第一句", "第二句", "第三句"]


@pytest.mark.asyncio
async def test_single_string_still_works_and_records_once():
    h = Host()
    ok = await h._send_reply("你好", group_id=1)
    assert ok is True
    assert h.sender.sent == [("group", 1, "你好")]
    assert h.policy_engine.replies == [1]
    assert h.policy_engine.context == [(1, "你好", True)]


@pytest.mark.asyncio
async def test_private_target_uses_private_sender():
    h = Host()
    await h._send_reply(["a", "b"], user_id=9527)
    assert h.sender.sent == [("private", 9527, "a"), ("private", 9527, "b")]
    assert h.policy_engine.replies == [9527, 9527]


@pytest.mark.asyncio
async def test_disabled_multi_reply_sends_only_first():
    class Off(FakeConfig):
        MULTI_REPLY_ENABLED = False

    h = Host()
    h.config = Off()
    await h._send_reply(["1", "2", "3"], group_id=5)
    assert [m for _, _, m in h.sender.sent] == ["1"]


@pytest.mark.asyncio
async def test_empty_reply_sends_nothing():
    h = Host()
    ok = await h._send_reply(None, group_id=1)
    assert ok is False
    assert h.sender.sent == [] and h.policy_engine.replies == []
