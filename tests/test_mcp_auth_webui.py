"""MCP 认证的 WebUI 与 Core API 测试（任务书 §八 / §十三 / §十四）。

覆盖：merge_auth_spec 的留空保持/覆盖/清除语义、表单不回显 secret、
卡片显示认证状态、面板表单解析（留空保持 + 清除开关）、
Core API 暴露认证状态且不含 secret、非法配置被拒、历史 tools 字段兼容。
"""
import asyncio
import json
from types import SimpleNamespace

from src.plugins.manager import PluginManager
from src.services.mcp_auth import merge_auth_spec
from src.services.webui_panels.mcp_panel import McpPanelMixin
from src.services.webui_render.config_panel import _mcp_server_card, _mcp_server_form


# ---------- 1) merge_auth_spec：留空保持 / 覆盖 / 清除 / 切换 ----------
def test_merge_keeps_previous_secret_when_blank():
    spec, err = merge_auth_spec("bearer", {"type": "bearer", "token": "OLD"})
    assert err is None and spec == {"type": "bearer", "token": "OLD"}


def test_merge_overrides_with_new_secret():
    spec, err = merge_auth_spec("bearer", {"type": "bearer", "token": "OLD"}, token="NEW")
    assert err is None and spec["token"] == "NEW"


def test_merge_clear_drops_secret_and_fails_fast():
    # 清除密钥但类型仍需凭据 → fail-fast（提示用户同时把认证方式改成无认证）
    spec, err = merge_auth_spec("bearer", {"type": "bearer", "token": "OLD"}, clear=True)
    assert spec is None and "token" in err


def test_merge_switch_to_none_returns_none():
    assert merge_auth_spec("none", {"type": "bearer", "token": "OLD"}) == (None, None)


def test_merge_basic_keeps_username_and_password():
    prev = {"type": "basic", "username": "u", "password": "p"}
    assert merge_auth_spec("basic", prev) == ({"type": "basic", "username": "u", "password": "p"}, None)


def test_merge_api_key_without_header_uses_default():
    spec, err = merge_auth_spec("api_key", None, token="k")
    assert err is None and spec == {"type": "api_key", "token": "k"}


def test_merge_invalid_returns_error_without_secret():
    spec, err = merge_auth_spec("api_key", None, token="SECRET-9", header="bad name")
    assert spec is None and "SECRET-9" not in err


# ---------- 2) 表单渲染：secret 一律不回显 ----------
def test_form_never_echoes_secret():
    srv = {"name": "a", "url": "https://a.example/mcp", "allowed_tools": "", "timeout": 15,
           "enabled": True, "auth": {"type": "bearer", "token": "TOK-SECRET"}}
    html = _mcp_server_form(0, srv, "编辑")
    assert "TOK-SECRET" not in html
    assert 'name="mcp_auth_token"' in html and 'type="password"' in html
    assert "留空保持原值" in html
    for label in ("无认证", "Bearer Token", "API Key", "自定义 Header", "Basic Auth"):
        assert label in html


def test_form_has_clear_switch_and_echoes_only_non_secret_fields():
    srv = {"name": "a", "url": "https://a.example/mcp",
           "auth": {"type": "basic", "username": "u", "password": "PWD-SECRET"}}
    html = _mcp_server_form(0, srv, "编辑")
    assert "PWD-SECRET" not in html
    assert "mcp_auth_clear" in html
    assert 'name="mcp_auth_username"' in html and 'value="u"' in html


def test_card_shows_auth_state_without_secret():
    html = _mcp_server_card(0, {"name": "a", "url": "https://a.example/mcp",
                                "auth": {"type": "api_key", "token": "K-SECRET"}})
    assert "api_key（已配置）" in html and "K-SECRET" not in html


def test_card_none_auth_label():
    html = _mcp_server_card(0, {"name": "a", "url": "https://a.example/mcp"})
    assert "认证：无认证" in html


# ---------- 3) 面板表单解析（留空保持 / 清除开关） ----------
def _panel_self():
    stub = SimpleNamespace()
    stub._form_flag = McpPanelMixin._form_flag          # 实例属性 → 不做方法绑定
    return stub


def test_panel_form_auth_keeps_secret_when_blank():
    servers = [{"name": "a", "auth": {"type": "bearer", "token": "OLD"}}]
    spec, err = McpPanelMixin._form_auth(_panel_self(), {"mcp_auth_type": "bearer", "mcp_auth_token": ""},
                                         0, servers)
    assert err is None and spec == {"type": "bearer", "token": "OLD"}


def test_panel_form_auth_new_value_wins():
    servers = [{"name": "a", "auth": {"type": "bearer", "token": "OLD"}}]
    spec, err = McpPanelMixin._form_auth(_panel_self(),
                                         {"mcp_auth_type": "bearer", "mcp_auth_token": "NEW"}, 0, servers)
    assert err is None and spec["token"] == "NEW"


def test_panel_form_auth_clear_switch():
    servers = [{"name": "a", "auth": {"type": "bearer", "token": "OLD"}}]
    spec, err = McpPanelMixin._form_auth(_panel_self(),
                                         {"mcp_auth_type": "none", "mcp_auth_clear": "1"}, 0, servers)
    assert err is None and spec is None


def test_panel_form_auth_new_server():
    spec, err = McpPanelMixin._form_auth(_panel_self(), {"mcp_auth_type": "bearer", "mcp_auth_token": "T"},
                                         None, [])
    assert err is None and spec == {"type": "bearer", "token": "T"}


# ---------- 4) Core API：认证状态可见、secret 不可见 ----------
class _Cfg:
    PLUGIN_DIR = "/tmp/mcp_auth_plugins"
    MCP_ENABLED = True
    MCP_SERVERS = json.dumps([
        {"name": "a", "url": "https://a.example/mcp", "auth": {"type": "bearer", "token": "TOK-SECRET"}},
        {"name": "b", "url": "https://b.example/mcp", "tools": "t1,t2"},
    ])
    MCP_SERVER_URL = ""
    MCP_TIMEOUT = 10
    MCP_ALLOWED_TOOLS = ""
    MCP_SERVER_NAME = "mcp"


class _Repo:
    def list_plugins(self):
        return []


def _run(mgr, action, payload):
    return asyncio.run(mgr._run_action("p", action, payload))


def test_core_api_exposes_auth_state_without_secret():
    mgr = PluginManager(config=_Cfg(), repository=_Repo())
    res = _run(mgr, "mcp_server", {})
    assert res["ok"] and len(res["servers"]) == 2
    assert res["servers"][0]["auth"] == {"type": "bearer", "configured": True}
    assert res["servers"][1]["auth"] == {"type": "none", "configured": False}
    assert "TOK-SECRET" not in json.dumps(res)


def test_core_api_rejects_invalid_auth_config():
    class Bad(_Cfg):
        MCP_SERVERS = json.dumps([{"name": "a", "url": "https://a.example/mcp",
                                   "auth": {"type": "oauth"}}])
    mgr = PluginManager(config=Bad(), repository=_Repo())
    res = _run(mgr, "mcp_server", {})
    assert not res["ok"] and "auth" in res["error"]


def test_core_api_accepts_legacy_tools_field():
    """历史字段 tools 仍等效于 allowed_tools（旧配置零迁移）。"""
    mgr = PluginManager(config=_Cfg(), repository=_Repo())
    res = _run(mgr, "mcp_tools", {})
    assert res["ok"]
    assert res["tools"][1]["allowed_tools"] == ["t1", "t2"]

