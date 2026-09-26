# 插件开发者指南（Plugin API v1 · 完整参考）

> 适用版本 **2.3.0** · 协议 `api_version = "1"` · 新手先看 [quick-start.md](quick-start.md)
>

> 这是插件作者的**唯一完整参考**：读完即可写插件，不必读源码。本文所有字段名、方法名、上限与错误码
> 都与 `src/plugins/{manifest,permissions,protocol,comm,router}.py` 逐条核对。
>

> 相关文档：[sdk.md](sdk.md)（SDK 模式）· [api.md](api.md)（动作 × 权限速查）·
> [plugin-protocol.md](plugin-protocol.md)（线协议）· [plugin-communication.md](plugin-communication.md)（插件间通信）·
> [plugin-webui.md](plugin-webui.md) / [plugin-webui-protocol.md](plugin-webui-protocol.md)（WebUI）

---

## 1. 5 分钟上手

**目录结构**（`PLUGIN_DIR` 默认 `./plugins`，一个插件一个子目录）：

```text
plugins/my_first/
├── manifest.json      # 必需：元数据 + 权限声明
├── plugin.py          # 入口（runtime=python）
├── flowerie_sdk/      # 可选：只有用 SDK 模式才需要（cp -r <repo>/plugin_sdk/flowerie_sdk .）
└── data/              # 运行时自动创建：本插件的数据目录
```

**manifest.json（最小可用）**

```json
{
  "id": "my_first",
  "name": "My First Plugin",
  "version": "1.0.0",
  "runtime": "python",
  "entry": "plugin.py",
  "api_version": "1",
  "permissions": ["read_message", "send_message"]
}
```

**plugin.py（最小可运行，经典钩子模式，不需要 SDK）**

```python
def on_message(event, api=None):
    """群消息事件（需批准 read_message）；返回动作 dict / list / None。"""
    if str(event.get("text") or "").startswith("!hi"):
        return {"type": "send_message",                # 动作名 + payload（不是 params）
                "payload": {"group_id": event["group_id"], "message": "你好"}}
    return None

def on_startup(context, api=None):
    api.log("info", "启动，数据目录 %s" % context["data_dir"])
```

> 想用装饰器模式（`FlowerieBot` + `@command` + `await event.reply`）见 [sdk.md](sdk.md)；两种写法协议层等价。
**安装启用（4 步）**

| 步骤 | 操作 |
| :--- | :--- |
| 1. 放入 | 把插件目录放进 `PLUGIN_DIR`（默认 `./plugins`），或 Web UI「插件」页上传 ZIP / 填 URL 安装 |
| 2. 发现 | Web UI「插件」页点「刷新扫描」（`POST /panel/plugins/refresh`）；新插件一律 `discovered`（**禁用**） |
| 3. 启用 | 勾选要批准的权限 → 启用（`POST /panel/plugins/enable`）；批准确是「声明 ∩ 你的选择」，未声明的批不了 |
| 4. 验证 | 群里发 `!hi`；没有反应先查 §9.4 排查表 |

**看日志**

| 位置 | 内容 |
| :--- | :--- |
| `logs/bot.log` | 引擎日志（默认 `init_logging(log_file="logs/bot.log")`） |
| Web UI `GET /api/logs` | 最近日志（`get_recent_logs(limit=100)`） |
| 日志关键字 | `plugin_started` / `plugin_enabled` / `plugin_permission_denied` / `plugin_event_error` / `plugin_crash` / `plugin_output_overflow` |
| 插件主动写 | `api.log("info", "…")` → 引擎日志（无需权限）；子进程 stderr 只留**尾 4KB**，崩溃时随 `plugin_crash` 一起打出 |

---

## 2. manifest.json 全字段参考

顶级字段是**严格白名单**：出现未知字段直接拒绝（`manifest 包含未知字段: [...]`）；manifest 文件 ≤ **64 KiB**。

| 字段 | 必填 | 类型 | 规则 / 上限 | 示例 |
| :--- | :--: | :--- | :--- | :--- |
| `id` | ✅ | string | `^[a-z][a-z0-9_-]{0,31}$`（小写字母开头，≤32）；必须已是小写 | `"my_first"` |
| `name` | ✅ | string | 1~64 字符 | `"My First Plugin"` |
| `version` | ✅ | string | `x.y.z`（三段数字） | `"1.0.0"` |
| `runtime` | ✅ | string | `python` / `node` / `json` / `exec` | `"python"` |
| `entry` | ✅ | string | 相对路径，禁前导 `/`、`..` 段、反斜杠；`json` 可空 | `"plugin.py"` |
| `api_version` | ✅ | string | 只支持 `"1"`（写数字 `1` 也接受，会转字符串） | `"1"` |
| `permissions` | ✅ | string[] | 每项必须在 §5 权限集内；去重；**最多 24 项** | `["read_message"]` |
| `author` | ❌ | string | 超 64 字符**截断**（不报错） | `"flowerie"` |
| `description` | ❌ | string | 超 500 字符**截断** | `"示例插件"` |
| `config` | ❌ | object | JSON 对象；序列化后 ≤ **16 KiB** | `{"values": {"greeting": "hi"}}` |
| `declarations` | ❌ | array | **仅 `runtime=json` 允许**；≤64 条（见 §2.3） | — |
| `web_ui` | ❌ | object | 插件自带管理页声明（见 §7.1） | — |
| `platform` | ❌ | string | **仅 `runtime=exec` 允许**：`any`(默认)/`linux`/`windows`/`darwin`/`android` | `"android"` |
| `arch` | ❌ | string | **仅 `runtime=exec` 允许**：`any`(默认)/`x64`/`arm64`/`x86` | `"arm64"` |

- `entry` 路径规则：`^[A-Za-z0-9_][A-Za-z0-9_.\-/]{0,127}$`。
- `platform`/`arch` 不匹配宿主时启用被拒（如「该插件包面向 windows，当前宿主为 android」）；
  别名 `x86_64`→`x64`、`aarch64`→`arm64`、`win32`→`windows` 会被归一。
- 插件运行在独立子进程，**不能** `import` 引擎内部模块；能力只能来自协议（§3）。

### 2.1 runtime 对照

| runtime | 启动命令（引擎侧） | 适用 |
| :--- | :--- | :--- |
| `python` | `python3 -I src/plugins/runner/python_runner.py --dir <dir> --entry <entry> --plugin-id <id>` | 仓库自带 runner，提供完整 Python API（§4.1） |
| `node` | `node src/plugins/runner/node_runner.js --dir <dir> --entry <entry> --plugin-id <id>` | 仅经典钩子 + 8 个动作方法，**无**存储/配置/WebUI/插件间通信（§4.6） |
| `exec` | 直接执行 `<dir>/<entry>`（不经 shell；自动补 `chmod +x`） | 任意语言，自己实现 JSON-Lines 协议（§3.4） |
| `json` | 不启动进程，引擎进程内做声明式匹配 | 无代码插件（§2.3） |

### 2.2 环境变量与隔离

插件进程只继承 **`PATH` / `HOME` / `LANG` / `TMPDIR` / `TEMP` / `TMP` / `NODE_PATH` / `LD_LIBRARY_PATH`**，
不注入任何 API Key/Token；工作目录 = 插件目录；stderr 只留尾 4KB。
这是**代码级隔离**（无共享状态、无密钥、无引擎内部模块），**不是 OS 沙箱**：插件与引擎同用户运行，
仍可读同用户文件。只安装你审查过的插件；生产环境建议容器/独立用户运行。

### 2.3 声明式插件（runtime=json）

```json
{
  "id": "greet_plugin", "name": "Greet", "version": "1.0.0",
  "runtime": "json", "entry": "", "api_version": "1",
  "permissions": ["read_message", "send_message"],
  "declarations": [
    {"event": "message", "match": {"text_prefix": "hello"}, "priority": 0, "stop": false,
     "actions": [{"type": "send_message",
                  "payload": {"group_id": "${group_id}", "message": "你好 ${user_id}"}}]}
  ]
}
```

- `event` ∈ `message` / `group_message` / `notice`；`match` 可用键：`text_contains` / `text_prefix` /
  `text_exact` / `text_suffix` / `text_regex`（编译失败即拒绝）/ `command` / `user_id`(int) / `group_id`(int)；
  每个 match 值 ≤200 字符。
- `priority` ∈ [-1000, 1000]；`stop` 为 bool；每条规则 1~4 个 `actions`；插件 ≤64 条规则。
- payload 模板字段：`${group_id}` `${user_id}` `${text}` `${message}` `${message_name}`。
- **没有 eval/exec，没有表达式**；声明式插件同样过权限检查，不是沙箱。

---

## 3. 生命周期与线协议

### 3.1 状态机

