/**
 * @flowerie/sdk —— Flowerie Plugin Protocol v1 的 TypeScript / Node.js 实现。
 *
 * 零 npm 依赖：只用 node 内置模块（readline / fs / path）。
 * 协议规范见 docs/plugin-protocol.md；与 Python runner 的行为由
 * tests/test_plugin_sdk_contract.py + tests/fixtures/plugin_protocol_vectors.json 交叉验证。
 *
 * 运行方式（二选一）：
 * 1. **零构建**：Node ≥ 22.6 可直接执行 .ts（类型擦除）—— `node src/plugin.ts`
 * 2. 传统构建：`tsc` 编译成 .js 再 `node dist/plugin.js`
 */
import * as fs from "node:fs";
import * as path from "node:path";
import * as readline from "node:readline";

export const PROTOCOL_VERSION = "1";
export const API_VERSION = "1";
export const ACTION_ID_BASE = 1000000;
export const OPTIONAL_METHODS = [
  "context.get", "config.get", "config.set", "permission.check",
  "storage.get", "storage.set", "storage.delete", "storage.list",
  "webui.page", "webui.action", "webui.asset",
] as const;
/** WebUI Protocol 方法（任务书第 3 份 §三）：与其它语言 SDK 同名同义。 */
export const WEBUI_METHODS = ["webui.page", "webui.action", "webui.asset"] as const;
export const CAPABILITY_GROUPS: Record<string, string[]> = {
  context: ["context.get"],
  config: ["config.get", "config.set"],
  permission: ["permission.check"],
  storage: ["storage.get", "storage.set", "storage.delete", "storage.list"],
  webui: ["webui.page", "webui.action", "webui.asset"],
};
const STORAGE_KEY_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const MAX_STORAGE_KEYS = 200;
const MAX_STORAGE_VALUE_BYTES = 64 * 1024;
const MAX_CONFIG_KEYS = 64;
const MAX_CONFIG_VALUE_BYTES = 8 * 1024;


/** WebUI 应答允许透传的字段（其余字段一律丢弃，不把插件内部对象塞进协议）。 */
const WEBUI_PAYLOAD_KEYS = ["html", "vars", "context", "message", "content_type", "body",
  "base64", "config_set", "storage_set"];

function normalizeWebuiResult(result: unknown): Record<string, unknown> {
  if (typeof result === "string") return { ok: true, html: result };
  if (result && typeof result === "object") {
    const out: Record<string, unknown> = { ok: true };
    const src = result as Record<string, unknown>;
    for (const key of WEBUI_PAYLOAD_KEYS) if (key in src) out[key] = src[key];
    return out;
  }
  return { ok: false, error: "WebUI 处理器没有返回内容" };
}

export interface Action { type: string; params?: Record<string, unknown> }
export interface PluginInfo {
  plugin_id?: string; name?: string; version?: string; runtime?: string;
  protocol_version?: string; permissions?: string[]; declared_permissions?: string[];
}

