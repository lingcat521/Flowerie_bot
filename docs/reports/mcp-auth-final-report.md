# MCP 认证能力升级 · 最终报告

> 任务书：`mcp_update.txt`（§二十四 15 步流程）· 基线 `b2daf04` · 交付 `ff2d395`
> 覆盖链路：Config → McpAuthConfig → McpAuthStrategy → McpClient → McpToolManager → Core API → 五语言 Plugin SDK → WebUI → 测试/文档

## 1. 改了哪些文件

40 个文件、+2862 / −34 行（不含本报告）。新增 10 个、修改 30 个：

| 层 | 文件 | 变化 |
| :--- | :--- | :--- |
| 认证抽象（新） | `src/services/mcp_auth.py` | +270（策略 + 校验 + 脱敏） |
| 配置 | `src/config.py` · `src/services/config_schema.py` · `.env_example` | +48 / +6 / +16 |
| 客户端 | `src/services/mcp_client.py` · `src/services/mcp_tool_manager.py` | +13 / +25 |
| Core 与 WebUI | `src/plugins/manager.py` · `webui_panels/mcp_panel.py` · `webui_render/config_panel.py` | +56 / +28 / +59 |
| Python SDK | `plugin_sdk/flowerie_sdk/mcp.py`（新）· `bot.py` · `__init__.py` | +136 / +10 / +7 |
| TypeScript SDK | `sdk/typescript/flowerie_sdk.ts` | +107 |
| Go SDK | `sdk/go/flowerie/plugin.go` | +148 |
| Rust SDK | `sdk/rust/src/lib.rs` | +159 |
| Java SDK | `sdk/java/.../FloweriePlugin.java` | +149 |
| 五语言示例 | `examples/{python,typescript,go,rust,java}-plugin/...` | +32 / +30 / +44 / +55 / +42 |
| 测试 | 7 个新文件 + `tests/test_plugin_sdk_contract.py`（+18） | +1164 |
| 自检脚本 | `scripts/check_imports.py` | +62（I001 两条规则） |
| 文档 | `docs/features/mcp.md` · `guides/configuration.md` · `reference/{api,sdk}.md` · `plugins/plugin-sdk{,-typescript,-go,-java}.md` · `plugin-developer-guide.md` · `reports/mcp-auth-design.md`（新） | +208 |

## 2. 新增 API

| 位置 | API | 说明 |
| :--- | :--- | :--- |
| `src/services/mcp_auth.py` | `McpAuthStrategy`（ABC）· `NoneAuth` / `BearerAuth` / `ApiKeyAuth` / `HeaderAuth` / `BasicAuth` | `apply(headers)` 唯一注入点 + `info()` 只回 type/configured；`__repr__` 脱敏 |
| 同上 | `build_auth(spec)` · `AUTH_TYPES` · `DEFAULT_API_KEY_HEADER` · `McpAuthError` | 解析 fail-fast，未知 type 直接报错（不静默降级） |
| 同上 | `merge_auth_spec(type, previous, *, token, header, username, password, clear)` | WebUI 编辑语义：留空 = 保留旧 secret，显式 clear 才删 |
| `src/config.py` | `build_legacy_mcp_auth(get)` · `_checked_auth_spec(spec, where)` | 单 server 环境变量兼容 + 每个 server 的 `auth` 字段 |
| `src/services/mcp_client.py` | `McpClient(..., auth=)` · `auth_info()` | 认证对象与传输解耦；`_rpc` 里 `headers = self._auth.apply(headers)` |
| `src/services/mcp_tool_manager.py` | `servers_view()` | 运行态视图，认证只出 type/configured |
| `src/plugins/manager.py` | `_public_mcp_auth(spec)` | 插件面动作的认证状态（白名单式提取） |
| WebUI | `_form_auth` · `_mcp_auth_options_html` · `_mcp_auth_label` | 认证下拉 + 字段渲染，零 JS |

## 3. 新增 SDK 能力（五语言逐个）

