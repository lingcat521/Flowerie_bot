# Flowerie_bot — Phase 0 只读审计报告（上帝类拆分 + 代码卫生 + 性能）

- **仓库**：`/storage/emulated/0/Flowerie_bot`，HEAD = `e8ce351`（工作树干净：`git status --short` 空输出）
- **审计模式**：**只读**。全程未写入、未提交、未运行任何会改仓库的脚本；所有分析脚本写在仓库外（`~/incoming/work/audit/`），Python 仅用 `ast` 解析源码文本，**不 import 仓库模块**（因此不会产生 `.pyc`）。
- **证据约定**：所有结论附 `文件:行号`；凡未经运行时验证者，一律标注 UNKNOWN / 未验证。
- **分支计数口径**（本报告统一）：对方法体做 AST 遍历，统计 `If / For / While / Try / BoolOp / IfExp` 六类节点总数。任务书里的"52 分支"与本口径的 76 不同，属口径差异，不是矛盾（见 §6.3）。
- **静态 import 图**：仓库 367 个 `.py`（排除被 `.gitignore` 忽略的损坏嵌套克隆 `Flowerie_bot/`、`data/`、`logs/`、`plugins/` 运行期目录）；从 `main.py` 出发可达 **138** 个，其余 229 个中 205 个是 `tests/`。

---

## 1. 范围清单（文件 → 行数）

行数为 `wc -l` 口径（含末尾换行差异 ±1）。"可达"= 从 `main.py` 出发的静态 import 闭包内（解释器会执行的模块）。

### 1.1 `src/services/`（审计主战场，小计 6473 行）

| 文件 | 行数 | 从 main.py 可达 |
|---|---:|---|
| `sender.py` | 513 | ✅ |
| `config_service.py` | 699 | ✅ |
| `web_ui.py` | 401 | ✅ |
| `file_parser.py` | 414 | ✅ |
| `ai_client.py` | 413 | ✅ |
| `memory_manager.py` | 357 | ✅ |
| `config_schema.py` | 342 | ✅ |
| `meme_knowledge_manager.py` | 292 | ✅ |
| `meme_summary.py` | 290 | ✅ |
| `blossom_memory.py` | 287 | ✅ |
| `persona_manager.py` | 273 | ✅ |
| `mcp_tool_manager.py` | 253 | ✅ |
| `persona_presets.py` | 250 | ✅ |
| `vision.py` | 234 | ✅ |
| `prompt_builder.py` | 202 | ✅ |
| `mcp_client.py` | 157 | ✅ |
| `toxic_detector.py` | 145 | ✅ |
| `sticker_manager.py` | 143 | ✅ |
| `group_nicknames.py` | 136 | ✅ |
| `storage_migrate.py` | 129 | ❌（CLI，见 §6.1） |
| `env_template.py` | 117 | ✅ |
| `reply_tool.py` | 103 | ✅ |
| `system_status.py` | 81 | ✅ |
| `group_style_rules.py` | 73 | ✅ |
| `prompt_manager.py` | 71 | ✅ |
| `web_ui_assets.py` | 52 | ✅ |
| `webui_static.py` | 46 | ✅ |

### 1.2 `src/adapters/`（小计 3809 行）

| 文件 | 行数 | 可达 |
|---|---:|---|
| `onebot_parser.py` | 434 | ✅ |
| `milky_parser.py` | 389 | ✅ |
| `resource.py` | 339 | ✅ |
| `client_profile.py` | 281 | ✅ |
| `onebot_serializer.py` | 256 | ✅ |
| `capabilities.py` | 233 | ✅ |
| `onebot/adapter.py` | 224 | ✅ |
| `contract.py` | 206 | ❌（测试夹具，见 §6.1） |
| `testkit/test_protocol.py` | 182 | ❌（虚拟协议，见 §6.1） |
| `onebot/transformer.py` | 182 | ✅ |
| `onebot12_parser.py` | 178 | ❌（骨架适配器） |
| `instance.py` | 169 | ❌（Gate S 多实例，未接线） |
| `milky_serializer.py` | 157 | ✅ |
| `proto.py` | 150 | ✅ |
| `outgoing.py` | 93 | ✅ |
| `onebot/resource_fetcher.py` | 83 | ✅ |
| `container.py` | 77 | ✅ |
| `milky_resource_fetcher.py` | 54 | ✅ |
| `compat.py` | 50 | ✅ |
| `__init__.py` | 32 | ✅ |
| `onebot/dto.py` | 31 | ✅ |
| `testkit/__init__.py` | 9 | ❌ |

### 1.3 `src/transport/`（小计 1457 行，全部可达）

| 文件 | 行数 | 说明 |
|---|---:|---|
| `transports.py` | 471 | 契约参考实现（被 `__init__.py:28` 顶层 import，因此**每次启动都会导入**） |
| `ws_server.py` | 229 | 生产路径（反向 WS） |
| `action_channels.py` | 210 | 生产路径（唯一读协议开关处，`action_channels.py:204-209`） |
| `ws_forward_client.py` | 192 | 生产路径（正向 WS） |
| `contract.py` | 192 | 传输 8 项契约（被 `__init__.py:22` 顶层 import） |
| `milky_ws_client.py` | 94 | 生产路径（Milky 事件） |
| `__init__.py` | 69 | 聚合导出 + PEP 562 懒加载（`__init__.py:57-69`） |

### 1.4 `src/repositories/`（小计 1782 行）

| 文件 | 行数 | 可达 |
|---|---:|---|
| `settings_repository.py` | 413 | ✅（25 个导入方，全仓最高之一） |
| `meme_knowledge_repository.py` | 259 | ✅ |
| `env_store.py` | 258 | ✅ |
| `sqlite_repository.py` | 180 | ✅ |
| `postgres_memory_repository.py` | 174 | ✅ |
| `blossom_memory_repository.py` | 173 | ✅ |
| `postgres_blossom_repository.py` | 133 | ❌（生产未接线，见 §6.1） |
| `sticker_repository.py` | 113 | ✅ |
| `base.py` | 79 | ✅ |

### 1.5 根目录

| 文件 | 行数 | 结论 |
|---|---:|---|
| `main.py` | 310 | 组合根（本次审计的"谁在调用它"依据） |
| `old_ai_tmp.py` | 762 | **死代码**（§6.2） |

---

## 2. 候选类职责域拆解表

表格列义：**状态所有权** = 该类是否真正持有/拥有该职责的状态；**可独立测试** = 仓库现有测试是否能在不启动 bot 的前提下覆盖它（附测试文件名作为证据）。

### 2.1 `Sender`（`src/services/sender.py:15-512`，61 方法 / 54 公共 / 4 构造依赖 / 6 实例属性）

| 职责 | 证据（文件:行） | 状态所有权 | 谁在调用它 | 是否可独立测试 |
|---|---|---|---|---|
| 动作通道懒建 + 协议选择（唯一出口） | `sender.py:48-55`、`sender.py:80-82` | 自己持有 `_channel`（`sender.py:29`）；**工厂与 ws_sender 外部注入**（`sender.py:16-17,26-27`） | `main.py:126` 构造；`main.py:253` 回填 `sender._ws_sender` | ✅ `tests/test_ws_send_channel.py:77` |
| 出站段收敛（ClientProfile 差异） | `sender.py:57-78` | 无（`_outgoing_adapter` 外部注入，`sender.py:22`） | `main.py:123-126` | ✅ `tests/test_outgoing_routing.py` |
| 发送重试策略（3 份相同循环） | `sender.py:107-122`、`134-149`、`178-198` | 无（局部变量） | 内部 | ✅ |
| 54 个协议 API 薄封装（`self._post(` 出现 49 次） | `sender.py:201-512` | 无 | `src/plugins/manager.py`（插件 SDK 出口）、`src/core/*` | ✅ `tests/test_plugin_manager.py`、`tests/sdk/harness.py` |
| HTTP 会话生命周期 | `sender.py:31-42` | 自己持有 `aiohttp.ClientSession`（`sender.py:24,32`） | `main.py:125-126` `async with` | ✅ |
| 指标埋点 | `sender.py:12,119,146` | 模块级 `registry` | — | ✅ |

**关键事实**：61 个方法里 **36 个方法体 ≤4 行**；无任何业务分支、无持久化、无协议解析、无配置读写。它是"协议出口门面"，不是多职责聚合体。

### 2.2 `FileParser`（`src/services/file_parser.py:32-413`，10 方法 / 1 构造依赖 / 2 实例属性）

