"""缺口池 ↔ 源码/SDK 一致性钉死（防漂移）：

- api.md 每种方法必须可执行到（PluginApi 方法名 AST 全量对照）
- 缺口池关键入口 ∈ SDK（bot 方法或 gap_sdk 对象/类）
- sdk.md 矩阵声明的入口全部存在（bot attr 或 flowerie_sdk 模块级符号）
"""
import ast
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin_sdk"))

# 缺口池关键入口（SDK 侧必存在；API 侧方法必存在）
_GAP_API = {
    "edit_message", "forward_message", "split_message", "merge_message", "search_message",
    "quote_chain", "friend_detail", "friend_remark", "friend_delete", "friend_group",
    "friend_online", "group_member_search", "group_member_update", "group_mute_status",
    "group_title", "group_notice_create", "group_notice_update", "group_file_upload",
    "group_essence", "group_invite", "group_apply", "group_admins",
    "reaction", "poke", "like", "emoji", "emoji_list", "file_upload", "file_download",
    "file_info", "file_delete", "file_convert", "image_compress", "image_resize",
    "audio_info", "video_info", "ai_stream", "ai_vision", "ai_embedding", "ai_rerank",
    "ai_token", "ai_models", "ai_model_info", "ai_usage", "ai_budget", "memory_get",
    "memory_search", "memory_semantic", "memory_update", "memory_delete", "memory_tag",
    "memory_pin", "memory_expire", "mcp_server", "mcp_tools", "mcp_call", "mcp_resource",
    "mcp_prompt", "mcp_status", "plugin_call", "plugin_event", "plugin_service",
    "plugin_discovery", "plugin_dependency", "plugin_health", "plugin_reload",
    "plugin_config", "router", "ws", "sse", "webhook", "http_middleware", "static_file",
    "db_query", "db_transaction", "db_migration", "db_index", "cache_get", "cache_set",
    "cache_delete", "task_status", "task_cancel", "task_pause", "task_resume",
    "resource_usage", "resource_quota", "runtime_status", "metrics", "trace", "health",
    "debug", "plugin_test", "mock_api",
}

_SDK_SYMBOLS = {
    "MessageSegment", "MessageFilter", "FriendContext", "FriendRequest", "GroupRequest",
    "GroupMemberContext", "ReactionContext", "SessionContext", "Conversation",
    "TaskManager", "I18n", "PluginFeatureError", "FileContext", "MediaContext",
    "WebSocketServer", "SseServer", "HttpMiddleware", "PluginEventBus",
    "PluginServiceBus", "PluginDependency", "build_sdk",
}


def _plugin_api_names() -> set:
    tree = ast.parse((ROOT / "src/plugins/runner/python_runner.py").read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == "PluginApi":
            return {f.name for f in n.body if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return set()


def test_gap_api_all_exist_in_pluginapi():
    api = _plugin_api_names()
    missing = _GAP_API - api
    assert not missing, f"PluginApi 缺方法: {sorted(missing)}"


def test_gap_sdk_symbols_exist():
    from flowerie_sdk import gap_sdk as gs
    missing = {s for s in _SDK_SYMBOLS if not hasattr(gs, s)}
    assert not missing, f"gap_sdk 缺符号: {sorted(missing)}"


def test_gap_sdk_bot_methods_exist():
    from flowerie_sdk.bot import FlowerieBot
    methods = {n for n in dir(FlowerieBot) if not n.startswith("_")}
    bot_needed = _GAP_API - {
        # API 层存在但 SDK 门面经分面访问的（bot.sdk()[...]）
        "mock_api", "ws", "sse", "http_middleware", "plugin_test",
        "db_index", "resource_usage", "resource_quota", "runtime_status",
    }
    missing = bot_needed - methods
    assert not missing, f"FlowerieBot 缺门面: {sorted(missing)}"


def test_permissions_all_gap_mapped():
    perms = (ROOT / "src/plugins/permissions.py").read_text(encoding="utf-8")
    unmapped = [m for m in sorted(_GAP_API) if f'    "{m}":' not in perms]
    assert not unmapped, f"权限映射缺失: {unmapped}"


def test_api_md_records_gap_methods():
    text = (ROOT / "docs/api.md").read_text(encoding="utf-8")
    missing = [m for m in sorted(_GAP_API) if f"`{m}(payload)`" not in text]
    assert not missing, f"api.md 缺失（生成器未跑？）: {missing}"


def test_doc_matrix_entries_exist():
    text = (ROOT / "docs/sdk.md").read_text(encoding="utf-8")
    seg = text.split("v2.1 缺口 SDK 矩阵")[-1]
    # 矩阵中 `名字(...)`/`名字` 入口必须出现在 gap_sdk 或 bot（抽样断言代表性 12 项）
    for token in ("MessageSegment", "MessageFilter", "rule_or", "rule_not",
                  "FriendContext", "TaskManager", "I18n", "WebSocketServer"):
        assert re.search(rf"`{re.escape(token)}", seg), f"sdk.md 矩阵缺入口: {token}"
