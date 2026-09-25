# 安全模型（Security Model）

> 当前版本 **v2.3.0**。本文只列**代码里真实存在的防线**（每条都给实现位置）；插件开发侧的接口规范见
> [plugin-developer-guide.md](plugin-developer-guide.md)，方法 × 权限总表见 [api.md](api.md)，
> 2026-09 Code Scanning 逐条判定与证据见 [archive/code-scanning-report.md](archive/code-scanning-report.md)。

## 1. 提示词权限分层（低层不能覆盖高层）

```text
Runtime Security Policy（安全声明 / 记忆铁律 / 知识区边界）      ← 最高，任何文本都不能覆盖
        ↓
Persona（人格 system_prompt + 全局说话风格）                     ← 继承，但不能突破
        ↓
ADMIN_RESPONSE_RULES（管理员补充发言规则）                        ← 只做风格补充
        ↓
Memory / MCP / Plugin / Knowledge（记忆 / 工具结果 / 插件输出 / 群知识）← 全部按不可信外部输入
```

- 安全声明由 `AIClient` 组装，人格/自定义 Prompt/插件输出都改不动它。
- 记忆写入过 `validate_memory_content` 闸门；MCP 与插件工具结果、群聊知识过 `sanitize_untrusted_text`
  （注入句式替换为占位符、清控制字符与零宽字符）；MCP 工具元数据过 `sanitize_tool_metadata`（防 tool description 注入）。
- 不可信内容只进「不可信区段」，不混入指令区。

## 2. 网络与 URL 防线（SSRF / 重定向 / UA）

| 入口 | 实际防线（实现位置） |
| :--- | :--- |
| 识图 / 图片下载（`src/services/vision.py`） | scheme 白名单（`http`/`https`，以及 `data:image/*`）；`check_image_url` 字面量校验（拒回环/私网/链路本地/组播/保留地址、`.local`、userinfo）；**重定向逐跳校验**（`follow_redirects=False` + 每跳重新过校验，上限 3 次）；固定桌面 UA + `Referer: https://q.qq.com/`；`Content-Length` 预检 + 流式大小中止（`MAX_IMAGE_DOWNLOAD_BYTES`）；MIME 魔数嗅探；可选 `IMAGE_ALLOWED_HOSTS`（放行 NapCat 本地 loopback） |
| MCP server URL（`src/core/sanitizer.py`） | `validate_mcp_server_url`（字面量，**含 legacy 单 server 与多 server**）+ `validate_mcp_resolved_ips`（DNS 解析结果，抗 rebinding）；本地/内网地址只有 `MCP_ALLOWED_HOSTS` 显式放行才可用 |
| 插件 URL 安装（`src/plugins/installer.py`） | 三层且都在 sink 之前：字面量校验 → DNS 校验 → `follow_redirects=False`；大小 / 超时 / Content-Type / 扩展名（仅 `.zip`、`.json`）检查 |
| 插件 `http_request`（`src/plugins/http_action.py`） | 字面量 + DNS 双闸；**不跟随重定向**（3xx 直接判失败）；请求体与响应体各 ≤256KB；剥离 `Host`/`Authorization`/`Cookie` 等敏感头；动作仅 GET/POST/PUT/DELETE/HEAD（后三者与下载共用同一套防线） |

## 3. 路径与文件安全（path-injection 整改）

- **插件路径安全化**：`_PLUGIN_ID_RE`（`^[a-z][a-z0-9_-]{0,31}$`）先校验 id，再用 `_plugin_base()` 对
  `PLUGIN_DIR` 做 realpath + `commonpath` 包含性判定，**净化内联到 sink 同一函数**（卸载 `uninstall`、插件文件读写、数据目录）；
  修掉了「用 id 推导出的 base 去比」的假校验（原本 `../` 可直接越界 `rmtree`）。
- **ZIP 安装**：成员名禁止绝对路径与 `..`（ZIP Slip）、拒绝符号链接成员、解压后总大小（`PLUGIN_ZIP_MAX_UNZIPPED_BYTES`，防 Zip Bomb）、
  文件数与目录深度上限；缺 `manifest.json` 或多个顶层目录直接拒绝；manifest 严格 schema（未知字段拒绝）。
- **插件落盘**：`http_download` 的 `save_to` 只允许插件目录内相对路径 + 真实路径公共前缀校验（≤10MB）。
- **面板静态资源**：`/panel/static/{name}` 文件名白名单（拒 `../`、路径分隔符、非 `.css`）。
- **解析预算（防套娃 DoS）**：转发深度 5 / 消息总数 100 / 遍历节点 500 / 单条消息拉取 20；PDF 100 页、Excel 5 万格、
  CSV 1 万行、单条消息最多 10 张图、单文件文本 8000 字符。