/** 传给插件钩子的上下文：storage / config / permission / logger / action。 */
export class PluginContext {
  readonly pluginId: string;
  readonly pluginDir: string;
  readonly dataDir: string;
  readonly info: PluginInfo;
  private readonly client: ProtocolClient;
  /** 需要用户显式提供的能力分组（默认全开；关闭后不向引擎声明对应方法）。 */
  constructor(client: ProtocolClient, pluginId: string, pluginDir: string, dataDir: string, info: PluginInfo) {
    this.client = client;
    this.pluginId = pluginId;
    this.pluginDir = pluginDir;
    this.dataDir = dataDir;
    this.info = info;
  }
  get logger() {
    return {
      info: (msg: string, ...rest: unknown[]) => process.stderr.write("[info] " + msg + " " + rest.join(" ") + "\n"),
      warn: (msg: string, ...rest: unknown[]) => process.stderr.write("[warn] " + msg + " " + rest.join(" ") + "\n"),
      error: (msg: string, ...rest: unknown[]) => process.stderr.write("[error] " + msg + " " + rest.join(" ") + "\n"),
    };
  }
  /** 发一个 action（唯一副作用出口；引擎侧过 PermissionManager）。 */
  action(type: string, params: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    return this.client.action(type, params);
  }
  async permissionCheck(permission: string): Promise<boolean> {
    const res = await this.client.engineOp("permission.check", { permission });
    return res && res.granted === true;
  }
  async refreshContext(): Promise<PluginInfo> {
    const res = await this.client.engineOp("context.get", {});
    return (res && (res.result as PluginInfo)) || {};
  }
  // ---------------- storage：只落本插件自己的 data 目录 ----------------
  private storageDir(): string {
    const dir = path.join(this.dataDir, "storage");
    fs.mkdirSync(dir, { recursive: true });
    return dir;
  }
  private storagePath(key: string): string {
    if (!STORAGE_KEY_RE.test(key || "")) throw new Error("存储键非法（字母数字开头 ≤64，允许 . _ -）");
    return path.join(this.storageDir(), key + ".json");
  }
  storageGet(key: string): unknown {
    const file = this.storagePath(key);
    if (!fs.existsSync(file)) return null;
    return JSON.parse(fs.readFileSync(file, "utf8"));
  }
  storageSet(key: string, value: unknown): number {
    const file = this.storagePath(key);
    const text = JSON.stringify(value);
    if (Buffer.byteLength(text, "utf8") > MAX_STORAGE_VALUE_BYTES) throw new Error("值超过上限");
    const keys = fs.readdirSync(this.storageDir()).filter((f) => f.endsWith(".json"));
    if (keys.length >= MAX_STORAGE_KEYS && !fs.existsSync(file)) throw new Error("存储键数量超过上限");
    fs.writeFileSync(file + ".tmp", text);
    fs.renameSync(file + ".tmp", file);
    return Buffer.byteLength(text, "utf8");
  }
  storageDelete(key: string): boolean {
    const file = this.storagePath(key);
    if (!fs.existsSync(file)) return false;
    fs.unlinkSync(file);
    return true;
  }
  storageList(prefix = ""): string[] {
    return fs.readdirSync(this.storageDir()).filter((f) => f.endsWith(".json"))
      .map((f) => f.slice(0, -5)).filter((k) => k.startsWith(prefix)).sort();
  }
  // ---------------- config：操作员值（引擎，只读）+ 插件自己的覆盖层 ----------------
  private configPath(): string { return path.join(this.dataDir, "config.json"); }
  private configOverlay(): Record<string, unknown> {
    try { return JSON.parse(fs.readFileSync(this.configPath(), "utf8")) as Record<string, unknown>; }
    catch { return {}; }
  }
  async configGet(keys?: string[]): Promise<Record<string, unknown>> {
    const res = await this.client.engineOp("config.get", {});
    const operator = (res && (res.values as Record<string, unknown>)) || {};
    const merged: Record<string, unknown> = { ...this.configOverlay(), ...operator };
    if (keys && keys.length) {
      const out: Record<string, unknown> = {};
      for (const k of keys) if (k in merged) out[k] = merged[k];
      return out;
    }
    return merged;
  }
  configSet(values: Record<string, unknown>): string[] {
    const overlay = this.configOverlay();
    for (const [k, v] of Object.entries(values)) {
      if (!STORAGE_KEY_RE.test(k)) throw new Error("配置键非法: " + k);
      if (Buffer.byteLength(JSON.stringify(v), "utf8") > MAX_CONFIG_VALUE_BYTES) throw new Error("配置值超过上限: " + k);
      overlay[k] = v;
    }
    if (Object.keys(overlay).length > MAX_CONFIG_KEYS) throw new Error("配置键数量超过上限");
    fs.writeFileSync(this.configPath(), JSON.stringify(overlay));
    return Object.keys(values).sort();
  }
}

/** 协议客户端：一行一个 JSON，id 命名空间分离，支持反向 engine op。 */
export class ProtocolClient {
  private seq = 0;
  private pending = new Map<number, (msg: any) => void>();
  private onRequest: ((msg: any) => void) | null = null;
  private ready = false;

