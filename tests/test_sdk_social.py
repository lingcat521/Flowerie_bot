"""v1.5 社交/群管语义 API 测试：动作转发表、参数清洗、SDK 分组上下文、富内容 Builder。"""
import os
import sys
from pathlib import Path

import pytest

from src.plugins.manager import PluginManager
from src.repositories.settings_repository import SettingsRepository
from tests.test_plugin_manager import FakeConfig, FakeSender, _deploy  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin_sdk"))

from flowerie_sdk import BotMessage  # noqa: E402


class Recorder(FakeSender):
    """记录端点调用（sender 方法名 + 参数）。"""

    def __init__(self):
        super().__init__()
        self.calls = []

    async def send_poke(self, group_id, user_id):
        self.calls.append(("send_poke", {"group_id": group_id, "user_id": user_id}))
        return {"ok": True, "data": {}}

    async def set_react(self, message_id, react_type):
        self.calls.append(("set_react", {"message_id": message_id, "react_type": react_type}))
        return {"ok": True, "data": {}}

    async def set_essence_msg(self, message_id):
        self.calls.append(("set_essence_msg", {"message_id": message_id}))
        return {"ok": True, "data": {}}

    async def delete_essence_msg(self, message_id):
        self.calls.append(("delete_essence_msg", {"message_id": message_id}))
        return {"ok": True, "data": {}}

    async def set_friend_profile_like(self, user_id):
        self.calls.append(("set_friend_profile_like", {"user_id": user_id}))
        return {"ok": True, "data": {}}

    async def get_friend_list(self):
        self.calls.append(("get_friend_list", {}))
        return {"ok": True, "data": [{"user_id": 1}]}

    async def get_login_info(self):
        self.calls.append(("get_login_info", {}))
        return {"ok": True, "data": {"user_id": 10001, "nickname": "小璃"}}

    async def get_online_clients(self):
        self.calls.append(("get_online_clients", {}))
        return {"ok": True, "data": [{"device": "Android"}]}

    async def set_qq_profile(self, nickname="", signature=""):
        self.calls.append(("set_qq_profile", {"nickname": nickname, "signature": signature}))
        return {"ok": True, "data": {}}

    async def set_group_whole_ban(self, group_id, enable):
        self.calls.append(("set_group_whole_ban", {"group_id": group_id, "enable": enable}))
        return {"ok": True, "data": {}}

    async def set_group_name(self, group_id, name):
        self.calls.append(("set_group_name", {"group_id": group_id, "name": name}))
        return {"ok": True, "data": {}}

    async def set_group_card(self, group_id, user_id, card):
        self.calls.append(("set_group_card", {"group_id": group_id, "user_id": user_id, "card": card}))
        return {"ok": True, "data": {}}

    async def set_group_special_title(self, group_id, user_id, title):
        self.calls.append(("set_group_special_title",
                           {"group_id": group_id, "user_id": user_id, "title": title}))
        return {"ok": True, "data": {}}

    async def send_group_notice(self, group_id, content, image=""):
        self.calls.append(("send_group_notice", {"group_id": group_id, "content": content, "image": image}))
        return {"ok": True, "data": {}}

    async def get_group_notice(self, group_id):
        self.calls.append(("get_group_notice", {"group_id": group_id}))
        return {"ok": True, "data": {"content": "早上好"}}

    async def get_group_root_files(self, group_id):
        self.calls.append(("get_group_root_files", {"group_id": group_id}))
        return {"ok": True, "data": {"files": [{"file_id": "f1", "file_name": "a.txt"}]}}

    async def get_group_files_by_folder(self, group_id, folder_id):
        self.calls.append(("get_group_files_by_folder", {"group_id": group_id, "folder_id": folder_id}))
        return {"ok": True, "data": {"files": []}}

    async def get_group_file_url(self, group_id, file_id, busid):
        self.calls.append(("get_group_file_url",
                           {"group_id": group_id, "file_id": file_id, "busid": busid}))
        return {"ok": True, "data": {"url": "http://x/f"}}

    async def set_friend_add_request(self, flag, approve, remark=""):
        return True

    async def set_group_add_request(self, flag, approve, reason=""):
        return True


async def _mgr(tmp, approved=None):
    sender = Recorder()
    repo = SettingsRepository(os.path.join(str(tmp), "settings.db"))
    plugin_dir = os.path.join(str(tmp), "plugins")
    os.makedirs(plugin_dir, exist_ok=True)
    cfg = FakeConfig()
    cfg.PLUGIN_DIR = plugin_dir
    mgr = PluginManager(cfg, repo, sender=sender)
    _deploy(tmp, "sdk_plugin")
    mgr.discover()
    ok, msg = await mgr.enable("sdk_plugin",
                               approved_permissions=approved or
                               ["read_group_info", "group_manage", "read_user_info",
                                "read_message", "bot_profile", "read_message_history",
                                "scheduler"])
    assert ok, msg
    return mgr, sender


