# @flowerie/sdk（TypeScript / Node.js）

Flowerie **Plugin Protocol v1** 的 TypeScript 实现。零 npm 依赖，只用 node 内置模块。

- 协议规范：[../../docs/plugin-protocol.md](../../docs/plugin-protocol.md)
- 可运行示例：[../../examples/typescript-plugin/](../../examples/typescript-plugin/README.md)

## 运行方式

| 方式 | 命令 | 要求 |
| :--- | :--- | :--- |
| 零构建（推荐） | `node src/plugin.ts` | Node ≥ 22.6（类型擦除） |
| 传统编译 | `tsc` | 任意现代 TypeScript |

## 最小示例

```ts
import { FloweriePlugin } from "./flowerie_sdk.ts";

const plugin = new FloweriePlugin();

plugin.onStartup((ctx) => ctx.logger.info("启动 " + ctx.pluginId));
plugin.onMessage((ctx, ev) => {
  if (ev.text === "ping") {
    return { type: "send_group_msg", params: { group_id: ev.group_id, message: "pong" } };
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
| 事件 | `onMessage(fn)`（`text=ping → send_group_msg`）/ `on(event, fn)` |
| 动作 | `ctx.action("send_group_msg", {...})`（引擎侧过 PermissionManager）|
| 存储 | `ctx.storageGet/Set/Delete/List`（只落本插件 `data/`，键有格式与大小上限）|
| 配置 | `await ctx.configGet([...])` / `ctx.configSet({...})`（操作员值只读 + 插件覆盖层）|
| 权限 | `await ctx.permissionCheck("send_message")`（只读查询）|
| 日志 | `ctx.logger.info/warn/error`（写 stderr；stdout 只放协议 JSON）|
| 控制面 hook | `registerHook("status", fn)`（插件 WebUI 数据钩子走同一通道）|
