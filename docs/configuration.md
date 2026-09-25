# 配置说明

> 当前版本 **v2.3.0**。优先级：**Web UI 持久化配置 > 环境变量（`.env`）> 代码默认值**。
> Web UI 保存 = 写回项目根 `.env`（原子更新、保留注释与原有变量）+ 同步 `data/settings.db`，重启后仍优先生效。

- **首次启动**（项目根无 `.env`）自动释放完整模板：`main.ensure_env_template()` → `src/services/env_template.py`，
  由 `src/services/config_schema.py:SCHEMA` 渲染（**171 项**配置，每项带中文说明 + 分类，与 Web UI 配置页同源）；已有 `.env` 不覆盖。
- **启动校验**（`src/config.py:validate_config()`，fail-fast，见文末「启动校验」）：必填缺失/占位值、端口冲突、枚举非法、区间越界一律拒绝启动。
- 下表「默认」= 代码默认值；说明标 **重启** 的项改后需重启，其余热更新（完整重启清单见文末）。

## 必填

| 变量 | 说明 |
| :--- | :--- |
| `DEEPSEEK_API_KEY` | DeepSeek 密钥（仍为 `sk-your...` 占位值会在启动时报错） |
| `BOT_QQ` | 机器人 QQ 号（正整数） |

## AI / Provider

| 变量 | 说明 | 默认 |
| :--- | :--- | :--- |
| `AI_ENABLED` | AI 回复总开关（关=不请求 Provider，普通功能不受影响） | `true` |
| `DEEPSEEK_API_URL` | DeepSeek 接口地址 | `https://api.deepseek.com/chat/completions` |
| `DEEPSEEK_MODEL` | 群聊对话模型 | `deepseek-flash` |
| `TOXIC_API_KEY` / `TOXIC_API_URL` / `TOXIC_MODEL` | 引战检测 AI（留空回退 DeepSeek 的 key/网址） | 空 / 空 / `deepseek-flash` |
| `VISION_API_KEY` / `VISION_API_URL` | 识图视觉模型（留空回退 DeepSeek） | 空 |
| `VISION_MODEL` / `VISION_TIMEOUT` | 识图模型 / 超时（秒） | `deepseek-flash` / `30` |
| `VISION_ENABLED` | 识图总开关（关=不描述群图与转发图，省 token 且减少图片隐私顾虑） | `true` |
| `VISION_FORWARD_IMAGES` | 是否识别合并转发内的图片 | `false` |
| `MAX_AI_INPUT_CHARS` | 单次 AI 输入（上下文+消息）最大字符数 | `8000` |

## 多条回复（Multi-Reply）

> 一次 AI 回复拆成 **1~N 条独立消息**逐条发送；默认关闭，关闭时行为与单条回复完全一致。

| 变量 | 说明 | 默认 |
| :--- | :--- | :--- |
| `MULTI_REPLY_ENABLED` | 总开关；**同时**决定是否给模型注入内部工具 `reply`（AI 自主拆分，无独立开关） | `false` |
| `MULTI_REPLY_MAX_MESSAGES` | 单次最多几条（AI 无权绕过，超出直接丢弃） | `3` |
| `MULTI_REPLY_INTERVAL_MODE` | 间隔模式：`none` / `fixed` / `random` | `random` |
| `MULTI_REPLY_MIN_INTERVAL` / `MULTI_REPLY_MAX_INTERVAL` | 间隔秒数（`fixed` 用最小值；`MAX` 仅 `random` 生效） | `1.5` / `4.0` |

- 与防刷屏的关系：**每条都计一次连续回复**，达到 `MAX_CONSECUTIVE_REPLIES`（默认 3）后照常进入 `BOT_CONSECUTIVE_REPLY_COOLDOWN` 冷却
  —— 例：`MAX_MESSAGES=5` + `MAX_CONSECUTIVE_REPLIES=3` → 实际最多连发 3 条。
- Provider 不支持 tool calling 时自动降级：带工具的请求被拒（4xx）后在**同一次请求内**退回纯文本，不会收不到回复。
- 本地预演（不需要 QQ）：`python3 scripts/multi_reply_demo.py`（`--disabled` / `--max-messages N` 可对比配置效果）。

## 协议端与连接

