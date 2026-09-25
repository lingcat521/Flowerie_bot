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


    // ---------------- Plugin WebUI Protocol（任务书第 3 份 §六） ----------------
    // 页面 / 动作 / 资源三条通道；路由、权限、校验、净化、隔离全部由引擎负责。

    // HTML 文件页的模板变量（走 web_ui.entry 数据钩子）
    plugin.register_hook("webui_page", |ctx: &Context, _args: &[Json]| {
        Json::obj(vec![("vars", Json::obj(vec![
            ("nickname", Json::str(&read_nickname(ctx))),
        ]))])
    });

    plugin
        .webui()
        .page(|ctx: &Context, _args: &Json| {
            Json::obj(vec![
                ("html", Json::str(&settings_form(&ctx.plugin_id))),
                ("vars", Json::obj(vec![("nickname", Json::str(&read_nickname(ctx)))])),
            ])
        })
        .action(|ctx: &Context, args: &Json| {
            let action = args.get("action").and_then(|v| v.as_str()).unwrap_or("");
            if action != "save" {
                return Json::obj(vec![
                    ("ok", Json::Bool(false)),
                    ("error", Json::str(&format!("未知动作: {}", action))),
                ]);
            }
            let nickname = args
                .get("form")
                .and_then(|form| form.get("nickname"))
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            Json::obj(vec![
                ("html", Json::str(&settings_form(&ctx.plugin_id))),
                ("vars", Json::obj(vec![("nickname", Json::str(&nickname))])),
                ("message", Json::str("已保存")),
                ("config_set", Json::obj(vec![("nickname", Json::str(&nickname))])),
                ("storage_set", Json::obj(vec![("nickname", Json::str(&nickname))])),
            ])
        })
        .asset(|_ctx: &Context, args: &Json| {
            if args.get("path").and_then(|v| v.as_str()) == Some("theme.css") {
                return Json::obj(vec![
                    ("content_type", Json::str("text/css")),
                    ("body", Json::str("body { color: #1f6feb; }")),
                ]);
            }
            Json::obj(vec![
                ("ok", Json::Bool(false)),
                ("error", Json::str("资源不存在")),
            ])
        });

    plugin.on_shutdown(|ctx: &Context| {
        ctx.log("rust 示例插件退出");
    });

    if let Err(err) = plugin.run() {
        eprintln!("[flowerie] 运行失败: {}", err);
        std::process::exit(1);
    }
}

/// 读本插件 storage 里的昵称（与 `Context::storage_get` 同一份文件）。
fn read_nickname(ctx: &Context) -> String {
    match ctx.storage_get("nickname") {
        Ok(Some(Json::Str(text))) => text,
        _ => String::new(),
    }
}

/// 插件渲染页的 HTML：{{ nickname }} 由引擎 escape 后替换（受控模板变量）。
fn settings_form(plugin_id: &str) -> String {
    format!(
        "<h2>插件渲染页</h2>\
         <p class=\"who\">这份 HTML 来自插件进程（webui.page），不是磁盘文件。</p>\
         <form class=\"card\" method=\"post\" action=\"/panel/plugins/webui/{}/dynamic\">\
         <input type=\"hidden\" name=\"plugin_action\" value=\"save\">\
         <label>昵称 <input name=\"nickname\" value=\"{{{{ nickname }}}}\" maxlength=\"64\"></label>\
         <button type=\"submit\">保存</button></form>\
         <p class=\"msg\">{{{{ message }}}}</p>",
        plugin_id
    )
}
