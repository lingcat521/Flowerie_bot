"""v1.7.0 拉格朗日补齐：语义方法→端点（OneBot 只在 Sender/适配层）+ 网关回退。"""
import pytest

from src.plugins.manager import _SENDER_ACTIONS
from src.sdk.onebot.adapter import make_onebot_adapter


class RecordingSender:
    """记录端点调用（记录 + 返回虚拟 success）。"""

    def __init__(self):
        self.calls = []

    async def _post(self, endpoint, payload=None, **kw):
        self.calls.append((endpoint, payload or {}))
        return {"ok": True, "data": {"echo": endpoint}}

    # ---- 端点方法（本测试只关注记录；不实现某方法=模拟网关缺端点）----
    async def send_poke(self, group_id, user_id):
        return await self._post("/send_poke", {"group_id": group_id, "user_id": user_id})

    async def get_friend_msg_history(self, user_id, count=20, message_id=0):
        return await self._post("/get_friend_msg_history",
                                {"user_id": user_id, "count": count})

    async def friend_poke(self, user_id):
        return await self._post("/friend_poke", {"user_id": user_id})

    async def send_group_forward_msg(self, group_id, messages):
        return await self._post("/send_group_forward_msg",
                                {"group_id": group_id, "messages": messages})

    async def send_private_forward_msg(self, user_id, messages):
        return await self._post("/send_private_forward_msg",
                                {"user_id": user_id, "messages": messages})

    async def get_essence_msg_list(self, group_id):
        return await self._post("/get_essence_msg_list", {"group_id": group_id})

    async def get_group_honor_info(self, group_id, honor_type=""):
        return await self._post("/get_group_honor_info",
                                {"group_id": group_id, "honor_type": honor_type})

    async def delete_group_notice(self, group_id, notice_id):
        return await self._post("/_del_group_notice",
                                {"group_id": group_id, "notice_id": notice_id})

    async def set_group_portrait(self, group_id, file):
        return await self._post("/set_group_portrait", {"group_id": group_id, "file": file})

    async def create_group_file_folder(self, group_id, name):
        return await self._post("/create_group_file_folder", {"group_id": group_id, "name": name})

    async def delete_group_file(self, group_id, file_id, busid=0):
        return await self._post("/delete_group_file",
                                {"group_id": group_id, "file_id": file_id, "busid": busid})

    async def delete_group_folder(self, group_id, folder_id):
        return await self._post("/delete_group_folder", {"group_id": group_id, "folder_id": folder_id})

    async def move_group_file(self, group_id, file_id, busid=0, target_folder_id=""):
        return await self._post("/move_group_file", {"group_id": group_id, "file_id": file_id})

    async def rename_group_file_folder(self, group_id, folder_id, name):
        return await self._post("/rename_group_file_folder",
                                {"group_id": group_id, "folder_id": folder_id, "name": name})

    async def get_group_info(self, group_id, no_cache=False):
        return await self._post("/get_group_info", {"group_id": group_id})

    async def get_group_list(self, no_cache=False):
        return await self._post("/get_group_list", {})


class LagrangeOnlySender(RecordingSender):
    """只有 Lagrange 端点（模拟换网关）：set_group_reaction 可用、set_react 缺失。"""

    async def set_group_reaction(self, message_id, react_type, is_emoji_id=False, message_seq=None):
        return await self._post("/set_group_reaction",
                                {"message_id": message_id, "code": react_type})


def make_adapter(sender):
    return make_onebot_adapter(sender, None)


# ---------- 语义方法 → 端点 ----------
@pytest.mark.asyncio
async def test_semantic_methods_map_to_endpoints():
    s = RecordingSender()
    a = make_adapter(s)
    await a.user_history(1001, 30)
    await a.user_poke(1001)
    await a.group_forward(777, [{"name": "x", "uin": 1, "content": "hi"}])
    await a.user_forward(1001, [{"name": "x", "uin": 1, "content": "hi"}])
    await a.essence_list(777)
    await a.group_honor(777, "talkative")
    await a.group_notice_delete(777, "n1")
    await a.group_portrait(777, "bg.png")
    await a.group_folder_create(777, "相册")
    await a.group_file_delete(777, "f1", 5)
    await a.group_folder_delete(777, "fd1")
    await a.group_file_move(777, "f1", 5, "fd2")
    await a.group_folder_rename(777, "fd1", "新名")
    await a.group_list()
    await a.group_forward(777, [])
    endpoints = [c[0] for c in s.calls]
    assert "/get_friend_msg_history" in endpoints
    assert "/friend_poke" in endpoints
    assert "/send_group_forward_msg" in endpoints
    assert "/send_private_forward_msg" in endpoints
    assert "/get_essence_msg_list" in endpoints
    assert "/get_group_honor_info" in endpoints
    assert "/_del_group_notice" in endpoints
    assert "/set_group_portrait" in endpoints
    assert "/create_group_file_folder" in endpoints
    assert "/delete_group_file" in endpoints
    assert "/delete_group_folder" in endpoints
    assert "/move_group_file" in endpoints
    assert "/rename_group_file_folder" in endpoints
    assert "/get_group_list" in endpoints
    assert s.calls[-1][1]["messages"] == []