```text
安装/扫描 → discovered(禁用) ──管理员启用+批准权限──► starting ──initialize 握手──► running
     ▲                                                                              │
     └──────────── 卸载（删目录+注册行） ◄── disabled ◄── 管理员禁用 ────────────────┘
                                    crashed/error ◄── 超时 / 崩溃 / 输出超限（引擎继续运行）
```

生命周期状态（插件间通信用）：`STARTING` / `READY` / `STOPPING` / `STOPPED` / `FAILED`。

### 3.2 方法集

| 类别 | 方法 | 说明 |
| :--- | :--- | :--- |
| 必需（4） | `initialize` `event` `health` `shutdown` | 任何插件都要实现；引擎一定会调用 |
| 可选·核心（8） | `context.get` `config.get` `config.set` `permission.check` `storage.get` `storage.set` `storage.delete` `storage.list` | 在 `initialize` 的 `capabilities` 里声明后引擎才会调用 |
| 可选·WebUI（3） | `webui.page` `webui.action` `webui.asset` | §7 |
| 可选·插件间（3） | `plugin.call` `plugin.event` `plugin.cancel` | §8（发起侧名字是 `plugin.emit`，落地方法名是 `plugin.event`） |
| 引擎内部（1） | `hook` | 引擎调插件具名函数：`{"name":"my_hook","args":[…]}`（WebUI 数据钩子/控制面） |

**能力分组写法**：`capabilities` 可以写方法名，也可以写组名（等价）——
`context` `config` `permission` `storage` `webui` `plugin`；未知项被丢弃。
Python runner 未声明 `PLUGIN_CAPABILITIES` 时默认声明**全部六组**；其它语言 SDK 默认声明全部 14 个方法。
**引擎不会调用未声明的方法**（运行时 `supports()` 门控）。

### 3.3 线格式（JSON-Lines over stdio：一行一个 JSON、UTF-8、写完立即 flush）
```text
引擎 → 插件   {"id":1,"method":"initialize","params":{"context":{"plugin_id":"my_first",
              "plugin_dir":"/…/plugins/my_first","data_dir":"/…/plugins/my_first/data",
              "protocol_version":"1","api_version":"1"}}}
插件 → 引擎   {"id":1,"result":{"ok":true,"api_version":"1","protocol_version":"1",
              "capabilities":["config.get","storage.get","webui.page", …]}}
引擎 → 插件   {"id":2,"method":"event","params":{"event":"message","payload":{"text":"!hi", …}}}
插件 → 引擎   {"id":2,"result":{"actions":[{"type":"send_message","payload":{ … }}]}}
插件 → 引擎   {"id":1000001,"method":"action","params":{"action":"send_message","payload":{ … }}}
引擎 → 插件   {"id":1000001,"result":{"ok":true,"group_id":123}}
插件 → 引擎   {"id":1000002,"method":"engine","params":{"op":"config.get","args":{}}}
引擎 → 插件   {"id":1000002,"result":{"ok":true,"values":{ … }}}
插件 → 引擎   {"id":1000003,"method":"engine","params":{"op":"plugin.call","args":{ … }}}   # §8
引擎 → 插件   {"id":3,"method":"health","params":{}}    →  {"id":3,"result":{"ok":true}}
引擎 → 插件   {"id":4,"method":"shutdown","params":{}}  →  {"id":4,"result":{"ok":true}}（回完再退）
协议级错误    {"id":N,"error":"未知方法: foo"}          # 这一行不是合法请求
```

- **反向 op（插件 → 引擎）只有六个**：`context.get` / `config.get` / `permission.check` /
  `plugin.call` / `plugin.emit` / `plugin.cancel`；未知 op 一律 `{"ok":false,"error":"未知 op: …"}`。
- 插件发起的请求 id 用 **≥ 1000000**（`ACTION_ID_BASE`），与引擎请求 id（1,2,3…）不共用命名空间。
- 身份由连接决定：插件**不能**自报 `plugin_id`（引擎按进程识别，杜绝伪造）。

### 3.4 exec runtime 的四条铁律（任意语言）

1. **一行一个 JSON，写完立刻 flush**（缓冲住 = 引擎永远收不到，插件「没反应」九成是这个原因）。
2. **收到必须回**，`id` 原样带回。
3. **出错回** `{"id":N,"error":"原因"}`，别让进程崩。
4. **stdout 只能有协议 JSON**：日志/调试/编译警告一律走 stderr。

### 3.5 超时与资源上限（按保护级别）

| 项目 | normal（默认） | relaxed | unsafe |
| :--- | --: | --: | --: |
| `initialize` 握手 | 10s | 20s | 30s |
| 单事件处理（`event`） | 15s | 60s | 120s |
| 单次动作数（超出截断） | 8 | 16 | 32 |
| stdout 累计输出（超出杀进程） | 256 KiB | 1 MiB | 4 MiB |

其它固定值：`health` 5s；引擎调插件 hook 4s；插件间调用默认 5000ms、上限 60000ms（§8）；
插件并发处理上限 8（背压）；`shutdown` 等待 5s 后强杀。**保护级别不豁免权限检查**：manifest 校验、
管理员权限、进程隔离、日志、崩溃保护、PermissionManager 在任何级别都生效。

---

## 4. 五种语言的 API 对照

Python / TypeScript / Go / Rust / Java 实现同一套协议，**SDK 都声明全部 14 个可选方法**；差异只在语言习语。

| 能力 | Python（runner） | TypeScript | Go | Rust | Java |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 事件注册 | 模块级 `on_message(event, api)` / `on_notice` / `on_schedule` / `on_command` / `on_request` / `on_lifecycle`；任意事件 `on_<event>`、兜底 `on_event` | `plugin.onMessage(fn)`；`plugin.on(name, fn)`；`onCommand/onNotice/onRequest/onLifecycle/onSchedule` | `plugin.OnMessage(fn)`；`plugin.On(name, handler)`（按 handler 类型分派）；同名 `OnCommand…` | `plugin.on_message(f)`；`plugin.on_event(name, f)`；`on_command…` | `plugin.onMessage(h)`；`plugin.onEvent(name, h)`；`plugin.on(name,h)` 仅用于插件事件 |
| 发消息 | 返回 `{"type":"send_message","payload":{"group_id":…,"message":…}}`；或 `api.send_message({...})` | 返回动作对象；或 `await ctx.action("send_message", {...})` | 返回 `flowerie.Action{"type":…,"payload":…}`；或 `ctx.Action("send_message", map)` | 返回 `Some(Json::obj(...))`；或 `ctx.action("send_message", &json)` | 返回 Map；或 `ctx.action("send_message", Map.of(...))` |
| 存储 | `api.storage_get/set/delete/list` | `ctx.storageGet/Set/Delete/List` | `ctx.StorageGet/Set/Delete/List` | `ctx.storage_get/set/delete/list` | `ctx.storageGet/Set/Delete/List`（`throws IOException`） |
| 配置 | `api.config_get(keys=None)` / `api.config_set({...})` | `await ctx.configGet(keys?)` / `ctx.configSet(v)` | `ctx.ConfigGet(keys)` / `ctx.ConfigSet(v)` | `ctx.config_get()` / `ctx.config_set(&json)` | `ctx.configGet()`（无 keys）/ `ctx.configSet(map)` |
| 权限查询 | `api.permission_check(p) -> bool` | `await ctx.permissionCheck(p)` | `ctx.PermissionCheck(p)` | `ctx.permission_check(p)` | `ctx.permissionCheck(p)` |
| 日志 | `api.log("info", "…")`（写引擎日志） | `ctx.logger.info/warn/error`（stderr） | `ctx.Logf(...)`（stderr，`[flowerie] ` 前缀） | `ctx.log(&str)`（stderr） | `ctx.log(String)`（stderr） |
| WebUI | 模块级 `webui_render(page, context)` / `webui_action(page, action, form, context)` / `webui_asset(path)`；文件页数据钩子 `webui_page(page_id, action, params, values)` | `plugin.webui.page/action/asset(fn)`、`registerWebui(method, fn)` | `plugin.WebUI().Page/Action/Asset(fn)` | `plugin.webui().page/action/asset(f)` | `plugin.webUI().page/action/asset(h)` |
| 插件间调用 | `api.plugin.call(target, method, params, timeout=5000, route="auto")`（`acall` 同义） | `plugin.call(target, method, params, opts)` | `plugin.Call(target, method, params, WithTimeout(ms), WithRoute(r))` | `plugin.call(target, method, &json, CallOptions)` | `plugin.call(target, method, params, CallOptions)`、`callAsync` |
| 事件广播/订阅 | `api.plugin.emit(name, payload)` / `api.plugin.on(name, handler)` | `plugin.emit` / `plugin.on` | `plugin.Emit` / `plugin.OnPluginEvent` | `plugin.emit` / `plugin.on_event` | `plugin.emit` / `plugin.on` |
| 暴露被调用 | `api.plugin.expose(method, handler)` | `plugin.expose(method, handler)` | `plugin.Expose(method, handler)` | `plugin.expose(method, f)` | `plugin.expose(method, h)` |
| 启动/心跳/退出 | runner 自动；`on_startup` / `health_check` / `on_shutdown` | `await plugin.run()`；`onStartup/onHealth/onShutdown` | `plugin.Run()`；`OnStartup/OnHealth/OnShutdown` | `plugin.run()`；`on_startup/on_health/on_shutdown` | `plugin.run()`；`onStartup/onHealth/onShutdown` |
| 控制面 hook | 模块级同名函数 | `plugin.registerHook(name, fn)` | `plugin.RegisterHook(name, fn)` | `plugin.register_hook(name, f)` | `plugin.registerHook(name, h)` |

