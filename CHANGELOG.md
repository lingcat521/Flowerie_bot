# Changelog

本文件记录 Flowerie_bot 的版本变更。版本号遵循 [Semantic Versioning](https://semver.org/)。

## [2.1.4] - 2026-09-03

> 📦 **维护状态：停更一年（2026-09-03 起）**——由于 bug 太多懒得修，本项目停更一年，来年再更新。
> 已发布版本可继续使用；期间遇到问题可提 Issue（不保证修复）。

### Fixed——实战修复（Termux 真机验证）
- **WS 发送通道**（SEND_VIA_WS）：NapCat 只开 WebSocket（不开 3000 HTTP）也能发消息；
  OneBot action/echo 请求-响应匹配；HTTP 路径保留（默认 false 零行为变化）
- **图片识图恢复**：NT 图 URL 302→CDN 重定向（每跳 SSRF 校验跟随）+ 浏览器 UA/Referer
- **名字唤起必回**：文本含 BOT_NICKNAME/群特色昵称 = 点名（不带 @ 也必回）
- **日志落盘修复**：RotatingFileHandler 不建目录 → 自动建 `logs/`（之前静默无日志文件）
- sender 失败输出完整原因（message_send_action_failed）+ vision last_error
- websockets 新版 ServerConnection 兼容



### Fixed——配置列表持久化双格式崩溃（config_persisted_apply_failed）
- **根因**：Web UI 保存列表到 settings.db 为 JSON 数组（`[786368680]`），启动 `apply_persisted`
  的 `_coerce`/`_validate` 仅按逗号 split → `ValueError`（ALLOWED_GROUP_IDS/TOXIC_GROUP_IDS）
- **修复**：list-int / list-str 均"JSON 数组优先（元素类型校验）+ 逗号列表兜底（.env 旧写法）"
  ——与 pydantic（`List[int]` 强制 JSON）双向兼容，两种 .env 写法都能启动
- 回归：`test_coerce_accepts_json_list_from_db`（coerce/validate 双格式钉死）



### Added——群特色昵称（BOT_NICKNAME 按群隔离）
- 每个群可设专属称呼（Web UI 新增「群昵称」tab：列表/新增/批量改/留空恢复默认，零 JS）
- 注入链：group nickname store（./data/nicknames.json，原子持久化/≤20字/控制字符剥离）
  → AiGateway → 常规与工具路径 → system prompt【本群专属称呼】段（与默认相同不注入=零行为变化）
- 指令菜单随群昵称（{昵称}指令菜单）；默认仍为 BOT_NICKNAME=花璃
- 配置：GROUP_NICKNAMES_PATH（schema 注册）；与 Web UI 共享同一 store 实例
- 一致性加固：动作表↔Sender 方法、NS↔端点、动作↔权限映射 三项防回归测试（poke 类断链永久拦截）

### Fixed
- poke 群戳路由（send_poke 端点实际存在——能力不再被"无端点"埋没）
- webui_panels 导出遗漏（NicknamePanelMixin）、message_router 行数守护（650）/is_secret 类评审发现 4 项
- 图片 SSRF 默认拒绝私网/元数据 + 登录限速对面板登录生效（安全加固）



### Added——Plugin WebUI（新网络功能，零 JS 红线）
- 插件自有管理控制台：受控 DSL（25+ 组件/页面/tab/breadcrumb/文件/权限 `web_ui`+`web_ui.files`）
- 渲染器先转义后结构化；URL scheme/属性/style 白名单；上传魔数/大小/名称/穿越四道闸
- `webui_page(page, action, params, values)` hook（4s 超时/异常降级）；路由 GET/POST 零 JS 重渲染
- 一致性钉死：docs 组件表 ↔ 渲染器双向（test_plugin_webui_consistency）

### Added——API/SDK 缺口池全覆盖（~180 项）
- PluginApi 60→**160 个语义方法**（消息/好友/群/社交/文件/AI/Memory/MCP/插件/Web/数据/运行时/开发）
- 无端点能力一律**显式** `not supported in v1`（绝不静默/绝不假功能）；可用为本地实现或复用生产客户端
- SDK：gap_sdk 层（分面 ai/memory/mcp/db/cache/task/i18n/config/mock + 上下文 + TaskManager（专用后台 loop）真）
- Matcher 组合器 rule_or/rule_all/rule_not（主进程 any_of/all_of/not 真支持）
- 权限 +2（`plugin_admin`）；`scripts/gen_api_md.py` 自动生成 api.md（永不漂移）

### Fixed——全库白盒 Review（28 条发现）
- **启动崩溃**：config.py 错位校验（启用花语记忆+重排即 NameError）
- **功能失效**：sender._headers 未定义（表情包图片发送）、语义记忆检索死代码、group_res 参数名、
  PluginRuntime hook 通道缺失（WebUI 页/插件互调）、重复回复误杀、纯记忆回合重试空转
- **安全**：图片下载 SSRF（默认拒绝私网/元数据/重定向）、登录限速失效（爆破）、Excel zip 炸弹预检、
  MCP 鉴权头透传、跟踪日志路径、sticker 上下文清洗、service 注册名校验
- 测试：**930 单测（CI pytest 3.9/3.12+PG） + 37 项黑盒验收** 全绿；本轮新增黑盒/白盒 ~120 项（真进程黑盒、白盒审计 37、一致性 6、DSL 安全 19、文件 11、gate 8 等）

## [2.0.1] - 2026-08-31

### Fixed——"保存被拦截/关不掉/什么都没填也报错"修复
- **根因**：`BLOSSOM_MEMORY_*_API_KEY`/`DATABASE_URL` 为 secret 型但 `is_secret=False`
  → 空/短值不过保密跳过 → 误报"值不合法"；修复后扫描 0 残留
- `_chain_needs_secret` 优先读本次提交值（区分关闭开关 vs 错误提交）
- 每日提取上限放宽 (0,500)；全配置保存路径回归测试补齐

## [2.0.0] - 2026-08-30

### 架构重构（v2 主线）
- 语义层与 OneBot 低耦合：端点串只在 `sender.py`+适配层；语义层零 `/send_` `/get_` 字符串
- Web UI 零 JS 化（HTML+CSS+表单）；模型/API 配置行链状态徽标
- 花语记忆：SQLite 默认 + PostgreSQL 可选；BlossomMemory（向量/重排/每日限额/提取）
- 配置保存智能：保密跳过/热重载分组/校验提示

## [1.7.0] - 2026-08-29

### Added——拉格朗日能力对齐 + 低耦合
- 群文件/公告/精华/荣誉/资料（group_folder_*、group_notice_*、essence_list 等 ~15）
- `_SENDER_ACTIONS` 转发表（22+ 动作 → 端点；参数白名单；不支持显式报错）
- SDK 语义门面（group(user)/user(me)/top-level 动作）；OneBot 端点耦合审计测试

## [1.6.0] - 2026-08-28

### Added——Web UI 开关治理 + 持久记忆
- 面板全部配置组可折叠（零 JS `<details>`）；开关状态可视化；余额预警
- 持久记忆（SQLite；可选 PostgreSQL）；LivingMemory → 花语记忆 BlossomMemory
- 文档二层结构：quick-start（10 分钟）+ 完整参考分离



### Added（能力对标主流网关；形态自有特色——语义化分组上下文，端点只在适配层）

- **群操作上下文** `bot.group(gid)`：members/member/mute/kick/set_admin/whole_ban/
  rename/set_card/set_title/send_notice/get_notice/files/files_in/file_url/config/
  config_set/pin/unpin/resource
- **用户与自我**：`bot.user(uid)`（like/tap/card/info）、`bot.me`（info/devices/status/profile）
- **顶层语义动作**：`bot.tap`（戳）/ `bot.emoji`（表情回应）/ `bot.pin`+`bot.unpin`
  （精华）/ `bot.like` / `bot.friends`
- **富内容 Builder**：`BotMessage().card(json)` / `.markdown(text)` / `.button(label, action)`
  （合并 keyboard 段；底层转 json/markdown/keyboard 段，网关支持度见 sdk.md 兼容矩阵）
- 权限新增 `bot_profile`（改 Bot 资料）；群写复用 group_manage、读复用 read_group_info、
  好友/自我复用 read_user_info（总计 23）
- 管理端 `_SENDER_ACTIONS` 转发表（22 语义动作 → Sender 端点；参数白名单清洗；
  不支持端点返回明确错误——换网关即激活）

### Fixed

- **`_handle_action` 权限拒绝解析错误**：拒绝响应此前被伪装成 `ok=True`（插件误以为成功）
  ——现在原样回传 `{ok: False, denied: True, error}`
- **SDK 注册动作失败不再阻断插件启动**：matcher/schedule 注册被拒时降级为日志
- PR #4（README badge 空格）合并

### Tests

- +6：语义动作转发表（18 组端点参数断言）、不支持端点语义、权限拒绝传播、
  SDK 分组上下文转发、富 Builder 出段合并
- 本地 152 通过；ruff 0

## [1.4.0] - 2026-08-31

### Added（高频能力补齐；原则：OneBot 已有直接包装，没有的自造但要轻）

- **请求处理**：好友/加群请求同意/拒绝（`handle_friend_request` / `handle_group_request`）
- **定时任务**：`@bot.schedule(interval=60 / delay=10 / daily="09:30")`；
  主进程轻量调度（asyncio Task，无 cron 依赖）；`schedule_cancel/list`
- **等待与多轮**：`bot.wait_for` / `ask` / `confirm` / `select`（插件侧 Session）
- **命令系统**：`event.args`（shlex 参数拆分）；子命令=命令名含 `.`；
  `bot.cool_down(key, seconds)` 命令级冷却（限频/防刷）
- **KV / 插件缓存**：`bot.kv_get/set/delete/list`（plugin_kv 表按插件隔离；权限 storage）
- **HTTP 扩展**：PUT / DELETE / HEAD（复用既有 SSRF 防线）+ `http_download`
  （≤10MB 落插件目录）
- **记忆**：`mem_update` / `mem_clear`
- **AI（受限）**：`bot.ai_chat(message, system)`（权限 ai_chat；独立于聊天预算，建议自限频）
- **工具类**：`random_choice` / `random_int` / `now` / `format_time`（内建）
- **多媒体消息**：`BotMessage` 支持 `video()` / `voice()` / `file()`（可带名字）/
  `add_segment()`（通用段，如键盘 UI 平台相关透传）
- 事件负载 + `trace_id`；`event.trigger/schedule_id`
- 权限新增：`request_handle` / `scheduler` / `storage` / `ai_chat`

### Fixed

- 插件事件负载真正领域化（`kind/scope/text/at_list/images`；CQ 码在下层阉割）；
  `_plugin_event_type` 返回领域 kind（不再 group_message/meta_event）
- `route` 等待队列先于 api 检查（wait_for 未 attach 亦可接收）
- delay 调度触发即清理；shutdown 清理全部调度任务（防泄漏）

### Tests

- +14：KV 往返/隔离、请求处理、调度注册/触发/cancel/list、工具、HTTP 扩展、
  AI（注入与未注入）、记忆、cool_down、args（引号）、等待消息（命中与超时）、
  schedule 装饰器与路由、多媒体 Builder
- 本地 147 通过；ruff 0

## [1.3.0] - 2026-08-31

### Added

- **Bot SDK（插件生态第一阶段，三层架构）**：
  - 上层 `plugin_sdk/flowerie_sdk/`：FlowerieBot（send/reply/recall/get_message/
    get_context/群 API/权限）+ Matcher 装饰器（command/keyword/regex/prefix/exact）
    + Builder（add_text/at/image/reply）；插件零依赖 HTTP/JSON/SQLite，不接触 OneBot payload
  - 中层 `src/sdk/`：BotEvent（kind/scope 领域语义，零 OneBot 命名）/ BotMessage /
    Matcher（priority 大者先 + block + 可扩展 Rule）/ EventDispatcher（优先级/异常隔离/
    stop/shutdown）/ PermissionChecker（user/group_member/group_admin/group_owner/
    bot_admin/bot_owner，复用 ADMIN_QQ_IDS）/ BotAdapter 抽象
  - 下层 `src/sdk/onebot/`：DTO 瘦身 + Transformer（OneBot raw→BotEvent，CQ 码阉割为
    at_list/images/reply_id；BotMessage→段数组出站）+ OneBotAdapter（复用 Sender；
    错误统一 BotError 体系：BotAPIError/BotTimeoutError/BotPermissionError/
    MessageNotFoundError/UnsupportedOperationError）
- **消息 API 扩展**：send_reply（引用回复）/ delete_message（撤回，仅限本 bot 已发送
  记录）/ get_message / get_group_history / get_context（复用 ContextManager）
- **群 API**：get_group_member(s) / is_group_admin / is_group_owner / group_ban /
  group_kick（OneBot11）
- **事件投递领域化**：kind/scope/text/at_list/images/reply_id/notice_kind；
  notice/request/lifecycle 钩子（on_notice/on_request/on_lifecycle）
- 新权限：delete_message / read_message_history / group_manage
- 文档：docs/sdk.md（三层架构与 API）、docs/api.md（API 总表）、docs/plugins.md（插件开发入口）

### Changed

- 插件事件负载字段（post_type/message_type/notice_type/sub_type →
  kind/scope/notice_kind；CQ 段不再下沉，use at_list/images）
- `NAPCAT_WS_AUTH_MODE`（header/query 互斥鉴权，默认 header 单通道）见 v1.2.x 说明

### Tests

- 新增 SDK 测试（+24）：BotMessage/Transformer CQ 阉割/Event kind 映射/Matcher 5 型
  + priority + Rule async/Listener 优先级·隔离·stop/Adapter 错误语义·超时·context
  复用/Permission/端到端 SDK 插件（@command → event.reply 全链路 + 未命中不投递）
- 并发 100 事件/matcher 不互相污染

## [1.2.0] - 2026-08-31

### Added

- **插件系统（Plugin System v1）**：受控插件运行时。导航栏新增「插件」页（Web UI）。
  支持 Python（`plugin.py`）、Node.js（`index.js`/`package.json`）与 JSON 声明式插件
  （`runtime=json`，`declarations` 规则，无代码执行）。
  安装途径：Web UI 上传 ZIP / URL 下载安装（SSRF 防护 + 大小限制）、本地目录 `plugins/` 自动发现
  （发现 ≠ 自动执行，默认 disabled）。插件运行在独立子进程（`python -I` 隔离 / `node` 子进程），
  stdin/stdout JSON-Lines 协议，崩溃/超时被隔离标记 `crashed`。
  相关配置：`PLUGIN_DIR` / `PLUGIN_PROTECTION` / `PLUGIN_URL_MAX_BYTES` / `PLUGIN_URL_TIMEOUT` /
  `PLUGIN_ZIP_MAX_UNZIPPED_BYTES` / `PLUGIN_ZIP_MAX_FILES` / `PLUGIN_MAX_COUNT`。
  详见 [docs/plugin-developer-guide.md](docs/plugin-developer-guide.md)。
- **第三官方人格「艾拉（Isla）」**：内置 persona `id=isla`（《可塑性记忆》风格原创改编，
  不复制原作台词，温柔克制/自贬/关键时刻决断路线），与 flowerie / atri 并列。`PERSONA_DEFAULT=flowerie` 保持默认。
- **管理员补充发言规则配置**：`ADMIN_RESPONSE_RULES`（每行一条；Web UI「人格」页编辑；
  优先级：安全策略 > 人格 > 人格内置规则 > 本条；不能覆盖安全策略）。
- **主动发言概率配置化**：`PROACTIVE_MESSAGE_MIN/MAX/BASE/USER_BOOST/SINGLE_USER/SHORT_MESSAGE/EMPTY_CONTEXT/BOT_MULTIPLIER`
  （上下文随机回复概率全部可配置）与 `ACTIVE_CHAT_PROBABILITY` / `ACTIVE_CHAT_INTERVAL_MIN/MAX_SECONDS` /
  `ACTIVE_CHAT_CONSECUTIVE_COOLDOWN_SECONDS`（主动聊天循环只配置化数字不改逻辑）。默认值 = 原硬编码值，行为零变化。
- **NapCat WebSocket 正向模式**：`NAPCAT_WS_MODE=forward`（Flowerie 客户端连接 NapCat 正向 WS，
  需 `NAPCAT_WS_URL=ws://` 或 `wss://` + 可选 `NAPCAT_ACCESS_TOKEN` 鉴权），含超时/重连退避/心跳/连接失败处理。

### Changed

- **发言规则配置化**：说话风格规则归属各 Persona（`system_prompt` 内嵌），新增管理员补充规则 `ADMIN_RESPONSE_RULES`；
  全局规则仍以「全局说话风格 & 标点规则」最高优先级注入。
- **Web UI**：面板页签由六个增至七个（新增「插件」）；「人格」页新增管理员补充发言规则编辑；
  「用户状态」页新增修改登录账号表单；「配置」页「主动聊天」分组新增主动发言概率项、Connection 分组新增 NapCat WS 配置。
- **版本号**：1.1.0 → 1.2.0。

### Security

- **Web UI 注册 Bootstrap Lock**：系统一旦初始化（`.env` 或 `settings.db` 存在管理凭据），公开注册永久关闭
  （GET/POST `/panel/register` 与 `/api/register` 一律 403 / 展示「注册已关闭」）；只有 `UNINITIALIZED` 状态才能注册
  第一个管理员；并发注册用 `admin_bootstrap` 表原子 CAS 保证仅一个成功；改账号走登录态 `/panel/account/credentials`
  （需当前密码）；注销（`/panel/account/unregister`，需当前密码）= 显式重置回到 `UNINITIALIZED`；
  历史已有凭据自动视为已初始化。
- **插件安全**：安装 ZIP 防护（ZIP Slip / Zip Bomb / 符号链接 / 路径穿越 / manifest 注入）、URL 下载 SSRF 防护、
  权限强制（PermissionManager）、进程隔离、日志脱敏；保护级别（`PLUGIN_PROTECTION`）任何级别都不豁免
  manifest 校验 / 管理员权限 / 进程隔离 / 日志 / 崩溃保护 / 资源限制 / 权限检查。
- **NapCat WS token 脱敏**：`NAPCAT_ACCESS_TOKEN` 绝不写入日志（URL 查询串剥离后记录）。
