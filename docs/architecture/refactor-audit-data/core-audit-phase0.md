# Phase 0 只读审计报告 — 消息主链路 core/（上帝类拆分 + 代码卫生 + 性能）

> 审计对象：`/storage/emulated/0/Flowerie_bot`（Python / Flowerie QQ Bot）
> 审计范围：`src/core/*` + `src/services/{ai_client,prompt_builder,toxic_detector}.py` + 相关 models/utils/main 装配点
> 审计方式：**只读**。全量阅读源码 + AST 静态度量 + 全仓 grep 交叉验证；**未修改仓库任何文件**（`git status --porcelain` 为空可证），**未运行测试**（跑 pytest 会在仓库内写 `.pytest_cache`，属"会改仓库"的操作）。
> 证据约定：所有结论附 `文件:行号`；无法静态确认的一律进 §9 UNKNOWN。
> 行数口径：**总行数** = `wc -l`；**代码行** = 非空且非 `#` 注释行；**类行数** = 类定义起止行跨度。

---

## 1. 范围清单（文件 → 行数）

### 1.1 主链路 core/（19 个文件，2846 总行）

| 文件 | 总行 | 代码行 | 类数 | 备注 |
|---|---:|---:|---:|---|
| src/core/message_router.py | 643 | **504** | 1 | 任务书口径 504 = 代码行 ✅ |
| src/core/message_assembler.py | 388 | 318 | 1 | 任务书 372 = **类跨度**（L17-388） |
| src/core/ai_gateway.py | 332 | **270** | 1 | 任务书 270 = 代码行 ✅ |
| src/core/context_manager.py | 307 | 280 | 1 | 任务书 292 = 类跨度（L16-307） |
| src/core/sanitizer.py | 242 | 210 | 0 | 纯函数模块（5 个公共函数） |
| src/core/command_handler.py | 184 | **163** | 1 | ✅ |
| src/core/policy_engine.py | 131 | 95 | 1 | 门面 |
| src/core/reply_plan.py | 122 | 96 | 1 | ReplyPlan + 2 模块函数 |
| src/core/budget_manager.py | 75 | 58 | 1 | |
| src/core/active_chat_manager.py | 68 | 57 | 1 | |
| src/core/repeat_detector.py | 61 | 50 | 1 | |
| src/core/reply_sender.py | 59 | 50 | 1 | |
| src/core/cooldown_manager.py | 56 | 44 | 1 | |
| src/core/reply_dispatch.py | 50 | **40** | 1 | 任务书 40 = 代码行（总行 50） |
| src/core/memory_parser.py | 49 | 42 | 1 | |
| src/core/name_mention.py | 30 | 27 | 0 | 纯函数 |
| src/core/ai_guard_mixin.py | 25 | **19** | 1 | 任务书 19 = 代码行 ✅ |
| src/core/poke_manager.py | 24 | 18 | 1 | |
| src/core/newdir/ | — | — | — | **空目录**（残留，见 §7） |

### 1.2 直接相关 services/ 与装配点

| 文件 | 总行 | 代码行 | 备注 |
|---|---:|---:|---|
| src/services/ai_client.py | 412 | **361** | 任务书 361 ✅ |
| src/services/prompt_builder.py | 201 | 166 | 模块级纯函数（build_system_prompt 类跨度 L62-201 = 140 行 ✅） |
| src/services/toxic_detector.py | 144 | 128 | is_toxic 方法 L26-144 = **119 行** ✅（任务书 119 指方法长） |
| src/services/{memory_manager,persona_manager,prompt_manager,sticker_manager,group_nicknames,group_style_rules}.py | 356/272/70/142/135/72 | 307/228/54/117/110/60 | 被主链路直接依赖的 IO 服务 |
| src/models.py | 77 | 60 | GroupState / GlobalState / GroupMessage |
| src/utils/{expiring_map,task_manager,circuit_breaker,metrics}.py | 100/90/110/148 | 81/74/93/119 | 状态生命周期与任务基建 |
| main.py | 309 | 242 | 组合根（L125 起） |

### 1.3 约束性测试（拆分的"门"）

| 门 | 位置 | 内容 |
|---|---|---|
| 行数上限 | `tests/test_web_ui_persona_knowledge.py:443-465` | **src/core/message_router.py ≤ 650 行**（当前 643，仅余 7 行！）；ai_client.py ≤ 430（当前 412） |
| API 面冻结 | `tests/test_web_ui_persona_knowledge.py:467-497` | AiGateway 必须保留方法名 `__init__/guarded_chat/_ai_allowed/guarded_is_toxic/_get_group_breaker`（AST 级检查，L495-496） |
| 架构 Gate A/B/P | `tests/test_architecture_gates.py:56-104` | core 不得 import 传输库；协议分支基线只许缩小 |
| 行为回归 | `tests/test_router_regression.py`（L128 构造 Router）、`test_ai_reliability.py`、`test_concurrency.py`、`test_stress.py`、`test_bounded_state.py`、`test_circuit_breaker_isolation.py`（L130/157/209/212/214 直接读 router 属性）、`test_multi_reply_{core,dispatch,e2e,protocol,sdk}.py`、`test_graceful_shutdown.py:5-32`、`test_name_mention_reply.py`、`test_native_reply_tool.py` | 详见 §5.4 |

---

## 2. 真实流水线（事件进入 → 状态更新）

入口有 **3 条传输通道**，都在会话信号量 + 单条超时内调用同一入口：`ws_server.py:208-213`、`ws_forward_client.py:169-172`、`milky_ws_client.py:58-61`。

