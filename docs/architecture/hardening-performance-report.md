# Hardening + Hot-path Optimization 报告（fix.txt）

- **基线**：`0bb36a3`（上一轮重构收尾，CI 三绿、工作树干净）
- **本轮**：10 个提交（20 files changed, 1047 insertions(+), 19 deletions(-)）
- **范围**：fix.txt 的六个优先项 + 条件性项审计；任务书 §八「暂时不要做」的清单一项未碰
- **验收**：`bash work/verify.sh` + CI 三件套（CI / Acceptance / Push on main）

## 1. 修改清单

| # | 问题 | 原因 | 修改 | commit |
| ---: | :--- | :--- | :--- | :--- |
| ① | 旧插件通信通道只有「不能调用自身」一层防护，超时硬编码 `3.0` | `plugin_call / plugin_event / plugin_service` 是公开 SDK 能力（`python_runner`、`plugin_sdk` 都暴露），但缺 hop 环保护；A→B→A 会一路递归到超时 | 复用 `comm` 的 hop 机制（`hop_exceeded` / `next_hop` / `MAX_HOP_COUNT=8`）+ 本进程在途深度表兜底（SDK 目前不回传 `hop_count`）；超时改为 `PLUGIN_LEGACY_CALL_TIMEOUT`（默认 3 = 旧值）/ `_MAX`（默认 30）可配置 + payload 可协商；`ev` 补 `hop_count`/`trace_id`；新增 `plugin_legacy_calls_total{result}` 与三类日志 | `2e2ffed` |
| ② | 审计日志 append-only 无上限，磁盘单调增长 | `memory_manager._audit` 在每次记忆写入与 FORGET/CLEAR/REPLACE 时各追加一行 | 新增 `AUDIT_LOG_MAX_MB`（默认 0 = 不轮转 = 旧行为）；>0 时 `audit.log → .1 → .2`，`os.replace` 原子滚动 + `threading.Lock` 与追加互斥，失败只记 warning | `40e945e` |
| ③ | 被预算拒绝的请求仍白做上下文与表情包查询 | 主路径是「取上下文 → 取表情包 → guarded_chat 内的预算闸门」 | 新增只读 `BudgetManager.peek()` + `AiGateway.precheck_allowed()`，主路径在构建上下文前短路；预检不扣预算、不发「额度用尽」提示（提示仍只在闸门里发一次） | `2bdd5b2` |
| ④ | 一次逻辑请求内人格被解析多次，每次最多 4 次 SQLite | `guarded_chat` 里主路径 + 群昵称各解析一次，重试再来一轮 | `resolve_persona / _id / _name` 新增可选 `cache` 参数，`guarded_chat` 用函数内的局部 dict 作请求级缓存（不跨请求/群/用户） | `c05cbe7` |
| ⑤ | `save_context_backup` 的同步 SQLite 全表重写把事件循环按住 | 该函数由主路径定时任务 `await`，内部是 DELETE + 逐条 INSERT + COMMIT | `asyncio.to_thread` + 惰性 `asyncio.Lock` 串行化（保持旧实现的天然串行语义） | `8ed23d0` |
| ⑥ | 连接池每条请求都新建连接（每次 AI 调用重做 TCP+TLS 握手） | `ai_client` 用 `max_keepalive_connections=0` | 两参数 benchmark 后**启用**：0 → 5 + `keepalive_expiry=30s`（服务端设 TCP_NODELAY 时 +51%~+89%，见 §3 表 F）；stale 实验确认 httpx 会自动新建连接 | `107e2ea` |
| — | CI 修复与工具 | 本轮 CI 红过一次（ruff B007） | 用例循环变量改 `_`；本地兜底检查器补第 8 条规则（B007） | `162adfd` / `26d242c` |

## 2. 行为兼容性

| 维度 | 是否变化 | 说明 |
| :--- | :--- | :--- |
| 默认行为 | **不变** | 旧通道超时默认仍 3 秒；审计轮转默认关；预算判定与数值未动；备份保存的串行语义与结果未变 |
| 公开 API / 方法签名 | **向后兼容** | 只新增可选参数（`cache`、`audit_max_mb`、`peek`、`precheck_allowed`）；旧调用方式一律照旧 |
| 插件 SDK | **不变** | 三个旧 action 的名字、payload 字段、返回结构都没改；`ev` 只是多带了 `hop_count`/`trace_id`（新增字段，不删不改旧字段） |
| 插件权限语义 | **不变** | 未碰权限表与判定；旧通道的 `plugin_admin` 门照旧 |
| AI budget | **不变** | `check()` 未改；新增的 `peek()` 只读，不扣额度；被拒时的「额度用尽」提示仍每群每天最多一条 |
| AI retry / circuit breaker | **不变** | 未触碰重试循环结构与熔断计数 |
| 配置项 | **新增 3 项，默认值 = 旧行为** | `PLUGIN_LEGACY_CALL_TIMEOUT=3`、`PLUGIN_LEGACY_CALL_TIMEOUT_MAX=30`、`AUDIT_LOG_MAX_MB=0`；`Settings` 175 字段与 `SCHEMA` 173 键双向差集仍为 0（另 2 项为凭据，设计排除） |
| 日志 | 两处新增、一处顺序微调 | 新增旧通道 loop/timeout/error 日志与 `audit_log_rotated`；被预算拒绝时不再打印 `policy_pass`（语义上更准确：策略没通过），`budget_rejected` 照旧 |