| 职责 | 证据 | 状态所有权 | 谁在调用它 | 可独立测试 |
|---|---|---|---|---|
| 懒建并复用 httpx 客户端 | `file_parser.py:35`、`37-41`、`43-47` | **自己持有** `_client` | `main.py:208,213` | ✅ |
| URL 流式下载（上限/异常吞掉） | `file_parser.py:59-85` | 无 | `main.py:213` 注入 `resource_fetcher` | ✅ `tests/test_resource_model.py` |
| 字节→文本：**7 种格式分派** | `file_parser.py:88-196`（txt 102-109 / pdf 111-122 / docx 123-134 / xlsx 135-167 / csv 168-186 / other 187-193） | 无 | `src/core/message_assembler.py`、`src/core/message_router.py` | ✅ |
| 其中夹带的**安全预检**（zip 炸弹、单元格/行数上限） | `file_parser.py:139-148`、`157-161`、`181` | 无 | 同上 | ✅ |
| base64 JSON 文件响应解码 | `file_parser.py:199-225` | 无 | Adapter 的 resource_fetcher | ✅ |
| **转发消息抓取（HTTP + 协议端点硬编码）** | `file_parser.py:260-283`（`{HTTP_API_BASE}/get_forward_msg` 在 `271-274`） | 闭包状态 `seen_forwards`/`state`（`262-268`、`327-328`） | 内部 | ⚠️ 需 mock HTTP（无专门测试） |
| 转发递归展开（纯算法 + 4 重预算） | `file_parser.py:285-320` | 同上 | 内部 | ⚠️ 需 mock |
| 转发文本/图片抽取（闭包递归） | `file_parser.py:235-258` | 无 | 内部 | ✅ |
| JSON 卡片文本提取（深度上限 20） | `file_parser.py:352-396` | 无 | `src/core/*` | ✅ |
| @ 与纯文本提取（**与 Adapter 解析器重复**） | `file_parser.py:399-413` | 无 | `src/core/` | ✅ |

### 2.3 `AIClient`（`src/services/ai_client.py:16-412`，14 方法 / 2 构造依赖 / 7 实例属性）

| 职责 | 证据 | 状态所有权 | 谁在调用它 | 可独立测试 |
|---|---|---|---|---|
| HTTP 单次请求 + 响应解析（117 行） | `ai_client.py:41-157` | 自己持有 `client`（`ai_client.py:17-26`）、`_retryable`（`70`）、`_api_backoff`（`71`） | `main.py:125`、`src/core/*` | ✅ `tests/test_ai_client.py` |
| MCP 工具循环 | `ai_client.py:159-207` | 用调用方传入的 `tool_quota`（`184`） | `src/core/ai_gateway.py` | ✅ `tests/test_mcp.py` |
| 通用多轮对话（100 行） | `ai_client.py:209-308` | 无 | `src/core/*` | ✅ |
| 提示词组装（**已外置**） | `ai_client.py:310-324` → `src/services/prompt_builder.py` | 无 | — | ✅ |
| 回复解析/记忆指令/多消息 | `ai_client.py:327-353`、`355-393` | 无 | 内部 | ✅ `tests/test_multi_reply_ai.py` |
| 视觉、引战（**已外置**，纯委托） | `ai_client.py:401-412` → `vision.py` / `toxic_detector.py` | 无 | 内部 | ✅ |

### 2.4 `MemoryManager`（`memory_manager.py:40-356`，16 方法 / **6 构造依赖** / 7 实例属性）

| 职责 | 证据 | 状态所有权 | 谁在调用它 | 可独立测试 |
|---|---|---|---|---|
| 记忆写入（去重/矛盾替换/上限） | `memory_manager.py:246-331` | 无（`repository` 注入，`memory_manager.py:43-56`） | `src/core/*` | ✅ `tests/test_memory_manager.py` |
| 记忆读取/上下文渲染 | `memory_manager.py:167-187`、`333-351` | 无 | `prompt_builder.py:90` | ✅ |
| **审计日志（文件 IO）** | `memory_manager.py:152-164`（每事件 `open(...,'a')`） | 自己持有 `audit_log_path`（`memory_manager.py:49`） | 内部 | ⚠️ 仅间接覆盖 |
| **JSON→DB 一次性迁移** | `memory_manager.py:62-123` | 无 | `__init__` 调用 | ⚠️ 无专门测试 |
| TTL 清理（**全表扫描**，仅启动期） | `memory_manager.py:126-149`，调用点 `memory_manager.py:56` | 无 | `__init__` | ✅ `tests/test_memory_gate.py` |

### 2.5 `MemeSummaryService`（`meme_summary.py:55-289`，9 方法 / **10 个构造参数** / 12 实例属性）

| 职责 | 证据 | 状态所有权 | 谁在调用它 | 可独立测试 |
|---|---|---|---|---|
| 周期调度循环 | `meme_summary.py:79-90` | 自己持有 `_running` | `main.py:151-161` 构造；路由层注册任务 | ✅ `tests/test_meme_summary.py` |
| 批量遍历 + 每群治理（对每个处理过的群再查库） | `meme_summary.py:93-133`（`126-128` trim） | 无 | 内部 | ✅ |
| 预算闸门（复用 BudgetManager） | `meme_summary.py:135-159` | 无（`budget` 由 `main.py:219` 后注入） | 内部 | ✅ |
| 单群总结（AI 调用 + 写库） | `meme_summary.py:162-219` | 无 | 内部 | ✅ |
| 失败重试计数 | `meme_summary.py:221-236`（`_retry_count`，`75`） | **自己持有** `_retry_count`（成功/放弃时 pop，`225`、`239` → 有界） | 内部 | ✅ |
| 模型输出解析 + 可信度加权（纯函数） | `meme_summary.py:247-278`、`281-289` | 无 | 内部 | ✅ |

### 2.6 `BlossomMemoryManager`（`blossom_memory.py:149-286`，7 方法 / 4 构造依赖 / **19 实例属性** / **17 处 getattr**）

| 职责 | 证据 | 状态所有权 | 谁在调用它 | 可独立测试 |
|---|---|---|---|---|
| 配置读取（14 个 `getattr(config, ...)`） | `blossom_memory.py:155-168` | 自己持有 12 个配置快照属性 | `main.py:118` | ✅ `tests/test_blossom_memory.py` |
| 就绪检查（fail-fast） | `blossom_memory.py:180-190` | 无 | `main.py:` 启动链 | ✅ |
| 写入（净化 + 每日限额 + 落库 + 治理） | `blossom_memory.py:193-233` | `_daily_extracted`（`173`，**无界**，见 §7.4） | `src/core/*` | ✅ |
| 检索（embed → 群隔离查询 → 重排 → touch） | `blossom_memory.py:236-270` | 无 | `src/core/*` | ✅ |
| TTL/上限治理 | `blossom_memory.py:272-279` | 无 | 写入路径 | ✅ |
| 已拆出的协作件：`EmbeddingProvider` / `Reranker` / `VectorSearch` / 两个 OpenAI 兼容实现 | `blossom_memory.py:36-145` | 各自持有 client | `main.py:101-118` | ✅ |

### 2.7 `PersonaManager`（`persona_manager.py:36-272`，18 方法 / 5 构造依赖 / 6 实例属性）

| 职责 | 证据 | 状态所有权 | 谁在调用它 | 可独立测试 |
|---|---|---|---|---|
| **生效解析链（每请求最多 4 次 SQLite 查询）** | `persona_manager.py:81-108`（查询在 `88`、`93`、`101`、`105`） | 无（`repository` 注入） | `src/core/ai_gateway.py:137`、`191`、`message_router.py:609`、`command_handler.py:129` | ✅ `tests/test_persona_manager.py` |
| prompt 组合（纯） | `persona_manager.py:111-116`、`119+` | 无 | 同上 | ✅ |
| 人格 CRUD + 校验 | `persona_manager.py:151-244` | `_reserved_ids`（`persona_manager.py:` 类内） | WebUI 面板 | ✅ |
| 群/全局绑定 | `persona_manager.py:246-270` | 无 | WebUI / 解析链 | ✅ |

### 2.8 `McpToolManager`（`mcp_tool_manager.py:84-252`，9 方法 / 3 构造依赖 / 4 实例属性 / **9 处 getattr**）

| 职责 | 证据 | 状态所有权 | 谁在调用它 | 可独立测试 |
|---|---|---|---|---|
| 多 server 运行态构建（配置解析） | `mcp_tool_manager.py:99-139` | **自己持有** `_servers` / `breaker`（`92-94`） | `main.py:136` | ✅ `tests/test_mcp_multi.py` |
| 工具同步（并发拉取 schema） | `mcp_tool_manager.py:155-173` | `_tool_owner` 每次重建（`160`）→ 有界 | `main.py` 启动链 / WebUI | ✅ |
| tools payload 构造 | `mcp_tool_manager.py:175-200` | 无 | `ai_client` | ✅ |
| 工具路由执行（allowlist→熔断→超时） | `mcp_tool_manager.py:203-245` | 用 server 持有的 breaker | `ai_client.` 工具循环 | ✅ `tests/test_mcp_quota.py` |
| 结果净化（**复用了** `sanitize_untrusted_text`，非重复实现） | `mcp_tool_manager.py:38-68`，复用点在 `65` | 无 | 内部 | ✅ `tests/test_mcp_security.py` |

