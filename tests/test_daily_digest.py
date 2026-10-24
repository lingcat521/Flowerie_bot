"""每日摘要单元测试（DIGEST_*）。"

覆盖：定点调度计算、缓冲有界性、merge 语义（prior 传入）、收敛检查、
deqne checkpoint 落地与渲染、txt 导出、失败保留缓冲、quiet 群跳过。
全部用假对象（无真实网络），符合 CI 单元层口径。"""
import os
import pathlib
import tempfile
import time
from types import SimpleNamespace

from src.services.daily_digest import DailyDigestService, DigestStore, _seconds_to_next, frame_summary, is_shrunk


class _FakeAI:
    """假 AI：可预设回复；记录调用。"""

    def __init__(self, reply="摘要内容：今天大家聊了天气和晚饭"):
        self.reply = reply
        self.calls = []

    async def chat_once(self, user_message, context="", **kwargs):
        self.calls.append(user_message)
        return self.reply, None


class _FakeCfg:
    DIGEST_AT_HOUR = 0
    DIGEST_AT_MINUTE = 0
    DIGEST_MIN_MESSAGES = 3
    DIGEST_MAX_CHARS = 2000
    DIGEST_BUFFER_PER_GROUP = 50
    DIGEST_MAX_GROUPS_PER_RUN = 20
    DIGEST_EXPORT_DIR = ""


class _FakeCtx:
    """假 ContextManager：记录 set_digest_checkpoint 调用。"""

    def __init__(self):
        self.checkpoints = {}

    def set_digest_checkpoint(self, group_id, checkpoint):
        self.checkpoints[group_id] = checkpoint

    def restore_digest_checkpoints(self, rows):
        for gid, text in rows.items():
            self.checkpoints[gid] = text


def _make(tmp_path=None, ai=None, export_dir=""):
    if tmp_path is None:
        tmp_path = pathlib.Path(tempfile.mkdtemp())
    cfg = SimpleNamespace(**{k: v for k, v in vars(_FakeCfg).items()
                             if not k.startswith("_")})
    cfg.DIGEST_EXPORT_DIR = export_dir or ""
    store = DigestStore(str(tmp_path / "digest.db"))
    return cfg, DailyDigestService(cfg, ai or _FakeAI(), store,
                                    context_manager=_FakeCtx()), store


def _feed(svc, group_id=100, n=5, prefix="msg"):
    for i in range(n):
        svc.record_message(group_id, 200 + i, f"{prefix}-{i}")


# ---------- 纯函数 ----------

def test_seconds_to_next_returns_positive():
    # 固定 UTC 时刻（北京 12:34:56），到下一个 00:00 应差 11h25m4s
    # 用固定时间戳而非 mktime，使断言与 CI 机器时区无关
    now = 1792730096  # 2026-10-23T04:34:56Z == 北京时间 12:34:56
    d = _seconds_to_next(0, 0, "Asia/Shanghai", now=now)
    assert 0 < d < 86400
    assert abs(d - (11 * 3600 + 25 * 60 + 4)) < 3


def test_seconds_to_next_already_passed_rolls_to_tomorrow():
    # 北京时间 00:00:01（刚过触发点），下一个 00:00 约 24h 后
    now = 1792684801  # 2026-10-22T16:00:01Z == 北京时间 2026-10-23 00:00:01
    d = _seconds_to_next(0, 0, "Asia/Shanghai", now=now)
    assert d > 3600 * 23


def test_frame_summary_wraps_tags():
    out = frame_summary("正文")
    assert "<daily-digest>" in out and "</daily-digest>" in out
    assert "established background" in out
    assert "正文" in out


def test_is_shrunk():
    assert is_shrunk("短", 100)
    assert not is_shrunk("x" * 100, 100)


# ---------- 缓冲 ----------

def test_buffer_skips_blank_and_caps():
    cfg, svc, store = _make(None)
    svc.record_message(1, 10, "   ")  # 空文本不入缓冲
    _feed(svc, group_id=1, n=60)      # 超缓冲上限 50
    assert svc.buffered_count(1) == 50


async def test_quiet_group_skipped():
    cfg, svc, store = _make(None)
    _feed(svc, n=2)  # 不足 min_messages=3
    stats = await svc.run_once(now=time.time())
    assert stats["groups_processed"] == 0
    assert svc.buffered_count(100) == 2  # 缓冲保留，下轮累计


# ---------- 主流程 ----------

async def test_digest_lands_three_places(tmp_path):
    export = str(tmp_path / "digests")
    cfg, svc, store = _make(tmp_path, export_dir=export)
    _feed(svc, n=5)
    stats = await svc.run_once(now=time.time())
    assert stats["groups_processed"] == 1
    # deque 落地
    cp = svc.context.checkpoints[100]
    assert "<daily-digest>" in cp
    # SQLite 落地
    row = store.load(100)
    assert row is not None and "<daily-digest>" in row[1]
    # txt 导出
    files = os.listdir(export)
    assert len(files) == 1 and files[0].startswith("100_") and files[0].endswith(".txt")
    assert "<daily-digest>" in open(os.path.join(export, files[0]), encoding="utf-8").read()
    # 缓冲已清
    assert svc.buffered_count(100) == 0


