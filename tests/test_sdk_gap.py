"""SDK 缺口层（gap_sdk）：组合器/上下文/分面/任务/过滤/i18n/config/mock/NS 桩。"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin_sdk"))

from flowerie_sdk.gap_sdk import (
    Conversation,
    FriendContext,
    HttpMiddleware,
    I18n,
    MessageFilter,
    MessageSegment,
    PluginFeatureError,
    SessionContext,
    SseServer,
    TaskManager,
    WebSocketServer,
    build_sdk,
)
from flowerie_sdk.matcher import rule_all, rule_not, rule_or

from src.plugins.manager import PluginManager


def test_message_segment_and_filter():
    assert MessageSegment.text("hi") == {"type": "text", "data": {"text": "hi"}}
    assert MessageSegment.at(100)["data"]["qq"] == "100"
    f = MessageFilter({"text_contains": "钱"})
    got = f.apply([{"text": "收到 100 块钱"}, {"text": "hello"}])
    assert len(got) == 1 and got[0]["text"] == "收到 100 块钱"


def test_matcher_combinators():
    m = PluginManager._rule_matches
    r = rule_or(rule_or({"text_contains": "a"}), {"text_contains": "b"})
    assert m(r, {"text": "bb"}) and not m(r, {"text": "cc"})
    assert m(rule_all({"text_contains": "a"}, {"group_id": 1}), {"text": "a", "group_id": 1})
    assert not m(rule_all({"text_contains": "a"}, {"group_id": 1}), {"text": "a", "group_id": 2})
    assert m(rule_not({"text_contains": "禁"}), {"text": "开放"})
    assert not m(rule_not({"text_contains": "禁"}), {"text": "禁止"})


def test_contexts_forward():
    class Bot:
        _api = object()

        def friend_detail(self, uid): return {"ok": True, "uid": uid}

        def friend_remark(self, uid, t): return {"ok": True}

        def group_member_search(self, g, q): return {"ok": True, "g": g}

        def memory_search(self, q, g=0, k=3): return {"ok": True}

        def reaction(self, m, t): return {"ok": True, "m": m}

        def handle_friend_request(self, p): return {"ok": True, "p": p}

    bot = Bot()
    fc = FriendContext(bot, user_id=7)
    assert fc.detail()["uid"] == 7
    assert fc.remark("新备注")["ok"]
    ctx = SessionContext(bot, group_id=3)
    assert ctx.recall("q")["ok"]
    conv = Conversation(bot)
    conv.add_round(1, "你好")
    assert conv.history(1) == ["你好"]


def test_facades_via_build_sdk():
    class Bot:
        _api = object()

        def ai_stream(self, prompt=None, **kw): return {"ok": True, "p": prompt}

        def memory_search(self, q, g=0, k=3): return {"ok": True, "q": q}

        def mcp_tools(self): return {"ok": True, "t": []}

        def db_query(self, w=None, limit=50, offset=0): return {"ok": True}

        def cache_get(self, k): return {"ok": True, "k": k}

        def resource_usage(self): return {"ok": True}

        def metrics(self): return {"ok": True}

        def file_upload(self, n, d): return {"ok": True}

        def plugin_service(self, op, **kw): return {"ok": True, "op": op}

        def plugin_event(self, name, data=None, target=""): return {"ok": True}

    bot = Bot()
    sdk = build_sdk(bot, base_dir=str(Path(__file__).parent))
    assert sdk["ai"].chat("hello")["ok"]
    assert sdk["memory"].search("q")["q"] == "q"
    assert sdk["mcp"].tools()["ok"]
    assert sdk["db"].query()["ok"]
    assert sdk["cache"].get("k")["k"] == "k"
    assert sdk["runtime"].usage()["ok"]
    assert sdk["metrics"].snapshot()["ok"]
    assert sdk["events"].publish("e")["ok"]
    assert sdk["services"].register("svc")["op"] == "register"


def test_task_manager_lifecycle():
    tm = TaskManager()
    h = tm.submit("j1", lambda: (time.sleep(0.02), "done")[1])
    assert tm.status("j1")["ok"]
    time.sleep(0.15)
    assert h.done and h.wait() == "done"
    assert tm.status("missing")["ok"] is False


def test_i18n_and_mock(tmp_path):
    (tmp_path / "i18n").mkdir()
    (tmp_path / "i18n" / "zh.json").write_text('{"hello": "你好 {name}"}', encoding="utf-8")
    i = I18n(base_dir=str(tmp_path), default_lang="zh")
    assert i.t("hello", name="世界") == "你好 世界"
    assert i.t("missing") == "missing"


def test_ns_stubs_raise():
    for cls in (WebSocketServer, SseServer, HttpMiddleware):
        with pytest.raises(PluginFeatureError):
            cls()
