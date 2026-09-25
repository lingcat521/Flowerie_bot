# Plugin Protocol v1（语言无关插件协议）

> **权威规范**：线格式与信封全仓只在**本文件**定义一次。单一事实来源是代码 ——
> `src/plugins/protocol.py`（常量与校验）、`src/plugins/runtime.py`（连接与 initialize 协商）、
> `src/plugins/manager.py`（反向 op 策略）、`src/plugins/runner/python_runner.py`（Python 参考实现）。
>
> 相关：[plugin-communication.md](plugin-communication.md)（插件间通信：消息模型/路由/权限/环保护）、
> [plugin-webui-protocol.md](plugin-webui-protocol.md)（WebUI 三条通道）、
> [plugin-sdk-capabilities.md](plugin-sdk-capabilities.md)（逐语言能力矩阵）。
> 核对基线：Flowerie **2.3.0**；协议版本常量 `PROTOCOL_VERSION = "1"` / `API_VERSION = "1"`。

## 1. 一句话

**Flowerie 拉起插件进程，用「一行一个 JSON」在 stdin/stdout 上对话** —— 插件可以是任何语言，
只要能读标准输入、写标准输出。选型理由：零依赖、进程即隔离边界、没有端口/网络暴露面，
且不引入 JSON-RPC 的通知/批处理等本场景不需要的复杂度。

## 2. 线格式（framing）

| 规则 | 说明 |
| :--- | :--- |
| 一行一个 JSON | UTF-8，`\n` 结尾（`protocol.encode_line`）；JSON 内部不留裸换行 |
| 写完立刻 flush | 缓冲住 = 对方永远收不到（「插件没反应」九成是这个） |
| stdout 只放协议 | 日志/调试/编译输出一律 stderr（引擎采集 stderr 作为诊断） |
| 收到必须回 | `id` 原样带回；不要自己造 id |
| id 命名空间 | 引擎发起的请求用 `1,2,3…`；插件发起的请求从 `1000000` 起（`ACTION_ID_BASE`），两边永不相撞 |
| 非法行 | 解析失败 / 非对象 → 跳过该行、不断连（`protocol.decode_line` 返回 None） |

```text
引擎 → 插件   {"id":1,"method":"initialize","params":{"context":{…}}}
插件 → 引擎   {"id":1,"result":{"ok":true,"capabilities":[…]}}
引擎 → 插件   {"id":2,"method":"event","params":{"event":"message","payload":{…}}}
插件 → 引擎   {"id":2,"result":{"actions":[…]}}
插件 → 引擎   {"id":1,"error":"未知方法"}          ← 协议级错误（§6）
插件 → 引擎   {"id":1000001,"method":"engine","params":{"op":…,"args":{…}}}  ← 反向通道（§5）
引擎 → 插件   {"id":1000001,"result":{"ok":true,…}}
```

## 3. 信封（四种形状，别混）

| 方向 | 形状 | 语义 |
| :--- | :--- | :--- |
| 引擎 → 插件 | `{"id":N,"method":"<方法>","params":{…}}` | 调用必需/可选方法或 `"action"` |
| 插件 → 引擎（应答） | `{"id":N,"result":{…}}` / `{"id":N,"error":"原因"}` | 成功：语义在 `result`（如 `{"ok":true,…}`）；协议级错误：这行不是合法请求（§6） |
| 插件 → 引擎（反向请求） | `{"id":N,"method":"engine","params":{"op":"…","args":{…}}}` | 插件主动问引擎（§5） |

## 4. 方法集

### 4.1 必需（`REQUIRED_METHODS`，任何插件都要实现）

| 方法 | params | result |
| :--- | :--- | :--- |
| `initialize` | `{"context":{"plugin_dir","data_dir","protocol_version"}}` | `{"ok":true,"api_version":"1","protocol_version":"1","capabilities":[…]}` |
| `event` | `{"event":"message","payload":{…}}` | `{"actions":[{…}]}`（动作清单由引擎执行，动作才是副作用出口） |
| `health` | `{}` | `{"ok":true}` |
| `shutdown` | `{}` | `{"ok":true}`（回完再退；引擎随后强杀兜底） |

> `hook` 是引擎内部方法（`ENGINE_INTERNAL_METHODS`），由控制面调用插件函数（如 WebUI 数据钩子），
> 不在插件必须实现的清单里。

### 4.2 可选（`OPTIONAL_METHODS`，共 14 个：核心 8 + WebUI 3 + 插件间 3）

在 `initialize` 的 `capabilities` 里声明；**引擎不会调用未声明的方法**。

| 组 | 方法 | params → result |
| :--- | :--- | :--- |
| context | `context.get` | `{}` → `{"ok":true,"result":{"plugin_id","name","version","runtime","protocol_version","permissions","declared_permissions"}}` |
| config | `config.get` | `{"keys":[…]?}` → `{"ok":true,"values":{…}}`（操作员配置只读 + 插件覆盖层） |
| config | `config.set` | `{"values":{…}}` → `{"ok":true,"saved":[…]}`（只写插件自己的覆盖层） |
| permission | `permission.check` | `{"permission":"send_message"}` → `{"ok":true,"permission":…,"granted":true/false}` |
| storage | `storage.get` | `{"key":"note"}` → `{"ok":true,"value":<json|null>}` |
| storage | `storage.set` | `{"key":"note","value":<json>}` → `{"ok":true,"size":N}` |
| storage | `storage.delete` | `{"key":"note"}` → `{"ok":true,"deleted":true/false}` |
| storage | `storage.list` | `{"prefix":"no"?}` → `{"ok":true,"keys":[…]}` |
| webui | `webui.page` / `webui.action` / `webui.asset` | 见 [plugin-webui-protocol.md](plugin-webui-protocol.md) §1 |
| plugin | `plugin.call` / `plugin.event` / `plugin.cancel` | 见 [plugin-communication.md](plugin-communication.md) §2–§3 |

