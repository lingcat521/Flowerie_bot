"""首次启动：无 .env 自动释放模板（构建产物友好）；已有不覆盖。"""
from pathlib import Path

from main import _default_env_text, ensure_env_template


def test_creates_template_when_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert not Path(".env").exists()
    assert ensure_env_template() is True
    txt = Path(".env").read_text(encoding="utf-8")
    assert "Flowerie .env 完整配置模板" in txt
    assert "DEEPSEEK_API_KEY=sk-your-key-here" in txt
    assert "BOT_QQ=10001" in txt
    assert "WS_PORT=3001" in txt and "VISION_ENABLED=true" in txt


def test_does_not_overwrite_existing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(".env").write_text("DEEPSEEK_API_KEY=sk-mine\n", encoding="utf-8")
    assert ensure_env_template() is False
    assert Path(".env").read_text(encoding="utf-8") == "DEEPSEEK_API_KEY=sk-mine\n"


def test_template_contains_required_keys():
    txt = _default_env_text()
    for key in ("DEEPSEEK_API_KEY", "DEEPSEEK_API_URL", "DEEPSEEK_MODEL",
                "BOT_QQ", "WS_PORT", "HTTP_API_BASE", "WEB_UI_ENABLED",
                "VISION_ENABLED", "MEMORY_DISABLED_GROUPS", "GROUP_NICKNAMES_PATH"):
        assert key in txt, key
    # 完整导出：所有 Settings 字段都在模板中
    from src.config import Settings
    for name in Settings.model_fields:
        assert name + "=" in txt or name + "=" in txt, name
