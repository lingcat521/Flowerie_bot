"""Gate Q：TransportContract（8 项）—— WebSocketTransport / HTTPTransport 逐项核对。

做法：用**注入式 I/O 原语**在进程内测传输语义（不联网、不需要 websockets/aiohttp）：
- 假连接（FakeConnection）：send 记录帧、recv 从队列取、遇 action 帧自动回 echo 响应；
- 假 poster（FakePoster）：记录调用并按脚本返回 (status, body)。
契约核对 `check_transport_contract` 把 8 项逐项标成 implemented / N/A(附理由) / missing，
数字（covered、implemented、na、missing）直接进验收 Dashboard。
"""
import asyncio
import json
import os
import subprocess
import sys

import pytest

from src.transport import (
    CONTRACT_ITEMS,
    TRANSPORT_CONTRACT_ITEMS,
    HTTPTransport,
    ReconnectPolicy,
    RetryPolicy,
    TransportContract,
    WebSocketTransport,
    check_transport_contract,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIRED_ITEMS = ("connect", "disconnect", "send", "receive", "request",
                  "authentication", "error", "reconnect")


def _ok_body(data=None):
    return json.dumps({"status": "ok", "retcode": 0, "data": data or {}})


class FakeConnection:
    """进程内假 WS 连接：可选自动回 echo 响应（模拟 OneBot 协议端）。"""

    def __init__(self, auto_reply=True, fail_on_send=False, replies=None, close_after_recv=None):
        self.sent = []
        self.closed = False
        self.auto_reply = auto_reply
        self.fail_on_send = fail_on_send
        self.replies = list(replies or [])
        self.close_after_recv = close_after_recv
        self._queue = asyncio.Queue()
        self._recv_calls = 0

    async def send(self, text):
        if self.fail_on_send:
            raise ConnectionError("boom")
        frame = json.loads(text)
        self.sent.append(frame)
        if self.auto_reply and "action" in frame:
            body = dict(self.replies.pop(0)) if self.replies else {
                "status": "ok", "retcode": 0, "data": {"echoed": frame["action"]}}
            body.setdefault("echo", frame.get("echo"))
            self._queue.put_nowait(json.dumps(body))

    async def recv(self):
        self._recv_calls += 1
        if self.close_after_recv is not None and self._recv_calls > self.close_after_recv:
            return None
        return await self._queue.get()

    async def close(self):
        self.closed = True

    def push(self, frame):
        self._queue.put_nowait(json.dumps(frame) if not isinstance(frame, str) else frame)


class FakePoster:
    """假 HTTP poster：记录调用，按脚本出 (status, body) 或抛异常。"""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = list(responses or [])

    async def __call__(self, url, json=None, headers=None, timeout=10.0):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        item = self.responses.pop(0) if self.responses else (200, _ok_body({"via": "poster"}))
        if isinstance(item, Exception):
            raise item
        return item


def _ws(conn, **kwargs):
    """构造 WS 传输 + 记录 connector 收到的 (url, headers)。"""
    holder = {}

    async def connector(url, headers=None):
        holder["url"] = url
        holder["headers"] = headers
        holder["calls"] = holder.get("calls", 0) + 1
        return conn

    kwargs.setdefault("request_timeout", 0.3)
    kwargs.setdefault("reconnect_policy", ReconnectPolicy(attempts=3, base_delay=0.0, max_delay=0.0))
    return WebSocketTransport("ws://example/ws", connector=connector, **kwargs), holder


def _http(poster, **kwargs):
    kwargs.setdefault("retry_policy", RetryPolicy(attempts=1, base_delay=0.0, max_delay=0.0))
    return HTTPTransport("http://api.local", poster=poster, **kwargs)


# ------------------------- 契约定义本身 -------------------------

def test_contract_defines_exactly_the_eight_required_items():
    assert TRANSPORT_CONTRACT_ITEMS == REQUIRED_ITEMS
    assert len(TRANSPORT_CONTRACT_ITEMS) == 8
    assert tuple(i.name for i in CONTRACT_ITEMS) == REQUIRED_ITEMS
    for item in CONTRACT_ITEMS:
        assert item.summary.strip() and item.semantics.strip(), "契约项必须写清摘要与语义：%s" % item.name


def test_websocket_transport_covers_all_eight_items():
    report = check_transport_contract(_ws(FakeConnection())[0])
    assert report.ok is True
    assert (report.covered, report.implemented, report.na) == (8, 8, 0)
    assert report.missing == () and report.undocumented_na == ()


def test_http_transport_covers_all_eight_with_two_documented_na():
    report = check_transport_contract(_http(FakePoster()))
    assert report.ok is True
    assert (report.covered, report.implemented, report.na) == (8, 6, 2)
    assert report.missing == () and report.undocumented_na == ()
    assert set(report.reasons) == {"receive", "reconnect"}
    for item, reason in report.reasons.items():
        assert len(reason) >= 20, "N/A 理由要说清楚（%s）：%s" % (item, reason)
    # N/A 是"声明不适用"，不是"继承基类占位实现"
    assert "receive" not in HTTPTransport.__dict__ and "reconnect" not in HTTPTransport.__dict__


def test_incomplete_transport_is_reported_as_missing():
    class HalfTransport(TransportContract):
        name = "half"

        async def connect(self):
            return True

    report = check_transport_contract(HalfTransport())
    assert report.ok is False
    assert report.implemented == 1
    assert set(report.missing) == set(REQUIRED_ITEMS) - {"connect"}


def test_report_serializes_for_dashboard():
    data = check_transport_contract(_ws(FakeConnection())[0]).as_dict()
    assert data["total"] == 8 and data["covered"] == 8 and data["ok"] is True
    assert set(data["statuses"]) == set(REQUIRED_ITEMS)
    assert data["transport"] == "websocket"


def test_transport_package_imports_without_network_libraries():
    """契约与传输语义不得被网络库绑死：屏蔽 websockets/aiohttp 后仍能 import。"""
    blocker = (
        "import sys\n"
        "BLOCKED = ('websockets', 'aiohttp')\n"
        "class _Block:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in BLOCKED:\n"
        "            raise ImportError('blocked: ' + name)\n"
        "sys.meta_path.insert(0, _Block())\n"
        "import src.transport as t\n"
        "assert len(t.TRANSPORT_CONTRACT_ITEMS) == 8\n"
        "assert t.WebSocketTransport and t.HTTPTransport\n"
        "print('ok')\n"
    )
    proc = subprocess.run([sys.executable, "-c", blocker], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-800:]
    assert "ok" in proc.stdout


# ------------------------- WebSocketTransport 行为 -------------------------

@pytest.mark.asyncio
async def test_ws_connect_send_receive_roundtrip():
    conn = FakeConnection()
    transport, holder = _ws(conn)
    assert await transport.connect() is True
    assert holder["url"] == "ws://example/ws"
    assert await transport.send({"kind": "msg", "text": "hi"}) is True
    assert conn.sent[0] == {"kind": "msg", "text": "hi"}
    conn.push({"kind": "msg", "text": "from-server"})
    got = await transport.receive(timeout=1.0)
    assert got == {"kind": "msg", "text": "from-server"}
    assert await transport.receive(timeout=0.05) is None      # 超时返回 None，不抛
    assert transport.error() is None
    assert await transport.disconnect() is True
    assert conn.closed is True


@pytest.mark.asyncio
async def test_ws_request_pairs_echo_response():
    conn = FakeConnection()
    transport, _ = _ws(conn)
    await transport.connect()
    res = await transport.request("get_status", {"a": 1})
    assert res["ok"] is True and res["data"]["echoed"] == "get_status"
    frame = conn.sent[0]
    assert frame["action"] == "get_status" and frame["params"] == {"a": 1} and frame["echo"]
    assert transport.error() is None
    await transport.disconnect()


@pytest.mark.asyncio
async def test_ws_request_timeout_and_send_failure_are_observable():
    conn = FakeConnection(auto_reply=False)
    transport, _ = _ws(conn)
    await transport.connect()
    res = await transport.request("no_answer")
    assert res == {"ok": False, "error": "timeout"}
    assert "timeout" in (transport.error() or "")
    await transport.disconnect()

    errors = []
    bad = FakeConnection(fail_on_send=True)
    transport2, _ = _ws(bad, on_error=errors.append)
    await transport2.connect()
    assert await transport2.send({"x": 1}) is False
    assert "boom" in (transport2.error() or "")
    assert errors and "send" in errors[-1]
    await transport2.disconnect()


@pytest.mark.asyncio
async def test_ws_authentication_header_and_token_frame():
    conn = FakeConnection()
    transport, holder = _ws(conn, access_token="tok", auth_payload_key="access_token")
    assert transport.authentication() == {"Authorization": "Bearer tok"}
    assert transport.auth_frame() == {"access_token": "tok"}
    await transport.connect()
    assert holder["headers"] == {"Authorization": "Bearer tok"}
    assert conn.sent[0] == {"access_token": "tok"}          # 首帧带 token

    plain = FakeConnection()
    transport2, holder2 = _ws(plain)
    assert transport2.authentication() == {} and transport2.auth_frame() == {}
    await transport2.connect()
    assert holder2["headers"] == {} and plain.sent == []     # 无 token 时不多发帧
    await transport.disconnect()
    await transport2.disconnect()


@pytest.mark.asyncio
async def test_ws_reconnect_retries_with_backoff():
    conns = [FakeConnection()]
    attempts = []

    async def connector(url, headers=None):
        attempts.append(url)
        if len(attempts) == 1:
            raise OSError("first attempt fails")
        return conns[0]

    errors = []
    transport = WebSocketTransport("ws://example/ws", connector=connector, on_error=errors.append,
                                   reconnect_policy=ReconnectPolicy(attempts=3, base_delay=0.0, max_delay=0.0))
    assert await transport.reconnect() is True
    assert transport.reconnect_attempts == 2
    assert isinstance(errors, list)
    assert any("connect" in e for e in errors)
    assert await transport.send({"ping": 1}) is True
    await transport.disconnect()


@pytest.mark.asyncio
async def test_ws_disconnect_is_idempotent_and_fails_pending_request():
    conn = FakeConnection(auto_reply=False)
    transport, _ = _ws(conn)
    await transport.connect()
    pending = asyncio.ensure_future(transport.request("slow", timeout=5.0))
    await asyncio.sleep(0.05)
    assert await transport.disconnect() is True
    assert await transport.disconnect() is True            # 幂等
    res = await pending
    assert res["ok"] is False
    assert await transport.send({"after": "close"}) is False


@pytest.mark.asyncio
async def test_ws_reader_survives_bad_json_and_naughty_callback():
    conn = FakeConnection()
    seen = []

    def on_event(frame):
        seen.append(frame)
        raise RuntimeError("回调自己炸了")

    transport, _ = _ws(conn, on_event=on_event)
    await transport.connect()
    conn.push("not-json-at-all")          # 脏帧：不得打断读取循环
    conn.push({"kind": "msg"})
    frame = await transport.receive(timeout=1.0)
    assert frame == {"raw": "not-json-at-all"}
    frame2 = await transport.receive(timeout=1.0)
    assert frame2 == {"kind": "msg"}
    await asyncio.sleep(0.05)
    assert len(seen) == 2                 # 回调每个帧都被调用（自身异常被吞掉并记录）
    assert "on_event" in (transport.error() or "")
    await transport.disconnect()


# ------------------------- HTTPTransport 行为 -------------------------

@pytest.mark.asyncio
async def test_http_connect_requires_base_url_then_ready():
    no_url = HTTPTransport("", poster=FakePoster())
    assert await no_url.connect() is False
    assert "base_url" in (no_url.error() or "")

    transport = _http(FakePoster())
    assert await transport.connect() is True and transport.ready is True
    assert await transport.disconnect() is True and transport.ready is False


@pytest.mark.asyncio
async def test_http_request_success_url_payload_and_auth_header():
    poster = FakePoster()
    transport = _http(poster, access_token="tok")
    await transport.connect()
    res = await transport.request("send_group_msg", {"group_id": 1, "message": "hi"})
    assert res["ok"] is True and res["data"] == {"via": "poster"}
    call = poster.calls[0]
    assert call["url"] == "http://api.local/send_group_msg"
    assert call["json"] == {"group_id": 1, "message": "hi"}
    assert call["headers"]["Authorization"] == "Bearer tok"
    assert call["headers"]["Content-Type"] == "application/json"
    assert transport.authentication() == {"Content-Type": "application/json",
                                          "Authorization": "Bearer tok"}


@pytest.mark.asyncio
async def test_http_send_is_fire_and_forget_and_counts_requests():
    poster = FakePoster([(200, "not json but delivered")])
    transport = _http(poster)
    await transport.connect()
    assert await transport.send({"notice": "x"}, endpoint="report") is True
    assert transport.requests == 1
    assert poster.calls[0]["url"] == "http://api.local/report"


@pytest.mark.asyncio
async def test_http_request_retries_per_policy():
    poster = FakePoster([OSError("network down"), (200, _ok_body())])
    transport = _http(poster, retry_policy=RetryPolicy(attempts=3, base_delay=0.0, max_delay=0.0))
    await transport.connect()
    res = await transport.request("get_status")
    assert res["ok"] is True
    assert transport.last_attempts == 2 and transport.requests == 2

    failing = FakePoster([OSError("down"), OSError("down"), OSError("down")])
    transport2 = _http(failing, retry_policy=RetryPolicy(attempts=3, base_delay=0.0, max_delay=0.0))
    res2 = await transport2.request("get_status")
    assert res2["ok"] is False and transport2.last_attempts == 3
    assert "OSError" in (transport2.error() or "")


@pytest.mark.asyncio
async def test_http_http_error_and_non_json_body_are_failures():
    transport = _http(FakePoster([(500, "server exploded")]))
    res = await transport.request("boom")
    assert res["ok"] is False and res["error"] == "HTTP 500"

    transport2 = _http(FakePoster([(200, "<html>login page</html>")]))
    res2 = await transport2.request("intercepted")
    assert res2["ok"] is False and res2["error"] == "invalid json response"
    assert transport2.error() == "invalid json response"

    transport3 = _http(FakePoster([(200, json.dumps({"status": "failed", "retcode": 100}))]))
    res3 = await transport3.request("rejected")
    assert res3["ok"] is False and "retcode=100" in res3["error"]


# ------------------------- 真实 I/O 绑定（CI 有依赖；本机缺依赖则跳过） -------------------------

def test_real_io_bindings_are_provided_lazily():
    pytest.importorskip("websockets")
    from src.transport import websockets_connector
    assert callable(websockets_connector())

    pytest.importorskip("aiohttp")
    from src.transport import aiohttp_poster
    poster = aiohttp_poster()
    assert callable(poster) and callable(poster.aclose)