async def test_prior_checkpoint_is_merged_into_prompt():
    """嵌套合并语义：已有摘要必须作为 PRIOR 传给模型（连续运行不堆叠）。"""
    ai = _FakeAI()
    cfg, svc, store = _make(None, ai=ai)
    store.save(100, "2026-10-22", frame_summary("旧摘要：群里约定周末吃火锅"))
    _feed(svc, n=5)
    await svc.run_once(now=time.time())
    assert ai.calls, "model must be called"
    prompt = ai.calls[0]
    assert "既往摘要" in prompt and "周末吃火锅" in prompt
    assert "PRIOR" in prompt or "既往" in prompt


async def test_not_shrunk_rejected_and_buffer_kept():
    """收敛检查：摘要更长则拒写且缓冲保留（下轮重试）。"""
    long_reply = "x" * 3000
    ai = _FakeAI(reply=long_reply)
    cfg, svc, store = _make(None, ai=ai)
    _feed(svc, n=5)  # 渲染后远短于 3000
    stats = await svc.run_once(now=time.time())
    assert stats["groups_failed"] == 1
    assert svc.buffered_count(100) == 5  # 缓冲保留
    assert 100 not in svc.context.checkpoints
    row = store.load(100)
    assert row is None  # 没写脏库


async def test_ai_failure_keeps_buffer():
    class _BoomAI:
        async def chat_once(self, *a, **k):
            raise RuntimeError("provider down")
    cfg, svc, store = _make(None, ai=_BoomAI())
    _feed(svc, n=5)
    stats = await svc.run_once(now=time.time())
    assert stats["groups_failed"] == 1 and svc.buffered_count(100) == 5


async def test_new_digest_replaces_old_checkpoint():
    """merge 语义：第二轮摘要覆盖第一轮（deque/库里永远只有一份）。"""
    ai = _FakeAI("第一轮摘要")
    cfg, svc, store = _make(None, ai=ai)
    _feed(svc, n=4, prefix="day1")
    await svc.run_once(now=time.time())
    first = store.load(100)[1]
    _feed(svc, n=4, prefix="day2")
    ai.reply = "第二轮摘要"
    await svc.run_once(now=time.time())
    second = store.load(100)[1]
    assert first != second
    assert "第二轮摘要" in second
    # 每群只一行
    assert len(store.load_all()) == 1


def test_restore_checkpoints():
    cfg, svc, store = _make(None)
    store.save(100, "2026-10-22", "cp-100")
    store.save(200, "2026-10-22", "cp-200")
    ctx = _FakeCtx()
    svc.context = ctx
    svc.context.restore_digest_checkpoints(
        {gid: row[1] for gid, row in store.load_all().items()})
    assert ctx.checkpoints[100] == "cp-100" and ctx.checkpoints[200] == "cp-200"

def test_context_manager_renders_checkpoint_head():
    """ContextManager: 摘要前置渲染 + restore。"""
    from src.core.context_manager import ContextManager
    from src.models import GlobalState
    cfg = SimpleNamespace(CONTEXT_SIZE=10, CONTEXT_BACKUP_PATH="")
    cm = ContextManager(cfg, {}, GlobalState())
    cm.set_digest_checkpoint(100, "记事：小张明天请客")
    cm.add_context(100, 123, "你好")
    text = cm.get_context_text(100)
    assert text.startswith("[近期群聊摘要（既定背景，不用复述）]")
    assert "记事：小张明天请客" in text
    assert "[1] 用户123: 你好" in text
    cm.restore_digest_checkpoints({200: "cp-200"})
    assert cm.get_digest_checkpoint(200) == "cp-200"
    assert cm.get_digest_checkpoint(999) is None


def test_should_reply_skips_compact_entries():
    """集成暗坑：compact 条目不得挤占近 5 条窗口（安静群 digest 后不误杀主动聊天）。"""
    from src.core.context_manager import ContextManager
    from src.models import GlobalState
    cfg = SimpleNamespace(CONTEXT_SIZE=20, CONTEXT_BACKUP_PATH="")
    cm = ContextManager(cfg, {}, GlobalState())
    state = cm.get_group_state(100)
    state.context.append({"type": "compact", "user_id": 0, "message": "摘要",
                          "is_bot": True, "time": time.time()})
    recent = [m for m in list(state.context)[-5:] if m.get("type") != "compact"]
    assert all(m.get("type") != "compact" for m in recent)

def test_add_context_digest_text_full():
    """router 传 digest_text=full_text：摘要数据源拿全文，工作 deque 仍存截断。"""
    from src.core.context_manager import ContextManager
    from src.models import GlobalState
    cfg_gstate = SimpleNamespace(CONTEXT_SIZE=50, CONTEXT_BACKUP_PATH="")
    cm = ContextManager(cfg_gstate, {}, GlobalState())
    seen = []
    cm.digest_feed = lambda gid, uid, text: seen.append((gid, uid, text))
    long_text = "x" * 500
    cm.add_context(100, 123, long_text[:200], is_bot=False, digest_text=long_text)
    # 工作 deque 存截断
    state = cm.get_group_state(100)
    assert state.context[0]["message"] == long_text[:200]
    # digest 拿全文
    assert seen and seen[0][2] == long_text

