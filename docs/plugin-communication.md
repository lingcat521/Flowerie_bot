# Plugin-to-Plugin 通信（任务书《通信》）

本文是**插件间通信协议**的正式说明：五种语言（Python / TypeScript / Go / Rust / Java）的 SDK
与 Flowerie Core 实现的是同一套语义 —— **「插件是什么语言写的」不改变 Plugin API 的语义**。

- 协议模型（消息/错误码/数据类型的单一事实来源）：`src/plugins/comm.py`
- Core Router + Communication Bus：`src/plugins/router.py`
- 权限：`src/plugins/permissions.py`（与既有 Permission 系统同一套，不另造）
- 引擎接线：`src/plugins/manager.py`（反向 op `plugin.call` / `plugin.emit` / `plugin.cancel`）
- Python SDK：`src/plugins/runner/python_runner.py`

---

## 1. 五类消息（§十）

RPC 与 Event 是两类消息，**不得混成一种机制**：

| 类别 | 线格式（JSON-Lines） | 语义 |
| --- | --- | --- |
| CALL | `{"id":N,"method":"plugin.call","params":{request}}` | 请求-响应，有 request_id |
| RESPONSE | `{"id":N,"result":{"ok":true,"result":<any>}}` | 成功应答 |
| ERROR | `{"id":N,"result":{"ok":false,"error":{code,message,data}}}` | 失败应答（也含协议级 `{"id":N,"error":"..."}`） |
| EVENT | `{"id":N,"method":"plugin.event","params":{event}}` | 广播，无响应语义 |
| CANCEL | `{"id":N,"method":"plugin.cancel","params":{"request_id":...}}` | 取消一次在途调用 |

`comm.MESSAGE_KINDS` 是这份表的机器可读版本；`comm.classify_message()` 把任意一行
分类成这五类之一（测试直接断言它）。

## 2. 请求模型（§六）

```json
{
  "request_id": "…",                       // 引擎生成（插件可提议，引擎为准）
  "source": {"plugin_id": "a.py", "runtime": "python", "instance_id": "0"},
  "target": {"plugin_id": "b.go", "runtime": "go", "instance_id": "0"},
  "method": "get_status",
  "params": {},
  "timeout": 5000,                          // 毫秒
  "trace_id": "…", "call_id": "…", "hop_count": 0,
  "route": "auto",                          // auto | core | local
  "metadata": {}
}
```

**source 由引擎按连接（进程）填写**：插件自报的 source 一律被丢弃并覆盖 —— 否则任何插件都能
冒充别的插件去调用第三方。插件只需要给 `target` / `method` / `params` / `timeout` / `route`。

## 3. 响应模型（§七）

```json
{"request_id": "…", "ok": true,  "result": {}}
{"request_id": "…", "ok": false, "error": {"code": "…", "message": "…", "data": {}}}
```

各语言 SDK 负责把它转成本语言的习惯形态（Python/Java/TS 抛异常，Go/Rust 返回 error/Result）。

## 4. 错误模型（§二十一 + §十七 + §二十二）

`PLUGIN_NOT_FOUND` / `PLUGIN_NOT_READY` / `METHOD_NOT_FOUND` /
`PERMISSION_DENIED` / `INVALID_ARGUMENT` / `TIMEOUT` / `CANCELLED` /
`SERIALIZATION_ERROR` / `PLUGIN_ERROR` / `INTERNAL_ERROR`
（§二十一 的十个）＋ `PLUGIN_UNAVAILABLE`（§十七：目标崩溃/停用）＋
`PLUGIN_CALL_LOOP`（§二十二：超过最大跳数）。共 12 个，见 `comm.ERROR_CODES`。

生命周期（§十七）映射：STARTING/STOPPING → `PLUGIN_NOT_READY`；
FAILED/STOPPED → `PLUGIN_UNAVAILABLE`；不存在 → `PLUGIN_NOT_FOUND`。

## 5. 数据类型（§十九）与 Normalized DTO（§二十）

允许：null / boolean / integer / number / string / array / object / bytes（二进制引用
`{"$bytes":"<base64>","size":N}`）。**不允许**：Python object、Java object、Go struct、
Rust struct、TypeScript class instance —— 引擎在边界处直接拒绝（`SERIALIZATION_ERROR`），
不会悄悄 `toString()`。

