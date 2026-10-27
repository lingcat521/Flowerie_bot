"""v2.11.0 群内管理指令：Bot 权限自检 + /mute /unmute /admin（不经过 LLM）。

覆盖：
- 时长解析（s/m/h/d、上限 30 天、非法值）
- /admin 权限自检文案（有/没有管理员）
- /mute 的权限链：调用者权限 → Bot 权限 → 参数 → 平台结果
- ADMIN_COMMANDS_ENABLED 关闭时不响应
- GroupAdminService 角色查询缓存与白名单
"""
import pytest

from src.core.command_handler import CommandHandler
from src.services.group_admin import GroupAdminService


class _Cfg:
    BOT_QQ = 10000
    BOT_NICKNAME = "花璃"
    ADMIN_QQ_IDS = [999]
    ADMIN_COMMANDS_ENABLED = True
    ADMIN_ROLE_CACHE_SECONDS = 60


class _Sender:
    def __init__(self):
        self.messages = []

    async def send_group_message(self, group_id, text):
        self.messages.append((int(group_id), str(text)))
        return True


class _Memory:
    def get_user_notes(self, *a, **k):
        return []


class _Admin:
    """假群管理服务：记录调用、可编程角色与结果。"""

    def __init__(self, bot="admin", caller=True, result=None):
        self.bot = bot
        self.caller = caller
        self.result = result or {"ok": True}
        self.bans = []
        self.roles = {}

    async def bot_role(self, group_id, fresh=False):
        return self.bot

    async def member_role(self, group_id, user_id, fresh=False):
        return self.roles.get(int(user_id), "member")

    async def caller_can_manage(self, group_id, user_id):
        return bool(self.caller)

    async def ban(self, group_id, user_id, duration=0):
        self.bans.append((int(group_id), int(user_id), int(duration)))
        return self.result


def _handler(admin=None, cfg=None):
    cfg = cfg or _Cfg()
    sender = _Sender()
    handler = CommandHandler(cfg, sender, _Memory(), admin_service=admin)
    return handler, sender


# ---------- 时长解析 ----------
def test_parse_duration_units():
    assert CommandHandler.parse_duration("10m") == 600
    assert CommandHandler.parse_duration("1h") == 3600
    assert CommandHandler.parse_duration("90s") == 90
    assert CommandHandler.parse_duration("2d") == 172800
    assert CommandHandler.parse_duration("600") == 600
    assert CommandHandler.parse_duration("") == 600          # 默认 10 分钟
    assert CommandHandler.parse_duration("x") is None
    assert CommandHandler.parse_duration("-5") is None
    assert CommandHandler.parse_duration("999d") == 30 * 24 * 3600  # 上限 30 天


# ---------- /admin 权限自检 ----------
@pytest.mark.asyncio
async def test_admin_status_with_rights():
    service = _Admin(bot="admin")
    service.roles[7] = "owner"
    handler, sender = _handler(service)
    assert await handler.handle("/admin", 7, 200) is True
    text = sender.messages[-1][1]
    assert "管理员" in text and "可以禁言" in text
    assert "群主" in text


@pytest.mark.asyncio
async def test_admin_status_without_rights():
    service = _Admin(bot="member")
    handler, sender = _handler(service)
    await handler.handle("/admin", 7, 200)
    text = sender.messages[-1][1]
    assert "普通成员" in text and "没有管理权限" in text
    assert "请群主" in text or "让群主" in text


# ---------- /mute 全链路 ----------
@pytest.mark.asyncio
async def test_mute_success_calls_ban_with_duration():
    service = _Admin(bot="admin", caller=True)
    handler, sender = _handler(service)
    await handler.handle("/mute 123456 10m", 7, 200)
    assert service.bans == [(200, 123456, 600)]
    assert "已禁言 123456" in sender.messages[-1][1]


@pytest.mark.asyncio
async def test_mute_requires_caller_admin():
    service = _Admin(bot="admin", caller=False)
    handler, sender = _handler(service)
    await handler.handle("/mute 123456", 7, 200)
    assert service.bans == []
    assert "只有群主/管理员" in sender.messages[-1][1]


