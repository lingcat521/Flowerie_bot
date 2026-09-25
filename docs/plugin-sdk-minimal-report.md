# 多语言 SDK 最小化插件实测报告（任务书《插件测试》）

> 任务书：`/storage/emulated/0/插件测试.txt`　·　契约：`docs/plugin-sdk-minimal-test.md`
> 核心要求：**不要证明"SDK 代码存在"，要证明"开发者真的可以用这个 SDK 写出一个能运行的插件"。**

## 1. 交付物

| 层 | 位置 | 说明 |
| :--- | :--- | :--- |
| 最小插件 | `examples/multilang-sdk/{python,typescript,go,rust,java}/` | 每种语言一个极简插件，只依赖该语言 SDK：`ping/get_info/echo/slow/boom/seen` + `test.event` + `/sdk@<自己>` 命令 |
| 构建 | 各语言 `build.sh` / `run.sh` | Build 与 Load 分开：build.sh 真编译进 `.build/`，run.sh 只 exec 产物 |
| 验收 | `tests/sdk/{harness.py,test_minimal_plugins.py,test_minimal_paths.py}` | 真仓库 + 真引擎公开面（discover/enable/start_all/dispatch_event/shutdown）+ 真插件进程 |
| SDK 补齐 | `src/plugins/runner/python_runner.py` | 自定义事件类型（`test.event`）此前会被静默丢弃 → 现在分派给 `on_<event>` / `on_event` 钩子 |

## 2. §十七 验收表

（本机与 CI 的真实结果；`SKIP` 一律写明原因，绝不当 PASS）

| 测试 | TypeScript | Go | Rust | Java | Python |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Build | 见 §3 | | | | |
| Load | | | | | |
| Ready | | | | | |
| Ping | | | | | |
| Info | | | | | |
| Echo | | | | | |
| Event | | | | | |
| Call | | | | | |
| Error | | | | | |
| Permission | | | | | |
| Shutdown | | | | | |

三条核心链路：**TS → Go**、**TS → Java**、**TS → TS**（见 §4）。

## 3. 本机（Termux 沙箱）结果

（待填：本地 11 行表中 Python 全 PASS，其余 BLOCKED BY ENVIRONMENT + 缺什么）

## 4. 跨语言链路结果

（待填：§五 七条链路）

## 5. §十八 17 问

（待填）

