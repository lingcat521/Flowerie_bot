//! minimal_rust：任务书《插件测试》的最小 Rust 插件（与 Python/TS/Go/Java 最小插件语义完全一致）。
//!
//! 只用仓库自带的 Rust SDK（sdk/rust/src/{lib.rs,json.rs}，**零 crate 依赖**，不用 cargo）：
//!   * 暴露方法（expose）：ping / get_info / echo / slow / boom / seen；
//!   * 事件：test.event 记录 payload，并用 SDK 日志打一行 [test.event] <message>；
//!   * 命令：只响应 /sdk@<自己的 plugin_id> <命令>（message 事件是广播给所有插件的，
//!     不寻址会让多个插件同时回包）；老形式 /sdk <命令> 作为兼容也接受。
//!
//! 构建：build.sh（rustc，产物 .build/minimal_rust）；入口：run.sh（只 exec 产物，不编译）。
//!
//! 动作形状（容易踩的坑）：引擎执行事件动作时读的是 action["payload"]，所以回包是
//! {"type":"send_message","payload":{"group_id":…,"message":"<结果 JSON 字符串>"}}；
//! 仓库旧示例里的 {"type":"send_group_msg","params":{…}} 只被断言、不被执行，别照抄。

mod flowerie;

use std::collections::BTreeMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use flowerie::{parse_json, CallOptions, Context, Json, Plugin, PluginCommError, PROTOCOL_VERSION};

/// SDK 版本（SDK 本身没导出这个常量；与其它四种语言的最小插件取同一个值）。
const SDK_VERSION: &str = "1.0.0";
/// WebUI 页面上的 Language 一行。
const LANGUAGE_NAME: &str = "Rust";
/// WebUI 页面上的 SDK 一行（SDK 源码位置，与其它四种语言的写法同形）。
const SDK_NAME: &str = "sdk/rust";
/// 协议里的语言标识（ping 的 runtime 字段）。
const RUNTIME: &str = "rust";
/// plugin_id 兜底：正常路径下 initialize 一定会把真实 id 告诉插件。
const FALLBACK_PLUGIN_ID: &str = "minimal_rust";
/// slow 探针的睡眠时长（TIMEOUT 探针用 200ms 超时打它）。
const SLOW_MS: u64 = 1500;
/// TIMEOUT 探针的调用超时（毫秒）。
const PROBE_TIMEOUT_MS: i64 = 200;

// ==================== 插件状态 ====================

/// 收到的 test.event：payload 与对应的日志行（seen 两者都回，不依赖各语言日志通道）。
#[derive(Default)]
struct SeenState {
    events: Vec<Json>,
    logs: Vec<String>,
}

/// SDK 的处理器签名是 Fn（不是 FnMut），状态因此放在静态里；
/// 插件进程是单线程的，Mutex 只为满足 static 的 Sync 要求（不会真的竞争）。
static SEEN: Mutex<SeenState> = Mutex::new(SeenState { events: Vec::new(), logs: Vec::new() });

/// 取状态锁；中毒（某个处理器 panic 过）也继续用里面的数据，不让插件因此瘫掉。
fn seen_lock() -> std::sync::MutexGuard<'static, SeenState> {
    match SEEN.lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    }
}

// ==================== 入口 ====================

