# MCP 认证升级：审计与设计（任务书 §一 / §二十四 第 1–2 步）

> 基线：`b2daf04`（v2.4.0）。本文只做只读审计与设计，不含实现。

## 一、现状审计

| 层 | 现状 | 与目标的差距 |
| :--- | :--- | :--- |
| 配置 | `MCP_ENABLED / SERVER_URL / SERVER_NAME / SERVERS / TIMEOUT / MAX_TOOL_CALLS / ALLOWED_TOOLS / ALLOWED_HOSTS / CIRCUIT_*`；`MCP_SERVERS` 每个元素支持 `name/url/allowed_tools/timeout/enabled` | **无任何认证字段** |
| 解析 | `config.parse_mcp_servers()` 纯函数，已有 fail-fast（缺 name/url、name 非法、timeout 非法都抛 ValueError） | 需在其中解析 `auth` 并保持同样的 fail-fast 风格 |
| 客户端 | `McpClient(url, name, timeout, allowed_hosts)`（156 行）；**所有 RPC 都走 `_rpc()`**，headers 只在 `_rpc` 内构造一次 | 认证注入有天然单点：`headers = self._auth.apply(headers)` |
| SSRF | 两道闸：构造时 `validate_mcp_server_url` + 每次请求前 `_check_dns`（DNS rebinding 防护）；`follow_redirects=False` | **本次不得改动** |
| ToolManager | `_build_servers()` 在 `:133` 创建 `McpClient`；有 `is_enabled / allow_tool / sync_tools / build_tools_payload / call_tool` | 需把 auth 传进 client，并暴露「无 secret 的认证状态」 |
| Core API | `mcp_server / mcp_tools / mcp_call / mcp_prompt / mcp_resource / mcp_status` 等 action | 补认证状态字段（不含 secret） |
| Python SDK | `plugin_sdk/flowerie_sdk/bot.py` 有 MCP facade（20 处命中） | 补认证状态 |
| TS / Go / Rust / Java SDK | **MCP 命中 0 处** | ★ 本任务最大工作量：四语言都要新增 MCP facade |
| WebUI | `webui_panels/mcp_panel.py`（153 行）+ `webui_render/config_panel.py` 的 MCP editor | 加认证字段（掩码、留空保持） |
| 测试 | `test_mcp / test_mcp_multi / test_mcp_quota / test_mcp_security / test_mcp_ssrf_dns` | 补认证、注入、多 server 隔离、secret 泄漏扫描、五语言 acceptance |
| 文档 | `docs/features/mcp.md` / `docs/guides/configuration.md` / `docs/reference/api.md` / `.env_example` | 补五种认证与示例 |

## 二、能力矩阵（目标）

| 能力 | 配置层 | 客户端 | Core API | Python SDK | TS | Go | Rust | Java | WebUI |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 无认证 | 已有（等价 none） | 已有 | 已有 | 已有 | 待加 | 待加 | 待加 | 待加 | 待加 |
| Bearer | 待加 | 待加 | 待加 | 待加 | 待加 | 待加 | 待加 | 待加 | 待加 |
| API Key（自定义 header 名） | 待加 | 待加 | 待加 | 待加 | 待加 | 待加 | 待加 | 待加 | 待加 |
| 自定义 Header | 待加 | 待加 | 待加 | 待加 | 待加 | 待加 | 待加 | 待加 | 待加 |
| Basic | 待加 | 待加 | 待加 | 待加 | 待加 | 待加 | 待加 | 待加 | 待加 |
| 认证状态查询（不含 secret） | — | — | 待加 | 待加 | 待加 | 待加 | 待加 | 待加 | 待加 |

## 三、设计

### 3.1 模块划分（新文件只有一个）

