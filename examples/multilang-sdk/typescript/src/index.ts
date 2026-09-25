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

// ---------------- WebUI 调用页（任务书《plugin_to_webui》§12/§28） ----------------
// 页面契约见 tests/e2e/README.md §3：元素 id 就是断言契约；零 JS：form POST + 服务端渲染。
// 真调用：plugin.call -> 引擎 Core Router -> **目标插件进程** -> 结果回本页（失败也如实显示）。
// 关联 id：随请求发给目标、由目标原样带回（echo 原样回 params 即往返证明）；拿不到就如实标注。

const DEFAULT_REQUEST = '{"hello": "world"}';
const CALL_TIMEOUT_MS = 2500;          // 引擎给 webui.action 的上限是 4s，这里留足余量
const TRACE_KEY = "_e2e_trace";        // 随请求往返的关联 id（与 tests/e2e 夹具插件同一约定）
const COMM_METHODS = ["ping", "echo", "get_info", "no_such_method"];
const COMM_ROUTES = ["auto", "core", "local"];
const UNRETURNED = "（对端未回传）";
let callSeq = 0;

/** 本页这次调用的关联 id（插件侧生成）。 */
function newCallId(): string {
  callSeq += 1;
  return Date.now().toString(16) + callSeq.toString(16).padStart(2, "0")
    + Math.random().toString(16).slice(2, 8);
}

function pageIdOf(page: unknown): string {
  if (page && typeof page === "object") {
    const id = (page as Record<string, unknown>).id;
    return String(id === undefined || id === null ? "index" : id);
  }
  return String(page || "index");
}

/** 引擎若把表单塞进 context（当前版本不塞；webui.action 的 form 才是常规通道）。 */
function contextForm(context: any): Record<string, any> {
  const form = context && typeof context === "object" ? context.form : null;
  return form && typeof form === "object" ? form : {};
}

function isCallAction(context: any): boolean {
  const request = context && typeof context === "object" ? context.request : null;
  return String((request && request.action) || "") === "call";
}

/** 对端回传的引擎字段：_engine 块（夹具约定）与顶层平铺（README §3 约定）都认。 */
function engineBlock(result: any): Record<string, any> {
  if (!result || typeof result !== "object") return {};
  const engine = result._engine && typeof result._engine === "object" ? result._engine : {};
  const out: Record<string, any> = Object.assign({}, engine);
  for (const key of ["request_id", "trace_id", "route"]) {
    if (!out[key] && result[key]) out[key] = result[key];
  }
  return out;
}

/** 目标插件**自报**的 runtime：先看回包，再问一次 get_info；都拿不到就留空（不编造）。 */
async function observedRuntime(target: string, routePolicy: string, result: any): Promise<string> {
  if (result && typeof result === "object" && result.runtime) return String(result.runtime);
  try {
    const info: any = await plugin.call(target, "get_info", {},
      { timeout: CALL_TIMEOUT_MS, route: routePolicy });
    return info && typeof info === "object" && info.runtime ? String(info.runtime) : "";
  } catch (err) {
    return "";
  }
}

/** 真调用目标插件；任何失败都变成页面可渲染的结构化结果。 */
async function callTarget(target: string, method: string, requestText: string,
                          routePolicy: string): Promise<Record<string, string>> {
  let payload: any;
  try {
    const text = String(requestText || "").trim();
    payload = text ? JSON.parse(text) : {};
  } catch (err: any) {
    return { response_ok: "error", error_code: "INVALID_ARGUMENT",
             error: "INVALID_ARGUMENT: request 不是合法 JSON: " + String((err && err.message) || err) };
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return { response_ok: "error", error_code: "INVALID_ARGUMENT",
             error: "INVALID_ARGUMENT: request 必须是 JSON 对象" };
  }
  const callId = newCallId();
  const params: Record<string, unknown> = Object.assign({}, payload);
  params[TRACE_KEY] = callId;          // 发给目标；echo 原样带回 -> 证明回包来自目标进程
  let result: any;
  try {
    result = await plugin.call(target, method, params,
      { timeout: CALL_TIMEOUT_MS, route: routePolicy });
  } catch (err: any) {
    const code = String((err && err.code) || (err && err.name) || "PLUGIN_ERROR");
    const message = String((err && err.message) || err);
    return { response: JSON.stringify({ ok: false, error: { code, message } }),
             response_ok: "error", error_code: code, error: code + ": " + message,
             request_id: callId, request_id_source: "插件侧 call id（调用失败）",
             trace_id: callId, trace_id_source: "插件侧（调用失败，无回包）" };
  }
  let traceBack = "";
  if (result && typeof result === "object") {
    traceBack = String(result[TRACE_KEY] || result.trace_id || "");
  }
  const engine = engineBlock(result);
  const engineRequestId = String(engine.request_id || "");
  const engineTraceId = String(engine.trace_id || "");
  const engineRoute = String(engine.route || "");
  return { response: JSON.stringify({ ok: true, result }),
           response_ok: "ok",
           target_runtime: await observedRuntime(target, routePolicy, result),
           request_id: engineRequestId || callId,
           request_id_source: engineRequestId ? "引擎（目标插件回传）" : "插件侧 call id",
           trace_id: engineTraceId || traceBack || callId,
           trace_id_source: engineTraceId ? "引擎（目标插件回传）"
             : (traceBack ? "目标插件原样回传（随请求往返）" : "插件侧（无回包）"),
           route: engineRoute || routePolicy,
           route_source: engineRoute ? "引擎（目标插件回传）" : "调用方请求的路由策略" };
}

