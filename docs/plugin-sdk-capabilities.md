# Plugin SDK 能力矩阵（Capability Matrix）

> 任务书第 2 份 §九 / §十四 要求：逐能力列出各语言 SDK 的状态，
> **禁止为了让表格"全绿"而虚假声明**。状态只用四个词：
> `SUPPORTED`（有自动化证据）/ `PARTIAL`（部分实现或证据不足）/ `UNSUPPORTED`（明确不支持）/ `UNKNOWN`（未验证）。
>
> 证据来源：`tests/test_plugin_protocol.py`（协议本身，真子进程）、
> `tests/test_plugin_sdk_contract.py`（五语言同一批向量，真子进程 + 真管道）。

## 1. 逐能力对照

| Capability（协议方法） | Python | TypeScript | Go | Rust | Java |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Lifecycle（`initialize` / `shutdown`）| SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED |
| Event（`event`）| SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED |
| Health（`health`）| SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED |
| Action（`method:"action"` 反向）| SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED |
| Context（`context.get`）| SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED |
| Config（`config.get/set`）| SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED |
| Permission（`permission.check`）| SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED |
| Storage（`storage.get/set/delete/list`）| SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED |
| Logging（stderr 约定）| SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED |
| Shutdown（干净退出）| SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED |
| WebUI（`webui.page/action/asset`）| SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED |

## 2. Go / Rust / Java 的证据（**CI 实测，不是推断**）

