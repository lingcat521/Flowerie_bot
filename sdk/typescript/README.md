# @flowerie/sdk（TypeScript / Node.js）

Flowerie **Plugin Protocol v1** 的 TypeScript 实现。零 npm 依赖，只用 node 内置模块。

- 协议规范：[../../docs/plugin-protocol.md](../../docs/plugin-protocol.md)
- 可运行示例：[../../examples/typescript-plugin/](../../examples/typescript-plugin/README.md)

## 运行方式

| 方式 | 命令 | 要求 |
| :--- | :--- | :--- |
| 零构建（推荐） | `node src/plugin.ts` | Node ≥ 22.6（类型擦除） |
| 传统编译 | `tsc src/plugin.ts flowerie_sdk.ts shims/node.d.ts --target es2022 --module commonjs` | 任意现代 TypeScript（**不需要** `@types/node`）|

> **零依赖编译**：SDK 只用 node 内置模块，但 `tsc` 自身不带 Node 类型。仓库自带
> `shims/node.d.ts`（最小宿主声明）——机器上没有 `@types/node` 时把它一起传给 `tsc` 即可
> （有 `@types/node` 的项目别带 shim，会重复声明）。
> `examples/typescript-plugin/run.sh` 会自动判断，可直接照抄。

## 最小示例

```ts
import { FloweriePlugin } from "./flowerie_sdk.ts";

const plugin = new FloweriePlugin();

plugin.onStartup((ctx) => ctx.logger.info("启动 " + ctx.pluginId));
plugin.onMessage((ctx, ev) => {
  if (ev.text === "ping") {
    return { type: "send_message", payload: { group_id: ev.group_id, message: "pong" } };
  }
  return null;
});
plugin.registerHook("status", () => ({ counter: plugin.ctx.storageGet("counter") }));

await plugin.run();
```

## API 一览

| 能力 | 用法 |
| :--- | :--- |
| 生命周期 | `onStartup(ctx)` / `onShutdown(ctx)` / `run()` |
| 事件 | `onMessage(fn)`（`text=ping → send_message`）/ `on(event, fn)` |
| 动作 | `ctx.action("send_message", {...})`（引擎侧过 PermissionManager）|
| 存储 | `ctx.storageGet/Set/Delete/List`（只落本插件 `data/`，键有格式与大小上限）|
| 配置 | `await ctx.configGet([...])` / `ctx.configSet({...})`（操作员值只读 + 插件覆盖层）|
| 权限 | `await ctx.permissionCheck("send_message")`（只读查询）|
| 日志 | `ctx.logger.info/warn/error`（写 stderr；stdout 只放协议 JSON）|
| 控制面 hook | `registerHook("status", fn)`（插件 WebUI 数据钩子走同一通道）|