| 变量 | 说明 | 默认 |
| :--- | :--- | :--- |
| `QQ_PROTOCOL` | 协议端：`onebot`（NapCat 等）/ `milky`（Lagrange.Milky / Yogurt 等）；**重启** | `onebot` |
| `CLIENT_PROFILE` | 出站段按哪个客户端档案收敛：空=不收敛（与历史一致）/ `go-cqhttp` / `napcat` / `llbot` / `onebot11:<client>` / `milky:<client>`；取值必须是 [client-profiles.md](client-profiles.md) 登记过的客户端，未调查的名字只记一条日志、不做收敛 | 空 |
| `MILKY_API_BASE` | Milky 协议端 HTTP 根（`/api/<action>`）；**重启** | `http://127.0.0.1:8080` |
| `MILKY_EVENT_URL` | Milky 事件推送 WebSocket；**重启** | `ws://127.0.0.1:8080/event` |
| `MILKY_ACCESS_TOKEN` | Milky Bearer 鉴权 token；**重启** | 空 |
| `WS_HOST` / `WS_PORT` | 反向 WS 监听地址/端口（NapCat 连入）；**重启** | `127.0.0.1` / `3001` |
| `HTTP_API_BASE` | NapCat HTTP API；**重启** | `http://127.0.0.1:3000` |
| `WS_TOKEN` | 反向 WS 鉴权 token（空=不鉴权，建议仅在绑 loopback 时留空）；**重启** | 空 |
| `SEND_VIA_WS` | 发送通道：`auto`（WS 优先→HTTP 回退）/ `true`（仅 WS）/ `false`（仅 HTTP） | `auto` |
| `NAPCAT_WS_MODE` | `reverse`（本机做 WS 服务端，原有行为）/ `forward`（连接 NapCat 正向 WS）；**重启** | `reverse` |
| `NAPCAT_WS_URL` | `forward` 必填，`ws://` 或 `wss://`；**重启** | 空 |
| `NAPCAT_ACCESS_TOKEN` | `forward` 鉴权 token（绝不写日志）；**重启** | 空 |
| `NAPCAT_WS_AUTH_MODE` | forward 鉴权通道：`header`（`Authorization: Bearer`，URL 不带 token）/ `query`（`?access_token=`，OneBot11 约定）——**两者互斥，绝不同时发送**；**重启** | `header` |

## 机器人行为

| 变量 | 说明 | 默认 |
| :--- | :--- | :--- |
| `BOT_NICKNAME` | 全局昵称（Web UI「群昵称」页可按群覆盖） | `花璃` |
| `ONLY_REPLY_WHEN_AT` | 哑巴模式（只回 @） | `false` |
| `USER_COOLDOWN` / `BOT_COOLDOWN` | 同一用户 / 机器人自身冷却（秒） | `5` / `2` |
| `MAX_REPLY_LENGTH` | 单条回复最大长度 | `40` |
| `MAX_CONSECUTIVE_REPLIES` | 连续回复上限（超出进入冷却） | `3` |
| `BOT_CONSECUTIVE_REPLY_COOLDOWN` | 连续回复后的冷却（秒） | `60` |
| `CONTEXT_SIZE` | 上下文条数 | `300` |
| `MAX_CUSTOM_PROMPT_LENGTH` | 自定义 Prompt 最大长度；**重启** | `2000` |
| `POKE_REPLY_ENABLED` / `POKE_REPLIES` | 戳戳回复开关 / 回复语（textarea，每行一条，共 34 条内置） | `true` / 内置列表 |
| `REPEAT_ENABLED` / `REPEAT_WINDOW` / `REPEAT_THRESHOLD` | 复读检测开关 / 窗口（秒）/ 触发次数 | `true` / `120` / `3` |
| `ANTI_SPAM_ENABLED` | 防刷/冷却逻辑开关 | `true` |
| `TOXIC_GROUP_IDS` / `TOXIC_WARNING_COOLDOWN` | 引战检测群号（空=不检测）/ 警告冷却（秒） | 空 / `900` |

## 主动聊天

