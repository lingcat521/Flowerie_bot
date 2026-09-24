"""Multi-Reply：SDK 层单测（Bot.send_many / reply_many / Event.reply_many）。

用假 adapter 验证：按顺序逐条发出、首条带 reply_id（后续不带）、返回 message_id 列表、
以及条数受 MULTI_REPLY_MAX_MESSAGES 约束。
"""
import pytest

from src.core.reply_plan import INTERVAL_NONE
from src.sdk.bot import Bot
from src.sdk.event import BotEvent


class FakeAdapter:
    def __init__(self):
        self.calls = []

    async def send(self, kind, target_id, message, reply_id=None):
        self.calls.append({"kind": kind, "target_id": target_id,
                           "message": str(message), "reply_id": reply_id})
        return len(self.calls)


class FakeConfig:
    MULTI_REPLY_MAX_MESSAGES = 3
    MULTI_REPLY_INTERVAL_MODE = INTERVAL_NONE
    MULTI_REPLY_MIN_INTERVAL = 0.0
    MULTI_REPLY_MAX_INTERVAL = 0.0


@pytest.mark.asyncio
async def test_send_many_sends_each_message():
    ad = FakeAdapter()
    bot = Bot(ad, config=FakeConfig())
    ids = await bot.send_many(12345, ["你好呀", "今天怎么样"])
    assert ids == [1, 2]
    assert [c["message"] for c in ad.calls] == ["你好呀", "今天怎么样"]
    assert all(c["kind"] == "group" and c["target_id"] == 12345 for c in ad.calls)


@pytest.mark.asyncio
async def test_send_many_respects_max_messages():
    ad = FakeAdapter()
    bot = Bot(ad, config=FakeConfig())
    await bot.send_many(1, ["1", "2", "3", "4", "5"])
    assert len(ad.calls) == 3          # 上限 3，AI/插件都绕不过


@pytest.mark.asyncio
async def test_reply_many_attaches_reply_id_only_to_first():
    ad = FakeAdapter()
    bot = Bot(ad, config=FakeConfig())
    event = BotEvent({"post_type": "message", "message_type": "group", "group_id": 777,
                      "user_id": 5, "message_id": 99, "raw_message": "hi"}, bot=bot)
    ids = await bot.reply_many(event, ["a", "b"])
    assert ids == [1, 2]
    assert ad.calls[0]["reply_id"] == 99
    assert ad.calls[1]["reply_id"] is None


@pytest.mark.asyncio
async def test_event_reply_many_delegates():
    ad = FakeAdapter()
    bot = Bot(ad, config=FakeConfig())
    event = BotEvent({"post_type": "message", "message_type": "group", "group_id": 1,
                      "user_id": 2, "message_id": 3, "raw_message": "hi"}, bot=bot)
    await event.reply_many(["x", "y"])
    assert [c["message"] for c in ad.calls] == ["x", "y"]
