# Plugin-to-Plugin 通信（插件间通信协议）

> **范围**：本文件只写插件间通信**特有**的东西 —— 五类消息、请求/响应/错误模型、语言无关类型与 DTO、
> 路由、权限、超时/取消/环保护/trace。**线格式、信封、id 命名空间、反向通道的通用形状只在
> [plugin-protocol.md](plugin-protocol.md) 定义一次**，本文不重复（下面 JSON 片段都用那里的信封）。
>
> 单一事实来源：`src/plugins/comm.py`（消息/错误码/类型/DTO）、`src/plugins/router.py`（Core Router +
> Bus：投递/超时/取消/事件广播/统计）、`src/plugins/permissions.py`（权限键与判定）、
> `src/plugins/manager.py`（反向 op 接线）。五种语言实现同一套语义：**「插件是什么语言写的」
> 不改变 Plugin API 的语义**。

## 1. 五类消息（`comm.MESSAGE_KINDS`）

| 类别 | 线格式（信封见 protocol §3） | 语义 |
| :--- | :--- | :--- |
| CALL | `{"id":N,"method":"plugin.call","params":{请求模型}}` | 请求-响应，有 request_id |
| RESPONSE | `{"id":N,"result":{"ok":true,"result":<any>}}` | 成功应答 |
| ERROR | `{"id":N,"result":{"ok":false,"error":{code,message,data}}}` | 失败应答（协议级 `{"id":N,"error":"…"}` 也算） |
| EVENT | `{"id":N,"method":"plugin.event","params":{事件模型}}` | 广播，**无**响应语义 |
| CANCEL | `{"id":N,"method":"plugin.cancel","params":{取消模型}}` | 取消一次在途调用 |

`comm.classify_message()` 是这份表的机器可读版本（任意一行 → 五类之一，无法分类 → `"UNKNOWN"`）；
RPC 与 Event 是两类消息，**不得混成一种机制**。

## 2. 请求模型（`comm.make_request` / `comm.validate_request`）

| 字段 | 类型 | 必填 | 说明与上限 |
| :--- | :--- | :--- | :--- |
| `request_id` | string | 是 | 引擎生成（插件可提议，引擎为准） |
| `source` | object | 是 | `{plugin_id, runtime[, instance_id]}`；**引擎按连接填写**，插件自报一律丢弃覆盖 |
| `target` | object \| string | 是 | `{plugin_id[, instance_id]}`；也可写 `"plugin.a"` / `"plugin.a#instance1"` |
| `method` | string | 是 | `^[A-Za-z_][A-Za-z0-9_.]{0,95}$`（`comm.METHOD_RE`） |
| `params` | object \| array | 是 | 只允许语言无关类型（§5） |
| `timeout` | integer(ms) | 是 | 默认 5000（`DEFAULT_TIMEOUT_MS`）；≤0 → 默认；>60000 截到 60000（`MAX_TIMEOUT_MS`） |
| `metadata` | object | 是 | 附加元数据（可为 `{}`） |
| `trace_id` / `call_id` | string | 否 | 缺省自动生成（§8） |
| `hop_count` | integer | 否 | 缺省 0；引擎转发时 +1（§8） |
| `route` | string | 否 | `auto`（默认）/ `core` / `local`；非法值 → `auto` |

字段缺失、`method` 非法、`params` 不是对象/数组、`metadata` 不是对象、`target.plugin_id` 非法
→ `INVALID_ARGUMENT`。示例（`source` 由引擎填，插件只给其余字段）：

```json
{"request_id":"r-1","source":{"plugin_id":"a.py","runtime":"python","instance_id":"0"},
 "target":{"plugin_id":"b.go","runtime":"go","instance_id":"0"},"method":"get_status","params":{},"timeout":5000,
 "trace_id":"t-1","call_id":"c-1","hop_count":0,"route":"auto","metadata":{}}
```

## 3. 响应与错误模型（`comm.make_response` / `make_error_response`）

```json
{"request_id":"r-1","ok":true,"result":<any>}
{"request_id":"r-1","ok":false,"error":{"code":"TIMEOUT","message":"调用 b.go.get_status 超过 5000ms","data":{}}}
```

`error` **永远是** `{code,message,data}` 三件套；SDK 转成本语言形态（Python/Java/TS 抛异常，
Go 返回 `(nil, err)`，Rust 返回 `Err`）；未知 code / 裸字符串经 `PluginCommError.from_error`
归一（兜底 `PLUGIN_ERROR`），**不允许退化成一句裸字符串**。

