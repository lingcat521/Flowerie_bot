"""本机回环模型免密钥（v2.7.0）：判定函数 + 请求头 + Web UI 配置链路。

覆盖用户在 Web UI / .env 两处都能配置「本机自建模型」的需求：
地址指向 127.0.0.1/localhost/::1 时，API 密钥可以留空。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import is_loopback_url
from src.utils.llm_headers import auth_headers, is_local_endpoint

# ---------- URL 判定 ----------

@pytest.mark.parametrize("url", [
    "http://127.0.0.1:11434/v1/chat/completions",
    "http://127.0.0.1:8080/v1/chat/completions",
    "http://127.1.2.3:9000/v1",
    "http://localhost:11434/v1/chat/completions",
    "https://localhost/v1/chat",
    "http://[::1]:8000/v1/chat/completions",
])
def test_loopback_urls_recognized(url):
    assert is_loopback_url(url) is True


@pytest.mark.parametrize("url", [
    "https://api.deepseek.com/chat/completions",
    "http://192.168.1.5:11434/v1/chat/completions",   # 局域网不算回环（仍可能校验密码）
    "http://10.0.0.7:8000/v1",
    "http://example.com/localhost",                    # 域名里出现 localhost 不算
    "",
    None,
    "not-a-url",
])
def test_non_loopback_urls_rejected(url):
    assert is_loopback_url(url) is False


# ---------- 请求头 ----------

def test_headers_with_key_unchanged():
    """有 key：Authorization 与历史完全一致（旧行为零变化）。"""
    h = auth_headers("sk-real-key")
    assert h == {"Authorization": "Bearer sk-real-key", "Content-Type": "application/json"}


def test_headers_without_key_omit_authorization():
    """本机回环：空 key 不发 Authorization（不再发 "Bearer " 脏头）。"""
    h = auth_headers("")
    assert "Authorization" not in h
    assert h["Content-Type"] == "application/json"


def test_headers_whitespace_key_treated_as_empty():
    assert "Authorization" not in auth_headers("   ")


def test_local_endpoint_helper():
    assert is_local_endpoint("http://127.0.0.1:11434/v1") is True
    assert is_local_endpoint("https://api.deepseek.com/chat/completions") is False


# ---------- 启动校验（validate_config） ----------

def _settings(**overrides):
    from src.config import Settings
    kwargs = {
        "DEEPSEEK_API_KEY": "sk-test-key",
        "BOT_QQ": 10001,
        "WS_PORT": 3001,
        "MAX_CONCURRENT_AI": 1,
    }
    kwargs.update(overrides)
    return Settings(**kwargs)


def test_validate_allows_empty_key_for_loopback():
    """本机回环 + 空 key：允许启动（免密钥接入本机模型）。"""
    from src.config import validate_config
    cfg = _settings(DEEPSEEK_API_KEY="",
                    DEEPSEEK_API_URL="http://127.0.0.1:11434/v1/chat/completions")
    validate_config(cfg)  # 不抛


def test_validate_rejects_empty_key_for_remote():
    """第三方厂商 + 空 key：仍然拒绝（不能被本地能力放宽）。"""
    from src.config import validate_config
    cfg = _settings(DEEPSEEK_API_KEY="",
                    DEEPSEEK_API_URL="https://api.deepseek.com/chat/completions")
    with pytest.raises(ValueError):
        validate_config(cfg)


def test_validate_loopback_can_be_disabled():
    """严格模式：关掉 AI_ALLOW_LOOPBACK_NO_KEY 后回环也必须填 key。"""
    from src.config import validate_config
    cfg = _settings(DEEPSEEK_API_KEY="",
                    DEEPSEEK_API_URL="http://127.0.0.1:11434/v1/chat/completions",
                    AI_ALLOW_LOOPBACK_NO_KEY=False)
    with pytest.raises(ValueError):
        validate_config(cfg)


def test_validate_placeholder_key_still_rejected_on_remote():
    """占位符 sk-your-key-here 在远端地址下仍算未配置。"""
    from src.config import validate_config
    cfg = _settings(DEEPSEEK_API_KEY="sk-your-key-here",
                    DEEPSEEK_API_URL="https://api.deepseek.com/chat/completions")
    with pytest.raises(ValueError):
        validate_config(cfg)


# ---------- Web UI 配置链路 ----------

def test_schema_declares_loopback_switch():
    from src.services.config_schema import SCHEMA
    assert "AI_ALLOW_LOOPBACK_NO_KEY" in SCHEMA
    assert SCHEMA["AI_ALLOW_LOOPBACK_NO_KEY"][1] == "bool"
    assert SCHEMA["AI_ALLOW_LOOPBACK_NO_KEY"][3] is True  # 热更新


def test_env_template_covers_loopback_switch():
    """首次释放的 .env 模板必须包含该开关（三入口之一）。"""
    from src.config import Settings
    from src.services.env_template import default_env_text
    text = default_env_text(Settings)
    assert "AI_ALLOW_LOOPBACK_NO_KEY" in text
    assert "127.0.0.1" in text or "回环" in text


def test_account_status_marks_loopback(tmp_path):
    """用户状态页：本机回环模型显示为「免密钥」而不是「未配置 Key」。"""
    from src.services.webui_panels.account_panel import AccountPanelMixin

    class _Fake(AccountPanelMixin):
        def __init__(self, values):
            self._values = values

        class config_service:  # noqa: N801 - 简化桩
            pass

    fake = _Fake({
        "DEEPSEEK_API_URL": "http://127.0.0.1:11434/v1/chat/completions",
        "DEEPSEEK_MODEL": "qwen2.5:7b",
        "DEEPSEEK_API_KEY": "",
    })
    fake.config_service = type("S", (), {"get_value": lambda self, k: fake._values.get(k)})()
    status = fake._config_status()
    assert status["deepseek"]["loopback"] is True
    assert "本机回环" in status["deepseek"]["label"]

    fake2 = _Fake({
        "DEEPSEEK_API_URL": "https://api.deepseek.com/chat/completions",
        "DEEPSEEK_MODEL": "deepseek-flash",
        "DEEPSEEK_API_KEY": "sk-real-key",
    })
    fake2.config_service = type("S", (), {"get_value": lambda self, k: fake2._values.get(k)})()
    status2 = fake2._config_status()
    assert status2["deepseek"]["loopback"] is False
    assert status2["deepseek"]["key_set"] is True

