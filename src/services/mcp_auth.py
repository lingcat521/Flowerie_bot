"""MCP server 认证抽象（None / Bearer / API Key / 自定义 Header / Basic）。

设计约束（任务书 §二 / §五 / §七 / §二十一）：

- **策略与客户端解耦**：McpClient 只持有一个 auth 对象，发请求前调用 apply(headers)；
  五种认证各自一个类，调用方不写 if/elif；将来加 OAuth 只需再加一个类。
- **secret 不出策略**：info() 只返回 {type, configured(, header)}，__repr__ 脱敏 ——
  日志、Core API、插件 SDK 都拿不到 token/password。
- **fail-fast 解析**：非法 type、缺必要字段、非法 header 名/值一律抛 McpAuthError，
  绝不静默降级为无认证。
- **注入防护**：header 名限定字母/数字/连字符/下划线，且不允许覆盖协议头；
  header 值禁止 CR/LF/NUL（防 Header Injection）。
"""
import abc
import base64
import re
from typing import Any, Dict, Optional

#: header 名白名单（RFC 7230 token 的保守子集）
_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_]*$")
#: 不允许被认证配置覆盖的协议头（Content-Type/Accept 由客户端按 MCP 协议设置）
_FORBIDDEN_HEADERS = frozenset({"content-type", "accept", "content-length", "host",
                                "mcp-session-id"})
#: api_key 认证未指定 header 名时的默认值（常见约定）
DEFAULT_API_KEY_HEADER = "X-API-Key"

AUTH_TYPES = ("none", "bearer", "api_key", "header", "basic")


class McpAuthError(ValueError):
    """认证配置非法（fail-fast；错误信息不含 secret）。"""


def _clean_header_name(name: Any) -> str:
    text = str(name if name is not None else "").strip()
    if not text or not _HEADER_NAME_RE.fullmatch(text):
        raise McpAuthError("认证 header 名非法（只允许字母/数字/连字符/下划线，且以字母或数字开头）")
    if text.lower() in _FORBIDDEN_HEADERS:
        raise McpAuthError("认证 header 名不允许覆盖协议头: %s" % text)
    return text


def _clean_header_value(value: Any) -> str:
    text = str(value if value is not None else "")
    if not text.strip():
        raise McpAuthError("认证 header 值不能为空")
    if any(ch in text for ch in ("\r", "\n", "\0")):
        raise McpAuthError("认证 header 值含非法字符（CR/LF/NUL）")
    return text


class McpAuthStrategy(abc.ABC):
    """认证策略基类：apply() 注入 header，info() 对外描述（不含 secret）。"""

    type = "none"

    def __init__(self) -> None:
        self._configured = False

    @abc.abstractmethod
    def apply(self, headers: Dict[str, str]) -> Dict[str, str]:
        """返回注入认证后的**新** headers（不修改传入的 dict）。"""

    @property
    def configured(self) -> bool:
        return bool(self._configured)

    def info(self) -> Dict[str, Any]:
        """对外的认证描述（供 Core API / 插件 SDK）：只有 type 与 configured。"""
        return {"type": self.type, "configured": self.configured}

    def __repr__(self) -> str:
        # 只暴露类型与是否配置，绝不包含 token/password（日志里打印对象也安全）
        return "<McpAuth %s configured=%s>" % (self.type, self.configured)

    __str__ = __repr__


class NoneAuth(McpAuthStrategy):
    """无认证：原样返回 headers。"""

    type = "none"

    def apply(self, headers: Dict[str, str]) -> Dict[str, str]:
        return dict(headers)


class BearerAuth(McpAuthStrategy):
    """Authorization: Bearer <token>。"""

    type = "bearer"

    def __init__(self, token: Any) -> None:
        super().__init__()
        self._token = _clean_header_value(token)
        self._configured = True

    def apply(self, headers: Dict[str, str]) -> Dict[str, str]:
        out = dict(headers)
        out["Authorization"] = "Bearer " + self._token      # 认证层覆盖普通 headers
        return out


