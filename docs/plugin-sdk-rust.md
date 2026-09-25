# Rust SDK（flowerie · 零 crate 依赖）

> 总览与通用规则：[plugin-sdk.md](plugin-sdk.md)｜协议：[plugin-protocol.md](plugin-protocol.md)｜能力矩阵：[plugin-sdk-capabilities.md](plugin-sdk-capabilities.md)
> 源码 `sdk/rust/src/lib.rs` + `sdk/rust/src/json.rs` · 示例 `examples/multilang-sdk/rust/`（契约/WebUI 用例另跑 `examples/rust-plugin/`）· CI 实测：`tests/sdk/test_minimal_plugins.py::test_build_load_ready_and_api[rust]`、`tests/sdk/test_minimal_paths.py::test_plugin_communication_path[rust->java]`、`tests/test_plugin_sdk_contract.py::test_plugin_call_inbound_matches_vector[rust]`、`tests/test_plugin_webui_multilang.py::test_webui_action_save_is_identical[rust]`

## 1. 安装与引入
- 工具链：`rustc --edition 2021`（≥1.70）——只要编译器，**不用 cargo、不联网**（`examples/multilang-sdk/rust/build.sh:33,83`；仓库里没有 `sdk/rust/Cargo.toml`）。
- **零 crate 依赖**：只用 `std`（`lib.rs:2`），JSON 编解码自带（`sdk/rust/src/json.rs:1-4`，不拉 serde）。
- 引入：把 `sdk/rust/src/lib.rs` 拷成 `<源码根>/flowerie/mod.rs`、`json.rs` 拷成 `flowerie/json.rs`，入口写 `mod flowerie;`（`lib.rs:18` 的 `pub mod json;`；布局见 `examples/rust-plugin/run.sh:7-10`）。
- 环境变量：定位 SDK 用 `FLOWERIE_SDK_RUST` / `FLOWERIE_RUST_SDK_DIR` / `FLOWERIE_SDK_DIR` / `FLOWERIE_REPO_ROOT` / `GITHUB_WORKSPACE`（`build.sh:31,43,63`）；`FLOWERIE_RUSTC` 换编译器、`FLOWERIE_RUST_BIN` 换产物路径、`FLOWERIE_RUST_BUILD_DIR` 换临时构建目录。

## 2. 最小插件（可直接复制）
清单键值同 `examples/multilang-sdk/rust/manifest.json`（省略 `description`；`src/plugins/manifest.py:125` 的七个必填字段齐全，`web_ui` 见 §6）：
```json
{ "id": "minimal_rust", "name": "Minimal Rust Plugin", "version": "1.0.0", "author": "Flowerie",
  "runtime": "exec", "entry": "run.sh", "api_version": 1,
  "permissions": ["read_message", "send_message", "plugin.call.*", "plugin.emit", "web_ui"] }
```
入口结构取自 `examples/rust-plugin/src/main.rs:3-26`，动作形状用 `examples/multilang-sdk/rust/src/main.rs:696-702` 的**可执行**写法：
```rust
mod flowerie;
use flowerie::{Context, Json, Plugin};

fn main() {
    let mut plugin = Plugin::new();
    plugin.on_message(|_ctx: &Context, ev: &Json| {
        if ev.get("text").and_then(|v| v.as_str()) != Some("ping") {
            return None;                                  // 不匹配回 None = 无动作
        }
        Some(Json::obj(vec![
            ("type", Json::str("send_message")),          // 引擎只读 action["payload"]（manager.py:1329）
            ("payload", Json::obj(vec![
                ("group_id", ev.get("group_id").cloned().unwrap_or(Json::Null)),
                ("message", Json::str("pong")),
            ])),
        ]))
    });
    if let Err(err) = plugin.run() {
        eprintln!("[flowerie] 运行失败: {}", err);
        std::process::exit(1);
    }
}
```

## 3. 事件注册（出处 `sdk/rust/src/lib.rs`）
| 事件 / 钩子 | 本语言写法 |
| :--- | :--- |
| initialize / shutdown / `message` | `plugin.on_startup(f)` :374 · `plugin.on_shutdown(f)` :380 · `plugin.on_message(f)`，`f: Fn(&Context, &Json) -> Option<Json>` :386（`message` 走独立列表 :665-669）|
| `command` / `notice` / `request` / `lifecycle` / `schedule` | `on_command` / `on_notice` / `on_request` / `on_lifecycle` / `on_schedule`，都是 `on_event("<名>", f)` 的别名（:404-426）；任意事件用 `on_event(name, f)` :392 |
| health / 控制面 hook / 插件事件订阅 | `on_health(f)`，`f: Fn(&Context) -> bool` :398 · `register_hook(name, f)`，`f: Fn(&Context, &[Json]) -> Json` :429 · `ctx.on(name, f)` / `plugin.on(name, f)`，`"*"` 订阅全部（:1026 / :1250）|

