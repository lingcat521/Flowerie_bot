# 重构审计报告（Phase 0：只读审计）

> 任务书：`/storage/emulated/0/Optimization.txt`（上帝类拆分 + 代码卫生 + 性能优化）。
> 阶段：**Phase 0 只读审计**（本阶段仓库零改动）。
> 证据等级：`[CODE]` 源码行号 · `[TEST]` 测试断言 · `[SCAN]` 脚本统计（AST / import 图） · `[UNKNOWN]` 未验证。
> 状态：**Phase 0 完成**（4 个只读分片全部合并：插件子系统 503 行 / core 主链路 398 行 / WebUI 与配置 555 行 / services+死代码 545 行；原始机械数据与分片报告见 refactor-audit-data/）

## 0. 结论摘要

1. **真正的上帝类只有一个：`PluginManager`**（2630 行跨度 / 81 方法 / 23 实例属性 / 85 处 self 私有调用 / 14 个职责域）`[SCAN]`。
   但它的**权限门 + 唯一副作用出口**必须保持单体语义，且 5 个测试用 AST/源码文本钉死它的符号 → 只能「部分拆」。
2. **两个"看起来像上帝类"的其实是外观，判不拆**：`PluginApi`（169 个 1-2 行转发方法，被 4 个 AST 测试 + `docs/api.md` 生成器逐方法枚举）、
   `PluginRuntime`（单一主语「一个插件子进程」）。
3. **两个「编排过载」而非「状态上帝类」**：`MessageRouter._handle_message`（229 行 / 37 分支 / 16 早退）、`AiGateway.guarded_chat`（205 行 / 九件事）。
   修法是**内部拆块 + 保留门面方法**，不是搬类。
4. **WebUI 的上帝痕迹是「上帝基类」**：11 个 mixin 本身干净（各 2-13 方法、0 实例属性、0 重名），但它们共用同一份 **17 项宿主内部面、访问 198 次（私有 159）**，
   其中 `_check_token` 一项 43 次 `[SCAN]`。
5. **`SettingsRepository` 是第二个上帝类**（God Module 型）：名字叫 settings，实际是 6~7 个数据域的 CRUD 大杂烩，被 **20 个测试文件**直接 import。
6. **模块级 import 图无环**（96 模块 / 0 组循环依赖）`[SCAN]`；47 处函数内延迟 import 属"绕环"气味而非硬违规（如 `adapters/resource.py:330-331`）。
7. **动手前必须先知道的 4 类硬约束**（§2）：文件行数上限（`message_router.py` 只剩 **7 行**、`config_service.py` 只剩 **2 行**）、AST 冻结的方法名、
   aiohttp 白名单只许缩小、测试直接触碰的私有成员清单。
8. **顺带发现 6 类真实缺陷**（§5，非重构目标；其中修 bug 会改变行为，需单独确认）：群昵称/群风格注入**从未生效**、`received_messages_total` 重复注册吞标签、
   WebUI **4 条断链**（含 2 个无鉴权 handler）、`runtime.py` 两处裸 `create_task`、若干死代码。

## 1. 判定总表（拆 / 部分拆 / 不拆）

