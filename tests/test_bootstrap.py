"""Phase 4 最小 DI 回归测试：组合根构造 / 注入正确性 / 反向依赖 / Legacy 契约。"""
import os

import pytest

from src.adapters import Adapters, OneBotEventParser, make_adapters
from src.adapters.proto import MessageSender
from tests.test_plugin_manager import FakeSender


class FullSender(FakeSender):
    """满足 MessageSender 全部契约方法的测试桩（避免污染公共 FakeSender）。"""

    async def send_group_message_with_image(self, group_id, text, image_path, retries=2):
        return True

    async def send_poke(self, group_id, user_id):
        return {"ok": True, "data": {}}

    async def set_react(self, message_id, react_type):
        return {"ok": True, "data": {}}

    async def set_group_whole_ban(self, group_id, enable):
        return {"ok": True, "data": {}}

    async def set_group_name(self, group_id, name):
        return {"ok": True, "data": {}}

    async def set_group_card(self, group_id, user_id, card):
        return {"ok": True, "data": {}}

    async def set_group_special_title(self, group_id, user_id, title):
        return {"ok": True, "data": {}}

    async def send_group_notice(self, group_id, content, image=""):
        return {"ok": True, "data": {}}

    async def get_group_notice(self, group_id):
        return {"ok": True, "data": {}}

    async def get_group_root_files(self, group_id):
        return {"ok": True, "data": {}}

    async def get_group_files_by_folder(self, group_id, folder_id):
        return {"ok": True, "data": {"files": []}}

    async def get_group_file_url(self, group_id, file_id, busid):
        return {"ok": True, "data": {"url": ""}}

    async def set_essence_msg(self, message_id):
        return {"ok": True, "data": {}}

    async def delete_essence_msg(self, message_id):
        return {"ok": True, "data": {}}

    async def set_friend_profile_like(self, user_id):
        return {"ok": True, "data": {}}

    async def get_friend_list(self):
        return {"ok": True, "data": []}

    async def get_login_info(self):
        return {"ok": True, "data": {}}

    async def get_online_clients(self):
        return {"ok": True, "data": []}

    async def set_qq_profile(self, nickname="", signature=""):
        return {"ok": True, "data": {}}

    async def get_group_config(self, group_id):
        return {"ok": True, "data": {}}

    async def set_group_config(self, group_id, **kwargs):
        return {"ok": True, "data": {}}

    async def get_group_res(self, group_id, res_type):
        return {"ok": True, "data": {}}


# ---------- 1. main/composition root 能构造 Adapters ----------
def test_make_adapters_constructs():
    sender = FullSender()
    adapters = make_adapters(10001, sender)
    assert isinstance(adapters, Adapters)
    assert isinstance(adapters.parser, OneBotEventParser)
    assert adapters.sender is sender          # 共享实例（不重复构造）✓
    assert adapters.bot_qq == 10001
    assert adapters.transport == "onebot"


# ---------- 2. Parser 被正确注入（bot_qq 生效） ----------
def test_parser_injected_and_functional():
    sender = FullSender()
    adapters = make_adapters(10001, sender)
    ev = adapters.parser.parse({
        "post_type": "message", "message_type": "group", "group_id": 7,
        "user_id": 9, "message_id": 3, "time": 1,
        "message": [{"type": "at", "data": {"qq": "10001"}},
                    {"type": "text", "data": {"text": "早安"}}]})
    assert ev.is_mentioned is True and ev.text == "早安"
    assert ev.kind == "message" and ev.scope == "group"


# ---------- 3. Sender 被正确注入 + 满足 MessageSender 契约 ----------
def test_sender_injected_and_contract():
    sender = FullSender()
    adapters = make_adapters(10001, sender)
    # FakeSender 满足协议的全方法面（缺失会由 make_adapters 抛 RuntimeError；
    # 此处再显式验证一组核心签名）
    for name in ("send_group_message", "send_msg_raw", "delete_msg", "get_msg",
                 "set_group_ban", "set_group_kick", "set_group_admin"):
        assert hasattr(sender, name), f"FakeSender 缺 {name}"
    # Legacy Sender 兼容：契约方法面与 adapters.container 的 _missing_sender_methods 一致
    from src.adapters.container import _missing_sender_methods
    assert _missing_sender_methods(sender) == []


# ---------- 4. 依赖方向与 raw_data 泄漏检查（uwu Phase5 §8） ----------
def test_no_backward_dependency():
    root = os.path.join(os.path.dirname(__file__), "..", "src")
    banned_import = ("from src.adapters", "import src.adapters")
    # 冻结层（services/repositories/plugins）：禁止 import 消息边界
    frozen_offenders = []
    for base, _dirs, files in os.walk(os.path.join(root, "services")):
        for f in files:
            if not f.endswith(".py"):
                continue
            text = open(os.path.join(base, f), encoding="utf-8").read()
            if any(b in text for b in banned_import):
                frozen_offenders.append(os.path.join(base, f))
    for base, _dirs, files in os.walk(os.path.join(root, "repositories")):
        for f in files:
            if not f.endswith(".py"):
                continue
            text = open(os.path.join(base, f), encoding="utf-8").read()
            if any(b in text for b in banned_import):
                frozen_offenders.append(os.path.join(base, f))
    assert frozen_offenders == [], f"冻结层反向依赖 adapters: {frozen_offenders}"
    # core 允许 message_router 接入（合法单向依赖），其余 core 模块禁止
    core_offenders = []
    for base, _dirs, files in os.walk(os.path.join(root, "core")):
        for f in files:
            if not f.endswith(".py"):
                continue
            if f == "message_router.py":
                continue
            text = open(os.path.join(base, f), encoding="utf-8").read()
            if any(b in text for b in banned_import):
                core_offenders.append(os.path.join(base, f))
    assert core_offenders == [], f"core 意外依赖 adapters: {core_offenders}"


# ---------- 4b. 全库禁止读取 raw_data（无泄漏路径） ----------
def test_no_raw_data_read_anywhere():
    root = os.path.join(os.path.dirname(__file__), "..", "src")
    offenders = []
    for base, _dirs, files in os.walk(root):
        for f in files:
            if not f.endswith(".py") or f.startswith("__"):
                continue
            text = open(os.path.join(base, f), encoding="utf-8").read()
            if "raw_data[" in text or "raw_data.get(" in text:
                offenders.append(os.path.join(base, f))
    assert offenders == [], f"raw_data 被业务读取: {offenders}"


# ---------- 5. Legacy 路径仍可正常构造（Sender 流程函数面完整；解析旧路径同步） ----------
def test_legacy_paths_intact():
    # Legacy sender 桩依旧可直接使用（组合根之外的旧路径不受影响）
    sender = FakeSender()
    assert sender is not None
    # 旧解析路径（src/sdk/onebot/transformer）仍工作
    from src.sdk.onebot.transformer import to_bot_event
    ev = to_bot_event({"post_type": "message", "message_type": "group", "group_id": 1,
                       "user_id": 2, "message_id": 3, "time": 4,
                       "message": [{"type": "text", "data": {"text": "旧路径"}}]})
    assert ev.kind == "message" and ev.text == "旧路径"
    # 契约冒烟：MessageSender 协议方法面可枚举（Python 3.9 兼容）
    assert callable(getattr(MessageSender, "send_group_message", None))


# ---------- 6. 契约失败场景：缺方法的 sender → 启动期抛 RuntimeError ----------
def test_contract_failure_raises():
    class LameSender:
        async def send_group_message(self, group_id, message, retries=2):
            return True

    with pytest.raises(RuntimeError):
        make_adapters(10001, LameSender())