  start(onRequest: (msg: any) => void): void {
    this.onRequest = onRequest;
    const rl = readline.createInterface({ input: process.stdin, terminal: false });
    rl.on("line", (line: string) => {
      let msg: any;
      try { msg = JSON.parse(line); } catch { return; }
      if (!msg || typeof msg !== "object") return;
      if (typeof msg.id === "number" && this.pending.has(msg.id) && msg.method === undefined) {
        const resolve = this.pending.get(msg.id)!;
        this.pending.delete(msg.id);
        // 与 Python runner 同一口径：把 result 载荷交给调用方；error 归一成 {ok:false,error}
        if (msg.error) resolve({ ok: false, error: String(msg.error) });
        else resolve(msg.result !== undefined ? msg.result : { ok: false, error: "empty result" });
        return;
      }
      if (typeof msg.id === "number" && msg.method) {
        if (this.onRequest) this.onRequest(msg);
      }
    });
    this.ready = true;
  }
  private write(obj: unknown): void {
    process.stdout.write(JSON.stringify(obj) + "\n");
  }
  reply(id: number, result: unknown): void { this.write({ id, result }); }
  fail(id: number, message: string): void { this.write({ id, error: String(message).slice(0, 800) }); }
  /** 引擎 → 插件 的请求（initialize/event/health/shutdown/hook）。 */
  request(method: string, params: Record<string, unknown> = {}): Promise<any> {
    const id = ++this.seq;
    return new Promise((resolve) => {
      this.pending.set(id, resolve);
      this.write({ id, method, params });
    });
  }
  /** 插件 → 引擎 的反向 op（config / permission / context）。 */
  engineOp(op: string, args: Record<string, unknown> = {}): Promise<any> {
    const id = ACTION_ID_BASE + (++this.seq);
    return new Promise((resolve) => {
      this.pending.set(id, resolve);
      this.write({ id, method: "engine", params: { op, args } });
    });
  }
  /** 插件 → 引擎 的 action（副作用出口）。 */
  action(type: string, params: Record<string, unknown> = {}): Promise<any> {
    const id = ACTION_ID_BASE + (++this.seq);
    return new Promise((resolve) => {
      this.pending.set(id, resolve);
      this.write({ id, method: "action", params: { action: type, payload: params } });
    });
  }
  get isReady(): boolean { return this.ready; }
}

type MessageHook = (ctx: PluginContext, event: any) => unknown | Promise<unknown>;
type LifecycleHook = (ctx: PluginContext) => void | Promise<void>;
type WebuiHandler = (args: Record<string, any>) => unknown;

/** 插件主体：注册钩子 → run() 进入协议主循环。 */
export class FloweriePlugin {
  private client = new ProtocolClient();
  private context: PluginContext;
  private caps: string[];
  private messageHooks: MessageHook[] = [];
  private eventHooks = new Map<string, MessageHook[]>();
  private startupHooks: LifecycleHook[] = [];
  private shutdownHooks: LifecycleHook[] = [];
  private healthHooks: Array<() => boolean | void> = [];
  private hooks = new Map<string, (...args: unknown[]) => unknown>();
  private webuiHandlers = new Map<string, WebuiHandler>();

  constructor(opts: { capabilities?: string[]; pluginId?: string; pluginDir?: string } = {}) {
    const groups = opts.capabilities && opts.capabilities.length
      ? opts.capabilities
      : Object.keys(CAPABILITY_GROUPS);
    this.caps = [...new Set(groups.flatMap((g) => CAPABILITY_GROUPS[g] || []))]
      .filter((m) => (OPTIONAL_METHODS as readonly string[]).includes(m)).sort();
    const dir = opts.pluginDir || process.env.FLOWERIE_PLUGIN_DIR || process.cwd();
    this.context = new PluginContext(this.client, opts.pluginId || "unknown", dir,
      path.join(dir, "data"), {});
  }

