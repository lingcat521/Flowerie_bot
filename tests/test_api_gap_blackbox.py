"""API 缺口真进程黑盒：插件子进程调用 v2.1 语义方法 → action 协议往返（handler 判定）。"""
import json
import os
import shutil

import pytest

from src.plugins.manifest import PluginManifest
from src.plugins.runtime import PluginRuntime

TESTS_PLUGINS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugins")


def _deploy(tmp_path):
    dst = tmp_path / "gap_echo"
    shutil.copytree(os.path.join(TESTS_PLUGINS, "gap_echo"), dst)
    return str(dst)


class _Sender:
    """黑盒网关侧语义（与 manager._ext_* 相同契约：search/quote/friend/member 等）。"""

    def __init__(self):
        self.calls = []

    async def get_group_msg_history(self, group_id, count=15):
        self.calls.append(("h", group_id))
        return {"messages": [{"message": "hello world", "message_id": 1}]}

    async def get_msg(self, message_id):
        return {"message": {"message": "src", "quote_id": None}}

    async def get_friend_list(self):
        return {"data": [{"user_id": 100, "nickname": "阿雪"}]}

    async def get_group_member_list(self, group_id):
        return {"members": [{"user_id": 1, "nickname": "阿雪", "role": "admin"}]}


@pytest.mark.asyncio
async def test_gap_api_blackbox_full_roundtrip(tmp_path):
    """真进程 → 插件调用 9 类缺口 API → 逐项验证 → 返回 test_ok（黑盒往返）。"""
    # 手动桥接：action → 语义（照搬 manager._ext_* 的最小响应；目的=协议往返而非重复实现）
    async def handler(pid, action, payload):
        if action == "split_message":
            text, limit = payload["text"], int(payload.get("limit", 2000))
            segs = [text[i:i + limit] for i in range(0, len(text), limit)]
            return {"ok": True, "segments": segs}
        if action == "merge_message":
            return {"ok": True, "text": "".join(str(x) for x in payload["segments"])}
        if action == "search_message":
            return {"ok": True, "results": [], "count": 0}
        if action == "quote_chain":
            return {"ok": True, "chain": [{"message_id": 5}], "depth": 1}
        if action == "friend_detail":
            return {"ok": True, "friend": {"user_id": 100}}
        if action == "group_member_search":
            return {"ok": True, "results": [], "count": 0}
        if action == "cache_get":
            return {"ok": False, "error": "key 不存在"}
        if action in ("db_query",):
            return {"ok": True, "rows": [], "total": 0}
        if action == "kv_get":
            return {"ok": False, "error": "missing"}
        if action == "ai_token":
            return {"ok": True, "tokens_estimate": 4}
        if action == "http_request":
            return {"ok": True}
        if action == "get_memory":
            return {"ok": True, "memory": ""}
        if action == "log":
            return {"ok": True}
        return {"ok": False, "error": f"unhandled {action}"}

    dir_path = _deploy(tmp_path)
    rt = PluginRuntime("gap_echo", None, dir_path, protection="normal")
    from src.plugins.manifest import PluginManifest
    mf = PluginManifest.load(os.path.join(dir_path, "manifest.json"))
    rt = PluginRuntime("gap_echo", mf, dir_path, protection="normal")
    rt._limits["event_timeout"] = 5.0
    rt._limits["startup_timeout"] = 10.0
    rt.set_action_handler(handler)
    await rt.start()
    try:
        actions = await rt.dispatch_event("message", {
            "group_id": 1, "user_id": 2, "text": "hi", "message_id": 9})
        assert actions, "插件未返回 action"
        first = actions[0]
        assert first["type"] == "test_ok", f"黑盒往返失败: {json.dumps(first, ensure_ascii=False)}"
    finally:
        await rt.shutdown()


@pytest.mark.asyncio
async def test_gap_not_supported_explicit_from_subprocess(tmp_path):
    """无端点方法：插件侧收到确定性的 not supported 错误（绝不静默）。"""
    plugin_dir = tmp_path / "ns_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "manifest.json").write_text(json.dumps({
        "id": "ns_plugin", "name": "NS", "version": "1.0.0", "runtime": "python",
        "entry": "plugin.py", "api_version": "1", "permissions": []}), encoding="utf-8")
    (plugin_dir / "plugin.py").write_text(
        "def on_message(event, api=None):\n"
        "    r = api.edit_message({'message_id': 1}) if api else None\n"
        "    if r and not r.get('ok') and 'not supported' in r.get('error', ''):\n"
        "        return {'type': 'test_ok'}\n"
        "    return {'type': 'test_fail', 'reason': str(r)}\n", encoding="utf-8")
    rt = PluginRuntime("ns_plugin", PluginManifest.load(str(plugin_dir / "manifest.json")),
                       str(plugin_dir), protection="normal")
    rt._limits["event_timeout"] = 5.0
    rt._limits["startup_timeout"] = 10.0

    async def handler(pid, action, payload):
        return {"ok": False, "error": "edit_message: 网关 v1 无对应端点（not supported）"}

    rt.set_action_handler(handler)
    await rt.start()
    try:
        actions = await rt.dispatch_event("message", {"text": "x"})
        assert actions and actions[0]["type"] == "test_ok", actions
    finally:
        await rt.shutdown()