| 变量 | 说明 | 默认 |
| :--- | :--- | :--- |
| `PROACTIVE_CHAT_ENABLED` | 主动聊天循环总开关 | `true` |
| `NIGHT_SILENCE_START` / `NIGHT_SILENCE_END` | 夜间静默时段（小时；要求 `0<=start<end<=24`） | `0` / `8` |
| `ACTIVE_CHAT_COOLDOWN` | 主动聊天冷却（秒） | `180` |
| `PROACTIVE_MESSAGE_MIN_PROBABILITY` / `PROACTIVE_MESSAGE_MAX_PROBABILITY` | 上下文随机回复概率钳制区间（`min<=max`） | `0.01` / `0.05` |
| `PROACTIVE_MESSAGE_BASE_PROBABILITY` | 基础概率 | `0.03` |
| `PROACTIVE_MESSAGE_USER_BOOST` | 最近 5 条中用户消息 ≥2 条时的增量 | `0.01` |
| `PROACTIVE_MESSAGE_SINGLE_USER_PROBABILITY` | 最近消息全部来自同一用户时的低概率 | `0.02` |
| `PROACTIVE_MESSAGE_SHORT_MESSAGE_PROBABILITY` | 最近一条消息 <2 字时的低概率 | `0.02` |
| `PROACTIVE_MESSAGE_EMPTY_CONTEXT_PROBABILITY` | 群尚无上下文时的概率 | `0.02` |
| `PROACTIVE_MESSAGE_BOT_MULTIPLIER` | 机器人连续发言 ≥2 条时的衰减系数（1.0=不衰减） | `0.3` |
| `ACTIVE_CHAT_PROBABILITY` | 主动聊天循环触发概率 | `0.10` |
| `ACTIVE_CHAT_INTERVAL_MIN_SECONDS` / `ACTIVE_CHAT_INTERVAL_MAX_SECONDS` | 轮询间隔下限/上限（秒，`1<=min<=max<=3600`） | `5` / `10` |
| `ACTIVE_CHAT_CONSECUTIVE_COOLDOWN_SECONDS` | 连续主动发言 ≥2 次后的冷却（秒） | `1800` |

## 稳定性、熔断与预算

| 变量 | 说明 | 默认 |
| :--- | :--- | :--- |
| `EVENT_PROCESS_TIMEOUT` | 单条消息处理超时（秒；超时视为卡死跳过） | `90` |
| `MAX_CONCURRENT_AI` | 同时处理的 AI/识图并发上限；**重启** | `3` |
| `AI_MAX_RETRIES` | 单次逻辑 AI 操作最大重试次数（每次尝试单独过预算闸门） | `3` |
| `AI_CIRCUIT_BREAKER_FAILURES` / `AI_CIRCUIT_BREAKER_PAUSE_SECONDS` | Provider 级熔断阈值 / 冷却（4xx 不计入） | `10` / `60` |
| `GROUP_CIRCUIT_BREAKER_FAILURES` / `GROUP_CIRCUIT_BREAKER_PAUSE_SECONDS` | 群级熔断阈值 / 冷却 | `5` / `30` |
| `GROUP_CIRCUIT_BREAKER_MAX_GROUPS` / `GROUP_CIRCUIT_BREAKER_TTL_SECONDS` | 群级熔断器容量上限 / 空闲 TTL（秒）；容量项**重启** | `1000` / `604800` |
| `DAILY_AI_CALL_BUDGET` / `GROUP_DAILY_AI_CALL_BUDGET` | 全局 / 每群每日 AI 调用上限（0=不限） | `1000` / `300` |
| `USER_AI_CALL_MIN_INTERVAL` | 同一用户两次 AI 回复最小间隔（秒，0=不限） | `10` |
| `BUDGET_EXHAUSTED_NOTICE` | 额度用尽时在群里提示一句（每天每群一次） | `true` |
| `CONTEXT_BACKUP_PATH` / `CONTEXT_BACKUP_INTERVAL` | 上下文周期备份库（SQLite）/ 间隔（秒）；路径**重启** | `./data/context_backup.db` / `60` |
| `LOG_LEVEL` / `LOG_FORMAT` | 日志级别 / 格式（`text` 人类可读、`json` JSON lines 含 `trace_id`/`event`）；**重启** | `INFO` / `text` |

## 记忆与知识

