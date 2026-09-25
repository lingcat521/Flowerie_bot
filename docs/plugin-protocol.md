# Plugin Protocol v1（语言无关插件协议）

> 任务书《多语言 Plugin SDK 扩展任务》§三 要求"先定义稳定的、与语言无关的 Plugin Protocol"。
> 本文件是它的**权威规范**；引擎实现见 `src/plugins/protocol.py`（常量/校验的单一事实来源）、
> `src/plugins/runtime.py`（连接与协商）、`src/plugins/manager.py`（反向 op 策略），
> Python 侧参考实现见 `src/plugins/runner/python_runner.py`。
> 各语言 SDK 的操作指南（`plugin-sdk.md`）与能力对照表（`plugin-sdk-capabilities.md`）随 SDK 落地一并新增（见 §9 的实现状态表）。

## 1. 一句话

**Flowerie 拉起插件进程，用「一行一个 JSON」在 stdin/stdout 上对话。** 插件可以是任何语言 ——
只要能读标准输入、写标准输出。

```text
Flowerie（引擎）                        插件进程（任意语言）
   │  {"id":1,"method":"initialize",...}   │
   ├─────────────────────────────────────►│
   │  {"id":1,"result":{"ok":true,...}}    │
   │◄─────────────────────────────────────┤
   │  {"id":2,"method":"event",...}        │
   ├─────────────────────────────────────►│
   │  {"id":2,"result":{"actions":[...]}}  │
   │◄─────────────────────────────────────┤
   │  {"id":1000001,"method":"engine",...} │  ← 插件主动问引擎（反向通道）
   │◄─────────────────────────────────────┤
   │  {"id":1000001,"result":{...}}        │
   ├─────────────────────────────────────►│
```

## 2. 为什么是 JSON-Lines over stdio（选型理由）

| 候选 | 结论 | 理由 |
| :--- | :--- | :--- |
| **stdio + JSON-Lines** | ✅ **采用** | 零依赖：任何语言都能读写标准流；进程即隔离边界；没有端口/网络暴露面；与仓库已有的 `runtime=exec` 实现与 **13 种语言**夹具一致（`tests/plugins/multilang/`，CI 真编译真运行）；引擎不需要为每种语言维护传输栈 |
| WebSocket | ❌ | 需要每种语言带一个 WS 客户端库；监听端口 = 新的攻击面；插件是**本机子进程**，没有跨机需求 |
| HTTP | ❌ | 同上，且要处理鉴权/端口分配；对"进程内父子关系"是过度设计 |
| Unix socket / TCP | ❌ | 跨平台代价（Windows 命名管道/端口）；stdio 已经由操作系统保证"只连自己的父进程" |
| JSON-RPC 2.0 完整规范 | ⚠️ 部分借鉴 | 借用 `id`/`method`/`params`/`result`/`error` 的形状，但**不引入**通知、批处理等本场景不需要的复杂度；协议很小，实现成本低 |

**关键取舍**：协议只解决"说什么"，不解决"怎么跑"。编译型语言（Go/Rust/Java/C#…）由插件自己
提供可执行入口（`runtime=exec`），Flowerie 不假设任何语言、不经 shell 执行。

## 3. 线格式（framing）

| 规则 | 说明 |
| :--- | :--- |
| 一行一个 JSON | UTF-8，**`\n` 结尾**；JSON 内部不留裸换行 |
| 写完立刻 flush | 缓冲住 = 对方永远收不到（"插件没反应"九成是这个） |
| stdout 只放协议 | 日志/调试/编译器输出**一律 stderr**（引擎会采集 stderr 作为诊断） |
| 收到必须回 | `id` 原样带回；不要自己造 id |
| id 命名空间 | 引擎发的请求用 `1,2,3…`；插件发起的请求从 `1000000` 起（`ACTION_ID_BASE`），两边永不相撞 |
| 非法行 | 解析失败/非对象 → **跳过该行**，不崩、不断连（容错） |

## 4. 方法集

### 4.1 必需（任何插件都要实现）

