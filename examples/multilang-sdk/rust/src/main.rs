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

use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use flowerie::{CallOptions, Context, Json, Plugin, PluginCommError, PROTOCOL_VERSION};

/// SDK 版本（SDK 本身没导出这个常量；与其它四种语言的最小插件取同一个值）。
const SDK_VERSION: &str = "1.0.0";
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