| # | 步骤 | 现有负责人（文件:行） | 是否与其它职责挤在同一方法 |
|---|---|---|---|
| 1 | 并发闸门 + 单条超时 | `ws_server.py:208`（`process_semaphore`）、`:209-212`（`wait_for`） | 独立（传输层） |
| 2 | 边界解析 raw → InternalEvent | `message_router.py:185` → `src/adapters`（OneBotEventParser） | 独立 |
| 3 | 插件事件投递 | `message_router.py:187-191` + payload `201-230` | 与"事件分派"挤在 `process_event`（17 行/2 职责） |
| 4 | 事件分派（message/notice/其它） | `message_router.py:193-199` | 同上 |
| 5 | 群/私聊过滤 + 群白名单 | `message_router.py:238-242, 251-255` | **挤在 `_handle_message`** |
| 6 | 段格式兼容规范化 | `message_router.py:257-263` | 挤 |
| 7 | 消息去重（processed_msg_ids） | `message_router.py:273-279` → `ContextManager.get_group_state` `context_manager.py:24-27` | 挤 |
| 8 | 消息组装（识图/转发/卡片/文件/存档） | `message_router.py:282-284` → `message_assembler.py:35-77` | 实现已独立；**调用与门控挤在 `_handle_message`** |
| 9 | 指令判断 | `message_router.py:289-290` → `command_handler.py:26-54` | 实现独立 |
| 10 | 复读检测 | `message_router.py:293-298` → `repeat_detector.py:32-61` | 挤（且回写状态内联 `:296-297`） |
| 11 | 引战检测（预算放行才调） | `message_router.py:301-309` → `ai_guard_mixin.py:23-25` → `ai_gateway.py:312-319` → `toxic_detector.py:26-144` | 挤（冷却+发送内联） |
| 12 | 构造 GroupMessage | `message_router.py:312-325` | 挤 |
| 13 | 写上下文 | `message_router.py:328` → `context_manager.py:30-37` | 挤 |
| 14 | 梗知识缓冲 | `message_router.py:332-333` → `meme_knowledge_manager.py:57-70` | 挤 |
| 15 | 强制记忆（静默，先于回复决策） | `message_router.py:339-354` → `memory_parser.py:28-49` → `sanitizer.validate_memory_content` → `memory_manager.append_memory_text` `memory_manager.py:246-331` | 挤（含**第一条记忆写入路径**） |
| 16 | 回复决策（@/回复/点名/概率） | `message_router.py:357` → `_should_reply` `473-485` → `name_mention.py:9-30` + `context_manager.py:64-94` | 挤 |
| 17 | 防刷/冷却（机器人+用户） | `message_router.py:362-376` → `cooldown_manager.py:25-44` | 挤 |
| 18 | 上下文文本 + 用户消息构造（含表情包上下文） | `message_router.py:381-390` | 挤（**先构造、后准入**，见 §8 P5） |
| 19 | AI 准入与调用 | `message_router.py:393-399` → `ai_guard_mixin.py:9-17` → `ai_gateway.py:94-298`（熔断 `111-127`、预算 `167-170`→`budget_manager.py:27-60`、人格 `136-147`、梗注入 `149-153`、重试 `164-276`、熔断回写 `277-298`）→ `ai_client.py:41-157`（prompt 组装 `88-93`→`prompt_builder.py:62-201`，记忆读取 `88-97`） | 已分层；但"重试内每 attempt 重复组装"与"失败分类标志"跨对象（见 §6/§8） |
| 20 | 记忆回写（模型 MEMORY_JSON） | `message_router.py:407-422` → `memory_parser.py:13-26` → `validate_memory_content` → `append_memory_text` | 挤（**第二条记忆写入路径**，与 #15 门控不同） |
| 21 | 兜底回复 | `message_router.py:425-426` | 挤 |
| 22 | 回复查重 | `message_router.py:430-432` → `context_manager.py:97-113` | 挤 |
| 23 | 表情包分支（解析/冷却/带图发送） | `message_router.py:434-458` → `sticker_manager.py:115-139` | 挤 |
| 24 | 发送（单条/多条 + 间隔 + 逐条记录） | `message_router.py:460` → `reply_dispatch.py:18-50` → `reply_plan.plan_from_config` `110-122` → `reply_sender.send_plan` `26-59` → `sender` | 实现独立 ✅ |
| 25 | 状态更新（连续回复/上下文/最近回复） | 正式路径 `reply_dispatch.py:36-43`；**另有两处手写重复** `message_router.py:296-297`（复读）、`:454-456`（表情包） | 三处分散（见 §7 D2） |

**结论（问题 1）**：真正"挤在一个方法里"的是 **#5–#24 的顺序编排与门控**，全部落在 `MessageRouter._handle_message`（L237-465，229 行，**37 个 `if`**，57 个条件节点，**16 个 `return None`** 早退点，33 个局部变量，调用 9 个协作者：policy_engine×18 / sticker_manager×8 / config×3 / sender×3 / memory_manager×2 / global_state×2 / assembler / commands / meme_manager）。各步骤的**实现**大多已拆到独立类，但"谁先谁后、什么条件早退、失败如何降级"这层决策没有任何独立载体。

---

## 3. 候选类职责域拆解表

### 3.1 MessageRouter（643 行 / 19 方法 / 14 私有 / 构造 19 参 / 25 实例属性）

| 职责域 | 证据（文件:行） | 状态所有权 | 谁在调用它 | 可独立测试 |
|---|---|---|---|---|
| 事件分派（message/notice/unknown） | `message_router.py:183-199` | 无自有状态 | 3 个 transport（ws_server:210 等） | ✅ 可（无 IO 依赖，事件解析器可注入，`:71`） |
| 插件事件投递 | `:187-191, 201-230` | 无（用 plugin_manager） | 同上 | ✅ 可（plugin_manager=None 即跳过） |
| 消息处理主流程编排（13 个决策域） | `:237-465` | 仅读共享状态 | 同上 | ⚠️ 只能端到端（`tests/test_router_regression.py:136+`）；单步不可测 |
| 群白名单 / 记忆禁用群 | `:233-235, 488-490` | 无（读 config） | 自身 | ✅ 可 |
| 回复决策（@/回复/点名/上下文概率） | `:473-485` | 无（委托 name_mention / policy_engine） | 自身 | ✅ 可（`test_name_mention_reply.py`） |
| 文件上传配对缓存 | `:494-519, 521-532` | **写** `global_state.pending_files`（共享） | 自身写、MessageAssembler 消费（`message_assembler.py:286`） | ⚠️ 需全局状态 |
| 戳戳处理（冷却+回复） | `:538-565` | **写** `global_state.poke_last_time`（共享） | 自身 | ⚠️ 需全局状态 |
| 主动聊天循环 + 决策执行 | `:568-643` | 读/写 global_state 的主动聊天字段（经 manager） | 自身（TaskManager 注册 `:142`） | ⚠️ 后台循环，靠 `test_graceful_shutdown.py` |
| 并发闸门 | `:131-137` | **持有** `_process_semaphore` | 3 个 transport + `_do_active_chat` `:599` | ✅ 可 |
| 熔断兼容别名 | `:126-127`（→ `ai_gateway.py:60,65`） | 别名，真身在 gateway | 仅测试（`test_circuit_breaker_isolation.py:130,157,209,212,214`、`test_stress.py:66`） | ⚠️ 只读探针 |
| 群昵称/群风格 store | `:119-120, 481`（getattr）、**外部赋值** `main.py:239-240` | 外部注入但**不在构造契约内** | name_mention + gateway provider | ⚠️ 构造 Router 的测试拿不到 → 静默降级 |

**25 个实例属性按职责域归类**（全部来自 `__init__` L75-131；AST 交叉核对）：

| 域 | 属性（定义行） | 数量 | 说明 |
|---|---|---:|---|
| 外部注入依赖 | config(75), ai_client(76), memory_manager(77), sender(79), policy_engine(82), budget(106) | 6 | 只读引用 |
| **死引用**（写入后无人读） | file_parser(78), resource_fetcher(100), blossom_memory(124) | 3 | AST：router 内 reads=0（file_parser/resource_fetcher 只转交 assembler `:101`；blossom_memory 只被 provider lambda 捕获 `:118`） |
| 共享全局状态别名 | global_state(83) ← `policy_engine.global_state` | 1 | **跨请求共享、可串味**（见下） |
| 边界/协议 | _event_parser(81) | 1 | |
| 插件 | plugin_manager(85) | 1 | |
| 可选功能服务 | prompt_manager(87), sticker_manager(89), tool_manager(91), persona_manager(93), meme_manager(95), meme_summary(97) | 6 | None 即降级 |
| 自建子系统 | assembler(101), commands(104), ai_gateway(112) | 3 | 组合根职责下沉到 Router 构造器内 |
| 任务/并发 | task_manager(108), _process_semaphore(131) | 2 | |
| 熔断兼容别名 | provider_breaker(126), group_breakers(127) | 2 | 真身在 gateway |
| **合计** | | **25** | + 运行期外部 setattr 2 个（`group_nicknames`/`group_style_rules`，main.py:239-240）→ 实际 27 |

