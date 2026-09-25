// TypeScript 示例插件：用 @flowerie/sdk 实现 Plugin Protocol v1。
// 运行：node src/plugin.ts（Node ≥22.6 直接跑 TS；旧版 node 先 tsc 编译）
import { FloweriePlugin } from "../../../sdk/typescript/flowerie_sdk.ts";

/** 自己的 plugin_id：manifest.json 的 id（引擎若在 initialize 里给了 plugin_id，SDK 会覆盖它）。 */
const PLUGIN_ID = "typescript_demo";

const plugin = new FloweriePlugin({ pluginId: PLUGIN_ID });

plugin.onStartup((ctx) => {
  ctx.logger.info("typescript 示例插件启动 plugin_id=" + ctx.pluginId);
});

// ---------------- Plugin-to-Plugin 通信（任务书《通信》§五-§二十七） ----------------
// 与 Python / Go / Rust / Java 示例**完全一致**的语义：被调方 get_status + 两个控制面钩子。

plugin.onStartup(() => {
  // 暴露给其它插件（§五 CALL 的被调方）：handler 收到的是**完整请求模型**
  // （含 source / trace_id / hop_count / params），返回值就是 CALL 的 result。
  plugin.expose("get_status", (request) => ({
    plugin_id: plugin.ctx.pluginId,
    runtime: "typescript",
    trace_id: request.trace_id || "",
    hop_count: request.hop_count || 0,
    echo: request.params === undefined || request.params === null ? {} : request.params,
  }));
});

plugin.onMessage((ctx, event) => {
  // 与其它语言示例**完全一致**的语义：收到消息 → 回一条 pong（跨语言等价由契约测试比对）
  if (event && event.text === "ping") {
    return { type: "send_message", payload: { group_id: event.group_id, message: "pong" } };
  }
  return null;
});

// 命令事件（与 Python 的 on_command 对齐）：/ping → pong
plugin.onCommand((ctx, event) => {
  if (event && event.text === "/ping") {
    return { type: "send_message", payload: { group_id: event.group_id, message: "pong" } };
  }
  return null;
});

// 控制面可调用的 hook（插件 WebUI 的数据钩子走同一条通道）
plugin.registerHook("status", (ctx?: unknown) => {
  const value = plugin.ctx.storageGet("counter") as { n?: number } | null;
  return { counter: value && typeof value.n === "number" ? value.n : null };
});

/** 控制面钩子 comm_call：[target, method, params] -> plugin.call。
 *  失败**不抛出**，回结构化错误码（让引擎侧能断言错误码，§二十一）。 */
plugin.registerHook("comm_call", async (target, method, params) => {
  try {
    const result = await plugin.call(String(target), String(method),
      params === undefined ? {} : params);
    return { ok: true, result };
  } catch (err) {
    const comm = err as { code?: string; message?: string };
    return {
      ok: false,
      code: comm && comm.code ? comm.code : "PLUGIN_ERROR",
      message: String((comm && comm.message) || err),
    };
  }
});

/** 控制面钩子 comm_emit：[name, payload] -> plugin.emit，返回 { ok, delivered, failed }（§九）。 */
plugin.registerHook("comm_emit", (name, payload) =>
  plugin.emit(String(name), payload === undefined ? {} : payload));

plugin.onShutdown((ctx) => {
  ctx.logger.info("typescript 示例插件退出");
});


// ---------------- Plugin WebUI Protocol（任务书第 3 份 §六） ----------------
// 页面 / 动作 / 资源三条通道；路由、权限、校验、净化、隔离全部由引擎负责。

function readNickname(): string {
  const value = plugin.ctx.storageGet("nickname");
  return typeof value === "string" ? value : "";
}

/** 插件渲染页的 HTML：{{ nickname }} 由引擎 escape 后替换（受控模板变量）。 */
function settingsForm(pluginId: string): string {
  return "<h2>插件渲染页</h2>"
    + '<p class="who">这份 HTML 来自插件进程（webui.page），不是磁盘文件。</p>'
    + '<form class="card" method="post" action="/panel/plugins/webui/' + pluginId + '/dynamic">'
    + '<input type="hidden" name="plugin_action" value="save">'
    + '<label>昵称 <input name="nickname" value="{{ nickname }}" maxlength="64"></label>'
    + '<button type="submit">保存</button></form>'
    + '<p class="msg">{{ message }}</p>';
}

/** 引擎给的受控 context：plugin.id 由引擎按连接识别，插件不需要（也不能）自己声明身份。 */
function ctxPluginId(args: Record<string, any>, fallback: string): string {
  const context = (args.context || {}) as Record<string, any>;
  const pluginInfo = (context.plugin || {}) as Record<string, any>;
  return String(pluginInfo.id || fallback);
}

// HTML 文件页的模板变量（走 web_ui.entry 数据钩子）
plugin.registerHook("webui_page", () => ({ vars: { nickname: readNickname() } }));

plugin.webui.page((args) => ({
  html: settingsForm(ctxPluginId(args, plugin.ctx.pluginId)),
  vars: { nickname: readNickname() },
}));

plugin.webui.action((args) => {
  if (String(args.action) !== "save") {
    return { ok: false, error: "未知动作: " + String(args.action) };
  }
  const form = (args.form || {}) as Record<string, string>;
  const nickname = String(form.nickname || "").slice(0, 64);
  return {
    html: settingsForm(ctxPluginId(args, plugin.ctx.pluginId)),
    vars: { nickname },
    message: "已保存",
    config_set: { nickname },
    storage_set: { nickname },
  };
});

plugin.webui.asset((args) => String(args.path) === "theme.css"
  ? { content_type: "text/css", body: "body { color: #1f6feb; }" }
  : { ok: false, error: "资源不存在: " + String(args.path) });

void plugin.run();
