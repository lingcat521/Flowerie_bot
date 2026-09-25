# 插件间通信（Plugin-to-Plugin）最终验收报告

> 任务书：`/storage/emulated/0/通信.txt`《Flowerie_bot 多语言 Plugin SDK + Plugin-to-Plugin 通信》
> 协议说明：`docs/plugin-communication.md`　·　能力矩阵：`docs/plugin-sdk-capabilities.md` §4
> 一句话结论：**跨语言插件通信默认经 Flowerie Core Router；同语言保留 Local Runtime 通道但对外
> 暴露同一套 `plugin.call()` / `plugin.emit()` / `plugin.on()` 抽象 —— 插件用什么语言写，不改变
> Plugin API 的语义。**

## 1. 交付物

| 层 | 文件 | 说明 |
| :--- | :--- | :--- |
| 协议模型 | `src/plugins/comm.py`（新增，616 行）| 五类消息、请求/响应/错误模型、12 个错误码、语言无关数据类型、Normalized DTO、trace/hop 环保护、路由策略 —— 引擎与五语言 SDK 的**单一事实来源** |
| Core Router / Bus | `src/plugins/router.py`（新增，452 行）| 身份注册表、实例寻址、生命周期结构化错误、权限门、投递、超时/取消、事件广播、真实统计 |
| 引擎接线 | `src/plugins/{protocol,permissions,manifest,runtime,manager}.py` | 能力组 `plugin`、动态权限键 `plugin.call.<target>[.<method>]`、`comm_request`（插件间投递可并发 -> 插件可重入）、反向 op 三条、实例登记 |
| Python SDK | `src/plugins/runner/python_runner.py` | `api.plugin.call/emit/on/expose/cancel`、入站三方法、嵌套 pump、错误码保真 |
| TypeScript SDK | `sdk/typescript/flowerie_sdk.ts` | `plugin.call/emit/on/expose/cancel`、`PluginCommError`、wireCopy 线格式校验 |
| Go SDK | `sdk/go/flowerie/plugin.go` | `Call/Emit/On/Expose/Cancel`、`*CommError`、反射白名单序列化 |
| Rust SDK | `sdk/rust/src/lib.rs` | `call/emit/on/expose/cancel`、`PluginCommError`、`CommState` 注册表 |
| Java SDK | `sdk/java/.../FloweriePlugin.java` + `Json.java` | `call/callAsync/emit/on/expose/cancel`、`PluginCommException`、`Json.checkJsonValue` |
| 示例插件 | `examples/{python,typescript,go,rust,java}-plugin` | 五语言同一契约：expose(get_status) + hook comm_call / comm_emit |
| 测试 | `tests/test_plugin_comm_model.py` / `_bus.py` / `_paths.py`、`test_plugin_sdk_contract.py`、`test_plugin_protocol.py` | 模型 86 / 总线 17 / 三条验收路径 / 五语言同一批向量 |
| 文档 | `docs/plugin-communication.md`（新增）| 协议、路由、权限、错误、DTO、五语言 API 对照、禁止事项对照 |

## 2. §二十八 验收标准