**隐式全局状态（多请求共享、可能串味）**（问题 2 的核心）：

| 状态 | 位置 | 共享者 | 串味风险 |
|---|---|---|---|
| `GlobalState`（ws_connected / pending_files / poke_last_time / last_toxic_warning / ai_budget_* / user_ai_last_call / 主动聊天字段） | `models.py:39-60`；router 别名 `message_router.py:83` | Router、BudgetManager、transport（ws_server.py:227）、message_summary | 中（字段语义独立，但**所有权分散在 4 个类**） |
| `policy_engine.groups`（GroupState 字典） | `policy_engine.py:33` | ContextManager/CooldownManager/RepeatDetector/ActiveChatManager + main.py:170,199 + plugin state_provider | 中（4 份重复的惰性创建，见 §7 D1） |
| `provider_breaker` / `group_breakers` | `ai_gateway.py:60,65`；别名 `message_router.py:126-127` | Gateway（写）+ Router（别名） | 低（单写者） |
| `process_semaphore` | `message_router.py:131-137` | 3 transport + 主动聊天 | 低（有意共享） |
| **`AIClient._retryable` / `_api_backoff`**（单例客户端上的可变标志） | 写：`ai_client.py:69-70,124-128,242-244`；读：`ai_gateway.py:233,257,269` | 全部并发请求（`MAX_CONCURRENT_AI=3`，`config.py:78`） | **高（真串味）**：A 请求的 4xx 把标志置 False，B 请求读到自己之外的标志 → 误判"不可重试"提前放弃或反向。**建议**：把 `(reply, retryable, backoff)` 作为返回值传回，而不是共享可变属性 |

### 3.2 AiGateway（332 行 / 11 方法(含 6 property) / 构造 11 参 / 12 属性）

| 职责域 | 证据 | 状态所有权 | 谁在调用它 | 可独立测试 |
|---|---|---|---|---|
| 熔断准入（provider + 群级双层） | `ai_gateway.py:111-127, 321-331` | **自己持有** `provider_breaker`+`group_breakers`（有 TTL/容量上限） ✅ | Router（经 mixin）、测试 | ✅ `test_circuit_breaker_isolation.py` |
| 预算/限速闸门 | `:167-170, 300-310` → `budget_manager.py:27` | 无（状态在 GlobalState） | 自身、mixin | ✅ `test_ai_reliability.py:94,139` |
| 人格解析与管理员规则拼接 | `:136-147` | 无 | 自身 | ✅（可注入 persona_manager） |
| 群知识注入 | `:149-153` | 无 | 自身 | ✅ |
| MCP/内部 reply 工具 payload 组装 | `:158-162, 203-222` | `tool_quota` 字典跨 attempt 复用 | 自身 | ✅ `test_mcp*.py` |
| 重试循环（每次单独过预算）+ 退避 | `:164-276` | `retryable_failure` 局部 | 自身 | ✅ `test_ai_reliability.py:52-137` |
| 花语记忆检索注入 | `:174-185` | 无 | 自身 | ⚠️ 需注入 fake blossom |
| 群昵称/群风格注入 | `:186-200` | 无 | 自身 | ⚠️ **生产链路实际不生效**（见 §7 D9 类问题 / §9 U4） |
| reply tool 降级（Phase 9） | `:228-241` | `reply_tools_off` 局部 | 自身 | ✅ `test_native_reply_tool.py` |
| 熔断回写与指标 | `:242-298` | 写 breakers（自己的） | 自身 | ✅ |

判据核对：**guard_chat 205 行 / 27 个 `if` + 1 个 `for`**（条件节点合计 50），是本仓最长的第二个方法；但它的 12 个状态里 11 个是注入 provider，**自有状态只有 2 个熔断容器**（`ai_gateway.py:60-68`）——这是"编排密集"而非"状态+业务+IO+协议混合"。

### 3.3 AIClient（412 行 / 14 方法 / 构造 3 参 / 5 属性）

| 职责域 | 证据 | 状态所有权 | 谁在调用它 | 可独立测试 |
|---|---|---|---|---|
| HTTP 客户端生命周期 | `ai_client.py:17-38` | **持有** `self.client`（进程级单例，main.py:125） | main | ✅ |
| 单次 API 尝试（不重试）+ payload | `:41-157`（`chat_once` 117 行） | 写 `_api_backoff/_retryable`（**跨请求共享，见 3.1**） | AiGateway、PluginManager(manager.py:2399)、MemeSummary | ✅ `test_ai_client.py` |
| prompt 组装/截断/记忆读取 | `:88-93, 310-324` → `prompt_builder.py:62-201` | 无 | 自身 | ✅ `test_ai_client.py` |
| 多轮工具循环（MCP） | `:159-308` | 改 `tool_quota`（外部传入的字典） | AiGateway、MemeSummary | ✅ `test_mcp_multi.py` |
| 回复解析（记忆指令 + 多条 JSON） | `:326-393` | 无 | 自身 | ✅ `test_multi_reply_ai.py` |
| 视觉/引战委派 | `:400-412` | 无 | MessageAssembler、StickerManager、Gateway | ✅ |
| 兼容壳 `chat()` | `:395-398` | 无 | **无生产调用方**（grep 全仓 0 命中） | — |

### 3.4 MessageAssembler（388 行 / 13 方法 / 1 公共方法 / 构造 6 参 / 5 属性）

| 职责域 | 证据 | 状态所有权 | 谁在调用它 | 可独立测试 |
|---|---|---|---|---|
| 编排 6 类配件 → full_text | `message_assembler.py:35-77` | 无 | MessageRouter（唯一） | ✅ `test_face_context.py` 等 |
| 顶层图片识图 | `:80-105` | 无 | 同上 | ✅ `test_vision_switch.py`、`test_image_source_compat.py`（`__new__` 构造） |
| 转发解析（含转发内图） | `:109-138` | 无 | 同上 | ✅ `test_multimsg_card.py` |
| 表情/媒体/引用卡片文本化 | `:141-230, 259-279` | 无 | 同上 | ✅ `test_face_context.py`、`test_media_segments.py` |
| 待配对文件取数+解码 | `:282-328` | **消费** `global_state.pending_files`（pop 语义，`:286`） | 同上 | ✅（resource_fetcher 可注入） |
| **隐私存档 + 保留策略** | `:331-387`（_archive/_archive_cleanup） | 无（直接写盘） | 同上 | ❌ 无测试引用（grep `_archive` 仅本文件） |

### 3.5 CommandHandler（184 行 / 9 方法 / 1 公共方法 / 构造 5 参 / 4 属性）

| 职责域 | 证据 | 状态所有权 | 谁在调用它 | 可独立测试 |
|---|---|---|---|---|
| 指令分派（8 个指令族） | `command_handler.py:26-54` | 无 | MessageRouter（唯一，`:289`） | ✅ `test_prompt_manager.py:129-138` |
| /prompt 命令族（查看/设置/重置 × 全局/群） | `:57-121`（65 行 / 22 条件） | 无（写 prompt_manager） | 同上 | ✅ |
| /help（含群昵称展示） | `:124-142` | **反向 getattr `self.router`** `:126-130` | 同上 | ⚠️ 反向依赖恒为 None（见 §6 R1） |
| 记忆类指令 | `:144-184` | 无（读写 memory_manager） | 同上 | ✅ |