  onMessage(fn: MessageHook): this { this.messageHooks.push(fn); return this; }
  on(event: string, fn: MessageHook): this {
    const list = this.eventHooks.get(event) || [];
    list.push(fn);
    this.eventHooks.set(event, list);
    return this;
  }
  onStartup(fn: LifecycleHook): this { this.startupHooks.push(fn); return this; }
  onShutdown(fn: LifecycleHook): this { this.shutdownHooks.push(fn); return this; }
  /** 心跳钩子（Python 侧对应 health_check）：返回 false 即视为不健康。 */
  onHealth(fn: () => boolean | void): this { this.healthHooks.push(fn); return this; }
  // 与 Python SDK 的具名钩子对齐（协议层就是 event 名字，on() 是通用入口）
  onCommand(fn: MessageHook): this { return this.on("command", fn); }
  onNotice(fn: MessageHook): this { return this.on("notice", fn); }
  onRequest(fn: MessageHook): this { return this.on("request", fn); }
  onLifecycle(fn: MessageHook): this { return this.on("lifecycle", fn); }
  onSchedule(fn: MessageHook): this { return this.on("schedule", fn); }
  /** 注册一个可被控制面调用的 hook（插件 WebUI 的数据钩子等）。 */
  registerHook(name: string, fn: (...args: unknown[]) => unknown): this {
    this.hooks.set(name, fn);
    return this;
  }

  /** Plugin WebUI Protocol（任务书第 3 份 §六）：注册页面/动作/资源处理器。
   *
   * 处理器拿到的是**引擎给的受控参数**（page / context，action 时还有 action / form），
   * 返回字符串（= `{html: ...}` 简写）或对象（html / vars / message /
   * content_type / body / base64 / config_set / storage_set）。
   * 路由、权限、校验、净化、隔离全部由引擎负责，插件只负责内容。
   */
  readonly webui = {
    page: (fn: WebuiHandler): this => this.registerWebui("webui.page", fn),
    action: (fn: WebuiHandler): this => this.registerWebui("webui.action", fn),
    asset: (fn: WebuiHandler): this => this.registerWebui("webui.asset", fn),
  };

  /** 按协议方法名注册 WebUI 处理器（`plugin.webui.page(...)` 是它的语义化包装）。 */
  registerWebui(method: string, fn: WebuiHandler): this {
    if (!(WEBUI_METHODS as readonly string[]).includes(method)) {
      throw new Error("未知 WebUI 方法: " + method);
    }
    this.webuiHandlers.set(method, fn);
    return this;
  }
  get ctx(): PluginContext { return this.context; }

  async run(): Promise<void> {
    this.client.start((msg) => { void this.handle(msg); });
    await new Promise<void>((resolve) => {
      process.stdin.on("end", () => resolve());
      process.on("SIGTERM", () => resolve());
    });
  }

