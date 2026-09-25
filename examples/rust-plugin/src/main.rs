// Rust 示例插件：与 Python / TypeScript / Go / Java 示例**语义完全一致**。
// 编译运行：run.sh（rustc，零 crate 依赖）；协议规范见 docs/plugin-protocol.md。
mod flowerie;

use flowerie::{CallOptions, Context, Json, Plugin};

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

    // ---------------- Plugin-to-Plugin 通信（任务书《通信》§五/§九/§二十七） ----------------
    // 暴露方法：别的插件（任意语言）可以 plugin.call 过来。handler 收到的是**完整请求模型**
    // （request_id / source / target / method / params / timeout / trace_id / hop_count / ...），
    // 返回值就是 CALL 的 result。注册表与协议主循环共享同一份，on_startup 里注册也等价。
    if let Err(err) = plugin.expose("get_status", |ctx: &Context, request: &Json| {
        // 回执字段与其它四种语言的示例逐项同形：trace_id / hop_count 取不到时退化成 ""/0，
        // echo 取请求模型里的 params（缺失或 null 一律按空对象，与 TS/Go 示例一致）。
        let trace_id = match request.get("trace_id") {
            Some(Json::Str(text)) => Json::Str(text.clone()),
            _ => Json::str(""),
        };
        let hop_count = match request.get("hop_count") {
            Some(Json::Num(number)) => Json::num(*number as i64),
            _ => Json::num(0),
        };
        let echo = match request.get("params") {
            Some(Json::Null) | None => Json::obj(vec![]),
            Some(value) => value.clone(),
        };
        Ok(Json::obj(vec![
            ("plugin_id", Json::str(&ctx.plugin_id)),
            ("runtime", Json::str("rust")),
            ("trace_id", trace_id),
            ("hop_count", hop_count),
            ("echo", echo),
        ]))
    }) {
        eprintln!("[flowerie] expose(get_status) 失败: {}", err);
    }

    // hook comm_call：args = [target, method, params] -> SDK 的 plugin.call（经 Core Router）；
    // 第 4 个参数可选（超时毫秒）、第 5 个可选（route），与 Python / Go / Java 示例同义。
    // 失败**不抛**（Rust 里即不 panic），按契约回 {"ok":false,"code":...,"message":...}。
    plugin.register_hook("comm_call", |ctx: &Context, args: &[Json]| {
        let target = args.first().and_then(|v| v.as_str()).unwrap_or("");
        let method = args.get(1).and_then(|v| v.as_str()).unwrap_or("");
        let params = args.get(2).cloned().unwrap_or_else(|| Json::obj(vec![]));
        let mut options = CallOptions::default();
        if let Some(timeout) = args.get(3).and_then(|v| v.as_f64()) {
            if timeout > 0.0 {
                options = options.with_timeout(timeout as i64);
            }
        }
        if let Some(route) = args.get(4).and_then(|v| v.as_str()) {
            if !route.is_empty() {
                options = options.with_route(route);
            }
        }
        match ctx.call(target, method, &params, options) {
            Ok(result) => Json::obj(vec![("ok", Json::Bool(true)), ("result", result)]),
            Err(err) => Json::obj(vec![
                ("ok", Json::Bool(false)),
                ("code", Json::str(&err.code)),
                ("message", Json::str(&err.message)),
            ]),
        }
    });

    // hook comm_emit：args = [name, payload] -> plugin.emit，返回引擎的投递结果。
    plugin.register_hook("comm_emit", |ctx: &Context, args: &[Json]| {
        let name = args.first().and_then(|v| v.as_str()).unwrap_or("");
        let payload = args.get(1).cloned().unwrap_or_else(|| Json::obj(vec![]));
        match ctx.emit(name, &payload) {
            Ok(outcome) => Json::obj(vec![
                ("ok", Json::Bool(true)),
                ("delivered", Json::num(outcome.delivered as i64)),
                ("failed", Json::Arr(outcome.failed)),
                ("trace_id", Json::str(&outcome.trace_id)),
            ]),
            Err(err) => Json::obj(vec![
                ("ok", Json::Bool(false)),
                ("code", Json::str(&err.code)),
                ("message", Json::str(&err.message)),
            ]),
        }
    });

    // 事件订阅（§九）：与 Java 示例一致挂一个通配订阅，证明 EVENT 通道真的到达了插件
    // （handler 返回 ()；引擎关心的是「有没有投递到」，handled 计数由 SDK 回给引擎）。
    let _ = plugin.on("*", |ctx: &Context, event: &Json| {
        let name = event.get("name").and_then(|v| v.as_str()).unwrap_or("");
        ctx.log(&format!("收到插件事件 name={}", name));
    });

    // hook comm_cancel：args = [request_id, reason] -> plugin.cancel（与 Python 示例对齐）。
    plugin.register_hook("comm_cancel", |ctx: &Context, args: &[Json]| {
        let request_id = args.first().and_then(|v| v.as_str()).unwrap_or("");
        let reason = args.get(1).and_then(|v| v.as_str()).unwrap_or("");
        match ctx.cancel(request_id, reason) {
            Ok(outcome) => Json::obj(vec![
                ("ok", Json::Bool(true)),
                ("request_id", Json::str(&outcome.request_id)),
                ("cancelled", Json::Bool(outcome.cancelled)),
                ("target", Json::str(&outcome.target)),
            ]),
            Err(err) => Json::obj(vec![
                ("ok", Json::Bool(false)),
                ("code", Json::str(&err.code)),
                ("message", Json::str(&err.message)),
            ]),
        }
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
        .page(|ctx: &Context, args: &Json| {
            Json::obj(vec![
                ("html", Json::str(&settings_form(&ctx_plugin_id(args, &ctx.plugin_id)))),
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
                ("html", Json::str(&settings_form(&ctx_plugin_id(args, &ctx.plugin_id)))),
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

/// 取引擎给的受控 context 里的 plugin.id（插件不自己声明身份），拿不到再退回本地 ctx。
fn ctx_plugin_id(args: &Json, fallback: &str) -> String {
    args.get("context")
        .and_then(|context| context.get("plugin"))
        .and_then(|plugin| plugin.get("id"))
        .and_then(|id| id.as_str())
        .map(|id| id.to_string())
        .unwrap_or_else(|| fallback.to_string())
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
