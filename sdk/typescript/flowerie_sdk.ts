/**
 * @flowerie/sdk —— Flowerie Plugin Protocol v1 的 TypeScript / Node.js 实现。
 *
 * 零 npm 依赖：只用 node 内置模块（readline / fs / path）。
 * 协议规范见 docs/plugin-protocol.md；与 Python runner 的行为由
 * tests/test_plugin_sdk_contract.py + tests/fixtures/plugin_protocol_vectors.json 交叉验证。
 * Plugin-to-Plugin 通信（任务书《通信》§五-§二十七）见 docs/plugin-communication.md：
 * plugin.call / plugin.emit / plugin.on / plugin.expose / plugin.cancel，跨语言一律经 Core Router。
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
  "plugin.call", "plugin.event", "plugin.cancel",
] as const;
/** WebUI Protocol 方法（任务书第 3 份 §三）：与其它语言 SDK 同名同义。 */
export const WEBUI_METHODS = ["webui.page", "webui.action", "webui.asset"] as const;
/** Plugin-to-Plugin 通信方法（任务书第 4 份 §十）：CALL / EVENT / CANCEL 语义互不混用。 */
export const PLUGIN_METHODS = ["plugin.call", "plugin.event", "plugin.cancel"] as const;
/** 路由策略（§十三）：默认 auto；测试用 core 验证统一协议路径，local 是同进程托管时的保留通道。 */
export const ROUTE_POLICIES = ["auto", "core", "local"] as const;
/** 结构化错误码（§二十一 十个 + §十七 生命周期 + §二十二 循环保护）：与 comm.ERROR_CODES 同源。 */
export const ERROR_CODES = [
  "PLUGIN_NOT_FOUND", "PLUGIN_NOT_READY", "METHOD_NOT_FOUND", "PERMISSION_DENIED",
  "INVALID_ARGUMENT", "TIMEOUT", "CANCELLED", "SERIALIZATION_ERROR", "PLUGIN_ERROR",
  "INTERNAL_ERROR", "PLUGIN_UNAVAILABLE", "PLUGIN_CALL_LOOP",
] as const;
/** 默认超时（毫秒，§十八）：与 comm.DEFAULT_TIMEOUT_MS 同源。 */
export const DEFAULT_TIMEOUT_MS = 5000;
/** 循环保护（§二十二）：hop_count 由 SDK 直传，+1 由引擎负责；超过上限回 PLUGIN_CALL_LOOP。 */
export const MAX_HOP_COUNT = 8;
/** 入站消息嵌套深度上限：防退化递归（正常链路远小于此，与 Python runner 同口径）。 */
const MAX_INBOUND_DEPTH = 16;
/** 已取消 request_id 的记忆上限：有界，不无限增长（§十八）。 */
const MAX_CANCELLED_IDS = 256;
export const CAPABILITY_GROUPS: Record<string, string[]> = {
  context: ["context.get"],
  config: ["config.get", "config.set"],
  permission: ["permission.check"],
  storage: ["storage.get", "storage.set", "storage.delete", "storage.list"],
  webui: ["webui.page", "webui.action", "webui.asset"],
  plugin: ["plugin.call", "plugin.event", "plugin.cancel"],
};
const STORAGE_KEY_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const MAX_STORAGE_KEYS = 200;
const MAX_STORAGE_VALUE_BYTES = 64 * 1024;
const MAX_CONFIG_KEYS = 64;
const MAX_CONFIG_VALUE_BYTES = 8 * 1024;


// ==================== Plugin-to-Plugin 通信（任务书第 4 份） ====================
// 语义与 Python runner / Go / Rust / Java SDK 完全一致：只有一种线格式（JSON-Lines）
// 与一套消息模型；跨语言一律经 Core Router，SDK 里没有任何绕过 Core 的直连通道。

/** 调用方/被调方身份（§四）；source 由**引擎按连接**填写，插件自报的一律被覆盖。 */
export interface CommSource { plugin_id?: string; runtime?: string; instance_id?: string }

