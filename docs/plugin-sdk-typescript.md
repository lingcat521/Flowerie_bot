# TypeScript / Node.js SDK（@flowerie/sdk）

> 总览与通用规则：[plugin-sdk.md](plugin-sdk.md)（§1–§9 的通用语义都在那里）｜ 协议：[plugin-protocol.md](plugin-protocol.md) ｜ 能力矩阵：[plugin-sdk-capabilities.md](plugin-sdk-capabilities.md)
> 源码 `sdk/typescript/flowerie_sdk.ts` · 示例 `examples/multilang-sdk/typescript/`（契约/WebUI 用例另跑 `examples/typescript-plugin/`）· CI 实测：`tests/sdk/test_minimal_plugins.py::test_build_load_ready_and_api[typescript]`、`tests/sdk/test_minimal_paths.py::test_plugin_communication_path[typescript->go]`、`tests/test_plugin_sdk_contract.py`（含 `test_typescript_shim_covers_host_apis`）、`tests/test_plugin_webui_multilang.py::test_webui_action_save_is_identical[typescript]`

## 1. 安装与引入
- 工具链：**Node ≥ 22.6** 直接执行 `.ts`（类型擦除、零构建），老 node 用 `tsc`（`sdk/typescript/package.json:14-16`）；**零 npm 依赖**，只用内置 `node:fs` / `node:path` / `node:readline`（`flowerie_sdk.ts:14-16`）；机器上没有 `@types/node` 时 `tsc` 要额外带 SDK 自带的 `sdk/typescript/shims/node.d.ts`，有则**不要**带（`sdk/typescript/README.md:15-18`）。
- 引入：`import { FloweriePlugin } from "../../../sdk/typescript/flowerie_sdk.ts"`（`examples/multilang-sdk/typescript/src/index.ts:3`；`build.sh` 会把它改写成同目录拷贝）。包名 `@flowerie/sdk`（`package.json:2,7-8`）在仓库内**不可解析**，别照抄包名导入。
- 环境变量：SDK 只在缺失时把 `FLOWERIE_PLUGIN_DIR` / `FLOWERIE_PLUGIN_ID` 当回退读（`flowerie_sdk.ts:482,485`），而引擎**不注入**它们（`src/plugins/runtime.py:40-41` 只给 `PATH/HOME/LANG/TMPDIR/TEMP/TMP/NODE_PATH/LD_LIBRARY_PATH`）；`plugin_id` 真实来源是 `initialize` 的 `context`（`runtime.py:103-111`）。

## 2. 最小插件（可直接复制）
清单键值逐字取自 `examples/multilang-sdk/typescript/manifest.json`（省略 `author`/`description` 与 `web_ui` 段，后者见 §6；`src/plugins/manifest.py:125` 的七个必填字段一个不少）：
```json
{ "id": "minimal_ts", "name": "Minimal TypeScript Plugin", "version": "1.0.0",
  "runtime": "exec", "entry": "run.sh", "api_version": "1",
  "permissions": ["read_message", "send_message", "plugin.call.*", "plugin.emit", "web_ui"] }
```
入口取自 `examples/multilang-sdk/typescript/src/index.ts`（只保留启动 + 暴露 `ping`；省略 `get_info`/`echo`/`seen`/`slow`/`boom`/`webui`，完整版见该目录）：
```ts
import { FloweriePlugin } from "../../../sdk/typescript/flowerie_sdk.ts";
const plugin = new FloweriePlugin({ pluginId: "minimal_ts" });

plugin.onStartup(() => {                       // initialize 握手之后调用
  plugin.expose("ping", () => ({ ok: true, plugin: "minimal-ts", runtime: "typescript" }));
});
plugin.onMessage((ctx, event) => {
  const text = String(event.text ?? "");       // 消息文本在事件对象的平铺字段里
  if (text !== "ping") return null;            // 不匹配必须显式回 null（= 无动作）
  return { type: "send_message",               // 引擎只执行白名单动作，且只读 action["payload"]
           payload: { group_id: event.group_id, message: "pong" } };
});
void plugin.run();
```

## 3. 事件注册
| 事件 / 钩子 | 本语言写法（`flowerie_sdk.ts:行`）|
| :--- | :--- |
| `message` | `plugin.onMessage((ctx, event) => 动作 \| null)`（:489；event = `{event, plugin_id, ...payload}`，:859）|
| `command` / `notice` / `request` / `lifecycle` / `schedule` | `onCommand` / `onNotice` / `onRequest` / `onLifecycle` / `onSchedule`（:509-513）；任意事件名用 `on(event, fn)`（:498）|
| 启动 / 关闭 / 心跳 | `onStartup(fn)`（:504）· `onShutdown(fn)`（:505）· `onHealth(() => boolean)`，返回 false 即不健康（:507）|
| 控制面 hook / WebUI | `registerHook(name, fn)`，名字须匹配 `^[a-z_][a-z0-9_]{0,63}$`（:515,670）· `plugin.webui.page/action/asset(fn)`（:527-531）|
| 插件间 | `on(name, fn)` 收 `plugin.event`，`"*"` 订阅全部（:807-827）；`expose(method, handler)` 供 `plugin.call` 调用（:583）；`plugin.cancel` 由 SDK 自己记 `request_id`（:830-837）|