// HTML 文件页的模板变量（manifest 的 web_ui.entry，与其它四种语言同名同义）
plugin.registerHook("webui_page", (pageId?: unknown) =>
  ({ vars: String(pageId) === "communication"
     ? communicationVars(String(plugin.ctx.pluginId || ""))
     : webuiVars(String(plugin.ctx.pluginId || "")) }));

/** 调用页的全部模板变量（名字与引擎侧断言一致：response_ok / target_runtime / trace_id …）。 */
function communicationVars(pluginId: string, over: Record<string, string> = {}): Record<string, string> {
  const base: Record<string, string> = {
    plugin_name: pluginId, plugin_id: pluginId, plugin_status: "running",
    plugin_runtime: RUNTIME, plugin_sdk_version: SDK_VERSION,
    target: "", method: "echo", request: DEFAULT_REQUEST, route_policy: "auto",
    response: "", response_ok: "", error: "", error_code: "", target_runtime: "",
    request_id: "", request_id_source: "", trace_id: "", trace_id_source: "",
    route: "", route_source: "", message: "",
  };
  return Object.assign(base, over);
}

/** 把表单变成一次真调用 + 一页可渲染的变量（任何分支都必须渲染得出来）。 */
async function applyCall(form: Record<string, any>, pluginId: string): Promise<Record<string, string>> {
  const target = String(form.target || "").trim();
  const method = String(form.method || "ping").trim() || "ping";
  const requestText = String(form.request || form.params || DEFAULT_REQUEST);
  const routePolicy = String(form.route || "auto").trim() || "auto";
  const vars = communicationVars(pluginId, { target, method, request: requestText,
                                             route_policy: routePolicy });
  if (!target) {
    Object.assign(vars, { response_ok: "error", error_code: "INVALID_ARGUMENT",
                          error: "INVALID_ARGUMENT: 请填写目标插件 id" });
  } else {
    try {
      Object.assign(vars, await callTarget(target, method, requestText, routePolicy));
    } catch (err: any) {
      Object.assign(vars, { response_ok: "error",
                            error_code: String((err && err.name) || "PLUGIN_ERROR"),
                            error: String((err && err.name) || "Error") + ": "
                              + String((err && err.message) || err) });
    }
  }
  vars.message = vars.response_ok === "ok" ? "Status: OK · 调用完成"
    : ("Status: Failed · Code: " + (vars.error_code || "PLUGIN_ERROR"));
  return vars;
}

function optionsHtml(values: readonly string[], current: string): string {
  let html = values.map((v) => '<option value="' + escapeHtml(v) + '"'
    + (String(current) === v ? " selected" : "") + ">" + escapeHtml(v) + "</option>").join("");
  if (String(current) && values.indexOf(String(current)) < 0) {
    // 自定义方法名也要能原样回填提交
    html += '<option value="' + escapeHtml(current) + '" selected>'
      + escapeHtml(current) + "</option>";
  }
  return html;
}

