"""Layer A 边界感知切分单元测试。

覆盖：长度不变性、边界优先级（换行>句尾标点>逗号>空格>硬切）、
内容零丢失、段长上限、碎片段防护、旧路径（SPLIT_REPLY_ENABLED=False）行为零变化。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.reply_plan import plan_from_config
from src.core.reply_splitter import SplitSegments, needs_split, split_by_boundary
from src.services.reply_parser import parse_reply_content


class _Cfg:
    """最小配置替身：与 Settings 同名属性，默认值复刻线上默认（开关全关=旧行为）。"""

    MULTI_REPLY_ENABLED = False
    MULTI_REPLY_MAX_MESSAGES = 3
    MULTI_REPLY_INTERVAL_MODE = "random"
    MULTI_REPLY_MIN_INTERVAL = 1.5
    MULTI_REPLY_MAX_INTERVAL = 4.0
    MAX_REPLY_LENGTH = 40
    SPLIT_REPLY_ENABLED = False
    SPLIT_REPLY_SEGMENT_LIMIT = 40
    SPLIT_REPLY_MAX_MESSAGES = 8


# ---------- split_by_boundary ----------

def test_short_text_passthrough():
    assert split_by_boundary("你好呀", 40) == ["你好呀"]


def test_empty_text():
    assert split_by_boundary("", 40) == []
    assert split_by_boundary("   ", 40) == []


def test_hard_cut_no_boundary():
    """无标点无空格长文：保证每段 <= limit 且内容零丢失。"""
    text = "啊" * 95
    parts = split_by_boundary(text, 40)
    assert all(len(p) <= 40 for p in parts)
    assert "".join(parts) == text


def test_newline_is_strongest_boundary():
    text = "第一段内容\n第二段内容\n第三段内容"
    parts = split_by_boundary(text, 8)
    assert parts == ["第一段内容", "第二段内容", "第三段内容"]


def test_sentence_punct_preferred_over_comma():
    text = "今天天气真不错。我们出去玩吧，记得带伞喔"
    parts = split_by_boundary(text, 12)
    assert all(len(p) <= 12 for p in parts)
    assert parts[0] == "今天天气真不错。"


def test_space_boundary_for_punct_free_persona():
    """人设场景（空格代替逗号、无句号）：空格成为主要切分边界。"""
    text = "虽然我文笔约等于滚木 毕竟是写日记才让我表达能力变强的"
    parts = split_by_boundary(text, 20)
    assert all(len(p) <= 20 for p in parts)
    assert len(parts) >= 2
    chars = [c for c in "".join(parts) if not c.isspace()]
    assert chars == [c for c in text if not c.isspace()]


def test_diary_case_zero_loss():
    """用户实测 case：85 字三行日记 → 多条、零丢失、无 '...'。"""
    diary = (
        "有时候真的很羡慕表达能力没那么强的人\n"
        "要是我表达能力没这么强 我就不会天天在空间扰民了\n"
        "虽然我文笔约等于滚木 毕竟是写日记才让我表达能力变强的 日记里面写的东西就是很发散"
    )
    parts = split_by_boundary(diary, 40)
    assert all(len(p) <= 40 for p in parts)
    assert all("..." not in p for p in parts)
    orig = [c for c in diary if not c.isspace()]
    got = [c for c in "".join(parts) if not c.isspace()]
    assert orig == got


def test_no_short_fragments():
    """切点保护：不得出现「句子 + 单个标点」式碎片段（除非本身就是短文本）。"""
    text = "今天天气真不错。明天继续玩。后天还要出去玩呢。"
    parts = split_by_boundary(text, 30)
    assert all(len(p) >= 3 for p in parts)


# ---------- needs_split ----------

def test_needs_split():
    assert needs_split("x" * 41, 40) is True
    assert needs_split("x" * 40, 40) is False
    assert needs_split("", 40) is False


# ---------- parse_reply_content 默认路径零变化 ----------

def test_parse_reply_truncates_when_disabled():
    cfg = _Cfg()
    long = "一" * 60
    reply, _ = parse_reply_content(long, cfg)
    assert isinstance(reply, str)
    assert reply == "一" * 40 + "..."


def test_parse_reply_splits_when_enabled():
    cfg = _Cfg()
    cfg.SPLIT_REPLY_ENABLED = True
    long = "今天天气真不错。我们出去玩吧，记得带伞喔，别忘了带水壶，记得带伞喔，别忘了带水壶，记得带伞喔"
    reply, _ = parse_reply_content(long, cfg)
    assert isinstance(reply, list)
    assert len(reply) >= 2
    assert all("..." not in p for p in reply)
    chars = [c for c in "".join(reply) if not c.isspace()]
    assert chars == [c for c in long if not c.isspace()]


def test_parse_reply_short_untouched_when_enabled():
    cfg = _Cfg()
    cfg.SPLIT_REPLY_ENABLED = True
    reply, _ = parse_reply_content("你好呀", cfg)
    assert reply == "你好呀"


# ---------- plan_from_config 段数门控 ----------

def test_plan_clamped_one_when_disabled():
    cfg = _Cfg()
    plan = plan_from_config(["一", "二", "三", "四"], cfg)
    assert len(plan.messages) == 1


def test_plan_keeps_split_segments_when_enabled():
    """C3 修复后：识别来源靠 SplitSegments 标记，而不是 SPLIT 开关劫持任意 list。"""
    cfg = _Cfg()
    cfg.SPLIT_REPLY_ENABLED = True
    plan = plan_from_config(SplitSegments(["一", "二", "三", "四"]), cfg)
    assert len(plan.messages) == 4


def test_plan_split_max_messages_cap():
    cfg = _Cfg()
    cfg.SPLIT_REPLY_ENABLED = True
    cfg.SPLIT_REPLY_MAX_MESSAGES = 2
    plan = plan_from_config(SplitSegments(["一", "二", "三", "四"]), cfg)
    assert len(plan.messages) == 2


def test_plan_single_string_unchanged_when_enabled():
    cfg = _Cfg()
    cfg.SPLIT_REPLY_ENABLED = True
    plan = plan_from_config("你好", cfg)
    assert plan.messages == ["你好"]


# ---------- C1/C3/C5：SplitSegments 的 plan 语义（v2.7.0） ----------

def test_split_segments_use_own_max_messages_not_multi_reply_cap():
    """C3：两开关同开，AI 多条防刷屏上限（3）不再被切分段上限（8）接管。"""
    cfg = _Cfg()
    cfg.MULTI_REPLY_ENABLED = True
    cfg.MULTI_REPLY_MAX_MESSAGES = 3
    cfg.SPLIT_REPLY_ENABLED = True
    cfg.SPLIT_REPLY_MAX_MESSAGES = 8
    split_plan = plan_from_config(SplitSegments(["一", "二", "三", "四", "五", "六", "七", "八", "九"]), cfg)
    assert len(split_plan.messages) == 8
    multi_plan = plan_from_config(["一", "二", "三", "四", "五"], cfg)
    assert len(multi_plan.messages) == 3
    assert multi_plan.count_as_one is False


def test_split_segments_count_as_one_and_no_interval():
    """C1/C5：分段轮只计一次连续回复、零段间隔；AI 自主多条保持 random。"""
    cfg = _Cfg()
    cfg.SPLIT_REPLY_INTERVAL_MODE = "none"
    split_plan = plan_from_config(SplitSegments(["一", "二"]), cfg)
    assert split_plan.count_as_one is True
    assert split_plan.interval_mode == "none"
    multi_plan = plan_from_config(["一", "二"], cfg)
    assert multi_plan.count_as_one is False
    assert multi_plan.interval_mode == "random"


def test_split_segments_invalid_interval_mode_falls_back_none():
    cfg = _Cfg()
    cfg.SPLIT_REPLY_INTERVAL_MODE = "bogus"
    plan = plan_from_config(SplitSegments(["一"]), cfg)
    assert plan.interval_mode == "none"


def test_parse_reply_returns_split_segments():
    """C3 标记链：parser 切分分支产出 SplitSegments。"""
    cfg = _Cfg()
    cfg.SPLIT_REPLY_ENABLED = True
    long = "今天天气真不错。我们出去玩吧，记得带伞喔，别忘了带水壶，记得带伞喔，别忘了带水壶，记得带伞喔"
    reply, _ = parse_reply_content(long, cfg)
    assert isinstance(reply, SplitSegments)
    assert len(reply) >= 2


def test_clamped_preserves_count_as_one():
    """clamped 不丢 count_as_one 标记（C1 在截断后仍生效）。"""
    cfg = _Cfg()
    cfg.SPLIT_REPLY_MAX_MESSAGES = 2
    plan = plan_from_config(SplitSegments(["一", "二", "三", "四"]), cfg)
    assert len(plan.messages) == 2
    assert plan.count_as_one is True