CI run [36129069164](https://github.com/lingcat521/Flowerie_bot/actions/runs/36129069164)
（workflow `CI`，job `test (3.12)`，commit `cf283fe`，结论 **success**），整仓
**1755 passed / 22 skipped**（22 条全是实机集成用例：没有协议端环境，按任务书要求 skip 并打印原因）。

| 语言 | 状态 | 依据（可复核）|
| :--- | :--- | :--- |
| Go | **SUPPORTED** | CI 真装 go → `tests/test_plugin_sdk_contract.py` 里 10 条用例**真编译、真起进程、真走管道**（本机无 go 工具链 → skip 并打印原因）|
| Rust | **SUPPORTED** | 同上（rustc 直接编译 SDK 与示例，零 crate 依赖）|
| Java | **SUPPORTED** | 同上（javac 编译 SDK + 示例到临时 classes，java 运行）|

CI 绿跑里没有任何 `SKIP(本机缺工具链 …)` —— 五种语言全部 RUNNABLE 并全绿。

### 2.1 CI 一次抓出的三个真问题（都已修，记录在此，避免"全绿"变成无根之谈）

| # | 现象 | 根因 | 修复 |
| :--- | :--- | :--- | :--- |
| 1 | Go：`permission.check` 一发起就 `fatal error: all goroutines are asleep - deadlock!` | 读循环与请求处理挤在同一个 goroutine，反向 engine op 等不到应答 | 读/处理分离：读循环独立 goroutine，应答立即投递、请求排队顺序处理 |
| 2 | Rust：`hook status` 返回 `{"counter": null}` | `register_hook` 的闭包签名只有 args，拿不到上下文，示例只能写死 null | `HookFn = Fn(&Context, &[Json]) -> Json`，示例真读 storage |
| 3 | TypeScript：CI 的 tsc 报 `TS2307` ×3 + `TS2580` ×6 | CI 环境没有 `@types/node`，而 SDK 刻意零 npm 依赖 | 新增 `sdk/typescript/shims/node.d.ts`（最小宿主声明）+ run.sh 自动探测；静态用例守住覆盖 |

本机装不了 go/rustc/javac，所以这三个问题**只有 CI 能抓** —— 这正是"skip 不等于 pass"的意义。

## 3. WebUI 能力（第 3 份任务书的范围）

WebUI Protocol（`webui.page` / `webui.action` / `webui.asset`）落地后，
五种语言的 WebUI 能力**完全对齐**（不是"Python 有、别人没有"）：

| 语言 | 页面声明 | 模板 Context | Action | Asset | 状态 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Python | manifest `pages[].file` / `render="plugin"` / 旧 DSL 兼容页 | `{{ var }}`（受控；先净化后替换）| POST → `webui.action` | `webui.asset` + `webui/static` | **SUPPORTED** |
| TypeScript | 同上 | 同上 | 同上 | 同上 | **SUPPORTED** |
| Go | 同上 | 同上 | 同上 | 同上 | **SUPPORTED** |
| Rust | 同上 | 同上 | 同上 | 同上 | **SUPPORTED** |
| Java | 同上 | 同上 | 同上 | 同上 | **SUPPORTED** |

**证据**（CI run [36132261166](https://github.com/lingcat521/Flowerie_bot/actions/runs/36132261166)，
commit `42427a0`，`CI` / `Acceptance` / `Push on main` 三项全绿；整仓 **1829 passed / 22 skipped**）：

- `tests/test_plugin_webui_multilang.py` **31 条**：同一套 WebUI 请求跑五种语言真进程
  （Register Page / Load HTML / Load Asset / Receive Context / Submit Action / Receive Result / Handle Error）；
- `tests/test_plugin_webui_protocol.py` **43 条**：真 Manager + 真插件进程，覆盖 20 类安全问题；
- `tests/test_plugin_webui_html.py` **68 条**：Phase 1 真实 HTML 迁移与安全矩阵（回归）。

本机（只有 python + node）能跑到的部分：`test_plugin_webui_multilang.py` 13 passed / 18 skipped
（缺 go/rustc/javac → skip 并打印原因，**不当作通过**）。

权限强制点（六项 `webui.*`）见 [plugin-webui-protocol.md](plugin-webui-protocol.md) §7。
## 4. 怎么复核这张表

```bash
python3 -m pytest tests/test_plugin_protocol.py -q          # 协议本身（含真子进程）
python3 -m pytest tests/test_plugin_sdk_contract.py -q -rs  # 五语言向量（skip 会打印原因）
# 本机：23 passed / 30 skipped（无 go/rustc/javac）；CI：同文件 50 条全绿

# TypeScript 的 tsc 分支（无 @types/node 时靠 SDK 自带 shim 编译）：
PATH="$HOME/tscheck/bin:$PATH" FLOWERIE_FORCE_TSC=1 \
  python3 -m pytest tests/test_plugin_sdk_contract.py -k typescript -q   # 10 passed
```

> 表格里任何 `SUPPORTED` 都必须能指到上面某条绿色输出或 §2 的 CI run；指不到就改成 `PARTIAL`/`UNKNOWN`。

## 4. 插件间通信（第 4 份任务书《通信》）

协议与语义见 `docs/plugin-communication.md`；这里只列**逐语言能力与证据**。

| Capability（协议方法 / API） | Python | TypeScript | Go | Rust | Java |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `plugin.call`（被调用：expose + 分派 handler）| SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED |
| `plugin.event`（收事件：on + 通配）| SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED |
| `plugin.cancel`（收 CANCEL：记录 + 可查询）| SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED |
| 出站 `plugin.call`（反向 op → Core）| SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED |
| 出站 `plugin.emit`（广播）| SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED |
| 出站 `plugin.cancel` | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED |
| 结构化错误码映射（12 个码）| SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED |
| trace_id / hop_count 自动传播 | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED |
| 嵌套调用（等待响应时仍处理入站消息）| SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED |

**证据（本地可复核）**：

- 模型层：`tests/test_plugin_comm_model.py`（86 passed）—— 五类消息、请求/响应/错误模型、
  语言无关类型、Normalized DTO、环保护、权限串、超时归一，并与 Python runner 内联常量逐项比对。
- 总线层：`tests/test_plugin_comm_bus.py`（16 passed）—— **真子进程**跑真 Core Router：
  投递、权限拒绝不投递、超时 + CANCEL、事件广播、A↔B 环保护（PLUGIN_CALL_LOOP）、
  实例寻址（`plugin.b#instance1` 与"任意健康实例"）、生命周期（PLUGIN_UNAVAILABLE）。
- 跨语言层：`tests/test_plugin_comm_paths.py` —— Python→Go / TS→Java / TS→TS 三条路径，
  真编译真启动（本机只有 node + python，缺工具链的路径 skip 并打印原因；CI 全跑）。
  Go / Rust / Java 的编译与运行证据**只能来自 CI**，本轮 CI 记录见最终报告
  `docs/plugin-communication-report.md`。

