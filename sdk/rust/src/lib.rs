
//! Flowerie Plugin Protocol v1 的 Rust SDK（**零 crate 依赖**，只用 std）。
//!
//! 协议规范：docs/plugin-protocol.md。与其它语言示例的行为一致性由
//! `tests/test_plugin_sdk_contract.py` 用真进程 + 真管道比对（同一批向量）。
//!
//! Plugin-to-Plugin 通信（plugin.call / plugin.emit / plugin.on / plugin.expose /
//! plugin.cancel）见 docs/plugin-communication.md：语义与其它四种语言完全一致，
//! 唯一出口是引擎的反向 op —— SDK 里没有任何绕过 Core 的直连通道。

use std::cell::RefCell;
use std::collections::HashMap;
use std::fs;
use std::io::{self, BufRead, Write};
use std::path::{Path, PathBuf};
use std::rc::Rc;

pub mod json;

pub use json::{parse as parse_json, Json};

/// 协议版本。
pub const PROTOCOL_VERSION: &str = "1";
/// 插件 → 引擎 请求 id 偏移（与引擎请求 id 不共用命名空间）。
pub const ACTION_ID_BASE: u64 = 1_000_000;

const API_VERSION: &str = "1";
const MAX_STORAGE_KEYS: usize = 200;
const MAX_STORAGE_VALUE: usize = 64 * 1024;
const MAX_CONFIG_KEYS: usize = 64;
const MAX_CONFIG_VALUE: usize = 8 * 1024;
const OPTIONAL_METHODS: [&str; 14] = [
    "config.get", "config.set", "context.get", "permission.check",
    "plugin.call", "plugin.cancel", "plugin.event",
    "storage.delete", "storage.get", "storage.list", "storage.set",
    "webui.action", "webui.asset", "webui.page",
];
const MAX_COMM_NAME: usize = 96;
const MAX_INBOUND_DEPTH: usize = 16;
const MAX_CANCELLED_REQUESTS: usize = 256;
const MAX_DEFERRED_MESSAGES: usize = 64;

/// 结构化错误码（§二十一 十个 + §十七 生命周期 + §二十二 循环），与 Core 的 comm.ERROR_CODES 同源。
pub const ERROR_CODES: [&str; 12] = [
    "PLUGIN_NOT_FOUND", "PLUGIN_NOT_READY", "METHOD_NOT_FOUND", "PERMISSION_DENIED",
    "INVALID_ARGUMENT", "TIMEOUT", "CANCELLED", "SERIALIZATION_ERROR", "PLUGIN_ERROR",
    "INTERNAL_ERROR", "PLUGIN_UNAVAILABLE", "PLUGIN_CALL_LOOP",
];

/// 插件间通信的三条入站方法（§十）：CALL / EVENT / CANCEL 不混成一种机制。
pub const PLUGIN_METHODS: [&str; 3] = ["plugin.call", "plugin.event", "plugin.cancel"];

/// 路由策略（§十三）：默认 auto；测试用 core 验证统一协议路径。
pub const ROUTE_POLICIES: [&str; 3] = ["auto", "core", "local"];

/// 调用链最大跳数（§二十二）：判定在 Core（SDK 只负责直传 hop_count，不自己 +1）。
pub const MAX_HOP_COUNT: i64 = 8;

/// 默认调用超时（毫秒）。
pub const DEFAULT_TIMEOUT_MS: i64 = 5000;

/// 插件返回给引擎的动作（唯一副作用出口）。
pub type Action = Json;

#[derive(Default)]
struct Io {
    next_id: u64,
}

type Shared = Rc<RefCell<Io>>;
type StartupFn = Box<dyn Fn(&Context)>;
type MessageFn = Box<dyn Fn(&Context, &Json) -> Option<Json>>;
type HookFn = Box<dyn Fn(&Context, &[Json]) -> Json>;
type WebuiFn = Box<dyn Fn(&Context, &Json) -> Json>;

/// 传给插件的上下文：storage / config / permission / action。
pub struct Context {
    pub plugin_id: String,
    pub plugin_dir: PathBuf,
    pub data_dir: PathBuf,
    shared: Shared,
    /// 插件间通信的注册表与链路状态（与 Plugin 共享同一份）。
    comm: CommShared,
}

fn valid_key(key: &str) -> bool {
    if key.is_empty() || key.len() > 64 {
        return false;
    }
    for (i, ch) in key.chars().enumerate() {
        let alnum = ch.is_ascii_alphanumeric();
        if i == 0 && !alnum {
            return false;
        }
        if !alnum && ch != '.' && ch != '_' && ch != '-' {
            return false;
        }
    }
    true
}

impl Context {
    /// 写 stderr（协议规定 stdout 只能放协议 JSON）。
    pub fn log(&self, message: &str) {
        let _ = writeln!(io::stderr(), "[flowerie] {}", message);
    }

    fn storage_dir(&self) -> Result<PathBuf, String> {
        let dir = self.data_dir.join("storage");
        fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
        Ok(dir)
    }

    fn storage_path(&self, key: &str) -> Result<PathBuf, String> {
        if !valid_key(key) {
            return Err("存储键非法（字母数字开头 ≤64，允许 . _ -）".to_string());
        }
        Ok(self.storage_dir()?.join(format!("{}.json", key)))
    }

    /// 读取一个键；不存在返回 None。
    pub fn storage_get(&self, key: &str) -> Result<Option<Json>, String> {
        let path = self.storage_path(key)?;
        match fs::read_to_string(&path) {
            Ok(text) => Ok(Some(parse_json(&text)?)),
            Err(_) => Ok(None),
        }
    }

    /// 写入一个键（有大小与数量上限）。
    pub fn storage_set(&self, key: &str, value: &Json) -> Result<usize, String> {
        let path = self.storage_path(key)?;
        let text = value.dump();
        if text.len() > MAX_STORAGE_VALUE {
            return Err("值超过上限".to_string());
        }
        let dir = self.storage_dir()?;
        let count = fs::read_dir(&dir)
            .map(|rd| rd.filter_map(|e| e.ok())
                .filter(|e| e.file_name().to_string_lossy().ends_with(".json")).count())
            .unwrap_or(0);
        if !path.exists() && count >= MAX_STORAGE_KEYS {
            return Err("存储键数量超过上限".to_string());
        }
        fs::write(&path, text.as_bytes()).map_err(|e| e.to_string())?;
        Ok(text.len())
    }

    /// 删除一个键；返回是否真的删掉了。
    pub fn storage_delete(&self, key: &str) -> Result<bool, String> {
        let path = self.storage_path(key)?;
        Ok(fs::remove_file(path).is_ok())
    }

    /// 列出键（可按前缀过滤）。
    pub fn storage_list(&self, prefix: &str) -> Result<Vec<String>, String> {
        let dir = self.storage_dir()?;
        let mut keys: Vec<String> = fs::read_dir(&dir)
            .map_err(|e| e.to_string())?
            .filter_map(|e| e.ok())
            .filter_map(|e| {
                let name = e.file_name().to_string_lossy().to_string();
                name.strip_suffix(".json").map(|k| k.to_string())
            })
            .filter(|k| k.starts_with(prefix))
            .collect();
        keys.sort();
        Ok(keys)
    }