class ApiKeyAuth(McpAuthStrategy):
    """自定义 header 里放 API key（默认 X-API-Key）。"""

    type = "api_key"

    def __init__(self, header: Any, token: Any) -> None:
        super().__init__()
        # 只有 None（完全没给）才用默认名；空串/非法值走 _clean_header_name 报错
        self._header = _clean_header_name(DEFAULT_API_KEY_HEADER if header is None else header)
        self._token = _clean_header_value(token)
        self._configured = True

    def info(self) -> Dict[str, Any]:
        # header 名不含 secret，可以对外（便于 WebUI 展示"Key 放在哪个头"）
        out = super().info()
        out["header"] = self._header
        return out

    def apply(self, headers: Dict[str, str]) -> Dict[str, str]:
        out = dict(headers)
        out[self._header] = self._token
        return out


class HeaderAuth(McpAuthStrategy):
    """任意自定义 header：name + value 都由配置指定。"""

    type = "header"

    def __init__(self, name: Any, value: Any) -> None:
        super().__init__()
        self._name = _clean_header_name(name)
        self._value = _clean_header_value(value)
        self._configured = True

    def info(self) -> Dict[str, Any]:
        out = super().info()
        out["header"] = self._name
        return out

    def apply(self, headers: Dict[str, str]) -> Dict[str, str]:
        out = dict(headers)
        out[self._name] = self._value
        return out


class BasicAuth(McpAuthStrategy):
    """Authorization: Basic base64(username:password)（password 允许为空）。"""

    type = "basic"

    def __init__(self, username: Any, password: Any = "") -> None:
        super().__init__()
        user = str(username if username is not None else "").strip()
        if not user:
            raise McpAuthError("basic 认证缺少 username")
        pwd = str(password if password is not None else "")
        if any(ch in user for ch in ("\r", "\n", "\0", ":")):
            raise McpAuthError("basic 认证的 username 含非法字符（CR/LF/NUL/冒号）")
        if any(ch in pwd for ch in ("\r", "\n", "\0")):
            raise McpAuthError("basic 认证的 password 含非法字符（CR/LF/NUL）")
        self._user = user
        self._credential = base64.b64encode(("%s:%s" % (user, pwd)).encode("utf-8")).decode("ascii")
        self._configured = True

    def info(self) -> Dict[str, Any]:
        out = super().info()
        out["username"] = self._user          # 用户名不算 secret；password 绝不出现
        return out

    def apply(self, headers: Dict[str, str]) -> Dict[str, str]:
        out = dict(headers)
        out["Authorization"] = "Basic " + self._credential
        return out


def build_auth(spec: Optional[dict]) -> McpAuthStrategy:
    """按配置构造认证策略（fail-fast）。

    - spec 为 None / 空 dict / {"type": "none"} → NoneAuth（旧配置的等价形态）；
    - type 缺失按 none 处理（但显式给了非 none 的 type 就必须字段齐全）；
    - 非法 type、缺 token/username/name/value、非法 header 名/值 → McpAuthError。
    """
    if spec is None:
        return NoneAuth()
    if not isinstance(spec, dict):
        raise McpAuthError("auth 必须是对象")
    auth_type = str(spec.get("type") or "none").strip().lower()
    if auth_type in ("", "none"):
        return NoneAuth()
    if auth_type == "bearer":
        if not str(spec.get("token") or "").strip():
            raise McpAuthError("bearer 认证缺少 token")
        return BearerAuth(spec.get("token"))
    if auth_type == "api_key":
        if not str(spec.get("token") or "").strip():
            raise McpAuthError("api_key 认证缺少 token")
        # header 缺失才用默认名；显式给了空串/非法值一律报错（fail-fast，不静默兜底）
        header = spec.get("header")
        if header is None:
            header = DEFAULT_API_KEY_HEADER
        return ApiKeyAuth(header, spec.get("token"))
    if auth_type == "header":
        if not str(spec.get("name") or "").strip():
            raise McpAuthError("header 认证缺少 name")
        if not str(spec.get("value") or "").strip():
            raise McpAuthError("header 认证缺少 value")
        return HeaderAuth(spec.get("name"), spec.get("value"))
    if auth_type == "basic":
        if not str(spec.get("username") or "").strip():
            raise McpAuthError("basic 认证缺少 username")
        return BasicAuth(spec.get("username"), spec.get("password"))
    raise McpAuthError("不支持的 auth type: %r（可选: %s）" % (auth_type, "/".join(AUTH_TYPES)))