/** 调用页 HTML（零 JS）：表单 + 结果区；元素 id 见 tests/e2e/README.md §3。 */
function communicationHtml(v: Record<string, string>): string {
  const base = "/panel/plugins/webui/" + escapeHtml(v.plugin_id);
  return '<link rel="stylesheet" href="' + base + '/static/style.css">'
    + '<h1 id="plugin-name">' + escapeHtml(v.plugin_name) + "</h1>"
    + '<p id="plugin-status" class="status">状态：' + escapeHtml(v.plugin_status) + "</p>"
    + '<section id="communication-panel" class="card">'
    + "<h2>跨插件调用（Browser → " + escapeHtml(LANGUAGE)
    + " 插件 → Core Router → 目标插件 → 回本页）</h2>"
    + '<form id="communication-form" method="post" action="' + base + '/communication">'
    + '<label for="communication-target">目标插件（target plugin）</label>'
    + '<input type="text" id="communication-target" name="target" value="'
    + escapeHtml(v.target) + '" placeholder="minimal_go">'
    + '<label for="communication-method">方法（method）</label>'
    + '<select id="communication-method" name="method">'
    + optionsHtml(COMM_METHODS, v.method) + "</select>"
    + '<label for="communication-route">路由策略（route）</label>'
    + '<select id="communication-route" name="route">'
    + optionsHtml(COMM_ROUTES, v.route_policy) + "</select>"
    + '<label for="communication-request">请求参数（request，JSON 对象）</label>'
    + '<textarea id="communication-request" name="request" rows="3">'
    + escapeHtml(v.request) + "</textarea>"
    + '<button type="submit" id="communication-submit" name="plugin_action" value="call">'
    + '调用</button>'
    + "</form>"
    + '<table id="communication-result">'
    + '<tr><th>target plugin</th><td id="communication-target-out">'
    + escapeHtml(v.target) + "</td></tr>"
    + '<tr><th>method</th><td id="communication-method-out">'
    + escapeHtml(v.method) + "</td></tr>"
    + '<tr><th>request</th><td><pre id="communication-request-out">'
    + escapeHtml(v.request) + "</pre></td></tr>"
    + '<tr><th>response</th><td><pre id="communication-response">'
    + escapeHtml(v.response) + "</pre></td></tr>"
    + '<tr><th>request_id</th><td id="communication-request-id">' + escapeHtml(v.request_id)
    + ' <small id="communication-request-id-source">' + escapeHtml(v.request_id_source)
    + "</small></td></tr>"
    + '<tr><th>trace_id</th><td id="communication-trace-id">' + escapeHtml(v.trace_id)
    + ' <small id="communication-trace-id-source">' + escapeHtml(v.trace_id_source)
    + "</small></td></tr>"
    + '<tr><th>route</th><td id="communication-route-out">' + escapeHtml(v.route)
    + ' <small id="communication-route-source">' + escapeHtml(v.route_source)
    + "</small></td></tr>"
    + '<tr><th>目标运行时（观察值）</th><td id="communication-target-runtime">'
    + escapeHtml(v.target_runtime || UNRETURNED) + "</td></tr>"
    + '<tr><th>结果</th><td id="communication-response-ok">'
    + escapeHtml(v.response_ok) + "</td></tr>"
    + '<tr><th>错误</th><td id="communication-error">' + escapeHtml(v.error) + "</td></tr>"
    + "</table>"
    + '<p id="communication-message">' + escapeHtml(v.message) + "</p>"
    + "</section>"
    + '<nav id="plugin-nav"><a id="nav-index" href="' + base + '/index">Index</a>'
    + '<a id="nav-communication" href="' + base + '/communication">Communication</a></nav>';
}

// webui.page：引擎要 HTML（GET 与 POST 都会调本钩子；POST 的表单在 webui.action 里）
plugin.webui.page((args) => {
  const pluginId = ctxPluginId(args, String(plugin.ctx.pluginId || ""));
  if (pageIdOf(args && args.page) === "communication") {
    const form = contextForm(args && args.context);
    if (isCallAction(args && args.context) && Object.keys(form).length > 0) {
      // 某个实现若把表单放进了 context，这里也能真调用（引擎当前走 webui.action）
      return applyCall(form, pluginId).then((vars) =>
        ({ html: communicationHtml(vars), vars }));
    }
    const idle = communicationVars(pluginId);
    return { html: communicationHtml(idle), vars: idle };
  }
  return { html: webuiHtml(pluginId), vars: webuiVars(pluginId) };
});

// webui.action：调用页的 POST（按钮 name=plugin_action value=call）-> 真调用 -> 重渲染
plugin.webui.action(async (args) => {
  const pluginId = ctxPluginId(args, String(plugin.ctx.pluginId || ""));
  if (pageIdOf(args && args.page) !== "communication") {
    return { ok: false, error: "未知动作: " + String((args && args.action) || "") };
  }
  const form = (args && args.form && typeof args.form === "object") ? args.form : {};
  const action = String((args && args.action) || "");
  const vars = (action === "call" || String(form.plugin_action || "") === "call")
    ? await applyCall(form, pluginId)
    : communicationVars(pluginId, { message: "未知动作: " + action });
  return { html: communicationHtml(vars), vars, message: vars.message };
});

plugin.onShutdown(() => {
  plugin.ctx.logger.info("minimal-ts 退出");
});


void plugin.run();