  private async handle(msg: any): Promise<void> {
    const id = msg.id as number;
    const method = String(msg.method || "");
    const params = (msg.params || {}) as any;
    try {
      switch (method) {
        case "initialize": {
          const ctxIn = params.context || {};
          const dir = ctxIn.plugin_dir || this.context.pluginDir;
          this.context = new PluginContext(this.client, ctxIn.plugin_id || this.context.pluginId, dir,
            ctxIn.data_dir || path.join(dir, "data"), {});
          for (const fn of this.startupHooks) await fn(this.context);
          this.client.reply(id, {
            ok: true, api_version: API_VERSION, protocol_version: PROTOCOL_VERSION,
            capabilities: this.caps,
          });
          return;
        }
        case "event": {
          const actions = await this.dispatchEvent(String(params.event || ""), params.payload || {});
          this.client.reply(id, { actions });
          return;
        }
        case "health": {
          let healthy = true;
          for (const fn of this.healthHooks) {
            try {
              if (fn() === false) healthy = false;
            } catch (err: any) {
              healthy = false;
            }
          }
          this.client.reply(id, healthy ? { ok: true } : { ok: false, error: "health check failed" });
          return;
        }
        case "shutdown":
          for (const fn of this.shutdownHooks) await fn(this.context);
          this.client.reply(id, { ok: true });
          return;
        case "hook": {
          const name = String(params.name || "");
          if (!/^[a-z_][a-z0-9_]{0,63}$/.test(name)) { this.client.fail(id, "hook 名非法"); return; }
          const fn = this.hooks.get(name);
          if (!fn) { this.client.reply(id, { ok: true, result: null }); return; }
          try {
            const result = await fn(...(params.args || []));
            this.client.reply(id, { ok: true, result: result === undefined ? null : result });
          } catch (err: any) {
            this.client.reply(id, { ok: false, error: String(err && err.message || err) });
          }
          return;
        }

        // ---- WebUI Protocol（任务书第 3 份 §三）：引擎 → 插件的页面/动作/资源请求 ----
        case "webui.page":
        case "webui.action":
        case "webui.asset": {
          const fn = this.webuiHandlers.get(method);
          if (!fn) {
            this.client.reply(id, { ok: false, error: "插件未注册 " + method + " 处理器" });
            return;
          }
          try {
            this.client.reply(id, normalizeWebuiResult(await fn(params as Record<string, unknown>)));
          } catch (err: any) {
            this.client.reply(id, { ok: false, error: String(err && err.message || err) });
          }
          return;
        }
        // ---- 可选方法 ----
        case "storage.get": {
          try { this.client.reply(id, { ok: true, value: this.context.storageGet(String(params.key || "")) }); }
          catch (err: any) { this.client.reply(id, { ok: false, error: String(err.message || err) }); }
          return;
        }
        case "storage.set": {
          try {
            const size = this.context.storageSet(String(params.key || ""), params.value);
            this.client.reply(id, { ok: true, size });
          } catch (err: any) { this.client.reply(id, { ok: false, error: String(err.message || err) }); }
          return;
        }
        case "storage.delete": {
          try { this.client.reply(id, { ok: true, deleted: this.context.storageDelete(String(params.key || "")) }); }
          catch (err: any) { this.client.reply(id, { ok: false, error: String(err.message || err) }); }
          return;
        }
        case "storage.list": {
          try { this.client.reply(id, { ok: true, keys: this.context.storageList(String(params.prefix || "")) }); }
          catch (err: any) { this.client.reply(id, { ok: false, error: String(err.message || err) }); }
          return;
        }
        case "config.get": {
          const keys = Array.isArray(params.keys) ? params.keys.map(String) : undefined;
          this.client.reply(id, { ok: true, values: await this.context.configGet(keys) });
          return;
        }
        case "config.set": {
          if (!params.values || typeof params.values !== "object") {
            this.client.reply(id, { ok: false, error: "config.set 需要 values 对象" });
            return;
          }
          try { this.client.reply(id, { ok: true, saved: this.context.configSet(params.values) }); }
          catch (err: any) { this.client.reply(id, { ok: false, error: String(err.message || err) }); }
          return;
        }
        case "permission.check": {
          const res = await this.client.engineOp("permission.check", { permission: String(params.permission || "") });
          this.client.reply(id, res);
          return;
        }
        case "context.get": {
          const res = await this.client.engineOp("context.get", {});
          this.client.reply(id, res);
          return;
        }
        default:
          this.client.fail(id, "未知方法: " + JSON.stringify(method));
      }
    } catch (err: any) {
      this.client.fail(id, "runner 异常: " + String(err && err.message || err));
    }
  }

  private async dispatchEvent(event: string, payload: any): Promise<Action[]> {
    const eventObj = { event, plugin_id: this.context.pluginId, ...payload };
    const handlers = event === "message" ? this.messageHooks : (this.eventHooks.get(event) || []);
    const actions: Action[] = [];
    for (const fn of handlers) {
      const result = await fn(this.context, eventObj);
      if (!result) continue;
      if (Array.isArray(result)) actions.push(...(result as Action[]));
      else actions.push(result as Action);
    }
    return actions;
  }
}