    fn config_path(&self) -> PathBuf {
        self.data_dir.join("config.json")
    }

    fn config_overlay(&self) -> Json {
        match fs::read_to_string(self.config_path()) {
            Ok(text) => parse_json(&text).unwrap_or(Json::Obj(Default::default())),
            Err(_) => Json::Obj(Default::default()),
        }
    }

    /// 操作员配置（引擎） + 插件覆盖层，操作员的值优先。
    pub fn config_get(&self) -> Result<Json, String> {
        let res = self.engine_op("config.get", &Json::obj(vec![]))?;
        let mut merged = self.config_overlay();
        if let (Json::Obj(base), Some(Json::Obj(operator))) = (&mut merged, res.get("values")) {
            for (k, v) in operator.iter() {
                base.insert(k.clone(), v.clone());
            }
        }
        Ok(merged)
    }

    /// 写入插件自己的覆盖层（改不了操作员的全局配置）。
    pub fn config_set(&self, values: &Json) -> Result<Vec<String>, String> {
        let pairs = match values {
            Json::Obj(map) => map.clone(),
            _ => return Err("config.set 需要对象".to_string()),
        };
        let mut overlay = match self.config_overlay() {
            Json::Obj(map) => map,
            _ => Default::default(),
        };
        let mut saved = Vec::new();
        for (k, v) in pairs.iter() {
            if !valid_key(k) {
                return Err(format!("配置键非法: {}", k));
            }
            if v.dump().len() > MAX_CONFIG_VALUE {
                return Err(format!("配置值超过上限: {}", k));
            }
            overlay.insert(k.clone(), v.clone());
            saved.push(k.clone());
        }
        if overlay.len() > MAX_CONFIG_KEYS {
            return Err("配置键数量超过上限".to_string());
        }
        fs::write(self.config_path(), Json::Obj(overlay).dump().as_bytes()).map_err(|e| e.to_string())?;
        saved.sort();
        Ok(saved)
    }

    /// 查询管理员是否批准了某个权限（只读，无法提权）。
    pub fn permission_check(&self, permission: &str) -> Result<bool, String> {
        let res = self.engine_op("permission.check",
                                 &Json::obj(vec![("permission", Json::str(permission))]))?;
        Ok(res.get("granted").and_then(|v| v.as_bool()).unwrap_or(false))
    }

    /// 拉取引擎侧上下文（插件名 / 版本 / 已批准权限）。
    pub fn info(&self) -> Result<Json, String> {
        let res = self.engine_op("context.get", &Json::obj(vec![]))?;
        Ok(res.get("result").cloned().unwrap_or(res))
    }

    /// 发起动作（副作用出口；引擎侧过 PermissionManager）。
    pub fn action(&self, action_type: &str, params: &Json) -> Result<Json, String> {
        self.reverse("action", &Json::obj(vec![
            ("action", Json::str(action_type)), ("payload", params.clone())]))
    }

    fn engine_op(&self, op: &str, args: &Json) -> Result<Json, String> {
        self.reverse("engine", &Json::obj(vec![
            ("op", Json::str(op)), ("args", args.clone())]))
    }

    fn reverse(&self, method: &str, params: &Json) -> Result<Json, String> {
        let id = {
            let mut io_state = self.shared.borrow_mut();
            io_state.next_id += 1;
            ACTION_ID_BASE + io_state.next_id
        };
        let frame = Json::obj(vec![
            ("id", Json::num(id as i64)),
            ("method", Json::str(method)),
            ("params", params.clone()),
        ]);
        write_line(&frame)?;
        let stdin = io::stdin();
        loop {
            let mut line = String::new();
            let read = stdin.lock().read_line(&mut line).map_err(|e| e.to_string())?;
            if read == 0 {
                return Err("connection closed".to_string());
            }
            let msg = match parse_json(line.trim()) {
                Ok(value) => value,
                Err(_) => continue,
            };
            let msg_id = msg.get("id").and_then(|v| v.as_f64()).map(|n| n as u64);
            if msg_id != Some(id) {
                // 不是我在等的那条：可能是引擎投递进来的 plugin.call / plugin.event /
                // plugin.cancel —— 必须原地处理，不能丢（§二十二；否则 A -> B -> A 的回调
                // 永远到不了，环保护也就没有真实链路可观察）。
                self.pump_nested(&msg)?;
                continue;
            }
            if let Some(err) = msg.get("error").and_then(|v| v.as_str()) {
                return Err(err.to_string());
            }
            return Ok(msg.get("result").cloned().unwrap_or(Json::Null));
        }
    }
}

fn write_line(value: &Json) -> Result<(), String> {
    let mut out = io::stdout();
    writeln!(out, "{}", value.dump()).map_err(|e| e.to_string())?;
    out.flush().map_err(|e| e.to_string())
}

/// 插件主体：注册钩子后 `run()` 进入协议主循环。
pub struct Plugin {
    capabilities: Vec<&'static str>,
    startup: Vec<StartupFn>,
    shutdown: Vec<StartupFn>,
    message: Vec<MessageFn>,
    health: Vec<Box<dyn Fn(&Context) -> bool>>,
    events: HashMap<String, Vec<MessageFn>>,
    hooks: HashMap<String, HookFn>,
    webui_handlers: HashMap<String, WebuiFn>,
    shared: Shared,
    ctx: Context,
}

impl Default for Plugin {
    fn default() -> Self {
        Self::new()
    }
}

/// Plugin WebUI Protocol 注册器（任务书第 3 份 §六）：
///
/// ```ignore
/// plugin.webui().page(|_ctx, _args| Json::str("<h1>hi</h1>")).action(|_ctx, _args| Json::Null);
/// ```
///
/// 处理器拿到引擎给的受控参数（page/context，action 时还有 action/form），
/// 返回 `Json::Str`（= html 简写）或 `Json::Obj`（白名单字段）。
/// 路由、权限、校验、净化、隔离全部由引擎负责，插件只负责内容。
pub struct Webui<'a> {
    plugin: &'a mut Plugin,
}

impl<'a> Webui<'a> {
    fn register<F: Fn(&Context, &Json) -> Json + 'static>(self, method: &str, f: F) -> Self {
        self.plugin.webui_handlers.insert(method.to_string(), Box::new(f));
        self
    }

    /// 页面处理器（webui.page）。
    pub fn page<F: Fn(&Context, &Json) -> Json + 'static>(self, f: F) -> Self {
        self.register("webui.page", f)
    }

    /// 动作处理器（webui.action）。
    pub fn action<F: Fn(&Context, &Json) -> Json + 'static>(self, f: F) -> Self {
        self.register("webui.action", f)
    }

    /// 资源处理器（webui.asset）。
    pub fn asset<F: Fn(&Context, &Json) -> Json + 'static>(self, f: F) -> Self {
        self.register("webui.asset", f)
    }
}

