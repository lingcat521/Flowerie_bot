# Plugin SDK（多语言）

> 插件协议**语言无关**：[plugin-protocol.md](plugin-protocol.md)（线格式 / 方法集 / 错误模型 / 版本协商）。
> 本文是**通用规则的唯一出处**——五种语言共同的语义只写在这里，单语言文档只写「本语言特有的写法」并链回本文。
> 源码：`sdk/typescript/flowerie_sdk.ts` · `sdk/go/flowerie/plugin.go` · `sdk/rust/src/lib.rs` · `sdk/java/src/main/java/dev/flowerie/sdk/` · Python 的运行时对端 `src/plugins/runner/python_runner.py`；逐能力状态与证据：[plugin-sdk-capabilities.md](plugin-sdk-capabilities.md)。

## 0. 选语言

| 语言 | 单语言文档 | 本语言特有之处 | 可跑示例（CI 实测） |
| :--- | :--- | :--- | :--- |
| Python | [sdk.md](sdk.md) | `flowerie_sdk` 手册（Event / BotMessage / Matcher / 上下文）；经典模式仍是 `api.*` | `examples/multilang-sdk/python/` |
| TypeScript / Node | [plugin-sdk-typescript.md](plugin-sdk-typescript.md) | 零 npm 依赖；node ≥ 22.6 直跑 `.ts`，否则 `tsc` + SDK 自带 `shims/node.d.ts` | `examples/multilang-sdk/typescript/` |
| Go | [plugin-sdk-go.md](plugin-sdk-go.md) | 标准库；`go build` 用临时模块 + `replace` 指向 SDK，`GOPROXY=off` | `examples/multilang-sdk/go/` |
| Rust | [plugin-sdk-rust.md](plugin-sdk-rust.md) | `std` + 自带极简 JSON（`sdk/rust/src/json.rs`）；`rustc` 直编，不用 cargo | `examples/multilang-sdk/rust/` |
| Java | [plugin-sdk-java.md](plugin-sdk-java.md) | 只用 JDK；`javac` 编「SDK + 插件」到 `.build/classes` | `examples/multilang-sdk/java/` |
| 其它任意语言 | [plugin-developer-guide.md §31](plugin-developer-guide.md) | 不需要 SDK：直接说协议（JSON-Lines） | 13 种语言夹具 |

## 1. 安装与引入

- 五种 SDK 都**零第三方依赖**（只用各自语言的标准库）：不为插件引入任何运行时或代码生成，「任何语言只要能说 JSON-Lines 就能当插件」是设计底线。
- SDK 就是**源码**：仓库内路径见上表；插件目录被拷到仓库外时，用该语言 `build.sh` 认的环境变量指向（如 `FLOWERIE_SDK_GO` / `FLOWERIE_SDK_RUST` / `FLOWERIE_JAVA_SDK_DIR`）；引入方式、工具链版本要求、`run.sh` 写法见各语言文档 §1 与 §8。

**manifest.json 必填 7 个字段**（校验在加载前，`src/plugins/manifest.py`）：

| 字段 | 约束 |
| :--- | :--- |
| `id` | 小写字母开头，`[a-z0-9_-]`，≤32 字符（**不能用点**）|
| `name` / `version` / `api_version` | 1~64 字符 / `x.y.z` / 只支持 `"1"` |
| `runtime` | `python` \| `node` \| `json` \| `exec`（五种语言里只有 Python 用 `python`，其余都是 `exec`）|
| `entry` | 相对路径文件名（禁止绝对路径 / `..` / 反斜杠）；`exec` 下是**可直接执行的文件或脚本** |
| `permissions` | 权限键列表，见 §5；`plugin.call.*` / `plugin.emit` / `web_ui` 属于这里 |

> 可选：`author` / `description` / `config` / `web_ui`（§6）；`platform` / `arch` **仅 `runtime=exec`** 可声明。
> Manifest 全字段与打包/安装见 [plugin-developer-guide.md §2](plugin-developer-guide.md)。

## 2. 最小插件（可直接复制）

每份单语言文档的 §2 都有一份**完整可复制**的最小插件（入口源码 + manifest + 构建运行命令），与 `examples/multilang-sdk/<lang>/` 同源，并被 `tests/sdk/test_minimal_plugins.py` 真编译、真进程拉起。