## 4. API 表（出处 `lib.rs`；JSON 相关在 `json.rs`）
| 能力 | 本语言签名 |
| :--- | :--- |
| 生命周期 / 日志 | `Plugin::new()` :349 · `plugin.run()` :445 · `plugin.context()` :440 · `ctx.log(&str)` → stderr :104 ｜ 动作 / 存储：`ctx.action(action_type, &Json) -> Result<Json, String>` :237 · `storage_get(key)` :122 · `storage_set(key, &Json)` :131 · `storage_delete(key)` :150 · `storage_list(prefix)` :156 |
| 配置 / 权限 / 上下文 | `config_get()` :183 · `config_set(&Json)` :195 · `permission_check(&str)` :224 · `info()` :231 · 字段 `ctx.plugin_id` / `ctx.plugin_dir` / `ctx.data_dir` :78-80 |
| JSON / WebUI | `Json::obj/str/num`、`get/as_str/as_f64/as_bool/as_arr/dump`（`json.rs:22-78`）、`parse_json` :20 · `plugin.webui().page(f).action(f).asset(f)`（:435 / :332 / :337 / :342）|
| 插件间通信 / 错误 | `ctx.call` :931 · `emit` :956 · `cancel` :984 · `expose` :1005 · `unexpose` :1021 · `on` :1026 · `exposed_methods` :1042 · `comm_context` :920 · `CallOptions::default().with_timeout(ms).with_route(route)` :745-766 · `PluginCommError`（:813-881）/ `EmitResult` :771 / `CancelResult` :782 |

## 5. 存储 / 配置 / 权限（通用语义见 [plugin-sdk.md §5](plugin-sdk.md#5-存储配置与权限)）
- 存储：一文件一键 `<ctx.data_dir>/storage/<key>.json`，键须字母数字开头、≤64、可含 `. _ -`，上限 200 键 / 64 KiB（:28-29、:108-119）。
- 配置：`config_set` 只写自己的 `<ctx.data_dir>/config.json` 覆盖层（≤64 键 / 8 KiB）；`config_get` 叠加引擎的操作员值且**操作员优先**（:30-31、:171-221）。
- 权限：`ctx.permission_check(p)` 是只读查询（反向 engine op），不能借此提权（:224-228）。

## 6. WebUI
```json
"web_ui": { "static": "static", "entry": "webui_page",
  "pages": [ { "id": "index", "title": "Index", "render": "plugin" },
             { "id": "communication", "title": "Communication", "render": "plugin" } ] }
```
- 三通道一条链注册：`plugin.webui().page(f).action(f).asset(f)`，`f: Fn(&Context, &Json) -> Json`（:435 / :332 / :337 / :342）；返回 `Json::Str` = `{html}` 简写；`Json::Obj` 只透传白名单字段（:683-699）；文件页数据钩子用 `register_hook("webui_page", f)` 回 `vars`（`examples/rust-plugin/src/main.rs:161-165`，page/action/asset 真实处理器 :167-208）。

## 7. 插件间通信
入口与 Python 的 `api.plugin.*` 一一对应：`ctx.expose` / `unexpose` / `on` / `call` / `emit` / `cancel` / `exposed_methods` / `comm_context`（`lib.rs:916-1046`），`Plugin` 上还有同名转发（:1233-1278）。失败一律 `Result::Err(PluginCommError)`（`code`/`message`/`data` 取 12 个错误码之一），不退化成字符串、不自动重试（:808-889）。通用语义见 [plugin-sdk.md §7](plugin-sdk.md#7-插件间通信)。

## 8. 构建与运行
- 构建（`examples/multilang-sdk/rust/build.sh`）：把 SDK 拷成 `.build/src/flowerie/{mod.rs,json.rs}`、入口拷成 `.build/src/main.rs`，再跑 `rustc --edition 2021 -O -o .build/minimal_rust .build/src/main.rs`（:77-83）；产物 `.build/minimal_rust`。
- 缺 `rustc`（可用 `FLOWERIE_RUSTC` 换）打印「请安装 Rust >= 1.70」并非零退出（:31-35）；找不到 `sdk/rust/src/{lib.rs,json.rs}` 同样非零退出，可用 `FLOWERIE_SDK_RUST` 指路（:38-72）；运行：`sh run.sh` 只 `exec` 产物（路径可用 `FLOWERIE_RUST_BIN` 覆盖），产物不存在就报错退出、**绝不隐式编译**（`run.sh:9-21`）；CI 侧 `tests/sdk/harness.py:81-112` 真拷目录、真跑 build.sh（超时 1800s），构建失败不进缓存。

## 9. 常见错误
| 症状 | 原因 → 处理（出处）|
| :--- | :--- |
| 写成 `{"type":"send_group_msg","params":{…}}`，引擎不执行任何动作 | `send_group_msg` 不是插件动作类型，且引擎只读 `action["payload"]`、从不读 `params`（`src/plugins/manager.py:1327-1329`）→ 用 `{"type":"send_message","payload":{…}}`（`examples/multilang-sdk/rust/src/main.rs:696-702`）|
| `hook status` 返回 `{"counter":null}` | 早期 `register_hook` 闭包只拿到 args、读不到 storage（CI 抓到的真问题）→ 现签名是 `Fn(&Context, &[Json]) -> Json`，用 `ctx.storage_get`（`lib.rs:429`）|
| 页面里 `{{ nickname }}` 没被替换，或 `format!` 直接编译不过 | `format!` 把花括号当自己的占位符 → 写四层花括号 `{{{{ nickname }}}}`（`examples/rust-plugin/src/main.rs:245-247`）；编译报 `file not found for module flowerie` 则是 `mod flowerie;` 同级缺 `flowerie/mod.rs`（要连 `flowerie/json.rs` 一起）→ 按 `examples/rust-plugin/run.sh:7-10` 的布局拷 SDK |
