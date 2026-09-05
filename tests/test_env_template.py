"""首次启动：无 .env 自动释放模板（构建产物友好）；已有不覆盖。"""
import os
from pathlib import Path

from main import ensure_env_template, _DEFAULT_ENV_TEMPLATE


def test_creates_template_when_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert not Path(".env").exists()
    assert ensure_env_template() is True
    txt = Path(".env").read_text(encoding="utf-8")
    assert "Flowerie .env 配置模板" in txt
    assert "DEEPSEEK_API_KEY=sk-your-key-here" in txt
    assert "BOT_QQ=10001" in txt


def test_does_not_overwrite_existing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(".env").write_text("DEEPSEEK_API_KEY=sk-mine\n", encoding="utf-8")
    assert ensure_env_template() is False
    assert Path(".env").read_text(encoding="utf-8") == "DEEPSEEK_API_KEY=sk-mine\n"


def test_template_contains_required_keys():
    for key in ("DEEPSEEK_API_KEY", "DEEPSEEK_API_URL", "DEEPSEEK_MODEL",
                "BOT_QQ", "WS_PORT", "HTTP_API_BASE", "WEB_UI_ENABLED"):
        assert key in _DEFAULT_ENV_TEMPLATE, key
