"""v2.1 缺口池 Batch1（消息+好友）：语义执行（本地真实现/路由/受控 NS）+ SDK 门面。"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

# 仅在需要 SDK 的测试内局部加载（避免全局 path 污染叠加测试副本）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin_sdk"))

from src.plugins.manager import PluginManager


class _Cfg:
    PLUGIN_DIR = "/tmp/gap_plugins"


class _Repo:
    def list_plugins(self):
        return []


class _FakeSender:
    def __init__(self):
        self.calls = []

    async def get_group_msg_history(self, group_id, count=15):
        self.calls.append(("history", group_id))
        return {"messages": [{"message": "你好 QQ 群", "message_id": 1},
                             {"message": "hello world", "message_id": 2}]}

    async def get_friend_msg_history(self, user_id, count=20):
        self.calls.append(("fh", user_id))
        return {"messages": [{"message": "私聊消息", "message_id": 3}]}

    async def get_msg(self, message_id):
        if message_id == 5:
            return {"message": {"message": "引用源", "quote_id": None}}
        return {"message": {"message": "一级引用", "quote_id": 5}}

    async def get_friend_list(self):
        return {"data": [{"user_id": 100, "nickname": "阿雪"}]}

    async def send_group_forward_msg(self, group_id, messages):
        self.calls.append(("gf", group_id))
        return {"ok": True}

    async def send_private_forward_msg(self, user_id, messages):
        self.calls.append(("pf", user_id))
        return {"ok": True}


def _mgr():
    sender = _FakeSender()
    mgr = PluginManager(config=_Cfg(), repository=_Repo(), sender=sender)
    return mgr, sender


def _run(mgr, pid, act, payload):
    return asyncio.run(mgr._run_action(pid, act, payload))


def test_search_local_filter():
    mgr, s = _mgr()
    r = _run(mgr, "p", "search_message", {"group_id": 1, "query": "hello", "count": 10})
    assert r["ok"] and r["count"] == 1 and r["results"][0]["message"] == "hello world"


def test_search_private():
    mgr, _s = _mgr()
    r = _run(mgr, "p", "search_message", {"user_id": 9, "query": "私聊"})
    assert r["ok"] and r["count"] == 1


def test_quote_chain_depth():
    mgr, _s = _mgr()
    r = _run(mgr, "p", "quote_chain", {"message_id": 2})
    assert r["ok"] and r["depth"] == 2 and r["chain"][0]["message_id"] == 2


def test_split_merge_roundtrip():
    mgr, _s = _mgr()
    sp = _run(mgr, "p", "split_message", {"text": "abcdef", "limit": 2})
    assert sp["ok"] and sp["segments"] == ["ab", "cd", "ef"]
    mg = _run(mgr, "p", "merge_message", {"segments": sp["segments"]})
    assert mg["ok"] and mg["text"] == "abcdef"


def test_forward_routes_group_vs_private():
    mgr, s = _mgr()
    _run(mgr, "p", "forward_message", {"group_id": 99, "text": "转发内容"})
    assert ("gf", 99) in s.calls
    _run(mgr, "p", "forward_message", {"user_id": 88, "messages": [{"type": "text"}]})
    assert ("pf", 88) in s.calls


def test_friend_detail():
    mgr, _s = _mgr()
    r = _run(mgr, "p", "friend_detail", {"user_id": 100})
    assert r["ok"] and r["friend"]["nickname"] == "阿雪"
    r2 = _run(mgr, "p", "friend_detail", {"user_id": 999})
    assert not r2["ok"] and "未找到" in r2["error"]


@pytest.mark.parametrize("act", ["edit_message", "favorite_message", "mark_message",
                                 "read_status", "friend_remark", "friend_delete",
                                 "friend_group", "friend_category", "friend_online"])
def test_not_supported_explicit(act):
    mgr, _s = _mgr()
    r = _run(mgr, "p", act, {})
    assert not r["ok"] and "not supported" in r["error"]


def test_sdk_facade_no_api():
    from plugin_sdk.flowerie_sdk.bot import FlowerieBot
    bot = FlowerieBot()
    r = bot.forward_message([{"type": "text", "data": {"text": "hi"}}])
    assert not r["ok"] and "attach" in r["error"]


def test_sdk_facade_forwards():
    from plugin_sdk.flowerie_sdk.bot import FlowerieBot

    class Api:
        def search_message(self, payload):
            return {"ok": True, "count": payload["count"]}

    bot = FlowerieBot()
    bot._api = Api()
    r = bot.search_message("q", group_id=1, count=5)
    assert r["ok"] and r["count"] == 5


def test_group_member_search_and_admins():
    mgr, _s = _mgr()
    class S2(_FakeSender):
        async def get_group_member_list(self, group_id):
            self.calls.append(("members", group_id))
            return {"members": [{"user_id": 1, "nickname": "阿雪", "role": "admin"},
                                {"user_id": 2, "nickname": "小明", "role": "member"}]}
    sender = S2()
    from src.plugins.manager import PluginManager
    mgr = PluginManager(config=_Cfg(), repository=_Repo(), sender=sender)
    r = _run(mgr, "p", "group_member_search", {"group_id": 5, "query": "阿雪"})
    assert r["ok"] and r["count"] == 1 and r["results"][0]["user_id"] == 1
    a = _run(mgr, "p", "group_admins", {"group_id": 5})
    assert a["ok"] and a["count"] == 1 and a["admins"][0]["user_id"] == 1


def test_group_not_supported_explicit():
    mgr, _s = _mgr()
    for act in ("group_mute_status", "group_file_upload", "group_file_rename", "group_invite"):
        r = _run(mgr, "p", act, {})
        assert not r["ok"] and "not supported" in r["error"]


def test_social_alias_and_poke_route():
    mgr, s = _mgr()
    r = _run(mgr, "p", "reaction", {"message_id": 7, "react_type": 1})
    assert r.get("error", "").find("not supported") == -1 or (not r["ok"])
    r2 = _run(mgr, "p", "poke", {"user_id": 5})
    assert "群戳" not in r2.get("error", "")  # 好友戳走 fake（无端点方法→error 路径正常处理）
    r3 = _run(mgr, "p", "poke", {"group_id": 9, "user_id": 5})
    # 群戳走 tap(send_poke)：fake sender 无该方法 → 明确"网关不支持该能力"
    assert not r3["ok"] and "不支持" in r3["error"]


def test_file_space_roundtrip(tmp_path):

    from src.plugins.manager import PluginManager
    class C2(_Cfg):
        PLUGIN_DIR = str(tmp_path)
    mgr = PluginManager(config=C2(), repository=_Repo())
    up = _run(mgr, "p", "file_upload", {"name": "info.txt", "data": "hello"})
    assert up["ok"] and up["size"] == 5
    info = _run(mgr, "p", "file_info", {"name": "info.txt"})
    assert info["ok"] and info["info"]["size"] == 5
    dl = _run(mgr, "p", "file_download", {"name": "info.txt"})
    assert dl["ok"] and dl["data"] == "hello"
    de = _run(mgr, "p", "file_delete", {"name": "info.txt"})
    assert de["ok"]


def test_file_ns_explicit():
    mgr, _s = _mgr()
    for act, payload in (("file_convert", {"name": "a.txt"}),
                         ("image_compress", {"name": "a.png"}),
                         ("audio_info", {"name": "a.mp3"}),
                         ("emoji_list", {"message_id": 1})):
        r = _run(mgr, "p", act, payload)
        assert not r["ok"] and "not supported" in r["error"]


def test_ai_local_semantics():
    mgr, _s = _mgr()
    class C3(_Cfg):
        DEEPSEEK_MODEL = "deepseek-chat"
        DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
        VISION_MODEL = ""
        BLOSSOM_MEMORY_EMBEDDING_MODEL = ""
        BLOSSOM_MEMORY_RERANKER_MODEL = ""
        DAILY_AI_CALL_BUDGET = 100
        GROUP_DAILY_AI_CALL_BUDGET = 20
        BUDGET_EXHAUSTED_NOTICE = True
    mgr2 = PluginManager(config=C3(), repository=_Repo())
    t = _run(mgr2, "p", "ai_token", {"text": "你好world"})
    assert t["ok"] and t["tokens_estimate"] > 0
    ms = _run(mgr2, "p", "ai_models", {})
    assert ms["ok"] and "DEEPSEEK_MODEL" in ms["models"]
    mi = _run(mgr2, "p", "ai_model_info", {"model": "VISION_MODEL"})
    assert mi["ok"] and mi["kind"] == "vision"
    b = _run(mgr2, "p", "ai_budget", {})
    assert b["ok"] and b["daily_limit"] == 100


def test_ai_embedding_missing_config():
    mgr, _s = _mgr()
    r = _run(mgr, "p", "ai_embedding", {"text": "x"})
    assert not r["ok"] and "未配置" in r["error"]
    r2 = _run(mgr, "p", "ai_rerank", {"query": "q", "documents": ["a"]})
    assert not r2["ok"] and "未配置" in r2["error"]


def test_memory_alias_and_ns():
    mgr, _s = _mgr()
    r = _run(mgr, "p", "memory_pin", {"key": "k"})
    assert not r["ok"] and "not supported" in r["error"]
    r2 = _run(mgr, "p", "memory_expire", {})
    assert not r2["ok"] and "not supported" in r2["error"]
    # memory_get 别名走 get_memory（fake sender 无该端点→明确错误，但不报"未知语义"）
    r3 = _run(mgr, "p", "memory_get", {})
    assert "未知语义" not in r3.get("error", "")


def test_mcp_config_lists():
    class C4(_Cfg):
        MCP_ENABLED = True
        MCP_SERVER_URL = ""
        MCP_SERVERS = json.dumps([
            {"name": "s1", "url": "https://mcp.example.com/rpc", "tools": "a,b"},
            {"name": "s2", "url": "http://127.0.0.1:9000/mcp", "tools": "*"}])
        MCP_TIMEOUT = 10
    mgr2 = PluginManager(config=C4(), repository=_Repo())
    sv = _run(mgr2, "p", "mcp_server", {})
    assert sv["ok"] and len(sv["servers"]) == 2
    tools = _run(mgr2, "p", "mcp_tools", {})
    assert tools["ok"] and tools["tools"][0]["allowed_tools"] == ["a", "b"]
    # 白名单拒绝（不经网络）
    den = _run(mgr2, "p", "mcp_call", {"server": "s1", "tool": "evil"})
    assert not den["ok"] and "白名单" in den["error"]
    # 未找到服务器
    nf = _run(mgr2, "p", "mcp_status", {"server": "nope"})
    assert not nf["ok"] and "未找到" in nf["error"]


class _ManifestStub:
    def __init__(self):
        self.permissions = ["plugin_admin"]
        self.api_version = "1"
        self.declarations = []
        self.config = {"k": "v"}
        self.web_ui = {"pages": [{"id": "home", "title": "总览"}]}


def test_plugin_semantics_local():
    mgr, _s = _mgr()
    class Row:
        id = "abc"
        name = "ABC"
        enabled = True
        version = "1.0.0"
        install_source = "test"
    mgr.get_plugin = lambda pid: Row() if pid == "abc" else None
    mgr._manifest_of = lambda r: _ManifestStub()
    mgr.list_plugins = lambda: [{"id": "abc", "name": "ABC", "enabled": True,
                                 "version": "1.0.0", "install_source": "test"}]
    d = _run(mgr, "p", "plugin_discovery", {})
    assert d["ok"] and d["plugins"][0]["id"] == "abc"
    h = _run(mgr, "p", "plugin_health", {})
    assert h["ok"] and h["running"] is False
    c = _run(mgr, "p", "plugin_config", {})
    assert c["ok"] and c["config"]["k"] == "v"
    r = _run(mgr, "p", "router", {})
    assert r["ok"] and r["pages"][0]["id"] == "home"


def test_plugin_call_delivery():
    mgr, _s = _mgr()
    got = {}

    class Rt:
        def _call_hook(self, name, ev):
            got["ev"] = ev
            return {"ok": True}

    mgr._runtimes["target"] = Rt()
    mgr.get_plugin = lambda pid: {"id": "target", "enabled": True} if pid == "target" else None
    r = _run(mgr, "p", "plugin_call", {"target": "target", "name": "ping", "data": {"a": 1}})
    assert r["ok"] and r["delivered"] == "target"
    assert got["ev"]["caller"] == "p" and got["ev"]["data"]["a"] == 1
    # 自身调用拒绝
    r2 = _run(mgr, "p", "plugin_call", {"target": "p"})
    assert not r2["ok"] and "自身" in r2["error"]
    # 未启用目标
    mgr.get_plugin = lambda pid: {"id": "target", "enabled": False} if pid == "target" else None
    r3 = _run(mgr, "p", "plugin_call", {"target": "target"})
    assert not r3["ok"] and "未启用" in r3["error"]


def test_plugin_web_ns():
    mgr, _s = _mgr()
    for act in ("ws", "sse", "http_middleware"):
        r = _run(mgr, "p", act, {})
        assert not r["ok"] and "不支持" in r["error"]
    h = _run(mgr, "p", "webhook", {"url": "https://a.b/c", "method": "POST"})
    assert "未知语义" not in h.get("error", "")


def test_db_roundtrip_and_transaction(tmp_path):
    from src.plugins.manager import PluginManager
    class C5(_Cfg):
        PLUGIN_DIR = str(tmp_path)
    mgr = PluginManager(config=C5(), repository=_Repo())
    t = _run(mgr, "p", "db_transaction", {"ops": [
        {"type": "insert", "row": {"id": 1, "name": "a"}},
        {"type": "insert", "row": {"id": 2, "name": "b"}}]})
    assert t["ok"] and t["applied"] == 2
    q = _run(mgr, "p", "db_query", {"where": {"name": "b"}})
    assert q["ok"] and q["total"] == 1 and q["rows"][0]["id"] == 2
    m = _run(mgr, "p", "db_migration", {"version": 2})
    assert m["ok"] and m["schema_version"] == 2


def test_health_and_metrics_local():
    mgr, _s = _mgr()
    h = _run(mgr, "p", "health", {})
    assert h["ok"] and h["status"] == "healthy"
    met = _run(mgr, "p", "metrics", {})
    assert met["ok"] and isinstance(met["metrics"], dict)


def test_task_ns_and_cache_alias():
    mgr, _s = _mgr()
    r = _run(mgr, "p", "task_status", {"task_id": "x"})
    assert not r["ok"] and "TaskManager" in r["error"]
    r2 = _run(mgr, "p", "debug", {})
    assert not r2["ok"]


def test_poke_group_routing():
    mgr, s = _mgr()

    class S3(_FakeSender):
        async def send_poke(self, group_id, user_id):
            self.calls.append(("sp", group_id, user_id))
            return {"ok": True}

    mgr2 = PluginManager(config=_Cfg(), repository=_Repo(), sender=S3())
    r = _run(mgr2, "p", "poke", {"group_id": 9, "user_id": 5})
    assert r["ok"] and ("sp", 9, 5) in mgr2.sender.calls
