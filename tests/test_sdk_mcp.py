"""Python SDK 的 MCP facade 测试（任务书 §九 / §十一 / §十二）。

覆盖：server 列表与认证状态、工具白名单过滤、结构化调用结果、失败不抛异常、
未知 server、未接线降级、异常返回形状容错、以及**任何输出都不含密钥**。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin_sdk"))

from flowerie_sdk import McpAuthInfo, McpFacade  # noqa: E402


class _Api:
    def __init__(self, servers=None, tools=None, call=None, status=None):
        self.calls = []
        self._servers = servers if servers is not None else {"ok": True, "servers": [
            {"name": "a", "url": "https://a/mcp", "auth": {"type": "bearer", "configured": True}},
            {"name": "c", "url": "https://c/mcp"},
        ]}
        self._tools = tools if tools is not None else {"ok": True, "tools": [
            {"server": "a", "allowed_tools": ["t1", "t2"]},
        ]}
        self._call = call if call is not None else {"ok": True, "result": {"content": "ok"}}
        self._status = status if status is not None else {"ok": True, "status": "online",
                                                         "auth": {"type": "bearer", "configured": True}}

    def mcp_server(self, payload):
        self.calls.append(("mcp_server", payload))
        return self._servers

    def mcp_tools(self, payload):
        self.calls.append(("mcp_tools", payload))
        return self._tools

    def mcp_call(self, payload):
        self.calls.append(("mcp_call", payload))
        return self._call

    def mcp_status(self, payload):
        self.calls.append(("mcp_status", payload))
        return self._status


def test_servers_expose_auth_state():
    facade = McpFacade(_Api())
    servers = facade.servers()
    assert [s.name for s in servers] == ["a", "c"]
    assert servers[0].auth.type == "bearer" and servers[0].auth.configured is True
    assert servers[0].auth.status == "configured"
    assert servers[1].auth.type == "none" and servers[1].auth.status == "none"


def test_tools_filter_by_server_and_empty_means_all():
    api = _Api(tools={"ok": True, "tools": [
        {"server": "a", "allowed_tools": ["t1"]},
        {"server": "b", "allowed_tools": []},
    ]})
    facade = McpFacade(api)
    assert [(t.server, t.allowed_tools) for t in facade.tools("a")] == [("a", ["t1"])]
    assert len(facade.tools()) == 2
    assert facade.tools("b")[0].allowed_tools == []          # 空 = 放行全部


def test_call_returns_structured_result():
    api = _Api()
    result = facade_call(api)
    assert result.ok is True and result.result == {"content": "ok"}
    assert api.calls[-1][1] == {"server": "a", "tool": "t1", "arguments": {"x": 1}}


def facade_call(api):
    return McpFacade(api).call("a", "t1", {"x": 1})


def test_call_failure_is_folded_not_raised():
    facade = McpFacade(_Api(call={"ok": False, "error": "白名单拒绝: evil"}))
    result = facade.call("a", "evil")
    assert result.ok is False and "白名单" in result.error


def test_transport_exception_is_folded():
    class Boom(_Api):
        def mcp_server(self, payload):
            raise RuntimeError("管道断了")

    assert McpFacade(Boom()).servers() == []


def test_auth_lookup_and_unknown_server():
    facade = McpFacade(_Api())
    assert facade.auth("a").status == "configured"
    unknown = facade.auth("nope")
    assert isinstance(unknown, McpAuthInfo) and unknown.status == "none"


def test_status_passes_through():
    api = _Api()
    out = McpFacade(api).status("a")
    assert out["status"] == "online" and api.calls[-1][0] == "mcp_status"


def test_no_api_channel_degrades_gracefully():
    facade = McpFacade(None)
    assert facade.servers() == [] and facade.tools() == []
    result = facade.call("a", "t")
    assert result.ok is False and "未接线" in result.error


def test_unexpected_engine_shapes_tolerated():
    facade = McpFacade(_Api(servers={"ok": True, "servers": ["nope", None, 42]}))
    assert facade.servers() == []
    weird = McpFacade(_Api(call="not-a-dict"))
    assert weird.call("a", "t").ok is False


def test_secret_never_appears_in_any_output():
    """引擎即便多给了密钥字段，facade 也不能把它带出去（白名单式提取）。"""
    leaky = {"ok": True, "servers": [{
        "name": "a", "url": "https://a/mcp",
        "auth": {"type": "bearer", "configured": True, "token": "LEAK-TOKEN",
                 "password": "LEAK-PWD"},
    }]}
    facade = McpFacade(_Api(servers=leaky))
    blob = json.dumps([s.auth.to_dict() for s in facade.servers()], ensure_ascii=False)
    assert "LEAK-TOKEN" not in blob and "LEAK-PWD" not in blob
    assert "token" not in blob and "password" not in blob