| 目标 | 判定 | 一句话理由（标准驱动，非行数） | 风险 |
| :--- | :--- | :--- | :--- |
| `PluginManager` | **部分拆** | 9 构造依赖 / 23 属性 / 14 职责域；WebUI 宿主 512 行、action 执行 1345 行、生命周期 444 行各有独立生命周期与测试边界 —— 但「唯一副作用出口 + 唯一权限门」必须保持单体 | 高（AST 钉死符号） |
| `PluginApi` | **不拆** | 159/169 方法同形态转发、零私有辅助 → 方法数 = 接口宽度，不是复杂度；被 4 个 AST 测试与文档生成器逐方法枚举 | 高（拆即必红） |
| `PluginRunner` | **部分拆（仅叶子域）** | 11 个职责域被一条**阻塞式可重入读循环**焊死（`_readline:941` ← `_send_action_inner:958` / `_send_engine_op:1036` / `run:1538`，共享 `_req_id:922` 与 `_pump_nested:1123`） | 中（构造签名是硬接口） |
| `PluginRuntime` | **不拆** | 单一主语「一个插件子进程」，28 方法全服务于传输/请求响应/生命周期；回调经 setter 注入而非反向 import | 低 |
| `MessageRouter` | **部分拆** | 业务在 manager、IO 在 services、协议在 adapters → 它只管**编排 + 门控**；但 `_handle_message` 229 行 = "没有名字的编排方法" | 中（7 个测试文件直接构造；行数只剩 7 行） |
| `AiGateway` | **部分拆** | `guarded_chat` 205 行里熔断+预算+人格+梗+昵称+工具 payload+重试+降级+指标九件事；12 属性中 11 个是注入 provider（自有状态仅 2 个熔断容器） | 中（方法名被 AST 冻结） |
| `AIClient` | **部分拆** | 单次尝试 vs 重试/预算/熔断边界清晰，三处越界：prompt 组装+记忆读取（**每次 attempt 重复**）、回复解析、MCP 多轮循环；`_retryable/_api_backoff` 跨请求共享 | 中低 |
| `MessageAssembler` | **部分拆** | 11/13 方法是「配件→文本」；但隐私存档+保留策略与组装零共享数据，且识图逻辑重复两遍 | 低（签名不能改） |
| `ContextManager` | **部分拆** | 上下文读写/概率/查重 与 SQLite 崩溃备份（占其 60% 体积、唯一同步阻塞 IO）是两件事 | 低中 |
| `CommandHandler` / `PolicyEngine` / 6 个 manager | **不拆** | 163 行 9 方法职责单一；20 个方法全是 1-3 行委托（已是薄门面） | 低 |
| `AiGuardMixin` | **不拆，应删/内联** | 19 行纯转发壳，`_ai_allowed` 无生产调用；是历史拆分的**兼容残留**，不是「上帝类挪进 mixin」 | 低 |
| `WebUIServer` | **部分拆** | 400 行 / 4 公开方法看似薄门面，但攥着 token 表 + 登录限速 + 凭据校验 + 外观偏好 + tab 分发 + 路由表 + 生命周期 7 个域 → **上帝基类** | 中（43 处 `_check_token` + 5 种未认证响应语义） |
| 11 个 Mixin | **不拆** | 每个只做一个域、实例属性 0、方法名 0 冲突（AST 实测）→ 真横切；改组合式 handler 要重命名 80 方法 + 51 条路由，收益低 | 低 |
| `ConfigService` | **部分拆** | 25 方法里 8 个是账号与凭据域（与配置 schema 零耦合）；且 698/700 行触红线 | 中（模块级 hash/verify 被测试与 web_ui 直接 import） |
| `config_schema` / `webui_render` 包 | **不拆** | 纯数据表 / 全部无状态纯函数、按域分文件已到位 | 低 |
| `SettingsRepository` | **不拆（保留）** | 分片 D 反证：38 个方法都是**同形 DAO**（get/set/list/delete/upsert × 6~7 个表域），拆开反而破坏「单连接 + 单锁」不变量，且有 25 个导入方；父代理初判「部分拆」已按其反证撤回 | 高（不动） |
| `Sender` | **不拆** | 61 个方法里 36 个 ≤4 行、49 处 `self._post` —— 是「协议表面」而非职责堆叠 | 低 |
| `MemeSummaryService` | **部分拆** | 10 个构造参数 / 12 个实例属性（本层最接近上帝类的） | 中 |
| `FileParser` | **部分拆** | `extract_forward_messages` 122 行叠了 HTTP + 预算 + 递归 + 抽取；`decode_bytes` 7 种格式 + 安全预检 | 中 |
| `MemoryManager` | **部分拆** | 审计日志 + JSON 迁移与记忆读写异质（前者可后台化） | 低中 |
| `VisionService._download_image` | **部分拆（方法内拆块）** | 下载/校验/编码混在一个方法里 | 低 |
| `McpToolManager` / `PersonaManager` / `BlossomMemoryManager` / 两个 parser / 三个 WS 类 | **不拆** | 单域或已是薄委托；解析器间已共享助手（见 §7.2 反向结论） | 低 |
| `ToxicDetector.is_toxic` | **部分拆** | 119 行 = 90+ 关键词表 + 预检 + AI 复核；表与预检可外提为纯数据/纯函数 | 低（API 面被测试钉死） |

## 2. 硬约束（动手前必须知道）

### 2.1 文件行数上限 `[TEST]` `tests/test_web_ui_persona_knowledge.py:452-462`

| 文件 | 上限 | 当前 | 余量 |
| :--- | ---: | ---: | ---: |
| `src/core/message_router.py` | 650 | 643 | **7 行** |
| `src/services/config_service.py` | 700 | 698 | **2 行** |
| `src/services/ai_client.py` | 430 | 412 | 18 行 |
| `src/services/web_ui.py` | 430 | 400 | 30 行 |
| `src/services/web_ui_assets.py` | 120 | 51 | 69 行 |

→ 往这些文件加代码会先撞门：**必须先搬出、再改**。

### 2.2 AST 冻结的方法名 `[TEST]` 同文件 `:467-497`

- `VisionService`：`__init__` / `client` / `_url_for_log` / `describe_image` / `_describe_image_bytes` / `describe_image_file`
- `ToxicDetector`：`__init__` / `client` / `is_toxic`
- `AiGateway`：`__init__` / `guarded_chat` / `_ai_allowed` / `guarded_is_toxic` / `_get_group_breaker`
- `AccountPanelMixin`：`_render_account_page` / `_credential_info` / `_mcp_status` / `_config_status` / `_handle_panel_unregister`

### 2.5 其它"搬文件即红"的文本钉死 `[TEST]`