| 语言 | 入口 | 方法 | 类型 |
| :--- | :--- | :--- | :--- |
| Python | `bot.mcp`（`@property`，`bot.py:488`） | `servers()` · `tools(server="")` · `call(server, tool, args)` · `status(server)` · `auth(server)` | `McpAuthInfo` / `McpServer` / `McpTool` / `McpCallResult`（dataclass + `to_dict()`，`flowerie_sdk/mcp.py`，136 行） |
| TypeScript | `ctx.mcp`（PluginContext getter `:420`）· `client.mcp`（`:554`） | `servers()/tools()/call()/status()/auth()` | `McpAuthInfo` `:296` · `McpServer` `:304` · `McpTool` `:307` · `McpCallResult` `:310` |
| Go | `ctx.MCP()`（`plugin.go:1587`） | `Servers()` `:1611` · `Tools(server)` `:1631` · `Call(server, tool, args)` `:1661` · `Status(server)` `:1684` · `Auth(server)` `:1689` | `McpAuthInfo` `:1560` / `McpServer` `:1567` / `McpTool` `:1574` / `McpCallResult` `:1580` |
| Rust | `ctx.mcp()`（`lib.rs:1416`） | `servers()` `:1428` · `tools()` `:1444` · `call()` `:1469` · `status()` `:1493` · `auth()` `:1498` | `McpAuthInfo` `:1363` / `McpServer` `:1373` / `McpTool` `:1381` / `McpCallResult` `:1388` |
| Java | `ctx.mcp()`（`FloweriePlugin.java:385`） | `servers()` `:1195` · `tools(server)` `:1209` · `call(server, tool, args)` `:1233` · `status(server)` `:1246` · `auth(server)` `:1251` | `McpAuthInfo` `:1124` / `McpServer` `:1146` / `McpTool` `:1159` / `McpCallResult` `:1170` |

五语言语义一致：认证状态只有 `none` / `configured` / `error`（运行期 `authenticated` 由 `mcp_status` 给出），**任何语言都拿不到 token / password**；业务失败折叠进 `McpCallResult`，不抛异常。

## 4. 支持哪些认证

| `auth.type` | 字段 | 注入 | 备注 |
| :--- | :--- | :--- | :--- |
| （省略 / `null` / `none`） | — | 不注入 | 旧配置零迁移 |
| `bearer` | `token` | `Authorization: Bearer <token>` | |
| `api_key` | `token`，`header` 可选 | `<header>: <token>` | 缺省 `X-API-Key` |
| `header` | `name`、`value` | `<name>: <value>` | 自定义头，过 CRLF/保留头校验 |
| `basic` | `username`、`password` | `Authorization: Basic base64(user:pass)` | |

单 server 环境变量兼容（`MCP_SERVERS` 为空时生效）：`MCP_AUTH_TYPE` / `MCP_AUTH_TOKEN` / `MCP_AUTH_HEADER` / `MCP_AUTH_USERNAME` / `MCP_AUTH_PASSWORD`；同时配了 `MCP_SERVERS` 就以它为准，不产生重复配置。OAuth **只预留**：不在 `AUTH_TYPES` 里，写了直接 fail-fast，不做半成品。

## 5. 配置格式

```ini
MCP_SERVERS=[
  {"name":"search","url":"https://mcp.example.com/mcp","allowed_tools":"web_search","auth":{"type":"bearer","token":"sk-xxx"}},
  {"name":"local","url":"http://192.168.1.10:9000/mcp","auth":{"type":"api_key","header":"X-API-Key","token":"sk-xxx"}},
  {"name":"custom","url":"https://mcp.example.com/mcp","auth":{"type":"header","name":"X-Custom-Auth","value":"sk-xxx"}},
  {"name":"legacy_basic","url":"https://mcp.example.com/mcp","auth":{"type":"basic","username":"u","password":"p"}},
  {"name":"open","url":"https://mcp.example.com/mcp"}
]
```

fail-fast 覆盖：未知 type、缺必填字段、header 名不合法（限 `[A-Za-z0-9][A-Za-z0-9\-_]*`）、header 值含 CR/LF/NUL、协议保留头（`Content-Type` / `Accept` / `Content-Length` / `Host` / `Mcp-Session-Id`）——启动即报错，错误文案给出元素名与原因。

## 6. WebUI 变化

「MCP 工具」页的 server 表单里新增认证配置：**认证方式下拉**（无认证 / Bearer / API Key / 自定义 Header / Basic）+ 随方式显隐的字段；secret 输入框 `type=password`，已有值时显示 `********（留空保持原值）`，另给「清除认证」勾选；改普通字段（url/timeout/白名单）不会覆盖已存 secret。沿用既有 config schema + render，**零 JS** 可用。

## 7. 安全措施

