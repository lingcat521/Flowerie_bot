
"""预算只读预检（fix.txt ③）：peek 不消耗额度、不更新状态，且与 check 判定逐条一致。"""
import time
import unittest
from types import SimpleNamespace

from src.core.budget_manager import BudgetManager
from src.models import GlobalState


class _Sender:
    def __init__(self):
        self.sent = []

    async def send_group_message(self, group_id, message, retries=2):
        self.sent.append((group_id, message))
        return True


def _cfg(**over):
    base = dict(DAILY_AI_CALL_BUDGET=10, GROUP_DAILY_AI_CALL_BUDGET=5,
                USER_AI_CALL_MIN_INTERVAL=10, BUDGET_EXHAUSTED_NOTICE=False)
    base.update(over)
    return SimpleNamespace(**base)


def _mgr(cfg=None):
    return BudgetManager(cfg or _cfg(), GlobalState(), _Sender())


def _snapshot(state):
    """只比较预算相关状态（GlobalState 内含锁，不能 deepcopy）。"""
    return (state.ai_budget_date, state.ai_budget_count,
            dict(state.group_ai_budget_count), len(state.user_ai_last_call))


class TestBudgetPeek(unittest.TestCase):
    def test_peek_is_read_only(self):
        mgr = _mgr()
        before = _snapshot(mgr.global_state)
        self.assertEqual(mgr.peek(10, 1), (True, ""))
        self.assertEqual(_snapshot(mgr.global_state), before)

    def test_peek_does_not_touch_user_interval(self):
        mgr = _mgr()
        before = len(mgr.global_state.user_ai_last_call)
        mgr.peek(10, 1)
        self.assertEqual(len(mgr.global_state.user_ai_last_call), before)

    def test_peek_matches_check_in_all_scenarios(self):
        today = time.strftime("%Y-%m-%d")

        def fresh(state):
            pass

        def rate_limited(state):
            state.user_ai_last_call.set(1, time.time())

        def global_exhausted(state):
            state.ai_budget_date = today
            state.ai_budget_count = 999

        def group_exhausted(state):
            state.ai_budget_date = today
            state.group_ai_budget_count[10] = 999

        for setup in (fresh, rate_limited, global_exhausted, group_exhausted):
            peek_mgr = _mgr()
            check_mgr = _mgr()
            setup(peek_mgr.global_state)
            setup(check_mgr.global_state)
            self.assertEqual(peek_mgr.peek(10, 1), check_mgr.check(10, 1),
                             "peek 与 check 判定必须一致：%s" % setup.__name__)

    def test_peek_zero_budget_means_unlimited(self):
        mgr = _mgr(_cfg(DAILY_AI_CALL_BUDGET=0, GROUP_DAILY_AI_CALL_BUDGET=0,
                        USER_AI_CALL_MIN_INTERVAL=0))
        self.assertEqual(mgr.peek(10, 1), (True, ""))

    def test_peek_across_day_counts_as_fresh(self):
        mgr = _mgr()
        mgr.global_state.ai_budget_date = "1970-01-01"
        mgr.global_state.ai_budget_count = 999
        mgr.global_state.group_ai_budget_count[10] = 999
        self.assertEqual(mgr.peek(10, 1), (True, ""))