### 2.9 `VisionService`（`vision.py:41-233`，7 方法 / 2 构造依赖 / 3 实例属性）

| 职责 | 证据 | 状态所有权 | 谁在调用它 | 可独立测试 |
|---|---|---|---|---|
| 图片下载（data: URI + 重定向链 + 大小/魔数） | `vision.py:87-165`（79 行） | 无（`client` 由 `client_provider` 外部提供，`vision.py:44-51`） | `ai_client.py:406-412` 委托 | ✅ `tests/test_vision_redirect.py` |
| SSRF/域名白名单校验 | `vision.py:107-110`、`131-135`（`check_image_url`） | 无 | 同上 | ✅ |
| 魔数嗅探（`_looks_like_image`） | `vision.py:19-38` | 无 | 同上 | ✅ |
| 视觉模型调用 | `vision.py:168-201` | 无 | 同上 | ✅ |
| 本地文件描述（**同步 `open`**） | `vision.py:203-233` | 无 | 表情包索引 | ✅ |
| 日志脱敏 URL | `vision.py:55-62` | 无 | 内部 | ✅ |

### 2.10 `SettingsRepository`（`settings_repository.py:20-412`，**38 方法** / 1 构造依赖 / 2 实例属性 / 最长方法 67 行）

一个 SQLite 连接 + 一把 RLock（`settings_repository.py:21-29`）承载 **6 个表域**：

| 表域 | 方法区间 | 证据 |
|---|---|---|
| prompt 配置 | `get/set/delete_prompt` | `settings_repository.py:108-136` |
| app_config 键值 | `get/set/list/delete_config` + `get_config_meta` | `settings_repository.py:139-170` |
| WebUI 偏好 | `get/set/delete/list_pref` | `settings_repository.py:173-195` |
| 人格与绑定 | 9 个 `persona`/`binding` 方法 | `settings_repository.py:198-292` |
| 插件注册表 | `upsert/get/list/delete_plugin` | `settings_repository.py:295-339` |
| 引导状态（原子 CAS） | `get_bootstrap_state`、`try_mark_bootstrap_initialized`、`mark_bootstrap_uninitialized` | `settings_repository.py:342-376` |
| 插件 KV | 4 个 `*_plugin_kv` | `settings_repository.py:379-405` |
| schema DDL | `_init_schema`（67 行） | `settings_repository.py:39-105` |

**无业务逻辑、无协议语义、无错误处理分支**：38 个方法几乎全是 `with self._lock: self._conn.execute(...)` 的同形 DAO 代码；最长方法 67 行是 DDL 文本。

### 2.11 适配器解析器（`OneBotEventParser` / `MilkyEventParser`）

| 职责 | 证据 | 状态所有权 | 谁在调用它 | 可独立测试 |
|---|---|---|---|---|
| 信封解析（kind/scope/请求类/通知类） | `onebot_parser.py:172-232`、`234-254`、`413-421`；`milky_parser.py:93-176`、`179-212` | 只有 `_bot_qq` / `note` 两个属性（`onebot_parser.py:168-170`、`milky_parser.py:383-385`） | `src/adapters/container.py`、`compat.py`、`contract.py` | ✅ 25 个测试文件 |
| **段归一化（巨型 if 链）** | `onebot_parser.py:256-411`（156 行 / 20+ 段类型）；`milky_parser.py:215-318`（104 行 / 15 段类型） | 无（写入传入的 `InternalEvent`） | 同上 | ✅ `tests/test_protocol_roundtrip.py`、`test_roundtrip_matrix.py` |
| 共享归一化助手（跨协议复用，**非重复**） | `onebot_parser.py:58-162` 被 `milky_parser.py:33-40` 导入，调用点在 `milky_parser.py:271,274,278,297,314` | 无 | 两个解析器 | ✅ |
| 事件 ID 生成 | `onebot_parser.py:424-433`、`milky_parser.py:372-377` | 无 | 内部 | ✅ |

### 2.12 传输层三个连接类（重复而非上帝类）

| 类 | 行数 | 职责 | 证据 |
|---|---:|---|---|
| `WebSocketServer` | `ws_server.py:22-228` | 反向 WS 服务 + OneBot action/echo 信封 + 单连接守卫 + draining 停机 | `ws_server.py:45-57`（echo 信封）、`139-228`（处理循环） |
| `NapCatForwardClient` | `ws_forward_client.py:45-191` | 正向 WS 客户端 + 鉴权头/query + 重连 | `ws_forward_client.py:63-88`、`109-181` |
| `MilkyClient` | `milky_ws_client.py:17-93` | Milky 事件客户端 + 重连 | `milky_ws_client.py:35-80` |

三者共享同一骨架（连接 → 逐条事件 → trace + semaphore + `wait_for` 超时 → 退避 5/10/20/40/60），细节见 §6.3。

### 2.13 未接线但被文档/测试引用的类

| 类 | 行数 | 职责 | 状态所有权 | 谁在调用它 | 可独立测试 |
|---|---:|---|---|---|---|
| `TransportContract` / `WebSocketTransport` / `HTTPTransport` / `RetryPolicy` | `contract.py:59-166` + `transports.py:30-415` | 传输 8 项契约与两个参考实现（I/O 原语注入） | 各自持有连接/待响应表（`transports.py:99`） | **仅测试**（`tests/test_transport_contract.py`）+ `src/transport/__init__.py:22-35` 导出 | ✅ |
| `AdapterInstance` / `InstanceRegistry` | `instance.py:29-140` | 多实例注册表（Gate S），生产启动未接 | `_instances`（`instance.py:93`） | **仅测试**（`tests/test_multi_instance.py:18,65`） | ✅ |
| `AdapterUnderTest` + `all_adapters()` | `contract.py:39-206` | 适配器 12 项契约夹具注册表（4 协议 × 12 项） | 无（数据） | **仅测试**（`tests/test_adapter_contract.py:21`） | ✅ |
| `OneBot12EventParser` | `onebot12_parser.py:57-162` | OB12 骨架（`NOT_REAL_DEVICE_VALIDATED`） | `_bot_qq`/`note` | `src/adapters/contract.py:32,137`（惰性）+ 4 个测试 | ✅ |
| `TestProtocolEventParser`/`TestProtocolChannel` | `testkit/test_protocol.py:46-152` | Gate E/F 虚拟协议 | 记录态 | `src/adapters/contract.py:171-175`（惰性）+ `tests/test_pec_experiment.py` | ✅ |
| `PostgresBlossomMemoryRepository` | `postgres_blossom_repository.py:16-132` | 花语记忆的 PG 平行实现 | `_pool` | **仅测试**（`tests/test_postgres_backend.py:41-43`）；生产 `main.py:118` 不传 repository → `blossom_memory.py:169` 默认 SQLite | ✅ |
| `EventDispatcher` | `src/sdk/listener.py:27-64` | 进程内事件分发器 | `_listeners` | **仅测试**（`tests/test_sdk_listener.py:5`） | ✅ |

### 2.14 `old_ai_tmp.AIClient`（`old_ai_tmp.py:63-761`，15 方法 / 最长 120 行）

| 职责 | 证据 |
|---|---|
| 与 `src/services/ai_client.py` 同源的旧单体 AIClient（含视觉、引战、记忆、HTTP） | `old_ai_tmp.py:63-761`；文本相似度 0.575（`difflib.SequenceMatcher`，脚本 `work/audit/` 内执行）；重复函数 `_looks_like_image` 在 `old_ai_tmp.py:41` 与 `src/services/vision.py:19` |
| 被谁引用 | **无**（全仓 `rg 'old_ai_tmp'` 命中 0，文档/测试/脚本皆无） |

---


## 3. 上帝类判定：拆 / 部分拆 / 不拆

判定按任务书标准逐条过（方法数、公共方法数、构造依赖数、实例属性数、被依赖数、是否同时管业务+IO+状态+协议+错误处理、是否多职责域、是否靠大量 getattr、是否有 `_xxx` 内部迷宫、是否靠 mixin 维持体积）。**没有任何候选类同时命中"多职责域 + 多状态所有权 + 高扇入 + 内部迷宫"**。

