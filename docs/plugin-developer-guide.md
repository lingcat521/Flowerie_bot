# 插件开发者指南（Plugin Developer Guide·第二层·完整参考）

> Flowerie Plugin API **v1**（版本 `2.2.2222`）· **新手请先看 [第一层 quick-start.md](quick-start.md)**（10 分钟上手）
>
> 本文档是**完整参考**：Manifest 规则 / Python·Node·JSON / 任意语言 exec（§4.5、§31）/ 生命周期 /
> Event·Action·Permission API / 超时 / 资源限制 / 安全边界 / 打包 / Web UI 安装 / API Version。
> 本手册尽力做到**不需要看源码**——所有 API、参数、示例、权限、错误、限制都在文档里。
>
> 五份插件文档的分工：[quick-start](quick-start.md) 上手 → **本文（经典 Plugin API 完整参考）** →
> [sdk.md](sdk.md)（`flowerie_sdk` 模式 API 手册）→ [plugin-webui.md](plugin-webui.md)（插件自带管理页）→
> [api.md](api.md)（方法 × 权限速查总表）。

---

## 0. 60 秒上手（最短路径）

```python
# plugin.py —— 你的第一个插件（完整可运行）
from flowerie_sdk import FlowerieBot, command

bot = FlowerieBot()

@command("hi")                      # 群友发 !hi 自动回复
async def hello(event):
    await event.reply("你好呀")      # 一行回复

@command("add")
async def add(event):
    a, b = event.args[:2]
    await event.reply(str(int(a) + int(b)))   # !add 1 2 → 3

def on_startup(context, api=None):
    bot.attach(api)                 # 绑定能力通道
    bot.register()                  # 上报匹配器（一次）

def on_message(event, api=None):
    return bot.route(event)         # 有匹配返回 handler 结果，无匹配 None

def on_schedule(event, api=None):
    return bot.route_schedule(event)
```

**4 步上线**：
1. 新建目录 `my_plugin/`，放 `plugin.py`（上）与 `manifest.json`（见 §2）
2. 一起放进 `plugins/` 目录（或 Web UI 插件页上传 zip）
3. 重启 → Web UI「插件」页可见、保护级别默认 Safe
4. 群里发 `!hi` —— 完成。

更多示例与完整参考（每个 API 的签名/参数/返回/权限）见下文；SDK 模式全量文档见 [sdk.md](sdk.md)。

---

## 0.5 核心概念（5 分钟，先看这段再写代码）

> 下面三个点是最「反直觉」、最容易卡住新人的地方——**记牢它们，写插件就是拼模板**。

**① 插件是独立进程，不是 import 框架。**
插件运行在**独立子进程**里（`python3 -I`/node），通过 **stdin/stdout JSON 通信**，`import Flowerie` 内部模块**不行**也不允许。
→ 你的插件自成一个世界：只有 `flowerie_sdk/`（自带副本）+ 主进程通过 `api` 递给你的能力。
→ 心法：**写"剧本"，不是写"库"**——你不会被 import 进主进程，主进程只会用钩子调用你。

**② 「动作（Action）」是命令，不是函数调用。**
插件**不直接执行副作用**，而是**发出动作指令**（`{"type": "send_message", "payload": {...}}` 或 `api.send_message(...)`），由主进程**做权限检查后**执行。
→ 这就是为什么「发送私聊」是 `send_private_message` 而不是 `send_message`：**事件钩子**（`on_message`/`on_startup`）与**动作指令**（send_xxx）是两套词汇表。
→ SDK 模式下 `await event.reply(...)` 只是动作的**语法糖**——底层仍是动作。
→ 好处：**插件永远无法绕过权限**。

**③ 权限声明是唯一闸门，未声明 = 动作静默失败。**
`manifest.json` 里 `permissions` 未声明的动作，主进程**直接拒绝（写日志，页面不弹错）**——机器人"毫无反应"。
→ **先声明权限 → 再启用插件**；`send_message`/`read_message` 是最容易漏的两个。
→ 排查口诀：没反应先查**清单**（manifest）+ **日志**（关键词 `denied` / `permission`）。

---

## 1. Plugin API 概览

插件是**独立子进程**（Python / Node / 任意语言 exec）或**进程内声明式规则**（JSON），通过统一协议与
Flowerie 通信。插件**不能** `import Flowerie` 内部模块（进程隔离 + Python `-I` 隔离模式），
一切能力都来自本 API：

```
Flowerie Plugin Manager
        │  (stdin/stdout JSON-Lines 协议)
        ├── Python 插件进程（python3 -I python_runner.py --dir <dir> --entry plugin.py）
        ├── Node 插件进程（node node_runner.js --dir <dir> --entry index.js）
        └── JSON 声明式插件（进程内规则匹配，无代码执行）
```

**核心原则**：插件返回「动作（action）」而不是直接执行副作用；动作由 Flowerie 的
PermissionManager 检查后执行。插件永远无法绕过权限。

## 2. Plugin Manifest

`manifest.json` 是每个插件的唯一元数据来源（严格 schema 校验，未知字段拒绝）：

```json
{
  "id": "example_plugin",
  "name": "Example Plugin",
  "version": "1.0.0",
  "author": "author",
  "description": "Example",
  "runtime": "python",
  "entry": "plugin.py",
  "api_version": "1",
  "permissions": ["read_message", "send_message"],
  "config": {}
}
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `id` | ✅ | 小写字母开头，`[a-z0-9_-]`，≤32 字符 |
| `name` | ✅ | 1~64 字符 |
| `version` | ✅ | `x.y.z`（semver 三字段） |
| `runtime` | ✅ | `python` / `node` / `json` / `exec`（任意语言，见 §4.5） |
| `entry` | ✅ | 相对路径文件名（禁止绝对路径/`..`/反斜杠）；`json` 可留空；`exec` 为可执行文件 |
| `platform` / `arch` | ❌ | 仅 `runtime=exec` 允许：多平台分包时声明宿主（见 §4.5） |
| `api_version` | ✅ | 仅支持 `"1"` |
| `permissions` | ✅ | 数组，见 §9；未知键会被拒绝 |
| `author` / `description` / `config` | ❌ | 元数据（config 为 JSON 对象，≤16KB） |
| `declarations` | ❌ | 仅 `runtime=json` 允许，见 §5 |

Node 插件示例：

```json
{ "runtime": "node", "entry": "index.js" }
```

## 3. Python 插件

目录结构：

```
my_plugin/
├── manifest.json
└── plugin.py
```

`plugin.py` 导出钩子函数（全部可省略，只写用到的）：

```python
def on_startup(context, api):
    """插件被加载时调用一次。return None。"""

def on_message(event, api):
    """收到消息事件（权限 read_message 已批准时投递）。
    返回 None | 单个 action dict | action list。"""

def on_command(event, api):
    """(预留) 命令事件。v1 不主动投递。"""

def on_group_message(event, api):
    """群消息事件（与 on_message 二选一实现；v1 的 message 事件投递给 on_message）。"""

def health_check(context=None, api=None):
    """健康检查；返回 None=健康。"""

def on_shutdown(context, api):
    """插件进程被优雅关闭时调用。"""
```

`event` 为 dict（最小字段集）：

```python
{"event": "message", "plugin_id": "...", "group_id": 123, "user_id": 456,
 "message_id": 789, "time": 1700000000, "text": "用户发言文本"}
```

`api` 为同步辅助对象（每个方法发送动作请求并等待响应，见 §7）。

最小示例（等价于仓库 `tests/plugins/minimal_plugin/`）：

```python
def on_message(event, api=None):
    return {"type": "test", "message": "plugin-ok"}