复杂对象（Message / User / Group / File / Image / Event / Context）传 **Normalized DTO**：
`{"type":"message","message_id":"…","sender":{…},"segments":[…]}`。
字段表在 `comm.DTO_FIELDS`，五种语言 SDK 用同一份字段名（Python runner 内联了一份，
`tests/test_plugin_comm_model.py` 逐项比对，防止漂移）。

## 6. 路由（§十一/§十二/§十三/§十六）

- 跨语言**必须经 Core Router**（Python→Go、TS→Java…）；SDK 不提供、也不允许任何绕过 Core 的
  直连通道（没有私有 TCP/HTTP；越权通道不存在）。
- 同语言允许 Local Runtime 优化，但公开语义必须与走 Core 完全一致；SDK 提供
  `route: auto | core | local` 策略，`auto` 是默认值，测试用 `core` 验证统一协议路径。
  **注意（诚实声明）**：Flowerie 当前是「一个插件一个子进程」，两个插件不在同一个语言 Runtime
  进程内，因此引擎侧的实际路径总是 `core`；`local` 是 SDK 侧保留的通道（同进程托管多插件时
  才会命中），引擎**不会假装**走过 local（`PluginRouter.route_for()` 只有确实同进程才返回 local）。
- 目标可以是 `plugin.a`（任意健康实例）或 `plugin.a#instance1`（指定实例）；实例不存在时
  返回 `PLUGIN_NOT_FOUND` 并在 `data.available` 里给出可用实例列表。

## 7. 权限（§十四/§十五）

| 权限串 | 含义 |
| --- | --- |
| `plugin.call.<target>` | 允许调用某个插件 |
| `plugin.call.<target>.<method>` | 只允许调用该插件的某个方法（更细） |
| `plugin.call.*` / `plugin.call` | 允许调用任意插件（粗粒度，默认不给） |
| `plugin.emit` | 允许向其它插件广播事件 |

判定顺序：`plugin.call.<t>.<m>` → `plugin.call.<t>` → `plugin.call.*` → `plugin.call`。
**LOCAL 直连同样要过权限**（§十五）：权限检查在 Core Router 里做，SDK 无法跳过。

## 8. 五语言 SDK 的统一 API（§二十七）

对外抽象**完全相同**，命名遵循各语言习惯：

| 能力 | Python | TypeScript | Go | Rust | Java |
| --- | --- | --- | --- | --- | --- |
| 调用 | `api.plugin.call(target, method, params, timeout, route)` | `plugin.call(target, method, params, opts)` | `p.Call(target, method, params, opts...)` | `p.call(target, method, params, opts)?` | `p.call(target, method, params, opts)` |
| 异步 | `await api.plugin.acall(...)` | `await plugin.call(...)` | 同步返回 `(any, error)` | 同步返回 `Result` | 同步 + `CompletableFuture` 重载 |
| 广播 | `api.plugin.emit(name, payload)` | `plugin.emit(name, payload)` | `p.Emit(name, payload)` | `p.emit(name, payload)?` | `p.emit(name, payload)` |
| 订阅 | `api.plugin.on(name, handler)` | `plugin.on(name, handler)` | `p.On(name, handler)` | `p.on(name, handler)` | `p.on(name, handler)` |
| 暴露 | `api.plugin.expose(method, handler)` | `plugin.expose(method, handler)` | `p.Expose(method, handler)` | `p.expose(method, handler)` | `p.expose(method, handler)` |
| 取消 | `api.plugin.cancel(request_id, reason)` | `plugin.cancel(requestId, reason)` | `p.Cancel(requestID, reason)` | `p.cancel(request_id, reason)?` | `p.cancel(requestId, reason)` |

语义约定（五种语言必须一致）：

1. **失败即结构化错误**：目标插件的失败/超时/权限拒绝一律映射成 `{code, message, data}`，
   SDK 转成本语言的异常 / error / Result（Go 返回 `(nil, err)`，Python/Java/TS 抛异常，
   Rust 返回 `Err`）；错误码是 §4 的 12 个之一，**不允许**退化成一句字符串。
2. **handler 收到的是完整请求模型**（含 `source`/`trace_id`/`hop_count`/`params`），
   handler 的返回值就是 CALL 的 `result`；返回语言内部对象 → `SERIALIZATION_ERROR`。