/** §六 请求模型：expose() 的 handler 收到的是**完整请求模型**（不是裸 params）。 */
export interface CommRequest {
  request_id?: string;
  source?: CommSource;
  target?: CommSource | string;
  method?: string;
  params?: unknown;
  timeout?: number;
  trace_id?: string;
  call_id?: string;
  hop_count?: number;
  route?: string;
  metadata?: Record<string, unknown>;
}

/** §九/§十 事件模型：plugin.on() 的 handler 收到的是完整事件模型。 */
export interface CommEvent {
  event_id?: string;
  name?: string;
  payload?: unknown;
  source?: CommSource;
  trace_id?: string;
  hop_count?: number;
  metadata?: Record<string, unknown>;
}

/** 结构化错误载荷（§七/§二十一）：code 一定是 12 个错误码之一。 */
export interface CommErrorData { code: string; message: string; data: Record<string, unknown> }

/** plugin.call() 的可选策略：timeout（毫秒，默认 5000）与 route（auto|core|local）。 */
export interface CommCallOptions { timeout?: number; route?: string }

/** plugin.emit() 的结果（§九）：广播是**事件**，不是 RPC，所以不抛异常。 */
export interface CommEmitResult {
  ok: boolean;
  delivered: number;
  failed: Array<Record<string, unknown>>;
  error?: CommErrorData;
  trace_id?: string;
}

/** plugin.cancel() 的结果（§十八）。 */
export interface CommCancelResult {
  ok: boolean;
  cancelled: boolean;
  request_id?: string;
  target?: string;
  error?: CommErrorData;
}

/** expose 的 handler 签名：(完整请求模型, 插件实例)，返回值就是 CALL 的 result。 */
export type CommHandler = (request: CommRequest, plugin: FloweriePlugin) => unknown | Promise<unknown>;

/** 当前入站消息的 trace 上下文（§二十二/§二十三）：出站调用自动带上。 */
export interface CommTraceContext {
  trace_id: string;
  hop_count: number;
  source: CommSource;
  request_id: string;
}

/** 插件间通信失败（§七/§二十一）：TS 侧的原生异常形态。
 *
 * 引擎返回的永远是响应模型（跨语言没有异常这个东西）；SDK 负责把它转成本语言的异常，
 * 错误码原样保留 12 个码之一，**不允许退化成字符串**。message 保持引擎给的原话，
 * String(err) 与 Python 的 str(exc) 同形（CODE: message）。
 */
export class PluginCommError extends Error {
  readonly code: string;
  readonly data: Record<string, unknown>;
  constructor(code: string, message: string, data?: Record<string, unknown> | null) {
    const raw = code === undefined || code === null ? "" : String(code);
    const normalized = (ERROR_CODES as readonly string[]).includes(raw) ? raw : "INTERNAL_ERROR";
    super(message === undefined || message === null ? "" : String(message));
    this.name = "PluginCommError";
    this.code = normalized;
    this.data = data && typeof data === "object" && !Array.isArray(data)
      ? { ...(data as Record<string, unknown>) } : {};
  }
  toString(): string { return this.code + ": " + this.message; }
}

const COMM_NAME_RE = /^[A-Za-z_][A-Za-z0-9_.]{0,95}$/;

/** Python str(x or "") 的等价：null/undefined 归一成空串（身份/方法名/request_id）。 */
function asString(value: unknown): string {
  return value === undefined || value === null ? "" : String(value);
}

/** 超时归一（与 comm.normalize_timeout_ms 的**入参**口径一致）：0/空 -> 默认值，非法 -> 结构化错误。 */
function normalizeTimeout(value: unknown): number {
  if (value === undefined || value === null || value === 0 || value === false) return DEFAULT_TIMEOUT_MS;
  const ms = Number(value);
  if (!Number.isFinite(ms)) {
    throw new PluginCommError("INVALID_ARGUMENT", "timeout 必须是毫秒数字: " + String(value),
      { timeout: String(value) });
  }
  return ms;
}

