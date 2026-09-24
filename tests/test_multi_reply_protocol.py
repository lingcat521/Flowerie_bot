"""Multi-Reply：协议无关性（任务书 §13）与 Web UI 配置（§8/§14）测试。"""
import ast
import io
import re

from src.services.config_schema import SCHEMA

CORE_FILES = [
    "src/core/reply_plan.py",
    "src/core/reply_sender.py",
    "src/core/reply_dispatch.py",
]

BANNED_MODULES = ("aiohttp", "websocket", "onebot", "milky", "adapters", "requests")


def _imported_modules(path: str):
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    mods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods.append(node.module or "")
    return mods


def test_core_imports_no_protocol_modules():
    """核心层不得依赖任何协议/传输实现 —— OneBot 与 Milky 才能共用同一套 Core。"""
    hits = []
    for f in CORE_FILES:
        for mod in _imported_modules(f):
            for banned in BANNED_MODULES:
                if banned in mod:
                    hits.append((f, mod))
    assert hits == [], hits


def test_multi_reply_configs_are_declared_for_web_ui():
    """5 个配置项必须进 SCHEMA（否则 Web UI 配置页不会出现）。"""
    keys = {
        "MULTI_REPLY_ENABLED": "bool",
        "MULTI_REPLY_MAX_MESSAGES": "int",
        "MULTI_REPLY_INTERVAL_MODE": "str",
        "MULTI_REPLY_MIN_INTERVAL": "float",
        "MULTI_REPLY_MAX_INTERVAL": "float",
    }
    for key, ctype in keys.items():
        assert key in SCHEMA, key
        category, schema_type, is_secret, hot, desc = SCHEMA[key]
        assert category == "AI", (key, category)
        assert schema_type == ctype, (key, schema_type)
        assert is_secret is False and hot is True, key
        assert desc.strip(), key


def test_config_defaults_exist_in_settings():
    """Settings 必须有对应默认值（热更新/回退要用）。"""
    text = io.open("src/config.py", encoding="utf-8").read()
    for key, default in (("MULTI_REPLY_ENABLED", "False"),
                         ("MULTI_REPLY_MAX_MESSAGES", "3"),
                         ("MULTI_REPLY_INTERVAL_MODE", chr(34) + "random" + chr(34)),
                         ("MULTI_REPLY_MIN_INTERVAL", "1.5"),
                         ("MULTI_REPLY_MAX_INTERVAL", "4.0")):
        pattern = re.escape(key) + r"\s*:\s*\w+\s*=\s*" + re.escape(default)
        assert re.search(pattern, text), key


def test_default_is_off_so_behavior_is_unchanged():
    """默认必须关闭：不配置时行为与旧版完全一致。"""
    assert "MULTI_REPLY_ENABLED: bool = False" in io.open("src/config.py", encoding="utf-8").read()
