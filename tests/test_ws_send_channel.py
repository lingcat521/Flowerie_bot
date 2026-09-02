"""SEND_VIA_WS：sender 经 WebSocket 发送（echo 请求-响应匹配）。"""
import asyncio
import json

import pytest

from src.core.websocket_server import WebSocketServer
from src.services.sender import Sender


class _Cfg:
    SEND_VIA_WS = True
    HTTP_API_BASE = "http://127.0.0.1:3000"
    MAX_REPLY_LENGTH = 500


class _FakeWs:
    def __init__(self):
        self.sent = []
        self.closed = False

    async def send(self, msg):
        self.sent.append(json.loads(msg))


def test_send_action_echo_roundtrip():
    ws = _FakeWs()
    server = WebSocketServer.__new__(WebSocketServer)
    server.ws = ws
    server._pending = {}

    async def flow():
        async def waiter():
            await asyncio.sleep(0.05)
            # 模拟 NapCat 回 echo 响应
            echo = ws.sent[0]["echo"]
            server._pending[echo].set_result(
                {"echo": echo, "status": "ok", "retcode": 0, "data": {"message_id": 123}})
            return None
        task = asyncio.create_task(waiter())
        resp = await server.send_action("send_group_msg", {"group_id": 1, "message": "hi"})
        await task
        return resp

    resp = asyncio.run(flow())
    assert resp.get("status") == "ok"
    assert ws.sent[0]["action"] == "send_group_msg"
    assert ws.sent[0]["params"] == {"group_id": 1, "message": "hi"}


@pytest.mark.asyncio
async def test_sender_uses_ws_when_enabled():
    calls = []

    async def fake_ws_sender(action, params):
        calls.append((action, params))
        return {"status": "ok", "retcode": 0}

    sender = Sender(_Cfg(), ws_sender=fake_ws_sender)
    ok = await sender.send_group_message(786368680, "测试消息")
    assert ok and calls[0][0] == "send_group_msg"
    assert calls[0][1] == {"group_id": 786368680, "message": "测试消息"}


@pytest.mark.asyncio
async def test_sender_http_when_disabled(capsys):
    """SEND_VIA_WS=false：不经 WS（HTTP 路径，由既有测试覆盖）。"""
    calls = []

    async def fake_ws_sender(action, params):
        calls.append(action)

    sender = Sender(_Cfg(), ws_sender=fake_ws_sender)
    sender.config.SEND_VIA_WS = False
    # HTTP 不存在 → _post 报错路径（确认没有走 WS）
    import aiohttp
    sender.session = aiohttp.ClientSession()
    ok = await sender.send_group_message(1, "x")
    await sender.close()
    assert not ok
    assert calls == []   # 未触发 WS