### 4.1 Python 最小骨架（runtime=python）

```python
def on_startup(context, api=None):
    api.log("info", "启动 %s" % context["plugin_id"])
    api.plugin.expose("ping", lambda params: {"ok": True, "pong": True})   # 供其它插件调用
    api.plugin.on("weather.updated", lambda ev: api.log("info", str(ev)))  # 订阅插件事件

def on_message(event, api=None):
    if str(event.get("text") or "").startswith("!kv"):
        api.storage_set("last", event.get("text"))          # 插件私有 KV（无需权限）
        other = api.plugin.call("minimal_go", "ping", {}, timeout=2000)  # 需 plugin.call.<target>
        return {"type": "send_message",
                "payload": {"group_id": event["group_id"], "message": str(other)}}
    return None
```

### 4.2 TypeScript（runtime=exec，entry=run.sh）

```ts
import { FloweriePlugin } from "../../../sdk/typescript/flowerie_sdk.ts";  // 打包时把 SDK 一起带上

const plugin = new FloweriePlugin({ pluginId: "my_plugin" });

plugin.onStartup((ctx) => ctx.logger.info("ready " + ctx.pluginId));
plugin.onMessage((ctx, ev) => ev.text === "ping"
  ? { type: "send_message", payload: { group_id: ev.group_id, message: "pong" } }
  : null);

await plugin.run();     // Node >= 22.6 可直接跑 .ts；老 node 用 tsc 编译（见 §4.7）
```

### 4.3 Go（runtime=exec）

```go
package main

import "github.com/lingcat521/Flowerie_bot/sdk/go/flowerie"

func main() {
    plugin := flowerie.New()

    plugin.OnStartup(func(ctx *flowerie.Context) { ctx.Logf("ready %s", ctx.PluginID) })
    plugin.OnMessage(func(ctx *flowerie.Context, ev map[string]any) any {
        if text, _ := ev["text"].(string); text == "ping" {
            return flowerie.Action{"type": "send_message",
                "payload": map[string]any{"group_id": ev["group_id"], "message": "pong"}}
        }
        return nil
    })

    if err := plugin.Run(); err != nil {
        panic(err)
    }
}
```

### 4.4 Rust（runtime=exec）

源码以 `mod flowerie;` 引入 SDK：构建时把 `sdk/rust/src/lib.rs` 复制成 `src/flowerie/mod.rs`、
`sdk/rust/src/json.rs` 复制成 `src/flowerie/json.rs`，再 `rustc --edition 2021 -O`。

```rust
mod flowerie;
use flowerie::{Context, Json, Plugin};

fn main() {
    let mut plugin = Plugin::new();
    plugin.on_startup(|ctx: &Context| ctx.log("ready"));
    plugin.on_message(|_ctx: &Context, ev: &Json| {
        if ev.get("text").and_then(|v| v.as_str()) == Some("ping") {
            return Some(Json::obj(vec![
                ("type", Json::str("send_message")),
                ("payload", Json::obj(vec![
                    ("group_id", ev.get("group_id").cloned().unwrap_or(Json::Null)),
                    ("message", Json::str("pong"))])),
            ]));
        }
        None
    });
    if let Err(err) = plugin.run() {
        eprintln!("[flowerie] {}", err);
        std::process::exit(1);
    }
}
```

### 4.5 Java（runtime=exec，entry=run.sh）

```java
import dev.flowerie.sdk.FloweriePlugin;
import dev.flowerie.sdk.Json;

public final class Plugin {
    public static void main(String[] args) throws Exception {
        FloweriePlugin plugin = new FloweriePlugin();
        plugin.onStartup(ctx -> ctx.log("ready " + ctx.pluginId()));
        plugin.onMessage((ctx, event) -> "ping".equals(event.get("text"))
                ? Json.obj("type", "send_message",
                           "payload", Json.obj("group_id", event.get("group_id"), "message", "pong"))
                : null);
        plugin.run();
    }
}
```

### 4.6 Node.js（runtime=node）——能力受限的那一个

`index.js` 导出同名钩子（`on_startup` / `on_message` / `health_check` / `on_shutdown` / `webui_page` …，可 async）并返回动作。
Node 运行时的 `api` **只有** `send_message` / `send_private_message` / `get_group` / `get_user` / `get_memory` /
`write_memory` / `http_request` / `log`：**没有**存储、配置、权限查询、WebUI Protocol、插件间通信 ——
需要这些能力请改用 `runtime=exec` + `sdk/typescript`（§4.2）。

### 4.7 构建与入口

**构建与入口**：引擎不做构建，只 `exec` `entry`；`run.sh` 必须自己编译或 `exec` 现成产物，产物缺失时**非零退出**
（脚本里一律用 `exec`，否则信号与退出码传不下去）。示例（`examples/multilang-sdk/`）：Python `python/` 无需构建（`plugin.py`）；
TypeScript `typescript/` 由 `build.sh` 决定（Node >= 22.6 直接跑 TS，否则 `tsc`，无 `@types/node` 时带 `sdk/typescript/shims/node.d.ts`）→ `run.sh`；
Go `go/` 用临时模块 `GOPROXY=off go build -trimpath -o .build/plugin .` → `run.sh`；Rust `rust/` 复制 SDK 后 `rustc --edition 2021 -O` → `run.sh`；
Java `java/` 用 `javac` 编译 SDK + 插件（JDK >= 11）→ `run.sh`。

## 5. 权限系统

**模型**：插件默认 0 权限 → `manifest.permissions` 声明 → 管理员启用时**批准子集** →
每次动作执行前经 `PermissionManager.check()` → 未批准即拒绝并记 `plugin_permission_denied` 日志。
**插件永远无法自己决定权限**（唯一检查点在引擎）。

### 5.1 全部权限键（`ALL_PERMISSIONS`，共 31 项）

**31 个权限键与语义**（按能力分组）：

- **消息**：`send_message` 发群/私聊消息（含转发、戳一戳、表情回应等发送类动作）；`read_message` 接收消息事件（未批准则**事件根本不投递**）与 matcher 注册；`read_message_history` 读消息详情/群历史/上下文/搜索/引用链；`delete_message` 撤回（仅本 bot 发送过的消息）/编辑/标记。
- **群与用户**：`read_group_info` 读群信息/成员/公告/群文件/精华；`read_user_info` 读用户信息/好友列表/登录信息/设备；`group_manage` 群管理写操作（禁言/踢人/管理员/名片/公告/群文件/精华）；`request_handle` 好友与加群请求处理（approve/deny）。
- **记忆 / 存储 / 定时**：`read_memory` 读记忆与语义检索；`write_memory` 写记忆（更新/删除/置顶）；`storage` 插件 KV 存储动作与数据域（`kv_*` / `db_*` / `cache_*`）；`scheduler` 定时任务（interval/delay/daily）。
- **AI / 资料 / 网络 / 文件**：`ai_chat` 受限 AI 对话（独立预算，务必自限频）；`bot_profile` 修改 Bot 自身资料；`http_request` 受限 HTTP 请求（SSRF 防护；MCP 动作同权限）；`filesystem_read` / `filesystem_write` 插件目录内读/写文件。
- **插件运行时**：`plugin_admin` 插件管理面（调用/事件/服务/重载/发现/健康/配置/调试）。
- **WebUI**：`web_ui` 插件自带管理页（旧名，等价 `webui.view` + `webui.action`）；`web_ui.files` 文件上传下载（仅插件自身空间）；`webui.view` 打开页面、读静态/动态资源（只读）；`webui.action` 提交表单动作；`webui.config.read` / `webui.config.write` WebUI 读操作员配置 / 写插件自己的覆盖层；`webui.storage.read` / `webui.storage.write` WebUI 读插件存储快照 / 写插件存储。
- **插件间通信**：`plugin.emit` 事件广播；`plugin.call` 调用任意插件（等价 `plugin.call.*`；默认不给）。
- **保留（v1 无实现，批准也会拒绝）**：`execute_process`、`webhook`（`webhook` 动作会转发成 `http_request`，需 `http_request` 权限）。