1. **secret 不出现在**日志、错误信息、URL、插件 SDK 返回值里（有专门用例断言服务端/返回值中查不到真值）；
2. 认证状态对外只有 `type` / `configured`（`info()` 白名单式提取，SDK 再提取一次）；
3. **掩码与留空语义**：WebUI 不回显真值，留空 = 保持原值，显式 clear 才删除；
4. **Header Injection 校验**：自定义 header 名/值都校验，值拒绝 CR/LF/NUL；
5. **保留头禁止**：不允许覆盖 `Content-Type` / `Accept` / `Content-Length` / `Host` / `Mcp-Session-Id`；
6. **Authorization 冲突规则**：认证层 > 普通 headers（认证层最后写入）；
7. **注入点唯一**：`McpClient._rpc` 一处 `headers = self._auth.apply(headers)`，initialize / tools/list / tools/call / session 后续请求全覆盖，单测钉死；
8. **配置解析一次**：认证策略在 server 初始化时构造，请求期只做轻量注入（不重复解析/读库/读 env）；
9. **SSRF 与权限一个都没放松**：URL 仍过 `validate_config` + `McpClient` 双重校验（回环要操作员白名单），`mcp_*` 仍要 `http_request` 权限；
10. **插件改不了凭据**：插件的 MCP 动作是「读取与调用」，没有写认证配置的 API，也读不到 `settings.db`。

## 8. 测试数量

新增 **130** 条用例（全部通过）：

| 文件 | 条数 | 覆盖 |
| :--- | :--- | :--- |
| `tests/test_mcp_auth.py` | 39 | 五种策略、非法 type/缺字段/非法 header/CRLF 注入、`merge_auth_spec`、脱敏 `repr` |
| `tests/test_mcp_config_auth.py` | 24 | 每 server auth 解析、fail-fast、legacy env 组装、旧 `tools` 别名 |
| `tests/test_mcp_client_auth.py` | 11 | 三个 RPC + session 后续请求都带认证、各方式注入到正确 header |
| `tests/test_mcp_auth_webui.py` | 18 | 新建/编辑/改普通字段/切 type/留空保留/清除/非法配置 |
| `tests/test_sdk_mcp.py` | 10 | Python facade 语义、白名单提取、不抛异常 |
| `tests/test_mcp_auth_e2e.py` | 8 | 真 socket + 真 Core 动作路径（五种认证的真实请求头、401、白名单、SSRF、权限） |
| `tests/test_mcp_auth_multilang.py` | 20 | 五语言真插件进程 × 4（list server / list tools+auth / call tool / 权限拒绝） |

## 9. 测试结果

- 本机（真 pydantic 2.12.5 + 真 httpx 0.28.1）：MCP/SDK 族 `192 passed, 12 skipped`（skip = 本机缺 go/rustc/javac 工具链，CI 上全跑）；
- 全量：见本报告提交时的 CI 快照（`CI` / `Acceptance` 两个 workflow）；
- CI 修复过程中的三类真回归都被自检脚本补成了规则：I001 组内乱序、重导出块排序 + 注释空行、Rust `as_arr` 访问器（`scripts/check_imports.py` 现在 382 文件 0 问题）。

## 10. 已知缺口

1. **OAuth 未实现**（按任务书要求只预留：不在 `AUTH_TYPES`，写了直接报错，不静默当无认证）；
2. MCP `resource` / `prompt` 仍是 v1 未实现（返回 not supported，语义未变）；
3. 插件面 `mcp_status` / `mcp_call` 走的是「读配置 + httpx 直连」（认证头照样注入），不经 `McpClient`，因此没有 DNS 二次校验；URL 来自管理员配置、插件无法指定，SSRF 闸门仍在配置校验与 `McpClient` 两处。若将来允许插件传 URL，这条路径需要补校验；
4. `McpAuthInfo.status` 只给 `none/configured/error`，「authenticated」是运行期结论，由 `mcp_status`（真连一次）给出；
5. Go / Rust / Java 本机无工具链，只能靠 CI 编译 + 真进程验收（本机 skip 会打印原因，不当作通过）；
6. `.env_example` 存在**既有**漂移（`VISION_*` / `MULTI_REPLY_*` 等与生成器不一致，早于本任务），本次只保证 5 个 `MCP_AUTH_*` 与生成器逐字一致，未整体重生成（避免无关 diff）。

## 11. 是否破坏旧配置

**不破坏**，证据：

