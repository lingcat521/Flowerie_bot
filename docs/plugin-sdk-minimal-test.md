# 多语言 SDK 最小化插件实测（任务书《插件测试》）

任务书要求：**不要证明"SDK 代码存在"，要证明"开发者真的可以用这个 SDK 写出一个能运行的插件"**。
本文既是实测契约（各语言最小插件必须实现什么），也是验收报告的证据索引。

- 最小插件目录：`examples/multilang-sdk/{python,typescript,go,rust,java}/`
- 验收入口：`tests/sdk/test_minimal_plugins.py`（逐语言）与 `tests/sdk/test_minimal_paths.py`（跨语言链路）
- 报告：`docs/plugin-sdk-minimal-report.md`（§十七 验收表 + §十八 17 问）

## 1. 最小插件契约（五种语言语义完全一致）

插件 id（仓库规则：小写字母/数字/下划线/短横线，≤32）：`minimal_py` / `minimal_ts` /
`minimal_ts_2`（同语言第二实例）/ `minimal_go` / `minimal_rust` / `minimal_java`。
任务书里的 `plugin.call("minimal.go", ...)` 在本仓库写作 `plugin.call("minimal_go", ...)`
（插件 id 不允许点号），语义相同。

**暴露的方法**（经 SDK 的 `expose` 注册）：

| 方法 | 参数 | 返回 |
| :--- | :--- | :--- |
| `ping` | 无 | `{"ok": true, "plugin": "<label>", "runtime": "<lang>"}`（label = 自己的 plugin_id 把 `_` 换成 `-`，例如 `minimal_ts_2` -> `minimal-ts-2`）|
| `get_info` | 无 | `{"plugin_id", "runtime", "sdk_version", "protocol_version"}` |
| `echo` | 任意 JSON | **原样返回**`request.params` |
| `slow` | 无 | 睡 1500ms 后 `{"slept": true}`（TIMEOUT 探针）|
| `boom` | 无 | 抛/panic（PLUGIN_ERROR 探针）|
| `seen` | 无 | `{"events": [<收到过的 test.event payload>], "logs": ["[test.event] hello"]}`（日志行文本固定 `[test.event] <message>`）|

**事件处理**：`test.event` 到达时，记录 payload 并用 SDK 日志打一行 `[test.event] <message>`。

**消息命令**（`message` 事件的 `text` 形如 `/sdk@<executor_id> <命令>`，**只有自己的 plugin_id 等于 executor_id 时才执行**（事件是广播的，不寻址会多插件同时回包）；命令参数里的 `<target>` 才是被调用的插件）；返回值以
`{"type":"send_message","payload":{"group_id":<事件里的 group_id>,"message":<JSON 字符串>}}` 动作回给引擎；注意是 `payload` 而不是 `params`（引擎执行动作时读 `action["payload"]`，写错就变成"没有目标与 message"））：

| 命令 | 行为 | message 内容 |
| :--- | :--- | :--- |
| `/sdk@<self> ping <target>` | `plugin.call(target,"ping")` | 结果 JSON |
| `/sdk info` | 自己的 `get_info()` | 结果 JSON |
| `/sdk echo <json>` | 自己的 `echo(json)` | 结果 JSON |
| `/sdk seen <target>` | `plugin.call(target,"seen")` | 结果 JSON |
| `/sdk call <target> <method> [json]` | 通用调用 | 结果 JSON |
| `/sdk route <auto|local|core> <target> <method>` | 指定路由策略的调用 | 结果 JSON |
| `/sdk chain <t1> <t2> <t3>` | ping t1 -> echo t2 `{"hello":"world"}` -> ping t3 | `{"t1":…,"t2":…,"t3":…}` |
| `/sdk errors <granted> <denied>` | 依次触发六种错误 | `{"METHOD_NOT_FOUND":<native>,…}` |

- **成功**：message = 结果 JSON。
- **失败**：message = `{"ok": false, "code": "<错误码>", "message": "<消息>"}`（结构化错误，§八/§九）。
- `/sdk errors` 的每个值必须是**该语言原生错误模型的观察结果**，至少含
  `{"native": "<类型名>", "code": "<错误码>"}`（例如 TS `PluginCommError` / Go `*flowerie.CommError` /
  Rust `PluginCommError` / Java `PluginCommError` / Python `PluginCommError`）。

六种错误的触发方式（`granted` = 有调用权限的目标，`denied` = 无权限的目标）：
`METHOD_NOT_FOUND`（调用不存在的 method）、`PLUGIN_NOT_FOUND`（调用不存在的插件）、
`PERMISSION_DENIED`（调用 denied）、`INVALID_ARGUMENT`（target 为空串）、
`TIMEOUT`（`slow` + 200ms 超时）、`PLUGIN_ERROR`（`boom`）。

## 2. 目录与构建（Build 与 Load 分开验证）

每个语言目录遵循仓库既有约定（零第三方依赖、不用包管理器拉依赖）：

~~~text
examples/multilang-sdk/typescript/{manifest.json, src/index.ts, build.sh, run.sh}
examples/multilang-sdk/go/{manifest.json, go.mod, main.go, build.sh, run.sh}
examples/multilang-sdk/rust/{manifest.json, src/main.rs, build.sh, run.sh}
examples/multilang-sdk/java/{manifest.json, src/MinimalPlugin.java, build.sh, run.sh}
examples/multilang-sdk/python/{manifest.json, plugin.py}
~~~

- `build.sh`：真编译（tsc / go build / rustc / javac），产物落在插件目录下的 `.build/`；
  失败必须非零退出（验收表里的 Build 行就是它）。
- `run.sh`：exec 构建产物（runtime=`exec` 的入口）；产物不存在时报错而不是静默成功。
- Python 用仓库自带 runner（`runtime=python`，entry `plugin.py`），无需构建。

## 3. 验收怎么跑（不碰 Core 内部 API）

`tests/sdk/` 里的验收测试只用**公开面**：真仓库（`SettingsRepository`）+ 真引擎
（`PluginManager.discover/enable/start_all/dispatch_event/shutdown`）+ 真插件进程；
插件内部一律走各自 SDK，测试不手写协议行、不直接调 PluginRuntime、不 Mock 插件。

链路：`dispatch_event("message", {text:"/sdk chain …"})` -> 引擎投递 -> 插件 SDK ->
`plugin.call` -> Core Router -> 另一个真插件进程 -> 结果回到动作
（`send_message` + `payload`）-> 测试断言 message 内容。

## 4. 环境缺失怎么处理（§十三/§十四）

本机（Termux 沙箱）只有 Python 与 node，且沙箱不允许被引擎白名单裁剪过环境变量的 node 进程启动，
因此本地跳过的语言必须在报告里标 **BLOCKED BY ENVIRONMENT** 并写清缺什么；CI（Ubuntu + go/rustc/javac/node）
是真跑的唯一采信来源。**skip 永远不是 PASS。**