**动态权限键** `plugin.call.<target>[.<method>]` 不受 31 项列举限制，只要形状合法即可声明
（target `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`，method `^[A-Za-z_][A-Za-z0-9_.]{0,95}$`）。
匹配是**从细到粗的精确串匹配，不做 glob**（只有两个字面通配键）：

```text
plugin.call.weather.get_status  >  plugin.call.weather  >  plugin.call.*  >  plugin.call
```

### 5.2 动作到权限的映射（`ACTION_PERMISSIONS`，181 个动作）

**`ACTION_PERMISSIONS` 共 181 个动作**，按所需权限分组；`无需权限` 是内建无副作用动作，未知动作一律拒绝（白名单外，不是默认放行）：

- `send_message`：send_message, send_reply, send_many, send_private_message, forward_message, merge_message, poke, reaction, emoji；`read_message`：matcher_register, react, split_message。
- `read_message_history`：get_message, get_group_history, get_context, search_message, quote_chain, favorite_message, read_status, emoji_list；`read_group_info`：get_group, get_group_info, get_group_member, get_group_members, group_info, group_list, group_admins, group_member_search, group_mute_status, group_config, group_files, group_files_in, group_file_url, group_res, group_notice_get, group_essence, essence_list, group_honor, is_group_admin, is_group_owner, tap。
- `read_user_info`：get_user, friends, friend_detail, friend_remark, friend_delete, friend_group, friend_category, friend_online, like, login_info, devices, status, user_history, user_forward, user_poke；`group_manage`：group_ban, group_kick, group_admin, group_member_update, group_card, group_title, group_rename, group_whole_ban, group_notice_create, group_notice_update, group_notice_send, group_notice_delete, group_portrait, group_essence, group_invite, group_file_upload, group_file_rename, group_file_delete, group_file_move, group_folder_create, group_folder_delete, group_folder_rename, group_forward, pin, unpin。
- `request_handle`：handle_friend_request, handle_group_request, group_apply；`scheduler`：schedule_register, schedule_cancel, schedule_list；`storage`：kv_get, kv_set, kv_delete, kv_list, db_query, db_transaction, db_migration, db_index, cache_get, cache_set, cache_delete, memory_tag；`read_memory`：get_memory, mem_update, mem_clear, memory_get, memory_search, memory_semantic, memory_expire；`write_memory`：write_memory, memory_update, memory_delete, memory_pin。
- `ai_chat`：ai_chat, ai_stream, ai_vision, ai_embedding, ai_rerank, ai_token, ai_models, ai_model_info, ai_usage, ai_budget；`http_request`：http_request, http_put, http_delete, http_head, http_download, mcp_server, mcp_tools, mcp_call, mcp_resource, mcp_prompt, mcp_status。
- `filesystem_read`：file_read, file_download, file_info, file_convert, image_compress, image_resize, image_screenshot, audio_info, video_info；`filesystem_write`：file_write, file_upload, file_delete；`bot_profile`：profile_set。
- `plugin_admin`：plugin_call, plugin_event, plugin_service, plugin_discovery, plugin_dependency, plugin_health, plugin_reload, plugin_config, router, ws, sse, http_middleware, static_file, task_status, task_cancel, task_pause, task_resume, resource_usage, resource_quota, runtime_status, metrics, trace, health, debug, plugin_test, mock_api；`execute_process` / `webhook`：同名动作（保留，一律拒绝）；**无需权限**：log, test, now, format_time, random_choice, random_int。

### 5.3 申请 / 批准 / 被拒绝

| 阶段 | 行为 |
| :--- | :--- |
| 声明 | 只写你要用的；未声明的权限**批不了**（管理员只能批准声明过的子集） |
| 批准 | `enable(plugin_id, approved_permissions=[...])`：只保留「声明 ∩ 选择」；批准了未声明的权限直接报错；声明了权限却一项都不批则拒绝启用 |
| 拒绝（动作级） | 返回 `{"ok": false, "denied": true, "error": "需要权限 'x'（管理员未批准）"}` 并记 `plugin_permission_denied`；**页面不弹错**（表现为「机器人毫无反应」） |
| 拒绝（事件级） | 事件**不投递**（连钩子都不会被调用） |
| 拒绝（WebUI） | 按 §7.2 各自的闸门拒绝（未批准 `webui.view` 时页面渲染错误块） |
| 保护级别 | normal / relaxed / unsafe 只放宽**资源限制**，权限检查照旧 |

---

## 6. 存储与配置

### 6.1 `storage.*`（插件私有 KV，协议可选方法，**不需要权限**）

| 方法 | 参数 | 返回 | 说明 |
| :--- | :--- | :--- | :--- |
| `storage.get` | `{"key": "k"}` | `{"ok":true,"value":<任意>}`（不存在时 `null`） | 落盘 `<data_dir>/storage/<key>.json` |
| `storage.set` | `{"key","value"}` | `{"ok":true,"size":N}` | 原子写（`.tmp` + `os.replace`） |
| `storage.delete` | `{"key"}` | `{"ok":true,"deleted":bool}` | 不存在不算错 |
| `storage.list` | `{"prefix": ""}` | `{"ok":true,"keys":[...]}` | 按前缀过滤，最多返回 200 个 |

**键规则**：`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`（字母数字开头、<=64，允许 `.` `_` `-`；不允许斜杠、`..`、隐藏段）。
**上限**：<=**200** 个键（`MAX_STORAGE_KEYS`）；单值序列化后 <=**64 KiB**（`MAX_STORAGE_VALUE_BYTES`）。
键非法/超限返回 `{"ok":false,"error":"…"}`，不抛异常。
**落盘位置**：`<PLUGIN_DIR>/<plugin_id>/data/storage/`（`data_dir` 由 `initialize` 的 context 给出，自动创建；
创建失败时回退插件目录本体）。五种语言的 SDK 都写同一个位置（存储由插件进程自己实现，没有引擎侧 RPC）。

> 另有一种**动作层**存储：`kv_get` / `kv_set` / `kv_delete` / `kv_list`（需 `storage` 权限，走引擎检查）以及
> 数据域 `db_query` / `db_transaction` / `db_migration` / `db_index`（落 `data.json`，行式，单次 limit <=200）。
> 二者互不影响：协议层 `storage.*` 是插件私有文件，动作层 `kv_*` 由引擎记账。

### 6.2 `config.*`（操作员配置只读 + 插件覆盖层）

| 方法 | 参数 | 返回 |
| :--- | :--- | :--- |
| `config.get` | `{"keys": [...]}`（可选过滤） | `{"ok":true,"values":{…}}` |
| `config.set` | `{"values": {…}}` | `{"ok":true,"saved":[键名…]}` |

**覆盖层语义**：`config.get` 返回「插件覆盖层 ∪ 操作员配置」，**操作员值优先**（插件改不了管理员的值）。
操作员配置来自 `manifest.config`（若写成 `{"values": {…}}` 会自动解包 `values`）。
`config.set` 只写**插件自己的覆盖层** `<data_dir>/config.json`，不碰全局配置。

**键规则**同存储键；**上限**：<=**64** 个键（`MAX_CONFIG_KEYS`）、单值 <=**8 KiB**（`MAX_CONFIG_VALUE_BYTES`）；
非法键/超限返回 `{"ok":false,"error":"…"}`。

注意：反向 op 里只有 `config.get`（只读）；`config.set` 不是反向 op —— 它由插件自身 SDK 或引擎在
`webui.action` 里经 `config_set` 调用（§7.3），写入同样受上面的键/大小上限约束。

---

## 7. Plugin WebUI

插件自带管理页：**插件只提供内容**，路由/权限/校验/净化/隔离全部由引擎负责。

### 7.1 manifest 声明

```json
{
  "permissions": ["web_ui", "web_ui.files"],
  "web_ui": {
    "entry": "webui_page",
    "static": "static",
    "pages": [
      {"id": "index",    "title": "总览", "file": "pages/index.html"},
      {"id": "settings", "title": "设置", "file": "pages/settings.html", "description": "基础设置"},
      {"id": "dynamic",  "title": "动态页", "render": "plugin"}
    ]
  }
}
```