- `tests/test_api_sender_consistency.py:20,38,77`：解析 `manager.py` 的 `_SENDER_ACTIONS` / `*_EXT` / 命名空间
- `tests/test_api_gap_whitebox.py:38-45`：要求 8 个 `async def _ext_*` 与 8 个 `*_EXT` 名字**仍出现在 manager.py 文本里**
- `tests/test_plugin_path_injection.py:79-81`：钉死 manager.py 内恰好 4 处 `_safe_id` 与 3 处 `base = self._plugin_base(_safe_id)`（file_read / file_write / uninstall 不能搬走）
- **权限门陷阱**：`_execute_action`（`manager.py:1358-1382`）是唯一权限检查点，但 `_ext_data` / `_ext_plugin` / `_ext_memory` 有 **7 处直调 `_run_action`**（`:1453,1455,1456,1595,1699,1701,1703`）绕开门 →
  拆分时必须新增"内部派发（不判权）"通道复刻该语义，否则别名动作（`cache_get` → `kv_get`）会由"允许"变"拒绝"。

### 2.3 架构 Gate

- `tests/test_architecture_gates.py:24-41`：`KNOWN_SERVICES_AIOHTTP` **只许缩小不许增长** → 新增的 AuthService / SessionStore 不得 import aiohttp。
- `tests/test_circuit_breaker_isolation.py:130,157,209,212,214` 与 `tests/test_stress.py:66` 直接读 `router.provider_breaker / group_breakers`：删兼容别名前必须先改这些断言（**不许删用例**）。

### 2.4 依赖最广的模块与测试触碰的私有面 `[SCAN]`（205 个测试文件统计）

| 模块 | 直接 import 它的测试文件数 | 测试直接触碰的私有成员 |
| :--- | ---: | :--- |
| `src/repositories/settings_repository.py` | 20 | — |
| `src/plugins/manager.py` | 18 | `_handle_action`×30、`_runtimes`×16、`_servers`×8、`_execute_action`×8、`_manifest_of`×7、`_comm_bus`×7 |
| `src/adapters/milky_parser.py` / `onebot_parser.py` | 18 / 18 | `_assemble_quote`、`_assemble_media`、`_assemble_pending_file` … |
| `src/services/config_service.py` | 14 | `_download_image` 等 |
| `src/plugins/runtime.py` | — | `_limits`×8、`_cleanup`、`_on_exit`、`_build_command` |

另有 **39 个 src 模块没有任何测试直接 import**（含 `main.py`、`plugins/router.py`、`plugins/http_action.py`、`core/name_mention.py`、大部分 `webui_panels/*`）——
判死代码前必须查引用链（见 §7）。

## 3. 机械数据摘要 `[SCAN]`

### 3.1 God Class 候选（跨度 / 方法 / 属性 / self 私有调用）

| 类 | 位置 | 跨度 | 方法 | 属性 | self 私有调用 |
| :--- | :--- | ---: | ---: | ---: | ---: |
| PluginManager | `src/plugins/manager.py:59` | 2630 | 81 | 23 | 85 |
| PluginApi | `src/plugins/runner/python_runner.py:195` | 712 | 169 | 4 | 2 |
| PluginRunner | `src/plugins/runner/python_runner.py:908` | 647 | 42 | 11 | 38 |
| ConfigService | `src/services/config_service.py:80` | 619 | 25 | 3 | 15 |
| MessageRouter | `src/core/message_router.py:44` | 600 | 19 | 25 | 16 |
| Sender | `src/services/sender.py:15` | 498 | 61 | 6 | 7 |
| PluginRuntime | `src/plugins/runtime.py:48` | 449 | 28 | 23 | 26 |
| SettingsRepository | `src/repositories/settings_repository.py:20` | 393 | 38 | 2 | 4 |
| WebUIServer | `src/services/web_ui.py:71` | 330 | 17 | 15 | 67 |
| MessageAssembler | `src/core/message_assembler.py:17` | 372 | 13 | 5 | 11 |

### 3.2 超长 / 高分支函数 Top 12

| 函数 | 位置 | 行数 | 分支 |
| :--- | :--- | ---: | ---: |
| `PluginManager._run_action` | `src/plugins/manager.py:2152` | 330 | **105** |
| `render_persona_tab` | `src/services/webui_render/persona.py:7` | 297 | 10 |
| `main` | `main.py:64` | 236 | 16 |
| `MessageRouter._handle_message` | `src/core/message_router.py:237` | 229 | 37 |
| `serialize_segments` | `src/adapters/onebot_serializer.py:45` | 205 | 52 |
| `AiGateway.guarded_chat` | `src/core/ai_gateway.py:94` | 205 | 29 |
| `onebot_parser._fill_message` | `src/adapters/onebot_parser.py:256` | 156 | 31 |
| `validate_config` | `src/config.py:454` | 152 | 55 |
| `PluginManager._ext_data` | `src/plugins/manager.py:1444` | 144 | 42 |
| `build_system_prompt` | `src/services/prompt_builder.py:62` | 140 | 15 |
| `render_knowledge_tab` | `src/services/webui_render/knowledge.py:7` | 137 | 6 |
| `extract_forward_messages` | `src/services/file_parser.py:228` | 122 | 31 |