```

## 4. Node.js 插件

目录结构：

```
my_node_plugin/
├── manifest.json
├── package.json     # {"name": "...", "version": "1.0.0", "main": "index.js"}
└── index.js
```

`index.js` 导出与 Python 相同的钩子（支持 `async`）：

```js
'use strict';
exports.on_startup = async function (context, api) {};
exports.on_message = async function (event, api) {
  // 返回 action 或 action 数组（Promise 也支持）
  return { type: 'test', message: 'node-ok', event: event.event };
};
exports.on_shutdown = async function (context, api) {};
```

运行方式由 Flowerie 统一处理（`node node_runner.js --dir <dir> --entry index.js`），
插件只需要导出钩子。

## 4.5 任意语言插件（exec runtime）

`runtime=exec`：**entry 就是进程本身** —— 编译产物（Go / Rust / C / C++ / C# AOT）或带
shebang 的可执行脚本（PHP / Ruby / shell / Java 包装脚本）。Flowerie **不经 shell、不假设任何语言**：
只要程序会说同一套 JSON-Lines 协议，它就是合法插件。

```
my_anylang_plugin/
├── manifest.json            # { "runtime": "exec", "entry": "bin/plugin-linux-x64" }
└── bin/
    └── plugin-linux-x64     # 可执行文件（安装时自动补 chmod +x；Windows 用 .exe）
```

### 协议（Plugin API v1 · stdin/stdout JSON-Lines）

| 方向 | 报文 |
| --- | --- |
| 收（主进程 → 插件） | `{"id": 1, "method": "initialize", "params": {"context": {...}}}` |
| 收 | `{"id": 2, "method": "event", "params": {"event": "message", "payload": {...}}}` |
| 收 | `{"id": 3, "method": "health", "params": {}}` / `{"id": 4, "method": "shutdown", "params": {}}` |
| 回（插件 → 主进程） | `{"id": 1, "result": {"ok": true, "api_version": "1"}}` |
| 回（事件结果） | `{"id": 2, "result": {"actions": [{"type": "...", "payload": {...}}]}}` |
| 插件主动调能力 | `{"id": 1000001, "method": "action", "params": {"action": "send_message", "payload": {...}}}` |

约定：

- **一行一个 JSON**（换行结尾）、UTF-8；解析失败的行会被忽略
- 插件发起的 action 请求 id 请用 **≥ 1000000**（与主进程请求 id 隔离，互不相撞）
- `initialize` 必须在启动超时内返回；事件超时 / 输出字节超限会**杀掉进程**（阈值由保护级别决定）
- action 的返回由主进程回写：`{"id": 1000001, "result": {"ok": true, ...}}`

### 最小可跑示例（POSIX shell；仓库里有同名测试夹具）

```sh
#!/bin/sh
while IFS= read -r line; do
  id=$(printf '%s' "$line" | sed -n 's/.*"id": *\([0-9][0-9]*\).*/\1/p')
  method=$(printf '%s' "$line" | sed -n 's/.*"method": *"\([a-zA-Z_]*\)".*/\1/p')
  [ -z "$id" ] && continue
  case "$method" in
    initialize) printf '{"id":%s,"result":{"ok":true,"api_version":"1"}}\n' "$id" ;;
    event)      printf '{"id":%s,"result":{"actions":[]}}\n' "$id" ;;
    health)     printf '{"id":%s,"result":{"ok":true}}\n' "$id" ;;
    shutdown)   printf '{"id":%s,"result":{"ok":true}}\n' "$id" ;;
  esac
done
```

> 完整用例见 `tests/plugins/minimal_exec_plugin/` —— 测试会真的把它当子进程启动并跑完整协议。

### 多平台分包（`platform` / `arch`）

编译型语言按平台分发时，**每个包只声明自己能跑的宿主**，不匹配会被拒绝启用：

| 字段 | 可选值 | 说明 |
| --- | --- | --- |
| `platform` | `any`（默认）/ `linux` / `windows` / `darwin` / `android` | 宿主平台（Termux 上是 `android`） |
| `arch` | `any`（默认）/ `x64` / `arm64` / `x86` | 宿主架构 |

```json
{ "runtime": "exec", "entry": "bin/plugin-linux-x64", "platform": "linux", "arch": "x64" }
```

- 两个字段**仅 `exec` 允许声明**（其余 runtime 声明即拒绝，避免歧义）
- 不匹配时启用会被拒绝，并说明具体原因（如「该插件包面向 windows，当前宿主为 android」）

### 注意事项

1. **执行位**：ZIP 安装与运行时各补一次 `chmod +x`（Windows 无此概念，入口请用 `.exe`）
2. **不经 shell**：`entry` 被直接执行，不做 shell 展开，因此 `.bat`/`.cmd` 不会被特殊处理
3. **入口大小**：脚本类上限 1MB，`exec` 放宽到 32MB（编译产物）；解压后总量仍受 50MB 上限
4. **权限照旧**：任何语言都必须经 PermissionManager 批准，插件进程无法绕过
5. **环境变量白名单**：只透传 `PATH/HOME/LANG/TMPDIR/TEMP/TMP/NODE_PATH/LD_LIBRARY_PATH`，
   不注入任何 API Key（需要网络的插件用 `http_request` 权限走主进程代理）
6. **各语言落地**：Go/Rust/C/C++ 直接编译出二进制；PHP/Ruby 首行加 `#!/usr/bin/env php` /
   `#!/usr/bin/env ruby`；Java/C# 用几行包装脚本（`#!/bin/sh` + `exec java -jar app.jar "$@"`）

## 5. JSON 声明式插件（Declarative Plugin）


`runtime=json`：**无代码执行**。声明式规则在进程内做模板匹配与动作转发，
行为受同样的权限检查约束：

```json
{
  "id": "greet_plugin",
  "name": "Greet",
  "version": "1.0.0",
  "runtime": "json",
  "entry": "",
  "api_version": "1",
  "permissions": ["read_message", "send_message"],
  "declarations": [
    {
      "event": "message",
      "match": {"text_prefix": "hello"},
      "actions": [
        {"type": "send_message",
         "payload": {"group_id": "${group_id}", "message": "你好 ${user_id}"}}
      ]
    }
  ]
}
```

- `match` 支持：`text_contains` / `text_prefix`（字符串）、`user_id` / `group_id`（整数）
- `payload` 支持模板字段：`${group_id}` `${user_id}` `${text}` `${message}` `${message_name}`
- 每条规则最多 4 个 action；插件最多 64 条规则；**没有 eval/exec，没有任意表达式**

## 6. 生命周期

```
安装（上传 ZIP / URL / 目录扫描）  →  状态 discovered（默认禁用）
管理员「启用 + 批准权限」          →  启动子进程 initialize → running
事件到达（read_message 已批准）    →  on_message(event) → actions → 权限检查 → 执行
管理员「禁用」                     →  shutdown → 进程退出 → disabled
进程崩溃 / 执行超时                →  标记 crashed（Flowerie 继续运行；管理员可重新启用）
卸载                               →  停止进程 + 删除插件目录 + 清除注册
```

发现 ≠ 执行：放入插件目录（`PLUGIN_DIR`，默认 `./plugins`）的插件在刷新扫描后
注册为**禁用**；必须由管理员明确启用。

## 7. Event API

| 事件 | 投递条件 | 钩子 |
| --- | --- | --- |
| `message`（群消息） | `read_message` 已批准 | `on_message(event, api)` |
| `notice`（群上传/戳戳等） | `read_message` 已批准 | （v1 无专用钩子，事件不投递） |
| `command` | — | 预留，v1 不投递 |

事件负载只包含最小字段（group_id / user_id / message_id / time / text ≤2000 字符），
不透传原始段数组。

## 8. Action API

钩子返回值 = `{"type": <action>, "payload": {...}}` 或 `[{...}, ...]`；
插件也可在钩子内调用 `api.<method>(payload)` 同步执行并拿到结果。

| action / api 方法 | 所需权限 | payload | 返回 |
| --- | --- | --- | --- |
| `send_message` / `api.send_message` | `send_message` | `{group_id, message}` | `{ok, group_id}` |
| `send_private_message` / `api.send_private_message` | `send_message` | `{user_id, message}` | `{ok, user_id}` |
| `get_group` / `api.get_group` | `read_group_info` | `{group_id}` | `{ok, group_id, info}` |
| `get_user` / `api.get_user` | `read_user_info` | `{user_id}` | `{ok, user_id, info}` |
| `get_memory` / `api.get_memory` | `read_memory` | `{user_id, group_id}` | `{ok, memory}` |
| `write_memory` / `api.write_memory` | `write_memory` | `{user_id, group_id, content}` | `{ok}` |
| `http_request` / `api.http_request` | `http_request` | `{url, method?, headers?, body?}` | `{ok, status, body}` |
| `file_read` | `filesystem_read` | `{path}`（插件目录内相对路径） | `{ok, content}` |
| `file_write` | `filesystem_write` | `{path, data}` | `{ok, bytes}` |
| `log` / `api.log(level, message)` | 无（内建安全） | `{level, message}` | `{ok}` |
| `test` | 无（内建安全） | 任意 | `{ok}` |

