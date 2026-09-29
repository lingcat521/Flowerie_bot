"""MCP 认证抽象测试（任务书 §十四 的客户端部分 + §五 安全要求）。

覆盖：无认证 / Bearer / API Key / 自定义 Header / Basic / 非法 type / 缺字段 /
非法 header 名 / CRLF 注入 / 协议头保护 / Authorization 覆盖 / info 不含 secret /
repr 脱敏 / apply 不改原 dict。
"""
import base64
import json

import pytest

from src.services.mcp_auth import (
    DEFAULT_API_KEY_HEADER,
    ApiKeyAuth,
    BasicAuth,
    BearerAuth,
    HeaderAuth,
    McpAuthError,
    NoneAuth,
    build_auth,
)

BASE = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


# ---------- 1) 无认证：三种等价写法 ----------
@pytest.mark.parametrize("spec", [None, {}, {"type": "none"}, {"type": ""}])
def test_none_auth_variants(spec):
    auth = build_auth(spec)
    assert isinstance(auth, NoneAuth)
    assert auth.apply(BASE) == BASE
    assert auth.info() == {"type": "none", "configured": False}


# ---------- 2) Bearer ----------
def test_bearer_injects_authorization():
    auth = build_auth({"type": "bearer", "token": "tok-123"})
    out = auth.apply(BASE)
    assert out["Authorization"] == "Bearer tok-123"
    assert out["Content-Type"] == "application/json"      # 其余 header 保留
    assert auth.info() == {"type": "bearer", "configured": True}


# ---------- 3) API Key：默认 header 名 + 自定义 ----------
def test_api_key_default_and_custom_header():
    default = build_auth({"type": "api_key", "token": "k-1"})
    assert default.apply(BASE)[DEFAULT_API_KEY_HEADER] == "k-1"
    assert default.info()["header"] == DEFAULT_API_KEY_HEADER

    custom = build_auth({"type": "api_key", "header": "X-Token", "token": "k-2"})
    assert custom.apply(BASE)["X-Token"] == "k-2"
    assert "X-API-Key" not in custom.apply(BASE)


# ---------- 4) 自定义 Header ----------
def test_custom_header_auth():
    auth = build_auth({"type": "header", "name": "X-Auth", "value": "v-1"})
    assert auth.apply(BASE)["X-Auth"] == "v-1"
    assert auth.info()["header"] == "X-Auth"


# ---------- 5) Basic：base64 正确 ----------
def test_basic_auth_encoding():
    auth = build_auth({"type": "basic", "username": "u", "password": "p"})
    expected = "Basic " + base64.b64encode(b"u:p").decode()
    assert auth.apply(BASE)["Authorization"] == expected
    assert auth.info() == {"type": "basic", "configured": True, "username": "u"}


def test_basic_auth_empty_password_allowed():
    auth = BasicAuth("u", "")
    assert auth.apply(BASE)["Authorization"].startswith("Basic ")


# ---------- 6) fail-fast：非法 type 不降级 ----------
def test_unknown_auth_type_raises():
    with pytest.raises(McpAuthError) as e:
        build_auth({"type": "oauth"})
    assert "不支持的 auth type" in str(e.value)


# ---------- 7) fail-fast：缺必要字段 ----------
@pytest.mark.parametrize("spec", [
    {"type": "bearer"},
    {"type": "bearer", "token": "   "},
    {"type": "api_key"},
    {"type": "header", "value": "v"},
    {"type": "header", "name": "X-A"},
    {"type": "basic"},
    {"type": "basic", "username": "  "},
])
def test_missing_required_fields_raise(spec):
    with pytest.raises(McpAuthError):
        build_auth(spec)


def test_auth_must_be_object():
    with pytest.raises(McpAuthError):
        build_auth("bearer")


# ---------- 8) 非法 header 名 ----------
@pytest.mark.parametrize("name", ["bad name", "X-A: b", "X-A\r\nEvil", "", "-x", "☃"])
def test_invalid_header_name_rejected(name):
    with pytest.raises(McpAuthError):
        build_auth({"type": "api_key", "header": name, "token": "k"})


# ---------- 9) 协议头保护（不允许被认证配置覆盖） ----------
@pytest.mark.parametrize("name", ["Content-Type", "Accept", "Host", "Content-Length", "mcp-session-id"])
def test_protocol_headers_protected(name):
    with pytest.raises(McpAuthError):
        build_auth({"type": "api_key", "header": name, "token": "k"})


# ---------- 10) CRLF / 注入防护 ----------
@pytest.mark.parametrize("token", ["a\r\nX-Evil: 1", "a\nX-Evil: 1", "a\rb", "a\x00b", "   "])
def test_header_injection_rejected(token):
    with pytest.raises(McpAuthError):
        build_auth({"type": "bearer", "token": token})


def test_basic_username_rejects_colon_and_crlf():
    for user in ("a:b", "a\r\nb", "a\nb"):
        with pytest.raises(McpAuthError):
            build_auth({"type": "basic", "username": user, "password": "p"})


# ---------- 11) Authorization 覆盖规则：认证层 > 普通 headers ----------
def test_auth_layer_overrides_existing_authorization():
    auth = build_auth({"type": "bearer", "token": "new"})
    out = auth.apply(dict(BASE, Authorization="Bearer old"))
    assert out["Authorization"] == "Bearer new"


# ---------- 12) info() / repr() / str() 绝不泄漏 secret ----------
def test_info_and_repr_never_expose_secret():
    secrets = ["TOK-SECRET-1", "KEY-SECRET-2", "PWD-SECRET-3", "HDR-SECRET-4"]
    specs = [
        {"type": "bearer", "token": secrets[0]},
        {"type": "api_key", "token": secrets[1]},
        {"type": "basic", "username": "u", "password": secrets[2]},
        {"type": "header", "name": "X-Secret", "value": secrets[3]},
    ]
    for spec in specs:
        auth = build_auth(spec)
        blob = json.dumps(auth.info(), ensure_ascii=False) + repr(auth) + str(auth)
        for secret in secrets:
            assert secret not in blob, (spec, secret)


# ---------- 13) apply 不修改传入的 dict ----------
def test_apply_does_not_mutate_input():
    base = dict(BASE)
    build_auth({"type": "bearer", "token": "t"}).apply(base)
    build_auth({"type": "api_key", "token": "k"}).apply(base)
    build_auth({"type": "basic", "username": "u", "password": "p"}).apply(base)
    assert base == BASE


# ---------- 14) 各策略的 type 常量 ----------
def test_strategy_types():
    assert BearerAuth("t").type == "bearer"
    assert ApiKeyAuth("X-K", "k").type == "api_key"
    assert HeaderAuth("X-H", "v").type == "header"
    assert BasicAuth("u", "p").type == "basic"
    assert NoneAuth().configured is False
    for auth in (BearerAuth("t"), ApiKeyAuth("X-K", "k"), HeaderAuth("X-H", "v"), BasicAuth("u", "p")):
        assert auth.configured is True

