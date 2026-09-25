# TypeScript / Node.js SDK（@flowerie/sdk）

> 任务书第 2 份 §五 / §十五。协议规范：[plugin-protocol.md](plugin-protocol.md)；
> 能力矩阵：[plugin-sdk-capabilities.md](plugin-sdk-capabilities.md)；总览：[plugin-sdk.md](plugin-sdk.md)。
> 源码：`sdk/typescript/flowerie_sdk.ts`；示例：`examples/typescript-plugin/`。

## 1. 定位与依赖

- **零 npm 依赖**：只用 node 内置模块（`node:fs` / `node:path` / `node:readline`）；
- 运行方式二选一：
  1. Node ≥ 22.6 直接执行 `.ts`（类型擦除，零构建）；
  2. 老 node（如 CI 的 v20）用 `tsc` 编译：`tsc src/plugin.ts flowerie_sdk.ts shims/node.d.ts --target es2022 --module commonjs`。
     机器上**没有** `@types/node` 也能编译——SDK 自带最小宿主声明 `sdk/typescript/shims/node.d.ts`，
     `examples/typescript-plugin/run.sh` 会自动判断并带上（有 `@types/node` 时不要带，会重复声明）。

## 2. 最小示例

```ts
import { FloweriePlugin } from "@flowerie/sdk";          // 仓库内：../../sdk/typescript/flowerie_sdk.ts

const plugin = new FloweriePlugin();

plugin.onStartup((ctx) => ctx.logger.info("启动 " + ctx.pluginId));
plugin.onMessage((ctx, ev) => ev.text === "ping"
  ? { type: "send_group_msg", params: { group_id: ev.group_id, message: "pong" } }
  : null);
plugin.onCommand((ctx, ev) => ev.text === "/ping"
  ? { type: "send_group_msg", params: { group_id: ev.group_id, message: "pong" } }
  : null);
plugin.registerHook("status", () => ({ counter: plugin.ctx.storageGet("counter") }));

// Plugin WebUI Protocol：页面 / 动作 / 资源
plugin.webui.page(() => ({ html: "<h2>设置</h2>", vars: { nickname: "" } }));
plugin.webui.action((args) => ({ message: "已保存", vars: { nickname: String(args.form?.nickname) },
                                 storage_set: { nickname: String(args.form?.nickname) } }));
plugin.webui.asset(() => ({ content_type: "text/css", body: "body{color:#1f6feb}" }));

await plugin.run();
```

## 3. API 一览

| 能力 | 用法 |
| :--- | :--- |
| 生命周期 | `onStartup(fn)` / `onShutdown(fn)` / `run()` |
| 事件 | `onMessage(fn)` · `onCommand/onNotice/onRequest/onLifecycle/onSchedule` · `on(event, fn)` |
| 心跳 | `onHealth(() => boolean)`（返回 false 即不健康） |
| 动作 | `ctx.action("send_group_msg", {...})`（引擎侧过 PermissionManager） |
| 存储 | `ctx.storageGet/Set/Delete/List`（只落本插件 `data/`，键有格式/数量/大小上限） |
| 配置 | `await ctx.configGet(["k"])` / `ctx.configSet({...})`（操作员值只读 + 插件覆盖层） |
| 权限 | `await ctx.permissionCheck("send_message")`（只读查询） |
| 上下文 | `await ctx.refreshContext()` |
| 日志 | `ctx.logger.info/warn/error`（写 stderr） |
| 控制面 hook | `registerHook(name, fn)` |
| WebUI Protocol | `plugin.webui.page/action/asset(fn)` · `registerWebui(method, fn)` |

## 与 Python SDK 的能力对照

| 能力 | 本 SDK | Python（runner） |
| :--- | :--- | :--- |
| 必需方法 | initialize / event / health / shutdown | 同 |
| 可选能力（14 项） | context.get · config.get · config.set · permission.check · storage.get/set/delete/list · webui.page/action/asset · **plugin.call/event/cancel** | **完全相同**（`test_handshake_declares_protocol_and_capabilities` 是相等断言，不是子集） |
| 反向通道 | 插件 → 引擎的 engine op / action | 同 |
| 控制面 hook | 具名处理器（插件 WebUI 数据钩子） | `def status(...)` |
| WebUI Protocol | 页面/动作/资源三通道 | 同 |

差异只在**语言习语**：Python 的 `PluginApi` 另有 160+ 个动作包装方法（`send_message` / `group_ban` …），
其它语言用统一的 `action("send_group_msg", {...})` 得到同样效果（协议层没有差别）。

## 自查命令

```bash
python3 -m pytest tests/test_plugin_sdk_contract.py -q -rs -k <lang>
python3 -m pytest tests/test_plugin_webui_multilang.py -q -rs -k <lang>

# 本机缺工具链时会打印 SKIP 原因（不是 pass）；CI 装了 go/rustc/javac/node，全跑
```

## 已知限制

- 引擎按**连接**识别插件身份：插件**不能**（也不需要）自己声明 plugin_id；
- 只有声明过的可选方法才会被引擎调用（`supports()` 门控），所以声明与实现必须一致；
- stdout 只能放协议 JSON（一行一个）；日志一律 stderr，否则会被当成非法行跳过。

## 插件间通信（Plugin-to-Plugin，任务书第 4 份《通信》）

`plugin.call(target, method, params, opts)` / `plugin.emit(name, payload)` /
`plugin.on(name, handler)` / `plugin.expose(method, handler)` / `plugin.cancel(request_id, reason)`：

- 目标可以是 `plugin_a`（任意健康实例）或 `plugin_a#instance1`（指定实例）；
- **跨语言必须经 Core Router**（本 SDK 没有第二条出站通道）；`route` 策略 `auto|core|local` 默认 `auto`；
- 失败一律是结构化错误（`{code,message,data}`，12 个错误码之一），不会退化成一句字符串；
- `trace_id` / `hop_count` 由 SDK 自动传播；等待自己发起的调用响应期间，引擎投递进来的
  `plugin.call` / `plugin.event` / `plugin.cancel` 仍会被处理（插件可重入）；
- 权限 `plugin.call.<target>[.<method>]` / `plugin.emit` 由引擎强制，SDK 无法绕过；
- 不自动重试（§八）。

完整协议见 [plugin-communication.md](plugin-communication.md)。