| 变量 | 说明 | 默认 |
| :--- | :--- | :--- |
| `MEMORY_ENABLED` | 长期记忆总开关（关=不读/写；短期 Context 不受影响） | `true` |
| `MEMORY_PATH` | 记忆库（SQLite；旧 `memory.json` 自动迁移）；**重启** | `./data/memory.db` |
| `MEMORY_TTL_DAYS` / `MODEL_MEMORY_TTL_DAYS` | 用户原话 / AI 推断记忆保留天数（0=永久） | `0` / `30` |
| `MEMORY_DISABLED_GROUPS` | 完全禁止写入记忆的群号（逗号分隔） | 空 |
| `AUDIT_LOG_PATH` | 记忆审计日志；**重启** | `./data/audit.log` |
| `MEME_LEARNING_ENABLED` | 群聊梗知识每日总结任务总开关 | `false` |
| `MEME_KNOWLEDGE_DB_PATH` | 梗知识库（SQLite，按群隔离）；**重启** | `./data/knowledge.db` |
| `MEME_SUMMARY_INTERVAL_HOURS` | 总结周期（小时） | `24` |
| `MAX_GROUP_MEMES` / `MEME_MAX_SUMMARY_CANDIDATES` | 每群知识条数上限 / 单群单轮候选梗上限 | `500` / `20` |
| `MEME_BUFFER_PER_GROUP` | 每群消息缓冲上限（条）；**重启** | `1000` |
| `MEME_MAX_GROUPS_PER_RUN` / `MEME_MIN_MESSAGES_PER_SUMMARY` | 单轮最多处理群数 / 少于该消息数不总结 | `20` / `10` |

## 花语记忆（BlossomMemory，默认全关）

> 总开关 OFF = 零模型资源（不加载 embedding / reranker / 向量库）；子开关只在总开关 ON 时生效，各自默认关。
> 开启子链路但未配模型/地址 → 启动 fail-fast。

| 变量 | 说明 | 默认 |
| :--- | :--- | :--- |
| `BLOSSOM_MEMORY_ENABLED` | 总开关 | `false` |
| `BLOSSOM_MEMORY_EMBEDDING_ENABLED` / `BLOSSOM_MEMORY_RERANKER_ENABLED` / `BLOSSOM_MEMORY_EXTRACT_ENABLED` / `BLOSSOM_MEMORY_RETRIEVAL_ENABLED` | 向量模型 / 重排序 / 自动提取 / 长期检索 四子开关 | 全 `false` |
| `BLOSSOM_MEMORY_EMBEDDING_MODEL` / `BLOSSOM_MEMORY_EMBEDDING_API_URL` / `BLOSSOM_MEMORY_EMBEDDING_API_KEY` | Embedding（OpenAI-compatible） | 空 |
| `BLOSSOM_MEMORY_RERANKER_MODEL` / `BLOSSOM_MEMORY_RERANKER_API_URL` / `BLOSSOM_MEMORY_RERANKER_API_KEY` | Reranker | 空 |
| `BLOSSOM_MEMORY_VECTOR_DIMENSION` | 向量维度 | `1024` |
| `BLOSSOM_MEMORY_RETRIEVAL_TOP_K` / `BLOSSOM_MEMORY_RERANK_TOP_K` | 检索 / 重排 Top K | `5` / `3` |
| `BLOSSOM_MEMORY_SIMILARITY_THRESHOLD` | 相似度阈值 | `0.6` |
| `BLOSSOM_MEMORY_MAX_ENTRIES` | 每组语义记忆条目上限（超限清理最旧） | `2000` |
| `BLOSSOM_MEMORY_TTL_DAYS` | 语义记忆 TTL（天，0=永久） | `90` |
| `BLOSSOM_MEMORY_DAILY_EXTRACT_LIMIT` | 每日自动提取上限（0=不提取） | `20` |

## MCP 工具

| 变量 | 说明 | 默认 |
| :--- | :--- | :--- |
| `MCP_ENABLED` | 总开关（`true` 时必须配好 server，否则启动失败，不静默降级） | `false` |
| `MCP_SERVER_URL` / `MCP_SERVER_NAME` | 单 server 地址 / 名称（`MCP_SERVERS` 为空时回退使用）；名称**重启** | 空 / `mcp` |
| `MCP_SERVERS` | 多 server JSON 数组：`[{"name","url","allowed_tools"?,"timeout"?,"enabled"?}]`；name 唯一且合法、url 过 SSRF 校验；**重启** | 空 |
| `MCP_TIMEOUT` / `MCP_MAX_TOOL_CALLS` | 单次调用超时（秒）/ 单轮工具调用次数上限 | `15` / `5` |
| `MCP_ALLOWED_TOOLS` | 工具 allowlist（逗号分隔；空=放行所有工具） | 空 |
| `MCP_ALLOWED_HOSTS` | 显式放行的本地/内网主机白名单（仅这些地址可绕过回环/私网拒绝）；**重启** | 空 |
| `MCP_CIRCUIT_FAILURES` / `MCP_CIRCUIT_PAUSE_SECONDS` | MCP 独立熔断阈值 / 冷却（每 server 各自独立） | `5` / `60` |