| 字段 | 规则 |
| :--- | :--- |
| `web_ui` | 对象；**只允许** `pages` / `entry` / `static` 三个键（未知键拒绝） |
| `web_ui.pages` | 非空数组，**<=8** 页；每页只允许 `id` / `title` / `description` / `file` / `render` |
| `pages[].id` | `^[a-z][a-z0-9_-]{0,31}$`（URL 里的 page 名） |
| `pages[].title` | 1~64 字符（必填，显示在页签上） |
| `pages[].description` | <=300 字符（超出截断） |
| `pages[].file` | 插件 `webui/` 内的相对路径，**只允许 `.html`**；<=200 字符；禁绝对路径 / `..` / 反斜杠 / 隐藏段 |
| `pages[].render` | `"file"`（同 `file`）或 `"plugin"`（HTML 由插件经 `webui.page` 返回）；与 `file` 二选一 |
| `web_ui.entry` | 数据钩子函数名，`^[a-z_][a-z0-9_]{0,63}$`，默认 `webui_page` |
| `web_ui.static` | 插件内相对目录，默认 `static`（禁 `..` / 绝对路径） |

**三种页面形态**：`file`（引擎读文件 → 净化 → 替换变量）、`render:"plugin"`（插件返回 HTML → 同样先净化再替换）、
不写 `file`/`render`（旧 DSL 组件树，兼容保留，不推荐）。

### 7.2 路由与权限

| 方法 | 路径 | 权限闸门 |
| :--- | :--- | :--- |
| GET/POST | `/panel/plugins/webui/{pid}/{page}` | 面板令牌 + `webui.view`（POST 另需 `webui.action`）；别名 `web_ui` 等效 |
| GET | `/panel/plugins/webui/{pid}/static/{path}` | 启用的插件 + 批准集里**字面** `web_ui`（不认别名；只批 `webui.view` 时 CSS 会 404） |
| GET | `/panel/plugins/webui/{pid}/asset/{path}` | `webui.view` + 插件声明 `webui.asset` |
| POST | `/panel/plugins/webui/upload/{pid}/{page}` | `web_ui.files` |
| GET | `/panel/plugins/webui/files/{pid}/{name}` | `web_ui.files` |

页面地址形如 `/panel/plugins/webui/<plugin_id>/<page_id>`；表单 POST 到同一路径即可。

### 7.3 协议方法（引擎到插件）

```text
webui.page    params {"page":{"id","title","description"}, "context":{…6 键…}}
              回     {"ok":true,"html":"<h2>…</h2>", "vars":{…}, "message":"…"}
webui.action  params {"page":{…}, "action":"save", "form":{"k":"v"}, "context":{…}}
              回     {"ok":true,"html":…, "vars":{…}, "message":…,
                     "config_set":{…}, "storage_set":{…}}   # 写回需 webui.config.write / webui.storage.write
webui.asset   params {"path":"logo.png"}
              回     文本 {"content_type":"text/css","body":"…"} / 二进制 {"content_type":"image/png","base64":"…"}
```

- 插件返回**字符串**等价于 `{"html": …}`；对象里只有 `html` / `vars` / `context` / `message` / `content_type` /
  `body` / `base64` / `config_set` / `storage_set` 会被采纳，其余字段丢弃。
- 页面钩子超时 4s；返回值非对象或钩子抛异常 = **操作级错误**（`{"ok":false,"error":…}`），不是协议级错误。
- 文件页的**数据钩子**（`web_ui.entry`，签名 `(page_id, action, params, values)`）返回 `{"vars": {…}, "message": "…"}`；
  返回 DSL 组件树（含 `type` 键）会被拒绝。
- **执行顺序是「先净化、后替换变量」**：变量值里写 `{{ … }}` 或 `<script>` 只会变成字面文本。

### 7.4 受控 context（六个顶层键，永远只有这些）

```json
{"plugin": {"id": "…", "name": "…"},
 "page":   {"id": "…", "title": "…"},
 "request":{"method": "GET", "action": "get"},
 "user":   {"authenticated": true, "role": "admin"},
 "config": {},          // 需 webui.config.read，否则空对象
 "data":   {}}          // 需 webui.storage.read，否则空对象（存储快照，经 storage.list + storage.get 取）
```

**绝不**包含面板令牌、会话、环境变量、宿主路径。

### 7.5 模板变量与净化规则

**模板变量**：语法 `{{ key }}`（key `^[A-Za-z_][A-Za-z0-9_.]{0,63}$`，实际是**扁平字典**查值）。
引擎固定提供 6 个：`plugin_id` `plugin_name` `page_id` `page_title` `page_description` `message`；
插件返回的 `vars` / `context` 会**合并覆盖**在上面。命中则 HTML 转义（`quote=True`）；未命中则替换为空串并计入
`unresolved`（页面壳会显示告警，不静默）。**不支持**循环/条件/表达式/函数调用/属性链。

**HTML 净化**（白名单，`sanitize_plugin_html`）：输入 <=512 KiB，输出 <=1 MiB，嵌套深度 <=32；每次丢弃都记进报告。

| 类别 | 规则 |
| :--- | :--- |
| 标签白名单 | 结构/表单/表格/文本类：div span p h1-h6 ul ol li dl dt dd table thead tbody tfoot tr th td caption colgroup col form label input select option optgroup textarea button fieldset legend a img pre code blockquote hr br strong em b i u s small nav section article header footer main aside figure figcaption details summary mark time abbr sup sub kbd samp var address |
| 连内容丢弃 | script style iframe object template svg math noscript applet frameset |
| 只丢标签 | meta base frame param source track embed；html / head / body / title 也不在白名单（标签被丢，**文本会留在正文**） |
| 属性 | 全局 class id title style dir lang + 每标签白名单（a: href/target/rel；img: src/alt/width/height；form: method/action/enctype；input: type/name/value/placeholder/required/checked/disabled/readonly/min/max/step/maxlength/size/pattern/accept …） |
| 事件属性 | 任何 `on*` 一律丢弃 |
| URL 属性 | href / src / action / poster / formaction：只允许 `http:` `https:` `mailto:` 与站内相对路径；`javascript:` `vbscript:` `data:` `file:` `blob:` 一律拒绝；`action`/`formaction` 只允许**站内相对路径**（表单不能 POST 到外站） |
| style 属性 | 含 `expression(` / `url(` / `javascript` / `@import` / `behavior` / 反斜杠 / `{}` `<>` 就整条丢弃 |
| 样式表 | 只放行 `<link rel="stylesheet" href="/panel/plugins/webui/<pid>/static/…">`（必须落在本插件 static 前缀下） |
| 注释/声明 | 注释、DOCTYPE、处理指令、未知实体全部丢弃或转义 |

**CSS 净化**（`sanitize_plugin_css`，静态与动态资源同一收口）：<=256 KiB；删 `@import`；`url(...)` 只允许站内相对路径
（其余替换为 `none`）；删 `expression(` / `javascript:` / `vbscript:` / `behavior:` / `-moz-binding`；删 `</style`。

### 7.6 零 JS 约束

- 静态扩展名白名单**没有 `.js`**（`.css .png .jpg .jpeg .gif .webp .txt .json .md .csv .ico`）； 动态资源 MIME 白名单同样没有 javascript / text/html / svg。 - 内联 JS 不可用：`<script>` 连内容被丢；`on*` 属性被丢；`javascript:` URL 被拒。
- 页面响应头 CSP：`default-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'`， 外加 `X-Content-Type-Options: nosniff`、`Referrer-Policy: no-referrer`。 结论：**只有 HTML + CSS + 服务端渲染的表单 POST**。交互 = form POST 到 `webui.action` 后重新渲染。

### 7.7 静态资源 / 动态资源 / 上传下载

| 通道 | 位置 | 规则 |
| :--- | :--- | :--- |
| 静态文件 | `<plugin>/webui/<static 目录>/` | <=4 MiB/文件；扩展名白名单（含 `.ico`）；`.css` 每次请求过 CSS 净化；URL `…/{pid}/static/<相对路径>` |
| 动态资源 | 插件经 `webui.asset` 返回 | <=256 KiB；扩展名必须是资源 MIME 表白名单键；声明 `content_type` 必须与扩展名一致；文本用 `body`，二进制用 `base64`；失败一律 404（不泄露存在性） |
| 上传 | `POST …/upload/{pid}/{page}`（multipart，字段名 `file`） | 需 `web_ui.files`；文件名 `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`；扩展名 `.png .jpg .jpeg .gif .webp .txt .json .md .log .csv`；<=**10 MiB**；图片校验魔数；**不允许覆盖同名**；落到 `<plugin>/webui/`（不是 `static/`，只能经下载路由访问） |
| 下载 | `GET …/files/{pid}/{name}` | 需 `web_ui.files`；文件名同上；必须是插件空间内的普通文件；<=50 MiB；`Content-Disposition: attachment` |

上传成功后跳回页面并把 `msg`、`files`（逗号分隔）放进下一次 GET 的 `params`，插件据此提示。