fn main() {
    let mut plugin = Plugin::new();

    plugin.on_startup(|ctx: &Context| {
        ctx.log(&format!("minimal rust 插件启动 plugin_id={}", plugin_id(ctx)));
    });

    // ---------- 暴露方法（§三）：别的插件 plugin.call 过来时执行 ----------
    if let Err(err) = plugin.expose("ping", expose_ping) {
        eprintln!("[flowerie] expose(ping) 失败: {}", err);
    }
    if let Err(err) = plugin.expose("get_info", expose_get_info) {
        eprintln!("[flowerie] expose(get_info) 失败: {}", err);
    }
    if let Err(err) = plugin.expose("echo", expose_echo) {
        eprintln!("[flowerie] expose(echo) 失败: {}", err);
    }
    if let Err(err) = plugin.expose("slow", expose_slow) {
        eprintln!("[flowerie] expose(slow) 失败: {}", err);
    }
    if let Err(err) = plugin.expose("boom", expose_boom) {
        eprintln!("[flowerie] expose(boom) 失败: {}", err);
    }
    if let Err(err) = plugin.expose("seen", expose_seen) {
        eprintln!("[flowerie] expose(seen) 失败: {}", err);
    }

    // ---------- 事件（§四）：test.event 记录 payload + 打日志行 ----------
    plugin.on_event("test.event", handle_test_event);

    // ---------- 消息命令（§六）：/sdk@<自己> … -> 动作回包 ----------
    plugin.on_message(handle_message);

    plugin.on_shutdown(|ctx: &Context| {
        ctx.log("minimal rust 插件退出");
    });

    // ---------- §23/§12 WebUI：与其它四种语言**同一套** API（page / action） ----------
    // HTML 文件页的模板变量（manifest 的 web_ui.entry，与其它语言同名同义）。
    plugin.register_hook("webui_page", |ctx: &Context, args: &[Json]| {
        if args.first().and_then(|value| value.as_str()) == Some("communication") {
            return Json::obj(vec![("vars", Json::Obj(communication_vars(&plugin_id(ctx))))]);
        }
        Json::obj(vec![("vars", webui_vars(&plugin_id(ctx)))])
    });
    // 插件渲染页（index / communication）：Plugin 取受控 context 的 plugin id。
    plugin
        .webui()
        .page(|ctx: &Context, args: &Json| {
            let id = ctx_plugin_id(args, &plugin_id(ctx));
            let page = args.get("page").cloned().unwrap_or(Json::Null);
            if page_id(&page) == "communication" {
                let context = args.get("context").cloned().unwrap_or_else(|| Json::obj(vec![]));
                let form = context_form(&context);
                let has_form = matches!(&form, Json::Obj(map) if !map.is_empty());
                let vars = if is_call_action(&context) && has_form {
                    apply_call(ctx, &form, &id)
                } else {
                    communication_vars(&id)
                };
                return Json::obj(vec![
                    ("html", Json::str(&communication_html(&vars))),
                    ("vars", Json::Obj(vars)),
                ]);
            }
            Json::obj(vec![
                ("html", Json::str(&webui_html(&id))),
                ("vars", webui_vars(&id)),
            ])
        })
        .action(|ctx: &Context, args: &Json| {
            // 调用页的 POST（按钮 name=plugin_action value=call）-> 真调用 -> 重渲染。
            let id = ctx_plugin_id(args, &plugin_id(ctx));
            let action = args.get("action").and_then(|value| value.as_str()).unwrap_or("").to_string();
            let page = args.get("page").cloned().unwrap_or(Json::Null);
            if page_id(&page) != "communication" {
                return Json::obj(vec![("ok", Json::Bool(false)),
                                      ("error", Json::str(&format!("未知动作: {}", action)))]);
            }
            let form = args.get("form").cloned().unwrap_or_else(|| Json::obj(vec![]));
            let is_call = action == "call" || json_str_of(&form, "plugin_action") == "call";
            let vars = if is_call {
                apply_call(ctx, &form, &id)
            } else {
                let mut vars = communication_vars(&id);
                vars.insert("message".to_string(), Json::str(&format!("未知动作: {}", action)));
                vars
            };
            let message = var_str(&vars, "message");
            Json::obj(vec![
                ("html", Json::str(&communication_html(&vars))),
                ("vars", Json::Obj(vars)),
                ("message", Json::str(&message)),
            ])
        });

    if let Err(err) = plugin.run() {
        eprintln!("[flowerie] 运行失败: {}", err);
        std::process::exit(1);
    }
}

// ==================== 身份 / 返回体 ====================

/// 自己的 plugin_id（引擎在 initialize 里告诉插件；拿不到时退化为契约里的默认 id）。
fn plugin_id(ctx: &Context) -> String {
    let raw = ctx.plugin_id.trim();
    if raw.is_empty() || raw == "unknown" {
        FALLBACK_PLUGIN_ID.to_string()
    } else {
        raw.to_string()
    }
}

/// label = plugin_id 把下划线换成短横线（例如 minimal_rust -> minimal-rust）。
fn label(ctx: &Context) -> String {
    plugin_id(ctx).replace('_', "-")
}

// ---------------- WebUI 最小页面（任务书《plugin_to_webui》§23） ----------------
// 五种语言共用**同一套** WebUI API：页面由插件经 webui.page 返回 HTML（No-JS：只有 HTML + CSS）。
// 路由 / 权限 / 校验 / 净化 / 隔离全部由引擎负责，插件只负责内容。
// Plugin 与 Runtime 取自受控 context 与 SDK 值，不写死在 HTML 里（部署方改名后页面自动跟随）。

/// 受控 context 里的 plugin id（引擎按连接识别身份；拿不到才退回 SDK 的 plugin id）。
fn ctx_plugin_id(args: &Json, fallback: &str) -> String {
    args.get("context")
        .and_then(|context| context.get("plugin"))
        .and_then(|plugin| plugin.get("id"))
        .and_then(|id| id.as_str())
        .filter(|id| !id.is_empty())
        .map(|id| id.to_string())
        .unwrap_or_else(|| fallback.to_string())
}

/// 本语言原生的 HTML 转义（插件不假设引擎一定会替自己转义动态数据）。
fn escape_html(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    for ch in value.chars() {
        match ch {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&#39;"),
            _ => out.push(ch),
        }
    }
    out
}

