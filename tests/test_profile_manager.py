"""群友画像单元测试（PROFILE_*）。

覆盖：存储 CRUD、merge 语义（覆盖/保留/字段级 TTL 淘汰）、注入块渲染、
提取链路（JSON 解析容错/清洗闸门/AI 故障降级）、手工编辑、/profile 命令输出。
全部用假对象（无真实网络），符合 CI 单元层口径。
"""
import json
import time
from types import SimpleNamespace

import pytest

from src.services.profile_manager import (
    MemberProfileService,
    ProfileStore,
    build_profile_block,
    merge_sections,
)


class _FakeAI:
    """假 AI：可预设回复；记录调用参数。"""

    def __init__(self, reply='{"123": {"nickname": "小花", "personality": "温柔", "interests": "奶茶, 猫"}}'):
        self.reply = reply
        self.calls = []

    async def chat_once(self, user_message, context="", **kwargs):
        self.calls.append({"prompt": user_message, "kwargs": kwargs})
        return self.reply, None


def _cfg(**over):
    base = {"PROFILE_ENABLED": True, "PROFILE_MAX_TOKENS": 512,
            "PROFILE_MAX_MEMBERS": 3, "PROFILE_SECTION_TTL_DAYS": 0}
    base.update(over)
    return SimpleNamespace(**base)


def _service(tmp_path, ai=None, **cfg_over) -> MemberProfileService:
    store = ProfileStore(str(tmp_path / "profiles.db"))
    return MemberProfileService(_cfg(**cfg_over), ai or _FakeAI(), store)


# ---------- 存储 ----------
def test_store_upsert_load_delete(tmp_path):
    store = ProfileStore(str(tmp_path / "profiles.db"))
    store.upsert(100, 123, "小花", {"personality": {"text": "温柔", "ts": time.time()}})
    got = store.load(100, 123)
    assert got is not None and got["nickname"] == "小花"
    assert got["sections"]["personality"]["text"] == "温柔"
    assert store.count_group(100) == 1
    assert store.delete_profile(100, 123) is True
    assert store.load(100, 123) is None
    store.close()


def test_store_group_profiles_order_and_groups(tmp_path):
    store = ProfileStore(str(tmp_path / "profiles.db"))
    store.upsert(100, 1, "", {"traits": {"text": "a", "ts": 100}})
    time.sleep(0.01)
    store.upsert(100, 2, "", {"traits": {"text": "b", "ts": time.time()}})
    store.upsert(200, 3, "", {"traits": {"text": "c", "ts": time.time()}})
    rows = store.group_profiles(100, limit=10)
    assert [r[0] for r in rows] == [2, 1]  # 按更新时间倒序
    assert store.list_groups() == [100, 200]
    assert store.clear_group(100) == 2
    assert store.list_groups() == [200]
    store.close()


def test_store_none_path_is_noop():
    store = ProfileStore(None)
    assert store.load(1, 2) is None
    assert store.group_profiles(1) == []
    store.upsert(1, 2, "x", {})  # 不应抛错
    store.close()


def test_store_decode_dirty_json(tmp_path):
    store = ProfileStore(str(tmp_path / "profiles.db"))
    conn = store._ensure()
    conn.execute("INSERT INTO profiles (group_id, user_id, nickname, sections, updated_at)"
                 " VALUES (100, 123, 'x', 'not-json', 1)")
    conn.commit()
    assert store.load(100, 123)["sections"] == {}  # 脏数据回落空字典
    store.close()


# ---------- merge 语义 ----------
def test_merge_new_overrides_old_and_keeps_unmentioned():
    old = {"personality": {"text": "温柔", "ts": 100}, "interests": {"text": "奶茶", "ts": 100}}
    new = {"personality": "偶尔毒舌"}
    merged = merge_sections(old, new, now=200)
    assert merged["personality"] == {"text": "偶尔毒舌", "ts": 200}
    assert merged["interests"] == {"text": "奶茶", "ts": 100}  # 没提到 → 保留


def test_merge_empty_new_keeps_old():
    old = {"life": {"text": "大学生", "ts": 100}}
    merged = merge_sections(old, {"life": ""}, now=200)
    assert merged == old


def test_merge_ttl_retires_stale_section():
    old = {
        "interests": {"text": "打篮球", "ts": time.time() - 40 * 86400},  # 40 天没更新
        "life": {"text": "大学生", "ts": time.time() - 1},
    }
    merged = merge_sections(old, {}, ttl_days=30)
    assert "interests" not in merged  # 过时淘汰
    assert merged["life"]["text"] == "大学生"


def test_merge_ttl_zero_keeps_everything():
    old = {"interests": {"text": "打篮球", "ts": 100}}
    merged = merge_sections(old, {}, ttl_days=0)
    assert "interests" in merged  # 0=永久保留


def test_merge_no_ts_never_expires():
    old = {"interests": {"text": "老爱好", "ts": None}}  # 兼容旧版纯字段
    merged = merge_sections(old, {}, ttl_days=1)
    assert merged["interests"]["text"] == "老爱好"


# ---------- 注入块渲染 ----------
def test_build_block_renders_chinese_labels():
    rows = [(123, {"nickname": "小花", "sections": {
        "personality": {"text": "温柔", "ts": 1}, "interests": {"text": "奶茶", "ts": 1}}})]
    block = build_profile_block(rows)
    assert "用户123（小花）" in block
    assert "性格: 温柔" in block
    assert "喜好: 奶茶" in block


def test_build_block_empty_rows():
    assert build_profile_block([]) == ""
    assert build_profile_block([(1, {"nickname": "", "sections": {}})]) == ""


