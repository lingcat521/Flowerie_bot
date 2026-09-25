// Rust 示例插件：与 Python / TypeScript / Go / Java 示例**语义完全一致**。
// 编译运行：run.sh（rustc，零 crate 依赖）；协议规范见 docs/plugin-protocol.md。
mod flowerie;

use flowerie::{Context, Json, Plugin};

fn main() {
    let mut plugin = Plugin::new();

    plugin.on_startup(|ctx: &Context| {
        ctx.log(&format!("rust 示例插件启动 plugin_id={}", ctx.plugin_id));
    });

    plugin.on_message(|_ctx: &Context, ev: &Json| {
        if ev.get("text").and_then(|v| v.as_str()) == Some("ping") {
            let group_id = ev.get("group_id").cloned().unwrap_or(Json::Null);
            return Some(Json::obj(vec![
                ("type", Json::str("send_group_msg")),
                ("params", Json::obj(vec![
                    ("group_id", group_id),
                    ("message", Json::str("pong")),
                ])),
            ]));
        }
        None
    });

    // 命令事件（与 Python 的 on_command 对齐）：/ping → pong
    plugin.on_command(|_ctx: &Context, ev: &Json| {
        if ev.get("text").and_then(|v| v.as_str()) == Some("/ping") {
            let group_id = ev.get("group_id").cloned().unwrap_or(Json::Null);
            return Some(Json::obj(vec![
                ("type", Json::str("send_group_msg")),
                ("params", Json::obj(vec![
                    ("group_id", group_id),
                    ("message", Json::str("pong")),
                ])),
            ]));
        }
        None
    });

    // 控制面 hook：插件 WebUI 的数据钩子走同一条通道。
    // 与其它语言示例语义一致：读本插件 storage 的 counter.n（没有则 null）。
    plugin.register_hook("status", |ctx: &Context, _args: &[Json]| {
        let counter = match ctx.storage_get("counter") {
            Ok(Some(value)) => value.get("n").cloned().unwrap_or(Json::Null),
            _ => Json::Null,
        };
        Json::obj(vec![("counter", counter)])
    });

    plugin.on_shutdown(|ctx: &Context| {
        ctx.log("rust 示例插件退出");
    });

    if let Err(err) = plugin.run() {
        eprintln!("[flowerie] 运行失败: {}", err);
        std::process::exit(1);
    }
}