| 方法 | params | result | 说明 |
| :--- | :--- | :--- | :--- |
| `initialize` | `{"context":{...}}` | `{"ok":true,"api_version":"1","protocol_version":"1","capabilities":[...]}` | 握手；返回非 ok 或主版本不兼容 → 引擎拒绝启动该插件 |
| `event` | `{"event":"message","payload":{...}}` | `{"actions":[{...}]}` | 事件投递；返回的动作清单由引擎执行（**动作才是副作用出口**） |
| `health` | `{}` | `{"ok":true}` | 心跳探活 |
| `shutdown` | `{}` | `{"ok":true}` | 退出前；回完再退（引擎随后会强杀兜底） |

> `hook` 是**引擎内部**方法（控制面调用插件函数，例如插件 WebUI 的数据钩子），不在插件需要实现的清单里。

### 4.2 可选（在 `initialize` 的 `capabilities` 里声明；引擎不会调用未声明的）

| 方法 | params | result | 归属 |
| :--- | :--- | :--- | :--- |
| `context.get` | `{}` | `{"ok":true,"result":{"plugin_id","name","version","runtime","protocol_version","permissions","declared_permissions"}}` | 引擎 |
| `permission.check` | `{"permission":"send_message"}` | `{"ok":true,"permission":...,"granted":true/false}` | 引擎（只读） |
| `config.get` | `{"keys":[...]?}` | `{"ok":true,"values":{...}}` | 引擎（操作员配置，只读）+ 插件覆盖层 |
| `config.set` | `{"values":{...}}` | `{"ok":true,"saved":[...]}` | **插件自己的覆盖层**（写不进全局配置） |
| `storage.get` | `{"key":"note"}` | `{"ok":true,"value":<json|null>}` | 插件自己的数据目录 |
| `storage.set` | `{"key":"note","value":<json>}` | `{"ok":true,"size":N}` | 同上（≤64 KiB/键，≤200 键） |
| `storage.delete` | `{"key":"note"}` | `{"ok":true,"deleted":true/false}` | 同上 |
| `storage.list` | `{"prefix":"no"?}` | `{"ok":true,"keys":[...]}` | 同上 |

**能力分组**：SDK 与文档可以按组声明（`{"context":true,"config":true,"permission":true,"storage":true}`），
协议内部统一展开成方法名（`src/plugins/protocol.py` 的 `CAPABILITY_GROUPS` 是唯一映射表）。

### 4.3 反向通道：插件 → 引擎

插件主动请求引擎时用同一套信封，`method` 固定为 `"engine"`：

```json
{"id":1000001,"method":"engine","params":{"op":"permission.check","args":{"permission":"send_message"}}}
{"id":1000001,"result":{"ok":true,"permission":"send_message","granted":true}}
```

- `op ∈ {context.get, config.get, permission.check}`（`ENGINE_OPS`）；未知 op 一律 `ok:false`；
- 已有的 `method:"action"`（发消息、撤回、加群……）保持不变，它才是**副作用**通道，
  一切 action 先过 `PermissionManager`。

## 5. 生命周期

```text
发现（scan）→ 注册（disabled）→ 管理员启用 + 批准权限 → 启动进程
   → initialize 握手（超时 = startup_timeout；失败/不兼容 → 标记 crashed 并杀进程）
   → running（事件投递 / 心跳 / 反向请求）
   → shutdown（优雅）→ 超时强杀 → 标记 stopped
崩溃：on_exit 回调标记 unhealthy，按保护级别重启或禁用；不影响其他插件与主流程
```

## 6. 错误模型（两条通道，别混）

| 类型 | 形态 | 什么时候用 |
| :--- | :--- | :--- |
| **协议级错误** | `{"id":N,"error":"原因"}` | 未知方法、参数类型错、hook 名非法 —— 插件作者写错了，要早暴露 |
| **操作级失败** | `{"id":N,"result":{"ok":false,"error":"原因"}}` | 方法认识但这次没成功（key 不存在、值超限、权限未批准） |