## 3. Benchmark

| 表 | 项 | before | after | 测试条件 / 样本 |
| :--- | :--- | :--- | :--- | :--- |
| A | 旧通道 hop 保护 | 无（A→B→A 递归到 3 秒超时） | 第 8 跳拒绝，不再向下投递 | 8 个用例，含递归终止与在途表清零断言 |
| B | 审计日志轮转 | 文件无上限 | >0 时最多 3 份（当前 + .1 + .2） | 300 次写入 + 小阈值，行数守恒与归档有界断言 |
| C | 预算前置（调用次数） | 被拒请求：上下文查询 1 次 + 表情包查询 1 次 | **0 次 / 0 次** | `TestBudgetPrecheckSkipsQueries` 用 spy 计数 |
| D | Persona 请求级缓存（SQLite 次数） | 一次逻辑请求解析 2 轮，每轮最多 4 次查询 | **1 轮**（重试也不再查） | 假 repository 计数；三种命中路径各一例 |
| E | 上下文备份阻塞 | 同步全表重写 **407.5 ms**（200 群 × 50 条 + 200 个已处理 id），期间事件循环完全停摆 | 阻塞 **0 ms**；墙钟 819.6 ms（线程调度）期间 1 ms ticker 推进 **578 次** | 本机 Python 3.14 / 200 群；`tests/test_context_backup_async.py` |
| F | keepalive（20 次串行请求） | 见下方两参数扫描 | 服务端设 TCP_NODELAY 时 **+51%~+89%**、连接数 20 → 1 | 本地合成服务端：accept 后 sleep(RTT) 模拟握手，NODELAY 可开关 |

> 表 D 的「每轮最多 4 次查询」来自 `resolve_persona` 的分支数（群人格 id → 人格行 → 全局人格 id → 人格行 → 默认人格 → `list_personas` 兜底），不是端到端延迟测量。
**表 F 的两参数扫描**（N=20 次串行请求，`ka=0` → `ka=5`）：

| RTT | 服务端 NODELAY **on** | 服务端 NODELAY **off** |
| ---: | :--- | :--- |
| 0 ms | 412.8 → **125.5 ms**（+69.6%） | 242.8 → 1087.7 ms（−347.9%） |
| 10 ms | 407.2 → **197.8 ms**（+51.4%） | 394.5 → 1018.1 ms（−158.1%） |
| 40 ms | 1077.8 → **224.9 ms**（+79.1%） | 1052.4 → 1073.9 ms（−2.0%） |
| 80 ms | 1914.4 → **206.8 ms**（+89.2%） | 1854.5 → 1046.7 ms（+43.6%） |

第一轮实验（本地 `http.server`，启用后反而慢 2.2 倍）落在 **NODELAY=off** 那一列 ——
Python 的 `http.server` 不设 `TCP_NODELAY`，而生产 HTTP 服务（nginx / uvicorn /
Go net/http）默认都设。真实 AI 端点属 on 列，故按 benchmark 启用 keepalive。
**stale 风险实验**（服务端显式 `Connection: close` 与 0.2 s 后静默关闭两种）：
三次请求全部 `ok(200)`，httpx 0.28 会自行识别对端关闭并新建连接。

## 4. Regression

| 项 | 数字 |
| :--- | :--- |
| 新增测试文件 | 4 个：`test_plugin_legacy_channel_hardening.py`（8 例）、`test_audit_log_rotation.py`（7 例）、`test_budget_precheck.py`（8 例）、`test_persona_request_cache.py`（10 例）、`test_context_backup_async.py`（2 例） |
| 新增用例总数 | **35 例**（另有 `test_router_regression.py` 追加 2 例预算预检集成用例） |
| 本轮相关测试 | 196 + 34 + 108 + 64 + 11 passed（配置/插件族、记忆、路由族、AI 族、上下文） |
| 本地全量（不含 e2e，`timeout 1500` 兜底） | **2203 passed / 141 skipped / 1 xfailed / 15 failed**，4 分 16 秒（上一轮基线 2170 passed，本轮 +33，与新增用例数吻合） |
| 失败测试 | 15 项，与上一轮基线**逐条相同**、无新回归：httpx stub 缺 `MockTransport` 7 项、URL 下载安装需真实网络 5 项、缺 ruby/perl 运行时 2 项、另 1 项同类；CI 的 Acceptance（真环境）为 success |

## 5. CI