### 3.3 单文件体量 Top 8（代码行）

| 文件 | 代码行 |
| :--- | ---: |
| `src/plugins/manager.py` | 2549 |
| `src/plugins/runner/python_runner.py` | 1255 |
| `src/services/config_service.py` | 626 |
| `src/core/message_router.py` | 504 |
| `src/plugins/comm.py` | 483 |
| `src/config.py` | 470 |
| `src/plugins/runtime.py` | 430 |
| `src/services/sender.py` | 425 |

### 3.4 依赖与分层事实

- **模块级 import 图无环**：96 模块 / 0 组循环依赖；47 处函数内延迟 import（清单见附录数据）。
- 跨层依赖：`transport → core`（`ws_server.py` → `core/message_router.py`）；`adapters → sdk` 5 处（`onebot/adapter.py`、`onebot/transformer.py`）；
  **`core ↔ services` 双向**（core→services 18 处、services→core 7 处）。

## 4. 主链路与插件子系统的职责域事实

### 4.1 消息主链路（3 条传输入口 → 状态更新）

`ws_server.py:208-213` / `ws_forward_client.py:169-172` / `milky_ws_client.py:58-61` → 解析 `message_router.py:185` → 分派 `:193-199` →
**#5~#24 全部挤在 `_handle_message`（`:237-465`）**：白名单 / 去重 / 组装（`:282` → `message_assembler:35-77`）/ 指令（`:289` → `command_handler:26`）/
复读（`:293`）/ 引战（`:301`）/ 建模（`:312`）/ 上下文（`:328`）/ 梗缓冲（`:332`）/ 强制记忆（`:339`）/ 回复决策（`:357` → `_should_reply:473`）/ 冷却（`:362`）/
上下文+prompt 构造（`:381-390`）/ AI 准入（`:393` → `ai_guard_mixin:9-17` → `ai_gateway:94-298` → `ai_client:41-157`）/ 记忆回写（`:407`）/ 兜底（`:425`）/
查重（`:430`）/ 表情包（`:434`）/ 发送（`:460` → `reply_dispatch:18-50`）。

**结论**：实现层已分层，缺的是「顺序 / 门控 / 降级」的独立载体 —— 所以是"编排方法过载"，不是"上帝类什么都干"。

### 4.2 `MessageRouter` 25 个实例属性的归属（子代理 B 实测 + 我的复核）

| 类别 | 数量 | 例子 / 建议归属 |
| :--- | ---: | :--- |
| 外部注入依赖 | 6 | config / sender / memory_manager / persona_manager / sticker_manager / plugin_manager |
| **死引用**（AST reads=0） | 3 | `file_parser:78`、`resource_fetcher:100`、`blossom_memory:124` |
| 共享全局状态别名 | 1 | `global_state:83` → 其中 `groups` 应归 `GroupRegistry`、`pending_files` 应归 `PendingFileCache` |
| 自建子系统 | 3 | `assembler:101`、`commands:104`、`ai_gateway:112` |
| 任务并发 / 并发闸 | 2 | 信号量 → 建议收敛为 `ConcurrencyGate` |
| 熔断兼容别名 | 2 | `:126-127`（`provider_breaker` / `group_breakers`，被 5 处测试直接读） |
| 其它 | 8 | 边界解析器 / 插件 / 6 个可选服务 |

构造契约之外还有 `main.py:239-240` 的 2 处后置 `setattr`。

### 4.3 `PluginManager` 的 14 个职责域（子代理 A 实测）

| 域 | 规模 | 独立生命周期 / 可独立测试 |
| :--- | :--- | :--- |
| **WebUI 宿主**（文件空间 / 页面渲染 / WebUI Protocol） | 512 行（18.5%） | 是（8 个测试文件真 manager + 真子进程） |
| **action 执行**（唯一副作用出口 + 权限门） | 1345 行，`_run_action` 330 行/105 分支 | **否 —— 必须保持单体语义** |
| 生命周期（discover/enable/disable/uninstall/refresh/start_all/shutdown） | 444 行 | 是 |
| 定时任务（register/cancel/list/loop/dispatch） | ~200 行 | 是（当前无专属测试 → 缺口） |
| 插件 KV / 数据面（`_ext_data`、metrics、health、logs） | ~250 行 | 是 |
| 社交/媒体扩展（`_ext_social`） | ~150 行 | 是 |
| HTTP 扩展（`_http_ext` + SSRF） | ~120 行 | 是 |
| MCP 扩展（`_ext_mcp`） | ~80 行 | 是 |
| 声明式插件（rules/match） | ~150 行 | 是 |
| 插件间通信编排 | ~100 行 | 是（router/bus 已独立） |
| 安装器编排 / 权限批准 / manifest 缓存 / 调度记账 / 事件分发 | 其余 | 混合 |