**能力声明两种写法等价**（`protocol.normalize_capabilities` 归一）：方法名列表
`["config.get","storage.set"]`，或能力分组 `{"config":true,"storage":true}`；不在
`OPTIONAL_METHODS` / `CAPABILITY_GROUPS` 里的项**丢弃不报错**，结果去重排序。
分组表（`CAPABILITY_GROUPS`）：`context` / `config` / `permission` / `storage` /
`webui` / `plugin`。

## 5. 反向通道（插件 → 引擎）

`method` 固定为 `"engine"`，按 `op` 分派；未知 op 一律拒绝（`ENGINE_OPS`，6 个）：

```json
{"id":1000001,"method":"engine","params":{"op":"permission.check","args":{"permission":"send_message"}}}
{"id":1000001,"result":{"ok":true,"permission":"send_message","granted":true}}
```

| op | 用途 |
| :--- | :--- |
| `context.get` / `config.get` / `permission.check` | 只读查询（能力见 §4.2） |
| `plugin.call` / `plugin.emit` / `plugin.cancel` | 插件间通信的**唯一**发起路径，不许旁路 |

`method:"action"`（发消息、撤回、加群……）保持不变，它是**副作用**通道：一切 action 先过
`PermissionManager`（`src/plugins/permissions.py`）。

## 6. 错误模型（两条通道，别混）

| 类型 | 形态 | 什么时候用 |
| :--- | :--- | :--- |
| 协议级错误 | `{"id":N,"error":"原因"}` | 未知方法、参数类型错、hook 名非法 —— 插件作者写错了，要早暴露 |
| 操作级失败 | `{"id":N,"result":{"ok":false,"error":"原因"}}` | 方法认识但这次没成功（key 不存在、值超限、权限未批准） |

插件间调用的结构化错误码（12 个，`{code,message,data}`）见
[plugin-communication.md](plugin-communication.md) §4。

## 7. 版本协商与能力握手（`protocol.negotiate_initialize`）

1. 插件在 `initialize` 返回 `protocol_version`；**缺省按 `"1"`**（只回 `api_version` 的老插件也能跑）；
2. 主版本不同 → **拒绝启动**（宁可明确失败，也不猜兼容）：`协议主版本不兼容：插件 2.0 / 引擎 1`；
3. `capabilities` 归一成协议里存在的可选方法名（未知项丢弃，§4.2）；
4. 引擎把结果记在运行时对象上（`rt.protocol_version` / `rt.capabilities` / `rt.supports(method)`），
   调用可选能力前先 `supports()` —— 能力矩阵因此不会撒谎。

## 8. 安全不变式与限额（引擎强制，插件绕不过）

1. **身份由连接决定**：信封里没有「我是谁」字段，每个插件进程就是它自己，杜绝身份伪造；
2. **权限只读**：`permission.check` 查管理员**已批准**的权限集合，插件无法自行提权；
3. **配置归属**：`config.get` 返回操作员配置（插件改不了），`config.set` 只写插件自己的覆盖层；
4. **存储隔离**：`storage.*` 只落在该插件自己的 `data/` 目录；键必须匹配
   `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`（无斜杠/点段/隐藏段）；
5. **未知 op/方法一律拒绝**（不静默忽略）；
6. **进程隔离**：插件进程只继承白名单环境变量（无 API Key/Token），`runtime=python` 额外用
   `python -I` 启动；stdout/stderr 累计字节超限即杀。

限额常量（`protocol.py`）：`storage` ≤ 200 键/插件、单值 ≤ 64 KiB；`config` ≤ 64 键、
单值 ≤ 8 KiB（`MAX_STORAGE_KEYS` / `MAX_STORAGE_VALUE_BYTES` / `MAX_CONFIG_KEYS` / `MAX_CONFIG_VALUE_BYTES`）。

## 9. 生命周期

```text
发现（scan）→ 注册（disabled）→ 管理员启用 + 批准权限 → 启动进程 → initialize 握手
（超时 = startup_timeout；失败/不兼容 → 标记 crashed 并杀进程）→ running（事件/心跳/反向请求）
→ shutdown（优雅）→ 超时强杀 → stopped。崩溃：on_exit 标记 unhealthy，按保护级别重启或禁用。
```

## 10. 与 WebUI / 插件间通信的关系

WebUI 是 Plugin Protocol 的一部分（不是 Python SDK 的附属）：页面/动作/资源三条通道走**同一套信封**
与同一套能力声明，不另开进程、不另开端口 —— 协议见 [plugin-webui-protocol.md](plugin-webui-protocol.md)。
插件间通信同样建立在本协议之上（`plugin.call/event/cancel` 三个方法 + 三个反向 op），
模型见 `src/plugins/comm.py`，说明见 [plugin-communication.md](plugin-communication.md)。

## 11. 证据与复现命令

- `tests/test_plugin_protocol.py`（**25 passed**）：常量一致性（runner 内联常量 vs `protocol.py` 逐项比对）、
  键校验、能力归一、版本协商、方法集不交叠、真子进程端到端（initialize→storage→config→permission→
  context→event→hook→未知方法→shutdown）、引擎侧 op 安全；
- `tests/test_plugin_multilang.py`（**14 条**）：`tests/plugins/multilang/` 13 种语言最小插件真编译真运行。

```bash
python3 -m pytest tests/test_plugin_protocol.py -q        # 协议本身（含真子进程）
python3 -m pytest tests/test_plugin_multilang.py -q -rs  # 13 种语言（需要本机工具链，缺则打印原因 skip）
```
