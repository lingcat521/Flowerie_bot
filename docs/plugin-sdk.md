# Plugin SDK（多语言）

> Flowerie 的插件协议是**语言无关**的：[Plugin Protocol v1](plugin-protocol.md)。
> 本文件是各语言 SDK 的操作指南；能力对照见 [plugin-sdk-capabilities.md](plugin-sdk-capabilities.md)。
> 目标（任务书第 2 份）：**Flowerie 不是"Python Bot 框架 + 四个语言补丁"，而是有一个稳定的语言无关协议。**

## 1. 一张表选语言

| 语言 | SDK 位置 | 依赖 | 运行方式 | 示例 |
| :--- | :--- | :--- | :--- | :--- |
| **Python** | 内置（`runtime=python` 的 runner 即协议对端）| 无 | 引擎托管子进程 | [../examples/python-plugin/](../examples/python-plugin/README.md) |
| **TypeScript / Node** | [../sdk/typescript/](../sdk/typescript/README.md) | 无（node 内置模块）| `runtime=exec` → `run.sh` | [../examples/typescript-plugin/](../examples/typescript-plugin/README.md) |
| **Go** | [../sdk/go/flowerie/](../sdk/go/flowerie/plugin.go) | 无（标准库）| `runtime=exec` → `go build` + 执行 | [../examples/go-plugin/](../examples/go-plugin/README.md) |
| **Rust** | [../sdk/rust/](../sdk/rust/src/lib.rs) | 无（std；自带极简 JSON）| `runtime=exec` → `rustc` + 执行 | [../examples/rust-plugin/](../examples/rust-plugin/README.md) |
| **Java** | [../sdk/java/](../sdk/java/src/main/java/dev/flowerie/sdk/FloweriePlugin.java) | 无（JDK；自带极简 JSON）| `runtime=exec` → `javac` + `java` | [../examples/java-plugin/](../examples/java-plugin/README.md) |
| 其它任意语言 | 直接实现协议即可 | —— | `runtime=exec` | 13 种语言最小实现见 [plugin-developer-guide.md §31](plugin-developer-guide.md) |

**为什么其它语言不需要自己写 HTTP 服务器**：HTTP/静态资源/页面渲染都由 Flowerie 的 WebUI Runtime 负责，
插件只在 stdio 上说协议（任务书第 3 份 §十 的要求）。

## 2. 五语言 API 对照（语义一致，写法各随语言习惯）

| 能力 | Python | TypeScript | Go | Rust | Java |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 生命周期 | `on_startup / on_shutdown` | `plugin.onStartup / onShutdown` | `plugin.OnStartup / OnShutdown` | `plugin.on_startup / on_shutdown` | `plugin.onStartup / onShutdown` |
| 消息 | `on_message(event)` | `plugin.onMessage(fn)` | `plugin.OnMessage(fn)` | `plugin.on_message(fn)` | `plugin.onMessage(fn)` |
| 事件 | `on_notice / on_request` | `plugin.on("notice", fn)` | `plugin.On("notice", fn)` | `plugin.on_event("notice", fn)` | `plugin.onEvent("notice", fn)` |
| 动作 | `api.send_message(...)` | `ctx.action(type, params)` | `ctx.Action(type, params)` | `ctx.action(type, params)` | `ctx.action(type, params)` |
| 存储 | `api.storage_get/set`（见 runner）| `ctx.storageGet/Set/Delete/List` | `ctx.StorageGet/Set/Delete/List` | `ctx.storage_get/set/delete/list` | `ctx.storageGet/Set/Delete/List` |
| 配置 | `api.plugin_config()`（既有 action）| `ctx.configGet/configSet` | `ctx.ConfigGet/ConfigSet` | `ctx.config_get/config_set` | `ctx.configGet/configSet` |
| 权限 | 引擎侧强制（无需查询）| `ctx.permissionCheck` | `ctx.PermissionCheck` | `ctx.permission_check` | `ctx.permissionCheck` |
| 日志 | `print(..., file=sys.stderr)` | `ctx.logger.info` | `ctx.Logf` | `ctx.log` | `ctx.log` |
| 控制面 hook | `def status(...)` | `plugin.registerHook` | `plugin.RegisterHook` | `plugin.register_hook` | `plugin.registerHook` |

## 3. 三条铁律（任何语言都一样）

1. **stdout 只放协议 JSON**：日志/调试/编译器输出一律走 stderr，否则污染协议（引擎会当作非法行跳过）；
2. **一行一个 JSON，写完立刻 flush**：缓冲住 = 引擎永远收不到；
3. **收到必须回，id 原样带回**：不要自己造 id（插件主动请求的 id 从 1000000 起，见协议 §3）。

## 4. 跨语言一致性怎么保证的

`tests/test_plugin_sdk_contract.py` 用**同一批向量**
（`tests/fixtures/plugin_protocol_vectors.json`）驱动五种语言的示例插件，每个都是**独立子进程**：

