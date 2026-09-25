package dev.flowerie.sdk;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.function.BiFunction;
import java.util.function.Function;
import java.util.regex.Pattern;

/**
 * Flowerie Plugin Protocol v1 的 Java SDK（**零第三方依赖**，只用 JDK）。
 *
 * <p>协议规范：docs/plugin-protocol.md。与 Python / TypeScript / Go / Rust 示例的行为一致性由
 * {@code tests/test_plugin_sdk_contract.py} 用真进程 + 真管道比对（同一批向量）。
 *
 * <p>Plugin-to-Plugin 通信（任务书《通信》§五–§二十七，规范：docs/plugin-communication.md）：
 * {@link #call} / {@link #emit} / {@link #on} / {@link #expose} / {@link #cancel} 五个入口，
 * 与 Python / TypeScript / Go / Rust SDK 语义完全一致 —— 出站只走引擎反向 op（没有、也不允许
 * 绕过 Core 的直连通道，§十二/§二十六），失败一律是结构化 {@link PluginCommException}。
 */
public class FloweriePlugin {

    public static final String PROTOCOL_VERSION = "1";
    public static final String API_VERSION = "1";
    public static final int ACTION_ID_BASE = 1000000;
    private static final int MAX_STORAGE_KEYS = 200;
    private static final int MAX_STORAGE_VALUE = 64 * 1024;
    private static final int MAX_CONFIG_KEYS = 64;
    private static final int MAX_CONFIG_VALUE = 8 * 1024;
    private static final Pattern KEY_RE = Pattern.compile("^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$");

    // ================= Plugin-to-Plugin 通信（任务书《通信》§五–§二十七） =================
    // §十：CALL / EVENT / CANCEL 三条入站方法（引擎 → 插件）与三条出站反向 op（插件 → 引擎）
    public static final List<String> PLUGIN_METHODS = List.of(
            "plugin.call", "plugin.event", "plugin.cancel");
    /** 插件间调用的默认超时（毫秒，§十八）；引擎侧还会做上限归一。 */
    public static final int DEFAULT_TIMEOUT_MS = 5000;
    /** 路由策略（§十一/§十三）：auto 默认；core 强制经 Core Router；local 是同进程保留通道。 */
    public static final List<String> ROUTE_POLICIES = List.of("auto", "core", "local");
    /** 循环保护（§二十二）：调用链最大跳数。**引擎强制**，SDK 只负责传播 trace_id / hop_count。 */
    public static final int MAX_HOP_COUNT = 8;
    /** 结构化错误码（§二十一 十个 + §十七 生命周期 + §二十二 循环）：与 src/plugins/comm.py 同源。 */
    public static final List<String> ERROR_CODES = List.of(
            "PLUGIN_NOT_FOUND", "PLUGIN_NOT_READY", "METHOD_NOT_FOUND", "PERMISSION_DENIED",
            "INVALID_ARGUMENT", "TIMEOUT", "CANCELLED", "SERIALIZATION_ERROR", "PLUGIN_ERROR",
            "INTERNAL_ERROR", "PLUGIN_UNAVAILABLE", "PLUGIN_CALL_LOOP");
    /** 暴露方法名 / 事件名格式（与 Python 侧 _valid_comm_name 一致）：字母或下划线开头，允许 . 与 _，≤96。 */
    private static final Pattern COMM_NAME_RE = Pattern.compile("^[A-Za-z_][A-Za-z0-9_.]{0,95}$");
    /** 等待响应期间最多嵌套处理多少层入站消息（防退化递归；正常链路远小于此）。 */
    private static final int MAX_INBOUND_DEPTH = 16;
    /** 取消记录上限（§十八）：有界，不无限增长。 */
    private static final int MAX_CANCELLED_IDS = 256;
    /** 等待响应期间可原地处理的引擎请求（§八/§二十二）：插件间通信三条 + 控制面 hook/health。 */
    private static final List<String> NESTED_METHODS = List.of(
            "plugin.call", "plugin.event", "plugin.cancel", "hook", "health");

    /** 插件间通信失败（§七/§二十一）：引擎返回的永远只有响应模型，SDK 在这里把它变成 Java 异常。
     *
     * <p>错误码是 {@link #ERROR_CODES} 之一（非法值一律归 INTERNAL_ERROR，不制造第十三码）；
     * {@link #getMessage()} 是引擎给的消息，{@link #getData()} 是结构化细节（没有时为空 Map）。
     */
    public static class PluginCommException extends Exception {
        private static final long serialVersionUID = 1L;
        private final String code;
        private final Map<String, Object> data;

        public PluginCommException(String code, String message) {
            this(code, message, null);
        }

        public PluginCommException(String code, String message, Map<String, Object> data) {
            super(message == null ? "" : message);
            this.code = (code != null && ERROR_CODES.contains(code)) ? code : "INTERNAL_ERROR";
            Map<String, Object> copy = new LinkedHashMap<>();
            if (data != null) {
                copy.putAll(data);
            }
            this.data = copy;
        }

        /** §二十一/§十七/§二十二 的 12 个错误码之一。 */
        public String getCode() {
            return code;
        }

        /** 引擎给的消息（不含错误码前缀；错误码请看 {@link #getCode()}）。 */
        @Override
        public String getMessage() {
            return super.getMessage();
        }

        /** 结构化细节（只读拷贝；没有时是空 Map，不是 null）。 */
        public Map<String, Object> getData() {
            return new LinkedHashMap<>(data);
        }

        @Override
        public String toString() {
            return getClass().getName() + ": " + code + ": " + getMessage();
        }
    }