## 4. 插件权限与进程隔离

- **权限强制**（`src/plugins/permissions.py:PermissionManager`）：任何 action 执行前都过权限门，未批准 → 拒绝并记
  `plugin_permission_denied` 日志。`PLUGIN_PROTECTION=normal|relaxed|unsafe` **任何级别都不豁免**权限强制、
  manifest 校验、管理员权限、进程隔离、日志与崩溃保护（级别只影响运行时资源限制）。
  普通 QQ 用户永远不能安装/启用插件或改权限。
- **动作名白名单**：`PluginApi.call` 的动作由 `_SENDER_ACTIONS` 登记表校验，未登记动作一律拒绝（防任意端点调用）。
- **进程隔离**：插件跑在独立子进程（Python 用 `python -I`，Node/任意语言用子进程），环境变量白名单不含任何 API Key/Token；
  stdin/stdout JSON-Lines 协议；崩溃/超时被隔离标记 `crashed`，主进程继续运行。
- **资源限制**：单事件动作数、累计输出、入口与 manifest 大小、注册表总数（`PLUGIN_MAX_COUNT`）。
- **语义边界**：`delete_message` 只能撤回**本 bot 已发送并记录**的消息（`_sent_message_ids` 仅保留最近 200 条，其余一律拒绝）；
  `group_manage`（禁言/踢人/改名/公告等写操作）单独授权；`matcher_register` 只影响事件筛选、不授予副作用；
  `request_handle` 批准必须回传原 flag（伪造无效）。

## 5. Web UI 认证安全

- **注册 Bootstrap Lock**：`WEB_UI_PASSWORD` 为空 = `UNINITIALIZED`（此时 `_verify_admin` 拒绝一切登录），
  公开注册页是创建**第一个**管理员的唯一入口；并发注册由 `admin_bootstrap` 表**原子 CAS** 保证只有一个成功。
  系统一旦已有凭据（`.env` 或 `settings.db`）注册**永久关闭**：GET/POST `/panel/register` 与 `/api/register` 一律 403 / 展示
  「注册已关闭」；改账号（`/panel/account/credentials`）与注销（`/panel/account/unregister`）都在登录态且**需当前密码**，
  注销 = 显式重置回 UNINITIALIZED。
- **凭据存储**：密码只存 **scrypt 哈希**（`data/settings.db`，优先于 `.env`）；旧明文兼容比较用恒定时间，登录成功后自动迁移为哈希；
  明文永不写日志。
- **登录限流**：同一 IP 连续 5 次失败锁 60 秒（`_login_fails` 时间窗；表容量 512 防无界内存）。
- **会话与 CSRF**：JSON API 走 `Authorization: Bearer <token>`（无 cookie → 天然防 CSRF）；无 JS 面板走 Cookie `fb_token`
  （`httponly` + `SameSite=Strict`）；token 为 `secrets.token_hex(24)`、内存存储 + TTL（`WEB_UI_TOKEN_TTL_SECONDS`，上限 512 条）。
- **暴露面**：默认只监听 `127.0.0.1`；对外必须显式 `WEB_UI_ALLOW_LAN=true`（绑 `0.0.0.0` 并在启动日志输出安全警告）；
  `WEB_UI_PORT` 与 `WS_PORT` 相同直接启动失败。所有管理端点都要求管理员 token，未认证重定向回 `/panel`。
- **已知边界**：管理后台自身无 TLS —— 局域网/公网部署请设强密码并前置反向代理。

## 6. 插件 HTML 净化（`src/plugins/webui_security.py`）

插件从「不能输出 HTML」改为「HTML 必须净化」，边界全部可单测：

- **白名单净化** `sanitize_plugin_html()`（标准库 `html.parser`，零第三方依赖）：标签白名单（结构/表单/表格/文本类），
  `script`/`iframe`/`object`/`embed`/`template`/`svg`/`math`/`style`/`meta`/`link`/`base` 等一律丢弃（成对标签连内容一起丢）。
- 属性白名单按标签 + 全局属性；**任何 `on*` 事件属性一律丢弃**。
- URL 属性（href/src/action/poster/formaction）只允许 `http:`/`https:`/`mailto:` 与站内相对路径；
  `javascript:`/`vbscript:`/`data:`/`file:`/`blob:` 一律拒绝；表单 `action`/`formaction` 只允许站内相对路径
  （防插件把面板表单连同登录态提交到外部站点）。
- `style` 属性黑名单（`expression(`/`url(`/`javascript`/`@import`/`behavior`/反斜杠）；嵌套深度 32、输入 ≤512KB、输出 ≤1MB 上限；
  **每次丢弃都写进 report**（测试与运维可见）。
