// TypeScript 示例插件：用 @flowerie/sdk 实现 Plugin Protocol v1。
// 运行：node src/plugin.ts（Node ≥22.6 直接跑 TS；旧版 node 先 tsc 编译）
import { FloweriePlugin } from "../../../sdk/typescript/flowerie_sdk.ts";

const plugin = new FloweriePlugin();

plugin.onStartup((ctx) => {
  ctx.logger.info("typescript 示例插件启动 plugin_id=" + ctx.pluginId);
});

plugin.onMessage((ctx, event) => {
  // 与其它语言示例**完全一致**的语义：收到消息 → 回一条 pong（跨语言等价由契约测试比对）
  if (event && event.text === "ping") {
    return { type: "send_group_msg", params: { group_id: event.group_id, message: "pong" } };
  }
  return null;
});

// 控制面可调用的 hook（插件 WebUI 的数据钩子走同一条通道）
plugin.registerHook("status", (ctx?: unknown) => {
  const value = plugin.ctx.storageGet("counter") as { n?: number } | null;
  return { counter: value && typeof value.n === "number" ? value.n : null };
});

plugin.onShutdown((ctx) => {
  ctx.logger.info("typescript 示例插件退出");
});

void plugin.run();