未实现（保留定义，批准权限也会拒绝）：`execute_process`、`webhook`。

### http_request 限制

- 仅 `GET` / `POST`；仅 `http://` / `https://`
- SSRF 防线：拒绝回环/私网/链路本地/组播/保留地址、`.local` 主机、userinfo、
  DNS 解析结果命中内网（防 rebinding）；**不跟随重定向**
- 请求体 ≤256KB；响应体 ≤256KB（超限截断返回）；超时 10s
- `Host` / `Authorization` / `Cookie` 头一律剥离

## 9. Permission API

权限（manifest 声明 → 管理员启用时批准，可批准子集；插件默认 0 权限）：

| 权限 | 对应能力 |
| --- | --- |
| `send_message` | 发送群/私聊消息 |
| `read_message` | 接收消息事件 |
| `read_group_info` | 读取群信息 |
| `read_user_info` | 读取用户信息 |
| `read_memory` | 读取记忆 |
| `write_memory` | 写入记忆 |
| `http_request` | 受限 HTTP 请求 |
| `filesystem_read` | 插件目录内读文件 |
| `filesystem_write` | 插件目录内写文件 |
| `execute_process` | **保留**：v1 无实现 |
| `webhook` | **保留**：v1 无实现 |

运行时强制：任何 action 在真正执行前都会过 PermissionManager；
未批准 → 拒绝并记录 `plugin_permission_denied` 日志。**关闭插件保护也不会绕过**。

## 10. 配置 API

插件自己的配置写在 `manifest.json` 的 `config` 字段（≤16KB JSON 对象），
通过 `context["config"]` 在 `on_startup` 时读取：

```python
def on_startup(context, api):
    default_msg = context["config"].get("message", "hi")
```

v1 不提供运行时修改插件配置的接口（改动 manifest 后重新扫描/启用）。

## 11. Memory API

见 §8 `get_memory` / `write_memory`。写入内容会经过与模型写入相同的记忆安全闸门
`validate_memory_content`（长度 ≤100 字、不含 QQ 号、不含记忆指令句式），
被拒绝时返回 `{ok: False, error: "记忆内容被安全策略拒绝（防注入）"}`。

## 12. HTTP API

插件调用外部服务统一走 `http_request`（§8），不提供其他网络能力；
Flowerie 的 HTTP API（send_group_msg 等 OneBot 接口）不是插件接口——请用 `send_message`。

## 13-15. PluginApi 语义 API（唯一事实来源见 api.md）

> 全部 PluginApi 方法（含 v1.5 社交/群管与 v1.7 拉格朗日补齐）请直接查
> **[api.md](api.md) 权威速查总表**（方法/作用/权限/详解，源码自动生成，
> 此处不重复）。SDK 模式同一能力见 [sdk.md](sdk.md) §13。

## 16. Logging API

`api.log(level, message)` 或动作 `{"type":"log"}`：
写入 Flowerie 日志（等级 `info`），带 `plugin_id` 与 `plugin_log` 事件标记。
**插件无法读取 Flowerie 日志**；Flowerie 日志也不会记录任何插件 token/secret
（URL 下载与 WS 日志一律脱敏查询串）。

## 17. 错误处理

- 钩子抛异常 → 该事件被丢弃并记录 `plugin_event_error`（进程继续）
- 钩子返回 `{"__error__": ...}` → 同样丢弃
- action 执行失败 → 返回 `{ok: False, error: ...}` 给插件

## 18. 超时

| 场景 | 默认（与保护级别相关） |
| --- | --- |
| initialize 握手 | 10s（normal）/ 20s（relaxed）/ 30s（unsafe） |
| 单事件处理 | 15s / 60s / 120s |
| 插件 API 同步调用响应 | 30s |

超时 → 进程被终止、插件标记 `crashed`，Flowerie 继续运行。

## 19. 资源限制

- 单插件输出累计 ≥256KB（normal）/ 1MB / 4MB → 进程被终止
- 单事件动作数上限 8 / 16 / 32（超出截断）
- 插件目录文件/大小：安装时 ZIP 解压总大小 ≤50MB、文件数 ≤200、深度 ≤16、
  入口文件 ≤1MB；manifest ≤64KB
- 注册表插件总数 ≤100（`PLUGIN_MAX_COUNT`）

## 20. 安全规范

- 插件运行在**独立子进程**（`python3 -I` 隔离模式 / `node` 子进程），
  环境变量白名单不含任何 API Key / Token
- **边界诚实声明**：子进程隔离是"代码级"隔离（无共享状态、无 API Key、无 Flowerie
  内部模块），**不是 OS 级沙箱**——插件进程与 Flowerie 同用户运行，仍可读同用户的
  文件（如 `../.env` 配置）或执行任意系统调用。插件权限系统只约束**经管理器路由的
  动作**，不约束原始 OS 调用。因此：只安装你自己编写/审查过的插件；保护级别
  `unsafe` 只放宽资源限制，不改变上述边界；生产环境建议将 bot 运行在容器/独立
  用户内，并把 `.env` / 数据目录权限收紧
- 插件不能 `import Flowerie`，不能访问 Flowerie 数据库（没有也没有路径）
- 事件负载最小化：不传原始段数组、不传他人隐私
- `http_request` / 文件访问受路径与 SSRF 限制（§8）
- 安装（上传/URL）经 ZIP Slip / Zip Bomb / Symlink / 路径穿越 / manifest 注入防护（§22）
- **不要**在插件中硬编码 API Key；插件日志不外泄（Flowerie 侧已脱敏）

## 21. Plugin Packaging（打包）

ZIP 结构（也支持整体包一层目录 `pkg/`，自动剥离）：

```
plugin.zip
├── manifest.json
└── plugin.py          # 或 index.js + package.json（node）
```

限制：`.zip` 或 `.json`（单个 manifest，仅 `runtime=json`）；ZIP ≤5MB；
不允许符号链接；不允许绝对路径/`..`。

## 22. 本地插件目录 / 23. Web UI 安装 / 24. URL 安装

| 方式 | 入口 | 说明 |
| --- | --- | --- |
| 本地目录 | `<PLUGIN_DIR>/<id>/manifest.json` | Web UI「插件」页点「刷新扫描」即可发现；安装到注册表（默认禁用）后自动发现 |
| Web UI 上传 | Web UI「插件」页 → 导入插件 → 选择本地文件 → 上传并安装 | 文件类型/大小/内容均受控 |
| URL | Web UI「插件」页 → URL → 下载并安装 | SSRF 防护（内网/回环/私网/重定向全部拒绝）+ Content-Length 预检 + 流式大小中止 + 超时 + Content-Type/扩展名检查 |

三种方式安装后插件一律处于 **disabled**，由管理员启用并批准权限。

### 保护级别（插件保护措施开关）

Web UI「插件」页提供 Normal / Relaxed / Unsafe 三档（`PLUGIN_PROTECTION`）：

- **Normal（推荐）**：完整限制（默认）
- **Relaxed**：放宽非必要限制（更大的超时/输出/动作数）
- **Unsafe（仅可信插件，作者概不负责）**：进一步放宽限制

**任何级别都不豁免**：manifest 校验、管理员权限（Web UI 认证）、进程隔离、
日志、崩溃保护、资源限制、**权限强制（PermissionManager）**。
关闭保护≠无安全边界：普通 QQ 用户永远不能安装/启用插件或修改权限。

## 24.5 常见错误对照表（先看这里，省一小时排查）