    /** 被其它插件调用的方法处理器（plugin.expose，§五 CALL 的被调方）。
     *
     * <p>参数是**完整请求模型**（request_id / source / target / method / params / timeout /
     * trace_id / call_id / hop_count / route / metadata），返回值就是 CALL 的 result；
     * 返回 Java 内部对象会被边界拦下（SERIALIZATION_ERROR，§十九/§二十）。
     */
    public interface CommHandler {
        Object handle(Map<String, Object> request) throws Exception;
    }

    /** 插件事件订阅处理器（plugin.on，§九）：参数是**完整事件模型**；异常只影响自己这一次投递。 */
    public interface CommEventHandler {
        void handle(Map<String, Object> event) throws Exception;
    }

    /** plugin.call 的可选参数（§六/§十三/§十八）：超时、路由策略、请求 id、metadata。 */
    public static final class CallOptions {
        /** 默认：timeout=5000ms、route=auto、request_id 由引擎生成、metadata 空。 */
        public static final CallOptions DEFAULT = new CallOptions();
        private int timeout = DEFAULT_TIMEOUT_MS;
        private String route = "auto";
        private String requestId = "";
        private Map<String, Object> metadata = new LinkedHashMap<>();

        public CallOptions() {
        }

        public static CallOptions of(int timeoutMs) {
            return new CallOptions().timeout(timeoutMs);
        }

        public static CallOptions of(String route) {
            return new CallOptions().route(route);
        }

        public CallOptions timeout(int timeoutMs) {
            this.timeout = timeoutMs;
            return this;
        }

        /** 路由策略：auto（默认）/ core（强制经 Core Router）/ local（同进程保留通道）。 */
        public CallOptions route(String policy) {
            this.route = (policy == null || policy.isEmpty()) ? "auto" : policy;
            return this;
        }

        /** 提议一个 request_id（引擎为准：重复/非法时由引擎替换）。 */
        public CallOptions requestId(String id) {
            this.requestId = id == null ? "" : id;
            return this;
        }

        public CallOptions metadata(Map<String, Object> values) {
            Map<String, Object> copy = new LinkedHashMap<>();
            if (values != null) {
                copy.putAll(values);
            }
            this.metadata = copy;
            return this;
        }

        public int timeout() {
            return timeout;
        }

        public String route() {
            return route;
        }

        public String requestId() {
            return requestId;
        }

        public Map<String, Object> metadata() {
            return metadata;
        }
    }

    /** 插件钩子签名。 */
    public interface LifecycleHandler {
        void handle(Context ctx);
    }

    /** 消息/事件钩子：返回动作（Map）或 null。 */
    public interface MessageHandler {
        Object handle(Context ctx, Map<String, Object> event);
    }

    /** 控制面 hook（插件 WebUI 的数据钩子走同一通道）。 */
    public interface HookHandler {
        Object handle(List<Object> args);
    }

    /** 心跳钩子（Python 侧对应 health_check）：返回 false 即视为不健康。 */
    public interface HealthHandler {
        boolean handle(Context ctx);
    }

    private final BufferedReader in = new BufferedReader(
            new InputStreamReader(System.in, StandardCharsets.UTF_8));
    private final PrintStream out = new PrintStream(System.out, true, StandardCharsets.UTF_8);
    private final Map<Integer, Object> pending = new HashMap<>();
    private int nextId = 0;
    private final Context ctx = new Context();
    private final List<LifecycleHandler> startupHooks = new ArrayList<>();
    private final List<LifecycleHandler> shutdownHooks = new ArrayList<>();
    private final List<MessageHandler> messageHooks = new ArrayList<>();
    private final Map<String, List<MessageHandler>> eventHooks = new HashMap<>();
    private final Map<String, HookHandler> namedHooks = new HashMap<>();
    private final Map<String, WebuiHandler> webuiHandlers = new HashMap<>();
    private final List<HealthHandler> healthHooks = new ArrayList<>();
    /** 被调方：method -> handler（plugin.expose 注册，§五）。 */
    private final Map<String, CommHandler> commHandlers = new LinkedHashMap<>();
    /** 订阅方：event 名 -> [handler]（plugin.on 注册，§九；"*" 订阅全部）。 */
    private final Map<String, List<CommEventHandler>> commEventHandlers = new LinkedHashMap<>();
    /** 入站消息栈（§二十二/§二十三 trace/hop 传播 + 防退化递归）：嵌套调用时链路连续。 */
    private final Deque<Map<String, Object>> inboundStack = new ArrayDeque<>();
    /** 已被取消的 request_id（§十八）；有界（MAX_CANCELLED_IDS）。 */
    private final Set<String> cancelledRequests = new LinkedHashSet<>();

    /** 插件上下文：storage / config / permission / action / log。 */
    public class Context {
        private String pluginId = "unknown";
        private Path pluginDir = Paths.get(".").toAbsolutePath();
        private Path dataDir = pluginDir.resolve("data");

        public String pluginId() {
            return pluginId;
        }

        public void log(String message) {
            System.err.println("[flowerie] " + message);
        }

        private Path storageDir() throws IOException {
            Path dir = dataDir.resolve("storage");
            Files.createDirectories(dir);
            return dir;
        }

        private Path storagePath(String key) throws IOException {
            if (!KEY_RE.matcher(key == null ? "" : key).matches()) {
                throw new IOException("存储键非法（字母数字开头 ≤64，允许 . _ -）");
            }
            return storageDir().resolve(key + ".json");
        }