| 类 | 判定 | 一句话理由 | 预估风险 |
|---|---|---|---|
| `Sender` (513 行/61 方法) | **不拆** | 61 个方法里 36 个 ≤4 行、49 处 `self._post` 转发、零业务状态（`sender.py:29,80-82`）：方法多是因为**协议表面积大**，不是因为职责多；拆成 4 个类会让插件 SDK 的 `bot.xxx()` 出口变脆。 | 低（不动）；若强行拆分：**高**（54 个公共方法被 25+ 处调用） |
| `FileParser` (413 行/10 方法, `extract_forward_messages` 122 行) | **部分拆** | 门面本身不臃肿，但单个方法里叠了 HTTP 取数 + 预算状态 + 递归展开 + 文本抽取（`file_parser.py:260-349`），且解码方法里叠了 7 种格式 + 安全预检（`88-196`）——**职责按方法内聚而非按类内聚**。 | 中（有 round-trip/资源测试，但转发路径无专门测试） |
| `AIClient` (413 行/14 方法, 最长 117 行) | **部分拆** | 已做过一轮外置（Vision/Toxic/PromptBuilder），剩余 `chat_once`(117 行) 与 `chat_with_messages`(100 行) 仍叠着"HTTP 传输 + 工具循环 + 回复解析"三种职责。 | 高（15 个导入方，AI 主链路，回归面大） |
| `MemoryManager` (357 行/6 构造依赖) | **部分拆** | 核心 CRUD 单一职责可留；**审计日志（文件 IO）** 与 **JSON→DB 一次性迁移**是明显的异质职责（`memory_manager.py:152-164`、`62-123`）。 | 低-中 |
| `MemeSummaryService` (290 行/**10 构造参数**/12 实例属性) | **部分拆** | 构造依赖 10 个、实例属性 12 个是"缺参数对象"的典型信号；且"调度器"与"单群执行器"混在一个类（`79-133` vs `162-219`）。 | 中（有 `tests/test_meme_summary.py` 保护） |
| `BlossomMemoryManager` (19 实例属性/17 getattr) | **不拆** | 协作件（Embedding/Reranker/VectorSearch）已经外置成 5 个类，门面只剩 7 个方法；`getattr` 多是为了"配置缺省可运行"（`blossom_memory.py:155-168`），属配置读取风格而非职责泄漏。**只需修 `_daily_extracted` 无界问题与参数对象化**。 | 低 |
| `PersonaManager` (273 行/18 方法) | **不拆** | 单一领域（人格），状态全部外部注入（`persona_manager.py:36-56`）；问题不在类大，而在**解析链每请求重查 DB**（§7.1）。 | 低 |
| `McpToolManager` (253 行/4 实例属性) | **不拆** | 4 个实例属性、每 server 一个 `_McpServer` 值对象（`mcp_tool_manager.py:71-81`）已经是对齐的建模；253 行合理。 | 低 |
| `VisionService` (234 行) | **不拆** | 类只有 7 个方法、3 个属性、client 外部注入；问题在 `_download_image`(79 行) 单方法内叠了 5 种校验——**方法内拆，不是类拆**。 | 低 |
| `SettingsRepository` (413 行/38 方法/6 表域) | **不拆** | 命中"多表域"，但**未命中**"业务+IO+状态+协议+错误处理"混合：它是同形 DAO，共享**一个连接 + 一把锁**的事务不变量（`settings_repository.py:21-29`），拆类会把这个不变量打散；被 25 个文件依赖。 | 强行拆：**中-高**（连接/锁不变量 + 25 个调用方） |
| `OneBotEventParser` / `MilkyEventParser` | **不拆** | 段分支多但**状态只有 2 个属性**、跨协议共享助手已抽（`milky_parser.py:33-40`）；巨型 if 链是"每段独立证据"的产物，改成 dict 分派收益有限、行为风险实在。 | 中（有 round-trip 测试兜底） |
| `onebot_serializer.serialize_segments` (205 行/76 分支) | **不拆（低优先）** | 单职责=出站字段收敛，profile 驱动；混进来的是"未知段原样传递 + note"策略而非第二种业务。 | 中（`tests/test_onebot_serializer.py` 断言 note 文案） |
| `WebSocketServer`/`NapCatForwardClient`/`MilkyClient` | **不拆类，抽公共骨架** | 三个类各自 94-229 行、职责单一，不是上帝类；问题是三者**结构性重复**（§6.3），属代码卫生范畴。 | 中（WS 生命周期测试：`test_ws_lifecycle.py`、`test_napcat_ws_forward.py`、`test_milky_end_to_end.py`） |
| `old_ai_tmp.AIClient` (762 行) | **删（死代码）** | 全仓零引用、与 `ai_client.py` 同源（相似度 0.575）、由拆分提交遗留（`239bf60`）。 | 极低（删除前仅需一次全仓引用确认） |

**结论一句话**：本仓库不存在"典型上帝类"（那种把配置、业务、IO、协议、错误处理揉成 2000+ 行、靠 mixin/`getattr` 迷宫维持的类）。更需要处理的是**方法内职责叠加**（`file_parser.extract_forward_messages`、`ai_client.chat_once`、`vision._download_image`）、**构造参数膨胀**（`MemeSummaryService` 10 个）、**跨模块重复骨架**（3 个 WS 连接类、2 个 JSON store）与**死代码**。

---

## 4. 拆分方案（仅针对判定为"拆/部分拆"的项）

### 4.1 `FileParser` → 门面 + 3 个内聚件（建议 Phase 2 首个动作）

| 新组件 | 真正拥有什么职责与状态 | 迁移步骤 | 需要的测试保护 | 回滚点 |
|---|---|---|---|---|
| `ForwardMessageResolver`（建议放置 `src/services/forward_resolver.py`） | 转发**取数 + 递归展开 + 预算**：`seen_forwards`、`state{nodes,messages,fetches}`、4 个上限（现 `file_parser.py:260-328`）；通过注入的 `fetch(forward_id)` 回调取数，**不再自己拼 `HTTP_API_BASE`** | ① 把 `fetch_forward_messages`/`resolve_nested_forwards` 原样搬进新类，回调默认实现指向 `file_parser._get_client`（行为逐字不变）；② `FileParser.extract_forward_messages` 改为薄编排；③ 再加跨协议取数（经 `sender.call_api`）作为**独立后续提交** | 新增：转发预算/嵌套/缓存去重的纯单测（现无）；回归：`tests/test_resource_model.py`、`tests/test_media_segments.py` | 单提交回退（新文件 + 一处委托） |
| `CardTextExtractor`（纯函数模块） | JSON 卡片递归取文本 + 深度上限（现 `file_parser.py:352-396`） | 直接搬移为模块级纯函数 | `tests/test_face_context.py` 等间接覆盖；建议补纯单测 | 同上 |
| `FileFormatDecoder`（纯函数模块） | 7 种格式分支 + 每格式安全预检（现 `file_parser.py:88-196`）；`config` 上限以显式参数传入而不是 `getattr(self.config, ...)`（现 `95,53` 等 6 处 `getattr`） | 按格式拆成 `_decode_pdf/_decode_xlsx/...`，`decode_bytes` 只做分派 | `tests/test_media_segments.py`；建议补 xlsx 炸弹/超限单测 | 同上 |

**暂不建议**：把 `FileParser` 按"下载/解码/提取"拆成三个有状态类——三者共享同一个 httpx 客户端与上限配置，拆开只会多出注入管道。

### 4.2 `AIClient` → 保留门面，抽出"回复解析"与"工具循环"

| 新组件 | 职责与状态 | 迁移步骤 | 测试保护 | 回滚点 |
|---|---|---|---|---|
| `ReplyContentParser`（纯函数模块） | `_parse_reply_content` + `extract_multi_messages`（现 `ai_client.py:327-393`，纯字符串处理，无状态） | 原样搬移为模块级函数，`AIClient` 内保留同名转发 | `tests/test_ai_client.py`、`tests/test_multi_reply_ai.py`、`tests/test_native_reply_tool.py` | 单提交 |
| `ToolCallLoop`（可注入类） | MCP 工具循环与额度（现 `ai_client.py:159-207` + 额度对象由 `ai_gateway` 创建） | **必须最后由 `ai_gateway` 单测先行**：先给"循环"补一个 fake-tool 单测，再搬 | `tests/test_mcp.py`、`tests/test_mcp_quota.py`、`tests/test_mcp_multi.py` | 单个提交（`ai_client` 保留旧方法名做薄委托 → 可回退） |

**风险提示**：`chat_once` 内部耦合了 `_retryable` 标志（`ai_client.py:70,128,244`）与 `_api_backoff`（`71`），这是 `ai_gateway` 重试决策的输入（`src/core/ai_gateway.py:233,257`）。搬移时这两个字段必须保持**同一实例、同一语义**，否则重试/熔断行为会变——这是本项最大风险点。**若 Phase 2 时间紧，建议只做 4.2 的第一项（纯函数搬移）**。

### 4.3 `MemeSummaryService` → 参数对象 + 调度/执行分离

| 新组件 | 职责与状态 | 迁移步骤 | 测试保护 | 回滚点 |
|---|---|---|---|---|
| `MemeSummaryOptions`（dataclass） | 把 10 个构造参数里 7 个纯配置项（`min_messages`/`max_groups_per_run`/`max_candidates`/`interval_hours`/`max_retries` 等，现 `main.py:151-161` + `meme_summary.py:58-76`）收进一个冻结对象 | 先加 dataclass 并保留旧关键字参数兼容构造（`**legacy`），再让 `main.py` 传对象 | `tests/test_meme_summary.py`（含 `test_summary_group_cap_per_run`） | 单提交；旧签名保留一个版本周期 |
| `MemeSummaryRunner`（可选） | 单群执行：AI 调用 + 解析 + 落库 + 失败重试（现 `162-236`） | 仅当还需要继续加能力时才做 | 同上 + `tests/test_meme_knowledge.py` | 单提交 |