| 症状 | 原因 | 解法 |
| --- | --- | --- |
| 插件装上没反应，命令不触发 | `manifest.permissions` 漏 `read_message` | 声明 `read_message`；日志搜 `denied` |
| 能收到消息但**发不出去** | 漏 `send_message`（或 `send_private_message`） | 声明对应发送权限（最容易漏的两个） |
| `on_startup`/`on_message` 不执行 | **钩子名拼错**（拼错=静默不调用，不报错） | 对照 §6 生命周期逐字核对 |
| SDK 模式 matcher 全无 | `bot.attach(api)`/`bot.register()` 忘调用 | §0 模板四行必写：attach → register → route |
| `event.args` 为空/事件字段为 None | 用了 **notice/request 事件**却按 message 字段取 | 先看 `event.kind/scope`（§7） |
| `api.send_message` 报"参数错误" | 动作名/键名拼错（`send_message` vs `send_private_message`） | 查 [api.md](api.md) 速查表（生成自源码，最准） |
| 想发图/at 却拼 CQ 码 | 用了 OneBot 段字符串 | 用 `event.reply`/`BotMessage`（§3）或 SDK `message` 构造 |
| `file_read` 读不到 | 路径带了 `../` 或绝对路径 | 只能读插件目录内相对路径（§20） |
| JSON 插件能执行危险动作？ | `runtime=json` 被当沙箱 | **它不是** OS 沙箱！只放模板+信任内容（§5 警告） |
| URL 装插件失败/慢 | 直连无校验 | 用 `http_request`（主进程 SSRF 防护）或先下载再传 ZIP |
| 重启后插件没启用 | 安装默认 **discovered（禁用）** | Web UI「插件」页手动启用 + 批准权限 |

> 通用排查顺序：**① manifest 权限 → ② 钩子名 → ③ 日志（关键词 `denied`/`error`/`plugin_log`）→ ④ api.md 拼写**。

## 25. 最小插件示例（Python）

仓库自带可执行的最小插件（端到端测试用）：

```
tests/plugins/minimal_plugin/
├── manifest.json
└── plugin.py         # on_message → {"type": "test", "message": "plugin-ok"}
```

启用流程会真实启动子进程、发送事件、捕获 action → 见 `tests/test_plugin_runtime.py`。

## 26. Node.js 示例

```
tests/plugins/minimal_node_plugin/
├── manifest.json
├── package.json
└── index.js          # on_message → {"type": "test", "message": "node-ok"}
```

## 27. Python 示例（完整带权限）

```python
def on_message(event, api):
    if event.get("text") and event.get("text").startswith("!ping"):
        return {"type": "send_message",
                "payload": {"group_id": event["group_id"], "message": "pong"}}
    return None
```

（manifest 需声明 `"permissions": ["read_message", "send_message"]`）
（请配合 `tests/plugins/` 命名规范重命名 id 避免冲突）

## 28. Manifest 示例

见 §2 / §5。

## 29. 测试方法

插件开发者自测（无需真实 QQ）：

1. Manifest 校验：`PluginManifest.from_dict(...)`（单元测试，`tests/test_plugin_manifest.py`）
2. 端到端（推荐）：启动 `PluginRuntime` → `dispatch_event` → 断言返回 actions
   （参考 `tests/test_plugin_runtime.py`；Node 插件在 CI 有 Node 20 可执行）
3. 在线测试：启用后从群内发消息触发（事件经 `read_message` 投递）

## 30. API version compatibility

- `api_version` 当前仅支持 `"1"`；未来版本升级会保留 v1 兼容
- 破坏性变更会提升 `api_version` 并发布新指南；旧插件在升级后需更新 manifest
- 保留字段（`execute_process` / `webhook`）在 v1 中**不会**被实现；
  出现时只允许作为 manifest 权限声明（启用即被拒绝），不要作为功能使用


### 插件数据目录（data_dir）
- `on_startup(ctx, api)` 的 `ctx["data_dir"]`：**`plugins/<plugin_id>/data/`**（自动创建）
- 插件读写自己的数据（配置/缓存/资源）放这里——**无需自己建目录**
- 目录位于插件目录内（防穿越）；创建失败时回退插件目录本体
- 环境变量 `FLOWERIE_PLUGIN_DATA_DIR` 供子进程/工具脚本使用（后续版本）

## 31. 任意语言最小示例（13 种语言，CI 实测）

> 📄 **本节已内联「任意语言插件」完整开发指南**（协议三分钟说明 / manifest 字段 / 13 种语言完整最小实现 /
> 构建入口速查 / 排查清单 / 自测方法），照抄即可，不用另翻文档；下方表格只是速查。

`tests/plugins/multilang/` 下每种语言一份**最小可运行插件**，全部走 `runtime="exec"`：

| 语言 | 夹具 | 构建 / 启动方式 | 事件返回标记 |
| --- | --- | --- | --- |
| C | `multilang/c/` | `gcc -O2 -o plugin plugin.c` | `c-ok` |
| C++ | `multilang/cpp/` | `g++ -O2 -std=c++17 -o plugin plugin.cpp` | `cpp-ok` |
| Go | `multilang/go/` | `go build -o plugin main.go` | `go-ok` |
| Rust | `multilang/rust/` | `rustc -O -o plugin main.rs` | `rust-ok` |
| Java | `multilang/java/` | `javac Plugin.java`；`entry=run.sh` → `exec java -cp . Plugin` | `java-ok` |
| C# / .NET | `multilang/csharp/` | `dotnet build -c Release`；`entry=run.sh` → `dotnet run` | `csharp-ok` |
| Kotlin | `multilang/kotlin/` | `kotlinc plugin.kt -include-runtime -d plugin.jar`；`entry=run.sh` → `java -jar` | `kotlin-ok` |
| PHP | `multilang/php/` | `#!/usr/bin/env php` 直接执行 | `php-ok` |
| Lua | `multilang/lua/` | `#!/usr/bin/env lua` 直接执行 | `lua-ok` |
| Ruby | `multilang/ruby/` | `#!/usr/bin/env ruby` 直接执行 | `ruby-ok` |
| Perl | `multilang/perl/` | `#!/usr/bin/env perl` 直接执行 | `perl-ok` |
| R | `multilang/r/` | `#!/usr/bin/env Rscript` 直接执行 | `r-ok` |
| TypeScript | `multilang/typescript/` | `tsc plugin.ts --target es2019 --module commonjs`；`entry=run.sh` → `node plugin.js` | `typescript-ok` |

### 31.1 三分钟看懂协议（exec 模式）

花璃会拉起你的进程，然后用 **JSON-Lines** 与它通信（一行一个 JSON，UTF-8）：

```text
花璃 → 插件（stdin）  {"id":1,"method":"initialize","params":{}}
插件 → 花璃（stdout）  {"id":1,"result":{"ok":true,"api_version":"1"}}

花璃 → 插件（stdin）  {"id":2,"method":"event","params":{"event":{...}}}
插件 → 花璃（stdout）  {"id":2,"result":{"actions":[{"type":"send_group_msg","params":{...}}]}}
```

**只有四个方法**：

| 方法 | 你要回什么 | 什么时候来 |
| :--- | :--- | :--- |
| initialize | {"result":{"ok":true,"api_version":"1"}} | 启动握手，回完才算就绪 |
| event | {"result":{"actions":[…]}} | 有群消息 / 通知时（动作清单见 plugin-developer-guide §Action） |
| health | {"result":{"ok":true}} | 心跳探活 |
| shutdown | {"result":{"ok":true}} | 退出前（回完再退） |

**四条铁律**（照做就不会踩坑）：

1. **一行一个 JSON，写完立刻 flush** —— 缓冲住就等于花璃永远收不到，插件“没反应”九成是这个原因
2. **收到必须回**，id 原样带回（不要自己造 id）
3. **出错回** {"id":N,"error":"原因"}，别让进程崩（崩了会按保护级别被重启或禁用）
4. **stdout 只能有协议 JSON**：日志、调试、编译器警告一律走 stderr，否则污染协议

---

### 31.2 目录结构与 manifest

```text
plugins/my_plugin/
├── manifest.json      # 必需：声明 runtime=exec 与 entry
├── plugin.rb          # 你的源码（编译型语言这里是编译产物）
└── run.sh             # 可选：编译型 / 需要包装的语言用它当 entry
```

