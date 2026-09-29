"""MCP facade（bot.mcp）：插件只与抽象后的 MCP server / tool 打交道。

安全边界（任务书 §九 / §十一 / §十二）：

- 认证只以 type + configured 的形式暴露，**永远不含 token / password / secret**；
  引擎侧（Core API）也只返回这两个字段，本层再做一次白名单式提取；
- 插件**不得**读取或修改 MCP 认证凭据 —— 凭据由管理员在 WebUI 配置，插件只能用；
- 所有调用都经引擎的权限判定与工具白名单，本层不做任何绕过，也不直连 MCP server。

不抛异常：任何失败都折叠成 ok=False 的结果对象（与 SDK 其它动作接口一致）。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class McpAuthInfo:
    """MCP server 的认证状态（**不含任何密钥**）。"""

    type: str = "none"
    configured: bool = False

    @property
    def status(self) -> str:
        """语义化状态：none / configured / error。

        authenticated 属于运行期结论（需要真的连一次），由 bot.mcp.status(server)
        返回的 status 字段给出，这里不猜。
        """
        if self.type in ("", "none"):
            return "none"
        return "configured" if self.configured else "error"

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "configured": self.configured, "status": self.status}


@dataclass
class McpServer:
    """一个 MCP server 的公开视图。"""

    name: str = ""
    url: str = ""
    auth: McpAuthInfo = field(default_factory=McpAuthInfo)


@dataclass
class McpTool:
    """某个 server 允许插件调用的工具白名单（空列表 = 放行全部）。"""

    server: str = ""
    allowed_tools: List[str] = field(default_factory=list)


@dataclass
class McpCallResult:
    """工具调用结果（ok=False 时 error 为人类可读原因，不含密钥）。"""

    ok: bool = False
    result: Any = None
    error: str = ""


class McpFacade:
    """bot.mcp：列 server / 查工具白名单 / 查认证状态 / 调用工具。"""

    def __init__(self, api: Any) -> None:
        self._api = api

    # ---------- 内部：统一的动作调用与容错 ----------
    def _call(self, method: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if self._api is None:
            return {"ok": False, "error": "SDK 未接线（无 API 通道）"}
        fn = getattr(self._api, method, None)
        if fn is None:
            return {"ok": False, "error": "引擎不支持 %s" % method}
        try:
            out = fn(payload or {})
        except Exception as exc:  # noqa: BLE001 - 引擎/传输异常折叠成结果，不抛给插件
            return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
        return out if isinstance(out, dict) else {"ok": False, "error": "引擎返回非法结构"}

    @staticmethod
    def _auth_info(raw: Any) -> McpAuthInfo:
        data = raw if isinstance(raw, dict) else {}
        return McpAuthInfo(type=str(data.get("type") or "none"),
                           configured=bool(data.get("configured")))

    # ---------- 公开 API ----------
    def servers(self) -> List[McpServer]:
        """已配置的 MCP server 列表（含认证状态，不含密钥）。"""
        out = self._call("mcp_server")
        rows = out.get("servers") if out.get("ok") else None
        result: List[McpServer] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            result.append(McpServer(name=str(row.get("name") or ""),
                                    url=str(row.get("url") or ""),
                                    auth=self._auth_info(row.get("auth"))))
        return result

    def tools(self, server: str = "") -> List[McpTool]:
        """各 server 的工具白名单（留空 = 放行全部）。"""
        out = self._call("mcp_tools")
        rows = out.get("tools") if out.get("ok") else None
        result: List[McpTool] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            if server and str(row.get("server") or "") != server:
                continue
            allowed = row.get("allowed_tools")
            result.append(McpTool(server=str(row.get("server") or ""),
                                  allowed_tools=[str(t) for t in (allowed or [])]))
        return result

    def call(self, server: str, tool: str, arguments: Optional[Dict[str, Any]] = None) -> McpCallResult:
        """调用工具（经引擎权限 + 白名单；失败不抛异常）。"""
        out = self._call("mcp_call", {"server": server, "tool": tool,
                                      "arguments": arguments or {}})
        if out.get("ok"):
            return McpCallResult(ok=True, result=out.get("result", out.get("data", out.get("content"))))
        return McpCallResult(ok=False, error=str(out.get("error") or "调用失败"))

    def status(self, server: str) -> Dict[str, Any]:
        """连通性 + 认证状态（只读；不修改任何凭据）。"""
        return self._call("mcp_status", {"server": server})

    def auth(self, server: str) -> McpAuthInfo:
        """某个 server 的认证状态（不发起连接、不含密钥）。"""
        for item in self.servers():
            if item.name == server:
                return item.auth
        return McpAuthInfo()