### 7.8 最小 WebUI 插件（可直接抄 `examples/plugins/html_webui_demo/`）

```text
html_webui_demo/
├── manifest.json          # 见 §7.1（pages[].file 指向 webui/pages/*.html）
├── main.py                # webui_page(page, action, params, values) 返回 {"vars": {...}, "message": …}
└── webui/
    ├── pages/index.html   # 里面用 <link rel="stylesheet" href="/panel/plugins/webui/html_webui_demo/static/style.css">
    ├── pages/settings.html
    └── static/style.css
```

```html
<h1>{{ plugin_name }} · 总览</h1>
<table><tr><th>插件 ID</th><td>{{ plugin_id }}</td></tr>
       <tr><th>当前页</th><td>{{ page_title }}</td></tr></table>
<p class="ok">{{ message }}</p>
<form method="post" action="/panel/plugins/webui/html_webui_demo/settings">
  <label>问候语 <input type="text" name="greeting" value="{{ greeting }}" maxlength="80"></label>
  <button type="submit" name="plugin_action" value="save">保存</button>
</form>
```

```python
def webui_page(page, action, params, values):
    """文件页数据钩子：action=get 或按钮的 value；values 是表单值。"""
    state = _load_state()
    if action == "save":
        state["greeting"] = str(values.get("greeting") or "")[:80]
        _save_state(state)
        return {"vars": {"greeting": state["greeting"]}, "message": "设置已保存"}
    return {"vars": {"greeting": state["greeting"]}, "message": ""}
```

`webui/static/style.css` 的选择器请统一收在 `.flowerie-plugin-webui` 之下（页面壳会把内容包进这个 class）。

**两个高频坑**：

1. 净化在替换之前执行，所以 `<input ... {{ checked }}>` 这类**裸属性占位符会被整条丢掉**（占位符也不剩）——
   请改用 `value="{{ x }}"` / `class="{{ x_state }}"`，或改用 `render:"plugin"` 整页返回。
2. 只批准 `webui.view`（不批 `web_ui`）时页面能开，但静态 CSS **404**（静态路由只认字面 `web_ui`）。

---

## 8. 插件间通信（Plugin-to-Plugin）

五类消息严格区分（CALL / RESPONSE / EVENT / ERROR / CANCEL）；跨语言**一律经 Core Router**，SDK 无法私建旁路。

### 8.1 线格式
```text
CALL   引擎到目标  {"id":3,"method":"plugin.call","params":{<request 模型>}}
REPLY  目标到引擎  {"id":3,"result":{"ok":true,"result":<any>}}
ERROR  目标到引擎  {"id":3,"result":{"ok":false,"error":{"code","message","data"}}}
EVENT  引擎到订阅者 {"id":4,"method":"plugin.event","params":{<event 模型>}}  -> {"id":4,"result":{"ok":true,"handled":N}}
CANCEL 引擎到目标  {"id":5,"method":"plugin.cancel","params":{"kind":"CANCEL","request_id":"…","reason":"…"}}
发起   插件到引擎  {"id":1000001,"method":"engine","params":{"op":"plugin.call","args":{<request>}}}
       插件到引擎  {"id":1000001,"method":"engine","params":{"op":"plugin.emit","args":{<event>}}}
       插件到引擎  {"id":1000001,"method":"engine","params":{"op":"plugin.cancel","args":{"request_id":"…"}}}
```
**request 模型**：

```json
{"request_id": "…", "source": {"plugin_id": "a", "runtime": "python", "instance_id": "0"},
 "target": {"plugin_id": "b", "runtime": "go", "instance_id": "0"}, "method": "get_status",
 "params": {}, "timeout": 5000, "trace_id": "…", "call_id": "…", "hop_count": 0,
 "route": "auto", "metadata": {}}
```
`source` **由引擎按连接填写**（插件自报无效）；`target` 可写 `"b"`（任意健康实例）或 `"b#instance1"`（指定实例）；
`route` 属于 `auto|core|local`。**event 模型**：`{"event_id","name","payload","source","trace_id","hop_count","metadata"}`。

### 8.2 SDK API（五种语言同名同义）

| 语言 | 调用 | 广播 | 订阅 | 暴露 | 取消 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Python | `api.plugin.call(target, method, params, timeout=5000, route="auto")`（`acall` 同义） | `api.plugin.emit(name, payload)` | `api.plugin.on(name, handler)`（`"*"` = 全部） | `api.plugin.expose(method, handler)`（`None` 注销） | `api.plugin.cancel(request_id, reason="…")`；`is_cancelled(rid)` |
| TypeScript | `plugin.call(target, method, params, opts)` | `plugin.emit(name, payload)` | `plugin.on(name, h)` | `plugin.expose(method, h)` | `plugin.cancel(rid, reason)` |
| Go | `plugin.Call(target, method, params, WithTimeout(ms), WithRoute(r), WithRequestID(id))` | `plugin.Emit(name, payload)` | `plugin.OnPluginEvent(name, h)` | `plugin.Expose(method, h)` | `plugin.Cancel(rid, reason)`；`CancelledRequests()` |
| Rust | `plugin.call(target, method, &json, CallOptions)` | `plugin.emit(name, &json)` | `plugin.on_event(name, f)` | `plugin.expose(method, f)` | `plugin.cancel(rid, reason)` |
| Java | `plugin.call(target, method, params, CallOptions)` / `callAsync` | `plugin.emit(name, payload)` | `plugin.on(name, h)` | `plugin.expose(method, h)` | `plugin.cancel(rid, reason)` |

Python 被调用方的 handler 签名是 `handler(params)` 或 `handler(params, api)`；抛异常得到 `PLUGIN_ERROR`。

### 8.3 12 个错误码（响应里的 `error.code`，没有数字值）

| 码 | 含义 | 触发点 |
| :--- | :--- | :--- |
| `PLUGIN_NOT_FOUND` | 目标插件不存在（指定实例不存在时 `data.available` 列出可用实例） | 路由解析 |
| `PLUGIN_NOT_READY` | 目标处于 STARTING / STOPPING | 路由解析 |
| `PLUGIN_UNAVAILABLE` | 目标 FAILED / STOPPED（崩溃或已禁用） | 路由解析、投递失败 |
| `METHOD_NOT_FOUND` | 目标没有暴露该方法，或目标未声明 `plugin.call` 能力 | 目标侧 / 能力闸门 |
| `PERMISSION_DENIED` | 调用方缺 `plugin.call.<target>[.<method>]`（`data.required`/`granted`）或 `plugin.emit` | 权限闸门（**不投递**） |
| `INVALID_ARGUMENT` | request / event / DTO 形状非法（target、method、params 类型等） | 校验 |
| `TIMEOUT` | 投递超过 timeout（`data.timeout_ms`）；随后向目标发 CANCEL | 投递 |
| `CANCELLED` | 取消一个不存在或已完成的 request_id；或该调用已被取消 | 取消路径 |
| `SERIALIZATION_ERROR` | 语言内部对象 / NaN / 非字符串键 / 非法 `$bytes` / 嵌套 >32 层 | 序列化边界 |
| `PLUGIN_ERROR` | 目标 handler 抛异常，或对面只回了一句非结构化错误 | 目标侧 |
| `INTERNAL_ERROR` | 未知错误码被归一、传输层异常、调用方未注册等 | 引擎内部 |
| `PLUGIN_CALL_LOOP` | `hop_count >= 8`（`MAX_HOP_COUNT`），**投递前终止** | 环保护 |

错误响应形状固定为 `{"request_id","ok":false,"error":{"code","message","data"}}`；未知码归一成 `INTERNAL_ERROR`
（`from_error` 兜底 `PLUGIN_ERROR`），**不会退化成一句字符串**。五种语言 SDK 里的码表与上面完全一致。

### 8.4 超时 / 取消 / 环保护 / trace

- **超时**：默认 **5000ms**，上限 **60000ms**（引擎侧归一：非法值取默认、超上限截断）。插件间调用超时
  **不杀目标进程**（与事件超时不同），而是回 `TIMEOUT` 并向目标发 CANCEL（CANCEL 自身预算 1000ms）。
- **取消**：只能取消**自己发起的**在途 `request_id`；目标未声明 `plugin.cancel` 时如实返回「未送达」
  （`cancelled:false`），不假装成功。跨语言差异：只有 Go（`WithRequestID`）与 Java（`CallOptions.requestId`）
  能把 request_id 握在手里；Python / TypeScript / Rust 的 `call()` 只返回 result，拿不到自己的 request_id。
  查询被取消状态目前只有 Python 有 `is_cancelled` / `cancelled_requests`（Go 只有 `CancelledRequests()`）。
  长任务应在步骤之间自行检查；**同步阻塞中的 handler 无法被立刻打断**，CANCEL 会在它返回后才被处理。