manifest.json（exec 模式）字段：

| 字段 | 必填 | 说明 |
| :--- | :--- | :--- |
| id | ✅ | 唯一标识（[a-z0-9_]，建议带语言前缀如 ml_go） |
| name / version / author / description | ✅ | 展示信息 |
| runtime | ✅ | 固定 "exec"（任意语言模式） |
| entry | ✅ | 可执行文件名；编译型填产物（如 plugin），JVM / .NET / TS 填 run.sh |
| api_version | ✅ | 当前填 "1" |
| permissions | ✅ | 动作权限白名单，没有动作就写 []（见 plugin-developer-guide §权限） |

**run.sh 只做一件事**：把标准输入输出原样转给真正的运行时，例如

```bash
#!/usr/bin/env bash
exec java -cp . Plugin        # JVM：必须 exec，否则信号与退出码传不下去
```

---

### 31.3 逐语言最小实现

#### C

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| gcc -O2 -o plugin plugin.c | plugin | 编译产物 plugin 直接当入口 |

**manifest.json**

```json
{
  "id": "ml_c",
  "name": "Multilang C Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：C（编译产物直接作为插件进程）",
  "runtime": "exec",
  "entry": "plugin",
  "api_version": "1",
  "permissions": []
}
```

**plugin.c**

```c
/* 最小「任意语言插件」示例：C 实现 Plugin API v1（stdin/stdout JSON-Lines）
 * 编译：gcc -O2 -o plugin plugin.c        （entry 指向编译产物 plugin）
 * 说明：这里用 strstr/strtol 取值——最小实现，不引入任何 JSON 库。 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static long extract_id(const char *line) {
    const char *p = strstr(line, "\"id\":");
    if (!p) return -1;
    return strtol(p + 5, NULL, 10);
}

static int has_method(const char *line, const char *method) {
    char pat[64];
    snprintf(pat, sizeof(pat), "\"method\": \"%s\"", method);
    if (strstr(line, pat)) return 1;
    snprintf(pat, sizeof(pat), "\"method\":\"%s\"", method);
    return strstr(line, pat) != NULL;
}

int main(void) {
    char line[65536];
    while (fgets(line, sizeof(line), stdin)) {
        long id = extract_id(line);
        if (id < 0) continue;
        if (has_method(line, "initialize")) {
            printf("{\"id\":%ld,\"result\":{\"ok\":true,\"api_version\":\"1\"}}\n", id);
        } else if (has_method(line, "event")) {
            printf("{\"id\":%ld,\"result\":{\"actions\":[{\"type\":\"test\",\"message\":\"c-ok\"}]}}\n", id);
        } else if (has_method(line, "health") || has_method(line, "shutdown")) {
            printf("{\"id\":%ld,\"result\":{\"ok\":true}}\n", id);
        } else {
            printf("{\"id\":%ld,\"error\":\"unknown method\"}\n", id);
        }
        fflush(stdout);
    }
    return 0;
}
```

#### C++

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| g++ -O2 -std=c++17 -o plugin plugin.cpp | plugin | 同 C，注意 C++17 |

**manifest.json**

```json
{
  "id": "ml_cpp",
  "name": "Multilang C++ Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：C++（编译产物直接作为插件进程）",
  "runtime": "exec",
  "entry": "plugin",
  "api_version": "1",
  "permissions": []
}
```

**plugin.cpp**

```cpp
// 最小「任意语言插件」示例：C++ 实现 Plugin API v1（stdin/stdout JSON-Lines）
// 编译：g++ -O2 -std=c++17 -o plugin plugin.cpp
#include <iostream>
#include <regex>
#include <string>

int main() {
    std::ios::sync_with_stdio(false);
    const std::regex id_re("\"id\":\\s*([0-9]+)");
    const std::regex method_re("\"method\":\\s*\"([a-z_]+)\"");
    std::string line;
    while (std::getline(std::cin, line)) {
        std::smatch m;
        if (!std::regex_search(line, m, id_re)) continue;
        const std::string id = m[1];
        std::string method;
        if (std::regex_search(line, m, method_re)) method = m[1];

        if (method == "initialize") {
            std::cout << "{\"id\":" << id << ",\"result\":{\"ok\":true,\"api_version\":\"1\"}}" << std::endl;
        } else if (method == "event") {
            std::cout << "{\"id\":" << id
                      << ",\"result\":{\"actions\":[{\"type\":\"test\",\"message\":\"cpp-ok\"}]}}" << std::endl;
        } else if (method == "health" || method == "shutdown") {
            std::cout << "{\"id\":" << id << ",\"result\":{\"ok\":true}}" << std::endl;
        } else {
            std::cout << "{\"id\":" << id << ",\"error\":\"unknown method\"}" << std::endl;
        }
    }
    return 0;
}
```

#### Go

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| go build -o plugin main.go | plugin | 静态二进制，拷到服务器就能跑 |

**manifest.json**

```json
{
  "id": "ml_go",
  "name": "Multilang Go Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：Go（编译产物直接作为插件进程）",
  "runtime": "exec",
  "entry": "plugin",
  "api_version": "1",
  "permissions": []
}
```

**main.go**

```go
// 最小「任意语言插件」示例：Go 实现 Plugin API v1（stdin/stdout JSON-Lines）
// 编译：go build -o plugin main.go
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
)

type request struct {
	ID     int             `json:"id"`
	Method string          `json:"method"`
	Params json.RawMessage `json:"params"`
}

func main() {
	sc := bufio.NewScanner(os.Stdin)
	sc.Buffer(make([]byte, 1024*1024), 8*1024*1024)
	out := bufio.NewWriter(os.Stdout)

	for sc.Scan() {
		var req request
		if err := json.Unmarshal(sc.Bytes(), &req); err != nil {
			continue
		}
		switch req.Method {
		case "initialize":
			fmt.Fprintf(out, "{\"id\":%d,\"result\":{\"ok\":true,\"api_version\":\"1\"}}\n", req.ID)
		case "event":
			fmt.Fprintf(out, "{\"id\":%d,\"result\":{\"actions\":[{\"type\":\"test\",\"message\":\"go-ok\"}]}}\n", req.ID)
		case "health", "shutdown":
			fmt.Fprintf(out, "{\"id\":%d,\"result\":{\"ok\":true}}\n", req.ID)
		default:
			fmt.Fprintf(out, "{\"id\":%d,\"error\":\"unknown method\"}\n", req.ID)
		}
		out.Flush()
	}
}
```

#### Rust

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| rustc -O -o plugin main.rs | plugin | 不依赖任何 crate（免 cargo 联网） |

**manifest.json**

```json
{
  "id": "ml_rust",
  "name": "Multilang Rust Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：Rust（编译产物直接作为插件进程）",
  "runtime": "exec",
  "entry": "plugin",
  "api_version": "1",
  "permissions": []
}
```

**main.rs**

```rust
// 最小「任意语言插件」示例：Rust 实现 Plugin API v1（stdin/stdout JSON-Lines）
// 编译：rustc -O -o plugin main.rs   （不依赖任何 crate，避免 cargo 联网）
use std::io::{self, BufRead, Write};

fn extract_id(line: &str) -> Option<u64> {
    let idx = line.find("\"id\":")? + 5;
    let digits: String = line[idx..]
        .chars()
        .skip_while(|c| c.is_whitespace())
        .take_while(|c| c.is_ascii_digit())
        .collect();
    digits.parse::<u64>().ok()
}

fn has_method(line: &str, method: &str) -> bool {
    line.contains(&format!("\"method\": \"{}\"", method))
        || line.contains(&format!("\"method\":\"{}\"", method))
}

fn main() {
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = stdout.lock();
    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };
        let id = match extract_id(&line) {
            Some(v) => v,
            None => continue,
        };
        if has_method(&line, "initialize") {
            let _ = writeln!(out, "{{\"id\":{},\"result\":{{\"ok\":true,\"api_version\":\"1\"}}}}", id);
        } else if has_method(&line, "event") {
            let _ = writeln!(
                out,
                "{{\"id\":{},\"result\":{{\"actions\":[{{\"type\":\"test\",\"message\":\"rust-ok\"}}]}}}}",
                id
            );
        } else if has_method(&line, "health") || has_method(&line, "shutdown") {
            let _ = writeln!(out, "{{\"id\":{},\"result\":{{\"ok\":true}}}}", id);
        } else {
            let _ = writeln!(out, "{{\"id\":{},\"error\":\"unknown method\"}}", id);
        }
        let _ = out.flush();
    }
}
```

