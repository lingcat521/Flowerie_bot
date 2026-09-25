
//! Flowerie Plugin Protocol v1 的 Rust SDK（**零 crate 依赖**，只用 std）。
//!
//! 协议规范：docs/plugin-protocol.md。与其它语言示例的行为一致性由
//! `tests/test_plugin_sdk_contract.py` 用真进程 + 真管道比对（同一批向量）。

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
const OPTIONAL_METHODS: [&str; 8] = [
    "config.get", "config.set", "context.get", "permission.check",
    "storage.delete", "storage.get", "storage.list", "storage.set",
];

/// 插件返回给引擎的动作（唯一副作用出口）。
pub type Action = Json;

#[derive(Default)]
struct Io {
    next_id: u64,
}

type Shared = Rc<RefCell<Io>>;
type StartupFn = Box<dyn Fn(&Context)>;
type MessageFn = Box<dyn Fn(&Context, &Json) -> Option<Json>>;
type HookFn = Box<dyn Fn(&[Json]) -> Json>;

/// 传给插件的上下文：storage / config / permission / action。
pub struct Context {
    pub plugin_id: String,
    pub plugin_dir: PathBuf,
    pub data_dir: PathBuf,
    shared: Shared,
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
    shared: Shared,
    ctx: Context,
}

impl Default for Plugin {
    fn default() -> Self {
        Self::new()
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
            shared: shared.clone(),
            ctx: Context {
                plugin_id: "unknown".to_string(),
                plugin_dir: dir,
                data_dir: data,
                shared,
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
    pub fn register_hook<F: Fn(&[Json]) -> Json + 'static>(&mut self, name: &str, f: F) -> &mut Self {
        self.hooks.insert(name.to_string(), Box::new(f));
        self
    }

    /// 上下文（测试/嵌入场景）。
    pub fn context(&self) -> &Context {
        &self.ctx
    }

    /// 进入协议主循环。
    pub fn run(&mut self) -> Result<(), String> {
        let stdin = io::stdin();
        loop {
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
            let method = msg.get("method").and_then(|v| v.as_str()).unwrap_or("").to_string();
            if method.is_empty() {
                continue;
            }
            let id = msg.get("id").and_then(|v| v.as_f64()).unwrap_or(0.0) as i64;
            let params = msg.get("params").cloned().unwrap_or(Json::Null);
            if self.handle(id, &method, &params)? {
                return Ok(());
            }
        }
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
                    Some(hook) => hook(&args),
                    None => Json::Null,
                };
                self.reply(id, Json::obj(vec![("ok", Json::Bool(true)), ("result", result)]))?;
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