| 项目 | 结论 | 依据 |
| :--- | :--- | :--- |
| Plugin Protocol | **COMPLETE** | 五类消息、请求/响应/错误模型、数据类型与 DTO 全部落地并在引擎与五个 SDK 中一致；`tests/test_plugin_comm_model.py` 逐项断言 |
| Plugin Router | **COMPLETE** | 身份（plugin_id/runtime/version/protocol_version/instance_id）、实例寻址（`plugin_b` / `plugin_b#instance1` / 任意健康实例）、生命周期结构化错误、路由策略 |
| Cross-language RPC | **COMPLETE** | 三条核心路径真进程验证（见 §3）；跨语言一律经 Core，SDK 无旁路通道 |
| Event Bus | **COMPLETE** | `plugin.emit` 广播 + `plugin.on` 订阅（含通配）、`plugin.emit` 权限门、发送者不收自己的广播 |
| Permission | **COMPLETE** | `plugin.call.<target>[.<method>]` / `plugin.call.*` / `plugin.emit`，与既有 Permission 系统同一套（manifest 声明 -> 管理员批准 -> 运行时强制）；拒绝时不投递 |
| Timeout | **COMPLETE** | 每次调用有界（默认 5s，上限 60s），超时返回 `TIMEOUT` 且**不杀目标进程**；在途请求表无泄漏 |
| Cancellation | **PARTIAL** | `plugin.cancel` 协议、投递、`is_cancelled()/cancelled_requests()` 查询、`cancels_sent`/`cancels_acked` 统计都落地并有真进程用例；**但**同步阻塞中的 handler 无法被强制中断（CANCEL 在 handler 返回后生效）—— 五种语言一致，属协议语义内的"尽可能停止" |
| Trace | **COMPLETE** | `trace_id` / `call_id` / `hop_count` 全链路传播（复用 `src/utils/trace.py` 的既有 trace 上下文），日志逐跳可见，超 `MAX_HOP_COUNT` 立即 `PLUGIN_CALL_LOOP` |
| Python -> Go | **PASS** | 见 §3（CI 真编译真进程）|
| TS -> Java | **PASS** | 见 §3（CI 真编译真进程）|
| TS -> TS | **PASS** | 见 §3（两个真 TS 插件进程；实际路径 Core Router，语义与跨语言一致）|
| Existing Python Plugins | **0 new failures** | 旧插件测试（`test_api_gap_*` / `test_sdk_gap` / `test_plugin_*` / `test_doc_example_plugin`）本地全绿；旧的 `plugin_call` / `plugin_event` action 路径行为不变（`plugin_admin` 粗粒度授权仍生效）|
| Core protocol coupling | **0** | `src/plugins/{comm,router}.py` 不 import 任何语言的 SDK/runner/示例；Core 只认 JSON-Lines |
| SDK language coupling | **0** | TS 零 npm 依赖（自带 shim）、Go 只用标准库、Rust 零 crate、Java 只用 JDK、Python 只用标准库；SDK 之间零依赖 |
| Permission bypass | **0** | 唯一入口是引擎反向 op；权限检查在 `PluginBus.call` 内（SDK 无法跳过）；LOCAL 通路同样先过权限 |
| Cross-plugin isolation | **100%** | 每个插件仍是独立进程（协议与隔离不变式不变）；插件拿不到对方语言的对象（语言内部对象在边界被拒绝）|
| CI | 见 §3.2 | |

## 3. 真实验证（本地 + CI）

### 3.1 本地（本机：Python 3.14 + node v24；缺 go/javac/rustc）

| 用例 | 结果 |
| :--- | :--- |
| `tests/test_plugin_comm_model.py` | **86 passed**（五类消息 / 请求响应错误模型 / 数据类型与 DTO / 环保护 / 权限串 / 超时归一 / runner 常量同源）|
| `tests/test_plugin_comm_bus.py` | **17 passed**（真子进程 + 真 Core Router）：投递、身份不可伪造、权限拒绝不投递、细粒度权限、`plugin.emit` 权限、`PLUGIN_NOT_FOUND` / `METHOD_NOT_FOUND` / `PLUGIN_UNAVAILABLE` / `PLUGIN_ERROR` / `SERIALIZATION_ERROR`、实例寻址与"任意健康实例"、超时 + CANCEL、事件广播、A<->B 环保护、WebUI Action 驱动插件间调用 |
| `tests/test_plugin_sdk_contract.py` | **33 passed / 45 skipped**（Python 与 TypeScript 真跑；go/rust/java 因缺工具链 skip 并打印原因）|
| `tests/test_plugin_protocol.py` | 全绿（协议方法集 8 + 3 + 3 = 14、`ENGINE_OPS` 六条、真 runner 端到端）|
| `tests/test_plugin_comm_paths.py` | 本机 skip 三条路径（缺工具链 / Termux 沙箱执行限制），声明用例如实打印可用性 |

> 本机沙箱的两条**环境**限制（与代码无关，已如实标注、不当作 pass）：
> 1. 无 go / javac / rustc 工具链；
> 2. Termux 沙箱里 `PluginRuntime` 的环境变量白名单裁剪后，前缀内的 node/go 等二进制无法 exec
>    （缺 `libtermux-exec` 的 `LD_PRELOAD`）—— 白名单是安全不变式，不为测试放宽。
> 另外本沙箱**禁止硬链接**（已实测 `ln` 失败），因此 udocker 容器（Ubuntu 镜像层含硬链接）无法落地。

### 3.2 CI（真数字，不是估计）

| workflow | 结果 | 关键数字 |
| :--- | :--- | :--- |
| `CI`（Python 3.12）| **success** | `ruff check .` -> All checks passed!；pytest **2133 passed / 22 skipped** |
| `CI`（Python 3.9）| **success** | `ruff check .` -> All checks passed!；pytest **2133 passed / 22 skipped** |
| `Acceptance`（accept）| **success** | 验收汇总 **37/37 通过**（含 pytest 2129 passed / 26 skipped 与 ruff）|
| `Push on main` | **success** | CodeQL：actions / javascript-typescript / python 三份分析全过 |

- 22 skipped 全部是**实机集成**用例（没有协议端环境，按任务书要求 skip 并打印缺失条件），
  与上一版基线（1755 passed / 22 skipped）**skip 数完全相同** —— 说明本轮新增的
  Python->Go / TS->Java / TS->TS 与五语言 SDK 契约用例在 CI 上**全部真跑，没有一条被跳过**。