```text
minimal_<lang>/          # manifest.json（见下，把 id / name / entry 换成你的）
├── run.sh              # runtime=exec 的入口（Python 插件不需要；见 §8）
├── <入口源码>           # main.go / src/index.ts / src/main.rs / src/MinimalPlugin.java / plugin.py
└── webui/static/       # 可选：WebUI 静态资源（§6）
```

```json
{ "id": "minimal_ts", "name": "Minimal TypeScript Plugin", "version": "1.0.0",
  "runtime": "exec", "entry": "run.sh", "api_version": "1",
  "permissions": ["read_message", "send_message", "web_ui"],
  "web_ui": {"static": "static", "entry": "webui_page",
             "pages": [{"id": "index", "title": "总览", "render": "plugin"}]} }
```

最省事的一份完整插件（`runtime=python`，引擎用内置 runner 拉起，**不需要构建、不需要 SDK 副本**）：
```python
# plugins/minimal_py/plugin.py
def on_message(event, api=None):
    if str(event.get("text") or "") == "ping":
        return {"type": "send_message", "payload": {"group_id": event.get("group_id"), "message": "pong"}}
```
（manifest 用上面那份，把 `runtime` 改成 `"python"`、`entry` 改成 `"plugin.py"`；其它语言的完整版见各自文档 §2。）

**协议契约**（细节见 [plugin-protocol.md §4](plugin-protocol.md)）：`initialize`（握手 + 声明能力）、`event`（收事件，**返回动作**）、`health`、`shutdown`；可选 14 项在 `initialize` 的 `capabilities` 里声明，**未声明引擎绝不调用**。

## 3. 事件注册

| 事件/钩子 | Python | TypeScript | Go | Rust | Java |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 消息 | `@command/@keyword/...` 或 `on_message` | `onMessage(fn)` | `OnMessage(fn)` | `on_message(f)` | `onMessage(fn)` |
| 命令 | `@command("x")` | `onCommand(fn)` | `OnCommand(fn)` | `on_command(f)` | `onCommand(fn)` |
| 通知 / 请求 | `@bot.listen("notice")` | `onNotice` / `onRequest` | `OnNotice` / `OnRequest` | `on_notice` / `on_request` | `onNotice` / `onRequest` |
| 生命周期事件 / 定时 | `on_lifecycle` / `@bot.schedule(...)` | `onLifecycle` / `onSchedule` | `OnLifecycle` / `OnSchedule` | `on_lifecycle` / `on_schedule` | `onLifecycle` / `onSchedule` |
| 启动 / 关闭 | `on_startup` / `on_shutdown` | `onStartup` / `onShutdown` | `OnStartup` / `OnShutdown` | `on_startup` / `on_shutdown` | `onStartup` / `onShutdown` |
| 心跳 | `health_check` | `onHealth` | `OnHealth` | `on_health` | `onHealth` |
| 任意命名事件 | `on_event(name, f)` | `on(name, fn)` | `On(name, fn)` | `on_event(name, f)` | `onEvent(name, fn)` |
| 控制面 hook（WebUI 数据）| `def status(...)` | `registerHook(name, fn)` | `RegisterHook(name, fn)` | `register_hook(name, f)` | `registerHook(name, fn)` |

- 回调**返回值就是动作**：`None`/`nil`/`null` = 无动作，对象 = 单个动作，列表 = 多个动作（引擎逐个执行）。
- Python 的 `FlowerieBot` 用装饰器收集 matcher 上报主进程；**注册了 matcher 的插件只收到匹配事件**，要全量 notice 就别在该插件注册 matcher（拆插件）——见 [sdk.md §2](sdk.md)。

## 4. API 表（语义一致，写法各随语言习惯）