| 错误码（`comm.ERROR_CODES`，12 个） | 何时产生 |
| :--- | :--- |
| `PLUGIN_NOT_FOUND` | 目标插件/实例不存在（`data.available` 给可用实例） |
| `PLUGIN_NOT_READY` | 目标 STARTING / STOPPING |
| `PLUGIN_UNAVAILABLE` | 目标 FAILED / STOPPED（崩溃或已停用） |
| `METHOD_NOT_FOUND` | 目标未暴露该方法，或未声明 `plugin.call` 能力 |
| `PERMISSION_DENIED` | 缺少 `plugin.call.<target>[.<method>]`（`data.required`/`data.granted`） |
| `INVALID_ARGUMENT` | 请求/事件模型非法（字段缺失、类型错、名字非法） |
| `TIMEOUT` | 超过 `timeout` 未应答（随后尽力发 CANCEL，§8） |
| `CANCELLED` | 调用被取消；或 cancel 的 `request_id` 不存在/已完成 |
| `SERIALIZATION_ERROR` | 载荷含语言内部对象/NaN/非字符串键/bytes 超限（§5） |
| `PLUGIN_ERROR` | 目标插件自身报错（默认兜底码） |
| `INTERNAL_ERROR` | 引擎侧失败（投递异常、调用方未注册等） |
| `PLUGIN_CALL_LOOP` | `hop_count` 达到上限（§8） |

生命周期（`router.lifecycle_state`）→ 码：STARTING/STOPPING → `PLUGIN_NOT_READY`；
FAILED/STOPPED → `PLUGIN_UNAVAILABLE`；不存在 → `PLUGIN_NOT_FOUND`。

## 4. 事件模型（`comm.make_event` / `validate_event`）

| 字段 | 类型 | 必填 | 说明 |
| :--- | :--- | :--- | :--- |
| `event_id` / `trace_id` / `hop_count` / `metadata` | string/int/object | 否 | 缺省自动生成 / 同请求模型 |
| `name` | string | 是 | 事件名，同 `METHOD_RE` |
| `payload` | object \| array | 是 | 只允许语言无关类型 |
| `source` | object | 否 | `{plugin_id, runtime}`；**引擎按连接填写**（自报无效） |

广播投给所有 **READY 且声明 `plugin.event`** 的实例（**不含调用方自己**），单个订阅者失败不影响
其它订阅者；返回 `{"ok":true,"delivered":N,"failed":[{"plugin_id","code"[,"message"]}],"trace_id":"…"}`，
校验失败/权限拒绝/超环 → `{"ok":false,"error":{…},"delivered":0,"failed":[]}`。

## 5. 语言无关类型与 Normalized DTO

允许类型（`comm.DATA_TYPES`）：`null`/`boolean`/`integer`/`number`/`string`/`array`/`object`/`bytes`；
二进制用引用 `{"$bytes":"<base64>","size":N[,"mime":"…"]}`（原始字节 ≤ 4 MiB，`comm.BYTES_MAX`），
解码失败 → `SERIALIZATION_ERROR`。`comm.sanitize_value` 在**边界处**执行（不猜、不 `toString()`）：
tuple/set → list；dict 键必须是字符串；NaN/Infinity 拒绝；嵌套深度 ≤ 32；**语言内部对象直接拒绝**
`SERIALIZATION_ERROR`。复杂对象一律传 Normalized DTO `{"type":<kind>,…}`（未知字段 → `INVALID_ARGUMENT`）：

| kind | 字段（`comm.DTO_FIELDS`） |
| :--- | :--- |
| `message` | message_id, group_id, user_id, sender, segments, text, time |
| `user` | user_id, nickname, card, role, is_bot |
| `group` | group_id, name, member_count, max_member_count |
| `file` | file_id, name, size, url, ref, mime |
| `image` | file_id, url, width, height, ref, mime |
| `segment` | type, data |
| `event` | name, payload, trace_id, hop_count |
| `context` | plugin_id, runtime, instance_id, trace_id, request_id |
| `result` | ok, value, error |

`comm.to_dto(kind, obj)` 是引擎内部对象与跨语言边界之间**唯一的桥**：只取上表声明的字段，插件永远
拿不到对方语言的类实例。

## 6. 路由（`router.PluginRouter`）

- 目标形态：`plugin.a`（**任意健康实例**）或 `plugin.a#instance1`（指定实例）；指定实例不存在 →
  `PLUGIN_NOT_FOUND` + `data.available`；插件存在但无健康实例 → 按生命周期给 `PLUGIN_NOT_READY` /
  `PLUGIN_UNAVAILABLE`。
- 策略 `auto`/`core`/`local`：**跨语言一律经 Core Router**，SDK 不提供任何绕过 Core 的直连（没有私有
  TCP/HTTP）。诚实声明：当前一个插件一个子进程，引擎侧实际路径**总是 core**；`local` 是 SDK 侧保留
  通道（同进程托管多插件时才可能命中），引擎不会假装走过 local。

## 7. 权限（`permissions.py`）

