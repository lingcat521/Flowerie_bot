# 花璃 Web UI 管理后台

> 纯 **HTML + CSS + 服务端渲染**、**零 JavaScript** 的 Web 配置中心；任意浏览器（含禁用 JS 的手机浏览器）可用。

## 开启

默认已开启（`WEB_UI_ENABLED=true`）且**只监听回环** `127.0.0.1`，不对外暴露：

1. 启动：`bash run.sh` 或 `python main.py`
2. 浏览器打开 `http://127.0.0.1:8080/panel`
3. 首次进入是**注册页**：创建第一个管理员（也可提前在 `.env` 写 `WEB_UI_USERNAME` / `WEB_UI_PASSWORD`）

| 变量 | 默认 | 说明 |
| :--- | :--- | :--- |
| `WEB_UI_ENABLED` | `true` | 想彻底关闭改 `false`（需重启） |
| `WEB_UI_HOST` / `WEB_UI_PORT` | `127.0.0.1` / `8080` | 监听地址 / 端口（需重启）；端口不能与 `WS_PORT`（默认 3001）相同，否则启动直接报错 |
| `WEB_UI_ALLOW_LAN` | `false` | `true` → 绑定 `0.0.0.0`（启动日志输出安全警告；请设强密码、勿暴露公网） |
| `WEB_UI_TOKEN_TTL_SECONDS` | `3600` | 登录 token 有效期（秒） |
| `WEB_UI_USERNAME` / `WEB_UI_PASSWORD` | `admin` / 空 | 可留空走注册页（空=UNINITIALIZED）；密码只存 scrypt 哈希，永不写明文 |

> **注册 Bootstrap Lock**：公开注册仅在系统**尚未初始化**（`.env` 或 `settings.db` 无管理凭据）时可用；
> 一旦初始化，`/panel/register` 与 `/api/register` 一律「注册已关闭」，改账号只能走登录态的「用户状态」页。
> 并发注册由 `admin_bootstrap` 表原子 CAS 保证仅一个成功；历史凭据自动视为已初始化（升级绝不重开注册）。
> 注销账号 = 显式重置，回到 UNINITIALIZED 后才可重新首次注册（只清账号密码，其他配置不动）。

## 八个页签

| 页签 | 功能 |
| :--- | :--- |
| **配置** | 全部配置变量按分类分组（人格 / 群聊知识 / 插件配置已移入对应页签），顶部分类导航，每组一个表单保存 |
| **人格** | 全局人格、人格库 CRUD（创建/编辑/删除/设为全局）、群聊人格绑定与解除、管理员补充发言规则、按群自定义 Prompt、`PERSONA_*` 配置 |
| **插件** | 插件列表、上传 ZIP / 单 manifest / URL 安装、刷新扫描、启用（含权限批准）、禁用、卸载、保护措施与插件配置 |
| **群聊知识** | 输入群号查看该群梗知识：搜索/新增/编辑/删除/清空，严格按群隔离 |
| **群昵称** | 群特色昵称（× 人设隔离）：群绑定人设后唤名联动，留空恢复默认 |
| **外观** | 7 套主题 + 背景颜色/图片 + 面板透明度 + 卡片效果 + 恢复默认/删除图片 |
| **日志** | 最近 **200** 条运行日志（`get_recent_logs(200)`，`src/services/web_ui.py:340`） |
| **用户状态** | 账户信息与凭据来源、改账号、注销、服务器状态、MCP 工具状态、API 厂商连接状态（含**向量/重排模型（花语记忆）**两条链路） |

全部通过 HTML `<form>` + GET/POST + 服务端模板渲染，不使用任何 JavaScript。

## 配置页

- **分类导航**（单源常量 `src/services/webui_render/category_constants.py`）：AI / 基础 / 连接 / 行为与回复 / 稳定性与熔断 / 记忆库 / **花语记忆（默认关闭）** / 上下文 / 表情包 / MCP 工具 / Web UI / 日志 / 预算与限额 / 主动聊天 / 复读与防刷 / 戳戳 / 文件解析 / 安全与资源限制 / 白名单与隐私 / 消息存档 / 数据路径。
- **控件按类型自动匹配**：`bool` → checkbox（未勾选服务端写 `false`）；`int/float` → number（含 min/max/step）；`secret` → password（只显示掩码，留空=不修改）；枚举 → select；列表 → 逗号分隔文本框；多行/JSON → textarea。
- **保存**：服务端校验（类型/范围/枚举/JSON/列表）通过后**真正写入项目根 `.env`** 并热更新运行配置；需重启项在页面标注"部分配置将在服务器重启后生效"。
- **折叠（零 JS）**：每分类 `<details>/<summary>` 原生折叠 + `*_ENABLED` 开关徽标（ON/OFF），默认全部展开。
- **花语记忆门控**：总开关 OFF 时该组只渲染总开关本身 + 一行提示，其余 **17** 个键一律不渲染（子开关/模型/地址/密钥/参数）；开启并保存后整组展开（服务端门控，`src/services/webui_render/config_panel.py:80-90`）。
- **管理账号**（`WEB_UI_USERNAME` / `WEB_UI_PASSWORD`）不在配置表单：统一走注册页 / 用户状态页，避免明文写 `.env`。
- **`.env` 持久化**（`src/repositories/env_store.py`）：只改目标行、注释/空行/其他变量逐字节保留；原子写入（临时文件 → flush + fsync → `os.replace`）；线程锁串行化并发保存；空格/`#`/`=`/引号/中文/换行/空串都能正确编解码。