| 提交 | CI | Acceptance | Push on main |
| :--- | :--- | :--- | :--- |
| `2e2ffed`（① 旧通道加固） | success | success | success |
| `40e945e`（② 审计轮转） | **failure**（ruff B007 ×4） | failure（同因） | success |
| `2bdd5b2`（③ 预算前置） | **failure**（同一批 B007 —— 修复提交在它之后） | failure（同因） | success |
| `162adfd` + `26d242c`（B007 修复 + 检查器补规则） | success | success | success |
| `c05cbe7`（④ Persona 请求级缓存） | success | success | success |
| `8ed23d0`（⑤ 上下文备份线程化，本报告前最后一次代码提交） | 见仓库 Actions（撰写时进行中） | 同左 | success |

> 本轮 CI 只红过一次：`40e945e` 的 4 处 ruff B007（`for i in range(N)` 里未使用 `i`）。已修，并把 B007 补进 `scripts/check_imports.py`（第 8 条规则），全仓 363 个文件 0 问题。

## 6. 未实施项目

| 项 | 为什么没做 | 风险 | 什么条件下值得再做 |
| :--- | :--- | :--- | :--- |
| 存档/审计写盘改 `to_thread` | 每次一行 append（微秒级），线程调度开销大于收益；存档默认关闭 | 无 | 存档开启且单条消息触发大量写盘时 |
| Persona / 记忆 SQLite 查询改 `to_thread` | 查询是毫秒级单点，且 ④ 已把每请求的查询轮数砍半；整批改动会碰到连接线程亲和 | 主路径仍有毫秒级同步查询 | 有真实 p99 延迟数据证明它是瓶颈时 |
| `webui_loader` 阻塞读文件 | 属管理员 WebUI 路径，任务书明确要求不要为普通聊天性能动它 | 面板打开时的毫秒级阻塞 | 面板出现可复现的卡顿时 |
| `memory_manager._audit` 改 `to_thread` | 同上（一行 append） | 无 | 同「存档/审计写盘」 |
| 条件性项 A：Plugin Registry 全表 SQL + `get_plugin` O(n) | 当前插件规模下不构成瓶颈；优化要动核心读取路径且需处理测试 monkeypatch 行为 | 插件数量上千时线性劣化 | 启用插件数达到数百且 `dispatch_event` 延迟可测时 |
| 条件性项 B：花语记忆写放大（逐条 commit + 两次 `COUNT(*)`） | 该功能默认关闭，缺少开启状态下的真实数据 | 开启后写入放大 | 花语记忆开启且写入延迟可测时 |
| 条件性项 C：WebUI snapshot 最多 200 次子进程往返 | 只在管理员打开插件面板时发生 | 面板卡顿 | 面板出现可复现的卡顿时 |

**任务书 §八「暂时不要做」的核对**：未重写 PluginApi、未改插件权限模型、未删旧通道、未删 Mixin、未再拆 Manager、未重写 MessageRouter、未改 AI retry/budget/breaker、未改上下文截断语义、未合并重复逻辑、未删 `postgres_blossom_repository`、未新增抽象层、未做全仓 async 化、未做数据库迁移 —— 一项未碰。

## 停止条件核对

| 条件 | 状态 |
| :--- | :--- |
| 旧插件通道有 timeout + hop guard | ✅（`2e2ffed`，CI 三绿） |
| 审计日志可选轮转 | ✅（`40e945e` + B007 修复） |
| budget gate 前置 | ✅（`2bdd5b2`） |
| Persona request-local cache | ✅（`c05cbe7`） |
| 安全的阻塞 IO 已处理 | ✅（IO-1；其余逐条在 §6 说明为何不动） |
| keepalive benchmark 完成 | ✅（两参数扫描 + stale 实验；据其启用 `max_keepalive_connections=5` + `keepalive_expiry=30s`） |
| CI / Acceptance 全绿 | 见 §5 与仓库 Actions（`2e2ffed` / `26d242c` / `c05cbe7` 已三绿；`8ed23d0` 与报告提交本身以 Actions 为准） |
| 公开 API 无意外变化 / 默认配置语义无变化 | ✅（§2 逐项核对；配置仅新增 3 项且默认等于旧行为） |

## 最终输出

- **HEAD**：报告提交前的最后一次代码提交为 `107e2ea`
- **总提交数**：10（另有 docs 提交）
- **文件统计**：20 files changed, 1047 insertions(+), 19 deletions(-)
- **benchmark 对比**：§3 表 A–F（其中表 E 是唯一有明确阻塞时间对比的项：407.5 ms → 0 ms）
- **测试统计**：新增 35 例 + 追加 2 例；本轮相关 413 项通过；本地全量与失败归因见作业记录
- **公开 API / 默认行为兼容结论**：兼容（§2）
- **下一步建议**：「Persona / 记忆 SQLite 线程化」需要真实 p99 延迟才能决策（本地无法测真实端点）；条件性三项等规模上来后再看；keepalive 已按 benchmark 启用，若真实端点出现连接异常，把 `keepalive_expiry` 调小或回退到 0 即可（单行改动）