| 能力 | Python | TypeScript | Go | Rust | Java |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 动作（副作用出口）| `api.send_message({...})` | `ctx.action(type, params)` | `ctx.Action(type, params)` | `ctx.action(type, &json)` | `ctx.action(type, map)` |
| 存储 / 配置 | `api.storage_get/set/delete/list` · `api.config_get/config_set` | `ctx.storageGet/Set/Delete/List` · `ctx.configGet/configSet` | `ctx.StorageGet/Set/Delete/List` · `ctx.ConfigGet/ConfigSet` | `ctx.storage_get/set/delete/list` · `ctx.config_get/config_set` | `ctx.storageGet/Set/Delete/List` · `ctx.configGet/configSet` |
| 权限查询 | `api.permission_check` | `ctx.permissionCheck` | `ctx.PermissionCheck` | `ctx.permission_check` | `ctx.permissionCheck` |
| 上下文 | `api.context_info` | `ctx.refreshContext` | `ctx.Info` | `ctx.info` | `ctx.info` |
| 日志（stderr）| `api.log(level, msg)` | `ctx.logger.info/warn/error` | `ctx.Logf(fmt, ...)` | `ctx.log(&str)` | `ctx.log(str)` |
| WebUI 三通道 | `api.webui_page/action/asset` | `plugin.webui.page/action/asset` | `plugin.WebUI().Page/Action/Asset` | `plugin.webui().page/action/asset` | `plugin.webUI().page/action/asset` |
| 插件间调用 | `api.plugin.call/emit/on/expose/cancel` | 同左（`plugin.*`）| `p.Call/Emit/On/Expose/Cancel` | `p.call/emit/on/expose/cancel` | `p.call/emit/on/expose/cancel` |

**能力对齐（parity）**：五种语言声明**完全相同**的可选方法集合（14 项：`context.get` · `config.get` · `config.set` · `permission.check` · `storage.get/set/delete/list` · `webui.page/action/asset` · `plugin.call/event/cancel`），由 `tests/test_plugin_sdk_contract.py` 的**相等断言**钉住；
Python 的 `PluginApi` 另有 160+ 个动作包装方法（`send_message` / `group_ban` / `mcp_call` …），
那是**语言习语封装**，协议层没有差别：其它语言写 `ctx.action("send_message", {...})` 效果完全相同。

## 5. 存储、配置与权限

- **存储**：只落该插件自己的 `data/` 目录；键必须匹配 `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`
  （无斜杠、无隐藏段、无 `..`），≤200 键、单值 ≤64 KiB；跨插件必须走 §7 的 DTO，不能读写别人的目录。
- **配置**：`config.get` 读的是**操作员配置（只读）+ 插件覆盖层**，操作员的值优先；`config.set` 只写
  插件自己的覆盖层（≤64 键、单值 ≤8 KiB），写不进全局配置。
- **权限**：插件在 `manifest.permissions` 声明 → 管理员在 Web UI 批准（`read_message` 收事件、`send_message` 回复是绝大多数插件的全部所需）；`permission.check` 是**只读**查询，插件无法提权，引擎在动作出口强制执行。
> 权限全表 / 保护级别 / 资源上限见 [plugin-developer-guide.md §9](plugin-developer-guide.md) 与
> [plugin-protocol.md §8](plugin-protocol.md)。

## 6. WebUI（Plugin WebUI Protocol）

HTTP / 静态资源 / 页面渲染都由引擎负责，插件只在 stdio 上回三个方法（声明能力组 `webui`）：

| 方法 | 引擎发 | 插件回 |
| :--- | :--- | :--- |
| `webui.page` | `{"page":{id,title}, "context":{...}}` | `{"html": "...", "vars": {...}}` |
| `webui.action` | 另带 `action` 与 `form` | 同上，另可带 `config_set` / `storage_set` |
| `webui.asset` | `{"path": "theme.css"}` | `{"content_type": "...", "body": "..."}`（二进制 `base64`）|

页面两种形态：磁盘文件页（`pages[].file`，首选）与插件渲染页（`pages[].render = "plugin"`）；
返回对象只透传白名单字段（`html/vars/context/message/content_type/body/base64/config_set/storage_set`）。
注册写法见各语言文档 §6；协议与安全边界见 [plugin-webui-protocol.md](plugin-webui-protocol.md)。

## 7. 插件间通信

| 能力 | Python | TypeScript | Go | Rust | Java |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 调用 | `api.plugin.call(target, method, params, timeout, route)` | `plugin.call(target, method, params, opts)` | `p.Call(target, method, params, opts...)` | `p.call(target, method, params, opts)?` | `p.call(target, method, params, opts)` |
| 广播 / 订阅 / 暴露方法 | `plugin.emit` / `plugin.on` / `plugin.expose(method, handler)` | `emit` / `on` / `expose` | `Emit` / `On` / `Expose` | `emit` / `on` / `expose` | `emit` / `on` / `expose` |
| 取消在途调用 | `plugin.cancel(request_id, reason)` | `cancel(requestId, reason)` | `Cancel(requestID, reason)` | `cancel(request_id, reason)?` | `cancel(requestId, reason)` |