        public Object storageGet(String key) throws IOException {
            Path path = storagePath(key);
            if (!Files.isRegularFile(path)) {
                return null;
            }
            return Json.parse(Files.readString(path, StandardCharsets.UTF_8));
        }

        public int storageSet(String key, Object value) throws IOException {
            Path path = storagePath(key);
            String text = Json.dump(value);
            if (text.getBytes(StandardCharsets.UTF_8).length > MAX_STORAGE_VALUE) {
                throw new IOException("值超过上限");
            }
            long count;
            try (var stream = Files.list(storageDir())) {
                count = stream.filter(p -> p.getFileName().toString().endsWith(".json")).count();
            }
            if (!Files.exists(path) && count >= MAX_STORAGE_KEYS) {
                throw new IOException("存储键数量超过上限");
            }
            Files.writeString(path, text, StandardCharsets.UTF_8);
            return text.getBytes(StandardCharsets.UTF_8).length;
        }

        public boolean storageDelete(String key) throws IOException {
            return Files.deleteIfExists(storagePath(key));
        }

        public List<String> storageList(String prefix) throws IOException {
            List<String> keys = new ArrayList<>();
            try (var stream = Files.list(storageDir())) {
                stream.forEach(p -> {
                    String name = p.getFileName().toString();
                    if (name.endsWith(".json")) {
                        String key = name.substring(0, name.length() - 5);
                        if (key.startsWith(prefix == null ? "" : prefix)) {
                            keys.add(key);
                        }
                    }
                });
            }
            keys.sort(String::compareTo);
            return keys;
        }

        private Path configPath() {
            return dataDir.resolve("config.json");
        }

        private Map<String, Object> configOverlay() {
            try {
                Object parsed = Json.parse(Files.readString(configPath(), StandardCharsets.UTF_8));
                if (parsed instanceof Map) {
                    @SuppressWarnings("unchecked")
                    Map<String, Object> map = (Map<String, Object>) parsed;
                    return map;
                }
            } catch (IOException | Json.JsonException ignored) {
                // 没有覆盖层 / 文件损坏 → 空覆盖层
            }
            return new LinkedHashMap<>();
        }

        /** 操作员配置（引擎） + 插件覆盖层；操作员的值优先。 */
        @SuppressWarnings("unchecked")
        public Map<String, Object> configGet() throws IOException {
            Map<String, Object> merged = configOverlay();
            Object res = engineOp("config.get", Map.of());
            Object values = Json.get(res, "values");
            if (values instanceof Map) {
                merged.putAll((Map<String, Object>) values);
            }
            return merged;
        }

        /** 写入插件自己的覆盖层（改不了操作员的全局配置）。 */
        @SuppressWarnings("unchecked")
        public List<String> configSet(Map<String, Object> values) throws IOException {
            Map<String, Object> overlay = configOverlay();
            List<String> saved = new ArrayList<>();
            for (Map.Entry<String, Object> entry : values.entrySet()) {
                if (!KEY_RE.matcher(entry.getKey()).matches()) {
                    throw new IOException("配置键非法: " + entry.getKey());
                }
                if (Json.dump(entry.getValue()).getBytes(StandardCharsets.UTF_8).length > MAX_CONFIG_VALUE) {
                    throw new IOException("配置值超过上限: " + entry.getKey());
                }
                overlay.put(entry.getKey(), entry.getValue());
                saved.add(entry.getKey());
            }
            if (overlay.size() > MAX_CONFIG_KEYS) {
                throw new IOException("配置键数量超过上限");
            }
            Files.createDirectories(dataDir);
            Files.writeString(configPath(), Json.dump(overlay), StandardCharsets.UTF_8);
            saved.sort(String::compareTo);
            return saved;
        }

        /** 查询管理员是否批准了某个权限（只读，无法提权）。 */
        public boolean permissionCheck(String permission) throws IOException {
            Object res = engineOp("permission.check", Json.obj("permission", permission));
            Object granted = Json.get(res, "granted");
            return Boolean.TRUE.equals(granted);
        }

        /** 拉取引擎侧上下文（插件名 / 版本 / 已批准权限）。 */
        public Object info() throws IOException {
            Object res = engineOp("context.get", Map.of());
            Object inner = Json.get(res, "result");
            return inner != null ? inner : res;
        }

        /** 发起动作（副作用出口）。 */
        public Object action(String type, Map<String, Object> params) throws IOException {
            return reverse("action", Json.obj("action", type, "payload", params));
        }

        private Object engineOp(String op, Map<String, Object> args) throws IOException {
            return reverse("engine", Json.obj("op", op, "args", args));
        }

        /** 插件间通信的反向 op：协议级失败（连接断开 / 协议错误）也映射成结构化异常，不退化成字符串。 */
        Object engineOpComm(String op, Map<String, Object> args) throws PluginCommException {
            try {
                return engineOp(op, args);
            } catch (IOException e) {
                throw new PluginCommException("PLUGIN_ERROR", String.valueOf(e.getMessage()), null);
            }
        }

        /** 等待响应期间引擎投递进来的请求：**必须原地处理，不能丢**（§八/§二十二）。
         *
         * <p>插件是单线程读写 stdio 的循环：这里把消息丢掉，A 调用 B、B 又回调 A 时 A 永远收不到
         * 回调 —— 环保护也就没有真实链路可观察了。行为与 Python SDK 的 _pump_nested 一致。
         */
        private void pumpNested(Object msg) {
            if (inboundStack.size() > MAX_INBOUND_DEPTH) {
                return;                       // 防退化递归（正常链路远小于此）
            }
            String method = Json.str(msg, "method");
            if (method == null || !NESTED_METHODS.contains(method)) {
                return;
            }
            Object idValue = Json.get(msg, "id");
            int msgId = idValue instanceof Number ? ((Number) idValue).intValue() : 0;
            FloweriePlugin.this.handle(msgId, method, Json.get(msg, "params"));
        }