### 3.6 PolicyEngine + 6 个 manager（131 行 / 20 方法，全部 1-3 行委托）

| 职责域 | 证据 | 状态所有权 | 谁在调用它 | 可独立测试 |
|---|---|---|---|---|
| 群状态字典 + 上下文 | `policy_engine.py:33,45-64` → `context_manager.py` | **持有** `groups` + `global_state`（`:32-33`） | Router(30 reads)、main.py:170/199、PluginManager(main.py:184) | ✅ `test_context_manager.py` |
| 冷却 | `cooldown_manager.py:25-56` | 无（用共享 groups/global_state） | 经门面 | ✅ `test_cooldown_manager.py` |
| 复读 | `repeat_detector.py:32-61` | 无（用共享 groups） | 经门面 | ✅ `test_bounded_state.py` |
| 记忆解析 | `memory_parser.py:13-49` | 无 | 经门面 | ✅ `test_memory_parser.py` |
| 戳戳/主动聊天决策 | `poke_manager.py:17-24`、`active_chat_manager.py:39-68` | 无 | 经门面 | ✅ |
| 内存治理 | `policy_engine.py:102-131` | 遍历共享状态 | Router 备份循环 `:176-177` | ✅ `test_bounded_state.py:75-131` |

### 3.7 两个 mixin（ReplyDispatchMixin 50 行 / AiGuardMixin 25 行）

| 职责域 | 证据 | 状态所有权 | 谁在调用它 | 可独立测试 |
|---|---|---|---|---|
| 多条回复发送 + 逐条记账 | `reply_dispatch.py:18-50` | 无（宿主提供 sender/config/policy_engine） | Router `:460,562,637` | ✅ `test_multi_reply_dispatch.py:45+` |
| AI 开关 + 准入委派 | `ai_guard_mixin.py:9-17` | 无（宿主提供 config/ai_gateway） | Router `:302,393,622` | ⚠️ 无独立测试（间接覆盖） |
| `_ai_allowed`（预算闸门转发） | `ai_guard_mixin.py:19-21` | 无 | **无人调用**（生产 grep 0 命中；仅 API 面测试列出 AiGateway 的同名方法） | ❌ |
| `guarded_is_toxic` | `ai_guard_mixin.py:23-25` | 无 | Router `:302` | ✅ |

---

## 4. 上帝类判定（拆 / 部分拆 / 不拆）

| 类 | 判定 | 一句话理由 | 预估风险 |
|---|---|---|---|
| **MessageRouter** | **部分拆** | 判定标准里"是否同时管业务+IO+状态+协议+错误处理"→ 它只管**编排+门控**（业务在 manager、IO 在 services、协议在 adapters），但 `_handle_message` 229 行/**37 if**/**16 个早退**/**9 个协作者**/**13 个决策域**，且 2 处记忆写入、3 处回复记账、2 条发送路径都内联在它身上 —— 不是"什么都干的上帝类"，而是"**什么都没有名字的编排方法**" | 中：它是全部回归测试的锚点（`test_router_regression.py:128` 等 7 个测试文件直接构造它），且 `message_router.py` 距 650 行上限只剩 **7 行**（`test_web_ui_persona_knowledge.py:458`），拆分期间的任何新增都会先撞门 |
| **AiGateway** | **部分拆** | guarded_chat 205 行/28 控制流分支：熔断准入、预算、人格、知识、昵称、工具 payload、重试退避、降级、指标回写**九件事共用一个 200 行方法**；但自有状态只有 2 个熔断容器，12 个属性中 11 个是 provider —— 属于"**编排过载**"，不是状态上帝类 | 中：方法名被 API 面测试钉死（`:495-496`），只能"内部拆 + 保留门面方法" |
| **AIClient** | **部分拆** | 边界总体清晰（单次尝试 vs 重试/预算/熔断），但三处越界：① prompt 组装+记忆读取（`ai_client.py:88-93,310-324`，**每次 attempt 重复**）；② 回复解析（`:326-393`，含 MEMORY_JSON 与多条 JSON）；③ MCP 多轮循环+额度（`:159-308`）；另有跨请求共享的 `_retryable/_api_backoff` | 中低：调用方多（Gateway/Sticker/MemeSummary/PluginManager 4 处），改动需同步 `_TOOL_KWARGS` 隐式契约（`ai_gateway.py:35`） |
| **MessageAssembler** | **部分拆** | 13 个方法里 11 个是"配件→文本"，职责一致；但 `:331-387` 的隐私存档+保留策略与"组装"零共享数据（独立职责域，且无任何测试引用）；识图逻辑在 `:80-105` 与 `:123-137` 重复一遍 | 低：唯一调用方是 Router；`test_vision_switch.py:33` 用 `__new__` 直接构造，方法签名不能改 |
| **CommandHandler** | **不拆** | 163 代码行/9 方法/1 公共方法/4 依赖，职责单一（指令→回话），无状态、无 IO 抽象泄漏；唯一问题是 /help 的反向依赖与"绕过回复记账直发消息" | 低：只需修反向依赖，不需要拆 |
| **PolicyEngine** | **不拆** | 20 个方法全是 1-3 行委托，已经是薄门面；拆它只会增加跳转层 | 低 |
| **ContextManager** | **部分拆** | 上下文读写/概率/查重（职责一致）与 **SQLite 崩溃备份**（`:120-307`，含迁移/建表/全量重写）是两件事，后者占其 60% 体积且是唯一同步阻塞 IO | 低中：`test_context_manager.py:36-79` 直接测备份，需保留公共方法名 |
| **AiGuardMixin** | **不拆，应删/内联** | 19 代码行的纯转发壳，其中 `_ai_allowed` 无生产调用；它让"AI 准入 API"在 Router 与 Gateway 各存在一份，**是历史拆分的兼容残留，不是把上帝类挪进 mixin**（mixin 自身无状态、无业务） | 低：删前需确认外部调用方（仅测试） |
| **ToxicDetector.is_toxic** | **部分拆** | 119 行方法 = 关键词表(90+ 条) + 预检 + AI 复核；表与预检可外提为纯数据/纯函数，AI 复核留在类里 | 低（但 API 面测试钉死 `:495` 的 `["__init__","client","is_toxic"]`） |

---

## 5. 拆分方案（判定为"部分拆"的部分）

> 原则：**一次只搬一件事，每步保持"行为零变化"**；每步都不得让 `message_router.py` 增行（当前 643/650）。

### 5.1 新组件清单（名字 / 真正拥有什么 / 依赖）

