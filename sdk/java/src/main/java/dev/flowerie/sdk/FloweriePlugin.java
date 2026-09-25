package dev.flowerie.sdk;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.BiFunction;
import java.util.function.Function;
import java.util.regex.Pattern;

/**
 * Flowerie Plugin Protocol v1 的 Java SDK（**零第三方依赖**，只用 JDK）。
 *
 * <p>协议规范：docs/plugin-protocol.md。与 Python / TypeScript / Go / Rust 示例的行为一致性由
 * {@code tests/test_plugin_sdk_contract.py} 用真进程 + 真管道比对（同一批向量）。
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
                    List<Object> caps = new ArrayList<>(List.of(
                            "config.get", "config.set", "context.get", "permission.check",
                            "storage.delete", "storage.get", "storage.list", "storage.set",
                            "webui.action", "webui.asset", "webui.page"));
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
                default:
                    replyError(id, "未知方法: \"" + method + "\"");
                    return false;
            }
        } catch (IOException e) {
            replyError(id, "runner 异常: " + e.getMessage());
            return false;
        }
    }

    // 便于插件作者写 lambda 的辅助（保持 API 语义与其它语言一致）
    public static BiFunction<Context, Map<String, Object>, Object> handler(
            Function<Map<String, Object>, Object> fn) {
        return (ctx, event) -> fn.apply(event);
    }
}