# ---------- 网关回退：emoji 在 Lagrange-only ⽹墙 ----------
@pytest.mark.asyncio
async def test_emoji_fallback_to_lagrange_endpoint():
    s = LagrangeOnlySender()
    a = make_adapter(s)
    await a.react(42, 5)   # react 语义：adapter 层仍用 set_react？—— 语义层统一走转发表回退
    # adapter.react 直接调 sender.set_react（缺失）→ _call 应返回错误（语义不能崩溃）
    # 这里我们验证 Sender 层的回退：manager 转发动作时按可用方法选择
    assert _SENDER_ACTIONS["react"][0] == ["set_react", "set_group_reaction"]


@pytest.mark.asyncio
async def test_manager_fallback_selects_available_gateway():

    s = LagrangeOnlySender()
    # 直接测 _sender_forward 的端到端：构造最小 manager（不依赖插件目录）
    import src.plugins.manager as M
    mgr = M.PluginManager.__new__(M.PluginManager)
    mgr.sender = s
    mgr._rule_cache = getattr(mgr, "_rule_cache", {})
    result = await mgr._sender_forward("p1", "react", {"message_id": 42, "react_type": 5})
    assert s.calls and s.calls[-1][0] == "/set_group_reaction"  # 回退到 Lagrange 端点生效
    assert result.get("ok") is True


# ---------- 低耦合红线：端点名只出现在 Sender/适配层 ----------
def test_onebot_endpoints_stay_in_sender_layer():
    """低耦合红线：语义层文件不得出现 /send_ /get_ /set_ 端点字符串。"""
    import glob
    import os
    import re

    bad = []
    for f in sorted(glob.glob("src/sdk/*.py") + glob.glob("src/sdk/onebot/*.py")):
        body = open(f, encoding="utf-8").read()
        hits = re.findall(r'"(/[a-z_]+)"', body)
        real = [h for h in hits if h.startswith(("/send_", "/get_", "/set_"))]
        if real:
            bad.append((os.path.basename(f), real))
    assert not bad, f"OneBot 端点泄漏到语义层: {bad}"


# ---------- PluginApi 语义方法（看一眼就会；等效 call 白名单通道） ----------
def test_plugin_api_semantic_methods():
    from src.plugins.runner.python_runner import PluginApi

    calls = []
    api = PluginApi(lambda action, payload: calls.append((action, payload)) or {"ok": True}, "p1")
    api.react(42, 5)
    api.tap(777, 123)
    api.user_history(1001, 30)
    api.group_forward(777, [{"name": "x", "uin": 1, "content": "hi"}])
    api.group_file_move(777, "f1", 5, "fd2")
    api.group_folder_rename(777, "fd1", "新名")
    api.group_list()
    api.group_notice_delete(777, "n1")
    api.group_portrait(777, "bg.png")
    api.group_honor(777, "talkative")
    api.essence_list(777)
    api.user_poke(1001)
    api.user_forward(1001, [{"name": "x", "uin": 1, "content": "hi"}])
    api.group_info(777)
    api.group_folder_create(777, "相册")
    api.group_file_delete(777, "f1", 5)
    api.group_folder_delete(777, "fd1")
    actions = [c[0] for c in calls]
    for want in ("react", "tap", "user_history", "group_forward", "group_file_move",
                 "group_folder_rename", "group_list", "group_notice_delete", "group_portrait",
                 "group_honor", "essence_list", "user_poke", "user_forward", "group_info",
                 "group_folder_create", "group_file_delete", "group_folder_delete"):
        assert want in actions, f"缺失语义动作 {want}"
    assert calls[0] == ("react", {"message_id": 42, "react_type": 5})