### 4.4 `MemoryManager` → 抽 `MemoryAuditLog` 与 `JsonMemoryMigrator`

| 新组件 | 职责与状态 | 迁移步骤 | 测试保护 | 回滚点 |
|---|---|---|---|---|
| `MemoryAuditLog` | 审计行格式化 + 追加写（现 `memory_manager.py:152-164`），拥有 `audit_log_path` | 搬移后 `MemoryManager` 持有实例；顺带把"每次 open"改为可注入 writer（**行为不变**） | `tests/test_memory_gate.py`、`tests/test_prompt_injection_memory.py` | 单提交 |
| `JsonMemoryMigrator` | 旧 `memory.json` → 仓库的一次性迁移（现 `62-123`） | 搬移为独立函数/类，`__init__` 调用 | 建议补一个 tmp 目录迁移单测（现无） | 单提交 |

### 4.5 `VisionService._download_image` → 方法内拆（不改类边界）

建议拆为：`_decode_data_uri`（现 `vision.py:92-106`）、`_fetch_with_redirects`（`107-153`）、`_validate_bytes`（`157-160`）；重试循环（`115,163-164`）保留在外层。测试保护：`tests/test_vision_redirect.py`。

### 4.6 明确**不做**的拆分（附理由）

- **不拆 `Sender`**：54 个公共方法就是 `bot.xxx()` 契约面（任务书硬约束），拆分类=改 SDK 出口。
- **不拆 `SettingsRepository`**：单连接 + 单锁 + 原子 CAS 是它的核心不变量；按表域拆类会让"注销账号清凭据"这类跨表操作失去原子性。
- **不拆三个 WS 连接类**：它们各自与不同协议端交互，合并成"通用传输"会把协议语义上移（与 ADR-005 的既有结论一致：`docs/architecture/transport-contract.md`）。只抽**重连/事件分发骨架**。

---

## 5. 依赖问题

### 5.1 反向依赖 / 跨层泄漏（真实存在）

| 问题 | 证据 | 说明 |
|---|---|---|
| Services 直连协议端点（绕过 Adapter 通道） | `file_parser.py:271-274` 直接 GET `{self.config.HTTP_API_BASE}/get_forward_msg` | 该方法是 services 层里**唯一自己拼 OneBot 端点**的地方；Milky 模式下这条路依然打 OneBot 地址（行为冻结要求下未改）。属"协议知识泄漏进 services"，与 `src/adapters/container.py:14-16` 声明的"业务层不 import 本模块"并存。 |
| Services 直接依赖 transport（**已声明为合法**） | `sender.py:6` `from src.transport.action_channels import make_action_channel`；注释 `sender.py:18-21` 引用 ADR-001 | 不是 bug，但意味着"services 层不依赖 adapters"的规则**不覆盖 transport**；后续若把 `action_channels` 移入 adapters，会引入反向依赖。 |
| 适配器层被 core 反向 import | `src/core/*` 只 import `src.adapters.*` 的**数据契约**（`proto`/`resource`），无反向 import `core` 的适配器 | 未发现反向依赖。 |
| `old_ai_tmp.py` 与主实现并存 | `old_ai_tmp.py:63-761` vs `src/services/ai_client.py:16-412` | 死代码造成的"伪依赖面"：任何全仓 grep/静态扫描都会命中两份 AIClient。 |

### 5.2 循环依赖

静态 import 图（367 文件）中**未发现模块级循环**：从 `main.py` 可达的 138 个模块的依赖图无回边（脚本 `work/audit/graph3.py` 遍历结果）。以下是需要留意的**惰性/运行时依赖**（不是循环，但会掩盖真实耦合）：

- `src/transport/__init__.py:57-69`：PEP 562 `__getattr__` 用字符串表懒加载 `ws_server`/`ws_forward_client`/`milky_ws_client`——静态图看不到这条边（本报告已手工补上）。
- `src/plugins/runtime.py:90`：`asyncio.create_subprocess_exec` 以子进程方式启动 `src/plugins/runner/python_runner.py`（`python_runner.py:1557-1567` 有 `main()`/`__main__`）——静态 import 图判定"不可达"是**假阳性**，它是独立入口。
- `src/adapters/container.py:53-58` 与 `src/adapters/instance.py:145-160` 共用 `make_parser`（`container.py:53`），instance 未被生产使用。

### 5.3 隐式 `self` 状态耦合（带行号）

| 位置 | 隐式耦合 | 风险 |
|---|---|---|
| `src/core/message_router.py` ← `main.py:239-240` | 组合根在构造后**动态挂载** `group_nicknames`/`group_style_rules` 到 router 实例上 | 属性不在 `__init__` 中，IDE/静态检查不可见 |
| `main.py:219` | `meme_summary.budget = budget_manager`（构造时传 `budget=None`，见 `main.py:160`） | 同上；漏挂载会导致预算闸门静默跳过（`meme_summary.py:135-159`） |
| `main.py:253` | `sender._ws_sender = ws_server.send_action`（**下划线私有属性跨对象写**） | `Sender` 的通道在 `sender.py:48-55` 懒建；若顺序颠倒会用到旧值 |
| `src/services/persona_manager.py:99-100` | `resolve_persona` 每次读 `getattr(self.config, "PERSONA_DEFAULT")` | 有意设计（WebUI 热更新），但使该方法的输出**依赖类外可变状态**，缓存必须按配置版本失效 |
| `src/services/blossom_memory.py:155-168` | 14 个配置在构造时快照进实例属性 | 与 `persona_manager` 的"动态读"策略不一致：同一仓库两种配置语义（一处热更新、一处冷快照） |

---


## 6. 重复逻辑与死代码候选

### 6.1 死代码 / 未接线模块清单（判定 + 引用证据）

"可达"= 从 `main.py` 的静态 import 闭包内。判定分四类：**可删 / 公开契约要留 / 仅测试用 / 需人工确认**。

