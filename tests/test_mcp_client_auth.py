"""McpClient 认证注入测试（任务书 §六：所有 RPC 都必须经过认证层）。"""
import asyncio
import json

import pytest

from src.services.mcp_auth import ApiKeyAuth, BasicAuth, BearerAuth, build_auth
from src.services.mcp_client import McpClient


class _Resp:
    def __init__(self, payload, headers=None):
        self.status_code = 200
        self._payload = payload
        self.headers = headers if headers is not None else {"content-type": "application/json"}
        self.text = json.dumps(payload)


class _FakeHttp:
    """假 HTTP 客户端：记录每次请求的 headers，按 method 返回协议应答。"""

    def __init__(self):
        self.calls = []
        self.is_closed = False

    async def post(self, url, headers=None, json=None):
        self.calls.append({"url": url, "headers": dict(headers or {}), "body": json})
        method = (json or {}).get("method")
        if method == "initialize":
            return _Resp({"jsonrpc": "2.0", "id": 1, "result": {}},
                         {"content-type": "application/json", "mcp-session-id": "sess-1"})
        if method == "tools/list":
            return _Resp({"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "t1"}]}})
        return _Resp({"jsonrpc": "2.0", "id": 1,
                      "result": {"content": [{"type": "text", "text": "ok"}]}})

    async def aclose(self):
        self.is_closed = True


def _client(auth=None):
    cli = McpClient("https://mcp.example/rpc", "srv", timeout=5, auth=auth)
    fake = _FakeHttp()
    cli._client = fake                      # 注入假 HTTP 层（不触网）
    cli._resolve_ips = lambda host, port: asyncio.sleep(0, result=["93.184.216.34"])

    async def _noop():
        return None

    cli._check_dns = _noop                  # SSRF 的 DNS 校验不在本文件测试范围（有专门用例）
    return cli, fake


def _run(coro):
    return asyncio.run(coro)


# ---------- 1) 三个 RPC 都带认证 ----------
def test_all_rpcs_carry_auth_headers():
    cli, fake = _client(BearerAuth("tok-abc"))
    _run(cli.list_tools())
    _run(cli.call_tool("t1", {"a": 1}))
    methods = [c["body"]["method"] for c in fake.calls]
    assert methods == ["initialize", "tools/list", "tools/call"]
    for call in fake.calls:
        assert call["headers"]["Authorization"] == "Bearer tok-abc"


def test_session_followup_requests_keep_auth():
    cli, fake = _client(BearerAuth("tok-abc"))
    _run(cli.list_tools())
    _run(cli.list_tools())                   # 第二次：应带 session id 且认证仍在
    assert fake.calls[1]["headers"]["mcp-session-id"] == "sess-1"
    assert fake.calls[1]["headers"]["Authorization"] == "Bearer tok-abc"
    assert fake.calls[0]["headers"].get("mcp-session-id") is None


# ---------- 2) 各认证方式注入到正确的 header ----------
def test_api_key_and_basic_headers():
    cli, fake = _client(ApiKeyAuth("X-Token", "k-1"))
    _run(cli.list_tools())
    assert fake.calls[0]["headers"]["X-Token"] == "k-1"

    cli2, fake2 = _client(BasicAuth("u", "p"))
    _run(cli2.list_tools())
    assert fake2.calls[0]["headers"]["Authorization"].startswith("Basic ")


def test_custom_header_auth_injected():
    cli, fake = _client(build_auth({"type": "header", "name": "X-Auth", "value": "v-9"}))
    _run(cli.list_tools())
    assert fake.calls[0]["headers"]["X-Auth"] == "v-9"


# ---------- 3) 无认证：不加任何认证 header ----------
def test_no_auth_adds_nothing():
    cli, fake = _client()
    _run(cli.list_tools())
    for call in fake.calls:
        assert "Authorization" not in call["headers"]
        assert set(call["headers"]) <= {"Content-Type", "Accept", "mcp-session-id"}


# ---------- 4) 协议头与 base headers 不受影响 ----------
def test_base_headers_preserved():
    cli, fake = _client(BearerAuth("t"))
    _run(cli.list_tools())
    headers = fake.calls[0]["headers"]
    assert headers["Content-Type"] == "application/json"
    assert "text/event-stream" in headers["Accept"]


# ---------- 5) auth_info()：只有类型与是否配置，绝不含 secret ----------
@pytest.mark.parametrize("auth,expected_type", [
    (None, "none"),
    (BearerAuth("SECRET-B"), "bearer"),
    (ApiKeyAuth("X-K", "SECRET-K"), "api_key"),
    (build_auth({"type": "basic", "username": "u", "password": "SECRET-P"}), "basic"),
])
def test_auth_info_exposes_no_secret(auth, expected_type):
    cli, _ = _client(auth)
    info = cli.auth_info()
    assert info["type"] == expected_type
    blob = json.dumps(info)
    for secret in ("SECRET-B", "SECRET-K", "SECRET-P"):
        assert secret not in blob


# ---------- 6) 认证配置在构造时定型：之后改配置不影响已建客户端 ----------
def test_auth_bound_at_construction():
    spec = {"type": "bearer", "token": "first"}
    auth = build_auth(spec)
    cli, fake = _client(auth)
    spec["token"] = "second"                  # 事后改 dict 不应影响已构造的策略
    _run(cli.list_tools())
    assert fake.calls[0]["headers"]["Authorization"] == "Bearer first"