## 人格页 / 群聊知识页 / 插件页

- **人格页**：全局人格下拉保存；人格列表（内置带「内置」徽标，内置不可删除）支持编辑/设为全局/删除；新建人格填 id/名称/简介/system_prompt；群聊人格按群号绑定与一键解除（自动回退）；默认人格 `PERSONA_DEFAULT` 顶部直接改（热更新）；「管理员补充发言规则」textarea 每行一条；按群自定义 Prompt 用 `<details>` 折叠（与 `/prompt` 同一存储）。详见 [persona.md](persona.md)。
- **群聊知识页**：按群搜索/新增/编辑（含义/例句/可信度/状态）/删除/清空；`MEME_*` 配置在本页底部管理，不再出现在「配置」页。详见 [memory.md](memory.md)。
- **插件页**：启用/权限批准/安装/卸载只有管理员能操作；支持 Python（`plugin.py`）、Node（`index.js`/`package.json`）、任意语言（`runtime=exec`）与 JSON 声明式（`runtime=json`）；插件可自带管理页面（真实 HTML 或旧 DSL 兼容层，均需批准 `web_ui` 权限 + 白名单净化 + CSP），详见 [plugin-webui.md](plugin-webui.md) 与 [plugin-developer-guide.md](plugin-developer-guide.md)。
- **插件保护措施**：`Normal`（推荐）/ `Relaxed` / `Unsafe`，只影响运行时资源限制；**任何级别都不豁免** manifest 校验、管理员权限、进程隔离、日志、崩溃保护、资源限制与权限强制。
- **发现 ≠ 自动执行**：刷新扫描 `PLUGIN_DIR`（默认 `./plugins`）新发现的插件注册为**禁用**，由管理员启用并批准权限（勾选声明权限 → 启用）；导入 ZIP 受 ZIP Slip / Zip Bomb / 符号链接防护，URL 安装受 SSRF 防护（拒内网/回环/重定向 + 大小上限 + 超时 + Content-Type/扩展名检查）。

## 外观页

- **7 套主题**：默认（明亮浅色）/ 深色 / 浅色 / Sakura（浅粉）/ Ocean（天空蓝）/ Forest（草绿）/ AMOLED（纯黑，省电）。
- **背景色按主题隔离存储**（`bg_color__<主题>`），切主题互不污染；可填 `#RRGGBB` / `253,238,243` / `rgb(r,g,b)`，留空=用主题默认。
- **面板透明度** 0~100%；**卡片效果** `clear`（纯透明，淡入淡出）/ `glass`（液态玻璃磨砂）。
- **背景图**：PNG/JPEG/WEBP/GIF ≤ 5MB（`MAX_UPLOAD_BYTES`），服务端**魔数校验** + 固定文件名 `background.<ext>` 防路径穿越，持久化到 `data/webui/background/`；图片透明度 0~100% 与背景颜色经 CSS 渐变遮罩合成同一视觉层；显示方式 cover / contain + 位置（居中/顶部/底部/左右）；**顶栏不透明**；「恢复默认主题」「删除背景图片」独立按钮。

## MCP 工具页

服务器以**卡片列表**展示（无需手写 JSON）：每卡显示名称、已同步工具数/配置数、启用状态、地址、测试结果（✔/✖）；操作有启用/停用、**测试**（MCP `initialize` 握手）、编辑、删除；添加表单为名称/地址/工具白名单/超时/启用。**白名单留空 = 放行所有工具**（服务端仍做 SSRF/白名单校验）；保存到 `MCP_SERVERS`，**重启后生效**。详见 [mcp.md](mcp.md)。

## 用户状态页