/// WebUI 模板变量（HTML 文件页的数据钩子与插件渲染页共用一份）。
fn webui_vars(plugin_id: &str) -> Json {
    Json::obj(vec![
        ("language", Json::str(LANGUAGE_NAME)),
        ("sdk", Json::str(&format!("{} {}", SDK_NAME, SDK_VERSION))),
        ("plugin_id", Json::str(plugin_id)),
        ("runtime", Json::str(RUNTIME)),
    ])
}

/// 最小 WebUI 页面：<h2>插件页</h2> + Language / SDK / Plugin / Runtime 四项。
fn webui_html(plugin_id: &str) -> String {
    let style = format!("/panel/plugins/webui/{}/static/style.css", plugin_id);
    format!(
        "<link rel=\"stylesheet\" href=\"{}\">\
         <h2>插件页</h2>\
         <dl class=\"flowerie-webui lang-{}\" id=\"plugin-info\">\
         <dt>Language</dt><dd class=\"language\">{}</dd>\
         <dt>SDK</dt><dd class=\"sdk\">{} {}</dd>\
         <dt>Plugin</dt><dd class=\"plugin\">{}</dd>\
         <dt>Runtime</dt><dd class=\"runtime\">{}</dd>\
         </dl>",
        escape_html(&style),
        RUNTIME,
        escape_html(LANGUAGE_NAME),
        escape_html(SDK_NAME),
        SDK_VERSION,
        escape_html(plugin_id),
        escape_html(RUNTIME)
    )
}

// ---------------- WebUI 调用页（任务书《plugin_to_webui》§12/§28） ----------------
// 页面契约见 tests/e2e/README.md §3：元素 id 就是断言契约；零 JS：form POST + 服务端渲染。
// 真调用：plugin.call -> 引擎 Core Router -> **目标插件进程** -> 结果回本页（失败也如实显示）。
// 关联 id：随请求发给目标、由目标原样带回（echo 原样回 params 即往返证明）；拿不到就如实标注。

/// 默认请求（与 tests/e2e 的链路请求同形）。
const DEFAULT_REQUEST: &str = "{\"hello\": \"world\"}";
/// 引擎给 webui.action 的上限是 4s，这里给 plugin.call 留足余量。
const CALL_TIMEOUT_MS: i64 = 2500;
/// 随请求往返的关联 id（与 tests/e2e 夹具插件同一约定）。
const TRACE_KEY: &str = "_e2e_trace";
/// 目标没回传时的如实标注。
const UNRETURNED: &str = "（对端未回传）";
const COMM_METHODS: [&str; 4] = ["ping", "echo", "get_info", "no_such_method"];
const COMM_ROUTES: [&str; 3] = ["auto", "core", "local"];

/// 本页调用序号（单线程插件进程；原子只是为了让 Fn 处理器无副作用）。
static CALL_SEQ: AtomicU64 = AtomicU64::new(0);

/// 本页这次调用的关联 id（插件侧生成）。
fn new_call_id() -> String {
    let seq = CALL_SEQ.fetch_add(1, Ordering::Relaxed);
    let nanos = SystemTime::now().duration_since(UNIX_EPOCH)
        .map(|value| value.as_nanos()).unwrap_or(0);
    format!("{:x}{:02x}", nanos, seq)
}

/// 取字符串字段（缺失/类型不对一律空串）。
fn json_str_of(obj: &Json, key: &str) -> String {
    obj.get(key).and_then(|value| value.as_str()).unwrap_or("").to_string()
}

/// 取 page 的 id（引擎给的是对象 {id,title,description}）。
fn page_id(page: &Json) -> String {
    let id = json_str_of(page, "id");
    if !id.is_empty() {
        return id;
    }
    page.as_str().unwrap_or("index").to_string()
}

/// 引擎若把表单塞进 context（当前版本不塞；webui.action 的 form 才是常规通道）。
fn context_form(context: &Json) -> Json {
    context.get("form").cloned().unwrap_or_else(|| Json::obj(vec![]))
}

/// context 里的这次请求是不是 POST 的 call（引擎按表单的 plugin_action 填 request.action）。
fn is_call_action(context: &Json) -> bool {
    context.get("request").and_then(|request| request.get("action"))
        .and_then(|action| action.as_str()) == Some("call")
}

/// 目标插件**自报**的 runtime：先看回包，再问一次 get_info；都拿不到就留空（不编造）。
fn observed_runtime(ctx: &Context, target: &str, route_policy: &str, result: &Json) -> String {
    let runtime = json_str_of(result, "runtime");
    if !runtime.is_empty() {
        return runtime;
    }
    let options = CallOptions::default().with_timeout(CALL_TIMEOUT_MS).with_route(route_policy);
    match ctx.call(target, "get_info", &Json::obj(vec![]), options) {
        Ok(info) => json_str_of(&info, "runtime"),
        Err(_) => String::new(),
    }
}

