"""MCP 认证配置层测试（任务书 §三/§四/§十六：fail-fast + 零迁移 + legacy 兼容）。"""
import pytest

from src.config import build_legacy_mcp_auth, parse_mcp_servers


def _get(values):
    return lambda key, default="": values.get(key, default)


# ---------- 1) 向后兼容：旧配置零迁移 ----------
def test_legacy_config_without_auth_parses_unchanged():
    raw = '[{"name": "search", "url": "https://a.example/mcp"}]'
    servers = parse_mcp_servers(raw)
    assert len(servers) == 1
    assert servers[0]["name"] == "search"
    assert servers[0]["auth"] is None              # 无 auth = 无认证
    # 其余字段与旧版逐字一致
    assert servers[0]["allowed_tools"] == ""
    assert servers[0]["timeout"] == 15
    assert servers[0]["enabled"] is True


def test_auth_null_equals_no_auth():
    raw = '[{"name": "a", "url": "https://a.example/mcp", "auth": null}]'
    assert parse_mcp_servers(raw)[0]["auth"] is None


def test_auth_type_none_accepted():
    raw = '[{"name": "a", "url": "https://a.example/mcp", "auth": {"type": "none"}}]'
    assert parse_mcp_servers(raw)[0]["auth"] == {"type": "none"}


# ---------- 2) 五种认证都能解析 ----------
@pytest.mark.parametrize("auth", [
    {"type": "bearer", "token": "t"},
    {"type": "api_key", "header": "X-API-Key", "token": "k"},
    {"type": "api_key", "token": "k"},
    {"type": "header", "name": "X-Auth", "value": "v"},
    {"type": "basic", "username": "u", "password": "p"},
])
def test_supported_auth_types_parse(auth):
    raw = '[{"name": "a", "url": "https://a.example/mcp", "auth": %s}]' % __import__("json").dumps(auth)
    assert parse_mcp_servers(raw)[0]["auth"] == auth


# ---------- 3) fail-fast：非法 auth 明确报错，且不静默降级 ----------
@pytest.mark.parametrize("auth", [
    {"type": "oauth"},                       # 未支持的 type
    {"type": "bearer"},                      # 缺 token
    {"type": "api_key"},                     # 缺 token
    {"type": "header", "name": "X-A"},       # 缺 value
    {"type": "basic"},                       # 缺 username
    {"type": "api_key", "header": "bad name", "token": "k"},   # 非法 header 名
])
def test_invalid_auth_fails_fast(auth):
    raw = '[{"name": "a", "url": "https://a.example/mcp", "auth": %s}]' % __import__("json").dumps(auth)
    with pytest.raises(ValueError) as e:
        parse_mcp_servers(raw)
    assert "auth" in str(e.value)


def test_auth_must_be_object():
    raw = '[{"name": "a", "url": "https://a.example/mcp", "auth": "bearer"}]'
    with pytest.raises(ValueError):
        parse_mcp_servers(raw)


def test_error_message_never_contains_secret():
    raw = ('[{"name": "a", "url": "https://a.example/mcp", '
           '"auth": {"type": "nope", "token": "SECRET-TOKEN-42"}}]')
    with pytest.raises(ValueError) as e:
        parse_mcp_servers(raw)
    assert "SECRET-TOKEN-42" not in str(e.value)


# ---------- 4) 多 server：各自认证互不影响 ----------
def test_multi_server_independent_auth():
    raw = ('[{"name": "A", "url": "https://a.example/mcp", "auth": {"type": "bearer", "token": "ta"}},'
           ' {"name": "B", "url": "https://b.example/mcp", "auth": {"type": "api_key", "token": "kb"}},'
           ' {"name": "C", "url": "https://c.example/mcp"}]')
    a, b, c = parse_mcp_servers(raw)
    assert a["auth"]["type"] == "bearer" and a["auth"]["token"] == "ta"
    assert b["auth"]["type"] == "api_key" and b["auth"]["token"] == "kb"
    assert c["auth"] is None


# ---------- 5) legacy 单 server：MCP_AUTH_* 组装 ----------
def test_build_legacy_mcp_auth_empty_means_none():
    assert build_legacy_mcp_auth(_get({})) is None
    assert build_legacy_mcp_auth(_get({"MCP_AUTH_TYPE": ""})) is None
    assert build_legacy_mcp_auth(_get({"MCP_AUTH_TYPE": "none"})) is None


@pytest.mark.parametrize("values,expected", [
    ({"MCP_AUTH_TYPE": "bearer", "MCP_AUTH_TOKEN": "t"}, {"type": "bearer", "token": "t"}),
    ({"MCP_AUTH_TYPE": "api_key", "MCP_AUTH_TOKEN": "k", "MCP_AUTH_HEADER": "X-K"},
     {"type": "api_key", "token": "k", "header": "X-K"}),
    ({"MCP_AUTH_TYPE": "header", "MCP_AUTH_HEADER": "X-A", "MCP_AUTH_TOKEN": "v"},
     {"type": "header", "header": "X-A", "token": "v"}),
    ({"MCP_AUTH_TYPE": "basic", "MCP_AUTH_USERNAME": "u", "MCP_AUTH_PASSWORD": "p"},
     {"type": "basic", "username": "u", "password": "p"}),
])
def test_build_legacy_mcp_auth_variants(values, expected):
    assert build_legacy_mcp_auth(_get(values)) == expected


def test_legacy_single_server_carries_auth():
    servers = parse_mcp_servers("", legacy_url="https://a.example/mcp",
                                legacy_auth={"type": "bearer", "token": "t"})
    assert servers[0]["auth"] == {"type": "bearer", "token": "t"}


def test_legacy_single_server_invalid_auth_fails_fast():
    with pytest.raises(ValueError):
        parse_mcp_servers("", legacy_url="https://a.example/mcp", legacy_auth={"type": "bearer"})