impl Plugin {
    /// 创建插件（默认声明全部可选能力）。
    pub fn new() -> Self {
        let shared: Shared = Rc::new(RefCell::new(Io::default()));
        let dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        let data = dir.join("data");
        Plugin {
            capabilities: OPTIONAL_METHODS.to_vec(),
            startup: Vec::new(),
            shutdown: Vec::new(),
            message: Vec::new(),
            health: Vec::new(),
            events: HashMap::new(),
            hooks: HashMap::new(),
            webui_handlers: HashMap::new(),
            shared: shared.clone(),
            ctx: Context {
                plugin_id: "unknown".to_string(),
                plugin_dir: dir,
                data_dir: data,
                shared,
                comm: Rc::new(RefCell::new(CommState::default())),
            },
        }
    }

    /// 启动钩子（initialize 时调用）。
    pub fn on_startup<F: Fn(&Context) + 'static>(&mut self, f: F) -> &mut Self {
        self.startup.push(Box::new(f));
        self
    }

    /// 退出钩子。
    pub fn on_shutdown<F: Fn(&Context) + 'static>(&mut self, f: F) -> &mut Self {
        self.shutdown.push(Box::new(f));
        self
    }

    /// 消息钩子。
    pub fn on_message<F: Fn(&Context, &Json) -> Option<Json> + 'static>(&mut self, f: F) -> &mut Self {
        self.message.push(Box::new(f));
        self
    }

    /// 任意事件的钩子。
    pub fn on_event<F: Fn(&Context, &Json) -> Option<Json> + 'static>(&mut self, name: &str, f: F) -> &mut Self {
        self.events.entry(name.to_string()).or_default().push(Box::new(f));
        self
    }

    /// 心跳钩子（Python 侧对应 health_check）：返回 false 即视为不健康。
    pub fn on_health<F: Fn(&Context) -> bool + 'static>(&mut self, f: F) -> &mut Self {
        self.health.push(Box::new(f));
        self
    }

    /// 与 Python SDK 的具名钩子对齐（协议层就是 event 名字，on_event 是通用入口）。
    pub fn on_command<F: Fn(&Context, &Json) -> Option<Json> + 'static>(&mut self, f: F) -> &mut Self {
        self.on_event("command", f)
    }

    /// 通知事件。
    pub fn on_notice<F: Fn(&Context, &Json) -> Option<Json> + 'static>(&mut self, f: F) -> &mut Self {
        self.on_event("notice", f)
    }

    /// 请求事件。
    pub fn on_request<F: Fn(&Context, &Json) -> Option<Json> + 'static>(&mut self, f: F) -> &mut Self {
        self.on_event("request", f)
    }

    /// 生命周期事件。
    pub fn on_lifecycle<F: Fn(&Context, &Json) -> Option<Json> + 'static>(&mut self, f: F) -> &mut Self {
        self.on_event("lifecycle", f)
    }

    /// 定时事件。
    pub fn on_schedule<F: Fn(&Context, &Json) -> Option<Json> + 'static>(&mut self, f: F) -> &mut Self {
        self.on_event("schedule", f)
    }

    /// 控制面可调用的 hook（插件 WebUI 的数据钩子走同一通道）。
    pub fn register_hook<F: Fn(&Context, &[Json]) -> Json + 'static>(&mut self, name: &str, f: F) -> &mut Self {
        self.hooks.insert(name.to_string(), Box::new(f));
        self
    }

    /// WebUI 注册入口：`plugin.webui().page(|ctx, args| ...).action(...)`。
    pub fn webui(&mut self) -> Webui<'_> {
        Webui { plugin: self }
    }

    /// 上下文（测试/嵌入场景）。
    pub fn context(&self) -> &Context {
        &self.ctx
    }

    /// 进入协议主循环。
    pub fn run(&mut self) -> Result<(), String> {
        let stdin = io::stdin();
        loop {
            // 等待应答期间被推迟的引擎请求（hook / health / ...）：先按到达顺序补处理，
            // 再阻塞读下一行 —— 相对顺序不乱，引擎的请求也不会永远等不到应答。
            while let Some(pending) = self.ctx.take_deferred() {
                if self.handle_message(&pending)? {
                    return Ok(());
                }
            }
            let mut line = String::new();
            let read = stdin.lock().read_line(&mut line).map_err(|e| e.to_string())?;
            if read == 0 {
                return Ok(());
            }
            if line.trim().is_empty() {
                continue;
            }
            let msg = match parse_json(line.trim()) {
                Ok(value) => value,
                Err(_) => continue,
            };
            if self.handle_message(&msg)? {
                return Ok(());
            }
        }
    }

    /// 把一条协议消息（主循环读到的，或嵌套等待期间推迟下来的）交给 handle。
    fn handle_message(&mut self, msg: &Json) -> Result<bool, String> {
        let method = msg.get("method").and_then(|v| v.as_str()).unwrap_or("").to_string();
        if method.is_empty() {
            return Ok(false);
        }
        let id = msg.get("id").and_then(|v| v.as_f64()).unwrap_or(0.0) as i64;
        let params = msg.get("params").cloned().unwrap_or(Json::Null);
        self.handle(id, &method, &params)
    }

    fn reply(&self, id: i64, result: Json) -> Result<(), String> {
        write_line(&Json::obj(vec![
            ("id", Json::num(id)),
            ("result", result),
        ]))
    }

    fn reply_error(&self, id: i64, message: &str) -> Result<(), String> {
        let trimmed: String = message.chars().take(800).collect();
        write_line(&Json::obj(vec![
            ("id", Json::num(id)),
            ("error", Json::str(&trimmed)),
        ]))
    }

    fn handle(&mut self, id: i64, method: &str, params: &Json) -> Result<bool, String> {
        match method {
            "initialize" => {
                if let Some(ctx_in) = params.get("context") {
                    if let Some(dir) = ctx_in.get("plugin_dir").and_then(|v| v.as_str()) {
                        self.ctx.plugin_dir = PathBuf::from(dir);
                    }
                    if let Some(dir) = ctx_in.get("data_dir").and_then(|v| v.as_str()) {
                        self.ctx.data_dir = PathBuf::from(dir);
                    }
                    if let Some(pid) = ctx_in.get("plugin_id").and_then(|v| v.as_str()) {
                        self.ctx.plugin_id = pid.to_string();
                    }
                }
                for hook in self.startup.iter() {
                    hook(&self.ctx);
                }
                let caps: Vec<Json> = self.capabilities.iter().map(|m| Json::str(m)).collect();
                self.reply(id, Json::obj(vec![
                    ("ok", Json::Bool(true)),
                    ("api_version", Json::str(API_VERSION)),
                    ("protocol_version", Json::str(PROTOCOL_VERSION)),
                    ("capabilities", Json::Arr(caps)),
                ]))?;
            }
            "event" => {
                let name = params.get("event").and_then(|v| v.as_str()).unwrap_or("");
                let payload = params.get("payload").cloned().unwrap_or(Json::Null);
                let actions = self.dispatch(name, &payload);
                self.reply(id, Json::obj(vec![("actions", Json::Arr(actions))]))?;
            }
            "health" => {
                let mut healthy = true;
                for hook in self.health.iter() {
                    if !hook(&self.ctx) {
                        healthy = false;
                    }
                }
                if healthy {
                    self.reply(id, Json::obj(vec![("ok", Json::Bool(true))]))?;
                } else {
                    self.reply(id, Json::obj(vec![("ok", Json::Bool(false)),
                        ("error", Json::str("health check failed"))]))?;
                }
            }
            "shutdown" => {
                for hook in self.shutdown.iter() {
                    hook(&self.ctx);
                }
                self.reply(id, Json::obj(vec![("ok", Json::Bool(true))]))?;
                return Ok(true);
            }
            "hook" => {
                let name = params.get("name").and_then(|v| v.as_str()).unwrap_or("").to_string();
                if !valid_hook_name(&name) {
                    self.reply_error(id, "hook 名非法")?;
                    return Ok(false);
                }
                let args = params.get("args").and_then(|v| v.as_arr()).cloned().unwrap_or_default();
                let result = match self.hooks.get(&name) {
                    Some(hook) => hook(&self.ctx, &args),
                    None => Json::Null,
                };
                self.reply(id, Json::obj(vec![("ok", Json::Bool(true)), ("result", result)]))?;
            }
            "webui.page" | "webui.action" | "webui.asset" => {
                let payload = match self.webui_handlers.get(method) {
                    Some(handler) => normalize_webui(handler(&self.ctx, params)),
                    None => Json::obj(vec![
                        ("ok", Json::Bool(false)),
                        ("error", Json::str(&format!("插件未注册 {} 处理器", method))),
                    ]),
                };
                self.reply(id, payload)?;
            }
            "storage.get" => {
                let key = params.get("key").and_then(|v| v.as_str()).unwrap_or("");
                if !valid_key(key) {
                    self.reply(id, Json::obj(vec![("ok", Json::Bool(false)),
                        ("error", Json::str("存储键非法（字母数字开头 ≤64，允许 . _ -）"))]))?;
                    return Ok(false);
                }
                let value = self.ctx.storage_get(key).unwrap_or(None);
                self.reply(id, Json::obj(vec![("ok", Json::Bool(true)),
                    ("value", value.unwrap_or(Json::Null))]))?;
            }
            "storage.set" => {
                let key = params.get("key").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let value = params.get("value").cloned().unwrap_or(Json::Null);
                match self.ctx.storage_set(&key, &value) {
                    Ok(size) => self.reply(id, Json::obj(vec![("ok", Json::Bool(true)),
                        ("size", Json::num(size as i64))]))?,
                    Err(err) => self.reply(id, Json::obj(vec![("ok", Json::Bool(false)),
                        ("error", Json::str(&err))]))?,
                }
            }
            "storage.delete" => {
                let key = params.get("key").and_then(|v| v.as_str()).unwrap_or("");
                if !valid_key(key) {
                    self.reply(id, Json::obj(vec![("ok", Json::Bool(false)),
                        ("error", Json::str("存储键非法（字母数字开头 ≤64，允许 . _ -）"))]))?;
                    return Ok(false);
                }
                let deleted = self.ctx.storage_delete(key).unwrap_or(false);
                self.reply(id, Json::obj(vec![("ok", Json::Bool(true)),
                    ("deleted", Json::Bool(deleted))]))?;
            }
            "storage.list" => {
                let prefix = params.get("prefix").and_then(|v| v.as_str()).unwrap_or("");
                let keys: Vec<Json> = self.ctx.storage_list(prefix).unwrap_or_default()
                    .iter().map(|k| Json::str(k)).collect();
                self.reply(id, Json::obj(vec![("ok", Json::Bool(true)),
                    ("keys", Json::Arr(keys))]))?;
            }
            "config.get" => match self.ctx.config_get() {
                Ok(values) => self.reply(id, Json::obj(vec![("ok", Json::Bool(true)),
                    ("values", values)]))?,
                Err(err) => self.reply(id, Json::obj(vec![("ok", Json::Bool(false)),
                    ("error", Json::str(&err))]))?,
            },
            "config.set" => {
                let values = params.get("values").cloned().unwrap_or(Json::Null);
                match self.ctx.config_set(&values) {
                    Ok(saved) => {
                        let items: Vec<Json> = saved.iter().map(|k| Json::str(k)).collect();
                        self.reply(id, Json::obj(vec![("ok", Json::Bool(true)),
                            ("saved", Json::Arr(items))]))?;
                    }
                    Err(err) => self.reply(id, Json::obj(vec![("ok", Json::Bool(false)),
                        ("error", Json::str(&err))]))?,
                }
            }
            "permission.check" => {
                let permission = params.get("permission").and_then(|v| v.as_str()).unwrap_or("");
                match self.ctx.permission_check(permission) {
                    Ok(granted) => self.reply(id, Json::obj(vec![
                        ("ok", Json::Bool(true)),
                        ("permission", Json::str(permission)),
                        ("granted", Json::Bool(granted))]))?,
                    Err(err) => self.reply(id, Json::obj(vec![("ok", Json::Bool(false)),
                        ("error", Json::str(&err))]))?,
                }
            }
            "context.get" => match self.ctx.info() {
                Ok(info) => self.reply(id, Json::obj(vec![("ok", Json::Bool(true)),
                    ("result", info)]))?,
                Err(err) => self.reply(id, Json::obj(vec![("ok", Json::Bool(false)),
                    ("error", Json::str(&err))]))?,
            },
            // Plugin-to-Plugin 通信的入站方法（§五/§九/§十八）：与嵌套等待共用同一条路径
            "plugin.call" | "plugin.event" | "plugin.cancel" => {
                self.ctx.dispatch_plugin_method(id, method, params)?;
            }
            other => self.reply_error(id, &format!("未知方法: {:?}", other))?,
        }
        Ok(false)
    }

    fn dispatch(&self, event: &str, payload: &Json) -> Vec<Json> {
        let mut event_obj = match payload.clone() {
            Json::Obj(map) => map,
            _ => Default::default(),
        };
        event_obj.insert("event".to_string(), Json::str(event));
        event_obj.insert("plugin_id".to_string(), Json::str(&self.ctx.plugin_id));
        let event_json = Json::Obj(event_obj);
        let hooks = if event == "message" {
            Some(&self.message)
        } else {
            self.events.get(event)
        };
        let mut actions = Vec::new();
        if let Some(list) = hooks {
            for hook in list.iter() {
                if let Some(action) = hook(&self.ctx, &event_json) {
                    actions.push(action);
                }
            }
        }
        actions
    }
}