/// 真调用目标插件；任何失败都变成页面可渲染的结构化结果。
fn call_target(ctx: &Context, target: &str, method: &str, request_text: &str,
               route_policy: &str) -> Json {
    let trimmed = request_text.trim();
    let parsed = if trimmed.is_empty() { Json::obj(vec![]) } else {
        match parse_json(trimmed) {
            Ok(value) => value,
            Err(err) => return Json::obj(vec![
                ("response_ok", Json::str("error")),
                ("error_code", Json::str("INVALID_ARGUMENT")),
                ("error", Json::str(&format!("INVALID_ARGUMENT: request 不是合法 JSON: {}", err)))]),
        }
    };
    let payload = match parsed {
        Json::Obj(_) => parsed,
        _ => return Json::obj(vec![
            ("response_ok", Json::str("error")),
            ("error_code", Json::str("INVALID_ARGUMENT")),
            ("error", Json::str("INVALID_ARGUMENT: request 必须是 JSON 对象"))]),
    };
    let call_id = new_call_id();
    let mut pairs: Vec<(&str, Json)> = Vec::new();
    if let Json::Obj(map) = &payload {
        for (key, value) in map.iter() {
            pairs.push((key.as_str(), value.clone()));
        }
    }
    pairs.push((TRACE_KEY, Json::str(&call_id))); // 发给目标；echo 原样带回 -> 证明回包来自目标
    let params = Json::obj(pairs);
    let options = CallOptions::default().with_timeout(CALL_TIMEOUT_MS).with_route(route_policy);
    let result = match ctx.call(target, method, &params, options) {
        Ok(value) => value,
        Err(err) => {
            let code = if err.code.is_empty() { "PLUGIN_ERROR".to_string() } else { err.code.clone() };
            let body = Json::obj(vec![
                ("ok", Json::Bool(false)),
                ("error", Json::obj(vec![("code", Json::str(&code)),
                                         ("message", Json::str(&err.message))]))]);
            return Json::obj(vec![
                ("response", Json::str(&body.dump())),
                ("response_ok", Json::str("error")),
                ("error_code", Json::str(&code)),
                ("error", Json::str(&format!("{}: {}", code, err.message))),
                ("request_id", Json::str(&call_id)),
                ("request_id_source", Json::str("插件侧 call id（调用失败）")),
                ("trace_id", Json::str(&call_id)),
                ("trace_id_source", Json::str("插件侧（调用失败，无回包）"))]);
        }
    };
    let trace_back = {
        let direct = json_str_of(&result, TRACE_KEY);
        if direct.is_empty() { json_str_of(&result, "trace_id") } else { direct }
    };
    // 对端回传的引擎字段：_engine 块（夹具约定）与顶层平铺（README §3 约定）都认。
    let engine = result.get("_engine").cloned().unwrap_or_else(|| Json::obj(vec![]));
    let mut engine_request_id = json_str_of(&engine, "request_id");
    let mut engine_trace_id = json_str_of(&engine, "trace_id");
    let mut engine_route = json_str_of(&engine, "route");
    if engine_request_id.is_empty() { engine_request_id = json_str_of(&result, "request_id"); }
    if engine_trace_id.is_empty() { engine_trace_id = json_str_of(&result, "trace_id"); }
    if engine_route.is_empty() { engine_route = json_str_of(&result, "route"); }
    let (trace_id, trace_source) = if !engine_trace_id.is_empty() {
        (engine_trace_id, "引擎（目标插件回传）")
    } else if !trace_back.is_empty() {
        (trace_back, "目标插件原样回传（随请求往返）")
    } else {
        (call_id.clone(), "插件侧（无回包）")
    };
    let (request_id, request_source) = if engine_request_id.is_empty() {
        (call_id, "插件侧 call id")
    } else {
        (engine_request_id, "引擎（目标插件回传）")
    };
    let (route, route_source) = if engine_route.is_empty() {
        (route_policy.to_string(), "调用方请求的路由策略")
    } else {
        (engine_route, "引擎（目标插件回传）")
    };
    let envelope = Json::obj(vec![("ok", Json::Bool(true)), ("result", result)]);
    Json::obj(vec![
        ("response", Json::str(&envelope.dump())),
        ("response_ok", Json::str("ok")),
        ("target_runtime", Json::str(&observed_runtime(ctx, target, route_policy, &envelope))),
        ("request_id", Json::str(&request_id)),
        ("request_id_source", Json::str(request_source)),
        ("trace_id", Json::str(&trace_id)),
        ("trace_id_source", Json::str(trace_source)),
        ("route", Json::str(&route)),
        ("route_source", Json::str(route_source))])
}