- **环保护**：唯一机制是 hop 计数——每次转发 `hop_count + 1`，达到 8 立即 `PLUGIN_CALL_LOOP` 且不再向下转发。
  该判定**只在引擎侧**（`PluginBus`），各语言 SDK 不重复实现。插件在等自己的响应时仍会处理入站
  `plugin.call/event/cancel`（可重入），所以 A 到 B 再到 A 会得到环错误而不是超时。
- **trace**：`trace_id` / `call_id` / `hop_count` 全链路传播（复用引擎既有 trace 上下文）；SDK 自动把当前的
  `trace_id` 附到出站调用上。日志事件 `plugin_comm` 可按 trace 串起每一跳。
- **不自动重试**：SDK 不做无限 retry，重试策略由插件自己决定。

### 8.5 路由策略 LOCAL / CORE / AUTO

| 策略 | 含义 | 引擎现状 |
| :--- | :--- | :--- |
| `auto`（默认） | 由引擎选路 | 一律 `core` |
| `core` | 强制经 Core Router | `core` |
| `local` | 同语言同进程直连（SDK 侧优化） | 引擎当前一插件一进程，**明确回落 `core`**（不假装走了 local） |

所以今天没有任何 SDK 能真正走 local；只有 Go 会校验 route 取值（非法值报 `INVALID_ARGUMENT`），
其它语言原样透传、由引擎归一。统计口径在 `PluginBus.snapshot()`（calls / denied / timeouts / cancels_sent /
cancels_acked / loop_aborted / events_delivered / by_error_code / by_route …），管理面经 `comm_snapshot()` 读。

### 8.6 权限与失败表现

- 调用：需 `plugin.call.<target>.<method>` / `plugin.call.<target>` / `plugin.call.*` / `plugin.call` 之一；
  广播：需 `plugin.emit`（或任一 `plugin.call` 通配）。**同语言直连同样要过闸门**。
- 目标必须声明能力，否则 `METHOD_NOT_FOUND`：接收调用要声明 `plugin.call`，接收事件要 `plugin.event`，
  接收取消要 `plugin.cancel`（写组名 `plugin` 一次声明三个）。
- 目标未启用 / 未加载 / 崩溃：分别得到 `PLUGIN_NOT_FOUND` / `PLUGIN_UNAVAILABLE`（禁用后实例仍留在路由表里，
  所以是 UNAVAILABLE 而不是 NOT_FOUND）。
- 载荷只能是语言无关类型：null / boolean / integer / number / string / array / object / bytes；二进制统一写成
  `{"$bytes": "<base64>", "size": N}`（<=4 MiB）；复杂对象用 Normalized DTO（message / user / group / file /
  image / segment / event / context / result，字段表在 `comm.DTO_FIELDS`）。

> 别把它和 action 层的旧机制混淆：`plugin_call` / `plugin_event` / `plugin_service` 是**动作**（权限 `plugin_admin`，
> 投递给目标的 `on_plugin_event` 钩子，3s 超时）。新代码请用 `plugin.call` / `plugin.emit`。

---

## 9. 错误处理与调试

### 9.1 两级错误，别混

| 级别 | 线格式 | 含义 |
| :--- | :--- | :--- |
| 协议级 | `{"id":N,"error":"未知方法: foo"}` | 这一行不是合法请求（未知方法/参数类型错/名字非法）；错误串截断到 800 字符 |
| 操作级 | `{"id":N,"result":{"ok":false,"error":"…"}}` | 方法认识但这次没成功（key 不存在、权限不足…） |
| 插件间 | `{"ok":false,"error":{"code","message","data"}}` | §8.3 的 12 个结构化码（是 object，不是字符串） |

### 9.2 插件自身出错时的行为

| 情况 | 引擎行为 |
| :--- | :--- |
| 钩子抛异常 | runner 捕获成 `{"__error__": "Type: msg"}`：事件被丢弃、动作清单为空、traceback 写 stderr；引擎记 `plugin_event_error`，**进程继续** |
| 动作执行异常 | 该动作返回 `{"ok":false,"error":"Type: msg"}`；引擎记 `plugin_action_error` |
| 事件处理超时 | 杀进程 -> `crashed`（`plugin_crash`）；该插件的后续事件不再投递，直到重新启用 |
| `initialize` 超时/协商失败 | 启用失败并回滚为禁用（`plugin_enable_failed`），拒绝启动而不是猜兼容 |
| stdout 累计超限 | 杀进程（`plugin_output_overflow`）——预算是**累计**的，长会话反复渲染页面也会耗尽 |
| 进程异常退出 | 标记 `crashed`，引擎继续运行（`plugin_crashed`）；stderr 尾 4KB 一并打进日志 |
| WebUI 页面失败 | 渲染错误块（中文文案，**没有 error code**）；静态/资源失败一律 404 |

### 9.3 日志去哪看

`logs/bot.log`（引擎与插件日志同一个文件）-> Web UI `GET /api/logs`；按 `event` 字段过滤：`plugin_lifecycle` /
`plugin_permission_denied` / `plugin_event_error` / `plugin_action_error` / `plugin_crash` / `plugin_truncated` / `plugin_comm`。
插件自己的日志：Python 用 `api.log(level, message)`，其它语言写 stderr（`ctx.log` / `ctx.logger` / `ctx.Logf`）。

### 9.4 常见报错与解法

| 症状 | 原因 | 解法 |
| :--- | :--- | :--- |
| 装上没反应，命令不触发 | `permissions` 漏 `read_message` | 补声明并重新批准；日志搜 `plugin_permission_denied` |
| 动作静默无效 | 用了 `"params"` 或 `send_group_msg` | 动作必须是 `{"type":"send_message","payload":{…}}`；`params` 会被静默丢弃 |
| 插件「没反应」但进程活着 | stdout 没 flush | 每写一行立即 flush |
| 跨插件调用报 `PERMISSION_DENIED` | 只批了 `plugin_admin`，或目标/方法不匹配 | 声明并批准 `plugin.call.<target>[.<method>]`（或 `plugin.call.*`） |
| 报 `METHOD_NOT_FOUND` 但方法确实存在 | 目标没声明 `plugin.call` 能力 | 目标 SDK 里声明 `plugin`（或 `plugin.call`）能力 |
| WebUI 页面能开但样式丢了 | 只批了 `webui.view`，静态路由要字面 `web_ui` | 同时批准 `web_ui`，或改用 `webui.asset` 动态资源 |

---

## 10. 测试你的插件

### 10.1 本机起一个最小引擎（不用 QQ）

```python
import asyncio, os, tempfile
from src.plugins.manager import PluginManager
from src.repositories.settings_repository import SettingsRepository

class Cfg:                                   # 引擎只用到这两个属性
    PLUGIN_DIR = os.path.join(tmp, "plugins")
    PLUGIN_PROTECTION = "normal"

async def main():
    root = tempfile.mkdtemp(prefix="my-plugin-test-")
    os.makedirs(Cfg.PLUGIN_DIR, exist_ok=True)
    repo = SettingsRepository(os.path.join(root, "settings.db"))      # 真 SQLite
    mgr = PluginManager(config=Cfg, repository=repo)
    mgr.discover()                                                    # 扫出插件（默认禁用）
    ok, why = await mgr.enable("my_first",
                               approved_permissions=["read_message", "send_message"])
    assert ok, why
    summary = await mgr.dispatch_event("message",
                                       {"text": "!hi", "group_id": 10001, "user_id": 20002})
    print(summary)                                                    # 每插件的动作结果摘要
    await mgr.shutdown()

asyncio.run(main())
```

### 10.2 可直接复用的夹具

| 夹具 | 位置 | 提供什么 |
| :--- | :--- | :--- |
| `Rig` / `RigCtx` | `tests/sdk/harness.py` | 临时插件目录 + 真 SQLite 仓库 + 真 `PluginManager` + `CapturingSender`；`deploy(lang, pid, declared=…)` 铺插件、`load(...)` 发现+启用、`raw(text)` 发消息取回包、`close()` 收尾、`plugin_processes()` 查残留进程 |
| `standalone_probe(lang, dir)` | `tests/sdk/harness.py` | 不经引擎直接握手（initialize -> health -> shutdown），失败时带回 stderr —— 诊断「插件自己能不能被拉起来」 |
| `stack` / `web` | `tests/webui/conftest.py` | 真 aiohttp `WebUIServer`（随机端口）+ 真仓库 + 真插件进程；`web` 是已登录的黑盒客户端（`get/post/multipart`、`element_text(html, id)`、`live_event_handlers(html)`） |
| `_write_plugin` / `_manager` / `_render` | `tests/test_plugin_webui_protocol.py` | 用真引擎渲染页面/取资源的最小写法（含路径穿越、manifest 注入的现成参数表） |