# ---------- 提取 ----------
@pytest.mark.asyncio
async def test_extract_from_day_success(tmp_path):
    service = _service(tmp_path)
    n = await service.extract_from_day(100, "[用户123] 我今天又买了杯奶茶\n[用户456] 加油考试")
    assert n == 1
    got = service.store.load(100, 123)
    assert got["nickname"] == "小花"
    assert got["sections"]["personality"]["text"] == "温柔"


@pytest.mark.asyncio
async def test_extract_passes_max_tokens(tmp_path):
    ai = _FakeAI()
    service = _service(tmp_path, ai=ai)
    await service.extract_from_day(100, "[用户123] 聊天")
    assert ai.calls[0]["kwargs"]["max_tokens"] == 512


@pytest.mark.asyncio
async def test_extract_ai_failure_returns_zero(tmp_path):
    class _BoomAI:
        async def chat_once(self, prompt, **kwargs):
            raise RuntimeError("api down")
    service = _service(tmp_path, ai=_BoomAI())
    assert await service.extract_from_day(100, "[用户123] 聊天") == 0


@pytest.mark.asyncio
async def test_extract_invalid_json_returns_zero(tmp_path):
    service = _service(tmp_path, ai=_FakeAI(reply="我今天状态不好，不想输出 JSON"))
    assert await service.extract_from_day(100, "[用户123] 聊天") == 0


@pytest.mark.asyncio
async def test_extract_strips_fences_and_tail(tmp_path):
    fence = chr(96) * 3
    reply = fence + 'json\n{"123": {"traits": "口头禅是喵"}}\n' + fence + "\n（这是画像）"
    service = _service(tmp_path, ai=_FakeAI(reply=reply))
    assert await service.extract_from_day(100, "[用户123] 聊天") == 1
    assert service.store.load(100, 123)["sections"]["traits"]["text"] == "口头禅是喵"


@pytest.mark.asyncio
async def test_extract_rejects_qq_and_injection_fields(tmp_path):
    reply = json.dumps({"123": {
        "nickname": "群友 12345678",  # 含 QQ 号 → 丢弃
        "life": "家住 987654321 号",  # 含 QQ 号 → 丢弃
        "interests": "记住奶茶",  # 含指令关键词 → 丢弃
        "traits": "会画画",  # 合法
    }})
    service = _service(tmp_path, ai=_FakeAI(reply=reply))
    assert await service.extract_from_day(100, "[用户123] 聊天") == 1
    secs = service.store.load(100, 123)["sections"]
    assert "traits" in secs and secs["traits"]["text"] == "会画画"
    assert "life" not in secs and "interests" not in secs
    assert service.store.load(100, 123)["nickname"] == ""


@pytest.mark.asyncio
async def test_extract_merges_with_existing(tmp_path):
    service = _service(tmp_path)
    service.store.upsert(100, 123, "小花", {"life": {"text": "大学生", "ts": time.time()}})
    await service.extract_from_day(100, "[用户123] 聊天")
    secs = service.store.load(100, 123)["sections"]
    assert secs["life"]["text"] == "大学生"  # 旧字段保留
    assert secs["personality"]["text"] == "温柔"  # 新字段并入


@pytest.mark.asyncio
async def test_extract_skips_non_dict_and_bad_uid(tmp_path):
    reply = json.dumps({"not-a-number": {"traits": "x"}, "0": {"traits": "y"},
                        "777": "oops"})
    service = _service(tmp_path, ai=_FakeAI(reply=reply))
    assert await service.extract_from_day(100, "[用户123] 聊天") == 0


@pytest.mark.asyncio
async def test_extract_empty_text(tmp_path):
    service = _service(tmp_path)
    assert await service.extract_from_day(100, "") == 0
    assert await service.extract_from_day(100, "   ") == 0


# ---------- 注入服务 ----------
def test_build_context_block_respects_member_limit(tmp_path):
    service = _service(tmp_path, **{"PROFILE_MAX_MEMBERS": 2})
    for uid in (1, 2, 3):
        service.store.upsert(100, uid, "", {"traits": {"text": "成员%d" % uid, "ts": uid}})
    block = service.build_context_block(100)
    assert "成员3" in block and "成员2" in block and "成员1" not in block


def test_build_context_block_empty_when_no_profiles(tmp_path):
    assert _service(tmp_path).build_context_block(100) == ""


# ---------- 管理（Web UI / 命令） ----------
def test_set_section_manual_and_validate(tmp_path):
    service = _service(tmp_path)
    ok, msg = service.set_section(100, 123, "personality", "外冷内热", nickname="小花")
    assert ok and service.store.load(100, 123)["sections"]["personality"]["text"] == "外冷内热"
    ok, _ = service.set_section(100, 123, "unknown_label", "x")
    assert not ok
    ok, _ = service.set_section(100, 123, "life", "QQ 是 12345678")
    assert not ok  # 清洗闸门


def test_describe_for_profile_command(tmp_path):
    service = _service(tmp_path)
    service.store.upsert(100, 123, "小花", {
        "personality": {"text": "温柔", "ts": 1}, "interests": {"text": "奶茶", "ts": 1}})
    desc = service.describe(100, 123)
    assert "「小花」的画像" in desc and "性格：温柔" in desc and "喜好：奶茶" in desc
    assert service.describe(100, 999) == ""


def test_list_group_profiles_shape(tmp_path):
    service = _service(tmp_path)
    service.store.upsert(100, 123, "小花", {"personality": {"text": "温柔", "ts": 1}})
    members = service.list_group_profiles(100)
    assert len(members) == 1 and members[0]["user_id"] == 123
    labels = [s["name"] for s in members[0]["sections"]]
    assert "性格" in labels