- 测试规模 1755 -> **2133 passed（+378）**。

### 3.3 一次真实的红 -> 绿（如实记录）

| commit | 结果 | 根因 | 修复 |
| :--- | :--- | :--- | :--- |
| `1731884` | **红**（CI + Acceptance）| 1) Ruff 8 条（I001 x6 + F401 x2）；2) Python->Go 的 `get_status` 回 `plugin_id="unknown"` | 见 `9814b93` |
| `9814b93` | **绿**（三项 workflow 全过）| —— | 1) 按 CI 给出的 Organize imports 逐条修正；2) 引擎在 `initialize` 上下文补上 `plugin_id`/`instance_id`（§四 身份：任意语言的可执行入口没有别的途径知道自己的身份），Go 示例改为优先读请求模型的 `target.plugin_id`（与 Java/Rust 一致），`ctx.PluginID` 兜底 |

> 这条记录的意义：**本机没有 go/javac/rustc、也没有 ruff、容器方案被沙箱禁硬链接挡住**，
> 所以 `1731884` 的红只有 CI 能抓 —— 与"skip 不等于 pass"是同一条纪律：真实数字优先于好看。

## 4. §二十六 禁止事项自查

| # | 禁止 | 结论 | 证据 |
| :--- | :--- | :--- | :--- |
| 1 | Core 依赖 Python Plugin | 未违反 | `comm.py` / `router.py` 无任何语言 import |
| 2 | Go SDK 依赖 Python SDK | 未违反 | Go SDK 只 import 标准库 |
| 3 | Java SDK 依赖 TypeScript SDK | 未违反 | Java SDK 只用 JDK；TS SDK 零 npm 依赖 |
| 4 | 跨语言私自建通道绕过 Core | 未违反 | 五语言 SDK 均只有引擎反向 op 一条出站路径（无 socket/http 客户端）|
| 5 | Local 调用绕过 Permission | 未违反 | 权限检查在 Core（`PluginBus.call`），LOCAL 策略同样经过它 |
| 6 | 语言对象跨语言传递 | 未违反 | `comm.sanitize_value` / TS `wireCopy` / Go 反射白名单 / Java `checkJsonValue` / Rust 序列化 —— 边界处直接 `SERIALIZATION_ERROR` |
| 7 | 每种语言一套不同 RPC | 未违反 | 只有一种线格式（JSON-Lines）与一套消息模型；`test_plugin_comm_model.py` 校验常量同源 |
| 8 | 删除旧插件测试 | 未违反 | 只新增；旧用例行为不变（见 §2 表）|
| 9 | 为测试方便关闭 Permission | 未违反 | 测试也必须显式批准；拒绝路径有专门用例 |
| 10 | 用 Mock 冒充跨语言通信 | 未违反 | 跨语言用例全部起真进程（缺工具链时 skip 并打印原因）|

## 5. 与既有系统的整合

- **权限**：沿用 `src/plugins/permissions.py`（manifest 声明 -> 管理员批准 -> 运行时检查），新增的只是
  `plugin.call.<target>[.<method>]` 这一族动态键与 `plugin.emit`；旧的 `plugin_admin` 粗粒度授权保持原语义。
- **Trace**：`comm.new_trace_id()` 优先取 `src/utils/trace.py` 的上下文，插件链路日志逐跳带 `trace=`。
- **WebUI**（§二十五）：WebUI Action 的 handler 在同一个插件进程、同一个 SDK 上执行，调用另一个插件
  走的就是 `plugin.call`；`tests/test_plugin_comm_bus.py::test_webui_action_drives_plugin_to_plugin_call`
  用真插件 + 真引擎验证了这条链路，没有第二套机制。

## 6. 诚实边界（PARTIAL / 未验证）

1. **同语言 Local Runtime 优化**：SDK 侧保留了 Local 通道与 `route` 策略（`auto/core/local`），
   但 Flowerie 当前"一个插件一个进程"，两个插件不在同一个语言 Runtime 进程内，因此引擎侧实际路径
   总是 `core`（`PluginRouter.route_for` 只有确实同进程才可能返回 local，绝不假装）。
2. **取消**：见 §2 —— "尽可能停止"，同步阻塞中的 handler 不能被打断。
3. **5x5 全矩阵**：测试框架按语言对（caller, callee）参数化，本阶段只落地 §二十四 要求的三条核心路径。
4. **`runtime=node` 的 `node_runner.js`**：未接插件间通信（非 SDK 运行时；用 `runtime=exec`
   + 任一语言 SDK 都有完整支持）。
5. **本机无法验证 Go/Rust/Java 编译**：本沙箱无工具链、禁硬链接（容器方案受阻），证据来自 CI。

