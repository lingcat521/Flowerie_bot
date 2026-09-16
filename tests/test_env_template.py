"""首次启动 .env 模板测试：与 config_schema.SCHEMA 同源、带分组与中文说明。"""
from src.services.env_template import (
    REQUIRED_PLACEHOLDERS,
    format_value,
    render_env_template,
)

SCHEMA = {
    "DEEPSEEK_API_KEY": ("AI", "secret", True, True, "DeepSeek API 密钥（必填）"),
    "DEEPSEEK_MODEL": ("AI", "str", False, True, "群聊对话模型"),
    "QQ_PROTOCOL": ("Bot", "str", False, False, "协议端：onebot / milky"),
    "MEMORY_ENABLED": ("Memory", "bool", False, True, "长期记忆总开关"),
    "ALLOWED_GROUP_IDS": ("Whitelist", "list-int", False, True, "白名单群号"),
}
ORDER = ["AI", "Bot", "Memory", "Whitelist"]
LABELS = {"AI": "AI / Provider 配置", "Bot": "基础配置", "Memory": "记忆库", "Whitelist": "白名单与隐私"}
DEFAULTS = {
    "DEEPSEEK_API_KEY": "", "DEEPSEEK_MODEL": "deepseek-v4-flash", "QQ_PROTOCOL": "onebot",
    "MEMORY_ENABLED": False, "ALLOWED_GROUP_IDS": [10001, 10002], "INTERNAL_ONLY": "x",
}


def _render(**over):
    kw = dict(schema=SCHEMA, category_order=ORDER, category_labels=LABELS, defaults=DEFAULTS)
    kw.update(over)
    return render_env_template(**kw)


def test_groups_and_labels_present():
    text = _render()
    for label in LABELS.values():
        assert ("# ========== %s ==========" % label) in text, label


def test_every_key_has_chinese_description():
    text = _render()
    for key, meta in SCHEMA.items():
        assert ("# %s" % meta[4]) in text, key
        assert ("%s=" % key) in text, key


def test_required_placeholder_and_marks():
    text = _render()
    assert "DEEPSEEK_API_KEY=sk-your-key-here" in text
    assert "⚠️ 必填" in text
    assert "密钥" in text                      # secret 标记
    assert "QQ_PROTOCOL=onebot  # 需重启" in text  # 非热更新标记


def test_bool_and_list_rendering():
    text = _render()
    assert "MEMORY_ENABLED=false" in text
    assert 'ALLOWED_GROUP_IDS=[10001, 10002]' in text


def test_settings_only_fields_appended_at_end():
    """SCHEMA 未覆盖但 Settings 有的字段必须仍然出现（全量导出不退化）。"""
    text = _render()
    assert "INTERNAL_ONLY=x" in text
    assert text.index("INTERNAL_ONLY=x") > text.index("ALLOWED_GROUP_IDS")


def test_header_mentions_first_run_and_same_source():
    text = _render()
    assert "首次启动自动生成" in text
    assert "config_schema.SCHEMA" in text


def test_ends_with_single_newline():
    text = _render()
    assert text.endswith("\n") and not text.endswith("\n\n")


def test_empty_schema_does_not_crash():
    text = render_env_template({}, [], {}, {})
    assert "首次启动自动生成" in text


def test_format_value_types():
    assert format_value(True) == "true"
    assert format_value(False) == "false"
    assert format_value(None) == ""
    assert format_value(3) == "3"
    assert format_value("s") == "s"
    assert format_value([1, "a"]) == '[1, "a"]'


def test_real_schema_has_placeholders_for_required():
    """真实 SCHEMA 里必填项（DEEPSEEK_API_KEY / BOT_QQ）必须有占位值。"""
    from src.services.config_schema import SCHEMA as REAL_SCHEMA
    for key in REQUIRED_PLACEHOLDERS:
        assert key in REAL_SCHEMA, "必填项不在 SCHEMA 里: %s" % key

