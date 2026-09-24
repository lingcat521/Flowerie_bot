"""Multi-Reply 核心单测（ReplyPlan / send_plan / 配置裁剪）。

这些用例不碰网络与协议：间隔用注入的假 sleep，发送用假的 send_one，
于是「有序、按间隔、受上限约束、失败策略」都能被确定性验证。
"""
import random

import pytest

from src.core.reply_plan import (
    INTERVAL_FIXED,
    INTERVAL_NONE,
    INTERVAL_RANDOM,
    ReplyPlan,
    plan_from_config,
)
from src.core.reply_sender import MultiReplyError, send_plan


class FakeConfig:
    def __init__(self, **kw):
        self.MULTI_REPLY_ENABLED = kw.get("enabled", True)
        self.MULTI_REPLY_MAX_MESSAGES = kw.get("max_messages", 3)
        self.MULTI_REPLY_INTERVAL_MODE = kw.get("mode", INTERVAL_RANDOM)
        self.MULTI_REPLY_MIN_INTERVAL = kw.get("lo", 1.5)
        self.MULTI_REPLY_MAX_INTERVAL = kw.get("hi", 4.0)


# ---------- ReplyPlan ----------

def test_single_string_is_backward_compatible():
    plan = ReplyPlan.of("你好")
    assert len(plan) == 1 and plan.messages == ["你好"] and plan.is_single


def test_none_and_blank_produce_empty_plan():
    assert not ReplyPlan.of(None)
    assert not ReplyPlan.of("   ")
    assert not ReplyPlan.of([])


def test_iterable_becomes_multi_message_plan():
    plan = ReplyPlan.of(["你好呀", "今天怎么样", "最近还好吗"])
    assert len(plan) == 3
    assert plan.messages[1] == "今天怎么样"


def test_plan_of_plan_is_identity():
    plan = ReplyPlan.of(["a", "b"])
    assert ReplyPlan.of(plan) is plan


def test_clamped_drops_extra_messages():
    plan = ReplyPlan.of(["1", "2", "3", "4", "5"]).clamped(3)
    assert plan.messages == ["1", "2", "3"]


def test_delay_respects_mode_and_first_message():
    rng = random.Random(42)
    random_plan = ReplyPlan.of(["a", "b"], interval_mode=INTERVAL_RANDOM, min_interval=1.5, max_interval=4.0)
    assert random_plan.delay_before(0) == 0.0            # 第一条不等
    d = random_plan.delay_before(1, rng)
    assert 1.5 <= d <= 4.0

    fixed = ReplyPlan.of(["a", "b"], interval_mode=INTERVAL_FIXED, min_interval=2.0)
    assert fixed.delay_before(1) == 2.0

    none = ReplyPlan.of(["a", "b"], interval_mode=INTERVAL_NONE)
    assert none.delay_before(1) == 0.0


def test_invalid_mode_falls_back_to_random():
    plan = ReplyPlan.of(["a"], interval_mode="wut").normalize_mode()
    assert plan.interval_mode == INTERVAL_RANDOM


# ---------- 配置驱动 ----------

def test_disabled_config_sends_only_first_message():
    plan = plan_from_config(["a", "b", "c"], FakeConfig(enabled=False))
    assert plan.messages == ["a"]


def test_enabled_config_clamps_to_max_messages():
    plan = plan_from_config(["1", "2", "3", "4", "5"], FakeConfig(enabled=True, max_messages=2))
    assert plan.messages == ["1", "2"]


def test_config_intervals_are_used():
    plan = plan_from_config(["a", "b"], FakeConfig(mode=INTERVAL_FIXED, lo=3.0))
    assert plan.delay_before(1) == 3.0


# ---------- 发送编排 ----------

@pytest.mark.asyncio
async def test_send_plan_sends_in_order_with_intervals():
    slept = []

    async def fake_sleep(sec):
        slept.append(sec)

    sent = []

    async def send_one(msg, idx):
        sent.append((idx, msg))
        return "mid-%d" % idx

    plan = ReplyPlan.of(["你好呀", "今天怎么样", "最近还好吗"],
                        interval_mode=INTERVAL_FIXED, min_interval=2.0)
    results = await send_plan(plan, send_one, sleep=fake_sleep)

    assert [m for _, m in sent] == ["你好呀", "今天怎么样", "最近还好吗"]
    assert results == ["mid-0", "mid-1", "mid-2"]
    assert slept == [2.0, 2.0]          # 第一条不等，后两条各等一次


@pytest.mark.asyncio
async def test_send_plan_calls_on_sent_hook():
    hooks = []

    async def send_one(msg, idx):
        return idx

    async def fake_sleep(_):
        return None

    await send_plan(ReplyPlan.of(["a", "b"]), send_one, sleep=fake_sleep,
                    on_sent=lambda i, r: hooks.append((i, r)))
    assert hooks == [(0, 0), (1, 1)]


@pytest.mark.asyncio
async def test_send_plan_stops_on_error_by_default():
    async def send_one(msg, idx):
        if idx == 1:
            raise RuntimeError("boom")
        return idx

    async def fake_sleep(_):
        return None

    with pytest.raises(MultiReplyError) as ei:
        await send_plan(ReplyPlan.of(["a", "b", "c"]), send_one, sleep=fake_sleep)
    assert ei.value.failed_index == 1
    assert ei.value.sent == [0]          # 第一条成功、第二条失败、第三条没发


@pytest.mark.asyncio
async def test_send_plan_continue_mode_keeps_going():
    async def send_one(msg, idx):
        if idx == 1:
            raise RuntimeError("boom")
        return idx

    async def fake_sleep(_):
        return None

    results = await send_plan(ReplyPlan.of(["a", "b", "c"]), send_one,
                              sleep=fake_sleep, on_error="continue")
    assert results[0] == 0 and isinstance(results[1], Exception) and results[2] == 2