## 4. API 表（出处 `flowerie_sdk.ts:行`）
| 能力 | 本语言签名 / 写法 |
| :--- | :--- |
| 构造 · 主循环 · 上下文 | `new FloweriePlugin({ pluginId?, pluginDir?, capabilities? })`（:476）· `await plugin.run()`（:621）· `plugin.ctx`（:541）|
| 动作（唯一副作用出口）| `ctx.action(type, params): Promise<Record<string, unknown>>`（:317）|
| 存储 / 配置 | `ctx.storageGet(key)`（:338）· `storageSet(key, value): number`（:343）· `storageDelete(key): boolean`（:353）· `storageList(prefix?)`（:359）· `await ctx.configGet(keys?)`（:369）· `configSet(values): string[]`（:380）|
| 权限 / 上下文 / 日志 | `await ctx.permissionCheck(p): boolean`（:320）· `await ctx.refreshContext()`（:324）· `ctx.logger.info/warn/error`（stderr，:309-315）|
| 通信 / 错误 | `plugin.call`（:551）· `emit`（:571）· `expose`（:583）· `cancel`（:601）· `commTrace`（:610）· `exposedMethods`（:619）；`PluginCommError{code,message,data}`（:136-149）、12 个 `ERROR_CODES`（:34-38）、`DEFAULT_TIMEOUT_MS=5000`（:40）|

## 5. 存储 / 配置 / 权限（通用语义见 [plugin-sdk.md §5](plugin-sdk.md#5-存储配置与权限)）
- 存储落本插件 `data/storage/*.json`；键须匹配 `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`、值 ≤64 KiB、≤200 键（:55-57），越界抛 `Error`。
- `configGet` = 引擎操作员值（只读）+ 本插件 `data/config.json` 覆盖层；`configSet` 只写覆盖层、回已存键的升序数组（:364-390）。
- `permissionCheck` 是只读查询（:320-323），动作与插件间调用仍由引擎强制；权限先写进 manifest `permissions`。

## 6. WebUI
`web_ui` 段与 §2 同一份（`examples/multilang-sdk/typescript/manifest.json:17-24`）：`static` 静态目录 + `entry: "webui_page"` 文件页数据钩子 + 若干 `{ "id", "render": "plugin" }` 插件渲染页（HTML 由插件进程返回；文件页换成 `"file"`）。
```ts
plugin.webui.page((args) => ({ html, vars }));                       // :106-109
plugin.webui.action(async (args) => ({ html, vars, message, config_set, storage_set }));   // :111-124，未知 action 回 {ok:false,error}
plugin.webui.asset((args) => String(args.path) === "theme.css"       // 见 examples/typescript-plugin/src/plugin.ts
  ? { content_type: "text/css", body: "body { color: #1f6feb; }" }
  : { ok: false, error: "资源不存在: " + String(args.path) });
```
返回对象只透传 `html/vars/context/message/content_type/body/base64/config_set/storage_set`；返回字符串 = `{html}` 简写，`{ok:false,error}` = 操作级错误（:270-286）。

## 7. 插件间通信
`plugin.call(target, method, params, { timeout, route })`（:551）· `plugin.emit(name, payload)` → `{ok, delivered, failed}`（:571）· `plugin.expose(method, handler)`（:583）· `plugin.cancel(requestId, reason)`（:601）· `plugin.on(name, fn)`（:498）；失败抛 `PluginCommError`，`.code` 取 12 个错误码之一。语义 / 路由 / 权限见 [plugin-sdk.md §7](plugin-sdk.md#7-插件间通信)。

## 8. 构建与运行
- 构建 `sh build.sh`：拷 SDK 到 `.build/`、`sed` 改写跨目录 import；node ≥22 直接产出 `.build/index.ts` 并退出，否则要 `tsc`（`examples/multilang-sdk/typescript/build.sh:4-18`）。
- 运行 `sh run.sh`：优先 `exec node .build/js/index_cjs.js`，其次 `.build/index.ts`；都没有就打印「未构建：请先执行 build.sh」并 exit 1（`run.sh:5-12`）——**绝不隐式编译**。
- 缺工具链：`tests/sdk/harness.py:42-55` 会 **skip 并打印原因**（不是 pass）。本机实测（node v24.18.0）：`sh build.sh` → `build ok: …/.build/index.ts（node 24 直接执行 TS）`。

## 9. 常见错误
| 症状 | 原因 → 处理（`flowerie_sdk.ts:行`）|
| :--- | :--- |
| `SERIALIZATION_ERROR`（`undefined 字段会被 JSON 悄悄丢掉`）| 入参/返回值里有 `undefined`、函数、`BigInt`、`Date`/`Map` 等内部对象 → 只传 JSON 值（:184-213），空值用 `null` |
| 引擎看不到日志 / 协议行被跳过 | `console.log` 写进了 stdout（stdout 只放协议 JSON）→ 一律 `ctx.logger.*`（stderr，:309-315,421-423）|
| `hook 名非法` | hook 名不符合 `^[a-z_][a-z0-9_]{0,63}$`（驼峰 `webuiPage` 必失败，已实测）→ 改 `webui_page` 这类小写名（:670）|
