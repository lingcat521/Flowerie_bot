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
| Lifecycle（`initialize` / `shutdown`）| SUPPORTED | SUPPORTED | 见 §2 | 见 §2 | 见 §2 |
| Event（`event`）| SUPPORTED | SUPPORTED | 见 §2 | 见 §2 | 见 §2 |
| Health（`health`）| SUPPORTED | SUPPORTED | 见 §2 | 见 §2 | 见 §2 |
| Action（`method:"action"` 反向）| SUPPORTED | SUPPORTED | 见 §2 | 见 §2 | 见 §2 |
| Context（`context.get`）| SUPPORTED | SUPPORTED | 见 §2 | 见 §2 | 见 §2 |
| Config（`config.get/set`）| SUPPORTED | SUPPORTED | 见 §2 | 见 §2 | 见 §2 |
| Permission（`permission.check`）| SUPPORTED | SUPPORTED | 见 §2 | 见 §2 | 见 §2 |
| Storage（`storage.get/set/delete/list`）| SUPPORTED | SUPPORTED | 见 §2 | 见 §2 | 见 §2 |
| Logging（stderr 约定）| SUPPORTED | SUPPORTED | 见 §2 | 见 §2 | 见 §2 |
| Shutdown（干净退出）| SUPPORTED | SUPPORTED | 见 §2 | 见 §2 | 见 §2 |
| WebUI（页面/动作/资源）| 见 [plugin-webui.md](plugin-webui.md)（DSL + HTML）| 见 §3 | 见 §3 | 见 §3 | 见 §3 |

## 2. Go / Rust / Java 的当前状态（**如实**）

| 语言 | 状态 | 依据 |
| :--- | :--- | :--- |
| Go | **代码已就位，等待 CI 证据** | 本机**没有 go 工具链**（`shutil.which("go")` 为空）→ 契约测试 skip 并打印原因；CI 装了 go，会在那里真编译 + 真跑。**在 CI 出结论之前，本表不写 SUPPORTED。** |
| Rust | **代码已就位，等待 CI 证据** | 同上（本机无 `rustc`）|
| Java | **代码已就位，等待 CI 证据** | 同上（本机无 `javac` / `java`）|

> 这一节故意不预填结论：任务书禁止"未验证却标 SUPPORTED"。
> CI 跑绿后，这里会改成逐能力 `SUPPORTED`（或如实写 `PARTIAL` 并给出缺哪一项）。

## 3. WebUI 能力（第 3 份任务书的范围）

| 语言 | 页面声明 | 模板 Context | Action | Asset | 状态 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Python | manifest `web_ui.pages[].file` 或旧 DSL | `{{ var }}`（受控）| POST → `webui_page` hook | `webui/static` | SUPPORTED（Phase 1 已落地，68 用例）|
| TypeScript / Go / Rust / Java | 同上（协议层统一）| 同上 | 同上（同一 hook 方法）| 同上 | **未开始（Phase 3）** |

任务书第 3 份的核心要求是"WebUI 是 Plugin Protocol 的一部分，而不是 Python SDK 的附属"；
Phase 3 会让五种语言用**同一套** `webui.*` 能力声明与 Action 语义，届时更新本表。

## 4. 怎么复核这张表

```bash
python3 -m pytest tests/test_plugin_protocol.py -q        # 协议本身（含真子进程）
python3 -m pytest tests/test_plugin_sdk_contract.py -q -rs # 五语言向量（skip 会打印原因）
```

> 表格里任何 `SUPPORTED` 都必须能指到上面两条命令里的一条绿色输出；指不到就改成 `PARTIAL`/`UNKNOWN`。