## Web UI

| 变量 | 说明 | 默认 |
| :--- | :--- | :--- |
| `WEB_UI_ENABLED` | 管理后台开关（只监听配置的 host）；**重启** | `true` |
| `WEB_UI_HOST` / `WEB_UI_PORT` | 监听地址 / 端口（端口不能与 `WS_PORT` 相同，否则启动报错）；**重启** | `127.0.0.1` / `8080` |
| `WEB_UI_ALLOW_LAN` | `true` 时改绑 `0.0.0.0`（局域网/公网可访问，启动日志输出安全警告）；**重启** | `false` |
| `WEB_UI_TOKEN_TTL_SECONDS` | 登录 token 有效期（秒，区间 60~604800） | `3600` |
| `WEB_UI_USERNAME` / `WEB_UI_PASSWORD` | 初始管理账号；**不在 SCHEMA/配置表单中**——由 `/panel/register` 注册页管理，密码只存 scrypt 哈希 | `admin` / 空 |

- 访问：`http://127.0.0.1:8080/panel`（八个页签：配置 / 人格 / 群聊知识 / 群昵称 / 插件 / 外观 / 日志 / 用户状态，全部零 JavaScript 服务端渲染）。
- **Bootstrap Lock**：`WEB_UI_PASSWORD` 允许为空（= UNINITIALIZED，此时拒绝一切登录），公开注册页是创建**第一个**管理员的唯一入口；
  系统一旦初始化（`.env` 或 `settings.db` 已有凭据）注册**永久关闭**，改账号走登录态「用户状态」页（需当前密码），
  注销 = 显式重置回 UNINITIALIZED 才能重新注册。详见 [security.md](security.md)、[web-ui.md](web-ui.md)。

## 插件系统

| 变量 | 说明 | 默认 |
| :--- | :--- | :--- |
| `PLUGIN_DIR` | 插件目录（扫描其中 `*/manifest.json` 自动发现；发现 ≠ 执行，默认禁用）；**重启** | `./plugins` |
| `PLUGIN_PROTECTION` | 保护级别 `normal` / `relaxed` / `unsafe`（只影响运行时资源限制；**任何级别都不豁免** manifest 校验/管理员权限/进程隔离/日志/崩溃保护/权限强制） | `normal` |
| `PLUGIN_MAX_COUNT` | 注册表插件总数上限；**重启** | `100` |
| `PLUGIN_URL_MAX_BYTES` / `PLUGIN_URL_TIMEOUT` | URL 下载插件包大小上限（字节）/ 超时（秒） | `5242880` / `15` |
| `PLUGIN_ZIP_MAX_UNZIPPED_BYTES` / `PLUGIN_ZIP_MAX_FILES` | ZIP 解压后总大小上限（防 Zip Bomb）/ 包内文件数上限 | `52428800` / `200` |

支持 Python（`plugin.py`）、Node（`index.js`/`package.json`）、任意语言（exec，stdin/stdout JSON-Lines）与 JSON 声明式（`runtime=json`，无代码执行）；
运行在独立子进程，崩溃/超时被隔离标记 `crashed`。详见 [plugin-developer-guide.md](plugin-developer-guide.md)。

## 表情包、文件解析与资源限制