| 新组件 | 拥有什么职责 | 拥有什么状态 | 依赖（构造注入） | 来源行 |
|---|---|---|---|---|
| `core/notice_handler.py` → `NoticeHandler` | 群文件上传缓存 + 戳戳（白名单/冷却/回复文本裁剪） | 无自有状态（用注入的 PendingFileCache + GlobalState） | config, sender, dispatch, policy_engine, pending_cache | `message_router.py:494-565` |
| `core/pending_file_cache.py` → `PendingFileCache` | 待配对文件 TTL(600s)+容量(100) 治理 | **独占** `pending_files` 字典（从 GlobalState 迁出） | config | `message_router.py:505-532` + `message_assembler.py:286` |
| `core/active_chat_runner.py` → `ActiveChatRunner` | 主动聊天循环 + 触发 + 3 次尝试 + 提示词模板 | 任务句柄（经 TaskManager） | config, policy_engine, gateway_port, dispatch, semaphore, persona_manager | `message_router.py:568-643` |
| `core/reply_composer.py` → `ReplyComposer` | 兜底文本、回复查重、表情包解析/冷却/带图发送、转交发送 | 无（用 policy_engine + sticker_manager） | config, sender, policy_engine, sticker_manager, dispatch | `message_router.py:424-465` |
| `core/memory_writeback.py` → `MemoryWriteback` | **统一两条记忆写入路径**（强制记忆 + 模型 MEMORY_JSON）的门控 | 无 | config, memory_manager, policy_engine(MemoryParser), sanitizer | `message_router.py:339-354, 407-422` |
| `core/plugin_event_bridge.py` → `PluginEventBridge` | 事件 → 插件 payload 映射 + 异常隔离投递 | 无 | plugin_manager, trace | `message_router.py:187-191, 201-230` |
| `core/group_registry.py` → `GroupRegistry` | GroupState 生命周期（惰性创建 + inactive 清理 + 群维度 TTL 清理） | **独占** `groups` 字典 | config, global_state | 4 份重复：`context_manager.py:24-27`、`cooldown_manager.py:19-22`、`repeat_detector.py:27-30`、`active_chat_manager.py:28-31` |
| `core/context_backup_store.py` → `ContextBackupStore` | SQLite 备份读写/建表/JSON 迁移/周期落盘 | **独占** 备份库路径与连接 | config | `context_manager.py:120-307` |
| `core/ai_attempt_preparer.py` → `AiAttemptPreparer` | **每 attempt 的注入物组装**（人格补丁/昵称/风格/自定义 prompt/花语记忆/tools payload）—— 现在每次重试都重算 | 无（`tool_quota` 由调用方持有） | 各 provider + config | `ai_gateway.py:164-222` |
| `core/retry_policy.py` → `RetryPolicy` | 退避计算 + 可重试判定（现读 `ai_client._retryable/_api_backoff`） | 无（纯函数） | — | `ai_gateway.py:256-276` |
| `services/reply_parser.py` → `ReplyParser` | MEMORY_JSON/【记忆】剥离 + 多条 JSON 解析 + 长度裁剪 | 无（纯函数） | config | `ai_client.py:326-393` |
| `services/toxic_keywords.py` | 关键词表（归一化后）+ 预检纯函数 | 无（模块级常量） | — | `toxic_detector.py:32-100` |
| `services/conversation_archiver.py` → `ConversationArchiver` | 隐私存档 + 保留天数/容量清理（可后台化） | 无 | config | `message_assembler.py:331-387` |

**状态归属规则（问题 2 的落地答案）**：
- `groups` → GroupRegistry（唯一所有者，其余 manager 只持引用）
- `pending_files` → PendingFileCache（唯一所有者；router 写、assembler 读改为经该对象）
- 熔断两容器 → 已正确归 AiGateway ✅（保持；router 别名应删）
- 预算计数 → GlobalState（共享事实），但**只允许 BudgetManager 读写**（现状 `message_router.py:304-307` 也直接写 `last_toxic_warning` → 应归还给一个 ToxicGate）
- `process_semaphore` → 归 transport 层或独立 `ConcurrencyGate`（现在"持有者在 core、使用者在外层"）
- `_retryable/_api_backoff` → **取消共享属性**，改为 `chat_once()` 返回 `(reply, memory, meta)`
- `group_nicknames/group_style_rules` → 进构造参数（现在 main.py:239-240 后置 setattr，构造契约缺失）

### 5.2 迁移步骤（建议顺序，每步一个 commit）

1. **基线冻结**（不改代码）：跑全量测试记录绿灯基线 + `pytest --collect-only` 数量；保存 `git rev-parse HEAD`。
2. **纯搬移 1：NoticeHandler + PendingFileCache**（`_handle_group_upload`/`_prune_pending_files`/`_handle_poke`）→ Router 保留同名薄委托（一行转发），删除 Router 内实现。风险最低（无 AI 参与）。
3. **纯搬移 2：ReplyComposer**（`:424-465`）→ Router `_handle_message` 尾部改为一次调用。
4. **纯搬移 3：MemoryWriteback**（两条路径合并，**门控语义逐条比对**：`:341` `_memory_disabled`、`:343` validate、`:407` `_memory_disabled`、`:411` validate）→ 先写"行为等价"参数化测试再合并。
5. **纯搬移 4：ActiveChatRunner**（`:568-643`）→ Router.start() 只做 `task_manager.register("active_chat", runner.run_loop())`。
6. **纯搬移 5：PluginEventBridge**。
7. **收口重复：GroupRegistry**（4 处 get_group_state → 1 处）→ 各 manager 构造时注入 registry（保留 `get_group_state` 方法名做委托，避免测试改动）。
8. **ContextBackupStore** 从 ContextManager 抽出，同时把同步 SQLite 移入 `asyncio.to_thread`（**行为等价但线程边界变化，需先补并发测试**）。
9. **AiGateway 内部拆**：AiAttemptPreparer（把 `:172-222` 的每 attempt 组装提到循环外/一次算好）+ RetryPolicy（纯函数）→ `guarded_chat` 保留为门面方法名。
10. **AIClient**：抽 ReplyParser；把"是否需要重试/退避"从私有属性改成返回值。
11. **卫生**：删 `AiGuardMixin._ai_allowed`（无调用）、删 Router 的 `provider_breaker/group_breakers` 别名（同步改 3 个测试文件的读取点为 `router.ai_gateway.*`，**测试只修改断言目标，不删用例**）、`AiGateway._nicknames` 三元表达式修正。
12. **收紧门**：把 `test_core_modules_stay_slim` 的 `message_router.py` 上限从 650 下调到拆分后实测值 +10（**保持该测试存在，只改数字**）。

### 5.3 回滚点

| 回滚点 | 位置 | 说明 |
|---|---|---|
| R0 | 步骤 1 的 `git rev-parse HEAD` | 全绿基线 commit |
| R1..R6 | 每个"纯搬移"commit | 单 commit revert 即可恢复；每个 commit 都必须"只搬不改"（无逻辑编辑） |
| R7 | GroupRegistry commit | 若 `test_bounded_state.py:75-131` / `test_context_manager.py` 出现状态语义差异，单独 revert 本步 |
| R8 | ContextBackupStore + to_thread | 线程化可能暴露 SQLite 连接跨线程问题（`sqlite_repository.py:43` `check_same_thread=False` + RLock 已具备），需独立 commit 单独回滚 |
| R9/R10 | Gateway/Client 内部拆 | 若 `test_ai_reliability.py`/`test_mcp*.py` 红，回滚本步（API 面门要求方法名不变） |
| 兜底 | `git revert <range>` | 全部步骤都是纯 Python 内部重构，不涉及配置/数据库 schema，回滚无数据迁移成本 |