```text
initialize（协议版本 + 能力声明）
event(text=ping)      → 必须返回同一条 send_group_msg{message:"pong"}
event(text=hello)     → 必须不返回动作
storage.set/get/list/delete + 穿越键必须被拒
permission.check      → 反向 engine op（granted/denied 与向量一致）
hook status           → 必须读到 storage 里的计数器
未知方法              → 必须回协议级 error
shutdown              → ok 且进程干净退出
```

**缺工具链的语言会 skip 并打印原因**（不是 pass）—— CI 装了 go/rustc/javac/node，会真跑。

## 5. 新语言接入清单

1. 实现协议（必读 [plugin-protocol.md](plugin-protocol.md)：线格式 / 方法集 / 错误模型 / 版本与能力协商）；
2. 在 `examples/<lang>-plugin/` 放一个能跑通向量的示例（`ping → pong` + `status` hook）；
3. 在 `tests/test_plugin_sdk_contract.py` 的 `LANGUAGES` 里登记（示例目录 + 工具链需求）；
4. 跑 `python3 -m pytest tests/test_plugin_sdk_contract.py -q`，全绿后在
   [plugin-sdk-capabilities.md](plugin-sdk-capabilities.md) 里按**实际证据**更新状态。

## 6. 能力对齐（parity）：五语言必须一模一样

任务书第 2 份 §十四 + 用户要求：**其它语言 SDK 的能力必须与 Python SDK 对齐**，
不允许某个语言悄悄少一项。这里的"能力"分两层，各有自动化证据：

### 6.1 协议层（硬性，有测试钉住）

| 项 | 要求 | 证据 |
| :--- | :--- | :--- |
| 可选方法集合 | 五种语言**声明完全相同**的 8 项（`context.get / config.get / config.set / permission.check / storage.get / storage.set / storage.delete / storage.list`）| `test_plugin_sdk_contract.py::test_handshake_declares_protocol_and_capabilities`（**相等**断言，不是子集）|
| 必需方法 | `initialize / event / health / shutdown` 五种语言都实现 | 同上（握手 + health + 事件 + 退出用例）|
| 心跳 | 五种语言都能回 `{ok: true}` | `::test_health_method_is_supported` |
| 事件语义 | `message` 与 `command` 两类事件在五种语言里返回**同一条动作** | `::test_event_yields_vector_action` / `::test_command_event_yields_same_action` |
| 存储/配置/权限 | 五种语言走同一批向量（含穿越键必须被拒）| `::test_storage_roundtrip_matches_vector` / `::test_permission_check_uses_reverse_channel` |
| 数据钩子 | 五种语言都能被控制面 hook 调用并返回同一结果 | `::test_hook_status_reads_storage` |
| 源码一致性 | 五个 SDK 源码里都能找到这 8 个能力名（防"改了文档没改代码"）| `::test_capability_parity_is_declared_in_every_sdk_source` |

### 6.2 具名钩子对照（写法不同，语义一致）

| Python | TypeScript | Go | Rust | Java |
| :--- | :--- | :--- | :--- | :--- |
| `on_message` | `onMessage` | `OnMessage` | `on_message` | `onMessage` |
| `on_command` | `onCommand` | `OnCommand` | `on_command` | `onCommand` |
| `on_notice` | `onNotice` | `OnNotice` | `on_notice` | `onNotice` |
| `on_request` | `onRequest` | `OnRequest` | `on_request` | `onRequest` |
| `on_lifecycle` | `onLifecycle` | `OnLifecycle` | `on_lifecycle` | `onLifecycle` |
| `on_schedule` | `onSchedule` | `OnSchedule` | `on_schedule` | `onSchedule` |
| `health_check` | `onHealth` | `OnHealth` | `on_health` | `onHealth` |
| `on_startup` / `on_shutdown` | `onStartup` / `onShutdown` | `OnStartup` / `OnShutdown` | `on_startup` / `on_shutdown` | `onStartup` / `onShutdown` |
| `api.storage_*` | `ctx.storageGet/Set/Delete/List` | `ctx.StorageGet/Set/Delete/List` | `ctx.storage_get/set/delete/list` | `ctx.storageGet/Set/Delete/List` |
| `api.config_get/config_set` | `ctx.configGet/configSet` | `ctx.ConfigGet/ConfigSet` | `ctx.config_get/config_set` | `ctx.configGet/configSet` |
| `api.permission_check` | `ctx.permissionCheck` | `ctx.PermissionCheck` | `ctx.permission_check` | `ctx.permissionCheck` |
| `api.context_info` | `ctx.refreshContext` | `ctx.Info` | `ctx.info` | `ctx.info` |

### 6.3 Python 的"超集"部分（**是额外便利，不是能力差异**）

Python 的 `PluginApi` 另有 160+ 个动作包装方法（`send_message` / `group_ban` / `mcp_call` …）与 `kv_*`。
这些是**对同一套 action 通道的语言习语封装**：其它语言用
`ctx.action("send_group_msg", {...})` 得到完全一样的效果（协议层没有差别）。
判断标准很简单：**协议层能力集合必须相等**（§6.1），语言习语封装可以不同。

### 6.4 自查命令

```bash
python3 -m pytest tests/test_plugin_sdk_contract.py -q -rs
# 22 passed / 30 skipped（本机只有 node）；CI 装了 go/rustc/javac → 五种语言全跑
```