#### Java

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| javac Plugin.java | run.sh | JVM 产物不是可执行文件，用 run.sh 包装 |

**manifest.json**

```json
{
  "id": "ml_java",
  "name": "Multilang Java Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：Java（run.sh 包装 exec java -cp）",
  "runtime": "exec",
  "entry": "run.sh",
  "api_version": "1",
  "permissions": []
}
```

**Plugin.java**

```java
// 最小「任意语言插件」示例：Java 实现 Plugin API v1（stdin/stdout JSON-Lines）
// 编译：javac Plugin.java      入口：run.sh（exec java -cp <dir> Plugin）
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.io.PrintWriter;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class Plugin {
    private static final Pattern ID_RE = Pattern.compile("\"id\":\\s*([0-9]+)");
    private static final Pattern METHOD_RE = Pattern.compile("\"method\":\\s*\"([a-z_]+)\"");

    public static void main(String[] args) throws IOException {
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in));
        PrintWriter out = new PrintWriter(new OutputStreamWriter(System.out), true);
        String line;
        while ((line = in.readLine()) != null) {
            Matcher idm = ID_RE.matcher(line);
            if (!idm.find()) continue;
            String id = idm.group(1);
            Matcher mm = METHOD_RE.matcher(line);
            String method = mm.find() ? mm.group(1) : "";
            switch (method) {
                case "initialize":
                    out.println("{\"id\":" + id + ",\"result\":{\"ok\":true,\"api_version\":\"1\"}}");
                    break;
                case "event":
                    out.println("{\"id\":" + id
                            + ",\"result\":{\"actions\":[{\"type\":\"test\",\"message\":\"java-ok\"}]}}");
                    break;
                case "health":
                case "shutdown":
                    out.println("{\"id\":" + id + ",\"result\":{\"ok\":true}}");
                    break;
                default:
                    out.println("{\"id\":" + id + ",\"error\":\"unknown method\"}");
            }
        }
    }
}
```

**run.sh**

```bash
#!/bin/sh
# Java 插件的入口包装：JVM 不是可执行文件，用 3 行脚本把 entry 变成"能直接跑的东西"
exec java -cp "$(dirname "$0")" Plugin
```

#### Kotlin

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| kotlinc plugin.kt -include-runtime -d plugin.jar | run.sh | 同 JVM，run.sh 里 java -jar |

**manifest.json**

```json
{
  "id": "ml_kotlin",
  "name": "Multilang Kotlin Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：Kotlin（run.sh 包装 java -jar）",
  "runtime": "exec",
  "entry": "run.sh",
  "api_version": "1",
  "permissions": []
}
```

**plugin.kt**

```kotlin
// 最小「任意语言插件」示例：Kotlin 实现 Plugin API v1（stdin/stdout JSON-Lines）
// 编译：kotlinc plugin.kt -include-runtime -d plugin.jar   入口：run.sh（exec java -jar plugin.jar）
import java.io.PrintWriter

val ID_RE = Regex("\"id\":\\s*([0-9]+)")
val METHOD_RE = Regex("\"method\":\\s*\"([a-z_]+)\"")

fun main() {
    val out = PrintWriter(System.out, true)
    while (true) {
        val line = readLine() ?: break
        val id = ID_RE.find(line)?.groupValues?.get(1) ?: continue
        val method = METHOD_RE.find(line)?.groupValues?.get(1) ?: ""
        val payload: String = when (method) {
            "initialize" -> "{\"id\":$id,\"result\":{\"ok\":true,\"api_version\":\"1\"}}"
            "event" -> "{\"id\":$id,\"result\":{\"actions\":[{\"type\":\"test\",\"message\":\"kotlin-ok\"}]}}"
            "health", "shutdown" -> "{\"id\":$id,\"result\":{\"ok\":true}}"
            else -> "{\"id\":$id,\"error\":\"unknown method\"}"
        }
        out.println(payload)
    }
}
```

**run.sh**

```bash
#!/bin/sh
# Kotlin 插件的入口包装：跑编译好的 fat-jar（测试/构建阶段先 kotlinc 生成 plugin.jar）
exec java -jar "$(dirname "$0")/plugin.jar"
```

#### C# / .NET

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| dotnet build -c Release | run.sh | dotnet run 会打印启动信息，run.sh 必须只转发行协议 |

**manifest.json**

```json
{
  "id": "ml_csharp",
  "name": "Multilang C# Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：C# / .NET（run.sh 包装 dotnet run）",
  "runtime": "exec",
  "entry": "run.sh",
  "api_version": "1",
  "permissions": []
}
```

**Program.cs**

```csharp
// 最小「任意语言插件」示例：C# / .NET 实现 Plugin API v1（stdin/stdout JSON-Lines）
// 运行：dotnet run --project <dir>（入口 run.sh 包装）
using System;
using System.IO;
using System.Text.RegularExpressions;

class Plugin
{
    static readonly Regex IdRe = new Regex("\"id\":\\s*([0-9]+)");
    static readonly Regex MethodRe = new Regex("\"method\":\\s*\"([a-z_]+)\"");

    static void Main()
    {
        var stdout = new StreamWriter(Console.OpenStandardOutput()) { AutoFlush = true };
        string line;
        while ((line = Console.ReadLine()) != null)
        {
            var idm = IdRe.Match(line);
            if (!idm.Success) continue;
            string id = idm.Groups[1].Value;
            var mm = MethodRe.Match(line);
            string method = mm.Success ? mm.Groups[1].Value : "";
            switch (method)
            {
                case "initialize":
                    stdout.WriteLine("{\"id\":" + id + ",\"result\":{\"ok\":true,\"api_version\":\"1\"}}");
                    break;
                case "event":
                    stdout.WriteLine("{\"id\":" + id + ",\"result\":{\"actions\":[{\"type\":\"test\",\"message\":\"csharp-ok\"}]}}");
                    break;
                case "health":
                case "shutdown":
                    stdout.WriteLine("{\"id\":" + id + ",\"result\":{\"ok\":true}}");
                    break;
                default:
                    stdout.WriteLine("{\"id\":" + id + ",\"error\":\"unknown method\"}");
                    break;
            }
        }
    }
}
```

**run.sh**

```bash
#!/bin/sh
# C# 插件的入口包装：dotnet 项目不是可执行文件，用脚本把 entry 变成"能直接跑的东西"
exec dotnet run --project "$(dirname "$0")" --nologo -v quiet
```

#### TypeScript

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| tsc plugin.ts --target es2019 --module commonjs | run.sh | tsc 产物是 .js，run.sh 里 node |

**manifest.json**

```json
{
  "id": "ml_typescript",
  "name": "Multilang TypeScript Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：TypeScript（tsc 编译后用 run.sh 包装 node）",
  "runtime": "exec",
  "entry": "run.sh",
  "api_version": "1",
  "permissions": []
}
```

**plugin.ts**

```typescript
// 最小「任意语言插件」示例：TypeScript 实现 Plugin API v1（stdin/stdout JSON-Lines）
// 编译：tsc plugin.ts --target es2019 --module commonjs   -> plugin.js
// 入口：run.sh（exec node plugin.js）
//
// 刻意做到**零 npm 依赖**：不要求插件作者先装 @types/node，
// 用 declare 自声明用到的最小接口 + require 取 readline 即可编译。
// 同时用字符串拼接而不是模板字面量，避免插值语法在不同工具链下的歧义。

declare const process: any;
declare function require(name: string): any;

const readline = require("readline");

const ID_RE = /"id":\s*(\d+)/;
const METHOD_RE = /"method":\s*"([a-z_]+)"/;

const rl = readline.createInterface({ input: process.stdin, terminal: false });
rl.on("line", (line: string) => {
  const idm = ID_RE.exec(line);
  if (!idm) return;
  const id = idm[1];
  const mm = METHOD_RE.exec(line);
  const method = mm ? mm[1] : "";
  let payload: string;
  switch (method) {
    case "initialize":
      payload = '{"id":' + id + ',"result":{"ok":true,"api_version":"1"}}';
      break;
    case "event":
      payload = '{"id":' + id + ',"result":{"actions":[{"type":"test","message":"typescript-ok"}]}}';
      break;
    case "health":
    case "shutdown":
      payload = '{"id":' + id + ',"result":{"ok":true}}';
      break;
    default:
      payload = '{"id":' + id + ',"error":"unknown method"}';
  }
  process.stdout.write(payload + "\n");
});
```