/// 调用页的全部模板变量（名字与引擎侧断言一致：response_ok / target_runtime / trace_id …）。
fn communication_vars(plugin_id: &str) -> BTreeMap<String, Json> {
    let mut vars: BTreeMap<String, Json> = BTreeMap::new();
    let defaults = vec![
        ("plugin_name", plugin_id),
        ("plugin_id", plugin_id),
        ("plugin_status", "running"),
        ("plugin_runtime", RUNTIME),
        ("plugin_sdk_version", SDK_VERSION),
        ("target", ""),
        ("method", "echo"),
        ("request", DEFAULT_REQUEST),
        ("route_policy", "auto"),
        ("response", ""),
        ("response_ok", ""),
        ("error", ""),
        ("error_code", ""),
        ("target_runtime", ""),
        ("request_id", ""),
        ("request_id_source", ""),
        ("trace_id", ""),
        ("trace_id_source", ""),
        ("route", ""),
        ("route_source", ""),
        ("message", ""),
    ];
    for (key, value) in defaults {
        vars.insert(key.to_string(), Json::str(value));
    }
    vars
}

/// 取 vars 里的字符串字段。
fn var_str(vars: &BTreeMap<String, Json>, key: &str) -> String {
    vars.get(key).and_then(|value| value.as_str()).unwrap_or("").to_string()
}

/// 把表单变成一次真调用 + 一页可渲染的变量（任何分支都必须渲染得出来）。
fn apply_call(ctx: &Context, form: &Json, plugin_id: &str) -> BTreeMap<String, Json> {
    let target = json_str_of(form, "target").trim().to_string();
    let mut method = json_str_of(form, "method").trim().to_string();
    if method.is_empty() {
        method = "ping".to_string();
    }
    let mut request_text = json_str_of(form, "request");
    if request_text.is_empty() {
        request_text = json_str_of(form, "params");
    }
    if request_text.is_empty() {
        request_text = DEFAULT_REQUEST.to_string();
    }
    let mut route_policy = json_str_of(form, "route").trim().to_string();
    if route_policy.is_empty() {
        route_policy = "auto".to_string();
    }
    let mut vars = communication_vars(plugin_id);
    vars.insert("target".to_string(), Json::str(&target));
    vars.insert("method".to_string(), Json::str(&method));
    vars.insert("request".to_string(), Json::str(&request_text));
    vars.insert("route_policy".to_string(), Json::str(&route_policy));
    if target.is_empty() {
        vars.insert("response_ok".to_string(), Json::str("error"));
        vars.insert("error_code".to_string(), Json::str("INVALID_ARGUMENT"));
        vars.insert("error".to_string(), Json::str("INVALID_ARGUMENT: 请填写目标插件 id"));
    } else if let Json::Obj(map) = call_target(ctx, &target, &method, &request_text, &route_policy) {
        for (key, value) in map.into_iter() {
            vars.insert(key, value);
        }
    }
    let message = if var_str(&vars, "response_ok") == "ok" {
        "Status: OK · 调用完成".to_string()
    } else {
        let code = var_str(&vars, "error_code");
        let code = if code.is_empty() { "PLUGIN_ERROR".to_string() } else { code };
        format!("Status: Failed · Code: {}", code)
    };
    vars.insert("message".to_string(), Json::str(&message));
    vars
}

/// 下拉选项（零 JS：select_option 交互依赖它）。
fn option_tags(values: &[&str], current: &str) -> String {
    let mut html = String::new();
    for value in values {
        let selected = if *value == current { " selected" } else { "" };
        html.push_str(&format!("<option value=\"{}\"{}>{}</option>",
                               escape_html(value), selected, escape_html(value)));
    }
    if !current.is_empty() && !values.contains(&current) {
        // 自定义方法名也要能原样回填提交
        html.push_str(&format!("<option value=\"{}\" selected>{}</option>",
                               escape_html(current), escape_html(current)));
    }
    html
}