- **当前管理员**：登录账号 + 凭据来源（`settings.db` 注册账号 / `.env` 初始配置）。
- **改账号**：`/panel/account/credentials`，需新用户名（3~32 字符）+ 新密码（≥6 位）+ 当前密码，改密后强制重新登录（已初始化系统下这是唯一入口）。
- **注销账号**：`/panel/account/unregister`，需当前密码；仅清管理账号与密码（`settings.db` 与 `.env` 的 `WEB_UI_USERNAME`/`WEB_UI_PASSWORD`），其他配置一律不动，注销后强制登出。
- **服务器状态**：平台/系统/架构/主机名/Python 版本/内存（`/proc/meminfo`）/CPU 负载（`/proc/loadavg`），零依赖采集，读取失败显示 `N/A`。
- **MCP 工具状态**：各 server 已同步工具数 + 熔断状态。**API 厂商连接状态**：DeepSeek / 视觉识图 / 引战检测 / 向量模型（花语记忆）/ 重排模型（花语记忆）的地址、模型、Key 是否配置、是否回退 DeepSeek。

## 安全

- **登录限流与哈希**：密码 scrypt 哈希（永不写明文/日志）；同一 IP 连续失败 5 次锁 60 秒（`_LOGIN_FAIL_LIMIT` / `_LOGIN_FAIL_WINDOW`，`src/services/web_ui.py:67-68`）。
- **CSRF**：JSON API 走 `Authorization: Bearer <token>`（无 cookie → 天然防 CSRF）；无 JS 面板走 Cookie 会话（`fb_token`，`httponly` + `SameSite=Strict`）。
- **Secret 掩码**：API Key 只显示 `sk-a****xxxx`，永不回显明文，留空提交不覆盖。
- **上传与 URL 安全**：图片上传校验大小/扩展名/MIME/真实魔数并拒绝 HTML/SVG/脚本；插件 ZIP 与 URL 安装、MCP 与图片下载各有 SSRF 与资源上限防护（详见 [security.md](security.md)）。

## 相关文件

| 用途 | 路径 |
| :--- | :--- |
| 配置持久化 | 项目根 `.env`（原子写入）+ `data/settings.db`（`app_config` / `webui_prefs` / `personas` / `group_persona` / `persona_global`） |
| 服务端实现 | `src/services/web_ui.py`（薄门面：认证/面板壳/生命周期）+ `src/services/webui_panels/`（功能域 mixin：account/auth/config/appearance/mcp/persona/knowledge/nickname/prompt/plugin） |
| 渲染层 | `src/services/webui_render/`（theme/pages/config_panel/appearance/persona/knowledge/account/plugins/nicknames/plugin_dsl/plugin_webui/category_constants/markdown_mini/util + `assets.py` 兼容 PyInstaller `_MEIPASS`）+ `src/services/web_ui_assets.py`（聚合导出） |
| 模板与样式 | `src/services/webui_render/templates/*.html`（panel / login / register / register_closed）、`src/services/webui_render/static/panel.css`（含 `{{THEME_VARS}}` 占位） |
| 静态路由与缓存 | `src/services/webui_static.py`（`/panel/static/{name}` + HTML `no-store`） |
| 业务层 | `config_service.py`（SCHEMA + 双写）、`persona_manager.py` + `persona_presets.py`、`meme_knowledge_manager.py` + `meme_knowledge_repository.py`、`system_status.py`（用户状态页零依赖读 /proc）、`src/repositories/env_store.py`（.env 写入器） |
| 插件运行时 | `src/plugins/`（manager/runtime/manifest/permissions/installer/http_action/runner）+ `src/services/webui_panels/plugin_panel.py` |

## 缓存与自适应

- **缓存策略**：面板 HTML 一律 `Cache-Control: no-store`；面板 CSS 引用 `/panel/static/panel.css?v=<内容指纹>-<资源代际>`，响应 `no-cache + ETag`（未变 304）。改了"样式是怎么生成的"就把 `PANEL_ASSET_GEN` 加一（`src/services/webui_render/theme.py:236`）——URL 一变浏览器必然重新下载，用户无需强刷。
- **分辨率自适应五档断点**：≥1440px 内容区放宽到 1200px、常规 PC 1080px 居中、平板横屏 861~1023px 收紧内边距、平板竖屏 ≤860px 全部单列堆叠、手机 ≤720px 按钮全宽、小屏 ≤420px 主题卡单列。

## 相关文档

[configuration.md](configuration.md)（配置项全量）、[persona.md](persona.md)、[memory.md](memory.md)（群聊知识）、[mcp.md](mcp.md)、[plugin-developer-guide.md](plugin-developer-guide.md)、[security.md](security.md)。