/// 把 WebUI 处理器返回值归一成协议应答（`Json::Str` = html 简写）。
fn normalize_webui(result: Json) -> Json {
    match result {
        Json::Str(html) => Json::obj(vec![("ok", Json::Bool(true)), ("html", Json::Str(html))]),
        Json::Obj(map) => {
            if matches!(map.get("ok"), Some(Json::Bool(false))) {
                let message = map.get("error").and_then(|v| v.as_str()).unwrap_or("插件返回 ok=false");
                return Json::obj(vec![("ok", Json::Bool(false)), ("error", Json::str(message))]);
            }
            let mut pairs: Vec<(&str, Json)> = vec![("ok", Json::Bool(true))];
            for key in ["html", "vars", "context", "message", "content_type", "body",
                        "base64", "config_set", "storage_set"] {
                if let Some(value) = map.get(key) {
                    pairs.push((key, value.clone()));
                }
            }
            Json::obj(pairs)
        }
        _ => Json::obj(vec![
            ("ok", Json::Bool(false)),
            ("error", Json::str("WebUI 处理器返回了非法类型")),
        ]),
    }
}

fn valid_hook_name(name: &str) -> bool {
    if name.is_empty() || name.len() > 64 {
        return false;
    }
    for (i, ch) in name.chars().enumerate() {
        let ok = ch.is_ascii_lowercase() || ch == '_' || (i > 0 && ch.is_ascii_digit());
        if !ok {
            return false;
        }
    }
    true
}

