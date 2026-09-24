"""Multi-Reply 端到端串联测试：AI 结构化多条 → ReplyPlan → 逐条发送 + 历史记录。

覆盖任务书的核心承诺：
- 模型给出多条结构 → 真的发多条（顺序正确、间隔受策略控制）
- 未开启开关 / JSON 不合法 → 自动降级为单条（绝不让整轮回复失败）
- 每条都记一次：连续回复计数 + 上下文 + 最近回复
"""
import pytest

from src.core.reply_dispatch import ReplyDispatchMixin
from src.core.reply_plan import INTERVAL_NONE, plan_from_config


class FakePolicy:
    def __init__(self):
        self.replies, self.context, self.recent = [], [], []

    def record_bot_reply(self, target):
        self.replies.append(target)

    def add_context(self, group_id, user_id, text, is_bot=False):
        self.context.append(text)

    def add_recent_reply(self, group_id, text):
        self.recent.append(text)


class FakeSender:
    def __init__(self):
        self.sent = []

    async def send_group_message(self, group_id, message):
        self.sent.append(message)
        return True

    async def send_private_message(self, user_id, message):
        self.sent.append(message)
        return True


class FakeConfig:
    MULTI_REPLY_ENABLED = True
    MULTI_REPLY_MAX_MESSAGES = 3
    MULTI_REPLY_INTERVAL_MODE = INTERVAL_NONE
    MULTI_REPLY_MIN_INTERVAL = 0.0
    MULTI_REPLY_MAX_INTERVAL = 0.0
    MAX_REPLY_LENGTH = 40


class Host(ReplyDispatchMixin):
    def __init__(self, cfg=None):
        self.config = cfg or FakeConfig()
        self.sender = FakeSender()
        self.policy_engine = FakePolicy()


@pytest.mark.asyncio
async def test_ai_multi_json_flows_to_multiple_sends():
    """模型输出 {"messages": [...]} → 逐条发出，且每条都进历史。"""
    # 提取环节由 tests/test_multi_reply_ai.py 覆盖（只认完整 JSON、非法降级）：
    # 这里从"已提取出的多条"开始，验证 Core 侧的计划 → 发送 → 历史 全链路。
    messages = ["你好呀", "今天怎么样", "最近还好吗"]

    h = Host()
    plan = plan_from_config(messages, h.config, from_ai=True)
    assert plan.from_ai is True and len(plan) == 3

    ok = await h._send_reply(plan.messages, group_id=777)
    assert ok is True
    assert h.sender.sent == ["你好呀", "今天怎么样", "最近还好吗"]
    assert h.policy_engine.replies == [777, 777, 777]
    assert h.policy_engine.context == ["你好呀", "今天怎么样", "最近还好吗"]


@pytest.mark.asyncio
async def test_ai_multi_is_capped_by_config():
    """模型想发 5 条，配置上限 2 → 只发前 2 条（AI 绕不过）。"""
    messages = ["1", "2", "3", "4", "5"]          # 模型想发 5 条
    h = Host()
    h.config = type("C", (FakeConfig,), {"MULTI_REPLY_MAX_MESSAGES": 2})()
    await h._send_reply(messages, group_id=1)
    assert h.sender.sent == ["1", "2"]


@pytest.mark.asyncio
async def test_invalid_ai_json_degrades_to_single_message():
    """JSON 不合法 → 抽取返回 None → 调用方走单条路径（不失败）。"""
    # 解析失败时上游会退回单条字符串（见 test_multi_reply_ai.py）
    h = Host()
    ok = await h._send_reply("第一句。第二句。第三句。", group_id=9)
    assert ok is True and h.sender.sent == ["第一句。第二句。第三句。"]


@pytest.mark.asyncio
async def test_disabled_switch_keeps_single_behavior():
    """开关关闭：即使模型给了多条，也只发第一条（与旧版一致）。"""
    h = Host(type("C", (FakeConfig,), {"MULTI_REPLY_ENABLED": False})())
    await h._send_reply(["a", "b", "c"], group_id=3)
    assert h.sender.sent == ["a"]
    assert h.policy_engine.replies == [3]