        private Object reverse(String method, Map<String, Object> params) throws IOException {
            int id = ACTION_ID_BASE + (++nextId);
            out.println(Json.dump(Json.obj("id", id, "method", method, "params", params)));
            while (true) {
                String line = in.readLine();
                if (line == null) {
                    throw new IOException("connection closed");
                }
                Object msg;
                try {
                    msg = Json.parse(line.trim());
                } catch (Json.JsonException ignored) {
                    continue;
                }
                Object msgId = Json.get(msg, "id");
                if (!(msgId instanceof Number) || ((Number) msgId).intValue() != id) {
                    // 不是我在等的那条：可能是引擎投递进来的 plugin.call / plugin.event / plugin.cancel
                    pumpNested(msg);
                    continue;
                }
                String error = Json.str(msg, "error");
                if (error != null) {
                    throw new IOException(error);
                }
                Object result = Json.get(msg, "result");
                return result != null ? result : Json.obj();
            }
        }
    }

    /** 注册启动钩子。 */
    public FloweriePlugin onStartup(LifecycleHandler handler) {
        startupHooks.add(handler);
        return this;
    }

    /** 注册退出钩子。 */
    public FloweriePlugin onShutdown(LifecycleHandler handler) {
        shutdownHooks.add(handler);
        return this;
    }

    /** 注册消息钩子。 */
    public FloweriePlugin onMessage(MessageHandler handler) {
        messageHooks.add(handler);
        return this;
    }

    /** 注册任意事件的钩子。 */
    public FloweriePlugin onEvent(String event, MessageHandler handler) {
        eventHooks.computeIfAbsent(event, k -> new ArrayList<>()).add(handler);
        return this;
    }

    /** 注册心跳钩子（与 Python 的 health_check 对齐）。 */
    public FloweriePlugin onHealth(HealthHandler handler) {
        healthHooks.add(handler);
        return this;
    }

    // 与 Python SDK 的具名钩子对齐（协议层就是 event 名字，onEvent 是通用入口）
    public FloweriePlugin onCommand(MessageHandler handler) {
        return onEvent("command", handler);
    }

    /** 通知事件。 */
    public FloweriePlugin onNotice(MessageHandler handler) {
        return onEvent("notice", handler);
    }

    /** 请求事件。 */
    public FloweriePlugin onRequest(MessageHandler handler) {
        return onEvent("request", handler);
    }

    /** 生命周期事件。 */
    public FloweriePlugin onLifecycle(MessageHandler handler) {
        return onEvent("lifecycle", handler);
    }

    /** 定时事件。 */
    public FloweriePlugin onSchedule(MessageHandler handler) {
        return onEvent("schedule", handler);
    }

    /** 注册控制面 hook。 */
    public FloweriePlugin registerHook(String name, HookHandler handler) {
        namedHooks.put(name, handler);
        return this;
    }

    /** Plugin WebUI Protocol 处理器（任务书第 3 份 §六）：参数是引擎给的受控对象。 */
    public interface WebuiHandler {
        Object handle(Map<String, Object> args) throws IOException;
    }

    /** WebUI 注册入口：`plugin.webUI().page(args -> ...).action(args -> ...)`。 */
    public WebUI webUI() {
        return new WebUI();
    }

    /** WebUI 注册器（语义与 TypeScript 的 plugin.webui / Rust 的 plugin.webui() 一致）。 */
    public final class WebUI {
        /** 页面处理器（webui.page）。 */
        public WebUI page(WebuiHandler handler) {
            return register("webui.page", handler);
        }

        /** 动作处理器（webui.action）。 */
        public WebUI action(WebuiHandler handler) {
            return register("webui.action", handler);
        }

        /** 资源处理器（webui.asset）。 */
        public WebUI asset(WebuiHandler handler) {
            return register("webui.asset", handler);
        }

        private WebUI register(String method, WebuiHandler handler) {
            webuiHandlers.put(method, handler);
            return this;
        }
    }


    /** 暴露上下文（测试 / 嵌入场景）。 */
    public Context context() {
        return ctx;
    }

    /** 进入协议主循环。 */
    public void run() throws IOException {
        while (true) {
            String line = in.readLine();
            if (line == null) {
                return;
            }
            if (line.trim().isEmpty()) {
                continue;
            }
            Object msg;
            try {
                msg = Json.parse(line.trim());
            } catch (Json.JsonException ignored) {
                continue;
            }
            String method = Json.str(msg, "method");
            if (method == null || method.isEmpty()) {
                continue;
            }
            Object idValue = Json.get(msg, "id");
            int id = idValue instanceof Number ? ((Number) idValue).intValue() : 0;
            Object params = Json.get(msg, "params");
            if (handle(id, method, params)) {
                return;
            }
        }
    }

    private static final List<String> WEBUI_PAYLOAD_KEYS = List.of("html", "vars", "context",
            "message", "content_type", "body", "base64", "config_set", "storage_set");