| 模块 | 行数 | 可达 | 被谁引用（证据） | 判定 |
|---|---:|---|---|---|
| `old_ai_tmp.py` | 762 | ❌ | **零引用**（全仓 `rg old_ai_tmp` 命中 0；`git log --diff-filter=A` 显示由拆分提交 `239bf60` 引入 761 行） | **可删**（§6.2） |
| `src/utils/logger.py` | 16 | ❌ | **零引用**（`rg 'utils\.logger|utils/logger'` 命中 0）。文件自述为"兼容入口：旧 setup_logger 接口"（`logger.py:1`），但现状 `main.py:33` 直接用 `src.utils.logging_setup` | **可删**（低风险）；因自称"兼容入口"，删除前 **需人工确认** 是否有仓外脚本 import |
| `src/services/webui_render/__init__.py` | 43 | ✅（**任务书候选有误**） | 任何 `src.services.webui_render.X` 的导入都会执行包 `__init__`：`src/services/web_ui_assets.py:12-27`、`src/services/config_service.py:32`、`webui_render/persona.py:3-4` 等 20+ 处 | **不是死代码，要留**；但发现缺陷：`__init__.py` 的 `__all__` 列了 `hex_to_rgb` 而**未导入**（定义在 `src/services/webui_render/theme.py:189`）→ `from src.services.webui_render import *` 会 AttributeError（AST 校验脚本结论：missing in imports: ['hex_to_rgb']） |
| `src/core/name_mention.py` | 31 | ✅（**任务书候选有误**） | `src/core/message_router.py:11` `from src.core import name_mention as _name_mention`，调用点 `message_router.py:481`；文档 `docs/onebot-compatibility.md:27` | **不是死代码，要留**（`src/core` 是命名空间包、无 `__init__.py`，只按字面路径扫描会误判） |
| `src/transport/contract.py` | 192 | ✅ | `src/transport/__init__.py:22-27` 顶层 import（启动必经）；测试 `tests/test_transport_contract.py`；ADR `docs/architecture/transport-contract.md` | **公开契约要留**（Gate Q 的 8 项契约 + `check_transport_contract`） |
| `src/transport/transports.py` | 471 | ✅ | `src/transport/__init__.py:28-35` 顶层 import；`tests/test_transport_contract.py`；`docs/protocol-implementation.md:28` | **公开契约要留**，但**生产未使用**（生产走 `ws_server/ws_forward_client/milky_ws_client`，见 `docs/protocol-implementation.md:28` 自述"未迁移"） |
| `src/adapters/contract.py` | 206 | ❌ | `tests/test_adapter_contract.py:21`；`docs/architecture/adapter-boundary.md:29`；ACC 指标 `docs/architecture/acceptance-metrics.md:17`（48/48） | **公开契约要留**（适配器 12 项契约夹具注册表） |
| `src/adapters/instance.py` | 169 | ❌ | `tests/test_multi_instance.py:18,65,242`；ADR `docs/architecture/multi-instance.md:79` 明说"生产启动未改为多实例" | **需人工确认**：Gate S 交付物；若要留，建议在模块 docstring 标注"未接线"，否则每轮审计都会重复出现 |
| `src/adapters/onebot12_parser.py` | 178 | ❌ | `src/adapters/contract.py:32,137`（惰性）+ `tests/test_onebot12_adapter.py:15`、`test_protocol_roundtrip.py:61`、`test_fixtures_corpus.py:33`、`test_client_contract_matrix.py:21`；文档 `docs/onebot12-research.md:26` | **公开契约要留**（`NOT_REAL_DEVICE_VALIDATED` 骨架，任务书 §10.2 允许） |
| `src/adapters/testkit/__init__.py` + `test_protocol.py` | 9 + 182 | ❌ | `src/adapters/contract.py:171-175`（惰性）；`tests/test_pec_experiment.py:20-22`、`test_cross_protocol_equivalence.py:13`；ADR-004 `docs/architecture/test-protocol-experiment.md:46-51` | **公开契约要留**（Gate E/F 虚拟协议，PEC=0 的证据载体） |
| `src/repositories/postgres_blossom_repository.py` | 133 | ❌ | **仅测试**：`tests/test_postgres_backend.py:41-43`。生产 `main.py:118` 构造 `BlossomMemoryManager` 时**不传 repository** → `src/services/blossom_memory.py:169` 默认落到 SQLite | **需人工确认**：同类 `postgres_memory_repository` 已接线（`main.py:90-92`），花语记忆的 PG 后端漏接；要么接线，要么标注"仅测试" |
| `src/sdk/listener.py` | 64 | ❌ | **仅测试**：`tests/test_sdk_listener.py:5` | **仅测试用**（任务书禁删测试 → 模块随测试保留；若要删须与测试同步，需人工确认） |
| `src/services/storage_migrate.py` | 129 | ❌（CLI 入口） | 文档命令：`docs/development.md:105`、`docs/configuration.md:244`；测试 `tests/test_storage_backend.py:25` 导入 `_migrate_with_rollback`；自身 `storage_migrate.py:126-129` 有 `__main__` | **公开契约要留**（运维迁移工具，自带入口） |
| `src/plugins/runner/python_runner.py` | 1569 | ❌（**假阳性**） | 由 `src/plugins/runtime.py:90` 以 `create_subprocess_exec` 启动；自身 `python_runner.py:1557-1567` 有 `main()`/`__main__` | **要留**（插件运行时的独立进程入口） |
| `plugin_sdk/flowerie_sdk/*`（7 文件） | 2088 | ❌ | 插件以 `cp -r` 自带（`docs/plugin-developer-guide.md:24,826`）；运行器把插件目录加入 `sys.path`（`src/plugins/runner/python_runner.py:984`）；契约测试 `tests/test_plugin_sdk_contract.py` | **公开契约要留**（Plugin SDK，任务书硬约束） |
| `scripts/gen_api_md.py`、`scripts/multi_reply_demo.py` | 89 + 177 | ❌ | 独立脚本（`multi_reply_demo.py:153` 用 `__import__`）；`scripts/multi_reply_demo.py` 被 `docs/` 引用 | **要留**（开发工具/演示脚本，非生产路径） |
| `examples/**/*.py`（4 文件） | 1464 | ❌ | 示例插件（含 `examples/plugin-webui-test/README.md` 文档） | **要留**（对外示例） |
| `src/transport/__init__.py`、`src/adapters/__init__.py`、`src/sdk/__init__.py`、`src/repositories/__init__.py`、`src/__init__.py` | 69/32/29/6/2 | ✅ | 包初始化（被任意子模块导入触发） | **要留** |

**统计**：本次"未接线/死代码"确认为**可删 2 项**（`old_ai_tmp.py`、`src/utils/logger.py`，合计 778 行）、**需人工确认 3 项**（`adapters/instance.py`、`postgres_blossom_repository.py`、`sdk/listener.py`）、其余为公开契约或工具/示例。**任务书给出的 11 个候选里，有 2 个（`webui_render/__init__.py`、`core/name_mention.py`）实为可达模块**——这正是"禁止猜测、必须带证据"的价值所在。

### 6.2 `old_ai_tmp.py` 专项结论

| 问题 | 结论 | 证据 |
|---|---|---|
| 它是什么 | **拆分前的旧单体 AIClient**。内含 `AIClient`(15 方法, 最长 120 行)、`default_persona_text`、`_looks_like_image`，以及视觉/引战/记忆/HTTP 全套逻辑 | `old_ai_tmp.py:20-28`、`41-60`、`63-761` |
| 与现役实现关系 | 与 `src/services/ai_client.py`(413 行/14 方法) 同源但已分叉：文本相似度 **0.575**（`difflib.SequenceMatcher`）；现役多出 `extract_multi_messages` 与 `vision` 属性（`src/services/ai_client.py:16-23`），旧文件多出内联下载/视觉实现 | 脚本比对（`work/audit/`，只读） |
| 被谁引用 | **无任何引用**：全仓（含 tests/docs/scripts/examples/plugin_sdk）`rg old_ai_tmp` 命中 0 | — |
| 来源 | 拆分提交 `239bf60`（2026-08-30，"fix: 补回 effective_host/_url_for_log 的 @staticmethod（拆分遗漏）"）**新增 761 行**：提交信息是拆分收尾，却把旧文件add 进仓库；`git ls-files old_ai_tmp.py` 显示**已被 git 跟踪** | `git show --stat 239bf60` |
| 能否删 | **能删**（`git rm old_ai_tmp.py`）。风险极低：无引用、无测试依赖、不是插件 SDK 面、不被文档指向 | — |
| 附带风险 | 它是"重复实现"的污染源：全仓搜 `AIClient`/`_looks_like_image`/`describe_image` 都会命中两份，未来静态扫描（架构门禁、redos 扫描、PEC 扫描）可能误判 | `tests/test_pec_experiment.py:32` 一类"扫源码标记词"的门禁测试 |

### 6.3 重复逻辑清单（同语义多实现，带引用）