@pytest.mark.asyncio
async def test_mute_requires_bot_admin():
    service = _Admin(bot="member", caller=True)
    handler, sender = _handler(service)
    await handler.handle("/mute 123456", 7, 200)
    assert service.bans == []
    assert "没有管理权限" in sender.messages[-1][1]


@pytest.mark.asyncio
async def test_unmute_sends_zero_duration():
    service = _Admin(bot="admin", caller=True)
    handler, sender = _handler(service)
    await handler.handle("/unmute 123456", 7, 200)
    assert service.bans == [(200, 123456, 0)]
    assert "已解除" in sender.messages[-1][1]


@pytest.mark.asyncio
async def test_mute_invalid_duration_and_args():
    service = _Admin(bot="admin", caller=True)
    handler, sender = _handler(service)
    await handler.handle("/mute 123456 10x", 7, 200)
    assert "时长写法" in sender.messages[-1][1]
    await handler.handle("/mute abc", 7, 200)
    assert "用法" in sender.messages[-1][1]
    await handler.handle("/mute", 7, 200)
    assert "用法" in sender.messages[-1][1]
    assert service.bans == []


@pytest.mark.asyncio
async def test_mute_refuses_self():
    service = _Admin(bot="admin", caller=True)
    handler, sender = _handler(service)
    await handler.handle("/mute 10000", 7, 200)   # 10000 = BOT_QQ
    assert service.bans == []
    assert "不能禁言" in sender.messages[-1][1]


@pytest.mark.asyncio
async def test_mute_platform_failure_reported():
    service = _Admin(bot="admin", caller=True,
                     result={"ok": False, "error": "cannot ban admin"})
    handler, sender = _handler(service)
    await handler.handle("/mute 123456", 7, 200)
    assert "操作失败" in sender.messages[-1][1]
    assert "cannot ban admin" in sender.messages[-1][1]


@pytest.mark.asyncio
async def test_commands_disabled():
    cfg = _Cfg()
    cfg.ADMIN_COMMANDS_ENABLED = False
    service = _Admin(bot="admin", caller=True)
    handler, sender = _handler(service, cfg)
    assert await handler.handle("/mute 123456", 7, 200) is True
    assert service.bans == []
    assert "没有开启" in sender.messages[-1][1]


@pytest.mark.asyncio
async def test_other_commands_unaffected():
    handler, sender = _handler(_Admin())
    assert await handler.handle("/not_a_command", 7, 200) is False


# ---------- GroupAdminService 角色自检 ----------
class _RoleAdapter:
    def __init__(self, roles):
        self.roles = roles
        self.queries = []

    async def get_group_member(self, group_id, user_id):
        self.queries.append((group_id, user_id))
        role = self.roles.get((group_id, user_id))
        if role is None:
            raise RuntimeError("not found")
        return {"ok": True, "role": role}


@pytest.mark.asyncio
async def test_service_bot_role_and_cache():
    adapter = _RoleAdapter({(200, 10000): "admin"})
    service = GroupAdminService(adapter, _Cfg())
    assert await service.bot_role(200) == "admin"
    assert await service.can_manage(200) is True
    assert await service.bot_role(200) == "admin"          # 命中缓存
    assert len(adapter.queries) == 1
    assert await service.bot_role(200, fresh=True) == "admin"
    assert len(adapter.queries) == 2


@pytest.mark.asyncio
async def test_service_role_query_failure_is_unknown():
    service = GroupAdminService(_RoleAdapter({}), _Cfg())
    assert await service.bot_role(200) == ""
    assert await service.can_manage(200) is False


@pytest.mark.asyncio
async def test_service_caller_whitelist_and_group_role():
    adapter = _RoleAdapter({(200, 999): "member", (200, 5): "owner"})
    service = GroupAdminService(adapter, _Cfg())
    assert await service.caller_can_manage(200, 999) is True    # ADMIN_QQ_IDS 白名单
    assert await service.caller_can_manage(200, 5) is True      # 群主
    assert await service.caller_can_manage(200, 6) is False     # 普通成员