    /** 把 WebUI 处理器返回值归一成协议应答（String = html 简写，白名单字段透传）。 */
    static Map<String, Object> normalizeWebuiResult(Object result) {
        Map<String, Object> out = new LinkedHashMap<>();
        if (result instanceof String) {
            out.put("ok", Boolean.TRUE);
            out.put("html", result);
            return out;
        }
        if (result instanceof Map) {
            Map<?, ?> src = (Map<?, ?>) result;
            if (Boolean.FALSE.equals(src.get("ok"))) {
                out.put("ok", Boolean.FALSE);
                out.put("error", src.get("error") == null ? "插件返回 ok=false" : src.get("error"));
                return out;
            }
            out.put("ok", Boolean.TRUE);
            for (String key : WEBUI_PAYLOAD_KEYS) {
                if (src.containsKey(key)) {
                    out.put(key, src.get(key));
                }
            }
            return out;
        }
        out.put("ok", Boolean.FALSE);
        out.put("error", "WebUI 处理器没有返回内容");
        return out;
    }

    private void reply(int id, Object result) {
        out.println(Json.dump(Json.obj("id", id, "result", result)));
    }

    private void replyError(int id, String message) {
        String trimmed = message.length() > 800 ? message.substring(0, 800) : message;
        out.println(Json.dump(Json.obj("id", id, "error", trimmed)));
    }

    @SuppressWarnings("unchecked")
    private boolean handle(int id, String method, Object params) {
        Map<String, Object> paramsMap = params instanceof Map ? (Map<String, Object>) params : Map.of();
        try {
            switch (method) {
                case "initialize": {
                    Object contextValue = paramsMap.get("context");
                    if (contextValue instanceof Map) {
                        Map<String, Object> contextMap = (Map<String, Object>) contextValue;
                        if (contextMap.get("plugin_dir") instanceof String) {
                            ctx.pluginDir = Paths.get((String) contextMap.get("plugin_dir"));
                        }
                        if (contextMap.get("data_dir") instanceof String) {
                            ctx.dataDir = Paths.get((String) contextMap.get("data_dir"));
                        }
                        if (contextMap.get("plugin_id") instanceof String) {
                            ctx.pluginId = (String) contextMap.get("plugin_id");
                        }
                    }
                    for (LifecycleHandler handler : startupHooks) {
                        handler.handle(ctx);
                    }
                    // 核心 8 项 + WebUI 3 项 + Plugin-to-Plugin 3 项 = 14 项（§十四 能力矩阵不撒谎）
                    List<Object> caps = new ArrayList<>(List.of(
                            "config.get", "config.set", "context.get", "permission.check",
                            "storage.delete", "storage.get", "storage.list", "storage.set",
                            "webui.action", "webui.asset", "webui.page",
                            "plugin.call", "plugin.event", "plugin.cancel"));
                    reply(id, Json.obj("ok", true, "api_version", API_VERSION,
                            "protocol_version", PROTOCOL_VERSION, "capabilities", caps));
                    return false;
                }
                case "event": {
                    String event = paramsMap.get("event") instanceof String ? (String) paramsMap.get("event") : "";
                    Object payload = paramsMap.get("payload");
                    List<Object> actions = new ArrayList<>();
                    Map<String, Object> eventObj = new LinkedHashMap<>();
                    if (payload instanceof Map) {
                        eventObj.putAll((Map<String, Object>) payload);
                    }
                    eventObj.put("event", event);
                    eventObj.put("plugin_id", ctx.pluginId);
                    List<MessageHandler> hooks = "message".equals(event)
                            ? messageHooks : eventHooks.getOrDefault(event, List.of());
                    for (MessageHandler handler : hooks) {
                        Object action = handler.handle(ctx, eventObj);
                        if (action != null) {
                            actions.add(action);
                        }
                    }
                    reply(id, Json.obj("actions", actions));
                    return false;
                }
                case "health": {
                    boolean healthy = true;
                    for (HealthHandler handler : healthHooks) {
                        try {
                            if (!handler.handle(ctx)) {
                                healthy = false;
                            }
                        } catch (RuntimeException e) {
                            healthy = false;
                        }
                    }
                    reply(id, healthy ? Json.obj("ok", true)
                            : Json.obj("ok", false, "error", "health check failed"));
                    return false;
                }
                case "shutdown":
                    for (LifecycleHandler handler : shutdownHooks) {
                        handler.handle(ctx);
                    }
                    reply(id, Json.obj("ok", true));
                    return true;
                case "hook": {
                    String name = paramsMap.get("name") instanceof String ? (String) paramsMap.get("name") : "";
                    if (!name.matches("^[a-z_][a-z0-9_]{0,63}$")) {
                        replyError(id, "hook 名非法");
                        return false;
                    }
                    HookHandler handler = namedHooks.get(name);
                    Object result = null;
                    if (handler != null) {
                        Object args = paramsMap.get("args");
                        result = handler.handle(args instanceof List ? (List<Object>) args : List.of());
                    }
                    reply(id, Json.obj("ok", true, "result", result));
                    return false;
                }
                case "webui.page":
                case "webui.action":
                case "webui.asset": {
                    WebuiHandler webuiHandler = webuiHandlers.get(method);
                    if (webuiHandler == null) {
                        reply(id, Json.obj("ok", false, "error", "插件未注册 " + method + " 处理器"));
                        return false;
                    }
                    try {
                        reply(id, normalizeWebuiResult(webuiHandler.handle(paramsMap)));
                    } catch (IOException | RuntimeException e) {
                        reply(id, Json.obj("ok", false, "error", String.valueOf(e.getMessage())));
                    }
                    return false;
                }
                case "storage.get": {
                    String key = paramsMap.get("key") instanceof String ? (String) paramsMap.get("key") : "";
                    if (!KEY_RE.matcher(key).matches()) {
                        reply(id, Json.obj("ok", false, "error", "存储键非法（字母数字开头 ≤64，允许 . _ -）"));
                        return false;
                    }
                    reply(id, Json.obj("ok", true, "value", ctx.storageGet(key)));
                    return false;
                }
                case "storage.set": {
                    String key = paramsMap.get("key") instanceof String ? (String) paramsMap.get("key") : "";
                    try {
                        int size = ctx.storageSet(key, paramsMap.get("value"));
                        reply(id, Json.obj("ok", true, "size", size));
                    } catch (IOException e) {
                        reply(id, Json.obj("ok", false, "error", e.getMessage()));
                    }
                    return false;
                }
                case "storage.delete": {
                    String key = paramsMap.get("key") instanceof String ? (String) paramsMap.get("key") : "";
                    if (!KEY_RE.matcher(key).matches()) {
                        reply(id, Json.obj("ok", false, "error", "存储键非法（字母数字开头 ≤64，允许 . _ -）"));
                        return false;
                    }
                    reply(id, Json.obj("ok", true, "deleted", ctx.storageDelete(key)));
                    return false;
                }
                case "storage.list": {
                    String prefix = paramsMap.get("prefix") instanceof String ? (String) paramsMap.get("prefix") : "";
                    reply(id, Json.obj("ok", true, "keys", ctx.storageList(prefix)));
                    return false;
                }
                case "config.get":
                    reply(id, Json.obj("ok", true, "values", ctx.configGet()));
                    return false;
                case "config.set": {
                    Object values = paramsMap.get("values");
                    if (!(values instanceof Map)) {
                        reply(id, Json.obj("ok", false, "error", "config.set 需要 values 对象"));
                        return false;
                    }
                    reply(id, Json.obj("ok", true, "saved", ctx.configSet((Map<String, Object>) values)));
                    return false;
                }
                case "permission.check": {
                    String permission = paramsMap.get("permission") instanceof String
                            ? (String) paramsMap.get("permission") : "";
                    reply(id, Json.obj("ok", true, "permission", permission,
                            "granted", ctx.permissionCheck(permission)));
                    return false;
                }
                case "context.get":
                    reply(id, Json.obj("ok", true, "result", ctx.info()));
                    return false;
                case "plugin.call":
                case "plugin.event":
                case "plugin.cancel":
                    // 插件间通信（§十）：CALL / EVENT / CANCEL 分开处理，不混成一种机制
                    handleInboundComm(id, method, paramsMap);
                    return false;
                default:
                    replyError(id, "未知方法: \"" + method + "\"");
                    return false;
            }
        } catch (IOException e) {
            replyError(id, "runner 异常: " + e.getMessage());
            return false;
        }
    }