## 5. 本次审计发现的真实缺陷（非重构目标；修 bug 会改变行为，需单独确认）

| # | 缺陷 | 证据 | 影响 |
| ---: | :--- | :--- | :--- |
| 1 | **群特色昵称 / 群专属发言规则从未生效** | `ai_gateway.py:189,198` 判 `kwargs.get("group_id")`，但 `group_id` 是 `guarded_chat` 的**位置参数**（`:94`），且 94-190 行内无回填；生产与测试调用点全部用位置参数（`message_router.py:393/622`、`tests/test_stress.py:62` 等） → 两处 if 恒假 | 群昵称/群风格功能实际不可用（用户可见） |
| 2 | **`received_messages_total` 重复注册吞标签** | `message_router.py:40`（无标签）与 `ws_server.py:18`（带 `post_type`）同名注册；`registry.counter()`（`metrics.py:84-91`）先到先得返回首个实例 → `ws_server.py:206` 的 `inc({"post_type":…})` 被 `_label_key` 静默丢弃 | 监控数据缺 post_type 维度 |
| 3 | **WebUI 4 条断链** | ①`main.py:193,240` 建了 `group_style_rules` 但 `WebUIServer(...)`（`:204-209`）未注入 → 面板 `_style_rule_store` 恒 None；②`webui_render/nicknames.py:74` 表单 POST `/panel/nicknames`（51 条路由中无此路由，我已独立核对）；③`knowledge.py:137` 表单 POST `/panel/knowledge/config`（路由表只有 add/clear/delete/save/view）；④`plugin_dsl.py:151,255` 默认 `/panel/plugin-actions` 无路由 | 表单提交 404 / 保存永远返回未初始化 |
| 4 | **2 个 panel handler 无鉴权** | `nickname_panel.py:41,69` 是全项目仅有的两处未调用 `_check_token` 的 panel handler；若按 ② 直接补路由会变成未认证写入口 | 安全 |
| 5 | **`runtime.py` 两处裸 `create_task`** | `runtime.py:406`（`_handle_action_line_sem`）与 `:411`（`_handle_engine_op_sem`）任务引用未保存、`_cleanup()`（`:182`）也不追踪 → 与上一轮修的 manager 侧 `Task was destroyed` 同类 | 并发清理 + 异常丢失 |
| 6 | **插件 `ai_chat` 绕过 AiGateway** | `plugins/manager.py:2399` 直连 `AIClient.chat_once`；但 `permissions.py:47` 注释写明「独立于聊天预算，务必自限频」→ **刻意设计**；真正问题是 `ai_gateway.py:7` docstring 声称「统一所有消耗 AI 调用的入口」**与实现不一致** | 文档卫生项 |
| 7 | **两套并存的插件间通信通道**（安全语义分叉） | 新：`plugin.call/emit/cancel`（`manager.py:1307-1337` → `router.py:230/340/388`，有权限判定 + hop 环保护 + 可协商超时 + 统计）；旧：action `plugin_call/plugin_event/plugin_service`（`manager.py:1658-1693` → `_runtime_hook_call("on_plugin_event")`，**硬编码 timeout=3.0、无 call/emit 权限判定、无环保护、无统计**）。两者都在权限表里、都可能被插件调用 | 重复逻辑 + 安全语义分叉（Phase 0 只登记，收敛会改行为） |
| 8 | **不可达分支**：`group_title` / `group_honor` / `like` 的族分支与内联 webhook 分支被 `_SENDER_ACTIONS` 抢先生效 | 分派优先级 sender 表最先（`manager.py:2154`） | 死分支（卫生项） |
| 9 | 死代码（插件子系统） | `python_runner.py:970 _send_action_safe`（0 调用）、`manager.py:410 plugin_webui_page_file`（0 引用）、`_plugin_services` 只写不读（`:72/1665`）、`protocol.py` 的 `value_size/all_methods/group_of/valid_config_key`（0 引用）、`webui_security.py:56 TAG_ATTRS["img_"]=frozenset()` 疑似笔误 | 卫生项 |
| 10 | 重复逻辑 | `installer.py:346` vs `http_action.py:46` 两份 `_check_dns`；`manager.py:2242 get_group` vs `:2442 get_group_info`；`_webui_operator_config`（`:501-504`）与 engine `config.get`（`:1302-1305`）逐字相同 | 卫生项 |
| 11 | `webui_render/__init__.py` 的 `__all__` 列了**未导入**的 `hex_to_rgb`（实际定义在 `theme.py:189`） | 分片 D 实测 | `from src.services.webui_render import *` 会 `AttributeError`（卫生项：补 import 或删该项） |

## 6. 性能热点（只定位，未做 benchmark；Phase 4 才动手）