| 变量 | 说明 | 默认 |
| :--- | :--- | :--- |
| `STICKER_DIR` / `STICKER_ENABLED` | 表情包目录（**空=禁用**）/ 功能开关；目录**重启** | 空 / `false` |
| `STICKER_DB_PATH` / `STICKER_COOLDOWN` / `STICKER_MAX_LIST` | Vision 索引缓存库（**重启**）/ 每群冷却（秒）/ 提供模型描述上限 | `./data/stickers.db` / `60` / `30` |
| `MAX_FILE_TEXT_CHARS` / `MAX_FILE_DOWNLOAD_BYTES` | 文件解析提取文本上限（字符）/ 下载解码字节上限 | `8000` / `2097152` |
| `MAX_PDF_PAGES` / `MAX_EXCEL_CELLS` / `MAX_CSV_ROWS` | PDF 页数 / Excel 单元格 / CSV 行数上限 | `100` / `50000` / `10000` |
| `MAX_IMAGES_PER_MESSAGE` | 单条消息最多识图张数 | `10` |
| `MAX_FORWARD_DEPTH` / `MAX_FORWARD_MESSAGES` / `MAX_FORWARD_NODES` / `MAX_FORWARD_FETCHES` | 转发展开深度 / 消息总数 / 遍历节点数 / 单条消息拉取次数四重上限 | `5` / `100` / `500` / `20` |
| `MAX_IMAGE_DOWNLOAD_BYTES` / `IMAGE_DOWNLOAD_MAX_REDIRECTS` | 单张图片下载上限（字节）/ 重定向次数 | `10485760` / `3` |
| `IMAGE_ALLOWED_HOSTS` | 图片主机白名单（空=放行所有 http/https，设置后只放行白名单 + NapCat 本地 loopback） | 空 |
| `ARCHIVE_ENABLED` / `ARCHIVE_BASE_DIR` | 消息存档开关（默认关，隐私优先）/ 存档目录（**重启**） | `false` / `./data/archive` |
| `ARCHIVE_RETENTION_DAYS` / `ARCHIVE_MAX_SIZE_MB` | 存档保留天数（0=永久）/ 每群目录大小上限 MB（0=不限） | `0` / `0` |

> 表情包索引：首次扫描用视觉模型生成描述并按文件内容哈希缓存（存 `STICKER_DB_PATH`）；重启复用缓存不重复调 API；
> 文件被替换（同名不同内容）重新分析；Vision 失败记 failed 状态，**24 小时**后才允许自动重试（绝不每条消息重试）。

## 白名单、人格与数据路径

| 变量 | 说明 | 默认 |
| :--- | :--- | :--- |
| `ALLOWED_GROUP_IDS` | 允许群号白名单（空=所有群） | 空 |
| `ADMIN_QQ_IDS` | 管理员 QQ（可执行 `/memory_clear` `/memory_dump` 等） | 空 |
| `PERSONA_DEFAULT` | 默认（兜底）人格 id（内置 `flowerie` / `atri` / `isla`） | `flowerie` |
| `MAX_PERSONA_PROMPT_LENGTH` / `PERSONA_MAX_COUNT` | 单个人格 system_prompt 最大长度（字，**重启**）/ 自定义人格总数上限（内置不计） | `8000` / `200` |
| `ADMIN_RESPONSE_RULES` | 管理员补充发言规则（textarea，每行一条；优先级：安全策略 > 人格 > 人格内置规则 > 本条）；Web UI **人格页**编辑 | 4 条内置 |
| `GROUP_NICKNAMES_PATH` | 群特色昵称存储（Web UI「群昵称」页；留空恢复默认）；**重启** | `./data/nicknames.json` |
| `GROUP_STYLE_RULES_PATH` | 群专属发言规则存储（优先级：群专属 > 管理员补充 > 内置默认）；**重启** | `./data/style_rules.json` |
| `SETTINGS_DB_PATH` | 设置库（自定义 Prompt / Web UI 可编辑配置 / 人格 / webui_prefs）；**重启，谨慎修改** | `./data/settings.db` |
| `STORAGE_BACKEND` / `DATABASE_URL` | 存储后端 `sqlite` / `postgres`；PG 必填连接串 | `sqlite` / 空 |

## 功能总开关（都是一次性关停对应副作用的真实门控）

