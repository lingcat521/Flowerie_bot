"""预算闸门与跨记忆协调测试（v2.9.1 审计修复）。"

覆盖：摘要/画像提取的预算闸门与计入、画像注入按记忆做矛盾过滤、
存档日界与 raw_time 同源、AiGateway nicknames provider 缺陷修复。
"""
import time
from datetime import datetime
from types import SimpleNamespace

import pytest

from src.services.daily_digest import DailyDigestService, DigestStore
from src.services.profile_manager import MemberProfileService, ProfileStore
from src.services.privacy_archive import archive_message


class _FakeAI:
    def __init__(self, reply='摘要：今天大家聊了奶茶'):
        self.reply = reply
        self.calls = []

    async def chat_once(self, user_message, context='', **kwargs):
        self.calls.append(user_message)
        return self.reply, None


class _FakeBudget:
    """与 BudgetManager 同结构的假预算（只含 gate/spend 需要的字段）。"""

    def __init__(self, count=0, gcount=0, cap=10, gcap=5):
        self.config = SimpleNamespace(DAILY_AI_CALL_BUDGET=cap,
                                      GROUP_DAILY_AI_CALL_BUDGET=gcap)
        today = datetime.now().strftime('%Y-%m-%d')
        self.global_state = SimpleNamespace(ai_budget_date=today,
                                            ai_budget_count=count,
                                            group_ai_budget_count={100: gcount})

    def spend(self, group_id):
        gs = self.global_state
        gs.ai_budget_count += 1
        gs.group_ai_budget_count[group_id] = gs.group_ai_budget_count.get(group_id, 0) + 1


class _FakeCtx:
    def __init__(self):
        self.checkpoints = {}

    def set_digest_checkpoint(self, group_id, checkpoint):
        self.checkpoints[group_id] = checkpoint


def _digest(tmp_path, budget=None, ai=None):
    cfg = SimpleNamespace(DIGEST_AT_HOUR=0, DIGEST_AT_MINUTE=0,
                          DIGEST_MIN_MESSAGES=3, DIGEST_MAX_CHARS=20000,
                          DIGEST_BUFFER_PER_GROUP=50, DIGEST_MAX_GROUPS_PER_RUN=20,
                          DIGEST_EXPORT_DIR='', DIGEST_SOURCE='buffer')
    svc = DailyDigestService(cfg, ai or _FakeAI(), DigestStore(str(tmp_path / 'd.db')),
                             context_manager=_FakeCtx(), budget=budget)
    for i in range(5):
        svc.record_message(100, 200 + i, 'msg-%d' % i)
    return svc


# ---------- 摘要预算闸门 ----------
def test_digest_budget_exhausted_skips_and_keeps_buffer(tmp_path):
    budget = _FakeBudget(count=10)  # 全局预算已满
    svc = _digest(tmp_path, budget=budget)
    result = pytest.importorskip('asyncio').run(svc.run_once())
    assert result['groups_skipped'] == 1 and result['groups_processed'] == 0
    assert svc.buffered_count(100) == 5  # 缓冲保留，下轮再试
    assert budget.global_state.ai_budget_count == 10  # 没有计入


def test_digest_group_budget_exhausted_skips(tmp_path):
    budget = _FakeBudget(count=3, gcount=5)  # 群级预算已满
    svc = _digest(tmp_path, budget=budget)
    result = pytest.importorskip('asyncio').run(svc.run_once())
    assert result['groups_skipped'] == 1


def test_digest_counts_into_shared_budget(tmp_path):
    budget = _FakeBudget(count=0)
    svc = _digest(tmp_path, budget=budget)
    result = pytest.importorskip('asyncio').run(svc.run_once())
    assert result['groups_processed'] == 1
    assert budget.global_state.ai_budget_count == 1  # 摘要计入共享预算
    assert budget.global_state.group_ai_budget_count[100] == 1


def test_digest_no_budget_still_works(tmp_path):
    svc = _digest(tmp_path, budget=None)
    result = pytest.importorskip('asyncio').run(svc.run_once())
    assert result['groups_processed'] == 1


# ---------- 画像预算闸门 ----------
@pytest.mark.asyncio
async def test_profile_budget_exhausted_returns_zero(tmp_path):
    budget = _FakeBudget(count=10)
    svc = MemberProfileService(SimpleNamespace(PROFILE_ENABLED=True, PROFILE_MAX_TOKENS=32,
                                               PROFILE_MAX_MEMBERS=3,
                                               PROFILE_SECTION_TTL_DAYS=0),
                              _FakeAI(), ProfileStore(str(tmp_path / 'p.db')), budget=budget)
    n = await svc.extract_from_day(100, '[用户123] 聊天')
    assert n == 0
    assert svc.store.count_group(100) == 0


