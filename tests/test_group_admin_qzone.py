"""v2.10 群管理控制台 + QQ空间：服务层 / Adapter 映射 / 面板渲染 测试。"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.adapters.onebot.adapter import OneBotAdapter  # noqa: E402
from src.services.group_admin import GroupAdminService  # noqa: E402
from src.services.qzone import UGC_RIGHTS, QzoneService  # noqa: E402
from src.services.webui_render.admin import render_admin_tab  # noqa: E402
from src.services.webui_render.qzone import render_qzone_tab  # noqa: E402


class _Cfg:
    ADMIN_CONSOLE_ENABLED = True
    QZONE_ENABLED = True
    QZONE_DEFAULT_UGC_RIGHT = 1
    QZONE_MAX_HISTORY = 5


class _FakeAdapter:
    """记录调用参数的假 Adapter（只实现 v2.10 能力）。"""

    def __init__(self, fail=None, result=None):
        self.calls = []
        self.fail = fail or {}
        self.result = result or {}

    def _maybe_fail(self, name):
        if name in self.fail:
            raise RuntimeError(self.fail[name])

    async def set_group_admin(self, group_id, user_id, enable=True):
        self._maybe_fail("set_group_admin")
        self.calls.append(("set_group_admin", group_id, user_id, enable))
        return self.result.get("set_group_admin", {"ok": True})

    async def mute(self, group_id, user_id, duration_seconds):
        self._maybe_fail("mute")
        self.calls.append(("mute", group_id, user_id, duration_seconds))

    async def kick(self, group_id, user_id):
        self._maybe_fail("kick")
        self.calls.append(("kick", group_id, user_id))

    async def kick_with_reject(self, group_id, user_id):
        self._maybe_fail("kick_with_reject")
        self.calls.append(("kick_with_reject", group_id, user_id))
        return {"ok": True}

    async def group_card(self, group_id, user_id, card):
        self._maybe_fail("group_card")
        self.calls.append(("group_card", group_id, user_id, card))
        return {"ok": True}

    async def group_rename(self, group_id, name):
        self._maybe_fail("group_rename")
        self.calls.append(("group_rename", group_id, name))
        return {"ok": True}

    async def group_title(self, group_id, user_id, title):
        self._maybe_fail("group_title")
        self.calls.append(("group_title", group_id, user_id, title))
        return {"ok": True}

    async def group_whole_ban(self, group_id, enable):
        self._maybe_fail("group_whole_ban")
        self.calls.append(("group_whole_ban", group_id, enable))
        return {"ok": True}

    async def get_group_shut_list(self, group_id):
        self._maybe_fail("get_group_shut_list")
        self.calls.append(("get_group_shut_list", group_id))
        return {"ok": True, "data": [{"user_id": 1}, {"user_id": 2}]}

    async def quit_group(self, group_id, dismiss=False):
        self._maybe_fail("quit_group")
        self.calls.append(("quit_group", group_id, dismiss))
        return {"ok": True}

    async def qzone_publish(self, content, images, ugc_right=1, target_uins=None):
        self._maybe_fail("qzone_publish")
        self.calls.append(("qzone_publish", content, list(images), ugc_right, list(target_uins or [])))
        return self.result.get("qzone_publish", {"ok": True, "tid": "T1"})

    async def qzone_delete(self, tid):
        self._maybe_fail("qzone_delete")
        self.calls.append(("qzone_delete", tid))
        return self.result.get("qzone_delete", {"ok": True})


# ---------- GroupAdminService ----------
@pytest.mark.asyncio
async def test_admin_set_admin_and_unset():
    ad = _FakeAdapter()
    svc = GroupAdminService(ad, _Cfg())
    assert (await svc.set_admin(100, 200, True))["ok"] is True
    assert (await svc.set_admin(100, 200, False))["ok"] is True
    assert ad.calls == [("set_group_admin", 100, 200, True), ("set_group_admin", 100, 200, False)]


@pytest.mark.asyncio
async def test_admin_execute_dispatch_all_ops():
    ad = _FakeAdapter()
    svc = GroupAdminService(ad, _Cfg())
    cases = [
        ("set_admin", {"group_id": 1, "user_id": 2}),
        ("unset_admin", {"group_id": 1, "user_id": 2}),
        ("ban", {"group_id": 1, "user_id": 2, "duration": 600}),
        ("unban", {"group_id": 1, "user_id": 2}),
        ("kick", {"group_id": 1, "user_id": 2}),
        ("set_card", {"group_id": 1, "user_id": 2, "card": "x"}),
        ("set_group_name", {"group_id": 1, "group_name": "y"}),
        ("set_title", {"group_id": 1, "user_id": 2, "title": "t"}),
        ("whole_ban", {"group_id": 1}),
        ("whole_unban", {"group_id": 1}),
        ("shut_list", {"group_id": 1}),
        ("leave", {"group_id": 1}),
    ]
    for op, kwargs in cases:
        result = await svc.execute(op, **kwargs)
        assert result["ok"] is True, (op, result)
    assert len(ad.calls) == len(cases)


@pytest.mark.asyncio
async def test_admin_execute_validation_errors():
    svc = GroupAdminService(_FakeAdapter(), _Cfg())
    assert (await svc.execute("nope", group_id=1))["ok"] is False
    assert (await svc.execute("set_admin", group_id="x", user_id=2))["ok"] is False
    assert (await svc.execute("set_admin", group_id=1, user_id=None))["ok"] is False
    assert (await svc.execute("set_group_name", group_id=1, group_name=""))["ok"] is False


@pytest.mark.asyncio
async def test_admin_error_is_captured_not_raised():
    svc = GroupAdminService(_FakeAdapter(fail={"set_group_admin": "boom"}), _Cfg())
    result = await svc.set_admin(1, 2, True)
    assert result["ok"] is False and "boom" in result["error"]


@pytest.mark.asyncio
async def test_admin_platform_failure_propagates():
    svc = GroupAdminService(_FakeAdapter(result={"set_group_admin": {"ok": False, "error": "no"}}), _Cfg())
    result = await svc.set_admin(1, 2, True)
    assert result["ok"] is False and result["error"] == "no"


def test_admin_operations_and_enabled():
    svc = GroupAdminService(_FakeAdapter(), _Cfg())
    assert svc.enabled() is True
    ops = svc.operations()
    assert {o["op"] for o in ops} >= {"set_admin", "ban", "kick", "shut_list", "leave"}
    assert all("label" in o and "desc" in o for o in ops)


# ---------- QzoneService ----------
def _qzone(tmp_path, adapter=None):
    return QzoneService(adapter or _FakeAdapter(), _Cfg(),
                        history_path=str(tmp_path / "qzone_history.json"))


def test_qzone_validate_rules(tmp_path):
    svc = _qzone(tmp_path)
    assert svc.validate("", [])[0] is False
    assert svc.validate("hi", [], 2)[0] is False
    assert svc.validate("hi", [], 16)[0] is False                       # 16 无对象
    assert svc.validate("hi", [], 16, [1])[0] is True
    assert svc.validate("hi", ["ftp://x"], 1)[0] is False               # 非法来源
    assert svc.validate("hi", ["file://%s" % "/tmp/a.jpg"], 1)[0] is True
    assert svc.validate("hi", ["https://e.com/a.png"], 1)[0] is True
    ok, err, imgs, targets = svc.validate("hi", [], 1, [3, 4])
    assert ok and targets == []                                          # 非 16/128 清空对象


@pytest.mark.asyncio
async def test_qzone_publish_and_history(tmp_path):
    ad = _FakeAdapter()
    svc = _qzone(tmp_path, ad)
    result = await svc.publish("今天天气不错", ["file:///tmp/a.jpg"], 4, [])
    assert result == {"ok": True, "tid": "T1"}
    assert ad.calls[0][0] == "qzone_publish"
    assert ad.calls[0][2] == ["file:///tmp/a.jpg"] and ad.calls[0][3] == 4
    hist = svc.history()
    assert len(hist) == 1 and hist[0]["tid"] == "T1" and hist[0]["images"] == 1
    saved = json.loads(open(svc._path, encoding="utf-8").read())
    assert saved[0]["tid"] == "T1"


@pytest.mark.asyncio
async def test_qzone_publish_failure_and_no_tid(tmp_path):
    svc = _qzone(tmp_path, _FakeAdapter(result={"qzone_publish": {"ok": False, "error": "denied"}}))
    assert (await svc.publish("x", [], 1))["ok"] is False
    svc2 = _qzone(tmp_path / "b", _FakeAdapter(result={"qzone_publish": {"ok": True}}))
    result = await svc2.publish("x", [], 1)
    assert result["ok"] is False and "tid" in result["error"]


@pytest.mark.asyncio
async def test_qzone_delete_removes_history(tmp_path):
    ad = _FakeAdapter()
    svc = _qzone(tmp_path, ad)
    await svc.publish("hello", [], 1)
    assert len(svc.history()) == 1
    assert (await svc.delete("T1"))["ok"] is True
    assert svc.history() == []
    assert ("qzone_delete", "T1") in ad.calls
    assert (await svc.delete(""))["ok"] is False


def test_qzone_history_cap(tmp_path):
    svc = _qzone(tmp_path)
    for i in range(8):
        svc._record("T%d" % i, "c%d" % i, 1, 0)
    assert len(svc.history()) == 5          # QZONE_MAX_HISTORY=5
    assert svc.history()[0]["tid"] == "T7"  # 最新在前


def test_qzone_default_right_and_rights(tmp_path):
    svc = _qzone(tmp_path)
    assert svc.default_ugc_right() == 1
    assert [r["value"] for r in svc.rights()] == list(UGC_RIGHTS.keys())


# ---------- Adapter 映射（OneBotAdapter -> Sender 端点） ----------
class _FakeSender:
    def __init__(self):
        self.calls = []

    async def set_group_admin(self, group_id, user_id, enable):
        self.calls.append(("set_group_admin", group_id, user_id, enable))
        return True

    async def set_group_kick(self, group_id, user_id, reject):
        self.calls.append(("kick", group_id, user_id, reject))
        return True

    async def get_group_shut_list(self, group_id):
        self.calls.append(("shut", group_id))
        return {"ok": True, "data": []}

    async def set_group_leave(self, group_id, dismiss):
        self.calls.append(("leave", group_id, dismiss))
        return {"ok": True}

    async def send_qzone_msg(self, content, images, ugc_right, target_uins):
        self.calls.append(("qzone", content, images, ugc_right, target_uins))
        return {"ok": True, "data": {"tid": "T9"}}

    async def delete_qzone_msg(self, tid):
        self.calls.append(("qzone_del", tid))
        return {"ok": True}


@pytest.mark.asyncio
async def test_onebot_adapter_maps_capabilities():
    sender = _FakeSender()
    adapter = OneBotAdapter(sender)
    assert (await adapter.set_group_admin(1, 2, True)) == {"ok": True}
    assert (await adapter.kick_with_reject(1, 2)) == {"ok": True}
    assert (await adapter.get_group_shut_list(1))["ok"] is True
    assert (await adapter.quit_group(1, True))["ok"] is True
    assert (await adapter.qzone_publish("hi", ["file:///a"], 1, []))["ok"] is True
    assert (await adapter.qzone_delete("T9"))["ok"] is True
    assert sender.calls[0] == ("set_group_admin", 1, 2, True)
    assert sender.calls[1] == ("kick", 1, 2, True)
    assert sender.calls[-2] == ("qzone", "hi", ["file:///a"], 1, [])
    assert sender.calls[-1] == ("qzone_del", "T9")


# ---------- 面板渲染（零 JS 契约） ----------
def test_admin_tab_renders_form_and_no_script():
    svc = GroupAdminService(_FakeAdapter(), _Cfg())
    html = render_admin_tab(True, svc.operations())
    assert 'action="/panel/admin/run"' in html
    assert 'name="group_id"' in html and 'name="op"' in html
    assert "<script" not in html.lower()


def test_admin_tab_disabled():
    html = render_admin_tab(False, [])
    assert "ADMIN_CONSOLE_ENABLED" in html


def test_qzone_tab_renders_form_and_no_script():
    svc = QzoneService(_FakeAdapter(), _Cfg(), history_path="/tmp/x_qzone.json")
    html = render_qzone_tab(True, svc.rights(), 1, svc.history())
    assert 'action="/panel/qzone/publish"' in html
    assert 'name="content"' in html and 'name="ugc_right"' in html
    assert "<script" not in html.lower()


def test_qzone_tab_history_delete_button():
    html = render_qzone_tab(True, [{"value": 1, "label": "所有人可见"}], 1,
                            [{"tid": "TX", "content": "hi", "ugc_right": 1, "images": 0, "ts": 0}])
    assert 'action="/panel/qzone/delete"' in html and 'value="TX"' in html


def test_qzone_tab_disabled():
    assert "QZONE_ENABLED" in render_qzone_tab(False)