### 5.4 需要哪些测试保护（拆分前必须绿 + 拆分后逐步跑）

| 保护对象 | 测试 | 关键锚点 |
|---|---|---|
| 主流程行为 | `tests/test_router_regression.py` | `:128` 构造 Router；`:136+` TestMessageReplyFlow |
| AI 重试/预算/4xx | `tests/test_ai_reliability.py` | `:52,74,94,115,139` |
| 并发与串味 | `tests/test_concurrency.py`、`tests/test_stress.py` | `:16,48,65,80,93,110`；`:14,40,73`；`test_stress.py:66` 读 `router.provider_breaker` |
| 熔断隔离 | `tests/test_circuit_breaker_isolation.py` | `:130,157,209,212,214`（**直接读 router 别名属性**→ 删别名必须先改这些断言） |
| 状态有界 | `tests/test_bounded_state.py` | `:75,102,122` |
| 多条回复链路 | `test_multi_reply_{core,dispatch,e2e,protocol,sdk,ai}.py` | `test_multi_reply_dispatch.py:53,65`、`test_multi_reply_e2e.py:58,76,86,95` |
| 上下文备份 | `tests/test_context_manager.py` | `:36-79` |
| 主动聊天/启动关闭 | `test_graceful_shutdown.py:5,16,32` | 覆盖 `start/stop` 与备份落盘 |
| 点名回复 | `test_name_mention_reply.py:30,35,41,46` | 覆盖 `name_mention.detect` + store |
| 原生 reply tool / MCP | `test_native_reply_tool.py`、`test_mcp*.py` | `:192+` 用关键字构造 gateway |
| 脏话检测 | `tests/test_sanitizer.py` + toxic 相关 | 需补 `toxic_detector` 的表/函数等价测试 |
| **结构性门** | `test_web_ui_persona_knowledge.py:443-497`、`test_architecture_gates.py` | 行数上限 + AiGateway 方法名 + core 无传输依赖 |
| 未直接覆盖（缺口） | `_archive` / `_archive_cleanup`（`message_assembler.py:331-387`）、`_prune_pending_files`、`_handle_poke` 的**直接单元测试**（grep 无引用） | 拆分这些之前建议先补 characterization 测试 |

---

## 6. 依赖问题

| 类型 | 位置 | 说明 |
|---|---|---|
| **反向依赖（死）** | `command_handler.py:126-130` | `getattr(getattr(self,"router",None),"group_nicknames",None)`；全仓无任何 `self.router =` / `handler.router =` 赋值（grep 仅命中 `src/plugins/router.py` 的同名无关属性）→ 恒为 None，/help 的群昵称分支**永不生效**（静默走 `config.BOT_NICKNAME`） |
| **反向依赖（活）** | `main.py:170,199-200`；`main.py:184` | WebUI 状态提供者与 PluginManager **直接读 `message_router.policy_engine.groups`** 与 `policy_engine.context`（绕过 PolicyEngine 门面） |
| **准入层被绕过** | `src/plugins/manager.py:2399`（`self._ai_client.chat_once(...)`，注入点 `main.py:186`） | 插件的 `ai_chat` 直接调 AIClient，**不过 AiGateway 的预算/熔断/限速**——与 `ai_gateway.py` 文档声称的"唯一 AI 对话入口"（`:7`）矛盾 |
| **隐式 self 状态耦合（循环引用）** | `message_router.py:112-121` ↔ `ai_gateway.py:47-57,72-93` | Gateway 通过 9 个 lambda provider 动态读 Router 的属性（含 `getattr(self,"blossom_memory",None)` `:118`），Router 又持有 Gateway → 双向引用；测试替换 `router.ai_client` 才不失效（`:110-111` 注释自认） |
| **未声明的宿主契约（mixin）** | `ai_guard_mixin.py:3`、`reply_dispatch.py:16` | 两个 mixin 需要宿主提供 `config/ai_gateway/sender/policy_engine`，但无抽象基类/协议声明，仅 docstring 说明 |
| **封装破口：调私有方法** | `ai_guard_mixin.py:21`（`self.ai_gateway._ai_allowed`）、`message_router.py:470`（`self.ai_gateway._get_group_breaker`） | MRO 上的公开方法调用 Gateway 的私有方法；同名的 `_ai_allowed` 在两侧各存一份 |
| **跨对象私有属性协议** | `ai_gateway.py:233,257,269` 读 `self.ai_client._retryable` / `._api_backoff`（写点 `ai_client.py:69-70,124-128,242-244`） | 编排层依赖客户端的私有可变标志；**并发下会串味**（§3.1 表末行） |
| **隐式参数契约** | `ai_gateway.py:35` `_TOOL_KWARGS = ("tools","tool_caller","max_tool_calls","tool_quota")` | 与 `ai_client.py:55-58` 的签名手工同步；新增工具参数时降级路径会静默漏剥 |
| **后置注入（构造契约外状态）** | `main.py:239-240`（router）、`main.py:161+219`（`meme_summary.budget`） | 属性在构造后 setattr；`tests/test_router_regression.py:128` 等构造的 Router 没有这些属性 → 相关分支静默降级 |
| **同一对象被 4 处注入** | `ai_client`：`main.py:125 → main.py:186(PluginManager) / :222(Router→Gateway+Assembler) / :146(StickerManager) / :152(MemeSummary)` | 单一 HTTP 客户端被 4 条并发路径共享（配合 `_retryable` 标志 = 串味面） |
| **core 内被外部依赖的深状态** | `policy_engine.groups`（`policy_engine.py:33`） | 4 个 manager + main + 插件运行时共享同一 dict；惰性创建逻辑复制 4 份（§7 D1） |

---

## 7. 重复逻辑与死代码候选