@pytest.mark.asyncio
async def test_profile_counts_into_budget(tmp_path):
    budget = _FakeBudget(count=0)
    svc = MemberProfileService(SimpleNamespace(PROFILE_ENABLED=True, PROFILE_MAX_TOKENS=32,
                                               PROFILE_MAX_MEMBERS=3,
                                               PROFILE_SECTION_TTL_DAYS=0),
                              _FakeAI(), ProfileStore(str(tmp_path / 'p.db')), budget=budget)
    await svc.extract_from_day(100, '[用户123] 聊天')
    assert budget.global_state.ai_budget_count == 1


# ---------- 跨记忆协调 ----------
class _FakeMemory:
    def __init__(self, notes):
        self._notes = notes

    def get_user_notes(self, user_id, group_id):
        return self._notes


def _svc_with_memory(tmp_path, notes):
    return MemberProfileService(SimpleNamespace(PROFILE_ENABLED=True, PROFILE_MAX_TOKENS=32,
                                                PROFILE_MAX_MEMBERS=3,
                                                PROFILE_SECTION_TTL_DAYS=0),
                                None, ProfileStore(str(tmp_path / 'p.db')),
                                memory_manager=_FakeMemory(notes))


def test_profile_block_drops_field_contradicted_by_memory(tmp_path):
    svc = _svc_with_memory(tmp_path, ['戒奶茶了'])
    svc.store.upsert(100, 123, '小花', {
        'interests': {'text': '奶茶', 'ts': time.time()},
        'personality': {'text': '温柔', 'ts': time.time()},
    })
    block = svc.build_context_block(100, user_id=123)
    assert '奶茶' not in block  # 与记忆矛盾 → 剔除
    assert '温柔' in block  # 无矛盾 → 保留


def test_profile_block_keeps_field_when_no_memory(tmp_path):
    svc = _svc_with_memory(tmp_path, [])
    svc.store.upsert(100, 123, '', {'interests': {'text': '奶茶', 'ts': time.time()}})
    assert '奶茶' in svc.build_context_block(100, user_id=123)


def test_profile_block_other_members_unaffected(tmp_path):
    svc = _svc_with_memory(tmp_path, ['戒奶茶了'])
    svc.store.upsert(100, 123, '', {'interests': {'text': '奶茶', 'ts': time.time()}})
    svc.store.upsert(100, 456, '', {
        'interests': {'text': '奶茶', 'ts': time.time()},
        'traits': {'text': '会画画', 'ts': time.time()},
    })
    block = svc.build_context_block(100, user_id=456)
    assert '用户123' in block and '用户456' in block
    # 只有当前发言人 456 会被过滤：他的奶茶剔除、traits 保留；123 的画像行原样保留
    assert '用户123 — 喜好: 奶茶' in block
    line_456 = next(l for l in block.splitlines() if l.startswith('用户456'))
    assert '奶茶' not in line_456 and '特点: 会画画' in line_456


def test_profile_block_no_user_id_no_filter(tmp_path):
    svc = _svc_with_memory(tmp_path, ['戒奶茶了'])
    svc.store.upsert(100, 123, '', {'interests': {'text': '奶茶', 'ts': time.time()}})
    assert '奶茶' in svc.build_context_block(100)


# ---------- 存档日界 ----------
def test_archive_uses_raw_time_for_day_boundary(tmp_path):
    cfg = SimpleNamespace(ARCHIVE_ENABLED=True, ARCHIVE_BASE_DIR=str(tmp_path / 'ar'),
                          ARCHIVE_RETENTION_DAYS=0, ARCHIVE_MAX_SIZE_MB=0)
    # 2026-10-24 23:59:59 本地时间（raw_time 落在 24 日）
    ts = time.mktime(datetime(2026, 10, 24, 23, 59, 59).timetuple())
    archive_message(cfg, 100, 123, '深夜消息', int(ts))
    day_file = tmp_path / 'ar' / '100' / '2026-10-24.txt'
    assert day_file.exists(), '消息应落在 raw_time 对应的日期文件'
    assert '23:59:59' in day_file.read_text(encoding='utf-8')
    assert not (tmp_path / 'ar' / '100' / '2026-10-25.txt').exists()


# ---------- AiGateway nicknames provider 修复 ----------
def test_gateway_nicknames_provider_raw_store():
    from src.core.ai_gateway import AiGateway

    class NickStore:
        def get(self, gid, pid=None):
            return '群昵称'

    class PersonaMgr:
        pass

    # 传裸 store + 裸 persona_manager：第三分支此前返回 persona_manager 导致崩溃
    gw = AiGateway(SimpleNamespace(), None, None,
                   nicknames=NickStore(), persona_manager=PersonaMgr())
    assert gw._nicknames().get(100) == '群昵称'