| 权限串 | 含义 |
| :--- | :--- |
| `plugin.call.<target>` / `plugin.call.<target>.<method>` | 允许调用该插件 / 只允许调用其某个方法（后者是动态键，不在 `ALL_PERMISSIONS` 里） |
| `plugin.call.*` / `plugin.call` | 允许调用任意插件（粗粒度，默认不给；亦视为拥有广播权） |
| `plugin.emit` | 允许广播事件 |

判定顺序（`call_permission_granted`，命中即通过）：`plugin.call.<t>.<m>` → `plugin.call.<t>` →
`plugin.call.*` → `plugin.call`；**LOCAL 直连同样要过**（检查点在 `PluginBus.call`，SDK 无法跳过）；
事件广播在 `authorize_emit` 单独过 `plugin.emit`。

## 8. 超时、取消、环保护与 trace（`router.PluginBus`）

- **环保护**：`MAX_HOP_COUNT = 8`，`hop_count ≥ 8` 立即 `PLUGIN_CALL_LOOP` 且**不再向下转发**（事件同
  规则）；引擎每次转发 +1。SDK 出站时带上入站消息的 `trace_id`/`hop_count`，插件作者不写一行 trace
  代码就能拿到全链路。
- **超时**：超过 `timeout` → 返回 `TIMEOUT` 响应并**尽力**发 CANCEL（1s 应答窗口；统计分开记
  `cancels_sent` 与 `cancels_acked`）；插件间调用超时**不杀进程**（杀对方会把慢调用放大成崩溃）。
- **取消**：模型 `{"kind":"CANCEL","request_id","reason"(≤200),"source","trace_id"}`；插件只能取消**自己
  发起且在途**的调用（`request_id` 不存在/已完成 → `CANCELLED`）；目标未声明 `plugin.cancel` →
  如实返回未送达。
- **trace**：`trace_id` 全链路传播、`call_id` 标识单次调用；`comm.new_trace_id()` 优先复用
  `src/utils/trace.py` 的既有上下文，不另造 id 空间。
- **统计**（`PluginBus.snapshot()`）：`calls / calls_ok / calls_error / denied / timeouts / cancels_sent /
  cancels_acked / loop_aborted / events{,_delivered,_failed} / by_error_code / by_route / latency_ms_total`。

## 9. 五语言 SDK 的统一 API

| 能力 | Python | TypeScript | Go | Rust | Java |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 调用 | `api.plugin.call` / `await acall` | `await plugin.call(target, method, params, opts)` | `p.Call(target, method, params, opts...)` | `p.call(target, method, params, opts)` | `p.call` + `CompletableFuture` 重载 |
| 广播 | `api.plugin.emit(name, payload)` | `plugin.emit(name, payload)` | `p.Emit(name, payload)` | `p.emit(name, payload)` | `p.emit(name, payload)` |
| 订阅/暴露/取消 | `api.plugin.on/expose/cancel` | `plugin.on/expose/cancel` | `p.On/Expose/Cancel` | `p.on/expose/cancel` | `p.on/expose/cancel` |

语义约定（五种语言必须一致）：① 失败即结构化错误（码是 §3 的 12 个之一，不退化成字符串）；② handler 收到
完整请求模型（含 `source`/`trace_id`/`hop_count`/`params`），返回值就是 `result`，返回语言内部对象 →
`SERIALIZATION_ERROR`；③ **嵌套调用不丢消息**：等待自己发起的响应期间仍要处理入站的 `plugin.call`/
`plugin.event`/`plugin.cancel`（否则 A→B→A 的回调永远到不了）；④ 能力声明：`initialize` 里声明三个
`plugin.*` 方法（或能力组 `plugin`）；⑤ **不自动重试**（避免请求风暴），重试由插件自己决定。

## 10. 证据与复现命令

| 证据 | 覆盖 |
| :--- | :--- |
| `tests/test_plugin_comm_model.py`（**62 passed**） | 五类消息、请求/响应/错误模型、语言无关类型与 DTO、环保护、权限串、超时归一；与 runner 内联常量逐项比对 |
| `tests/test_plugin_comm_bus.py`（**17 passed**） | 真子进程跑真 Core Router：投递、权限拒绝不投递、超时 + CANCEL、事件广播、A↔B 环保护、实例寻址、生命周期 |
| `tests/test_plugin_comm_paths.py`（7 条）/ `tests/sdk/`（**46 条**） | 7 条跨语言路径真编译真进程 + 五语言最小插件实测（缺工具链 skip 并打印原因，CI 全跑）；逐语言状态见 [plugin-sdk-capabilities.md](plugin-sdk-capabilities.md) |

```bash
python3 -m pytest tests/test_plugin_comm_model.py tests/test_plugin_comm_bus.py -q   # 模型层 + 真子进程总线
python3 -m pytest tests/test_plugin_comm_paths.py -q -rs                            # 跨语言路径（缺工具链打印原因）
python3 -m pytest tests/sdk -q -rs                                                  # 五语言最小插件（本机 9 passed / 37 skipped）
```