- `render_plugin_template()` 受控变量替换：值一律 HTML escape，键不存在 → 替换为空并记 report；
  **不做**表达式/条件/循环/`eval`。

## 7. 数据、日志与指标

- **日志脱敏**（`src/utils/logging_setup.py:redact()`，text/json 两种 formatter 统一走）：
  `sk-***`（API Key）、`ghp_***`（GitHub token）、`Bearer ***`（Authorization）、`access_token|api_key|apikey|token=***`。
- **WS URL 脱敏**（`src/transport/ws_forward_client.py:redact_ws_url`）：剥离查询串与 fragment 后才进日志/UI（只留 scheme + host + path），
  `NAPCAT_ACCESS_TOKEN` 绝不出现明文；插件 URL 下载与 WS 日志同样只记脱敏串。
- **不变量**：敏感值只能以「布尔/枚举结论」进日志，不得出现前缀、后四位、哈希前段等派生片段。
- **Secret 显示**：UI 只回掩码，提交留空 = 不覆盖。
- **指标低基数**：metrics label 只用 operation/result 这类枚举，禁止 id 类高基数标签。

## 8. 熔断、预算与不可绕过的上限

- **三层预算**（`BudgetManager`）：全局每日 / 每群每日 / 同用户最小间隔；额度用尽即闭嘴（可配提示，每天每群一次）。
- **双层 AI 熔断**：Provider 级（只计可重试瞬时失败：超时/网络/429/5xx，4xx 不计）+ 群级（阈值/冷却/容量/TTL，
  防单群故障拖垮其他群）；MCP 另有**每 server 独立熔断**。
- **回复条数不可被 AI 绕过**：多条回复（含 AI 自主拆分的 Native Reply Tool）只产出 `ReplyPlan`，
  条数上限、间隔、连续回复计数、冷却、失败策略、协议能力检查全部由 Core 强制；模型返回 10 条而上限 3 条时只发 3 条。
- **资源闸门**：单条消息处理超时 90s、AI/识图并发上限、单次 AI 输入字符上限、单张图片下载上限、转发展开四重上限。

## 9. 已知边界（如实声明，不当作"已解决"）

- **插件子进程与主进程同 OS 用户/文件系统**：插件可直接读 `.env` 中密钥的落盘值（`DEEPSEEK_API_KEY` 等）。
  防护 = 权限批准流程 + 子进程环境白名单 + `python -I` 隔离；文件系统级沙箱是后续演进方向。
  当前隔离承诺仍然成立：插件**不能**影响其他插件或主进程的数据面。
- **DNS-rebinding TOCTOU**：installer 先解析校验 IP、再由 httpx 建连（二次解析），理论上可抢时间差；当前未做连接后校验。
- `_load_module` 只校验 entry 最终组件的符号链接（中间组件穿越由 manifest 正则 + 安装器兜底）。
- `blossom_memory` 每日限额读-改-写非原子（单进程内近似，可接受）。
- `trace` 读全局日志尾部（限插件批准后可见，无写权限）。
- **CodeQL**：56 条 open 告警 → 6 类真漏洞修复关闭、18 条已举证误报标记 `dismissed`、**32 条 `py/path-injection` 保留 open**
  并标注「暂时无法证明」（sink 安全性由 `_plugin_base()` 等跨函数保证，局部数据流看不到）——已加固，**不标误报**。

## 10. 安全回归测试（零依赖，本地可跑；6 文件 26 条）

| 文件 | 锁住的不变量 |
| :--- | :--- |
| `tests/test_plugin_path_injection.py` | 从源码 AST 取**真实** `_PLUGIN_ID_RE` 测语义：越界 id 全拒、合法放行；`uninstall` 校验先于拼路径 |
| `tests/test_no_open_redirect.py` | 重定向目标必须以 `/panel` 开头；不存在「整串来自变量」的重定向 |
| `tests/test_installer_ssrf_proof.py` | SSRF 三层防线的**顺序**不变量 + 13 类载荷全拒 + 正常 https 放行 |
| `tests/test_code_scanning_redos.py` | 正则**形状不变量**（全模式仅一个量词、无分组量词）+ 4 类病态输入 < 1s + 仓库级「量词套量词」闸门 |
| `tests/test_no_secret_in_logs.py` | `rec()`/`print()` 实参不得含敏感来源派生表达式；脱敏函数必须不存在 |
| `tests/test_webui_assets.py` | 静态资源 sink 层文件名白名单（拒 `../`、分隔符、非 `.css`） |

```bash
pytest tests/test_plugin_path_injection.py tests/test_no_open_redirect.py tests/test_installer_ssrf_proof.py \
       tests/test_code_scanning_redos.py tests/test_no_secret_in_logs.py tests/test_webui_assets.py -q
```