| # | 热点 | 位置 | 判定 |
| ---: | :--- | :--- | :--- |
| P1 | 引战关键词表**每次调用重建**（90+ 条 + 正则编译 + 逐词 NFKC） | `toxic_detector.py:32-70` | 纯计算重复，可外提为模块级常量 |
| P2 | **重试循环内重复 IO**：每次 attempt 重算人格/知识/昵称/工具 payload；最坏 4 倍（`AI_MAX_RETRIES=3`），含每次 attempt 一次 embedding HTTP | `ai_gateway.py:172-207` | 高价值（拆 `AiAttemptPreparer`） |
| P3 | **每 attempt 读记忆**：`ai_client.py:88-93` → `prompt_builder.py:88-97` → `memory_manager.py:333-351`（两次 SQLite） | 同上 | 与 P2 同源 |
| P4 | **上下文先清洗后截断**：每条 13 个正则 × 150 条，然后才截断 | `context_manager.py:39-48` + `prompt_builder.py:78-82` | 顺序反了 → 白洗 |
| P5 | `get_context_text` + `build_sticker_context`（每条一次 SELECT）在**预算闸门之前**执行 | `message_router.py:381-390` vs `ai_gateway.py:167` | 预算拒绝时白做 |
| P6 | **同步阻塞事件循环**：上下文全表重写、每次消息写盘 + listdir、记忆/人格 SQLite | `context_manager.py:263-307`、`message_assembler.py:331-387`、`memory_manager.py:333-351`、`persona_manager.py:88-105` | 对照 `memory_manager.py:356` 已用 `to_thread` |
| P7 | **HTTP keepalive 被关**：`max_keepalive_connections=0` → 每次 AI 调用重新握手 | `ai_client.py:29` | 一行配置，收益直接 |
| P8 | 插件侧 HTTP 每次新建 client（`http_request` / `mcp_call` / 下载） | `plugins/http_action.py:98`、`manager.py:1763,1781,2586` | 核心链路（Sender/AIClient）已合理，仅插件侧 |
| P9 | async 内同步 `open()` 5 处真候选（含日志 `f.readlines()[-50:]` 整文件读入） | `adapters/resource.py:223`、`sticker_manager.py:76`、`vision.py:221`、`manager.py:1566,2606` | 明细见附录 perf 数据 |
| P10 | 插件事件投递 `await` 在消息处理之前且占用信号量 | `message_router.py:187-191` | 可能阻塞主链路 |
| P11 | **每入站事件一次全表 SQL**（`dispatch_event`），每 action 再一次 | `manager.py:1097`（← `message_router.py:187-189`）、`:1361` | 插件表全表扫描 |
| P12 | `get_plugin` 是 **O(n) 线性查找**，被 9 处调用 | `manager.py:695` | 插件多时放大 |
| P13 | `_manifest_of` **缓存命中仍重新序列化** | `manager.py:660` | 纯浪费 CPU |
| P14 | WebUI 存储快照最多 **200 次子进程往返** | `manager.py:506-522` | 面板卡顿 |
| P15 | `webui_loader.py:78/86` 阻塞读文件（async 内） | `webui_loader.py:78,86` | 与 P9 同类 |
| P16 | **每请求 2-4 次同步 SQLite 人格查询**，且同一请求内解析 3 轮 | `ai_gateway.py:137` → `persona_manager.py:88,93,101,105`；`ai_gateway.py:191` → `persona_manager.py:110-112`；`message_router.py:609` | 高价值（同请求缓存即可） |
| P17 | `list_all_terms` **每请求全表扫描** | `ai_gateway.py:151` → `meme_knowledge_manager.py:109` | 中 |
| P18 | **写放大**：每命中一条 commit 一次 + 每次写入跑治理（两次 `COUNT(*)`） | `blossom_memory.py:265-266` → `blossom_memory_repository.py:118-124`；`:232` → `:272-279` → `repo:126-150` | 中 |
| P19 | **无界状态**：`_daily_extracted`（(group,day) 键**永不清除**）+ 审计日志 append **无轮转** | `blossom_memory.py:173`；`memory_manager.py:152-164` | 真实风险（内存/磁盘单调增长） |
| P20 | 有界正面样板（**勿动**） | `web_ui.py:103-104,127-128`、`meme_knowledge_manager.py:62-68`、`ws_server.py:57` | 保留 |



> 结论口径：以上均为**静态定位**。Phase 4 只做有证据的改动；没有 benchmark 就只写「减少了重复计算 / 重复 IO」，**不写百分比**。

## 7. 死代码与重复逻辑

判定口径：**只统计引用证据，不凭感觉删**（可达性 = 从 main.py 出发的静态 import 闭包；全仓 367 个 py，可达 138）。

### 7.1 死代码与未接线清单