/** hop_count 归一：非数字/NaN 一律按 0（与 Python int(x or 0) 的容错一致）。 */
function toHopCount(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return Math.trunc(value);
  if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) {
    return Math.trunc(Number(value));
  }
  return 0;
}

/** §十九/§二十 线格式校验：只允许语言无关数据类型，语言内部对象一律拒绝。
 *
 * 与 Python 的 json.dumps 口径一致但要**显式**：undefined / 函数 / symbol / BigInt /
 * 非有限数字 / class 实例（Map、Set、Date、Buffer…）不会被悄悄丢掉或 toString，
 * 而是抛 SERIALIZATION_ERROR（引擎边界同样会拒绝）。
 */
function wireCopy(value: unknown, path: string): unknown {
  if (value === null || typeof value === "boolean" || typeof value === "string") return value;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new PluginCommError("SERIALIZATION_ERROR", "数字必须是有限值: " + path, { path });
    }
    return value;
  }
  if (Array.isArray(value)) return value.map((item, i) => wireCopy(item, path + "[" + i + "]"));
  if (typeof value === "object") {
    const proto = Object.getPrototypeOf(value);
    if (proto !== Object.prototype && proto !== null) {
      const ctor = (value as { constructor?: { name?: string } }).constructor;
      throw new PluginCommError("SERIALIZATION_ERROR",
        "不允许传语言内部对象（只允许 JSON 值）: " + path + " -> " + ((ctor && ctor.name) || "object"),
        { path });
    }
    const out: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      if (item === undefined) {
        throw new PluginCommError("SERIALIZATION_ERROR",
          "undefined 字段会被 JSON 悄悄丢掉: " + path + "." + key, { path: path + "." + key });
      }
      out[key] = wireCopy(item, path + "." + key);
    }
    return out;
  }
  throw new PluginCommError("SERIALIZATION_ERROR",
    "不支持的类型 " + typeof value + ": " + path, { path });
}

/** 把引擎的错误载荷（{code,message,data} 或字符串）转成本语言的结构化错误（§七/§二十一）。 */
export function pluginCommErrorFrom(error: unknown, message = "插件调用失败"): PluginCommError {
  if (error instanceof PluginCommError) return error;
  if (error && typeof error === "object") {
    const src = error as Record<string, unknown>;
    const code = asString(src.code);
    if (code) {
      return new PluginCommError(code, asString(src.message) || code,
        (src.data && typeof src.data === "object" && !Array.isArray(src.data))
          ? src.data as Record<string, unknown> : {});
    }
  }
  return new PluginCommError("PLUGIN_ERROR", typeof error === "string" && error ? error : message, {});
}

/** 结构化错误载荷（回给引擎的响应模型里用它）。 */
function commFailure(code: string, message: string, data?: Record<string, unknown>): Record<string, unknown> {
  return { ok: false, error: { code, message, data: data || {} } };
}

function toCommErrorData(error: unknown): CommErrorData {
  const err = pluginCommErrorFrom(error);
  return { code: err.code, message: err.message, data: err.data };
}

/** handler 抛异常时的消息文本：与 Python "%s: %s" % (type(e).__name__, e) 同形。 */
function errorText(err: unknown): string {
  if (err instanceof PluginCommError) return err.toString();
  if (err instanceof Error) return (err.name || "Error") + ": " + err.message;
  return String(err);
}

/** plugin.emit() 的结果归一（广播失败**不抛**，失败信息保持结构化，§九/§二十一）。 */
function normalizeEmitResult(res: unknown): CommEmitResult {
  const src = (res && typeof res === "object") ? res as Record<string, unknown> : {};
  const out: CommEmitResult = {
    ok: src.ok === true,
    delivered: typeof src.delivered === "number" && Number.isFinite(src.delivered) ? src.delivered : 0,
    failed: Array.isArray(src.failed) ? src.failed as Array<Record<string, unknown>> : [],
  };
  if (src.error !== undefined) out.error = toCommErrorData(src.error);
  if (typeof src.trace_id === "string" && src.trace_id) out.trace_id = src.trace_id;
  return out;
}