/// 便捷：把目录规范化成插件目录（嵌入场景用）。
pub fn plugin_dir_from(path: &Path) -> PathBuf {
    fs::canonicalize(path).unwrap_or_else(|_| path.to_path_buf())
}


// ==================== Plugin-to-Plugin 通信（任务书《通信》§五–§二十七） ====================
//
// 与其它四种语言 SDK 的语义完全一致（docs/plugin-communication.md §8）：
//   * 出站：plugin.call / plugin.emit / plugin.cancel —— 反向 op 交给引擎，经 Core Router 转发；
//     SDK 里没有任何直连通道（没有 socket / http），权限判定在 Core，SDK 跳不过去。
//   * 入站：plugin.call / plugin.event / plugin.cancel —— 引擎投递进来的三条方法（§十 不混用）。
//   * 嵌套：等待自己发起的调用响应期间，投递进来的入站消息**原地处理，绝不丢弃**（§二十二）。
//   * trace/hop：处理入站消息时记住 trace_id / hop_count，出站自动带上（引擎负责 hop+1）。
//   * 失败：一律映射成 PluginCommError（code / message / data），不退化成字符串；不自动重试。

/// 一次 plugin.call 的可选参数（Rust 用结构体代替其它语言的关键字参数）。
#[derive(Debug, Clone, PartialEq)]
pub struct CallOptions {
    /// 超时毫秒（默认 5000；引擎侧会夹到 [1, 60000]）。
    pub timeout: i64,
    /// 路由策略：auto | core | local（§十三）。
    pub route: String,
}

impl Default for CallOptions {
    fn default() -> Self {
        CallOptions { timeout: DEFAULT_TIMEOUT_MS, route: "auto".to_string() }
    }
}

impl CallOptions {
    pub fn new() -> Self {
        Self::default()
    }

    /// 设置超时（毫秒）。
    pub fn with_timeout(mut self, timeout_ms: i64) -> Self {
        self.timeout = timeout_ms;
        self
    }

    /// 设置路由策略（auto | core | local）。
    pub fn with_route(mut self, route: &str) -> Self {
        self.route = route.to_string();
        self
    }
}

/// plugin.emit 的结果（§九）：广播不是 RPC，没有 result，只有投递统计。
#[derive(Debug, Clone, PartialEq)]
pub struct EmitResult {
    /// 成功投递到的插件数。
    pub delivered: u64,
    /// 投递失败的插件清单（[{"plugin_id":…,"code":…}]）。
    pub failed: Vec<Json>,
    /// 本次广播的 trace_id（入站消息沿用，否则引擎生成）。
    pub trace_id: String,
}

/// plugin.cancel 的结果（§十八）。
#[derive(Debug, Clone, PartialEq)]
pub struct CancelResult {
    pub request_id: String,
    pub cancelled: bool,
    pub target: String,
}

/// 当前入站消息的链路上下文（§二十二/§二十三）：出站调用自动带上它。
#[derive(Debug, Clone, PartialEq)]
pub struct CommContext {
    pub trace_id: String,
    pub hop_count: i64,
    pub source: Json,
    pub request_id: String,
}

impl Default for CommContext {
    fn default() -> Self {
        CommContext {
            trace_id: String::new(),
            hop_count: 0,
            source: Json::Null,
            request_id: String::new(),
        }
    }
}

/// 插件间通信失败（§二十一）：Rust 侧的原生形态（Result::Err）。
///
/// 引擎返回的永远是响应模型（跨语言没有异常这个东西），SDK 负责把它转成本语言的 Result。
/// 未知错误码按 Core 的约定归一成 INTERNAL_ERROR —— 错误绝不退化成一句字符串。
#[derive(Debug, Clone, PartialEq)]
pub struct PluginCommError {
    pub code: String,
    pub message: String,
    pub data: Json,
}

impl PluginCommError {
    /// 构造：未知错误码归一成 INTERNAL_ERROR（与 Core 的 PluginCommError 一致）。
    pub fn new(code: &str, message: &str, data: Json) -> Self {
        let normalized = if is_error_code(code) { code } else { "INTERNAL_ERROR" };
        PluginCommError {
            code: normalized.to_string(),
            message: message.to_string(),
            data,
        }
    }

    /// 默认形态 PLUGIN_ERROR：handler 内部失败 / 传输层失败。
    pub fn plugin(message: &str) -> Self {
        Self::new("PLUGIN_ERROR", message, Json::obj(vec![]))
    }

    /// 目标插件没暴露这个方法（§五）：data 带 method 与 exposed 清单，方便对方定位。
    pub fn method_not_found(method: &str, exposed: &[String]) -> Self {
        let listed: Vec<Json> = exposed.iter().map(|name| Json::str(name)).collect();
        Self::new(
            "METHOD_NOT_FOUND",
            &format!("插件未暴露方法: {}", method),
            Json::obj(vec![("method", Json::str(method)), ("exposed", Json::Arr(listed))]),
        )
    }

    /// 从对方 / 引擎给的 error 字段（对象 / 字符串 / 缺失）还原结构化错误。
    pub fn from_error(error: &Json) -> Self {
        match error {
            Json::Obj(map) => {
                let code = map.get("code").and_then(|v| v.as_str()).unwrap_or("PLUGIN_ERROR");
                let message = map.get("message").and_then(|v| v.as_str()).unwrap_or(code);
                let data = map.get("data").cloned().unwrap_or_else(|| Json::obj(vec![]));
                Self::new(code, message, data)
            }
            Json::Str(text) => Self::new("PLUGIN_ERROR", text, Json::obj(vec![])),
            _ => Self::new("PLUGIN_ERROR", "插件调用失败", Json::obj(vec![])),
        }
    }

