"""MCP 认证端到端验收（任务书 §九 / §十五）：真 socket + 真 Core 动作路径。

链路里没有一段是本文件重写的：真配置解析（parse_mcp_servers + build_auth）
-> 真 Core 动作处理（PluginManager._run_action -> _ext_mcp；以及 McpToolManager /
McpClient）-> 真 TCP socket -> 本文件起的假 MCP server，断言服务端**实际收到**的
请求头（不是断言我们自己拼出来的 headers 字典）。

安全边界一条都不放松：
- SSRF：回环地址仍被 validate_mcp_server_url 拒绝；只有操作员白名单
  MCP_ALLOWED_HOSTS=127.0.0.1 才放行（既有合法路径，不是为测试开后门）；
- 权限：mcp_* 动作仍要 http_request（ACTION_PERMISSIONS + PermissionManager.check）；
- 密钥：只允许出现在请求头。断言 Core 回给插件 / WebUI 的字符串里查不到 token。
"""
import asyncio
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional

import pytest

from src.config import Settings, validate_config
from src.plugins.manager import PluginManager
from src.plugins.permissions import ACTION_PERMISSIONS, PermissionManager
from src.services.mcp_auth import BearerAuth
from src.services.mcp_client import McpClient, McpError
from src.services.mcp_tool_manager import McpToolManager

TOKEN = "test-token-9f3a"
APIKEY = "test-apikey-4b8e"
USERNAME = "ops-user"
PASSWORD = "test-pass-7c1d"
CUSTOM_VALUE = "test-custom-2d5f"
ALL_SECRETS = (TOKEN, APIKEY, PASSWORD, CUSTOM_VALUE)


class _Handler(BaseHTTPRequestHandler):
    """假 MCP server：记录真实请求头，按 JSON-RPC method 回协议应答。"""

    protocol_version = "HTTP/1.1"

    def do_POST(self):  # noqa: N802 - http.server 的命名约定
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", "replace")
        try:
            body = json.loads(raw)
        except ValueError:
            body = {}
        self.server.requests.append({          # type: ignore[attr-defined]
            "authorization": self.headers.get("Authorization"),
            "api_key": self.headers.get("X-API-Key"),
            "custom": self.headers.get("X-Custom-Auth"),
            "content_type": self.headers.get("Content-Type"),
            "session": self.headers.get("mcp-session-id"),
            "method": str(body.get("method") or ""),
            "body": body,
        })
        force = getattr(self.server, "force_status", None)   # type: ignore[attr-defined]
        if force:
            self.send_response(int(force))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        method = str(body.get("method") or "")
        extra: List[Any] = []
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "serverInfo": {"name": "fake-mcp"},
                      "capabilities": {"tools": {}}}
            extra = [("mcp-session-id", "sess-e2e")]
        elif method == "tools/list":
            result = {"tools": [{"name": "echo", "description": "回显工具",
                                 "inputSchema": {"type": "object", "properties": {}}}]}
        else:
            result = {"content": [{"type": "text", "text": "pong"}]}
        data = json.dumps({"jsonrpc": "2.0", "id": body.get("id", 1), "result": result}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        for key, value in extra:
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):   # 静音：默认会往 stderr 刷访问日志
        return


class _FakeMcp:
    """真 socket 上的假 MCP server（127.0.0.1 随机端口）。"""

    def __init__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.requests = []             # type: ignore[attr-defined]
        self.httpd.force_status = None       # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return "http://127.0.0.1:%d/mcp" % self.httpd.server_address[1]

    @property
    def requests(self) -> List[Dict[str, Any]]:
        return self.httpd.requests            # type: ignore[attr-defined]

    def set_status(self, status: Optional[int]) -> None:
        self.httpd.force_status = status      # type: ignore[attr-defined]

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def fake_mcp():
    srv = _FakeMcp()
    try:
        yield srv
    finally:
        srv.close()


def _servers_json(url: str) -> str:
    """五种认证方式各一个 server + 一个无认证 server（同名工具 echo 便于路由断言）。"""
    return json.dumps([
        {"name": "bearer_srv", "url": url, "allowed_tools": "echo",
         "auth": {"type": "bearer", "token": TOKEN}},
        {"name": "apikey_srv", "url": url, "allowed_tools": "echo",
         "auth": {"type": "api_key", "token": APIKEY}},
        {"name": "header_srv", "url": url, "allowed_tools": "echo",
         "auth": {"type": "header", "name": "X-Custom-Auth", "value": CUSTOM_VALUE}},
        {"name": "basic_srv", "url": url, "allowed_tools": "echo",
         "auth": {"type": "basic", "username": USERNAME, "password": PASSWORD}},
        {"name": "open_srv", "url": url, "allowed_tools": "echo"},
    ], ensure_ascii=False)