| 文件 | 动作 | 内容 |
| :--- | :--- | :--- |
| `src/services/mcp_auth.py` | **新增** | 认证抽象与 fail-fast 解析（不依赖 McpClient） |
| `src/config.py` | 改 | `parse_mcp_servers` 解析每个 server 的 `auth`；单 server 的 `MCP_AUTH_*` 组装 |
| `src/services/config_schema.py` | 改 | 新增 5 个单 server 兼容配置项（`MCP_AUTH_TYPE / TOKEN / HEADER / USERNAME / PASSWORD`） |
| `src/services/mcp_client.py` | 改 | `__init__` 接 `auth`（默认 `NoneAuth`）；`_rpc` 内 `headers = self._auth.apply(headers)` |
| `src/services/mcp_tool_manager.py` | 改 | 建 client 时传 auth；新增 `servers_view()`（名称/URL/超时/工具数/**auth 状态**，无 secret） |
| `src/plugins/manager.py` | 改 | MCP 相关 action 补 auth 状态字段 |
| `plugin_sdk` + `sdk/{typescript,go,rust,java}` | 改 | 五语言 MCP facade 对齐（servers / tools / call / auth status） |
| `webui_panels/mcp_panel.py` + `webui_render` | 改 | 认证方式下拉 + 对应字段；掩码；留空保持 |
| `docs/*` + `.env_example` | 改 | 五种认证示例与敏感凭据声明 |
| `tests/*` | 改/增 | 见 3.5 |

### 3.2 认证抽象（核心）

`~python
class McpAuthError(Exception): ...

class McpAuthStrategy(abc.ABC):
    type: str = "none"

    @abc.abstractmethod
    def apply(self, headers: Dict[str, str]) -> Dict[str, str]:
        """把认证注入 base headers，返回新 dict（不改原 dict）。"""

    def info(self) -> Dict[str, Any]:
        """对外的认证描述：只有 type / configured，**永远不含 secret**。"""
        return {"type": self.type, "configured": self._configured}

    def __repr__(self) -> str:
        return "<McpAuth %s configured=%s>" % (self.type, self._configured)

def build_auth(spec: Optional[dict]) -> McpAuthStrategy:
    """按 auth 配置构造策略（fail-fast：非法 type、缺字段、非法 header 一律抛 McpAuthError）。"""
`~

五种实现：`NoneAuth`（不加任何 header）/ `BearerAuth`（`Authorization: Bearer <token>`）/
`ApiKeyAuth`（自定义 header 名 + key）/ `HeaderAuth`（自定义 name + value）/
`BasicAuth`（`Authorization: Basic base64(user:pass)`）。
**OAuth 只留位置**（`type` 字段 + `info()` 的形态），本次不做半成品实现。

### 3.3 配置格式

多 server（`MCP_SERVERS` 每个元素内嵌）：

`~json
[
  {"name": "search", "url": "https://a.example/mcp"},
  {"name": "github", "url": "https://b.example/mcp",
   "auth": {"type": "bearer", "token": "..."}},
  {"name": "internal", "url": "https://c.example/mcp",
   "auth": {"type": "api_key", "header": "X-API-Key", "token": "..."}},
  {"name": "legacy-svc", "url": "https://d.example/mcp",
   "auth": {"type": "basic", "username": "u", "password": "p"}}
]
`~

单 server 兼容（`MCP_SERVER_URL` 走 legacy 分支时读这些）：

`~ini
MCP_AUTH_TYPE=            # none | bearer | api_key | header | basic（空 = 无认证）
MCP_AUTH_TOKEN=
MCP_AUTH_HEADER=          # api_key 的 header 名 / header 模式的 name
MCP_AUTH_USERNAME=
MCP_AUTH_PASSWORD=
`~

规则：`auth` 缺失或 `null` = 无认证；**旧配置零迁移**；非法 type / 缺必要字段**明确报错**（禁止静默降级为无认证）。

### 3.4 安全设计（本任务重点）

| 面 | 措施 |
| :--- | :--- |
| 日志 | `apply()` 只记 `type` 与 header 名；`__repr__` 脱敏；错误信息复用 `redact_url` 思路，**不含 token/password** |
| WebUI | 认证字段用 `type="password"`；编辑已有 server 时显示 `********` 占位；**留空 = 保持原 secret**，只有显式选择「清除」才删除 |
| URL | **不支持**把 secret 放 query；也不主动拼接 |
| Header 注入 | header name 匹配 `^[A-Za-z0-9-]+$`（禁 CR/LF/冒号/空格）；value 禁 CR/LF；越界即 `McpAuthError` |
| Authorization 冲突 | `apply()` 会覆盖 base headers 里的同名字段（认证层 > 普通 headers），并留 debug 日志；strategy 之间不可能互相冲突（一个策略只做一件事） |
| SDK | `info()` 只暴露 `type/configured`；插件任何 API 都拿不到 secret；读取/调用 ≠ 修改凭据（后者仍走 WebUI + 管理员） |
| 测试 | 断言日志与错误里不出现真值；断言发给测试 server 的 header 恰好是 `Authorization: Bearer test-token` |

### 3.5 测试计划

1. `tests/test_mcp_auth.py`（新增）：无认证 / Bearer / API Key / 自定义 Header / Basic / 非法 type / 缺 token / 缺 header / 非法 header 名 / CRLF 注入 / Authorization 冲突 / `info()` 不含 secret / `repr()` 脱敏；
2. RPC 覆盖：`initialize / tools/list / tools/call` 都带认证（用 fake transport 断言 headers）；
3. `tests/test_mcp_multi.py`：server A=Bearer、B=API Key、C=无认证，互不影响；
4. `tests/test_mcp_security.py` 扩展：日志与错误脱敏；
5. WebUI：新建 / 编辑 / 改普通字段保留 secret / 改 auth / 清除 secret / 切换 type / 非法配置；
6. `tests/sdk/*`：五语言 acceptance（list server / list tools / call tool / permission denied / auth configured / secret never exposed）。

### 3.6 分层不变

`~text
Config → McpServerConfig → McpAuthConfig → McpAuthStrategy → McpClient → McpToolManager → Core API → Plugin SDK
`~

OneBot / Plugin / WebUI / AIClient 都不直接处理 MCP authentication；
SSRF 两道闸与工具 allowlist 本次**一行不改**。

## 四、实施顺序（对应任务书 §二十四）

1. ✅ 审计（本文 §一/§二）；
2. ✅ 设计（本文 §三）；
3. `src/services/mcp_auth.py` + 单测；
4. 配置解析（`config.py` / `config_schema.py`）+ 单测；
5. `McpClient` 注入 + RPC 覆盖测试；
6. WebUI（面板 + render）+ 测试；
7. Core API 状态字段；
8. 五语言 SDK 同步（Python 补状态、TS/Go/Rust/Java 新增 facade）；
9. 单元测试补齐；
10. SDK acceptance；
11. 文档（含 `.env_example`）；
12. 完整测试；
13. 修回归；
14. secret 泄露扫描；
15. MCP authentication 架构审计 + 最终报告。