    /// 从响应模型（§七）取出 result；ok != true（含空响应）一律 Err。
    pub fn from_response(response: &Json) -> Result<Json, Self> {
        if response.get("ok").and_then(|v| v.as_bool()) == Some(true) {
            return Ok(response.get("result").cloned().unwrap_or(Json::Null));
        }
        let error = response.get("error").cloned().unwrap_or(Json::Null);
        Err(Self::from_error(&error))
    }

    /// 协议三件套 {"code":…,"message":…,"data":…}。
    pub fn to_error(&self) -> Json {
        Json::obj(vec![
            ("code", Json::str(&self.code)),
            ("message", Json::str(&self.message)),
            ("data", self.data.clone()),
        ])
    }

    /// 失败应答体（§七）：{"ok":false,"error":{code,message,data}}。
    pub fn to_body(&self) -> Json {
        Json::obj(vec![("ok", Json::Bool(false)), ("error", self.to_error())])
    }
}

impl std::fmt::Display for PluginCommError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{}: {}", self.code, self.message)
    }
}

impl std::error::Error for PluginCommError {}

/// expose 注册的 handler：收到**完整请求模型**，返回值就是 CALL 的 result。
pub type CommMethod = dyn Fn(&Context, &Json) -> Result<Json, PluginCommError>;
/// on 注册的事件 handler（订阅方；plugin.event 只回报 handled 数）。
pub type CommEvent = dyn Fn(&Context, &Json);

type CommMethodRef = Rc<CommMethod>;
type CommEventRef = Rc<CommEvent>;
type CommShared = Rc<RefCell<CommState>>;

/// 插件间通信的注册表 + 链路状态（Context 持有；Plugin 通过 ctx 用同一份）。
#[derive(Default)]
struct CommState {
    /// 被调方：method -> handler（expose，§五）。
    methods: HashMap<String, CommMethodRef>,
    /// 订阅方：事件名 -> [handler]（on，§九）；"*" 匹配全部。
    events: HashMap<String, Vec<CommEventRef>>,
    /// 入站消息栈（trace / hop 传递，§二十二/§二十三）。
    inbound: Vec<CommContext>,
    /// 已取消的 request_id（§十八）—— 有界。
    cancelled: Vec<String>,
    /// 等待应答期间到达、但不属于插件间通信的引擎请求（hook / health / …）：
    /// 推迟给主循环按到达顺序处理（与 Go SDK 的 deferred 一致）—— 不丢消息。
    deferred: Vec<Json>,
}

impl Context {
    // ---------- 出站：插件 -> 引擎（反向 op）-> Core Router -> 目标插件 ----------

    /// 当前入站消息的链路上下文（trace / hop）；不在处理入站消息时返回空值。
    pub fn comm_context(&self) -> CommContext {
        match self.comm.borrow().inbound.last() {
            Some(context) => context.clone(),
            None => CommContext::default(),
        }
    }

    /// 调用另一个插件（§五）：plugin.call(target, method, params, opts)。
    ///
    /// 走引擎的反向 op -> Core Router（跨语言必须经 Core；权限在 Core 判定，SDK 绕不过）。
    /// trace_id / hop_count 自动沿用在处理的入站消息（hop 直传，引擎负责 +1）。不自动重试。
    pub fn call(&self, target: &str, method: &str, params: &Json,
                opts: CallOptions) -> Result<Json, PluginCommError> {
        if !json_serializable(params) {
            // 语言内部对象不能过线（§十九）：NaN / Infinity 直接拦在边界上，别写出一行非法 JSON。
            return Err(PluginCommError::new(
                "SERIALIZATION_ERROR",
                "params 不是语言无关类型（NaN / Infinity 无法序列化）",
                Json::obj(vec![]),
            ));
        }
        let context = self.comm_context();
        let args = Json::obj(vec![
            ("target", Json::str(target)),
            ("method", Json::str(method)),
            ("params", params.clone()),
            ("timeout", Json::num(opts.timeout)),
            ("route", Json::str(&opts.route)),
            ("trace_id", Json::str(&context.trace_id)),
            ("hop_count", Json::num(context.hop_count)),
        ]);
        let response = self.comm_engine_op("plugin.call", &args)?;
        PluginCommError::from_response(&response)
    }

    /// 广播事件给其它插件（§九）：plugin.emit(name, payload)；失败即结构化错误。
    pub fn emit(&self, name: &str, payload: &Json) -> Result<EmitResult, PluginCommError> {
        if !json_serializable(payload) {
            return Err(PluginCommError::new(
                "SERIALIZATION_ERROR",
                "payload 不是语言无关类型（NaN / Infinity 无法序列化）",
                Json::obj(vec![]),
            ));
        }
        let context = self.comm_context();
        let args = Json::obj(vec![
            ("name", Json::str(name)),
            ("payload", payload.clone()),
            ("trace_id", Json::str(&context.trace_id)),
            ("hop_count", Json::num(context.hop_count)),
        ]);
        let response = self.comm_engine_op("plugin.emit", &args)?;
        if response.get("ok").and_then(|v| v.as_bool()) != Some(true) {
            let error = response.get("error").cloned().unwrap_or(Json::Null);
            return Err(PluginCommError::from_error(&error));
        }
        Ok(EmitResult {
            delivered: json_u64(response.get("delivered")),
            failed: response.get("failed").and_then(|v| v.as_arr()).cloned().unwrap_or_default(),
            trace_id: json_text(response.get("trace_id")),
        })
    }

    /// 取消一次**自己发起的**在途调用（§十八）。
    pub fn cancel(&self, request_id: &str, reason: &str) -> Result<CancelResult, PluginCommError> {
        let args = Json::obj(vec![
            ("request_id", Json::str(request_id)),
            ("reason", Json::str(reason)),
        ]);
        let response = self.comm_engine_op("plugin.cancel", &args)?;
        if response.get("ok").and_then(|v| v.as_bool()) != Some(true) {
            let error = response.get("error").cloned().unwrap_or(Json::Null);
            return Err(PluginCommError::from_error(&error));
        }
        let echoed = json_text(response.get("request_id"));
        Ok(CancelResult {
            request_id: if echoed.is_empty() { request_id.to_string() } else { echoed },
            cancelled: response.get("cancelled").and_then(|v| v.as_bool()).unwrap_or(false),
            target: json_text(response.get("target")),
        })
    }

    // ---------- 注册：被调方（expose）/ 订阅方（on） ----------

    /// 暴露方法给其它插件（§五）；方法名非法 -> Err(INVALID_ARGUMENT)。
    pub fn expose<F>(&self, method: &str, handler: F) -> Result<(), PluginCommError>
    where
        F: Fn(&Context, &Json) -> Result<Json, PluginCommError> + 'static,
    {
        if !valid_comm_name(method) {
            return Err(PluginCommError::new(
                "INVALID_ARGUMENT",
                &format!("方法名非法（字母/下划线开头，允许 . _，不超过 96 字符）: {}", method),
                Json::obj(vec![("method", Json::str(method))]),
            ));
        }
        self.comm.borrow_mut().methods.insert(method.to_string(), Rc::new(handler));
        Ok(())
    }