/// 调用页 HTML（零 JS）：表单 + 结果区；元素 id 见 tests/e2e/README.md §3。
fn communication_html(vars: &BTreeMap<String, Json>) -> String {
    let base = format!("/panel/plugins/webui/{}", escape_html(&var_str(vars, "plugin_id")));
    let runtime_raw = var_str(vars, "target_runtime");
    let runtime = if runtime_raw.is_empty() { UNRETURNED.to_string() } else { runtime_raw };
    let mut html = String::new();
    html.push_str(&format!("<link rel=\"stylesheet\" href=\"{}/static/style.css\">", base));
    html.push_str(&format!("<h1 id=\"plugin-name\">{}</h1>",
                           escape_html(&var_str(vars, "plugin_name"))));
    html.push_str(&format!("<p id=\"plugin-status\" class=\"status\">状态：{}</p>",
                           escape_html(&var_str(vars, "plugin_status"))));
    html.push_str("<section id=\"communication-panel\" class=\"card\">");
    html.push_str(&format!("<h2>跨插件调用（Browser → {} 插件 → Core Router → 目标插件 → 回本页）</h2>",
                           escape_html(LANGUAGE_NAME)));
    html.push_str(&format!("<form id=\"communication-form\" method=\"post\" action=\"{}/communication\">", base));
    html.push_str("<label for=\"communication-target\">目标插件（target plugin）</label>");
    html.push_str(&format!("<input type=\"text\" id=\"communication-target\" name=\"target\" value=\"{}\" placeholder=\"minimal_go\">",
                           escape_html(&var_str(vars, "target"))));
    html.push_str("<label for=\"communication-method\">方法（method）</label>");
    html.push_str(&format!("<select id=\"communication-method\" name=\"method\">{}</select>",
                           option_tags(&COMM_METHODS, &var_str(vars, "method"))));
    html.push_str("<label for=\"communication-route\">路由策略（route）</label>");
    html.push_str(&format!("<select id=\"communication-route\" name=\"route\">{}</select>",
                           option_tags(&COMM_ROUTES, &var_str(vars, "route_policy"))));
    html.push_str("<label for=\"communication-request\">请求参数（request，JSON 对象）</label>");
    html.push_str(&format!("<textarea id=\"communication-request\" name=\"request\" rows=\"3\">{}</textarea>",
                           escape_html(&var_str(vars, "request"))));
    html.push_str("<button type=\"submit\" id=\"communication-submit\" name=\"plugin_action\" value=\"call\">调用</button>");
    html.push_str("</form>");
    html.push_str("<table id=\"communication-result\">");
    html.push_str(&format!("<tr><th>target plugin</th><td id=\"communication-target-out\">{}</td></tr>",
                           escape_html(&var_str(vars, "target"))));
    html.push_str(&format!("<tr><th>method</th><td id=\"communication-method-out\">{}</td></tr>",
                           escape_html(&var_str(vars, "method"))));
    html.push_str(&format!("<tr><th>request</th><td><pre id=\"communication-request-out\">{}</pre></td></tr>",
                           escape_html(&var_str(vars, "request"))));
    html.push_str(&format!("<tr><th>response</th><td><pre id=\"communication-response\">{}</pre></td></tr>",
                           escape_html(&var_str(vars, "response"))));
    html.push_str(&format!("<tr><th>request_id</th><td id=\"communication-request-id\">{} <small id=\"communication-request-id-source\">{}</small></td></tr>",
                           escape_html(&var_str(vars, "request_id")),
                           escape_html(&var_str(vars, "request_id_source"))));
    html.push_str(&format!("<tr><th>trace_id</th><td id=\"communication-trace-id\">{} <small id=\"communication-trace-id-source\">{}</small></td></tr>",
                           escape_html(&var_str(vars, "trace_id")),
                           escape_html(&var_str(vars, "trace_id_source"))));
    html.push_str(&format!("<tr><th>route</th><td id=\"communication-route-out\">{} <small id=\"communication-route-source\">{}</small></td></tr>",
                           escape_html(&var_str(vars, "route")),
                           escape_html(&var_str(vars, "route_source"))));
    html.push_str(&format!("<tr><th>目标运行时（观察值）</th><td id=\"communication-target-runtime\">{}</td></tr>",
                           escape_html(&runtime)));
    html.push_str(&format!("<tr><th>结果</th><td id=\"communication-response-ok\">{}</td></tr>",
                           escape_html(&var_str(vars, "response_ok"))));
    html.push_str(&format!("<tr><th>错误</th><td id=\"communication-error\">{}</td></tr>",
                           escape_html(&var_str(vars, "error"))));
    html.push_str("</table>");
    html.push_str(&format!("<p id=\"communication-message\">{}</p>",
                           escape_html(&var_str(vars, "message"))));
    html.push_str("</section>");
    html.push_str(&format!("<nav id=\"plugin-nav\"><a id=\"nav-index\" href=\"{}/index\">Index</a>", base));
    html.push_str(&format!("<a id=\"nav-communication\" href=\"{}/communication\">Communication</a></nav>", base));
    html
}

/// 空参数（协议要求 params 是对象）。
fn no_params() -> Json {
    Json::obj(vec![])
}

fn ping_payload(ctx: &Context) -> Json {
    Json::obj(vec![
        ("ok", Json::Bool(true)),
        ("plugin", Json::str(&label(ctx))),
        ("runtime", Json::str(RUNTIME)),
    ])
}

fn info_payload(ctx: &Context) -> Json {
    Json::obj(vec![
        ("plugin_id", Json::str(&plugin_id(ctx))),
        ("runtime", Json::str(RUNTIME)),
        ("sdk_version", Json::str(SDK_VERSION)),
        ("protocol_version", Json::str(PROTOCOL_VERSION)),
    ])
}

/// echo：原样返回请求里的 params（缺失 / null -> 空对象）。
fn echo_payload(request: &Json) -> Json {
    match request.get("params") {
        Some(Json::Null) | None => no_params(),
        Some(value) => value.clone(),
    }
}

/// 结构化失败回包（§八/§九）：错误不退化成一句字符串。
fn error_body(err: &PluginCommError) -> Json {
    Json::obj(vec![
        ("ok", Json::Bool(false)),
        ("code", Json::str(&err.code)),
        ("message", Json::str(&err.message)),
    ])
}