| 类别 | 文件（行数） | 引用证据 | 判定 |
| :--- | :--- | :--- | :--- |
| **可删** | `old_ai_tmp.py`（762） | 全仓零引用（tests/docs/scripts 皆无）；它是**拆分前的旧单体 AIClient**（15 方法、最长 120 行），与 `src/services/ai_client.py` 相似度 0.575，由拆分提交 `239bf60` 遗留 | 可删（`git rm`，风险极低；顺带消除静态门禁污染，如 `test_pec_experiment.py:32` 的源码标记扫描） |
| **可删** | `src/utils/logger.py`（16） | `git grep "utils.logger"` = 0 | 可删（自述是旧 `setup_logger` 兼容入口 → 建议人工确认 1 分钟） |
| 仅测试用 | `src/sdk/listener.py`（64） | `tests/test_sdk_listener.py:5`、`test_sdk_plugin_lib.py` | 待确认（SDK 公开面） |
| **公开契约要留** | `src/transport/contract.py`（192）+ `transports.py`（471） | 被 `transport/__init__.py:22-35` 顶层 import = **启动必经**；但生产路径未用；`docs/protocol-implementation.md:28` 自述"未迁移" | 保留（要么接线、要么连同 `__init__` 一起退役 —— 单独立项） |
| 公开契约要留 | `src/adapters/contract.py`（206）、`onebot12_parser.py`（178）、`adapters/testkit/*`（191） | `test_adapter_contract.py:21`、`contract.py:32/171`、ACC 指标 48/48 | 保留（OneBot12 已标 `NOT_REAL_DEVICE_VALIDATED`） |
| 公开契约要留 | `src/services/storage_migrate.py`（129） | `docs/development.md:105` 是文档化 CLI + `test_storage_backend.py:25` | 保留 |
| 公开契约要留 | `plugin_sdk/flowerie_sdk/*`（2088）、`scripts/` + `examples/`（1730） | `python_runner.py:984` 把插件目录加入 `sys.path`；文档多处引用 | 保留 |
| 需人工确认 | `src/adapters/instance.py`（169） | 仅 `tests/test_multi_instance.py`；ADR-006 称"已实施"但 `docs/multi-instance.md:79` 自述生产未接线 | 需人工确认 |
| 需人工确认 | `src/repositories/postgres_blossom_repository.py`（133） | **仅** `tests/test_postgres_backend.py:41`；`main.py:118` 构造 `BlossomMemoryManager` 不传 repository → 落 SQLite；而 `postgres_memory_repository` 已接线 `main.py:90-92` | 需人工确认（平行实现待接线 或 删除） |
| 假阳性 | `src/plugins/runner/python_runner.py`（1569） | 由 `runtime.py:90 create_subprocess_exec` 启动 | **不可删**（独立进程入口） |

> **修正我早先（父代理快速扫描）的两处误判**：`src/services/webui_render/__init__.py` 与 `src/core/name_mention.py` **都不是死代码** ——
> 前者是包 `__init__`（任何 `webui_render.X` 导入都会执行它），后者被 `message_router.py:11` 以 `from src.core import name_mention` 形式导入（按模块字面路径扫描会漏）。
> 教训：可达性判断必须按**真实 import 语义**，不能只做字符串匹配。

### 7.2 重复逻辑（含"勿合并"的反向结论）

| 重复 | 位置 | 建议 |
| :--- | :--- | :--- |
| **WS 连接/重连/事件分发骨架 ×3**（退避 5/10/20/40/60 + semaphore + wait_for 全同构） | `ws_server.py:59-92,139-228` / `ws_forward_client.py:63-88,109-181` / `milky_ws_client.py:35-80` | 抽 `_ws_loop.py`（Phase 3） |
| `_note()` 逐字同体 + 4 个 `NOTE_*` 常量值相同 | `onebot_serializer.py:32-35` vs `milky_serializer.py:35-38` | 共享 note 层 |
| 原子写（tmp + `os.replace`）×6 | `env_store.py:245-254`、`group_nicknames.py:60-63`、`group_style_rules.py:44-47`、`manager.py:1442`、`python_runner.py:1271`、`appearance_panel.py:246` | 抽工具函数 |
| 两个 JSON store 同骨架（且用 `logging.getLogger`，而全仓 48 处用 `get_logger`） | `group_nicknames.py:45-66` vs `group_style_rules.py:19-41` | 抽基类/复用 store |
| SSRF 双闸 3 套 | `http_action.py:37`、`installer.py:152-160,353`、`mcp_client.py:38-69` | 统一到一处（安全语义必须一致） |
| sender 3 份同构重试 vs 契约版 `RetryPolicy`（生产未用） | `sender.py:107-122,134-149,178-198` vs `transports.py:43-52` | 二选一收敛 |
| 业务"今天"日期 4 处各算 | `budget_manager.py:33,64`、`meme_summary.py:148`、`message_assembler.py:343` | 抽 `today()` |
| 完全同形函数体 | `webui_panels/plugin_panel.py:233/242`、`transport/transports.py:270/406` | 合并 |
| 配置层双份字段清单（已漂移 2 个字段） | `src/config.py`（Settings 173 字段）vs `src/services/config_schema.py`（171 字段） | 单源化（Phase 3） |
| 两份 `_check_dns` / `get_group` vs `get_group_info` / `_webui_operator_config` vs engine `config.get` | `installer.py:346` vs `http_action.py:46`；`manager.py:2242` vs `:2442`；`:501-504` vs `:1302-1305` | 合并（Phase 3） |