- 目标 `plugin_a`（任意健康实例）或 `plugin_a#instance1`（指定实例）；跨语言**必须经 Core Router**，
  没有任何绕过通道；`route` 策略 `auto|core|local` 默认 `auto`（当前引擎一个插件一个子进程，实际总是 core）。
- 失败一律是结构化错误 `{code, message, data}`（12 个错误码之一），SDK 映射成本语言异常 / error / Result；
  `trace_id` / `hop_count` 自动传播；**不自动重试**。
- 权限：`plugin.call.<target>[.<method>]` / `plugin.emit`，由引擎在路由层强制。
> 请求/响应模型、五类消息、环保护见 [plugin-communication.md](plugin-communication.md)。

## 8. 构建与运行

| runtime | 谁启动插件 | entry 是什么 | 构建 |
| :--- | :--- | :--- | :--- |
| `python` | 引擎用 `python3 -I src/plugins/runner/python_runner.py --dir <插件目录>` | `plugin.py` | 不需要构建 |
| `node` | 引擎内建 node runner（能力 **PARTIAL**，可选方法尚未补齐）| `.js` | 不需要构建 |
| `exec` | 引擎直接 `exec` entry（TS / Go / Rust / Java 全部走这条）| **可执行脚本** `run.sh` | 各语言 `build.sh` 先编译，`run.sh` 只 exec 产物 |

- `run.sh` 的纪律：产物不存在就**非零退出并说明原因**，绝不隐式编译、绝不静默成功。
- 缺工具链时的行为：`build.sh` 报错退出，测试**skip 并打印原因**（不是 pass）；CI 装了 node/go/rustc/javac，五种语言全跑。
- 单语言命令（build / run / 环境变量 / 产物路径）见各语言文档 §8；任意语言的入口包装见 [plugin-developer-guide.md §31](plugin-developer-guide.md)。

## 9. 常见错误

| 症状 | 原因 | 处理 |
| :--- | :--- | :--- |
| 插件「没反应」/ 非法行被跳过 | stdout 混入日志、写完没 flush，或一行里放了多行 JSON / 裸换行 | 日志一律 stderr（§4），每行一个 JSON（UTF-8、`\n` 结尾）且立即 flush |
| 请求超时 / 对不上 | 自己造了 `id`，或没把 `id` 原样带回 | `id` 原样回传；插件主动请求从 1000000 起 |
| 可选方法是「未实现」 | `initialize` 没声明该能力 | 声明与实现必须一致（引擎按 `supports()` 门控）|
| 插件启动被拒 | `api_version` 不是 `"1"`、entry 是绝对路径 / 含 `..`、id 带点或大写 | 按 §1 的 manifest 约束改 |
| 存储报错 / 配置写了读不到 | 键含斜杠等非法字符、超 200 键 / 64 KiB；或 `config.set` 只写插件覆盖层（操作员值优先）| 键用 `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`；想在 UI 改的项放 manifest `config` |
| 收不到事件 | `read_message` 未批准；或插件注册了 matcher 只收匹配事件 | Web UI 批准权限；需要全量事件就拆插件 |
| `build.sh` 失败 | 缺 go/rustc/javac/node，或找不到 SDK 源码 | 装工具链；用 `FLOWERIE_SDK_*` / `FLOWERIE_REPO_ROOT` 指路 |
| WebUI 页面空白 / 字段丢失 | 返回对象里有白名单外的字段（被丢弃）或 `render` 与 `file` 同时写 | 只用 §6 的字段；一个页面只能有一个渲染者 |

## 10. 证据与自查

```bash
python3 -m pytest tests/sdk/ -q -rs                    # 最小插件：真 build + 真进程（缺工具链则 skip 并打印原因）
python3 -m pytest tests/test_plugin_sdk_contract.py -q -rs   # 协议向量 × 五语言（CI 全绿：node/go/rustc/javac 都在）
python3 -m pytest tests/test_plugin_webui_multilang.py tests/sdk/test_minimal_paths.py -q -rs  # WebUI 三通道 × 五语言 + 跨语言 plugin.call 链路
```

新语言接入清单：① 实现协议 → ② 在 `examples/multilang-sdk/<lang>/` 放能跑通协议向量的最小插件（`ping → pong` + `status` hook）→ ③ 在 `tests/sdk/harness.py` 的语言表与 `tests/test_plugin_sdk_contract.py` 的 `LANGUAGES` 登记 → ④ 全绿后按**实际证据**更新 [plugin-sdk-capabilities.md](plugin-sdk-capabilities.md)。
