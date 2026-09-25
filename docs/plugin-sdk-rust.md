# Rust SDK（flowerie · 零 crate 依赖）

> 任务书第 2 份 §七 / §十五。协议规范：[plugin-protocol.md](plugin-protocol.md)；
> 能力矩阵：[plugin-sdk-capabilities.md](plugin-sdk-capabilities.md)；总览：[plugin-sdk.md](plugin-sdk.md)。
> 源码：`sdk/rust/src/lib.rs` + `sdk/rust/src/json.rs`（自带最小 JSON 编解码）；
> 示例：`examples/rust-plugin/`。

## 1. 定位与依赖

- **零 crate 依赖**：只用 `std~（含自写的 JSON 解析/序列化，`json.rs`）；
- 构建：`rustc --edition 2021`（`examples/rust-plugin/run.sh` 会把 SDK 拷成临时目录再编译，不需要 Cargo）；
- 想用 Cargo 也可以：把 `sdk/rust` 当本地 crate 依赖（示例的 run.sh 走 rustc 直编，CI 就是这么跑的）。

## 2. 最小示例

```rust
mod flowerie;

use flowerie::{Context, Json, Plugin};

fn main() {
    let mut plugin = Plugin::new();

    plugin.on_startup(|ctx: &Context| ctx.log(&format!("启动 {}", ctx.plugin_id)));
    plugin.on_message(|_ctx: &Context, ev: &Json| {
        if ev.get("text").and_then(|v| v.as_str()) == Some("ping") {
            return Some(Json::obj(vec![
                ("type", Json::str("send_group_msg")),
                ("params", Json::obj(vec![
                    ("group_id", ev.get("group_id").cloned().unwrap_or(Json::Null)),
                    ("message", Json::str("pong")),
                ])),
            ]));
        }
        None
    });
    plugin.register_hook("status", |ctx: &Context, _args: &[Json]| {
        Json::obj(vec![("counter", ctx.storage_get("counter").ok().flatten().unwrap_or(Json::Null))])
    });

    // Plugin WebUI Protocol：页面 / 动作 / 资源
    plugin
        .webui()
        .page(|ctx: &Context, _args: &Json| Json::obj(vec![
            ("html", Json::str("<h2>设置</h2>")),
            ("vars", Json::obj(vec![("nickname", Json::str(""))])),
        ]))
        .action(|_ctx: &Context, args: &Json| Json::obj(vec![
            ("message", Json::str("已保存")),
            ("storage_set", args.get("form").cloned().unwrap_or(Json::Null)),
        ]))
        .asset(|_ctx: &Context, _args: &Json| Json::obj(vec![
            ("content_type", Json::str("text/css")),
            ("body", Json::str("body{color:#1f6feb}")),
        ]));

    if let Err(err) = plugin.run() {
        eprintln!("[flowerie] 运行失败: {}", err);
        std::process::exit(1);
    }
}
```

> 注意 hook 与 WebUI 处理器的**第一个参数是 `&Context`**（Rust 闭包不能像 Go/Java 那样捕获 plugin 本体）。
> 另外 `format!` 里要输出引擎的模板变量要写四层花括号：`{{{{ nickname }}}}`。

## 3. API 一览

| 能力 | 用法 |
| :--- | :--- |
| 生命周期 | `on_startup / on_shutdown` · `run()` |
| 事件 | `on_message` · `on_command / on_notice / on_request / on_lifecycle / on_schedule` · `on_event(name, f)` |
| 心跳 | `on_health(|ctx| bool)` |
| 动作 | `ctx.action("send_group_msg", &Json)` |
| 存储 | `ctx.storage_get/set/delete/list` |
| 配置 | `ctx.config_get()` / `ctx.config_set(&Json)` |
| 权限 | `ctx.permission_check("send_message")` |
| 上下文 | `ctx.info()` |
| 日志 | `ctx.log("...")`（stderr） |
| 控制面 hook | `register_hook(name, |ctx, args| ...)` |
| WebUI Protocol | `plugin.webui().page(...).action(...).asset(...)` |

## 与 Python SDK 的能力对照

| 能力 | 本 SDK | Python（runner） |
| :--- | :--- | :--- |
| 必需方法 | initialize / event / health / shutdown | 同 |
| 可选能力（14 项） | context.get · config.get · config.set · permission.check · storage.get/set/delete/list · webui.page/action/asset · **plugin.call/event/cancel** | **完全相同**（`test_handshake_declares_protocol_and_capabilities` 是相等断言，不是子集） |
| 反向通道 | 插件 → 引擎的 engine op / action | 同 |
| 控制面 hook | 具名处理器（插件 WebUI 数据钩子） | `def status(...)` |
| WebUI Protocol | 页面/动作/资源三通道 | 同 |

差异只在**语言习语**：Python 的 `PluginApi` 另有 160+ 个动作包装方法（`send_message` / `group_ban` …），
其它语言用统一的 `action("send_group_msg", {...})` 得到同样效果（协议层没有差别）。

## 自查命令

```bash
python3 -m pytest tests/test_plugin_sdk_contract.py -q -rs -k <lang>
python3 -m pytest tests/test_plugin_webui_multilang.py -q -rs -k <lang>

# 本机缺工具链时会打印 SKIP 原因（不是 pass）；CI 装了 go/rustc/javac/node，全跑
```

## 已知限制

- 引擎按**连接**识别插件身份：插件**不能**（也不需要）自己声明 plugin_id；
- 只有声明过的可选方法才会被引擎调用（`supports()` 门控），所以声明与实现必须一致；
- stdout 只能放协议 JSON（一行一个）；日志一律 stderr，否则会被当成非法行跳过。

## 插件间通信（Plugin-to-Plugin，任务书第 4 份《通信》）

`plugin.call(target, method, params, opts)` / `plugin.emit(name, payload)` /
`plugin.on(name, handler)` / `plugin.expose(method, handler)` / `plugin.cancel(request_id, reason)`：

- 目标可以是 `plugin_a`（任意健康实例）或 `plugin_a#instance1`（指定实例）；
- **跨语言必须经 Core Router**（本 SDK 没有第二条出站通道）；`route` 策略 `auto|core|local` 默认 `auto`；
- 失败一律是结构化错误（`{code,message,data}`，12 个错误码之一），不会退化成一句字符串；
- `trace_id` / `hop_count` 由 SDK 自动传播；等待自己发起的调用响应期间，引擎投递进来的
  `plugin.call` / `plugin.event` / `plugin.cancel` 仍会被处理（插件可重入）；
- 权限 `plugin.call.<target>[.<method>]` / `plugin.emit` 由引擎强制，SDK 无法绕过；
- 不自动重试（§八）。

完整协议见 [plugin-communication.md](plugin-communication.md)。