| # | 重复项 | 位置（全部引用） | 语义是否等价 | 统一建议 |
|---|---|---|---|---|
| 1 | **WS 连接/重连/事件分发骨架 ×3** | `src/transport/ws_server.py:59-92` + `139-228`；`ws_forward_client.py:63-88` + `109-181`；`milky_ws_client.py:35-80` | 行为等价（退避 5/10/20/40/60、trace_id、semaphore + `wait_for(EVENT_PROCESS_TIMEOUT)`），差异仅在"服务端 vs 客户端 vs 鉴权方式" | 抽 `src/transport/_ws_loop.py`：`backoff_delays()` + `handle_event(router, data)` + 通用 `run_with_reconnect(connect_fn, on_message)`；三个类只保留 connect 细节。**必须**由 `tests/test_ws_lifecycle.py`、`test_napcat_ws_forward.py`、`test_milky_ws_client.py`（若存在）/e2e 保护 |
| 2 | **`_note()` 完全同体** | `src/adapters/onebot_serializer.py:32-35` 与 `src/adapters/milky_serializer.py:35-38`（函数体逐字相同） | 等价 | 提到共享模块（如 `src/adapters/_notes.py`）或 `client_profile.py`；注意 note 文案被测试断言（`tests/test_onebot_serializer.py`） |
| 3 | **NOTE_* 常量重复定义** | `onebot_serializer.py:23-29` 与 `milky_serializer.py:24-28`；其中 `NOTE_INVALID/NOTE_UNKNOWN_SEGMENT/NOTE_UNSUPPORTED_SEGMENT/NOTE_DROPPED_FIELD` **字符串值完全相同** | 等价 | 与 #2 一起收敛为单一常量模块 |
| 4 | **原子写 JSON（tmp + os.replace）** | `src/repositories/env_store.py:245-254`；`src/services/group_nicknames.py:60-63`；`src/services/group_style_rules.py:44-47`；`src/plugins/manager.py:1442`；`src/plugins/runner/python_runner.py:1271`；`src/services/webui_panels/appearance_panel.py:246`（6 处） | 语义一致（原子替换），但 fsync/权限/异常清理细节不同（仅 `env_store.py:247-251` 做 fsync） | 抽 `src/utils/atomic_write.py`；本审计范围内优先统一 #2/#3 与 `group_*_store`（见 #5） |
| 5 | **两个 JSON 存储类骨架重复** | `src/services/group_nicknames.py:45-66`（`_load`/`_persist`）与 `src/services/group_style_rules.py:19-41`（同形） | 骨架等价，校验规则不同（昵称正则清洗 vs 数字键+2000 上限） | 抽 `JsonDictStore` 基类，子类只提供 `_validate(k,v)`；顺带统一日志（两者用 `logging.getLogger`：`group_nicknames.py:19`、`group_style_rules.py:15`，而全仓 48 处用 `src.utils.logging_setup.get_logger`，仅 `milky_ws_client.py:14` 与这两个文件例外） |
| 6 | **三套 SSRF 校验（同"字面量 + DNS 双闸"语义）** | `src/plugins/http_action.py:37-56`；`src/plugins/installer.py:152-160` + `353`；`src/services/mcp_client.py:38-69`；图片专用：`src/core/sanitizer.py:8`（`check_image_url`）+ `src/services/vision.py:107,131` | 语义同族但**威胁面不同**（插件下载 / 插件 HTTP / MCP server / 图片 CDN） | 抽公共 `assert_public_host(host)`（字面量 + `getaddrinfo` 结果校验），各调用点保留自己的策略差异；`blossom_memory.py:9` 已示范"复用 sanitizer 的 MCP URL 校验" |
| 7 | **重试机制两套** | 手写循环：`src/services/sender.py:107-122,134-149,178-198`（3 份相同）；`src/core/ai_gateway.py:97-282`（attempt 循环）。契约版：`src/transport/transports.py:43-52`(`RetryPolicy`)+ `310,345` | 语义不同（HTTP 发送重试 / AI 逻辑重试），但 sender 内部 3 份**完全同构** | ① sender 内抽一个 `_send_with_retry(endpoint, payload, retries)`（去掉 3 份复制）② 长期让 sender 走 `RetryPolicy`（需先给 transports 接线，风险高，不建议本阶段做） |
| 8 | **时间格式化散落 11 处** | `src/services/memory_manager.py:159`、`src/services/meme_summary.py:148`、`src/services/blossom_memory.py:202`、`src/core/message_assembler.py:343-344`、`src/core/budget_manager.py:33,64`、`src/services/webui_panels/knowledge_panel.py:37`、`src/utils/logging_setup.py:74,91`、`src/plugins/manager.py:2437`、`src/services/webui_render/…` | 语义分三类：日志时间戳 / 业务"今天"(`%Y-%m-%d` ×4) / 展示格式 | 仅需统一"业务今天"这一族（`budget_manager.py:33,64` 与 `meme_summary.py:148` 是同一语义、两地计算）→ `utils/timeutil.today_str()`；日志族建议保持原样（改日志格式会动断言） |
| 9 | **文本截断各自为政** | `src/services/file_parser.py:49-56`（`_cap`，唯一具名助手）；`src/services/sender.py:99,129,165,170`；`src/services/mcp_tool_manager.py:66`；`src/services/vision.py:62` | 语义近似（字符上限 + 省略号），参数各异 | 抽 `truncate(text, limit, suffix="…")`；**注意** `sender.py:129` 用 `"..."`、`file_parser._cap` 用中文后缀——统一会改可见输出（属"行为语义"，本阶段**只记录不改**） |
| 10 | **`_looks_like_image` 两份** | 现役 `src/services/vision.py:19-38`；死代码 `old_ai_tmp.py:41-60` | 等价（后者无调用方） | 删 `old_ai_tmp.py` 即消除 |
| 11 | **@/文本抽取两份** | 旧通道 `src/services/file_parser.py:399-413`（`extract_mention_and_text`）vs 新通道 `src/adapters/onebot_parser.py:274-296`（段扫描） | **不完全等价**：`onebot_parser.py:282-283` 注释明确指出"旧行为仅 `qq==bot_qq`" | 保留双轨（旧通道在迁移期仍需），**但应在 file_parser 方法上标注 deprecated**；不要贸然删 |
| 12 | 指标重复注册（无害） | `src/transport/ws_server.py:18-19` 与 `ws_forward_client.py:30-31` 注册同名 `received_messages_total`/`websocket_reconnect_total` | 等价 | `src/utils/metrics.py:85-91` 按 name 去重返回同一对象 → **不是 bug**，仅冗余；可删其中一份 |

### 6.4 看起来像重复、实则**不应**合并的（反向证据，避免误删）

| 项 | 位置 | 为什么不是重复 |
|---|---|---|
| `_sanitize_tool_result` vs `sanitize_untrusted_text` | `src/services/mcp_tool_manager.py:38-68` 的 `65` 行 | 前者**复用**后者，只在外面加了条目数/长度上限与"外部不可信"前缀——是正确的边界适配层 |
| `onebot_parser._fill_message` vs `milky_parser._scan_segments` | `onebot_parser.py:256-411` vs `milky_parser.py:215-318` | 两者**已共享**归一化助手（`milky_parser.py:33-40` 从 `onebot_parser` 导入，调用点 `271,274,278,297,314`），剩余差异是协议词汇差异（`mention`/`at`、`face_id`/`id`、`temp_url`/`url`），合并会制造"协议 if" |
| `onebot_serializer` vs `milky_serializer` 主体 | `onebot_serializer.py:45-249` vs `milky_serializer.py:41-156` | 段名/字段名完全不同（`milky_serializer.py:16-18` 自述差异），只应共享 #2/#3 的 note 基建 |
| `SQLiteMemoryRepository` vs `PostgresMemoryRepository` | `sqlite_repository.py:37-179` vs `postgres_memory_repository.py:14-173` | 同接口两后端（`repositories/base.py:61`），是**有意的平行实现**（`main.py:90-94` 按 `STORAGE_BACKEND` 选择） |

---

## 7. 性能热点（只找不改，全部带行号）

### 7.1 每请求重复的同步 SQLite 查询（无缓存、无 `to_thread`）

| 热点 | 调用链证据 | 量级 |
|---|---|---|
| **人格解析最多 4 次查询/请求** | `src/core/ai_gateway.py:137` → `src/services/persona_manager.py:88,93,101,105`（`get_group_persona_id` → `get_persona` → `get_global_persona_id` → `get_persona` → `get_persona(default)` → 兜底 `list_personas()`） | 每个 AI 请求 2-4 次全表/索引查询 |
| **同一请求内重复解析人格** | `src/core/ai_gateway.py:137`（`resolve_persona`）与 `ai_gateway.py:191`（`resolve_persona_id` → `persona_manager.py:110-112` 再走一遍解析链）；`src/core/message_router.py:609` 又调 `resolve_persona_name`（`persona_manager.py:114-116` 第三次） | 单条消息最多 3 轮 × (2-4) 次查询 |
| **梗知识检索每请求一次全表 terms 查询** | `src/core/ai_gateway.py:151` → `src/services/meme_knowledge_manager.py:136` → `retrieve_matches` → `meme_knowledge_manager.py:109` `self.repository.list_all_terms(group_id)` | 每请求 1 次；另有命中项 `touch_last_seen` 写库 |
| **记忆上下文每请求一次查询** | `src/services/prompt_builder.py:90` → `src/services/memory_manager.py:335` `repository.list_notes(...)` | 每请求 1 次 |
| 同步性 | 上述 repository 方法**全是同步 `def`**（如 `meme_knowledge_repository.py:26` 起、`settings_repository.py:21` 起），在 async 处理链中**直接调用、未走线程池**；对照实现：`src/services/memory_manager.py:354-356` 明确用 `to_thread` 提交写入 | 本地 SQLite 单次很快，但持锁期间会阻塞事件循环 |

### 7.2 每次调用新建 HTTP 客户端

| 位置 | 上下文 | 评价 |
|---|---|---|
| `src/services/webui_panels/config_panel.py:54`、`74`、`93` | 三个 `async with httpx.AsyncClient(timeout=10)` 在方法体内（WebUI 每个动作新建，含连接池/TLS 握手开销） | **应改**（本审计范围内的最明确一处） |
| `src/plugins/manager.py:1763`、`1781`、`2586` | 插件 HTTP 动作/下载，每次新建 | 应改（相邻模块） |
| `src/plugins/http_action.py:98` | 插件 `http_request` 每次新建 | 应改（相邻模块） |
| `src/plugins/installer.py:161` | 插件 URL 安装（一次性操作） | 可接受 |
| **已正确复用（对照）** | `src/services/file_parser.py:35,37-41`（懒建 + `is_closed` 判断）；`src/services/mcp_client.py:53-56`；`src/services/blossom_memory.py:57,89`；`src/services/ai_client.py:26`；`src/transport/transports.py:449-458`（闭包内单 session） | 说明仓库已有正确范式，属**不一致**而非能力缺失 |

### 7.3 写放大 / 重复 IO