    // ================= Plugin-to-Plugin 通信（§五–§二十七）公开 API =================

    /** 调用其它插件（§五/§六/§七）：成功返回 result，失败抛 {@link PluginCommException}。
     *
     * <p>出站永远是「插件 → 引擎反向 op → Core Router → 目标插件」：SDK 里没有、也不允许有
     * 任何绕过 Core 的直连通道（§十二/§二十六）；权限在 Core Router 判定，SDK 跳不过（§十五）。
     * **不自动重试**（§八）：重试由插件自己决定，避免插件之间形成请求风暴。
     */
    public Object call(String target, String method, Map<String, Object> params, CallOptions opts)
            throws PluginCommException {
        CallOptions options = opts == null ? CallOptions.DEFAULT : opts;
        Map<String, Object> payload = params == null ? new LinkedHashMap<>() : params;
        requireSerializable(payload, "params");
        if (!options.metadata().isEmpty()) {
            requireSerializable(options.metadata(), "metadata");
        }
        Map<String, Object> request = new LinkedHashMap<>();
        request.put("target", target == null ? "" : target);
        request.put("method", method == null ? "" : method);
        request.put("params", payload);
        request.put("timeout", options.timeout());
        request.put("route", options.route());
        // trace/hop 自动传播（§二十二/§二十三）：处理入站消息期间发起的调用沿用同一条链路
        request.put("trace_id", currentTraceId());
        request.put("hop_count", currentHopCount());
        if (!options.requestId().isEmpty()) {
            request.put("request_id", options.requestId());
        }
        if (!options.metadata().isEmpty()) {
            request.put("metadata", options.metadata());
        }
        Object res = ctx.engineOpComm("plugin.call", request);
        if (!(res instanceof Map) || !Boolean.TRUE.equals(((Map<?, ?>) res).get("ok"))) {
            throw toException(res);
        }
        return ((Map<?, ?>) res).get("result");
    }

    /** {@link #call(String, String, Map, CallOptions)} 的默认参数重载（timeout=5000ms、route=auto）。 */
    public Object call(String target, String method, Map<String, Object> params) throws PluginCommException {
        return call(target, method, params, CallOptions.DEFAULT);
    }

    /** {@link #call(String, String, Map, CallOptions)} 的默认参数重载（params={}）。 */
    public Object call(String target, String method) throws PluginCommException {
        return call(target, method, new LinkedHashMap<>(), CallOptions.DEFAULT);
    }

    /** 异步写法（§八）：语义与 {@link #call} 完全一致（失败也是同一个 PluginCommException）。
     *
     * <p>为什么是「立即兑现的 Future」而不是后台线程：SDK 是单线程 stdio 循环，另起线程读同一根
     * stdin 会撕裂协议（响应错配）。Python SDK 的 acall 同理：同步执行、await 语义一致。
     */
    public CompletableFuture<Object> callAsync(String target, String method,
                                               Map<String, Object> params, CallOptions opts) {
        try {
            return CompletableFuture.completedFuture(call(target, method, params, opts));
        } catch (PluginCommException | RuntimeException e) {
            CompletableFuture<Object> failed = new CompletableFuture<>();
            failed.completeExceptionally(e);
            return failed;
        }
    }

