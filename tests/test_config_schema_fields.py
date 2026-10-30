"""SCHEMA ↔ Settings 一致性守卫。

v2.17.2 的 bug：14 个键只在 SCHEMA 声明（Web UI 能保存），
但 pydantic Settings 没有对应字段——apply_persisted 的 setattr 直接抛
ValueError，启动日志刷一片 config_persisted_apply_failed，且用户保存的值
永不生效（重启后被静默丢弃）。本测试堵死这类漏申明。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import Settings  # noqa: E402
from src.services.config_schema import SCHEMA  # noqa: E402


def test_every_schema_key_is_a_settings_field():
    """SCHEMA 的每个键都必须是 Settings 的真实字段（否则持久化应用必失败）。"""
    fields = set(Settings.model_fields.keys())
    missing = sorted(k for k in SCHEMA if k not in fields)
    assert not missing, "SCHEMA 键未在 Settings 声明: %s" % missing


def test_search_keys_defaults():
    """搜索类键的默认值与文档一致（回归 v2.17.2 的漏申明）。"""
    s = Settings(_env_file=None, DEEPSEEK_API_KEY="k", BOT_QQ=1)
    assert s.AI_SEARCH_ENABLED is False
    assert s.AI_GROUP_INFO_ENABLED is False
    assert s.AI_PROFILES_ENABLED is False
    assert s.AI_KNOWLEDGE_ENABLED is False
    assert s.AI_POKE_ENABLED is False
    assert s.SEARCH_ENGINES == "ddg,bing,searxng,ddg-lite"
    assert s.SEARCH_MAX_RESULTS == 5
    assert s.SEARCH_TIMEOUT == 10
    assert s.SEARCH_CACHE_TTL == 5
    assert s.SEARCH_SAFE_SEARCH == "off"
    assert s.SEARCH_BLOCKED_DOMAINS == []
    assert s.SEARCH_SEARXNG_INSTANCES == []
    assert s.SEARCH_FETCH_MAX_CHARS == 2000
    assert s.SEARCH_PROOF_REQUIRED is True


def test_settings_accepts_env_comma_list():
    """list-str 键的 .env 逗号写法经 before-validator 解析为列表。"""
    s = Settings(_env_file=None, DEEPSEEK_API_KEY="k", BOT_QQ=1,
                 SEARCH_BLOCKED_DOMAINS="a.com,b.com",
                 SEARCH_SEARXNG_INSTANCES="https://x.example")
    assert s.SEARCH_BLOCKED_DOMAINS == ["a.com", "b.com"]
    assert s.SEARCH_SEARXNG_INSTANCES == ["https://x.example"]