# ---------- 动作转发表：参数白名单 + 端点名（语义动作 → Sender 方法） ----------
@pytest.mark.asyncio
async def test_sender_actions_table(tmp_path):
    mgr, sender = await _mgr(tmp_path)
    cases = [
        ("tap", {"group_id": "7", "user_id": "9"}, ("send_poke", {"group_id": 7, "user_id": 9})),
        ("react", {"message_id": "11", "react_type": 2}, ("set_react", {"message_id": 11, "react_type": 2})),
        ("pin", {"message_id": 11}, ("set_essence_msg", {"message_id": 11})),
        ("unpin", {"message_id": 11}, ("delete_essence_msg", {"message_id": 11})),
        ("like", {"user_id": 5}, ("set_friend_profile_like", {"user_id": 5})),
        ("friends", {}, ("get_friend_list", {})),
        ("login_info", {}, ("get_login_info", {})),
        ("devices", {}, ("get_online_clients", {})),
        ("profile_set", {"nickname": "小", "signature": "hi"},
         ("set_qq_profile", {"nickname": "小", "signature": "hi"})),
        ("group_whole_ban", {"group_id": 1, "enable": True},
         ("set_group_whole_ban", {"group_id": 1, "enable": True})),
        ("group_rename", {"group_id": 1, "name": "新名"}, ("set_group_name", {"group_id": 1, "name": "新名"})),
        ("group_card", {"group_id": 1, "user_id": 2, "card": "名片"},
         ("set_group_card", {"group_id": 1, "user_id": 2, "card": "名片"})),
        ("group_title", {"group_id": 1, "user_id": 2, "title": "头衔"},
         ("set_group_special_title", {"group_id": 1, "user_id": 2, "title": "头衔"})),
        ("group_notice_send", {"group_id": 1, "content": "公告", "image": ""},
         ("send_group_notice", {"group_id": 1, "content": "公告", "image": ""})),
        ("group_notice_get", {"group_id": 1}, ("get_group_notice", {"group_id": 1})),
        ("group_files", {"group_id": 1}, ("get_group_root_files", {"group_id": 1})),
        ("group_files_in", {"group_id": 1, "folder_id": "fd"}, ("get_group_files_by_folder",
                                                                {"group_id": 1, "folder_id": "fd"})),
        ("group_file_url", {"group_id": 1, "file_id": "f1", "busid": 0},
         ("get_group_file_url", {"group_id": 1, "file_id": "f1", "busid": 0})),
    ]
    for action, payload, expected in cases:
        r = await mgr._handle_action("sdk_plugin", action, payload)
        assert r.get("ok"), (action, r)
        assert sender.calls[-1] == expected, action
    await mgr.shutdown()


@pytest.mark.asyncio
async def test_unsupported_sender_action_semantics(tmp_path):
    """sender 缺失该方法 → 明确错误（换网关即激活）。"""
    mgr, sender = await _mgr(tmp_path)
    base = type(sender).__mro__[1]  # Sender 基类（不经 pydantic 配置导入）
    original = getattr(base, "get_group_config", None)
    if original is not None:
        delattr(base, "get_group_config")
    try:
        r = await mgr._handle_action("sdk_plugin", "group_config", {"group_id": 1})
        assert r["ok"] is False
        assert "当前网关不支持" in str(r.get("error"))
    finally:
        if original is not None:
            setattr(base, "get_group_config", original)
    await mgr.shutdown()


# ---------- 权限拒绝 ----------
@pytest.mark.asyncio
async def test_social_permission_denied(tmp_path):
    mgr, _ = await _mgr(tmp_path, approved=["read_message", "scheduler"])
    r = await mgr._handle_action("sdk_plugin", "group_whole_ban", {"group_id": 1, "enable": True})
    assert r.get("ok") in (False, None) and r.get("denied") in (True, False) or "权限" in str(r)
    r2 = await mgr._handle_action("sdk_plugin", "profile_set", {"nickname": "x"})
    assert "权限" in str(r2) or r2.get("ok") is not True
    await mgr.shutdown()


# ---------- 富内容 Builder（card/markdown/button 出段） ----------
def test_rich_builder_segments():
    m = BotMessage("菜单").markdown("**加粗**").button("开始", "/start")
    m2 = (BotMessage("").button("帮助", "/help").card({"app": "x"}))
    types = [s["type"] for s in m.segments + m2.segments]
    assert "markdown" in types and "keyboard" in types and "json" in types
    kb = [s for s in m.segments if s["type"] == "keyboard"][0]
    assert kb["data"]["buttons"][0]["text"] == "开始"
    # 两次 button 合并到同一 keyboard
    m3 = BotMessage().button("A", "/a").button("B", "/b")
    kbs = [s for s in m3.segments if s["type"] == "keyboard"]
    assert len(kbs) == 1 and len(kbs[0]["data"]["buttons"]) == 2