def _settings(url: str, allowed_hosts=("127.0.0.1",), **over) -> Settings:
    kwargs: Dict[str, Any] = {"DEEPSEEK_API_KEY": "sk-test-only", "BOT_QQ": 10001,
                              "MCP_ENABLED": True, "MCP_SERVERS": _servers_json(url),
                              "MCP_ALLOWED_HOSTS": list(allowed_hosts)}
    kwargs.update(over)
    return Settings(**kwargs)


class _CoreShim(PluginManager):
    """只补 self.config；动作分派表与实现全部继承 PluginManager 的真代码（不复制逻辑）。"""

    def __init__(self, config):
        self.config = config


def _action(settings: Settings, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return asyncio.run(PluginManager._run_action(_CoreShim(settings), "e2e_plugin", action, payload))


def _assert_no_secret(text: str, where: str) -> None:
    for secret in ALL_SECRETS:
        assert secret not in text, "%s 泄露了凭据 %r：%s" % (where, secret, text[:400])


# ---------- 1) 运行态视图：只给 auth type / configured ----------
def test_servers_view_reports_auth_without_secret(fake_mcp):
    mgr = McpToolManager(_settings(fake_mcp.url))
    try:
        view = mgr.servers_view()
    finally:
        asyncio.run(mgr.close())
    _assert_no_secret(json.dumps(view, ensure_ascii=False), "servers_view")
    by = {row["name"]: row for row in view}
    assert by["bearer_srv"]["auth"]["type"] == "bearer"
    assert by["bearer_srv"]["auth"]["configured"] is True
    assert by["basic_srv"]["auth"]["type"] == "basic"
    assert by["open_srv"]["auth"]["type"] == "none"
    assert by["open_srv"]["auth"]["configured"] is False
    assert by["bearer_srv"]["allowed_tools"] == ["echo"]


# ---------- 2) Core 动作：mcp_server / mcp_tools 也不含密钥 ----------
def test_plugin_actions_list_servers_and_tools_without_secret(fake_mcp):
    st = _settings(fake_mcp.url)
    listed = _action(st, "mcp_server", {})
    assert listed["ok"] is True and listed["enabled"] is True, listed
    _assert_no_secret(json.dumps(listed, ensure_ascii=False), "mcp_server")
    assert [s["name"] for s in listed["servers"]] == [
        "bearer_srv", "apikey_srv", "header_srv", "basic_srv", "open_srv"]
    auth = {s["name"]: s["auth"] for s in listed["servers"]}
    assert auth["bearer_srv"]["type"] == "bearer" and auth["bearer_srv"]["configured"] is True
    assert auth["open_srv"]["configured"] is False

    tools = _action(st, "mcp_tools", {})
    assert tools["ok"] is True, tools
    assert {t["server"]: t["allowed_tools"] for t in tools["tools"]}["bearer_srv"] == ["echo"]
    _assert_no_secret(json.dumps(tools, ensure_ascii=False), "mcp_tools")


# ---------- 3) 五种认证方式在真实请求头上的样子 ----------
def test_status_sends_real_header_for_every_auth_type(fake_mcp):
    st = _settings(fake_mcp.url)
    basic = "Basic " + base64.b64encode(
        (USERNAME + ":" + PASSWORD).encode("utf-8")).decode("ascii")
    cases = (
        ("bearer_srv", "authorization", "Bearer " + TOKEN),
        ("apikey_srv", "api_key", APIKEY),
        ("header_srv", "custom", CUSTOM_VALUE),
        ("basic_srv", "authorization", basic),
        ("open_srv", "authorization", None),
    )
    for name, field, want in cases:
        before = len(fake_mcp.requests)
        out = _action(st, "mcp_status", {"server": name})
        assert out["ok"] is True and out["status"] == "online", (name, out)
        assert len(fake_mcp.requests) == before + 1, "假 server 没收到请求：%s" % name
        got = fake_mcp.requests[-1]
        assert got["method"] == "tools/list", (name, got)
        assert got[field] == want, (name, field, got[field], want)
        if name != "open_srv":
            assert got["content_type"] == "application/json", got
        _assert_no_secret(json.dumps(out, ensure_ascii=False), "mcp_status/" + name)


# ---------- 4) mcp_call：真 header + 白名单（未命中不发请求） ----------
def test_call_tool_uses_auth_and_enforces_allowlist(fake_mcp):
    st = _settings(fake_mcp.url)
    ok = _action(st, "mcp_call", {"server": "bearer_srv", "tool": "echo", "arguments": {"q": 1}})
    assert ok["ok"] is True, ok
    sent = fake_mcp.requests[-1]
    assert sent["method"] == "tools/call", sent
    assert sent["authorization"] == "Bearer " + TOKEN, sent
    assert sent["body"]["params"]["name"] == "echo", sent
    assert "pong" in str(ok.get("content") or ""), ok
    _assert_no_secret(json.dumps(ok, ensure_ascii=False), "mcp_call")

    before = len(fake_mcp.requests)
    denied = _action(st, "mcp_call", {"server": "bearer_srv", "tool": "dangerous"})
    assert denied["ok"] is False and "白名单" in denied["error"], denied
    assert len(fake_mcp.requests) == before, "白名单外的工具不该发出任何网络请求"


# ---------- 5) 401 -> authentication failed，且不含密钥 ----------
def test_401_becomes_authentication_failed_without_secret(fake_mcp):
    fake_mcp.set_status(401)
    st = _settings(fake_mcp.url)
    out = _action(st, "mcp_status", {"server": "bearer_srv"})
    assert out["ok"] is False, out
    assert out["status"] == "authentication failed", out
    assert "authentication failed" in out["error"], out
    _assert_no_secret(json.dumps(out, ensure_ascii=False), "mcp_status/401")
    assert fake_mcp.requests[-1]["authorization"] == "Bearer " + TOKEN


# ---------- 6) SSRF 没被关掉：没有白名单时回环照样拒绝 ----------
def test_ssrf_gate_still_rejects_loopback_without_whitelist(fake_mcp):
    """生产同款闸门（validate_config）与连接层（McpClient）都不依赖测试开关。"""
    blocked = _settings(fake_mcp.url, allowed_hosts=())
    with pytest.raises(ValueError) as excinfo:
        validate_config(blocked)              # load_config 调用的就是它
    assert "URL 不合法" in str(excinfo.value), excinfo.value
    assert fake_mcp.requests == [], "被 SSRF 拒绝的地址仍然发出了请求"

    validate_config(_settings(fake_mcp.url))  # 白名单放行：同一个 URL 不再报错

    with pytest.raises(McpError) as excinfo2:
        McpClient(fake_mcp.url, "bearer_srv", timeout=5, allowed_hosts=[], auth=BearerAuth(TOKEN))
    assert "不合法" in str(excinfo2.value), excinfo2.value
    assert fake_mcp.requests == []


# ---------- 7) 权限门没被关掉 ----------
def test_mcp_actions_still_require_http_request_permission():
    assert ACTION_PERMISSIONS["mcp_call"] == "http_request"
    assert ACTION_PERMISSIONS["mcp_server"] == "http_request"
    deny = PermissionManager([])
    assert deny.check("mcp_call") is False
    assert "http_request" in deny.denied_reason("mcp_call")
    allow = PermissionManager(["http_request"])
    assert allow.check("mcp_call") is True


# ---------- 8) McpClient 走真 socket：三个 RPC 都带认证（含 session 后续请求） ----------
def test_mcp_client_rpcs_carry_auth_over_real_socket(fake_mcp):
    cli = McpClient(fake_mcp.url, "bearer_srv", timeout=5,
                    allowed_hosts=["127.0.0.1"], auth=BearerAuth(TOKEN))

    async def go():
        tools = await cli.list_tools()
        result = await cli.call_tool("echo", {"q": 2})
        again = await cli.list_tools()
        await cli.close()
        return tools, result, again

    tools, result, _again = asyncio.run(go())
    assert [t.get("name") for t in tools] == ["echo"], tools
    assert "pong" in str(result), result
    methods = [r["method"] for r in fake_mcp.requests]
    assert methods[0] == "initialize", methods
    assert "tools/list" in methods and "tools/call" in methods, methods
    for row in fake_mcp.requests:
        assert row["authorization"] == "Bearer " + TOKEN, row
    assert fake_mcp.requests[-1]["session"] == "sess-e2e", fake_mcp.requests[-1]