3. **嵌套调用不丢消息**：插件在等待自己发起的调用响应期间，必须能继续处理引擎投递进来的
   `plugin.call` / `plugin.event` / `plugin.cancel`（否则 A→B→A 的回调永远到不了，环保护也无从观察）。
4. **trace/hop 自动传播**：SDK 在处理入站消息时记住其 `trace_id` / `hop_count`，出站调用带上
   （引擎转发时 hop+1）。插件作者不写一行 trace 代码就能拿到全链路。
5. **能力声明**：插件的 `initialize` 必须声明 `plugin.call` / `plugin.event` / `plugin.cancel`
   （或能力组 `plugin`）—— 引擎不会调用未声明的方法。
6. **不自动重试**（§八）：SDK 不做无限自动 retry，避免插件之间形成请求风暴；重试由插件自己决定。

## 9. 示例插件契约（跨语言验收用）

`examples/{python,typescript,go,rust,java}-plugin` 每个都必须：

1. 在启动时（`on_startup` / 等价钩子）**暴露方法** `get_status`，handler 返回：

```json
{"plugin_id": "<自己的 plugin_id>", "runtime": "<python|typescript|go|rust|java>",
 "trace_id": "<请求里的 trace_id>", "hop_count": <请求里的 hop_count>,
 "echo": <请求里的 params>}
```

2. 提供 hook `comm_call`，参数 `[target, method, params]`：调用 `plugin.call`，
   返回 `{"ok": true, "result": <result>}`；失败返回
   `{"ok": false, "code": <错误码>, "message": <消息>}`（**不抛出**，让引擎侧能断言错误码）。
3. 提供 hook `comm_emit`，参数 `[name, payload]`：调用 `plugin.emit`，返回其结果。
4. 既有能力（event / storage / config / permission / webui / status hook / 命令事件）**行为不变** ——
   `tests/test_plugin_sdk_contract.py` 的向量必须继续全绿。

## 10. 验收路径（§二十四）

真实进程、真实管道、**不用 Mock 冒充跨语言通信**：

| 路径 | 怎么验 |
| --- | --- |
| Python → Go | 起真 Go 插件进程与真 Python 插件进程，Python 侧 `plugin.call` 经 Core 到达 Go |
| TS → Java | 起真 TypeScript 与真 Java 插件进程，TS 侧 `plugin.call` 经 Core 到达 Java |
| TS → TS | 两个真 TS 插件进程；`route="core"` 验证统一协议路径，AUTO 路径语义一致 |

测试在缺工具链的机器上 **skip 并打印原因**（本机只有 node + python；CI 上 go / rustc / javac / node
齐全，三条路径全跑），CI 是唯一采信来源。

## 11. 禁止事项（§二十六）与本文档的对应

| 禁止 | 保证方式 |
| --- | --- |
| Core 依赖 Python 插件 | `src/plugins/{comm,router}.py` 不 import 任何语言的 SDK/runner；Core 只认 JSON |
| Go SDK 依赖 Python SDK / Java SDK 依赖 TS SDK | 各语言 SDK 只依赖各自标准库（TS 零 npm 依赖、Go 零第三方、Rust 无 crate、Java 只用 JDK） |
| 跨语言私自建通道绕过 Core | SDK 里没有 socket/http 客户端用于插件间通信；唯一出口是引擎反向 op |
| Local 调用绕过 Permission | 权限检查在 Core Router（`PluginBus.call`）里，SDK 无法跳过 |
| 把语言对象直接传给另一种语言 | `comm.sanitize_value` 在边界拒绝非语言无关类型（`SERIALIZATION_ERROR`） |
| 每种语言一套不同 RPC | 只有一种线格式（JSON-Lines）与一套消息模型；`tests/test_plugin_comm_model.py` 校验常量同源 |
| 删除旧插件测试 | 只新增；旧测试（`test_api_gap_*` / `test_sdk_gap` / `test_plugin_*`）行为不变 |
| 为测试方便关闭 Permission | 权限来自 manifest 批准集，测试也必须显式批准；拒绝路径有专门用例 |
| 用 Mock 冒充跨语言 | 跨语言用例全部起真进程（工具链缺失时 skip 并打印原因，不假装通过） |