| 热点 | 证据 | 说明 |
|---|---|---|
| **检索每命中一条 commit 一次** | `src/services/blossom_memory.py:265-266` `for h in hits: self.repository.touch(h["memory_id"])` → `src/repositories/blossom_memory_repository.py:118-124`（单条 `UPDATE` + `commit()`） | 一次检索最多 `top_k`(默认 5) 次写事务；应合并为一条 SQL |
| **每次写入都做一次治理扫描** | `src/services/blossom_memory.py:232` → `_prune`（`272-279`）→ `src/repositories/blossom_memory_repository.py:126-150`（2 次 `COUNT(*)` + 1 次 `DELETE` + `commit`） | 每次 `extract_and_store` 都跑全表计数 |
| **总结后按群再查库治理** | `src/services/meme_summary.py:126-128` `for gid in processed_groups: trim_group_to_max(...)` | 与 `meme_knowledge_manager.py:290` 的 `enforce_caps` 职责重叠（两处都会裁剪） |
| 审计日志每事件一次 open 追加 | `src/services/memory_manager.py:152-164`（`open(...,'a')` 在方法内，每次记忆写/删/替换各一次） | 高频写入路径上是额外 syscall；且文件无轮转（`src/config.py:187` 默认 `./data/audit.log`；全仓未见轮转逻辑 → 见 §8 UNKNOWN） |
| 记忆写入的多段查询 | `src/services/memory_manager.py:275`(`list_notes`) + `301`(`count_notes`) + `302-303`(`trim_notes`) + `354-356`(`to_thread(save)`) | 单次写入 3-4 次 IO，属设计使然（去重/矛盾替换需要读），暂不建议改 |
| 转发抓取缓存是**单次调用内**的 | `src/services/file_parser.py:262-268,328`（`seen_forwards` 每次调用重建） | 同一 `forward_id` 跨消息会重复抓取；改成实例级有界缓存可省 HTTP（但需 TTL，属行为改动 → 记录不动） |

### 7.4 无界 / 有界状态容器（自增且无上限 = 热点）

| 容器 | 位置 | 判定 |
|---|---|---|
| `BlossomMemoryManager._daily_extracted` | 定义 `src/services/blossom_memory.py:173`；写入 `229`；读取 `204` | ⚠️ **无界**：键是 `(group_id, day)`，历史日期条目**永不清除**（只有 `repository` 侧的记忆有 TTL，字典本身没有）→ 长期运行按"群数 × 天数"线性增长。建议：按天切换时清理旧 key（或换 `ExpiringMap(ttl=86400*2)`） |
| `MemoryManager` 审计日志文件 | `src/services/memory_manager.py:161`（append，无轮转） | ⚠️ **磁盘无界**（UNKNOWN：是否有外部 logrotate，见 §8） |
| `WebUIServer._tokens` | `src/services/web_ui.py:84`，清理在 `103-104`（≥512 时剔除过期） | ✅ 有界（正面样板） |
| `WebUIServer._login_fails` | `src/services/web_ui.py:85`，容量保护在 `127-128` | ✅ 有界 |
| `MemeKnowledgeManager._buffers` / `_buffer_activity` | `src/services/meme_knowledge_manager.py:50-51`；LRU 淘汰在 `62-68`；`deque(maxlen=buffer_per_group)` | ✅ 有界（群数上限 + 每群条数上限） |
| `MemeSummaryService._retry_count` | `src/services/meme_summary.py:75`；成功/放弃时 `pop`：`225`、`239` | ✅ 有界（仅失败中的群） |
| `McpToolManager._tool_owner` | `src/services/mcp_tool_manager.py:92`，每次 `sync_tools` 重建（`160`） | ✅ 有界（工具数） |
| `WebSocketServer._pending` | `src/transport/ws_server.py:36`，`finally: pop`（`57`） | ✅ 有界 |
| `WebSocketTransport._pending` | `src/transport/transports.py:99`，`pop` 于 `197,202,256` | ✅ 有界（且该实现未接生产） |
| `lenient` 的 `_pending` in ws_server | 同上 | ✅ |

### 7.5 同步阻塞 IO 落在 async 函数里（无 `to_thread`）

扫描口径：`async def` 体内直接出现 `open(`/`sqlite3.connect`/`self._conn.execute`/`time.sleep`/`requests.` 等（排除已用 `to_thread` 者）。

| 位置 | 阻塞调用 | 备注 |
|---|---|---|
| `src/services/vision.py:203-233`（`describe_image_file`） | `open(...)` 读本地图片 | 表情包索引路径，文件可能数 MB |
| `src/adapters/resource.py:210`（`LocalPathFetcher.fetch`） | `open(...)` 读文件 | 在 async 资源取数链里 |
| `src/services/sticker_manager.py:74-78`（`_index_file`） | `open(path,'rb').read()` + sha256 | 索引期批量调用 |
| `src/services/memory_manager.py:161`（`_audit`，被 async `append_memory_text`(`246`) 调用） | 文件 append | 高频 |
| `old_ai_tmp.py:741` | `open(...)` | **死代码**，删除即消失 |
| 相邻（不在本审计范围） | `src/plugins/manager.py:1444,1910,2553`、`src/plugins/installer.py:140` | 记录备查 |
| **正确范式对照** | `src/services/memory_manager.py:354-356`（`await asyncio.to_thread(self.repository.commit)`） | 说明仓库具备该能力，属**选择性使用** |

### 7.6 重复计算（CPU）

| 项 | 位置 | 说明 |
|---|---|---|
| 发送重试循环 3 份 | `src/services/sender.py:107-122,134-149,178-198` | 同构代码 3 份，维护成本 > 性能成本 |
| 人格解析重复（同请求 3 轮） | §7.1 | 真正的"重复计算"：同一 `(group_id)` 一次请求内被解析多次 |
| `_core_words`/`_is_contradiction` 每次写入对全部旧记忆做核心词比较 | `src/services/memory_manager.py:222-244`，循环点 `270-273` | 记忆条数上限 50（`311`），量级可控 |

---

## 8. UNKNOWN / 未验证项

以下项**未取得证据**或**未运行验证**，不得当作结论使用：

1. **运行时行为一律未验证**：本阶段零执行（未跑 pytest、未启动 bot、未连设备/协议端）。所有"行为不变"判断都基于源码与既有测试文件的**存在性**，不是测试通过记录。
2. `old_ai_tmp.py` 是否被**仓外**脚本/用户本地工具 import：仓库内零引用已证实（`rg`），仓外无法验证 → 删除前建议保留一个提交周期的 git 历史即可回退。
3. `src/utils/logger.py`（16 行兼容入口）是否有**仓外插件**依赖：仓库内零引用；插件通常自带 SDK 不依赖主仓 utils，**未验证**。
4. `postgres_blossom_repository.py` 是否**打算**接线（`STORAGE_BACKEND=postgres` 时花语记忆是否应走 PG）：代码显示未接，`docs/` 未见结论 → **需人工确认**。
5. `src/adapters/instance.py` 多实例是否在路线图内：ADR-006 说"已实施"但生产未接（`docs/architecture/multi-instance.md:79` 自述"是独立动作"）→ 归属**需人工确认**。
6. 审计日志 `./data/audit.log` 是否有外部轮转（logrotate/定时脚本）：全仓 `rg` 未见，但可能在部署侧 → **UNKNOWN**。
7. `transports.py:439` 的 `websockets_connector` 只用 `extra_headers`，而 `ws_forward_client.py:134-141` 为 websockets 14+ 做了 `additional_headers` 兼容 → 若依赖升级到 ≥14，该连接器会 `TypeError`。**未运行验证**（当前环境 websockets 版本未查），标记为静态不一致。
8. 三大 WS 连接类的**断线重连/背压**行为在真实网络抖动下是否等价：仅静态比对，**未做故障注入验证**。
9. `meme_knowledge_manager.retrieve_matches` 的 `touch_last_seen` 写库频率（每次命中一条）：未统计真实命中率 → 写放大影响**量级未测**。
10. 各 repository 的**索引覆盖**是否充分（`list_all_terms`/`list_notes` 是否走索引）：未做 `EXPLAIN QUERY PLAN` → **UNKNOWN**（建议 Phase 1 用只读方式补测）。
11. `Flowerie_bot/` 目录是 `.gitignore:34-35` 明示的"误检出的嵌套旧克隆（工作树已损坏）"，共 39 个 `.py`：**未纳入本次范围**（不是生产代码），若磁盘清理需要另立任务。

---

## 附：本次审计的可复现脚本（均在仓库外，只读）

| 脚本 | 作用 |
|---|---|
| `work/audit/graph3.py` | AST import 图（绝对/相对/命名空间包/子模块导入 + 包 `__init__` 隐式边），输出 `graph3.json`（含每文件行数、扇入表） |
| `work/audit/clsmetrics.py` | 类级度量：方法数/公共方法数/构造参数/实例属性/`getattr` 次数/最长方法/分支数 |
| `work/audit/methinfo.py` | 方法级清单（行号区间 + 入参 + IO 标记 + docstring 首行） |
| `work/audit/perf.py` | async 内阻塞调用扫描 + 有界/无界状态容器扫描 |
| `work/audit/fan.py` | 单模块扇入查询（"谁在调用它"） |

仓库状态复核命令：`git -C /storage/emulated/0/Flowerie_bot status --short`（本次审计结束时输出为空 = **零改动**）。