/// 命令层的失败（空命令 / 未知命令 / JSON 解析失败）——与 Python 最小插件同码。
fn command_error(message: &str) -> PluginCommError {
    PluginCommError::new("PLUGIN_ERROR", message, Json::obj(vec![]))
}

// ==================== 暴露的方法（§三） ====================

fn expose_ping(ctx: &Context, _request: &Json) -> Result<Json, PluginCommError> {
    Ok(ping_payload(ctx))
}

fn expose_get_info(ctx: &Context, _request: &Json) -> Result<Json, PluginCommError> {
    Ok(info_payload(ctx))
}

fn expose_echo(_ctx: &Context, request: &Json) -> Result<Json, PluginCommError> {
    Ok(echo_payload(request))
}

/// TIMEOUT 探针：睡 1500ms（调用方用 200ms 超时打它）。
fn expose_slow(_ctx: &Context, _request: &Json) -> Result<Json, PluginCommError> {
    thread::sleep(Duration::from_millis(SLOW_MS));
    Ok(Json::obj(vec![("slept", Json::Bool(true))]))
}

/// PLUGIN_ERROR 探针：panic —— SDK 的 catch_unwind 把它变成结构化 PLUGIN_ERROR（不杀进程）。
fn expose_boom(_ctx: &Context, _request: &Json) -> Result<Json, PluginCommError> {
    panic!("minimal rust plugin boom")
}

/// 收到过的 test.event payload + 对应的日志行。
fn expose_seen(_ctx: &Context, _request: &Json) -> Result<Json, PluginCommError> {
    Ok(seen_payload())
}

fn seen_payload() -> Json {
    let state = seen_lock();
    let events = state.events.clone();
    let logs: Vec<Json> = state.logs.iter().map(|line| Json::str(line.as_str())).collect();
    Json::obj(vec![("events", Json::Arr(events)), ("logs", Json::Arr(logs))])
}

// ==================== 事件（§四） ====================

fn handle_test_event(ctx: &Context, event: &Json) -> Option<Json> {
    let payload = event_payload(event);
    let line = format!("[test.event] {}", message_text(&payload));
    ctx.log(&line); // SDK 日志（stderr）；引擎日志拿不到也不影响验收
    let mut state = seen_lock();
    state.events.push(payload);
    state.logs.push(line);
    None
}

/// SDK 把事件 payload **平铺**进事件对象，并额外塞了 event / plugin_id 两个键；
/// 取回原始 payload：引擎若已把 payload 嵌进来就原样用，否则去掉那两个键后的其余字段。
fn event_payload(event: &Json) -> Json {
    if let Some(inner) = event.get("payload") {
        if let Json::Obj(_) = inner {
            return inner.clone();
        }
    }
    match event {
        Json::Obj(map) => {
            let mut pairs: Vec<(&str, Json)> = Vec::new();
            for (key, value) in map.iter() {
                if key == "event" || key == "plugin_id" {
                    continue;
                }
                pairs.push((key.as_str(), value.clone()));
            }
            Json::obj(pairs)
        }
        _ => no_params(),
    }
}

/// payload.message 的文本形态（缺省空串；不是字符串时用它的 JSON 文本）。
fn message_text(payload: &Json) -> String {
    match payload.get("message") {
        Some(Json::Str(text)) => text.clone(),
        Some(Json::Null) | None => String::new(),
        Some(other) => other.dump(),
    }
}

// ==================== 消息命令（§六） ====================

/// message 事件：只有发给自己的 /sdk@<自己> <命令> 才执行，结果以动作回给引擎。
fn handle_message(ctx: &Context, event: &Json) -> Option<Json> {
    let text = event.get("text").and_then(|value| value.as_str()).unwrap_or("");
    let command = command_for(text, &plugin_id(ctx))?;
    let message = match run_command(ctx, &command) {
        Ok(result) => result.dump(),
        Err(err) => error_body(&err).dump(),
    };
    let group_id = event.get("group_id").cloned().unwrap_or(Json::Null);
    Some(Json::obj(vec![
        ("type", Json::str("send_message")),
        ("payload", Json::obj(vec![
            ("group_id", group_id),
            ("message", Json::str(&message)),
        ])),
    ]))
}

/// 解析命令文本：/sdk@<executor_id> <命令> 只在自己就是 executor 时才返回命令，
/// 否则返回 None（不回任何动作 —— 事件是广播的，不寻址会多插件同时回包）。
/// 兼容老形式 /sdk <命令>（不寻址）。
fn command_for(text: &str, self_id: &str) -> Option<String> {
    if let Some(rest) = text.strip_prefix("/sdk@") {
        let (target, rest) = split_token(rest);
        if target != self_id {
            return None;
        }
        return Some(rest.trim().to_string());
    }
    text.strip_prefix("/sdk ").map(|rest| rest.trim().to_string())
}