> **反向结论（勿合并，已核实）**：`mcp_tool_manager.py:38-68` 已复用 `sanitize_untrusted_text`（`:65`）；`milky_parser` 已复用 `onebot_parser` 的归一化助手（`milky_parser.py:33-40` → `271,274,278,297,314`）；
> **适配器层段处理无重复实现**（`onebot_parser._fill_message` 与 `milky_parser._scan_segments` 结构平行但词汇不同，共享助手已抽）；`serialize_segments`（205 行）职责单一（出站字段按 ClientProfile 收敛），**不建议改分派结构**（测试直接断言 note 文案）。

### 7.3 仓库卫生

- 根目录 `sqlite:` 误建目录、`src/core/newdir` 空目录、`old_ai_tmp.py`（见 7.1）
- `Flowerie_bot/` 嵌套旧克隆：**含拆分前的 `message_router.py`，会污染 grep/AST 工具**（本次审计脚本一律用 `git ls-files` 规避；后续工具也必须排除）
- `src/services/webui_render/__init__.py` 的 `__all__` 列了**未导入**的 `hex_to_rgb`（实际定义在 `theme.py:189`）→ `from ... import *` 会 `AttributeError`（真缺陷，见 §5）

## 8. Phase 1 方案（草案；动手前需用户确认）

### 8.1 顺序（先修已知缺陷，再拆最大类）

| 步 | 内容 | 风险 | 回滚 |
| ---: | :--- | :--- | :--- |
| P0-1 | `runtime.py` 两处裸 `create_task` 改为登记 + `_cleanup()` cancel/await（与 manager 侧 `_drain_shutdown_tasks` 同模式） | 低 | 单 commit revert |
| P0-2 | WebUI 断链修复（`group_style_rules` 注入 + 2 条缺失路由 + 2 处 handler 补 `_check_token`；DSL 默认 action 由调用方显式传入） | 中（行为变化） | 4 个独立 commit |
| P0-3 | 删 `AiGuardMixin`（19 行壳）并修正 `ai_gateway.py:7` docstring（插件 `ai_chat` 走独立通道） | 低 | 单 commit |
| 1-1 | 外移 `PluginScheduler` → `src/plugins/scheduler.py`（纯搬移 4 方法 + 2 个 dict） | 低 | 单 commit |
| 1-2 | 外移 `PluginWebUIHost` → `src/plugins/webui_host.py`（512 行；manager 保留 9 个同名委托） | 中 | 分段提交，可逐段 revert |
| 1-3 | `_run_action`（330 行/105 分支）按 action 族拆到 `src/plugins/actions/`，**权限门与拒绝语义保持单点** | 高 | 按族提交 |

### 8.2 第一步（PluginScheduler）细化

- **拥有**：`schedule_register` 的 kind 校验（`manager.py:2334-2346`）、同插件同名覆盖（`:2348-2350`）、`_schedule_loop`(`:2491`)、`_dispatch_schedule`(`:2524`)、`_cancel_schedule`(`:2536`)。
- **状态**：`_schedules`(`:89`)、`_schedule_tasks`(`:94`) 迁出，scheduler 成为唯一 owner。
- **注入**：`dispatch(sid)` 回调 + logger；manager 保留 `cancel_all_schedules()`(`:2545`) 作为委托（`shutdown` `:1016` 不变）。
- **保护**：`tests/test_plugin_manager.py`、`tests/test_graceful_shutdown.py`、`tests/test_api_gap_blackbox.py`；**新增** scheduler 专属用例（幂等覆盖 / interval 边界拒绝 / 越权 cancel 拒绝 / shutdown 后无残留 task）。

### 8.3 Phase 1 明确不碰

- `PluginApi`（接口宽度，且被 4 个 AST 测试与文档生成器枚举）
- `PluginRuntime`（单主语）
- 权限门 / `_execute_action` 的拒绝语义（`manager.py:1354-1356` 原样回传 `denied:True`）
- 任何被 §2.2 AST 冻结的名字、被 §2.4 列出的测试私有面
- 行数上限文件（`message_router.py` / `config_service.py`）在 Phase 1 一律不加代码

### 8.4 验收标准（每步都要满足）

1. `bash work/verify.sh`（语法 / 链接 / 核心测试子集）本地通过；
2. CI 三项（CI / Acceptance / Push on main）全绿；
3. 不新增 `# noqa`、不放宽 Ruff 规则、不删测试；
4. 每步一个 commit，commit message 写清"搬了什么 / 为什么 / 怎么回滚"。

