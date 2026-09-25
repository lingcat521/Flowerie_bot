// minimal TypeScript 插件（任务书《插件测试》）：与 Python/Go/Rust/Java 最小插件语义完全一致。
// 只用 TypeScript SDK（sdk/typescript/flowerie_sdk.ts），零 npm 依赖。
import { FloweriePlugin } from "../../../sdk/typescript/flowerie_sdk.ts";

const SDK_VERSION = "1.0.0";
const RUNTIME = "typescript";      // ping / get_info / WebUI 页面上的 runtime
const plugin = new FloweriePlugin({ pluginId: "minimal_ts" });
const state: { events: any[]; logs: string[] } = { events: [], logs: [] };

function label(): string {
  return String(plugin.ctx.pluginId || "minimal_ts").replace(/_/g, "-");
}

function getInfo(): Record<string, unknown> {
  return { plugin_id: plugin.ctx.pluginId, runtime: RUNTIME, sdk_version: SDK_VERSION,
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
  plugin.expose("ping", () => ({ ok: true, plugin: label(), runtime: RUNTIME }));
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

// ---------------- WebUI 最小页面（任务书《plugin_to_webui》§23） ----------------
// 五种语言共用**同一套** WebUI API：页面由插件经 webui.page 返回 HTML（No-JS：只有 HTML + CSS）。
// 路由 / 权限 / 校验 / 净化 / 隔离全部由引擎负责，插件只负责内容。
// Plugin 与 Runtime 取自受控 context 与 SDK 值，不写死在 HTML 里（部署方改名后页面自动跟随）。

const LANGUAGE = "TypeScript";
const SDK_NAME = "@flowerie/sdk";   // SDK 包名（sdk/typescript/package.json）

/** 本语言原生的 HTML 转义（插件不假设引擎一定会替自己转义动态数据）。 */
function escapeHtml(value: unknown): string {
  const table: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;",
                                          '"': "&quot;", "'": "&#39;" };
  return String(value).replace(/[&<>"']/g, (ch) => table[ch] || ch);
}

/** 受控 context 里的 plugin id（引擎按连接识别身份；拿不到才退回 SDK 的 pluginId）。 */
function ctxPluginId(args: Record<string, any>, fallback: string): string {
  const context = (args && args.context) || {};
  const pluginInfo = context.plugin || {};
  return String(pluginInfo.id || fallback);
}

/** WebUI 模板变量（HTML 文件页的数据钩子与插件渲染页共用一份）。 */
function webuiVars(pluginId: string): Record<string, string> {
  return { language: LANGUAGE, sdk: SDK_NAME + " " + SDK_VERSION,
           plugin_id: pluginId, runtime: RUNTIME };
}

/** 最小 WebUI 页面：<h2>插件页</h2> + Language / SDK / Plugin / Runtime 四项。 */
function webuiHtml(pluginId: string): string {
  const style = "/panel/plugins/webui/" + pluginId + "/static/style.css";
  return '<link rel="stylesheet" href="' + escapeHtml(style) + '">'
    + '<h2>插件页</h2>'
    + '<dl class="flowerie-webui lang-' + RUNTIME + '" id="plugin-info">'
    + '<dt>Language</dt><dd class="language">' + escapeHtml(LANGUAGE) + '</dd>'
    + '<dt>SDK</dt><dd class="sdk">' + escapeHtml(SDK_NAME + " " + SDK_VERSION) + '</dd>'
    + '<dt>Plugin</dt><dd class="plugin">' + escapeHtml(pluginId) + '</dd>'
    + '<dt>Runtime</dt><dd class="runtime">' + escapeHtml(RUNTIME) + '</dd>'
    + '</dl>';
}

// HTML 文件页的模板变量（manifest 的 web_ui.entry，与其它四种语言同名同义）
plugin.registerHook("webui_page", () =>
  ({ vars: webuiVars(String(plugin.ctx.pluginId || "")) }));

// webui.page：引擎要 HTML，插件返回 HTML + 受控模板变量
plugin.webui.page((args) => {
  const pluginId = ctxPluginId(args, String(plugin.ctx.pluginId || ""));
  return { html: webuiHtml(pluginId), vars: webuiVars(pluginId) };
});

plugin.onShutdown(() => {
  plugin.ctx.logger.info("minimal-ts 退出");
});


void plugin.run();
