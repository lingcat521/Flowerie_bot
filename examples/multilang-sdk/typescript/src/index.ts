// minimal TypeScript 插件（任务书《插件测试》）：与 Python/Go/Rust/Java 最小插件语义完全一致。
// 只用 TypeScript SDK（sdk/typescript/flowerie_sdk.ts），零 npm 依赖。
import { FloweriePlugin } from "../../../sdk/typescript/flowerie_sdk.ts";

const SDK_VERSION = "1.0.0";
const plugin = new FloweriePlugin({ pluginId: "minimal_ts" });
const state: { events: any[]; logs: string[] } = { events: [], logs: [] };

function label(): string {
  return String(plugin.ctx.pluginId || "minimal_ts").replace(/_/g, "-");
}

function getInfo(): Record<string, unknown> {
  return { plugin_id: plugin.ctx.pluginId, runtime: "typescript", sdk_version: SDK_VERSION,
           protocol_version: "1" };
}

function echo(params: unknown): unknown {
  return params === undefined || params === null ? {} : params;
}

function native(err: any): Record<string, unknown> {
  return { native: (err && (err.name || (err.constructor && err.constructor.name))) || typeof err,
           code: (err && err.code) || "PLUGIN_ERROR",
           message: String((err && err.message) || err) };
}

function call(target: string, method: string, params: unknown = {},
              opts: Record<string, unknown> = {}): Promise<any> {
  return plugin.call(String(target), String(method), params, opts);
}

async function errorProbe(granted: string, denied: string): Promise<Record<string, unknown>> {
  const probes: Array<[string, () => Promise<any>]> = [
    ["METHOD_NOT_FOUND", () => call(granted, "no_such_method")],
    ["PLUGIN_NOT_FOUND", () => call("no_such_plugin", "ping")],
    ["PERMISSION_DENIED", () => call(denied, "ping")],
    ["INVALID_ARGUMENT", () => call("", "ping")],
    ["TIMEOUT", () => call(granted, "slow", {}, { timeout: 200 })],
    ["PLUGIN_ERROR", () => call(granted, "boom")],
  ];
  const out: Record<string, unknown> = {};
  for (const [code, probe] of probes) {
    try {
      await probe();
      out[code] = { native: null, code: "NO_ERROR", message: "预期失败但调用成功了" };
    } catch (err) {
      out[code] = native(err);
    }
  }
  return out;
}

async function runCommand(text: string): Promise<any> {
  const parts = text.split(" ");
  const head = parts[1];
  const argv = parts.slice(2);
  switch (head) {
    case "ping": return await call(argv[0], "ping", {});
    case "info": return getInfo();
    case "echo": return echo(argv[0] ? JSON.parse(argv[0]) : {});
    case "seen": return await call(argv[0], "seen", {});
    case "call": return await call(argv[0], argv[1], argv[2] ? JSON.parse(argv[2]) : {});
    case "route": return await call(argv[1], argv[2], {}, { route: argv[0] });
    case "chain":
      return { t1: await call(argv[0], "ping", {}),
               t2: await call(argv[1], "echo", { hello: "world" }),
               t3: await call(argv[2], "ping", {}) };
    case "errors": return await errorProbe(argv[0], argv[1]);
    default: throw new Error("未知命令: " + head);
  }
}

/** 只响应发给自己的命令：/sdk@<自己的 plugin_id> ...（事件是广播的，不寻址会多插件同时回包）。 */
function addressedToMe(text: string): string | null {
  if (text.indexOf("/sdk@") === 0) {
    const rest = text.slice(5);
    const idx = rest.indexOf(" ");
    const head = idx < 0 ? rest : rest.slice(0, idx);
    const body = idx < 0 ? "" : rest.slice(idx + 1);
    if (head !== String(plugin.ctx.pluginId)) return null;
    return "/sdk " + body;
  }
  return text.indexOf("/sdk ") === 0 ? text : null;
}

plugin.onStartup(() => {
  plugin.expose("ping", () => ({ ok: true, plugin: label(), runtime: "typescript" }));
  plugin.expose("get_info", () => getInfo());
  plugin.expose("echo", (request: any) => echo(request && request.params));
  plugin.expose("seen", () => ({ events: state.events.slice(), logs: state.logs.slice() }));
  plugin.expose("slow", async () => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    return { slept: true };
  });
  plugin.expose("boom", () => {
    throw new Error("minimal typescript plugin boom");
  });
  plugin.ctx.logger.info("minimal-ts 就绪 plugin_id=" + plugin.ctx.pluginId);
});

// §四 Event：test.event 记录 payload 与固定格式的日志行
plugin.on("test.event", (_ctx: any, event: any) => {
  const payload = event && typeof event === "object" ? event : {};
  const message = String(payload.message || "");
  state.events.push({ message });
  state.logs.push("[test.event] " + message);
  return null;
});

// §六：/sdk@<自己> 命令 -> 执行 -> 用动作把结果回给引擎
plugin.onMessage(async (_ctx: any, event: any) => {
  const text = addressedToMe(String((event && event.text) || ""));
  if (text === null) return null;
  let message: string;
  try {
    message = JSON.stringify(await runCommand(text));
  } catch (err) {
    const e: any = err;
    message = JSON.stringify({ ok: false, code: (e && e.code) || "PLUGIN_ERROR",
                               message: String((e && e.message) || e) });
  }
  return { type: "send_message", payload: { group_id: event && event.group_id, message } };
});

plugin.onShutdown(() => {
  plugin.ctx.logger.info("minimal-ts 退出");
});


void plugin.run();