/** plugin.cancel() 的结果归一（§十八）。 */
function normalizeCancelResult(res: unknown): CommCancelResult {
  const src = (res && typeof res === "object") ? res as Record<string, unknown> : {};
  const out: CommCancelResult = { ok: src.ok === true, cancelled: src.cancelled === true };
  if (typeof src.request_id === "string" && src.request_id) out.request_id = src.request_id;
  if (typeof src.target === "string" && src.target) out.target = src.target;
  if (src.error !== undefined) out.error = toCommErrorData(src.error);
  return out;
}

/** WebUI 应答允许透传的字段（其余字段一律丢弃，不把插件内部对象塞进协议）。 */
const WEBUI_PAYLOAD_KEYS = ["html", "vars", "context", "message", "content_type", "body",
  "base64", "config_set", "storage_set"];

function normalizeWebuiResult(result: unknown): Record<string, unknown> {
  if (typeof result === "string") return { ok: true, html: result };
  if (result && typeof result === "object") {
    const src = result as Record<string, unknown>;
    if (src.ok === false) {
      return { ok: false, error: String(src.error || "插件返回 ok=false") };
    }
    const out: Record<string, unknown> = { ok: true };
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
  /** 被调方：method -> handler（plugin.expose 注册，§五 CALL 的被调方）。 */
  private exposedHandlers = new Map<string, CommHandler>();
  /** 入站消息栈（trace/hop 传播，§二十二/§二十三）：嵌套调用期间链路连续。 */
  private inboundStack: CommTraceContext[] = [];
  /** 已取消的 request_id（§十八）：有界记忆，避免无限增长。 */
  private cancelledRequests = new Set<string>();

  constructor(opts: { capabilities?: string[]; pluginId?: string; pluginDir?: string } = {}) {
    const groups = opts.capabilities && opts.capabilities.length
      ? opts.capabilities
      : Object.keys(CAPABILITY_GROUPS);
    this.caps = [...new Set(groups.flatMap((g) => CAPABILITY_GROUPS[g] || []))]
      .filter((m) => (OPTIONAL_METHODS as readonly string[]).includes(m)).sort();
    const dir = opts.pluginDir || process.env.FLOWERIE_PLUGIN_DIR || process.cwd();
    // plugin_id 优先级：显式传入 > 宿主注入的环境变量 > 占位符（引擎在 initialize 里给的值会覆盖它）
    this.context = new PluginContext(this.client,
      opts.pluginId || process.env.FLOWERIE_PLUGIN_ID || "unknown", dir,
      path.join(dir, "data"), {});
  }

  onMessage(fn: MessageHook): this { this.messageHooks.push(fn); return this; }
  /** 订阅具名事件。两类来源共用同一张注册表：
   *
   * - 引擎事件（message / command / notice / request / lifecycle / schedule）：
   *   handler 收 (ctx, { event, plugin_id, ...payload })，返回值是 action；
   * - 插件间事件（plugin.event，任务书第 4 份 §九）：handler 收 (ctx, 完整事件模型)
   *   即 { event_id, name, payload, source, trace_id, hop_count, metadata }，
   *   事件名 "*" 匹配全部插件间事件。
   */
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

  // ================= Plugin-to-Plugin 通信（任务书第 4 份 §五-§二十七） =================
  /** 调用其它插件的暴露方法（§五/§六/§七）：成功返回 result，失败抛 PluginCommError。
   *
   * opts 支持 { timeout, route }（route: auto|core|local，默认 auto）；跨语言一律经 Core
   * Router，SDK 不做任何自动重试（§八：避免插件之间形成请求风暴）。
   * 处理入站消息期间发起的调用会自动带上当前 trace_id/hop_count（§二十三），
   * +1 由引擎负责。
   */
  async call(target: string, method: string, params: unknown = {},
             opts: CommCallOptions | number = {}): Promise<any> {
    const options: CommCallOptions = typeof opts === "number" ? { timeout: opts } : (opts || {});
    const trace = this.commTrace();
    const args: Record<string, unknown> = {
      target: asString(target),
      method: asString(method),
      params: params === undefined || params === null ? {} : wireCopy(params, "params"),
      timeout: normalizeTimeout(options.timeout),
      route: asString(options.route) || "auto",
      trace_id: trace.trace_id,
      hop_count: trace.hop_count,
    };
    const res = await this.client.engineOp("plugin.call", args);
    const response = (res && typeof res === "object") ? res as Record<string, unknown> : {};
    if (response.ok !== true) throw pluginCommErrorFrom(response.error, "插件调用失败");
    return response.result === undefined ? null : response.result;
  }

  /** 广播事件给所有订阅者（§九）：返回 { ok, delivered, failed }；失败不抛，错误保持结构化。 */
  async emit(name: string, payload: unknown = {}): Promise<CommEmitResult> {
    const trace = this.commTrace();
    const res = await this.client.engineOp("plugin.emit", {
      name: asString(name),
      payload: payload === undefined || payload === null ? {} : wireCopy(payload, "payload"),
      trace_id: trace.trace_id,
      hop_count: trace.hop_count,
    });
    return normalizeEmitResult(res);
  }

  /** 暴露一个可被其它插件调用的方法（§五 CALL 的被调方）；handler 传 null 表示注销。 */
  expose(method: string, handler: CommHandler | null = null): this {
    const name = asString(method);
    if (!COMM_NAME_RE.test(name)) {
      throw new PluginCommError("INVALID_ARGUMENT",
        "方法名非法（字母/下划线开头，允许 . _，≤96）: " + JSON.stringify(name), { method: name });
    }
    if (handler === null || handler === undefined) {
      this.exposedHandlers.delete(name);
      return this;
    }
    if (typeof handler !== "function") {
      throw new PluginCommError("INVALID_ARGUMENT", "handler 必须是函数: " + name, { method: name });
    }
    this.exposedHandlers.set(name, handler);
    return this;
  }

  /** 取消自己发起的一次在途调用（§十八）；目标插件收到 CANCEL 后应尽可能停止。 */
  async cancel(requestId: string, reason = ""): Promise<CommCancelResult> {
    const res = await this.client.engineOp("plugin.cancel", {
      request_id: asString(requestId),
      reason: asString(reason),
    });
    return normalizeCancelResult(res);
  }

  /** 当前入站消息的 trace/hop（§二十二/§二十三）：出站调用自动带上，插件作者不用写 trace 代码。 */
  commTrace(): CommTraceContext {
    const frame = this.inboundStack.length ? this.inboundStack[this.inboundStack.length - 1] : null;
    return frame
      ? { trace_id: frame.trace_id, hop_count: frame.hop_count,
          source: frame.source, request_id: frame.request_id }
      : { trace_id: "", hop_count: 0, source: {}, request_id: "" };
  }

  /** 已暴露的方法名（升序）：METHOD_NOT_FOUND 的 data.exposed 与自检都用它。 */
  exposedMethods(): string[] { return [...this.exposedHandlers.keys()].sort(); }

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
        // ---- Plugin-to-Plugin 通信（任务书第 4 份 §十）：引擎 → 插件的 CALL / EVENT / CANCEL ----
        case "plugin.call": {
          await this.handleInboundCall(id, params as Record<string, unknown>);
          return;
        }
        case "plugin.event": {
          await this.handleInboundEvent(id, params as Record<string, unknown>);
          return;
        }
        case "plugin.cancel": {
          this.handleInboundCancel(id, params as Record<string, unknown>);
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

  // ---------- 入站 CALL / EVENT / CANCEL（§十）：不丢消息、不阻塞后续消息 ----------
  /** 入站 CALL：查 expose 注册表 → handler（收到**完整请求模型**）→ 应答（§五/§六/§七）。 */
  private async handleInboundCall(id: number, params: Record<string, unknown>): Promise<void> {
    const requestId = asString(params.request_id);
    const method = asString(params.method);
    const frame = this.pushInbound(params, requestId);
    try {
      if (requestId && this.cancelledRequests.has(requestId)) {
        this.cancelledRequests.delete(requestId);
        this.client.reply(id, commFailure("CANCELLED", "调用已被取消"));
        return;
      }
      const handler = this.exposedHandlers.get(method);
      if (!handler) {
        this.client.reply(id, commFailure("METHOD_NOT_FOUND", "插件未暴露方法: " + method,
          { method, exposed: this.exposedMethods() }));
        return;
      }
      let result: unknown;
      try {
        result = await handler(params as CommRequest, this);
      } catch (err) {
        // handler 异常 -> 结构化 PLUGIN_ERROR（不杀进程、不退化成字符串）
        this.client.reply(id, commFailure("PLUGIN_ERROR", errorText(err)));
        return;
      }
      try {
        const wire = result === undefined ? null : wireCopy(result, "result");
        this.client.reply(id, { ok: true, result: wire });
      } catch (err) {
        // 返回值无法序列化 -> SERIALIZATION_ERROR（§十九/§二十）
        const failure = err instanceof PluginCommError ? err : pluginCommErrorFrom(err);
        this.client.reply(id, commFailure(
          failure.code === "PLUGIN_ERROR" ? "SERIALIZATION_ERROR" : failure.code,
          failure.message, failure.data));
      }
    } finally {
      this.popInbound(frame);
    }
  }

  /** 入站 EVENT：投给 on() 注册的 handler（"*" 匹配全部），回 { ok, handled }（§九）。 */
  private async handleInboundEvent(id: number, params: Record<string, unknown>): Promise<void> {
    const name = asString(params.name);
    const frame = this.pushInbound(params, "");
    try {
      const handlers = [...(this.eventHooks.get(name) || [])];
      if (name !== "*") handlers.push(...(this.eventHooks.get("*") || []));
      let handled = 0;
      for (const fn of handlers) {
        try {
          await fn(this.context, params);
          handled += 1;
        } catch {
          // 单个订阅者异常不影响其它订阅者，也不计入 handled（与 Python 的计数口径一致）
        }
      }
      this.client.reply(id, { ok: true, handled });
    } finally {
      this.popInbound(frame);
    }
  }

  /** 入站 CANCEL：记录 request_id（有界记忆），回 { ok: true, cancelled }（§十八）。 */
  private handleInboundCancel(id: number, params: Record<string, unknown>): void {
    const requestId = asString(params.request_id);
    if (requestId) {
      this.cancelledRequests.add(requestId);
      if (this.cancelledRequests.size > MAX_CANCELLED_IDS) this.cancelledRequests.clear();
    }
    this.client.reply(id, { ok: true, cancelled: Boolean(requestId) });
  }

  /** 入站消息入栈：trace/hop 传播（§二十二/§二十三）；深度超限只影响 trace，不丢消息。 */
  private pushInbound(params: Record<string, unknown>, requestId: string): CommTraceContext {
    const source = (params.source && typeof params.source === "object")
      ? params.source as CommSource : {};
    const frame: CommTraceContext = {
      trace_id: asString(params.trace_id),
      hop_count: toHopCount(params.hop_count),
      source,
      request_id: requestId,
    };
    if (this.inboundStack.length < MAX_INBOUND_DEPTH) this.inboundStack.push(frame);
    return frame;
  }

  private popInbound(frame: CommTraceContext): void {
    const idx = this.inboundStack.lastIndexOf(frame);
    if (idx >= 0) this.inboundStack.splice(idx, 1);
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
