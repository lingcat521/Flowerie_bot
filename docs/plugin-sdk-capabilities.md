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
| WebUI（页面/动作/资源）| 见 [plugin-webui.md](plugin-webui.md)（DSL + HTML）| 见 §3 | 见 §3 | 见 §3 | 见 §3 |

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

| 语言 | 页面声明 | 模板 Context | Action | Asset | 状态 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Python | manifest `web_ui.pages[].file` 或旧 DSL | `{{ var }}`（受控）| POST → `webui_page` hook | `webui/static` | SUPPORTED（Phase 1 已落地，68 用例）|
| TypeScript / Go / Rust / Java | 同上（协议层统一）| 同上 | 同上（同一 hook 方法）| 同上 | **未开始（Phase 3）** |

任务书第 3 份的核心要求是"WebUI 是 Plugin Protocol 的一部分，而不是 Python SDK 的附属"；
Phase 3 会让五种语言用**同一套** `webui.*` 能力声明与 Action 语义，届时更新本表。

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