| # | 类型 | 证据 | 判断 |
|---|---|---|---|
| D1 | **4 份完全相同的 `get_group_state`** | `context_manager.py:24-27`、`cooldown_manager.py:19-22`、`repeat_detector.py:27-30`、`active_chat_manager.py:28-31` | 重复逻辑，应并入 GroupRegistry |
| D2 | **回复记账 3 处** | 正式 `reply_dispatch.py:36-43`；复读路径 `message_router.py:296-297`；表情包路径 `:454-456` | 重复且易漂移（docstring `reply_dispatch.py:31-35` 明确警告"不要再重复记录"） |
| D3 | **发送路径 2 套** | 计划化：`reply_dispatch.py:18-50`；直发 sender：`command_handler.py:60,70,72,78,80,83,87,91,93,97,104,108,114,116,118,120,142,147,150,154,158,160,165,167,174,184`、`message_router.py:295,306`、`budget_manager.py:71` | 命令/警告/额度提示的回复**不进 plan、不记连续回复/上下文/最近回复** → 行为不一致 |
| D4 | **恒假条件（死分支）** | `context_manager.py:111` 前半 `overlap >= 0.9 and max(len(reply), len(old)) <= 0` —— 非空字符串下 `max(...) <= 0` 恒 False，而两个空串在 `old_words` 空时已被 `:107-108` continue 掉 | 死代码；有效语义只在后半表达式 |
| D5 | **无调用的兼容壳** | `ai_client.py:395-398` `chat()`（`retry_count` 形参被忽略）；全仓 grep 无生产调用 | 死代码候选（保留需注明兼容对象） |
| D6 | **写入后无人读的实例属性** | `message_router.py:78` file_parser、`:100` resource_fetcher、`:124` blossom_memory、`:126` provider_breaker（AST：router 内 reads=0；provider_breaker 仅测试读 `test_stress.py:66` 等） | 兼容别名/纯冗余 |
| D7 | **只有测试调用的方法** | `message_router.py:468-470` `_get_group_breaker`（生产 0 命中）、`ai_guard_mixin.py:19-21` `_ai_allowed`（生产 0 命中） | 兼容壳，删除需同步改测试断言目标 |
| D8 | **永不生效的反向分支** | `command_handler.py:126-130`（`self.router` 恒不存在） | 死代码（见 §6 R1） |
| D9 | **只有测试走的关键分支** | `ai_gateway.py:189,197` 判 `kwargs.get("group_id")`，而生产调用 `message_router.py:393-399` 用**位置参数**传 group_id → 群昵称注入（`:188-194`）与群风格规则（`:195-200`）在主链路**永不执行**；只有 `tests/test_native_reply_tool.py:192` 等用关键字调用才生效 | 生产死分支（高置信，静态确认；未运行时验证） |
| D10 | **未使用状态字段** | `models.py:43` `next_random_active_time`、`models.py:46` `last_user_message_time`（全仓 0 读者） | 死字段 |
| D11 | **指标重复注册** | `received_messages_total`：`message_router.py:40`（无标签）与 `transport/ws_server.py:18`、`ws_forward_client.py:30`（有 `post_type` 标签）；`registry.counter()` 按名字返回首个实例（`utils/metrics.py:85-91`），`main.py:14`（import router）先于 `:29`（import ws_server）→ **post_type 标签被吞**，两处累加进同一无标签序列 | 重复注册 + 指标语义丢失（非崩溃） |
| D12 | **关键词表重复 + 双扫描** | `toxic_detector.py:37` 与 `:39` 重复条目（傻逼/煞笔/沙比/傻b/傻x）；`:61-70` 子串扫描与 `:72-98` 正则扫描覆盖大量相同短语 | 重复逻辑（也是性能项 P1） |
| D13 | **三元表达式复制粘贴** | `ai_gateway.py:52` `... else (lambda: nicknames) if callable(persona_manager) else (lambda: persona_manager)` —— nicknames 非 callable 时把 **persona_manager 当昵称源** | 逻辑异味（当前调用方都传 callable，未暴露） |
| D14 | **同一清洗模板重复 8 次** | `message_assembler.py:52,116,135,151,188,229,275,304`（sanitize + 命中告警） | 重复模板，可提取 `_clean_block(text, label)` |
| D15 | **识图循环重复** | `message_assembler.py:80-105` 与 `:123-137`（上限/描述/日志三件事各写一遍） | 重复逻辑 |
| D16 | **仓库卫生（非代码）** | 根 `old_ai_tmp.py`（41152 字节，**已被 git 跟踪**，全仓 0 引用）；根 `sqlite:/` **误建目录树**（`sqlite:/data/data/com.dshmobile.shell/.../pytest-of-...`，未跟踪、未 ignore）；`src/core/newdir/` 空目录；`Flowerie_bot/` 嵌套旧克隆（39 个 .py，**含拆分前的 message_router.py**，已被 `.gitignore:34-35` 明确忽略，但会污染 grep/AST 工具：本次审计首次 grep 就命中了它） | 卫生候选；嵌套克隆对自动化重构工具是**现实风险** |

---

## 8. 性能热点（只定位，不改）

| # | 类型 | 位置 | 说明 |
|---|---|---|---|
| **P1** | 重复计算（每消息） | `toxic_detector.py:32-70` | `is_toxic` **每次调用重建 90+ 条关键词 list**、`re.compile` 短词边界正则（`:60`）、并对每条关键词做一次 `unicodedata.normalize("NFKC", kw)`（`:62`）→ 每消息 ~90 次 NFKC + 90 次子串扫描；表/编译/归一化都是常量，可提到模块级。仅 `TOXIC_GROUP_IDS` 命中的群触发（`message_router.py:301`） |
| **P2** | **同一逻辑请求内重复 IO（重试放大）** | `ai_gateway.py:172-173`（`prompt_manager.get_effective_prompt` → `settings_repository.py:112-115` SQLite）、`:179-183`（`blossom_memory.search` → **每次 attempt 一次 embedding HTTP + 向量检索**）、`:186-200`（昵称/风格 store 读）、`:203-207`（`tool_manager.build_tools_payload()`） | 全部在 `for attempt in range(attempts)`（`:164`）内；`AI_MAX_RETRIES` 默认 3（`config.py:80`）→ **最坏 4 倍** |
| **P3** | 重复 IO（每 attempt） | `ai_client.py:88-93` → `prompt_builder.py:88-97` → `memory_manager.py:333-351` | 每次 attempt 读一次用户记忆：`list_notes` + `kv_list` 两次同步 SQLite SELECT（`sqlite_repository.py:83+`） |
| **P4** | 重复计算 + 无效功（清洗后截断） | `context_manager.py:39-48`（对最多 150 条逐条 `sanitize_untrusted_text`，每条 13 条正则，`sanitizer.py:150-176`）→ 随后 `prompt_builder.py:78-82` 才按 `MAX_AI_INPUT_CHARS=8000`（`config.py:283`）截断 | 静态推算 150×13 ≈ **1950 次 `re.subn`/消息**（未实测）；且 `add_context` 存原文（`:30-37`），历史消息**每次都被重新清洗** |
| **P5** | 先付代价后准入 | `message_router.py:381`（`get_context_text`）、`:386-390`（`sticker_manager.build_sticker_context` → `sticker_manager.py:106` 每次一条 SELECT）都在 `guarded_chat` 的预算闸门（`ai_gateway.py:167`）**之前** | 被预算/熔断拒绝的消息仍付完整上下文构造代价（日志 `:402` 证明该路径真实存在） |
| **P6** | **同步阻塞事件循环** | ① `context_manager.py:263-307` `save_context_backup`：async 函数内同步 SQLite `DELETE` 全表 + 逐群逐条 `INSERT`（`_context_backup_loop` `message_router.py:174` 周期触发、`stop()` `:166` 也调）；② `message_assembler.py:331-387`：每次消息同步 `open/write` + `makedirs` + `listdir`×2 + `getsize`×N；③ `memory_manager.py:333-351` 同步 SQLite；④ `persona_manager.py:88-105` 3~5 次同步 SELECT（每次 AI 请求，`ai_gateway.py:137`）；⑤ `prompt_manager.py:27-34`（每次 attempt）。**对照**：`memory_manager.py:356` 已用 `asyncio.to_thread` —— 说明修法在本仓已有先例 |
| **P7** | 连接复用 | `ai_client.py:26-30`：`max_keepalive_connections=0` → 每次 AI 调用**不复用连接**（重新 TCP+TLS），`max_connections=5` 与 `MAX_CONCURRENT_AI=3` 匹配。**未发现"每次请求新建 client"**：`main.py:125` 单实例、`sender.py:32` 单 aiohttp session；唯一每请求新建的是 WebUI 面板（`webui_panels/config_panel.py:54,74,93`），不在消息链路 |
| **P8** | 无界缓存排查 | 核心链路**未发现无界缓存**：`ExpiringMap` TTL+容量（`ai_gateway.py:65-68`、`expiring_map.py:78-82`）、复读缓存上限 200（`repeat_detector.py:50-55`）、pending_files 600s/100 条（`message_router.py:521-532`）、群状态 inactive 清理（`policy_engine.py:118-131`）、梗缓冲 200 群（`meme_knowledge_manager.py:62-68`）。跨天重置的两张 dict（`budget_manager.py:34-39`）在极端群数下当天可增长（低风险） |
| **P9** | 并发共享可变标志（正确性 > 性能） | 见 §3.1 末行 / §6；`MAX_CONCURRENT_AI=3`（`config.py:78`）→ 真实并发 |
| **P10** | 尾延迟叠加 | `message_router.py:187-191` 插件投递在**消息处理之前 await**，且整段持 `process_semaphore`（`ws_server.py:208-213`）→ 慢插件直接占用并发额度（`EVENT_PROCESS_TIMEOUT` 是唯一兜底） |
| **P11** | 每事件日志/指标 | `message_router.py:244-249,392,402,462`、`ai_gateway.py:129-134,250-254,271-275` 每消息多条 INFO + extra dict；量级未实测（UNKNOWN） |
| **P12** | 正则遍历 | `sanitizer.py:150-176`：每次调用 1 条控制字符正则 + 13 条注入正则（`re` 内部缓存已编译对象，但仍是 14 次全文扫描） | 与 P4 叠加 |