- `MCP_SERVERS` 里没有 `auth` 的旧配置：解析结果 `auth=None` → `NoneAuth`，行为与升级前完全一致；
- legacy 单 server（`MCP_SERVER_URL` / `MCP_SERVER_NAME`）继续可用，且新增 `MCP_AUTH_*` 兼容变量；
- 旧配置里的 `tools` 字段仍被接受（`allowed_tools` 的别名，由 `tests/test_api_gap_messages.py` 抓出并补上）；
- 插件侧旧 API（`bot.mcp_call` / `bot.sdk()["mcp"].*`）保持原样，新 facade 是**增量**；
- 147 条配置/MCP 相关既有用例全绿（含 `MCP_ENABLED` 的 fail-fast 文案用例）。

## 12. 是否需要版本号变化

**需要，MINOR（v2.5.0）**：新增了认证能力、配置字段（`auth` / `MCP_AUTH_*`）、Core API 字段（`auth` 状态）、五语言 SDK 能力与 WebUI 表单项——属于「向后兼容的功能新增」；不构成 MAJOR（无破坏性变更、不要求用户迁移），也不止 PATCH（不是修 bug）。

## 附 A：git diff 自查 7 项

| 项 | 结论 | 证据 |
| :--- | :--- | :--- |
| 无意外改动 | ✅ | `git status --short` 只有本次目标文件；`git diff --name-status b2daf04..HEAD` = 10 新增 / 30 修改，无删除（除 tests 侧必要的行替换） |
| 无 secret | ✅ | 全 diff 扫描真密钥模式 0 命中；3 处命中均为测试里的**标记值**（`PWD-SECRET` / `SECRET-P` / `LEAK-PWD`，用于断言不泄露） |
| 无测试 token 进生产配置 | ✅ | `.env_example` 的 5 个 `MCP_AUTH_*` 全为空值；文档示例统一 `sk-mcp-xxx` / `sk-xxx` 占位 |
| 无临时文件 | ✅ | 未跟踪 `.env` / `.gh_token` / `settings.db`；自检用的 `.calib*.py` 已删 |
| 无重复实现 | ✅ | 三种认证只有一份实现（`mcp_auth.py`）；Core 与插件面共用 `build_auth` / `_public_mcp_auth`；SDK 侧只做白名单提取，不复制注入逻辑 |
| 无新增 God Class | ✅ | 最大新文件 `mcp_auth.py` 270 行；`manager.py` 只 +56 行（在既有 `_ext_mcp` 内），`mcp.py` 136 行单一职责 |
| 未破坏现有 SDK API 与旧 MCP 配置 | ✅ | 旧 facade / 动作方法保留；`tools` 别名兼容；147 条既有配置/MCP 用例全绿 |

## 附 B：任务书 15 步对照

| 步 | 内容 | 交付 |
| :--- | :--- | :--- |
| 1–2 | 只读审计 + 设计 | `docs/reports/mcp-auth-design.md`（能力矩阵 + 分层设计 + 15 步映射）· `f572345` |
| 3 | 认证抽象 | `mcp_auth.py` + 39 条单测 · `ac94ea1` |
| 4–5 | 配置层 + 客户端注入 | `config.py` / `config_schema.py` / `.env_example` / `mcp_client.py` · `f192ac5` |
| 6–7 | WebUI + Core API | `mcp_panel.py` / `config_panel.py` / `manager.py` · `52c64c7` |
| 8 | 五语言 SDK | Python/TS · `0621b5b`；Go/Rust/Java · `168ecc9` |
| 9 | 测试（含五语言 acceptance） | `test_mcp_auth_e2e.py` · `test_mcp_auth_multilang.py` · `9e349f0` / `ff2d395` |
| 10 | 错误信息三分类 | 「MCP 配置非法: …」/「MCP authentication failed: HTTP 401」/「不支持的 auth type: …（可选: …）」，均不含 secret |
| 11 | 文档 | `docs/features/mcp.md`（认证章节）· `guides/configuration.md` · `reference/{api,sdk}.md` · `plugins/plugin-sdk*.md` · `plugin-developer-guide.md` · `cd23bfa` |
| 12 | 架构分层 | 认证只在 `mcp_auth` + `mcp_client`；OneBot / AIClient / WebUI 不碰认证（WebUI 只做表单与掩码） |
| 13 | 硬约束 | 无新依赖、无 God Class、无复制粘贴、旧配置兼容、不为测试关 SSRF/权限 |
| 14 | 收尾 | 全量测试 + secret 扫描 + 架构审计（本报告 §7–§10） |
| 15 | 最终报告 | 本文件 |