**run.sh**

```bash
#!/bin/sh
# TypeScript 插件的入口包装：tsc 产物是纯 JS（没有 shebang，不能直接 exec），用脚本包一层
exec node "$(dirname "$0")/plugin.js"
```

#### PHP

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| （无需构建） | plugin.php | shebang 脚本，注意别把警告输出到 stdout |

**manifest.json**

```json
{
  "id": "ml_php",
  "name": "Multilang PHP Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：PHP（shebang 脚本）",
  "runtime": "exec",
  "entry": "plugin.php",
  "api_version": "1",
  "permissions": []
}
```

**plugin.php**

```php
#!/usr/bin/env php
<?php
// 最小「任意语言插件」示例：PHP 实现 Plugin API v1（stdin/stdout JSON-Lines）
$in = fopen('php://stdin', 'r');
while (($line = fgets($in)) !== false) {
    if (!preg_match('/"id":\s*([0-9]+)/', $line, $m)) {
        continue;
    }
    $id = $m[1];
    $method = preg_match('/"method":\s*"([a-z_]+)"/', $line, $mm) ? $mm[1] : '';
    switch ($method) {
        case 'initialize':
            echo '{"id":' . $id . ',"result":{"ok":true,"api_version":"1"}}', PHP_EOL;
            break;
        case 'event':
            echo '{"id":' . $id . ',"result":{"actions":[{"type":"test","message":"php-ok"}]}}', PHP_EOL;
            break;
        case 'health':
        case 'shutdown':
            echo '{"id":' . $id . ',"result":{"ok":true}}', PHP_EOL;
            break;
        default:
            echo '{"id":' . $id . ',"error":"unknown method"}', PHP_EOL;
    }
    fflush(STDOUT);
}
```

#### Lua

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| （无需构建） | plugin.lua | 必须 io.stdout:setvbuf(line) |

**manifest.json**

```json
{
  "id": "ml_lua",
  "name": "Multilang Lua Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：Lua（shebang 脚本）",
  "runtime": "exec",
  "entry": "plugin.lua",
  "api_version": "1",
  "permissions": []
}
```

**plugin.lua**

```lua
#!/usr/bin/env lua
-- 最小「任意语言插件」示例：Lua 实现 Plugin API v1（stdin/stdout JSON-Lines）
io.stdout:setvbuf("line")   -- 逐行刷新，协议要求即时响应

for line in io.lines() do
  local id = line:match('"id":%s*(%d+)')
  local method = line:match('"method":%s*"([a-z_]+)"')
  if id and method then
    if method == "initialize" then
      io.write('{"id":' .. id .. ',"result":{"ok":true,"api_version":"1"}}\n')
    elseif method == "event" then
      io.write('{"id":' .. id .. ',"result":{"actions":[{"type":"test","message":"lua-ok"}]}}\n')
    elseif method == "health" or method == "shutdown" then
      io.write('{"id":' .. id .. ',"result":{"ok":true}}\n')
    else
      io.write('{"id":' .. id .. ',"error":"unknown method"}\n')
    end
  end
end
```

#### Ruby

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| （无需构建） | plugin.rb | 必须 $stdout.sync = true |

**manifest.json**

```json
{
  "id": "ml_ruby",
  "name": "Multilang Ruby Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：Ruby（最小 Plugin API v1 实现）",
  "runtime": "exec",
  "entry": "plugin.rb",
  "api_version": "1",
  "permissions": []
}
```

**plugin.rb**

```ruby
#!/usr/bin/env ruby
# frozen_string_literal: true
# 最小「任意语言插件」示例：Ruby 实现 Plugin API v1（stdin/stdout JSON-Lines）
# 协议：收 {"id":N,"method":"initialize|event|health|shutdown","params":{...}}
#       发 {"id":N,"result":{...}} 或 {"id":N,"error":"..."}
$stdout.sync = true

STDIN.each_line do |line|
  id = line[/"id":\s*(\d+)/, 1]
  method = line[/"method":\s*"([a-z_]+)"/, 1]
  next if id.nil? || method.nil?

  case method
  when "initialize"
    puts %({"id":#{id},"result":{"ok":true,"api_version":"1"}})
  when "event"
    puts %({"id":#{id},"result":{"actions":[{"type":"test","message":"ruby-ok"}]}})
  when "health"
    puts %({"id":#{id},"result":{"ok":true}})
  when "shutdown"
    puts %({"id":#{id},"result":{"ok":true}})
  else
    puts %({"id":#{id},"error":"unknown method"})
  end
end
```

#### Perl

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| （无需构建） | plugin.pl | 必须 $| = 1 |

**manifest.json**

```json
{
  "id": "ml_perl",
  "name": "Multilang Perl Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：Perl（最小 Plugin API v1 实现）",
  "runtime": "exec",
  "entry": "plugin.pl",
  "api_version": "1",
  "permissions": []
}
```

**plugin.pl**

```perl
#!/usr/bin/env perl
# 最小「任意语言插件」示例：Perl 实现 Plugin API v1（stdin/stdout JSON-Lines）
use strict;
use warnings;
$| = 1;    # 关闭输出缓冲（协议要求逐行即时响应）

while (my $line = <STDIN>) {
    my ($id)     = $line =~ /"id":\s*(\d+)/;
    my ($method) = $line =~ /"method":\s*"([a-z_]+)"/;
    next unless defined $id && defined $method;

    if    ($method eq 'initialize') { print qq({"id":$id,"result":{"ok":true,"api_version":"1"}}\n); }
    elsif ($method eq 'event')      { print qq({"id":$id,"result":{"actions":[{"type":"test","message":"perl-ok"}]}}\n); }
    elsif ($method eq 'health')     { print qq({"id":$id,"result":{"ok":true}}\n); }
    elsif ($method eq 'shutdown')   { print qq({"id":$id,"result":{"ok":true}}\n); }
    else                            { print qq({"id":$id,"error":"unknown method"}\n); }
}
```

#### R

| 构建 | entry | 备注 |
| :--- | :--- | :--- |
| （无需构建） | plugin.R | Rscript，输出后要 flush |

**manifest.json**

```json
{
  "id": "ml_r",
  "name": "Multilang R Plugin",
  "version": "1.0.0",
  "author": "flowerie",
  "description": "任意语言插件示例：R（shebang 脚本）",
  "runtime": "exec",
  "entry": "plugin.R",
  "api_version": "1",
  "permissions": []
}
```

**plugin.R**

```r
#!/usr/bin/env Rscript
# 最小「任意语言插件」示例：R 实现 Plugin API v1（stdin/stdout JSON-Lines）
con <- file("stdin", "r")
repeat {
  line <- readLines(con, n = 1, warn = FALSE)
  if (length(line) == 0) break
  id <- sub('.*"id":\\s*([0-9]+).*', '\\1', line)
  if (!grepl('"id":', line)) next
  method <- sub('.*"method":\\s*"([a-z_]+)".*', '\\1', line)
  if (!grepl('"method":', line)) method <- ""
  if (method == "initialize") {
    cat(sprintf('{"id":%s,"result":{"ok":true,"api_version":"1"}}\n', id))
  } else if (method == "event") {
    cat(sprintf('{"id":%s,"result":{"actions":[{"type":"test","message":"r-ok"}]}}\n', id))
  } else if (method == "health" || method == "shutdown") {
    cat(sprintf('{"id":%s,"result":{"ok":true}}\n', id))
  } else {
    cat(sprintf('{"id":%s,"error":"unknown method"}\n', id))
  }
  flush(stdout())
}
```

