"""MCP 认证的五语言 SDK 验收（任务书 §七 / §九）：真插件进程 -> 真 Core -> 假 MCP server。

五种语言的示例插件都注册了**同名同义**的 mcp_demo 控制面 hook（否则无法用真进程驱动 SDK）。
测试侧不当假引擎：插件的 action 请求交给真实 Core（PluginManager._run_action -> _ext_mcp）
与真实权限门（PermissionManager），所以断言到的请求头是插件进程一路走到 HTTP 服务端的
真实结果，而不是测试自己拼的字典。

安全边界不放松：SSRF 仍要操作员白名单才放行回环（MCP_ALLOWED_HOSTS）；mcp_* 仍要
http_request 权限。本机缺工具链的语言 skip 并打印原因（CI 上五种语言全跑）。
"""
import asyncio
import json
import os
import shutil
from typing import Any, Dict, Tuple

import pytest

from src.plugins.manager import PluginManager
from src.plugins.permissions import PermissionManager
from tests.test_mcp_auth_e2e import TOKEN, _assert_no_secret, _CoreShim, _FakeMcp, _settings
from tests.test_plugin_sdk_contract import ROOT, LANGUAGES, _missing_reason, _Peer

LANG_PARAMS = sorted(LANGUAGES)
SERVERS = ["apikey_srv", "basic_srv", "bearer_srv", "header_srv", "open_srv"]


@pytest.fixture
def fake_mcp():
    srv = _FakeMcp()
    try:
        yield srv
    finally:
        srv.close()


def _bundle_python_sdk(peer) -> None:
    """Python 示例插件不自带 SDK 副本；真实部署的插件目录里会带一份 —— 这里照做，
    否则插件进程里 import flowerie_sdk 会失败（runner 是 python -I 隔离启动）。"""
    if peer.lang != "python":
        return
    target = os.path.join(peer.proc_dir, "flowerie_sdk")
    if not os.path.isdir(target):
        shutil.copytree(os.path.join(ROOT, "plugin_sdk", "flowerie_sdk"), target,
                        ignore=shutil.ignore_patterns("__pycache__"))


def _core_action_handler(settings, approved: Tuple[str, ...] = ("http_request",)):
    """插件 action -> 真实权限门 -> 真实 Core 动作实现（这里一行业务逻辑都不复制）。"""
    gate = PermissionManager(list(approved))

    def handle(action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not gate.check(action):
            return {"ok": False, "error": gate.denied_reason(action)}
        return asyncio.run(
            PluginManager._run_action(_CoreShim(settings), "multilang_demo", action, payload))

    return handle


@pytest.fixture
def make_peer(fake_mcp):
    """按语言起真示例进程；引擎面接真 Core。"""
    created = []

    def _make(lang: str, approved: Tuple[str, ...] = ("http_request",)):
        reason = _missing_reason(lang)
        if reason:
            pytest.skip(reason)
        peer = _Peer(lang)
        _bundle_python_sdk(peer)
        peer.action_handler = _core_action_handler(_settings(fake_mcp.url), approved)
        peer.init_result = peer.initialize()["result"]
        created.append(peer)
        return peer

    yield _make
    for peer in created:
        peer.close()


def _hook(peer, *args) -> Dict[str, Any]:
    """hook mcp_demo -> 信封 {ok, result}：把插件返回的那一层解出来。"""
    envelope = peer.call("hook", {"name": "mcp_demo", "args": list(args)})["result"]
    assert envelope.get("ok") is True, "%s 的 mcp_demo hook 失败：%s" % (peer.lang, envelope)
    payload = envelope.get("result")
    assert isinstance(payload, dict), envelope
    return payload


@pytest.mark.parametrize("lang", LANG_PARAMS)
def test_servers_list_auth_status_without_secret(make_peer, lang):
    """list server：五语言同一批 server、同一批认证状态，且不含任何密钥。"""
    peer = make_peer(lang)
    out = _hook(peer, "servers")
    _assert_no_secret(json.dumps(out, ensure_ascii=False), "%s/mcp_demo.servers" % lang)
    rows = {row["name"]: row for row in out["servers"]}
    assert sorted(rows) == SERVERS, (lang, sorted(rows))
    assert rows["bearer_srv"]["auth"] == {"type": "bearer", "configured": True}, (lang, rows["bearer_srv"])
    assert rows["apikey_srv"]["auth"]["type"] == "api_key", (lang, rows["apikey_srv"])
    assert rows["header_srv"]["auth"]["type"] == "header", (lang, rows["header_srv"])
    assert rows["basic_srv"]["auth"]["type"] == "basic", (lang, rows["basic_srv"])
    assert rows["open_srv"]["auth"] == {"type": "none", "configured": False}, (lang, rows["open_srv"])
    assert [a["action"] for a in peer.actions] == ["mcp_server"], peer.actions


@pytest.mark.parametrize("lang", LANG_PARAMS)
def test_tools_and_auth_query_are_identical(make_peer, lang):
    """list tools + auth 状态查询：白名单与认证状态跨语言逐项一致。"""
    peer = make_peer(lang)
    tools = _hook(peer, "tools")["tools"]
    by_server = {row["server"]: row["allowed_tools"] for row in tools}
    assert sorted(by_server) == SERVERS, (lang, sorted(by_server))
    assert by_server["bearer_srv"] == ["echo"], (lang, by_server)
    assert _hook(peer, "auth", "bearer_srv")["auth"] == {"type": "bearer", "configured": True}, lang
    assert _hook(peer, "auth", "open_srv")["auth"]["type"] == "none", lang
    assert [a["action"] for a in peer.actions] == ["mcp_tools", "mcp_server", "mcp_server"], peer.actions


@pytest.mark.parametrize("lang", LANG_PARAMS)
def test_call_tool_sends_real_bearer_header(make_peer, fake_mcp, lang):
    """call tool：插件进程 -> Core -> 真 HTTP，服务端实际收到 Authorization: Bearer <token>。"""
    peer = make_peer(lang)
    before = len(fake_mcp.requests)
    out = _hook(peer, "call", "bearer_srv", "echo")["call"]
    assert out["ok"] is True, (lang, out)
    assert "pong" in str(out.get("result") or ""), (lang, out)
    _assert_no_secret(json.dumps(out, ensure_ascii=False), "%s/mcp_demo.call" % lang)
    assert [a["action"] for a in peer.actions] == ["mcp_call"], peer.actions
    sent = fake_mcp.requests[before:]
    assert sent, "%s 的工具调用没有到达假 MCP server" % lang
    assert sent[-1]["method"] == "tools/call", (lang, sent[-1])
    assert sent[-1]["authorization"] == "Bearer " + TOKEN, (lang, sent[-1]["authorization"])


@pytest.mark.parametrize("lang", LANG_PARAMS)
def test_permission_denied_is_structured_and_sends_nothing(make_peer, fake_mcp, lang):
    """permission denied：管理员没批 http_request 时是结构化拒绝，且一个包都不发。"""
    peer = make_peer(lang, approved=())
    before = len(fake_mcp.requests)
    out = _hook(peer, "call", "bearer_srv", "echo")["call"]
    assert out["ok"] is False, (lang, out)
    assert "http_request" in str(out.get("error") or ""), (lang, out)
    assert len(fake_mcp.requests) == before, "%s 权限被拒后仍然发出了请求" % lang
