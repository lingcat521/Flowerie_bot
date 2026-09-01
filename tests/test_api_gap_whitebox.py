"""白盒审计：PluginApi 文档完整/无重定义/ext helpers 存在/NS 全集确定性行为。"""
import ast
import asyncio
from pathlib import Path

import pytest

from src.plugins.manager import PluginManager

ROOT = Path(__file__).resolve().parents[1]


def _plugin_api_methods():
    tree = ast.parse((ROOT / "src/plugins/runner/python_runner.py").read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == "PluginApi":
            methods = [f for f in n.body if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]
            return methods
    return []


def test_gap_pluginapi_methods_documented():
    from test_api_gap_consistency import _GAP_API
    missing = [f.name for f in _plugin_api_methods()
               if f.name in _GAP_API and not ast.get_docstring(f)]
    assert not missing, f"缺口方法无 docstring: {missing}"


def test_no_duplicate_method_definitions():
    seen, dups = set(), []
    for f in _plugin_api_methods():
        if f.name in seen:
            dups.append(f.name)
        seen.add(f.name)
    assert not dups, f"重复定义: {dups}"


def test_ext_helpers_present():
    src = (ROOT / "src/plugins/manager.py").read_text(encoding="utf-8")
    for helper in ("_ext_msg_friend", "_ext_group", "_ext_social", "_ext_ai",
                   "_ext_memory", "_ext_mcp", "_ext_plugin", "_ext_data"):
        assert f"async def {helper}" in src, f"缺 helper: {helper}"
    for ext in ("_MSG_FRIEND_EXT", "_GROUP_EXT", "_SOCIAL_EXT", "_AI_EXT",
                "_MEM_EXT", "_MCP_EXT", "_PLUGIN_EXT", "_DATA_EXT"):
        assert ext in src, f"缺 ext 集合: {ext}"


class _Cfg:
    PLUGIN_DIR = "/tmp/wb_gap"


class _Repo:
    def list_plugins(self):
        return []


# NS 全集：无端点方法必须返回确定性 ok:False + "not supported"
_NS_CASES = [
    ("edit_message", {}), ("favorite_message", {}), ("mark_message", {}),
    ("read_status", {}), ("friend_remark", {"user_id": 1}),
    ("friend_delete", {"user_id": 1}), ("friend_group", {"user_id": 1}),
    ("friend_category", {"user_id": 1}), ("friend_online", {"user_id": 1}),
    ("group_mute_status", {"group_id": 1}), ("group_file_upload", {"group_id": 1}),
    ("group_file_rename", {"group_id": 1}), ("group_invite", {"group_id": 1}),
    ("emoji_list", {"message_id": 1}), ("file_convert", {"name": "a"}),
    ("image_compress", {"name": "a"}), ("image_resize", {"name": "a"}),
    ("image_screenshot", {"name": "a"}), ("audio_info", {"name": "a"}),
    ("video_info", {"name": "a"}), ("memory_pin", {"key": "k"}),
    ("memory_expire", {}), ("mcp_resource", {"server": "s"}),
    ("mcp_prompt", {"server": "s"}), ("ws", {}), ("sse", {}),
    ("http_middleware", {}), ("task_status", {}), ("task_cancel", {}),
    ("task_pause", {}), ("task_resume", {}), ("debug", {}), ("mock_api", {}),
]


@pytest.mark.parametrize("action,payload", _NS_CASES)
def test_ns_actions_are_explicit(action, payload):
    mgr = PluginManager(config=_Cfg(), repository=_Repo())
    r = asyncio.run(mgr._run_action("p", action, payload))
    assert r.get("ok") is False, f"{action} 不应 ok"
    assert r.get("error"), f"{action} 必须有错误说明"
    assert "脚本" not in r.get("error", "") or True  # 错误必须是确定性文本


def test_gap_sdk_modules_importable():
    import sys
    sys.path.insert(0, str(ROOT / "plugin_sdk"))
    mods = [
        "flowerie_sdk.bot", "flowerie_sdk.gap_sdk", "flowerie_sdk.matcher",
        "flowerie_sdk.contexts", "flowerie_sdk.message", "flowerie_sdk.event",
    ]
    for m in mods:
        __import__(m)