    /** {@link #callAsync(String, String, Map, CallOptions)} 的默认参数重载。 */
    public CompletableFuture<Object> callAsync(String target, String method, Map<String, Object> params) {
        return callAsync(target, method, params, CallOptions.DEFAULT);
    }

    /** 广播事件给所有订阅者（§九，需要 plugin.emit 权限）：返回引擎的结果 {ok, delivered, failed}。
     *
     * <p>事件**不是 RPC**（§十）：所以返回结果 Map 而不是抛异常；结构性失败以
     * {@code {"ok":false,"error":{code,message,data}}} 留在 Map 里（错误码不退化成字符串）。
     */
    @SuppressWarnings("unchecked")
    public Map<String, Object> emit(String name, Object payload) throws PluginCommException {
        Object body = payload == null ? new LinkedHashMap<String, Object>() : payload;
        requireSerializable(body, "payload");
        Map<String, Object> event = new LinkedHashMap<>();
        event.put("name", name == null ? "" : name);
        event.put("payload", body);
        event.put("trace_id", currentTraceId());
        event.put("hop_count", currentHopCount());
        Object res = ctx.engineOpComm("plugin.emit", event);
        if (res instanceof Map) {
            return (Map<String, Object>) res;
        }
        return errorResult("INTERNAL_ERROR", "引擎返回了非法结果", null);
    }

    /** {@link #emit(String, Object)} 的默认参数重载（payload={}）。 */
    public Map<String, Object> emit(String name) throws PluginCommException {
        return emit(name, null);
    }

    /** 取消自己发起的一次调用（§十八）：目标插件收到 CANCEL 后尽量避免继续处理。 */
    @SuppressWarnings("unchecked")
    public Map<String, Object> cancel(String requestId, String reason) throws PluginCommException {
        Map<String, Object> args = new LinkedHashMap<>();
        args.put("request_id", requestId == null ? "" : requestId);
        args.put("reason", reason == null ? "" : reason);
        Object res = ctx.engineOpComm("plugin.cancel", args);
        if (res instanceof Map) {
            return (Map<String, Object>) res;
        }
        return errorResult("INTERNAL_ERROR", "引擎返回了非法结果", null);
    }

    /** {@link #cancel(String, String)} 的默认参数重载（reason=""）。 */
    public Map<String, Object> cancel(String requestId) throws PluginCommException {
        return cancel(requestId, "");
    }

    /** 订阅插件事件（§九）：name 传 "*" 表示订阅全部；handler 收到**完整事件模型**。 */
    public FloweriePlugin on(String name, CommEventHandler handler) {
        String event = name == null ? "" : name;
        if (!"*".equals(event) && !COMM_NAME_RE.matcher(event).matches()) {
            throw new IllegalArgumentException("事件名非法（字母/下划线开头，允许 . _，≤96）: " + event);
        }
        if (handler == null) {
            throw new IllegalArgumentException("handler 不能为 null");
        }
        commEventHandlers.computeIfAbsent(event, k -> new ArrayList<>()).add(handler);
        return this;
    }

    /** 暴露一个可被其它插件调用的方法（§五 CALL 的被调方）；handler 传 null 表示注销。 */
    public FloweriePlugin expose(String method, CommHandler handler) {
        String name = method == null ? "" : method;
        if (!COMM_NAME_RE.matcher(name).matches()) {
            throw new IllegalArgumentException("方法名非法（字母/下划线开头，允许 . _，≤96）: " + name);
        }
        if (handler == null) {
            commHandlers.remove(name);
        } else {
            commHandlers.put(name, handler);
        }
        return this;
    }

    /** 已暴露的方法名（升序）：METHOD_NOT_FOUND 的 data.exposed 与诊断用。 */
    public List<String> exposedMethods() {
        List<String> names = new ArrayList<>(commHandlers.keySet());
        names.sort(String::compareTo);
        return names;
    }

    /** 当前入站消息的上下文（trace_id / hop_count / source / request_id）；不在入站处理中时为空 Map。 */
    public Map<String, Object> commContext() {
        if (inboundStack.isEmpty()) {
            return new LinkedHashMap<>();
        }
        return new LinkedHashMap<>(inboundStack.peek());
    }

    // ---------- 入站分发（引擎 → 插件：CALL / EVENT / CANCEL，§十） ----------

    private void handleInboundComm(int id, String method, Map<String, Object> params) {
        if ("plugin.call".equals(method)) {
            handleInboundCall(id, params);
        } else if ("plugin.event".equals(method)) {
            handleInboundEvent(id, params);
        } else {
            handleInboundCancel(id, params);
        }
    }

    /** plugin.call 的被调方：查 expose 注册表 → 调 handler（收完整请求模型）→ 回响应模型。 */
    private void handleInboundCall(int id, Map<String, Object> params) {
        String requestId = asString(params.get("request_id"));
        String method = asString(params.get("method"));
        pushInbound(params);
        try {
            if (!requestId.isEmpty() && cancelledRequests.contains(requestId)) {
                cancelledRequests.remove(requestId);
                reply(id, errorResult("CANCELLED", "调用已被取消", null));
                return;
            }
            CommHandler handler = commHandlers.get(method);
            if (handler == null) {
                reply(id, errorResult("METHOD_NOT_FOUND", "插件未暴露方法: " + method,
                        Json.obj("method", method, "exposed", exposedMethods())));
                return;
            }
            Object result;
            try {
                result = handler.handle(params);
            } catch (Exception e) {
                // handler 异常 → 结构化 PLUGIN_ERROR，不杀进程、不漏异常
                reply(id, errorResult("PLUGIN_ERROR",
                        e.getClass().getSimpleName() + ": " + e.getMessage(), null));
                return;
            }
            try {
                Json.checkJsonValue(result, "result");   // §十九/§二十：语言内部对象在边界被拒绝
            } catch (Json.JsonException e) {
                reply(id, errorResult("SERIALIZATION_ERROR", e.getMessage(), null));
                return;
            }
            reply(id, Json.obj("ok", true, "result", result));
        } finally {
            inboundStack.pop();
        }
    }