| 键 | 默认 | 关掉后 |
| --- | --- | --- |
| `AI_ENABLED` | `true` | 不执行 AI 回复 / Provider 请求 |
| `MEMORY_ENABLED` | `true` | 不读/写长期记忆（短期 Context 不受影响） |
| `PROACTIVE_CHAT_ENABLED` | `true` | 主动聊天循环停止 |
| `REPEAT_ENABLED` | `true` | 复读检测停止 |
| `ANTI_SPAM_ENABLED` | `true` | 防刷/冷却停止 |
| `POKE_REPLY_ENABLED` | `true` | 不回应戳一戳 |
| `ARCHIVE_ENABLED` | `false` | （默认关）不写消息存档 |
| `STICKER_ENABLED` | `false` | （默认关）不发表情包 |
| `MCP_ENABLED` | `false` | （默认关）不调用外部工具 |
| `MEME_LEARNING_ENABLED` | `false` | （默认关）不做每日梗总结 |
| `MULTI_REPLY_ENABLED` | `false` | （默认关）只回一条 |
| `BLOSSOM_MEMORY_ENABLED` | `false` | （默认关）零模型资源 |

## 存储后端扩展（SQLite 默认 / PostgreSQL 可选）

- 业务只依赖 Repository 接口；`STORAGE_BACKEND=postgres` 时用 `Postgres*Repository` 平行实现（psycopg 软依赖，需自备 PG）。
- 迁移工具（幂等、失败安全——源库不动）：
  `python -m src.services.storage_migrate --sqlite ./data/memory.db --postgres <DSN> [--blossom ./data/blossom_memory.db]`

## 启动校验与重启清单

启动即校验（`validate_config`，不通过直接退出）：`DEEPSEEK_API_KEY` 非占位、`BOT_QQ>0`、
`WS_PORT`/`WEB_UI_PORT` 在 1~65535 且**两者不相同**、`NIGHT_SILENCE` `0<=start<end<=24`、
`MAX_CONCURRENT_AI>=1`、主动发言概率均为 0~1 有限数且 `MIN<=MAX`、`1<=ACTIVE_CHAT_INTERVAL_MIN<=MAX<=3600`、
`PLUGIN_PROTECTION` 三选一、`NAPCAT_WS_MODE` `reverse|forward`（forward 必须给合法 `ws://`/`wss://` URL）、
`NAPCAT_WS_AUTH_MODE` `header|query`、`STORAGE_BACKEND` `sqlite|postgres`（postgres 必须给 `DATABASE_URL`）、
`MCP_ENABLED=true` 必须有可用 server（URL 过 SSRF 校验、name 唯一、工具名合法）、`BLOSSOM_*` 子链路开启必须配齐模型与地址。

需要**重启**生效的项（`SCHEMA` 中 `hot_reload=false`，共 39 项）：
`BOT_QQ`、`QQ_PROTOCOL`、`MILKY_API_BASE`、`MILKY_EVENT_URL`、`MILKY_ACCESS_TOKEN`、`GROUP_STYLE_RULES_PATH`、
`GROUP_NICKNAMES_PATH`、`MAX_CUSTOM_PROMPT_LENGTH`、`WS_HOST`、`WS_PORT`、`HTTP_API_BASE`、`WS_TOKEN`、
`NAPCAT_WS_MODE`、`NAPCAT_WS_URL`、`NAPCAT_ACCESS_TOKEN`、`NAPCAT_WS_AUTH_MODE`、`MAX_CONCURRENT_AI`、
`GROUP_CIRCUIT_BREAKER_MAX_GROUPS`、`CONTEXT_BACKUP_PATH`、`MEMORY_PATH`、`AUDIT_LOG_PATH`、`STICKER_DIR`、
`STICKER_DB_PATH`、`MCP_SERVER_NAME`、`MCP_SERVERS`、`MCP_ALLOWED_HOSTS`、`WEB_UI_ENABLED`、`WEB_UI_HOST`、
`WEB_UI_ALLOW_LAN`、`WEB_UI_PORT`、`LOG_LEVEL`、`LOG_FORMAT`、`ARCHIVE_BASE_DIR`、`SETTINGS_DB_PATH`、
`MAX_PERSONA_PROMPT_LENGTH`、`PLUGIN_DIR`、`PLUGIN_MAX_COUNT`、`MEME_KNOWLEDGE_DB_PATH`、`MEME_BUFFER_PER_GROUP`。

> 相关文档：[security.md](security.md)（安全边界）、[web-ui.md](web-ui.md)（面板细节）、
> [client-profiles.md](client-profiles.md)（`CLIENT_PROFILE` 取值）、[memory.md](memory.md)（记忆体系）、
> [mcp.md](mcp.md)（MCP 配置示例）、[plugin-developer-guide.md](plugin-developer-guide.md)（插件开发）。