---

## 9. UNKNOWN / 未验证项

| # | 项 | 说明 |
|---|---|---|
| U1 | **测试现状** | Phase 0 未运行测试（会写 `.pytest_cache`，属"改仓库"）。当前是否全绿、用例总数、耗时 **UNKNOWN**；拆分前必须补跑基线 |
| U2 | **任务书的 `_fill`** | 任务书把 `_fill` 归到 `message_assembler.py`；本仓 `_fill*` 只存在于 `src/adapters/onebot_parser.py:224,226,228,234,256,413` 与 `src/adapters/milky_parser.py:133,179,332`。message_assembler 无此方法 → 任务书条目疑似来自旧版本，**UNKNOWN（按现状审计）** |
| U3 | **运行时行为未实测** | 未启动 bot、未连真实 OneBot/Milky、未压测。所有"串味/死分支/性能放大"结论都是静态推导 |
| U4 | D9（群昵称/群风格在主链路不生效） | 静态证据链完整（`message_router.py:393` 位置参数 ↔ `ai_gateway.py:189,197` 判 kwargs），且已 grep 确认生产代码无关键字调用（仅 `tests/test_native_reply_tool.py:192,203,214,232,307,317`）→ **高置信但仍标"未运行时验证"**；同时 `test_group_nicknames*.py` / `test_group_style_rules.py` 是否覆盖该注入路径 **UNKNOWN**（未读全） |
| U5 | P9 串味的实际触发概率 | 机制明确（同 loop 并发 + 共享标志），但需要并发时序复现/压测才能量化 → **UNKNOWN** |
| U6 | P4 的 1950 次正则 | 是"150 条 × 13 正则"的静态推算，非实测 CPU 数据；需 profiling 才能定级 |
| U7 | `sqlite:/` 误建目录的来源 | 目录树含 `com.dshmobile.shell/.../pytest-of-u0_a233/pytest-251/test_blossom_repo_creates_dirs0` → 指向某次 `test_blossom_memory` 类用例在"无绝对路径"下用 `sqlite:` 前缀创建了相对目录。**来源为推断（UNKNOWN）**，未定位到具体测试行 |
| U8 | `Flowerie_bot/` 嵌套克隆 | 已确认被 `.gitignore:34-35` 忽略、无 git 跟踪、其 tests 目录仅 `__pycache__`；但它包含**拆分前**的 message_router.py，任何 grep/AST 批量工具都必须排除它（本次审计已踩到）。是否有 CI/脚本会误读它：未查全 `.github/` → **部分 UNKNOWN** |
| U9 | WebUI / 插件 SDK / Web 面板对 core 的反向依赖 | 超出本分片范围，未系统扫描；已知 3 处（`main.py:170,199-200`、`main.py:184`、`src/plugins/manager.py:2399`）。`src/services/webui_panels/*` 对路由/状态的引用未审计 → **UNKNOWN** |
| U10 | `AiGateway._nicknames` 三元表达式（D13）是否曾导致真实缺陷 | 当前所有构造点都传 callable（`message_router.py:119`、`tests/test_native_reply_tool.py:133` 传 None）→ 未暴露；历史缺陷记录 **UNKNOWN** |
| U11 | 历史拆分轮次的原始任务书 | 仓库内有前一轮审计文档：`Flowerie_bot/AUDIT.md`（285 行，2026-08-27 快照）与 `docs/archive/{architecture-audit,phase6-assembler-audit}.md`。本次未逐条比对"上一轮结论"与"当前形态" → 若需要"是否把上帝类挪进 mixin"的历史定性，应另开一轮读这三份文档 |
| U12 | P11 日志开销 | 未做日志量统计 → 不定级 |

---

## 附：任务书数字 ↔ 实测对账

| 任务书 | 实测 | 结论 |
|---|---|---|
| message_router.py 504 代码行 | 504（总 643） | ✅ |
| MessageRouter 19 方法 / 14 私有 / 25 实例属性 | 19 / 14 / 25（+运行期 setattr 2） | ✅ |
| `_handle_message` 229 行 / 37 分支 | 229 行 / **37 个 `if`**（+18 BoolOp +2 IfExp = 57 条件节点）/ 16 个 `return` | ✅（"分支"= if 数） |
| ai_gateway.py 270 行，guarded_chat 205 行 29 分支 | 270 代码行；guarded_chat 205 行 / 27 `if` +1 `for`（条件节点 50） | ⚠️ 28 vs 29：计数口径差异（可能把 1 个 `except`/`ifexp` 计入） |
| ai_guard_mixin.py 19 行 | 19 代码行（总 25） | ✅ |
| command_handler.py 163 行 | 163 代码行 | ✅ |
| reply_dispatch.py 40 行 | 40 代码行（总 50） | ✅ |
| message_assembler.py 372 行，`_fill` 等 | 类跨度 372 行；**无 `_fill`** | ⚠️ 方法名对不上（U2） |
| context_manager.py 292 行 | 类跨度 292 行 | ✅ |
| ai_client.py 361 行 | 361 代码行 | ✅ |
| prompt_builder build_system_prompt 140 行 14 参数 | L62-201 = 140 行；**13 个形参**（config/memory_manager/user_message/context/user_id/group_id/custom_prompt/is_mentioned + 5 个关键字） | ⚠️ 参数 13 vs 14（若把 `config` 拆算则同） |
| toxic_detector is_toxic 119 行 | L26-144 = 119 行 | ✅ |
| 上帝类"是否靠 mixin 维持体积" | mixin 合计 75 行/4 个方法（Router 自身 19 方法）；mixin 无状态无业务 → **不是"把上帝类挪进 mixin"，是兼容壳** | ✅ 判定（见 §4） |