/// 取第一个空白分隔的 token，返回 (token, 余下部分)。
fn split_token(text: &str) -> (&str, &str) {
    let trimmed = text.trim_start();
    match trimmed.find(|ch: char| ch.is_whitespace()) {
        Some(index) => (&trimmed[..index], &trimmed[index..]),
        None => (trimmed, ""),
    }
}

/// 解析命令里的 JSON 参数：空 -> 空对象；非法 -> 结构化失败（不 panic）。
fn parse_json_arg(text: &str) -> Result<Json, PluginCommError> {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return Ok(no_params());
    }
    match flowerie::parse_json(trimmed) {
        Ok(value) => Ok(value),
        Err(err) => Err(command_error(&format!("JSON 解析失败: {}", err))),
    }
}

/// 执行一条命令（命令名之后的 <target> 才是被调用的插件；§六 的命令表）。
fn run_command(ctx: &Context, command: &str) -> Result<Json, PluginCommError> {
    let (head, rest) = split_token(command);
    match head {
        "" => Err(command_error("空命令")),
        "ping" => {
            let (target, _) = split_token(rest);
            ctx.call(target, "ping", &no_params(), CallOptions::default())
        }
        "info" => Ok(info_payload(ctx)),
        "echo" => parse_json_arg(rest),
        "seen" => {
            let (target, _) = split_token(rest);
            ctx.call(target, "seen", &no_params(), CallOptions::default())
        }
        "call" => {
            let (target, rest) = split_token(rest);
            let (method, rest) = split_token(rest);
            let params = parse_json_arg(rest)?;
            ctx.call(target, method, &params, CallOptions::default())
        }
        "route" => {
            let (route, rest) = split_token(rest);
            let (target, rest) = split_token(rest);
            let (method, _) = split_token(rest);
            ctx.call(target, method, &no_params(), CallOptions::default().with_route(route))
        }
        "chain" => {
            let (first, rest) = split_token(rest);
            let (second, rest) = split_token(rest);
            let (third, _) = split_token(rest);
            let t1 = ctx.call(first, "ping", &no_params(), CallOptions::default())?;
            let echo_params = Json::obj(vec![("hello", Json::str("world"))]);
            let t2 = ctx.call(second, "echo", &echo_params, CallOptions::default())?;
            let t3 = ctx.call(third, "ping", &no_params(), CallOptions::default())?;
            Ok(Json::obj(vec![("t1", t1), ("t2", t2), ("t3", t3)]))
        }
        "errors" => {
            let (granted, rest) = split_token(rest);
            let (denied, _) = split_token(rest);
            Ok(probe_errors(ctx, granted, denied))
        }
        other => Err(command_error(&format!("未知命令: {}", other))),
    }
}

// ==================== 六种错误探针（§九） ====================

/// 依次触发六种错误，每种都返回**本语言原生错误模型**的观察结果。
fn probe_errors(ctx: &Context, granted: &str, denied: &str) -> Json {
    let method_not_found = probe_once(|| {
        ctx.call(granted, "no_such_method", &no_params(), CallOptions::default())
    });
    let plugin_not_found = probe_once(|| {
        ctx.call("no_such_plugin", "ping", &no_params(), CallOptions::default())
    });
    let permission_denied = probe_once(|| {
        ctx.call(denied, "ping", &no_params(), CallOptions::default())
    });
    let invalid_argument = probe_once(|| {
        ctx.call("", "ping", &no_params(), CallOptions::default())
    });
    let timeout = probe_once(|| {
        ctx.call(granted, "slow", &no_params(),
                 CallOptions::default().with_timeout(PROBE_TIMEOUT_MS))
    });
    let plugin_error = probe_once(|| {
        ctx.call(granted, "boom", &no_params(), CallOptions::default())
    });
    Json::obj(vec![
        ("METHOD_NOT_FOUND", method_not_found),
        ("PLUGIN_NOT_FOUND", plugin_not_found),
        ("PERMISSION_DENIED", permission_denied),
        ("INVALID_ARGUMENT", invalid_argument),
        ("TIMEOUT", timeout),
        ("PLUGIN_ERROR", plugin_error),
    ])
}

/// 单次探针：成功 = NO_ERROR（说明探针没造出错误）；失败 = PluginCommError 的 code/message。
///
/// Rust 的原生错误模型就是 Result::Err(PluginCommError)（SDK 不抛异常），
/// 所以 native 恒为类型名 PluginCommError。
fn probe_once<F>(probe: F) -> Json
where
    F: FnOnce() -> Result<Json, PluginCommError>,
{
    match probe() {
        Ok(_) => Json::obj(vec![
            ("native", Json::Null),
            ("code", Json::str("NO_ERROR")),
            ("message", Json::str("预期失败但调用成功了")),
        ]),
        Err(err) => Json::obj(vec![
            ("native", Json::str("PluginCommError")),
            ("code", Json::str(&err.code)),
            ("message", Json::str(&err.message)),
        ]),
    }
}