    /// 注销暴露的方法；返回是否真的注销了。
    pub fn unexpose(&self, method: &str) -> bool {
        self.comm.borrow_mut().methods.remove(method).is_some()
    }

    /// 订阅事件（§九）；name 传 "*" 订阅全部。
    pub fn on<F>(&self, name: &str, handler: F) -> Result<(), PluginCommError>
    where
        F: Fn(&Context, &Json) + 'static,
    {
        if !valid_event_name(name) {
            return Err(PluginCommError::new(
                "INVALID_ARGUMENT",
                &format!("事件名非法（字母/下划线开头，允许 . _，不超过 96 字符；单个 * 表示全部）: {}", name),
                Json::obj(vec![("name", Json::str(name))]),
            ));
        }
        self.comm.borrow_mut().events.entry(name.to_string()).or_default().push(Rc::new(handler));
        Ok(())
    }

    /// 已暴露的方法名（有序）—— 回 METHOD_NOT_FOUND 时给对方的 exposed 清单就是它。
    pub fn exposed_methods(&self) -> Vec<String> {
        let mut names: Vec<String> = self.comm.borrow().methods.keys().cloned().collect();
        names.sort();
        names
    }

    // ---------- 入站：引擎投递进来的 plugin.call / plugin.event / plugin.cancel ----------

    /// 主循环与嵌套等待共用同一条入站路径：调用点只有一处，语义不会漂移。
    fn dispatch_plugin_method(&self, id: i64, method: &str, params: &Json) -> Result<(), String> {
        match method {
            "plugin.call" => self.handle_inbound_call(id, params),
            "plugin.event" => self.handle_inbound_event(id, params),
            "plugin.cancel" => self.handle_inbound_cancel(id, params),
            _ => Ok(()),
        }
    }

    /// 等待自己发起的调用响应期间，引擎投递进来的请求**不能丢**（§二十二）。
    ///
    /// 插件是单线程的（读写 stdio 的循环）。这里把消息丢掉的话，A 调用 B、B 又回调 A 时
    /// A 永远收不到回调 —— 环保护也就没有真实链路可观察了。因此：
    ///   * plugin.call / plugin.event / plugin.cancel：**原地处理**（§二十二 的硬要求）；
    ///   * 其它请求（hook / health / ...）：按到达顺序推迟给主循环（不丢，引擎不会白等）。
    fn pump_nested(&self, msg: &Json) -> Result<(), String> {
        let method = msg.get("method").and_then(|v| v.as_str()).unwrap_or("");
        let id = msg.get("id").and_then(|v| v.as_f64()).unwrap_or(0.0) as i64;
        if !PLUGIN_METHODS.contains(&method) {
            let queued = {
                let mut state = self.comm.borrow_mut();
                if state.deferred.len() >= MAX_DEFERRED_MESSAGES {
                    false
                } else {
                    state.deferred.push(msg.clone());
                    true
                }
            };
            if !queued {
                return self.reply_protocol_error(
                    id, "推迟队列已满（等待应答期间堆积了过多非通信请求）");
            }
            return Ok(());
        }
        if self.comm.borrow().inbound.len() > MAX_INBOUND_DEPTH {
            // 防退化递归（正常链路远小于此）；不静默丢弃，回一条结构化错误（§二十一）。
            return self.reply_comm(id, PluginCommError::new(
                "INTERNAL_ERROR",
                "嵌套处理深度超过上限",
                Json::obj(vec![("depth", Json::num(MAX_INBOUND_DEPTH as i64))]),
            ).to_body());
        }
        let params = msg.get("params").cloned().unwrap_or(Json::Null);
        self.dispatch_plugin_method(id, method, &params)
    }

    /// 入站 plugin.call：查 expose 注册表 -> 调 handler（拿完整请求模型）-> 回响应模型。
    fn handle_inbound_call(&self, id: i64, params: &Json) -> Result<(), String> {
        let request_id = json_text(params.get("request_id"));
        if !request_id.is_empty() && self.take_cancelled(&request_id) {
            return self.reply_comm(id, PluginCommError::new(
                "CANCELLED", "调用已被取消", Json::obj(vec![])).to_body());
        }
        let method = json_text(params.get("method"));
        let registered = self.comm.borrow().methods.get(&method).cloned();
        let handler = match registered {
            Some(handler) => handler,
            None => {
                let error = PluginCommError::method_not_found(&method, &self.exposed_methods());
                return self.reply_comm(id, error.to_body());
            }
        };
        self.push_inbound(params);
        let invoke: &CommMethod = &*handler;
        let outcome = invoke_comm_handler(|| invoke(self, params));
        self.pop_inbound();
        match outcome {
            Ok(value) => {
                if json_serializable(&value) {
                    self.reply_comm(id, Json::obj(vec![
                        ("ok", Json::Bool(true)),
                        ("result", value),
                    ]))
                } else {
                    self.reply_comm(id, PluginCommError::new(
                        "SERIALIZATION_ERROR",
                        "返回值不是语言无关类型（NaN / Infinity 无法序列化）",
                        Json::obj(vec![])).to_body())
                }
            }
            Err(error) => self.reply_comm(id, error.to_body()),
        }
    }

    /// 入站 plugin.event：投给 on() 注册的 handler（"*" 匹配全部），回 handled 计数。
    fn handle_inbound_event(&self, id: i64, params: &Json) -> Result<(), String> {
        let name = json_text(params.get("name"));
        let handlers: Vec<CommEventRef> = {
            let state = self.comm.borrow();
            let mut list: Vec<CommEventRef> = state.events.get(&name).cloned().unwrap_or_default();
            if name != "*" {
                if let Some(wildcard) = state.events.get("*") {
                    list.extend(wildcard.iter().cloned());
                }
            }
            list
        };
        self.push_inbound(params);
        let mut handled: i64 = 0;
        for handler in handlers.iter() {
            let invoke: &CommEvent = &**handler;
            if invoke_comm_event(|| invoke(self, params)) {
                handled += 1;
            }
        }
        self.pop_inbound();
        self.reply_comm(id, Json::obj(vec![
            ("ok", Json::Bool(true)),
            ("handled", Json::num(handled)),
        ]))
    }

    /// 入站 plugin.cancel：记下这个 request_id（有界），下次收到它就直接回 CANCELLED。
    fn handle_inbound_cancel(&self, id: i64, params: &Json) -> Result<(), String> {
        let request_id = json_text(params.get("request_id"));
        if !request_id.is_empty() {
            let mut state = self.comm.borrow_mut();
            state.cancelled.push(request_id.clone());
            if state.cancelled.len() > MAX_CANCELLED_REQUESTS {
                state.cancelled.clear();        // 有界：取消记录不无限增长
            }
        }
        self.reply_comm(id, Json::obj(vec![
            ("ok", Json::Bool(true)),
            ("cancelled", Json::Bool(!request_id.is_empty())),
        ]))
    }