---

### 31.4 构建与入口速查

| 语言 | 构建命令 | entry | 首次运行需要 |
| :--- | :--- | :--- | :--- |
| C | gcc -O2 -o plugin plugin.c | plugin | gcc |
| C++ | g++ -O2 -std=c++17 -o plugin plugin.cpp | plugin | g++ |
| Go | go build -o plugin main.go | plugin | go |
| Rust | rustc -O -o plugin main.rs | plugin | rustc |
| Java | javac Plugin.java | run.sh | JDK |
| Kotlin | kotlinc plugin.kt -include-runtime -d plugin.jar | run.sh | kotlinc + JDK |
| C# / .NET | dotnet build -c Release | run.sh | .NET SDK |
| TypeScript | tsc plugin.ts --target es2019 --module commonjs | run.sh | node + tsc |
| PHP | （无需构建） | plugin.php | php |
| Lua | （无需构建） | plugin.lua | lua5.4 |
| Ruby | （无需构建） | plugin.rb | ruby |
| Perl | （无需构建） | plugin.pl | perl |
| R | （无需构建） | plugin.R | Rscript（r-base-core） |

---

### 31.5 排查清单（按出现频率排序）

| 症状 | 原因 | 解法 |
| :--- | :--- | :--- |
| 插件起来了但永远不回消息 | stdout 没 flush | Ruby $stdout.sync=true、Lua io.stdout:setvbuf("line")、Perl $|=1、C/C++/Go/Rust 每行后 flush |
| 花璃报协议错误 / 非法 JSON | stdout 混进了日志或编译器输出 | 日志一律走 stderr；dotnet run 这类会打印启动信息的必须用 run.sh 只转发协议 |
| 编译型插件换台机器跑不了 | 缺运行时（JVM/.NET）或架构不符 | 优先静态产物（Go / Rust / C）；否则装对应运行时 |
| 进程起来立刻退出 | run.sh 忘了 exec，或入口没有执行权限 | run.sh 用 exec；确认 chmod +x |
| 事件收得到、动作不生效 | manifest 的 permissions 没声明 | 补上对应权限（见 plugin-developer-guide §权限） |
| 中文乱码 | 没按 UTF-8 处理 | 读写都按 UTF-8 解码 |

---

### 31.6 自测（不用真 QQ）

```bash
# 手动喂一行 initialize，看它回什么
echo '{"id":1,"method":"initialize","params":{}}' | ./plugin
# 期望：{"id":1,"result":{"ok":true,"api_version":"1"}}

# 仓库里有完整黑盒测试（真的拉起进程跑：握手 → 事件 → 关机）
pytest tests/test_plugin_multilang.py -q -k go
```

验证方式（`tests/test_plugin_multilang.py`）**不是**语法检查，而是真的拉起子进程跑完整协议：
`PluginRuntime.start()` → `initialize` 握手 → `dispatch_event("message")` → 断言返回标记 → `shutdown`。
CI 中每种语言先构建再启动；镜像缺该语言工具链时用例自动 `skip`（不误报失败），
`ci.yml` 额外补装 `lua5.4` 与 `r-base-core`，因此 13 种在 CI 中**全部真实执行**。

### 三条可复用的经验

1. **JVM / .NET / tsc 的产物不是可执行文件** → 用 3 行 `run.sh` 包装（`exec java -jar ... "$@"`），
   manifest 的 `entry` 指向 `run.sh`：内核只认二进制与 shebang，不认「语言」。
2. **脚本语言必须首行 shebang 且带执行位**（`#!/usr/bin/env php` 等）；ZIP 安装时安装器会补一次 `chmod +x`。
   Android 的 `/storage/emulated/0` 是 FUSE，不支持执行位——exec 插件要放在可执行分区（如 `$HOME`）。
3. **stdout 必须逐行 flush**：协议是 JSON-Lines、主进程按行读取，谁缓冲谁握手超时。
   各语言惯用法：C `fflush(stdout)`、C++ `std::endl`、PHP `fflush(STDOUT)`、Ruby `$stdout.sync = true`、
   Perl `$| = 1`、Lua `io.stdout:setvbuf("line")`、R `flush(stdout())`、C# `Console.Out.Flush()`；
   Go / Rust / Java / Kotlin / Node 的 `Println`/`println!`/`println` 是按行刷新，无需额外处理。

## 32. 多条回复（Multi-Reply）

> 让插件一次发出多条独立消息，而**不是**自己写 `for` 循环 —— 条数上限、间隔、
> 发送记录、失败处理都由 Core 统一负责（这样限流与审计才不会被绕过）。

### 32.1 一行用法（SDK 模式）

```python
@command("greet")
async def greet(event):
    await event.reply_many(["你好呀", "今天怎么样", "最近还好吗"])
```

```python
# 主动发送（非回复）也支持
await bot.send_many(123456, ["第一句", "第二句"])          # 群号
await bot.send_many(("private", 10001), ["你好"])          # 私聊
```

返回值：每条消息的 `message_id` 列表（失败或部分失败见 §32.3）。

### 32.2 经典动作模式（任意语言插件）

插件进程用 `send_many` 动作（权限与 `send_message` 相同）：

```json
{
  "type": "send_many",
  "payload": {
    "group_id": 123456,
    "messages": ["你好呀", "今天怎么样"],
    "reply_id": 987654
  }
}
```

返回：`{"ok": true, "count": 2, "message_ids": [111, 112]}`。

### 32.3 规则（插件必须知道的四件事）

1. **条数上限由配置决定**：超出 `MULTI_REPLY_MAX_MESSAGES` 的部分会被**默默丢弃**（AI 与插件都绕不过）；
2. **间隔由 Core 控制**：插件无法指定间隔，统一跟随 `MULTI_REPLY_*` 配置；
3. **仍受连续回复限制**：每发一条都记一次，达到 `MAX_CONSECUTIVE_REPLIES` 后进入冷却；
4. **失败策略**：某条发送失败即停止后续（已发出的不回滚），返回体里给出 `error` 与已成功的 `message_ids`。

### 32.6 协议矩阵（OneBot / Milky）

多条回复是**核心能力**，不是某个协议的特性 —— 同一份代码在两种协议下都可用：

| 场景 | OneBot | Milky |
| :--- | :---: | :---: |
| `event.reply_many([...])` / `bot.send_many(...)` | ✓ | ✓ |
| `send_many` 动作（任意语言插件） | ✓ | ✓ |
| AI 结构化多条 | ✓ | ✓ |
| 间隔与 `MAX_CONSECUTIVE_REPLIES` 限制 | ✓ | ✓ |

原因：多条发送复用 `Sender` 的单条方法，而 `Sender` 已经统一处理了协议差异
（Milky 模式自动映射到 `send_group_message` 并转段数组）。详见 [milky-protocol.md](milky-protocol.md)。

### 32.5 本地验证（不需要 QQ）

仓库自带一个预演脚本，用**真实模块**（ReplyPlan / send_plan / 逐条记录）加一个会打印的假发送器，
把「解析几条 → 配置裁剪 → 计划间隔 → 逐条发送 → 逐条记历史」全过程跑一遍，不联网、不依赖第三方库：

```bash
python3 scripts/multi_reply_demo.py                       # 默认：开启 + 随机间隔
python3 scripts/multi_reply_demo.py --disabled            # 关闭：只发第一条
python3 scripts/multi_reply_demo.py --max-messages 2      # 条数上限裁剪
python3 scripts/multi_reply_demo.py --mode fixed --min 2  # 固定间隔 2 秒
python3 scripts/multi_reply_demo.py --raw 纯文本回复        # 模拟解析失败 → 降级单条
```
### 32.4 什么时候不要用它

- 只有一句话 → 直接用 `event.reply("...")`（单条路径更快也更省事）；
- 需要"一句话里多个表情/图片" → 那是**一条**消息的段数组（`BotMessage`），不是多条；
- 需要精确控制每条时间间隔 → 目前不支持（避免插件绕过限流），请用 `MULTI_REPLY_*` 配置。

