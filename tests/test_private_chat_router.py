"""v2.14.2 链路实测：真实 MessageRouter + process_event 走通「私聊 / 群聊」两条消息链路。

与 tests/test_private_chat.py（处理器级替身）互补：这里用真路由器、真 PolicyEngine、
真 CommandHandler，只在最外层替换 AI / Sender，专门验证 dispatch（process_event）没断。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.budget_manager import BudgetManager  # noqa: E402
from src.core.command_handler import CommandHandler  # noqa: E402
from src.core.message_router import MessageRouter  # noqa: E402
from src.core.policy_engine import PolicyEngine  # noqa: E402
from tests.test_router_regression import (  # noqa: E402
    FakeAIClient, FakeAssembler, FakeFileParser, FakeMemoryManager, FakeSender, make_config
)


class ReplyAIClient(FakeAIClient):
    """返回固定回复 + 一条记忆更新，用来验证记忆落库链路。"""

    async def chat_once(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        return "喵", "用户喜欢猫",


class RecordingSender(FakeSender):
    def __init__(self):
        super().__init__()
        self.private = []

    async def send_private_message(self, user_id, message):
        self.private.append((user_id, message))
        return True


def build_private_router():
    config = make_config(
        PRIVATE_CHAT_ENABLED=True,
        PRIVATE_CHAT_ALLOWED_QQS=[456],
        PRIVATE_CHAT_COOLDOWN_SECONDS=0,
        PRIVATE_CHAT_ALLOW_STRANGERS=False,
        PRIVATE_CHAT_CONTEXT_SIZE=40,
        PRIVATE_CHAT_MEMORY_ENABLED=True,
        ADMIN_QQ_IDS=[999],
    )
    ai = ReplyAIClient()
    sender = RecordingSender()
    mm = FakeMemoryManager()
    policy = PolicyEngine(config, mm)
    router = MessageRouter(config, ai, mm, FakeFileParser(), sender, policy)
    router.assembler = FakeAssembler()
    router.commands = CommandHandler(config, sender, mm)
    router.budget = BudgetManager(config, policy.global_state, sender)
    return router, config, ai, sender, mm


def _group_event(text="你好", gid=123, uid=456, mid=1):
    return {"post_type": "message", "message_type": "group", "group_id": gid,
            "user_id": uid, "message_id": mid, "time": 1700000000,
            "message": [{"type": "text", "data": {"text": text}}]}


def _private_event(text="你好", uid=456, mid=2):
    return {"post_type": "message", "message_type": "private",
            "user_id": uid, "message_id": mid, "time": 1700000001,
            "message": [{"type": "text", "data": {"text": text}}]}


def test_private_event_flows_through_real_router():
    router, _config, ai, sender, mm = build_private_router()
    asyncio.run(router.process_event(_private_event("在吗")))
    assert ai.calls == 1, "私聊消息应走到 AI"
    assert sender.private and sender.private[-1][0] == 456, sender.private
    assert sender.private[-1][1] == "喵", sender.private
    # 记忆用虚拟 key（-QQ）落库，与群聊隔离
    assert mm.writes and mm.writes[-1][0] == 456 and mm.writes[-1][1] == -456, mm.writes


def test_private_event_creates_isolated_context():
    router, _config, _ai, _sender, _mm = build_private_router()
    asyncio.run(router.process_event(_private_event("只属于 456", uid=456, mid=3)))
    assert router.policy_engine.get_context_text(-456), "私聊应写入自己的上下文"
    assert not router.policy_engine.get_context_text(456), "不得串到真实群 456"


def test_group_event_still_flows_after_private_branch():
    router, _config, ai, sender, _mm = build_private_router()
    router.policy_engine.should_reply_by_context = lambda gid: False
    asyncio.run(router.process_event(_group_event("@bot 你好", mid=4)))
    # 未 @ 且概率关掉 → 不回复，但链路不应抛错；再 @ 一次验证能回复
    asyncio.run(router.process_event({
        "post_type": "message", "message_type": "group", "group_id": 123,
        "user_id": 456, "message_id": 5, "time": 1700000002,
        "message": [{"type": "at", "data": {"qq": "10001"}},
                    {"type": "text", "data": {"text": " 你好"}}],
    }))
    assert ai.calls >= 1
    assert sender.sent, "群聊链路应照常回复"


def test_private_disabled_blocks_router_path():
    router, config, ai, sender, _mm = build_private_router()
    config.PRIVATE_CHAT_ENABLED = False
    asyncio.run(router.process_event(_private_event("在吗", mid=6)))
    assert ai.calls == 0 and sender.private == []