    /** plugin.event：投给 on() 注册的 handler（"*" 匹配全部），回 {ok:true,handled:N}（§九）。 */
    private void handleInboundEvent(int id, Map<String, Object> params) {
        String name = asString(params.get("name"));
        pushInbound(params);
        try {
            List<CommEventHandler> handlers = new ArrayList<>();
            List<CommEventHandler> exact = commEventHandlers.get(name);
            if (exact != null) {
                handlers.addAll(exact);
            }
            if (!"*".equals(name)) {
                List<CommEventHandler> wildcard = commEventHandlers.get("*");
                if (wildcard != null) {
                    handlers.addAll(wildcard);
                }
            }
            int handled = 0;
            for (CommEventHandler handler : handlers) {
                try {
                    handler.handle(params);
                    handled++;
                } catch (Exception ignored) {
                    // 单个订阅者失败不影响其它订阅者：事件没有响应语义（§十）
                }
            }
            reply(id, Json.obj("ok", true, "handled", handled));
        } finally {
            inboundStack.pop();
        }
    }

    /** plugin.cancel：记录该 request_id 已取消（有界），回 {ok:true,cancelled:bool}（§十八）。 */
    private void handleInboundCancel(int id, Map<String, Object> params) {
        String requestId = asString(params.get("request_id"));
        if (!requestId.isEmpty()) {
            cancelledRequests.add(requestId);
            if (cancelledRequests.size() > MAX_CANCELLED_IDS) {
                cancelledRequests.clear();          // 有界：取消记录不无限增长
            }
        }
        reply(id, Json.obj("ok", true, "cancelled", !requestId.isEmpty()));
    }

    private void pushInbound(Map<String, Object> params) {
        Map<String, Object> frame = new LinkedHashMap<>();
        frame.put("trace_id", asString(params.get("trace_id")));
        frame.put("hop_count", asInt(params.get("hop_count")));
        Object source = params.get("source");
        frame.put("source", source instanceof Map ? source : new LinkedHashMap<String, Object>());
        frame.put("request_id", asString(params.get("request_id")));
        inboundStack.push(frame);
    }

    private String currentTraceId() {
        return inboundStack.isEmpty() ? "" : asString(inboundStack.peek().get("trace_id"));
    }

    private int currentHopCount() {
        return inboundStack.isEmpty() ? 0 : asInt(inboundStack.peek().get("hop_count"));
    }

    /** 出站参数必须是语言无关类型（§十九/§二十）：Java 对象在这里被拦下，不退化成 toString()。 */
    private static void requireSerializable(Object value, String what) throws PluginCommException {
        try {
            Json.checkJsonValue(value, what);
        } catch (Json.JsonException e) {
            throw new PluginCommException("SERIALIZATION_ERROR", e.getMessage(), null);
        }
    }

    /** 响应模型 → Java 异常：错误码原样保留（§二十一），message/data 不丢。 */
    private static PluginCommException toException(Object response) {
        Object error = response instanceof Map ? ((Map<?, ?>) response).get("error") : null;
        if (error instanceof Map) {
            Map<?, ?> struct = (Map<?, ?>) error;
            Map<String, Object> detail = new LinkedHashMap<>();
            Object data = struct.get("data");
            if (data instanceof Map) {
                for (Map.Entry<?, ?> entry : ((Map<?, ?>) data).entrySet()) {
                    detail.put(String.valueOf(entry.getKey()), entry.getValue());
                }
            }
            Object code = struct.get("code");
            Object message = struct.get("message");
            return new PluginCommException(code == null ? "PLUGIN_ERROR" : String.valueOf(code),
                    message == null ? "" : String.valueOf(message), detail);
        }
        return new PluginCommException("PLUGIN_ERROR",
                error == null ? "插件调用失败" : String.valueOf(error), null);
    }

    /** 结构化错误应答（§七）：error 永远是 {code,message,data} 三件套。 */
    private static Map<String, Object> errorResult(String code, String message, Map<String, Object> data) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("ok", Boolean.FALSE);
        out.put("error", Json.obj("code", code, "message", message == null ? "" : message,
                "data", data == null ? new LinkedHashMap<String, Object>() : data));
        return out;
    }

    private static String asString(Object value) {
        if (value == null) {
            return "";
        }
        return value instanceof String ? (String) value : String.valueOf(value);
    }

    private static int asInt(Object value) {
        if (value instanceof Number) {
            return ((Number) value).intValue();
        }
        try {
            return Integer.parseInt(String.valueOf(value).trim());
        } catch (RuntimeException e) {
            return 0;
        }
    }

    // 便于插件作者写 lambda 的辅助（保持 API 语义与其它语言一致）
    public static BiFunction<Context, Map<String, Object>, Object> handler(
            Function<Map<String, Object>, Object> fn) {
        return (ctx, event) -> fn.apply(event);
    }
}