    /// 取走（并清除）一个已取消的 request_id；命中即「这次调用已被取消」。
    fn take_cancelled(&self, request_id: &str) -> bool {
        let mut state = self.comm.borrow_mut();
        match state.cancelled.iter().position(|item| item.as_str() == request_id) {
            Some(index) => {
                state.cancelled.remove(index);
                true
            }
            None => false,
        }
    }

    fn push_inbound(&self, params: &Json) {
        let context = CommContext {
            trace_id: json_text(params.get("trace_id")),
            hop_count: json_i64(params.get("hop_count")),
            source: params.get("source").cloned().unwrap_or(Json::Null),
            request_id: json_text(params.get("request_id")),
        };
        self.comm.borrow_mut().inbound.push(context);
    }

    fn pop_inbound(&self) {
        let _ = self.comm.borrow_mut().inbound.pop();
    }

    /// 插件间通信应答（协议信封：{"id":N,"result":{...}}）。
    fn reply_comm(&self, id: i64, payload: Json) -> Result<(), String> {
        write_line(&Json::obj(vec![("id", Json::num(id)), ("result", payload)]))
    }

    /// 协议级错误应答（{"id":N,"error":"..."}，与 Plugin::reply_error 同一形状）。
    fn reply_protocol_error(&self, id: i64, message: &str) -> Result<(), String> {
        let trimmed: String = message.chars().take(800).collect();
        write_line(&Json::obj(vec![("id", Json::num(id)), ("error", Json::str(&trimmed))]))
    }

    /// 取出一条「等待应答期间被推迟」的引擎请求（FIFO）；没有就返回 None。
    fn take_deferred(&self) -> Option<Json> {
        let mut state = self.comm.borrow_mut();
        if state.deferred.is_empty() {
            None
        } else {
            Some(state.deferred.remove(0))
        }
    }

    /// 反向 op（与 action 共用一套 id 命名空间）；传输层失败映射成 PLUGIN_ERROR（与 Core 一致）。
    fn comm_engine_op(&self, op: &str, args: &Json) -> Result<Json, PluginCommError> {
        self.engine_op(op, args).map_err(|err| PluginCommError::plugin(&err))
    }
}

/// Plugin 上的插件间通信入口（与 Python 的 api.plugin.* 一一对应，§二十七）。
impl Plugin {
    /// 暴露方法给其它插件（§五）。注册表是共享的：on_startup 里用 ctx.expose 等价。
    pub fn expose<F>(&mut self, method: &str, handler: F) -> Result<&mut Self, PluginCommError>
    where
        F: Fn(&Context, &Json) -> Result<Json, PluginCommError> + 'static,
    {
        self.ctx.expose(method, handler)?;
        Ok(self)
    }

    /// 注销暴露的方法。
    pub fn unexpose(&mut self, method: &str) -> &mut Self {
        self.ctx.unexpose(method);
        self
    }

    /// 订阅事件（§九）；name 传 "*" 订阅全部。
    pub fn on<F>(&mut self, name: &str, handler: F) -> Result<&mut Self, PluginCommError>
    where
        F: Fn(&Context, &Json) + 'static,
    {
        self.ctx.on(name, handler)?;
        Ok(self)
    }

    /// 调用另一个插件（§五）：plugin.call(target, method, params, opts)。
    pub fn call(&self, target: &str, method: &str, params: &Json,
                opts: CallOptions) -> Result<Json, PluginCommError> {
        self.ctx.call(target, method, params, opts)
    }

    /// 广播事件（§九）：plugin.emit(name, payload)。
    pub fn emit(&self, name: &str, payload: &Json) -> Result<EmitResult, PluginCommError> {
        self.ctx.emit(name, payload)
    }

    /// 取消一次自己发起的在途调用（§十八）。
    pub fn cancel(&self, request_id: &str, reason: &str) -> Result<CancelResult, PluginCommError> {
        self.ctx.cancel(request_id, reason)
    }

    /// 当前入站消息的链路上下文（trace / hop）。
    pub fn comm_context(&self) -> CommContext {
        self.ctx.comm_context()
    }
}

/// 错误码是否是协议定义的 12 个之一（§二十一）。
pub fn is_error_code(code: &str) -> bool {
    ERROR_CODES.iter().any(|known| *known == code)
}

/// 插件间通信的方法名（§五）：字母/下划线开头，允许 . 与 _，不超过 96 字符。
fn valid_comm_name(name: &str) -> bool {
    let mut chars = name.chars();
    match chars.next() {
        Some(first) if first.is_ascii_alphabetic() || first == '_' => {}
        _ => return false,
    }
    if name.chars().count() > MAX_COMM_NAME {
        return false;
    }
    chars.all(|ch| ch.is_ascii_alphanumeric() || ch == '_' || ch == '.')
}

/// 事件名允许单独的 *（订阅全部，§九）。
fn valid_event_name(name: &str) -> bool {
    name == "*" || valid_comm_name(name)
}

/// 协议只认语言无关类型（§十九）：NaN / Infinity 不是合法 JSON，在边界处拦下。
fn json_serializable(value: &Json) -> bool {
    match value {
        Json::Num(number) => number.is_finite(),
        Json::Arr(items) => items.iter().all(json_serializable),
        Json::Obj(map) => map.values().all(json_serializable),
        _ => true,
    }
}

fn json_text(value: Option<&Json>) -> String {
    value.and_then(|item| item.as_str()).unwrap_or("").to_string()
}

fn json_i64(value: Option<&Json>) -> i64 {
    value.and_then(|item| item.as_f64()).map(|number| number as i64).unwrap_or(0)
}

fn json_u64(value: Option<&Json>) -> u64 {
    value.and_then(|item| item.as_f64())
        .filter(|number| number.is_finite() && *number > 0.0)
        .map(|number| number as u64)
        .unwrap_or(0)
}

/// 调 expose 注册的 handler：panic 等价于其它语言的「抛异常」-> 结构化 PLUGIN_ERROR（不杀进程）。
fn invoke_comm_handler<F>(call: F) -> Result<Json, PluginCommError>
where
    F: FnOnce() -> Result<Json, PluginCommError>,
{
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(call)) {
        Ok(outcome) => outcome,
        Err(payload) => Err(PluginCommError::new(
            "PLUGIN_ERROR",
            &format!("handler panic: {}", panic_message(&*payload)),
            Json::obj(vec![]),
        )),
    }
}

/// 调 on 注册的事件 handler；返回它是否正常跑完（panic 不计入 handled）。
fn invoke_comm_event<F: FnOnce()>(call: F) -> bool {
    std::panic::catch_unwind(std::panic::AssertUnwindSafe(call)).is_ok()
}

/// 从 panic payload 取人类可读消息（字面量与格式化两种 panic 都覆盖）。
fn panic_message(payload: &(dyn std::any::Any + Send)) -> String {
    if let Some(text) = payload.downcast_ref::<&str>() {
        return (*text).to_string();
    }
    if let Some(text) = payload.downcast_ref::<String>() {
        return text.clone();
    }
    "panic".to_string()
}
