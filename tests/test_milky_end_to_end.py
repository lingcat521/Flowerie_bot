"""Milky 全链路：用本地假协议端验证 SDK -> Core -> Milky 的真实请求（任务书 §8-§12）。

不依赖真机：起一个本地 HTTP 服务模拟 Milky 协议端，记录它收到的 /api/<action> 请求，
于是"动作名映射对不对、Bearer 有没有带、消息有没有转成段数组、能力缺失是否明确报错"
都能被断言到。
"""
import pytest
from aiohttp import web

from src.core.reply_dispatch import ReplyDispatchMixin
from src.core.reply_plan import INTERVAL_NONE
from src.services.sender import Sender


class FakeMilky:
    """假 Milky 协议端：记录请求，返回 Milky 风格响应。"""

    def __init__(self):
        self.calls = []          # [(action, headers, body)]
        self.app = web.Application()
        self.app.router.add_post("/api/{action}", self._handle)   # Milky 模式
        self.app.router.add_post("/{action}", self._handle)       # OneBot 模式（无 /api 前缀）
        self._runner = None
        self.port = None

    async def _handle(self, request):
        action = request.match_info["action"]
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        self.calls.append((action, dict(request.headers), body))
        return web.json_response({"retcode": 0, "data": {"message_id": 1000 + len(self.calls)}})

    async def __aenter__(self):
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        await self._runner.cleanup()


class Cfg:
    """Sender 需要的最小配置。"""

    SEND_VIA_WS = False
    MILKY_ACCESS_TOKEN = "test-token"
    MAX_REPLY_LENGTH = 200        # Sender 硬读的属性（send_group_message 会截断超长文本）

    def __init__(self, protocol, base):
        self.QQ_PROTOCOL = protocol
        self.MILKY_API_BASE = base
        self.HTTP_API_BASE = base


@pytest.mark.asyncio
async def test_send_group_message_hits_milky_action_with_bearer():
    async with FakeMilky() as milky:
        async with Sender(Cfg("milky", "http://127.0.0.1:%d" % milky.port)) as sender:
            ok = await sender.send_group_message(12345, "你好呀")
        assert ok is True
        action, headers, body = milky.calls[0]
        assert action == "send_group_message"                 # 映射到 Milky 官方动作名
        assert headers.get("Authorization") == "Bearer test-token"
        assert body["group_id"] == 12345
        # Milky 要求消息是段数组
        assert body["message"] == [{"type": "text", "data": {"text": "你好呀"}}]


@pytest.mark.asyncio
async def test_mapped_group_actions_use_milky_names():
    async with FakeMilky() as milky:
        base = "http://127.0.0.1:%d" % milky.port
        async with Sender(Cfg("milky", base)) as sender:
            await sender.set_group_card(1, 2, "名片")
            await sender.set_group_ban(1, 2, 60)
            await sender.set_group_kick(1, 2)
            await sender.set_group_admin(1, 2, True)
        names = [c[0] for c in milky.calls]
        assert names == ["set_group_member_card", "set_group_member_mute",
                         "kick_group_member", "set_group_member_admin"], names


@pytest.mark.asyncio
async def test_unsupported_capability_reports_clearly_and_skips_http():
    async with FakeMilky() as milky:
        base = "http://127.0.0.1:%d" % milky.port
        async with Sender(Cfg("milky", base)) as sender:
            res = await sender.get_group_honor_info(1)
        assert res.get("ok") is False
        assert "Milky 协议不支持该能力" in str(res.get("error"))
        assert milky.calls == []          # 明确拒绝，不把请求丢给协议端


class _Policy:
    def __init__(self):
        self.count = 0
        self.context = []

    def record_bot_reply(self, target):
        self.count += 1

    def add_context(self, group_id, user_id, text, is_bot=False):
        self.context.append(text)

    def add_recent_reply(self, group_id, text):
        pass


class _Host(ReplyDispatchMixin):
    """模拟 MessageRouter：多条发送走 Core 的 ReplyPlan + 真实 Sender。"""

    def __init__(self, sender):
        self.sender = sender
        self.policy_engine = _Policy()
        self.config = type("C", (), {
            "MULTI_REPLY_ENABLED": True,
            "MULTI_REPLY_MAX_MESSAGES": 3,
            "MULTI_REPLY_INTERVAL_MODE": INTERVAL_NONE,
            "MULTI_REPLY_MIN_INTERVAL": 0.0,
            "MULTI_REPLY_MAX_INTERVAL": 0.0,
        })()


@pytest.mark.asyncio
async def test_multi_reply_over_milky_sends_each_message():
    """Multi-Reply 的 Milky 路径（任务书 §11）：3 条 -> 3 次 send_group_message。"""
    async with FakeMilky() as milky:
        base = "http://127.0.0.1:%d" % milky.port
        async with Sender(Cfg("milky", base)) as sender:
            host = _Host(sender)
            ok = await host._send_reply(["第一句", "第二句", "第三句"], group_id=777)
        assert ok is True
        assert [c[0] for c in milky.calls] == ["send_group_message"] * 3
        texts = [c[2]["message"][0]["data"]["text"] for c in milky.calls]
        assert texts == ["第一句", "第二句", "第三句"]
        assert host.policy_engine.count == 3          # 每条都计一次连续回复


@pytest.mark.asyncio
async def test_onebot_mode_path_unchanged():
    """OneBot 模式不受影响：仍打 /send_group_msg，不带 Milky 的 Bearer 语义。"""
    async with FakeMilky() as milky:
        base = "http://127.0.0.1:%d" % milky.port
        async with Sender(Cfg("onebot", base)) as sender:
            await sender.send_group_message(999, "hi")
        action = milky.calls[0][0]
        assert action == "send_group_msg"             # OneBot 端点名原样保留
        assert "Authorization" not in milky.calls[0][1] or \
            milky.calls[0][1].get("Authorization") is None