引擎侧对称：`request()` 收到 `error` 会抛异常；`result.ok=false` 由调用方按业务处理。

## 7. 版本协商与能力握手

1. 插件在 `initialize` 返回 `protocol_version`（缺省按 `"1"` —— 老插件只回 `api_version` 也能跑）；
2. **主版本不同 → 拒绝启动**（宁可明确失败，也不猜兼容）：`协议主版本不兼容：插件 2.0 / 引擎 1`；
3. `capabilities` 只保留协议里存在的可选方法（未知项丢弃）；
4. 引擎把两者记在运行时对象上（`rt.protocol_version` / `rt.capabilities` / `rt.supports(method)`），
   调用可选能力前先 `supports()` —— **能力矩阵因此不会撒谎**。

## 8. 安全模型（引擎强制，插件绕不过）

1. **身份由连接决定**：协议里没有"我是谁"字段 —— 每个插件进程就是它自己，杜绝身份伪造；
2. **权限只读**：`permission.check` 查的是管理员**已批准**的权限集合，插件无法自行提权；
3. **配置归属**：`config.get` 返回操作员配置（插件改不了）；`config.set` 只写插件自己的覆盖层，
   且读取时**操作员的值优先**；
4. **存储隔离**：`storage.*` 只落在该插件自己的 `data/` 目录，键必须是
   `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`（无斜杠、无点段、无隐藏段），并有数量/大小上限；
5. **未知 op/方法一律拒绝**（不静默忽略）；
6. **进程级隔离**：插件进程只继承白名单环境变量（无 API Key/Token），`runtime=python` 还额外用
   `python -I` 隔离模式启动；stdout/stderr 累计字节超限即杀。

## 9. 实现状态（诚实标注）

| 语言 | 运行时 | 协议实现 | 状态 |
| :--- | :--- | :--- | :--- |
| Python | `runtime=python` | `src/plugins/runner/python_runner.py` | **SUPPORTED**（必需 4 + 可选 8 全部实现，见 §11 证据） |
| Node.js | `runtime=node` | `src/plugins/runner/node_runner.js` | **PARTIAL**（必需方法已实现；可选方法待补 —— 见 §11 现状） |
| 任意语言（exec） | `runtime=exec` | 插件自己实现 | 必需方法由 13 种语言夹具验证（CI 真编译真运行）；**各语言 SDK 见即将新增的 `plugin-sdk.md`** |

> 本表只写**有证据**的状态；SDK 落地后由 `plugin-sdk-capabilities.md` 细化为逐能力对照表。

## 10. 与 WebUI Protocol 的关系

任务书第 3 份的核心要求是"**WebUI 是 Plugin Protocol 的一部分，而不是 Python SDK 的附属**"。
因此 WebUI 相关能力（页面声明 / 模板 Context / Action / Asset）也走同一套信封与同一套能力声明，
不另开进程、不另开端口；详见 `docs/plugin-webui.md` 的 §3.5 与（后续）`docs/plugin-webui-protocol.md`。

## 11. 测试与证据

```text
tests/test_plugin_protocol.py            25 passed（本文件描述的全部规则）
  · 常量一致性：runner 内联常量 vs src/plugins/protocol.py 逐项比对
  · 协议工具：键校验 11 例 / 能力归一 4 例 / 版本协商 5 例 / 方法集不交叠
  · 真子进程端到端：真起 python_runner，走 initialize→storage→config→permission→context→event→hook→未知方法→shutdown
    （反向 engine op 通道由测试实现，走**真管道**，不是 mock 协议）
  · 引擎侧 op 安全：未知 op 拒绝 / 未启用拒绝 / permission 只读 / config 只读
插件子集回归                             216 passed / 11 skipped（2 个 ruby/perl 失败是本地缺工具链的既有基线）
```

## 12. 复现

```bash
python3 -m pytest tests/test_plugin_protocol.py -q          # 协议本身
python3 -m pytest tests/test_plugin_multilang.py -q -rs     # 13 种语言（需要本机工具链）
```