多语言契约测试：`tests/test_plugin_sdk_contract.py`（能力握手逐项相等）、`tests/test_plugin_webui_multilang.py`、
`tests/sdk/test_minimal_plugins.py`（Build / Load / Ping / Call / Error / Shutdown 全链路，缺工具链时打印 SKIP 原因）。

### 10.3 常用命令

```bash
pytest -q tests/sdk/                          # 五种语言最小插件真编译真跑
pytest -q tests/webui/                        # 真 HTTP + 真插件进程
pytest -q tests/test_plugin_manifest.py tests/test_plugin_permissions.py
pytest -q tests/test_plugin_comm_bus.py tests/test_plugin_comm_model.py   # 插件间通信
pytest -q -k multilang                        # 13 种语言的最小插件（§12.2）
```

调试单行协议（自己当引擎）—— 判断「插件是否活着」最快的方法：

```bash
printf '{"id":1,"method":"initialize","params":{"context":{"plugin_id":"my_first","plugin_dir":"%s","data_dir":"%s/data","protocol_version":"1"}}}\n' "$PWD" "$PWD" \
  | python3 -I src/plugins/runner/python_runner.py --dir . --entry plugin.py --plugin-id my_first
```

---

## 11. 打包 / 安装 / 升级 / 卸载

### 11.1 ZIP 结构

```text
my_plugin.zip
├── manifest.json          # 必须在根目录；或整体包一层目录（pkg/manifest.json，自动剥离）
├── plugin.py              # 入口（runtime=python / node / exec）
├── flowerie_sdk/          # SDK 模式需要自带
└── webui/ …               # 可选：插件页面
```

| 限制 | 值 |
| :--- | :--- |
| ZIP 大小 | <=**5 MiB** |
| 解压后总量 | <=**50 MiB**（Zip Bomb 防线） |
| 文件数 | <=**200** |
| 目录深度 | <=**16** |
| manifest.json | <=**64 KiB** |
| 入口文件 | python/node <=**1 MiB**；exec（编译产物）<=**32 MiB** |
| 符号链接 / 绝对路径 / `..` / 反斜杠 | 一律拒绝 |
| 注册表插件总数 | <=100（`PLUGIN_MAX_COUNT`） |

单文件 `.json` 上传只允许 `runtime=json`（纯声明式插件，无代码）。

### 11.2 安装来源

| 来源 | 入口 | 说明 |
| :--- | :--- | :--- |
| 本地目录 | `<PLUGIN_DIR>/<id>/manifest.json` | Web UI「插件」页「刷新扫描」即可发现；`refresh()` 会同步 manifest 变更并停掉旧运行时 |
| Web UI 上传 | `POST /panel/plugins/upload` | 文件类型/大小/内容均受控（§11.1） |
| URL | `POST /panel/plugins/install-url` | 只接受 `.zip` / `.json`；SSRF 双重防线（字面量 + DNS 解析结果）；**重定向一律拒绝**；Content-Length 预检 + 流式累计双重大小限制；15s 超时；Content-Type 白名单 |

三种方式安装后插件一律是 **`discovered`（禁用）**，必须由管理员启用并批准权限。

### 11.3 升级 / 卸载 / 数据目录

- **升级**：安装器拒绝覆盖已存在的 id（「请先卸载再安装」）。就地升级 = 替换目录里的文件后点「刷新扫描」：
  `refresh()` 检测到 `manifest_json` 变化会**停掉旧运行时**并把状态置回 `discovered`，需要重新启用并批准权限。
- **卸载**：`uninstall(plugin_id)` 停进程 -> 删注册行 -> **删除整个插件目录**（含 `data/`）。数据不保留，先备份。
- **数据目录**：`<PLUGIN_DIR>/<plugin_id>/data/`（`initialize` 的 `context["data_dir"]` 给出，自动创建）； 存储 KV 在 `data/storage/<key>.json`，配置覆盖层在 `data/config.json`，WebUI 上传文件在 `<PLUGIN_DIR>/<plugin_id>/webui/`。
- **禁用**：进程优雅关闭（`shutdown` 请求 -> 等待 -> 强杀），注册行与权限保留，重新启用即恢复。

---

## 12. FAQ 与附录

### 12.1 FAQ

- **Q：插件能 `import` 引擎内部模块吗？** 不能。插件是独立子进程（Python 用 `python3 -I` 隔离模式），能力只能经协议获得。
- **Q：manifest 里写了权限，为什么动作还是被拒？** 声明不等于批准：管理员启用时批的是「声明 ∩ 选择」，可只批一部分；改完 manifest 需重新启用才生效。
- **Q：长会话之后 WebUI 页面都报「插件未启动」？** stdout 预算是**累计**的（normal 256 KiB），插件返回 HTML 也计入，超限按设计杀进程（`plugin_output_overflow`）；减少每页 HTML 体积或提高保护级别（放宽到 1 MiB / 4 MiB）。
- **Q：`send_group_msg` 为什么无效？** 它不是插件动作；插件动作用 `send_message`（`payload.group_id` / `payload.message`），`send_group_msg` 只存在于适配器/发送器层的 OneBot 接口。
- **Q：`plugin.call` 超时会把对方进程杀掉吗？** 不会：插件间调用超时是业务失败（返回 `TIMEOUT` 并发 CANCEL），只有事件超时才杀进程。
- **Q：CANCEL 发出去了目标还在跑？** 目标未声明 `plugin.cancel` 时 CANCEL 不送达（如实返回 `cancelled:false`）；即使送达，**同步阻塞的 handler 也无法被中断**。
- **Q：一个插件能开多个实例吗（`plugin_a#instance1`）？** 协议与路由支持（指定实例或任意健康实例），但当前引擎一插件一进程，默认实例 id 是 `0`。
- **Q：怎么让别的插件调用我？** 用 `expose(method, handler)` 暴露方法并声明 `plugin.call`（或组名 `plugin`）能力；调用方需 `plugin.call.<你的 id>[.<method>]` 权限。

### 12.2 13 种语言最小插件（`tests/plugins/multilang/`）

**13 种语言**（全部 `runtime=exec`，CI 真编译真运行，缺工具链的用例打印 SKIP 原因而不误报）：

- **编译型**：C `c/`（`gcc -O2 -o plugin plugin.c` → entry `plugin`，标记 `c-ok`）· C++ `cpp/`（`g++ -O2 -std=c++17 -o plugin plugin.cpp` → `plugin`，`cpp-ok`）· Go `go/`（`go build -o plugin main.go` → `plugin`，`go-ok`）· Rust `rust/`（`rustc -O -o plugin main.rs` → `plugin`，`rust-ok`）。
- **JVM / .NET**：Java `java/`（`javac Plugin.java`，entry `run.sh`，`java-ok`）· Kotlin `kotlin/`（`kotlinc plugin.kt -include-runtime -d plugin.jar`，entry `run.sh`，`kotlin-ok`）· C# `csharp/`（`dotnet build -c Release --nologo -v quiet`，entry `run.sh`，`csharp-ok`）。
- **脚本型（无需构建）**：PHP `php/`（entry `plugin.php`，`php-ok`）· Lua `lua/`（`plugin.lua`，`lua-ok`）· Ruby `ruby/`（`plugin.rb`，`ruby-ok`）· Perl `perl/`（`plugin.pl`，`perl-ok`）· R `r/`（entry `plugin.R`，用 `Rscript` 执行，`r-ok`）。
- **TypeScript**：`typescript/`（`tsc plugin.ts --target es2019 --module commonjs`，entry `run.sh` → `node plugin.js`，`typescript-ok`）。

### 12.3 示例与夹具索引

- `examples/`：`python-plugin/`（完整 Python 插件）· `typescript-plugin/` `go-plugin/` `rust-plugin/` `java-plugin/`（四语言 SDK 示例）·
  `plugins/html_webui_demo/`（最小 WebUI）· `plugin-webui-test/`（三页规范插件）· `multilang-sdk/`（五语言最小插件）
- `tests/plugins/`：`minimal_plugin` `minimal_node_plugin` `minimal_exec_plugin` `sdk_plugin` `doc_example` `declarative_plugin`
  `webui_example` `rogue_plugin` `noisy_plugin`（运行时 / SDK / 文档 / 声明式 / DSL WebUI / 越权 / 噪声夹具）
- `tests/sdk/`（五语言契约）· `tests/webui/`（真 HTTP WebUI）· `tests/e2e/`（真浏览器 E2E）
- 分主题文档：`docs/plugin-communication.md` · `docs/plugin-webui.md` / `plugin-webui-protocol.md` · `docs/plugin-protocol.md` · `docs/api.md`