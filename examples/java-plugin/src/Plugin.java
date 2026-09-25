import dev.flowerie.sdk.FloweriePlugin;
import dev.flowerie.sdk.Json;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Java 示例插件：与 Python / TypeScript / Go / Rust 示例**语义完全一致**。 */
public final class Plugin {

    private Plugin() {
    }

    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        FloweriePlugin plugin = new FloweriePlugin();

        plugin.onStartup(ctx -> {
            ctx.log("java 示例插件启动 plugin_id=" + ctx.pluginId());
            // Plugin-to-Plugin 通信（任务书《通信》§五）：暴露的方法在 initialize 之后就能被调用
            plugin.expose("get_status", request -> getStatus(plugin, request));
        });

        plugin.onMessage((ctx, event) -> {
            if ("ping".equals(event.get("text"))) {
                return Json.obj("type", "send_message",
                        "payload", Json.obj("group_id", event.get("group_id"), "message", "pong"));
            }
            return null;
        });

        // 命令事件（与 Python 的 on_command 对齐）：/ping → pong
        plugin.onCommand((ctx, event) -> {
            if ("/ping".equals(event.get("text"))) {
                return Json.obj("type", "send_message",
                        "payload", Json.obj("group_id", event.get("group_id"), "message", "pong"));
            }
            return null;
        });

        // 控制面 hook：插件 WebUI 的数据钩子走同一条通道
        plugin.registerHook("status", hookArgs -> {
            Object counter = null;
            try {
                Object value = plugin.context().storageGet("counter");
                if (value instanceof Map) {
                    counter = ((Map<String, Object>) value).get("n");
                }
            } catch (Exception ignored) {
                counter = null;
            }
            return Json.obj("counter", counter);
        });


        // ---------------- Plugin WebUI Protocol（任务书第 3 份 §六） ----------------
        // 页面 / 动作 / 资源三条通道；路由、权限、校验、净化、隔离全部由引擎负责。

        // HTML 文件页的模板变量（走 web_ui.entry 数据钩子）
        plugin.registerHook("webui_page", hookArgs ->
                Json.obj("vars", Json.obj("nickname", readNickname(plugin))));

        plugin.webUI()
                .page(webuiArgs -> Json.obj(
                        "html", settingsForm(ctxPluginId(webuiArgs, plugin.context().pluginId())),
                        "vars", Json.obj("nickname", readNickname(plugin))))
                .action(webuiArgs -> {
                    Object action = webuiArgs.get("action");
                    if (!"save".equals(action)) {
                        return Json.obj("ok", false, "error", "未知动作: " + action);
                    }
                    Object form = webuiArgs.get("form");
                    String nickname = "";
                    if (form instanceof Map) {
                        Object raw = ((Map<?, ?>) form).get("nickname");
                        if (raw != null) {
                            nickname = String.valueOf(raw);
                        }
                    }
                    return Json.obj(
                            "html", settingsForm(ctxPluginId(webuiArgs, plugin.context().pluginId())),
                            "vars", Json.obj("nickname", nickname),
                            "message", "已保存",
                            "config_set", Json.obj("nickname", nickname),
                            "storage_set", Json.obj("nickname", nickname));
                })
                .asset(webuiArgs -> {
                    if ("theme.css".equals(webuiArgs.get("path"))) {
                        return Json.obj("content_type", "text/css",
                                "body", "body { color: #1f6feb; }");
                    }
                    return Json.obj("ok", false, "error", "资源不存在");
                });

        // ---------------- Plugin-to-Plugin 通信（任务书《通信》§五–§二十七） ----------------
        // 订阅插件事件（§九）："*" 订阅全部；事件不是 RPC，没有返回值（§十）。
        plugin.on("*", event -> plugin.context().log("收到插件事件 name=" + event.get("name")));

        // 反向 hook：让引擎/测试驱动本插件的出站调用（跨语言验收用，与其它语言示例同名同义）。
        // 失败**不抛出去**：让引擎侧能断言结构化错误码（§九 示例契约 2）。
        plugin.registerHook("comm_call", hookArgs -> {
            String target = hookArg(hookArgs, 0);
            String method = hookArg(hookArgs, 1);
            Map<String, Object> params = hookParams(hookArgs, 2);
            try {
                // 可选第 4 个参数：超时（毫秒）；缺省 5000ms（与 Python 示例的 comm_call 同义）
                FloweriePlugin.CallOptions opts =
                        hookArgs.size() > 3 && hookArgs.get(3) instanceof Number
                                ? FloweriePlugin.CallOptions.of(((Number) hookArgs.get(3)).intValue())
                                : FloweriePlugin.CallOptions.DEFAULT;
                Object result = plugin.call(target, method, params, opts);
                return Json.obj("ok", true, "result", result);
            } catch (FloweriePlugin.PluginCommException e) {
                return Json.obj("ok", false, "code", e.getCode(), "message", e.getMessage());
            } catch (Exception e) {
                return Json.obj("ok", false, "code", "INTERNAL_ERROR",
                        "message", String.valueOf(e.getMessage()));
            }
        });

        // 反向 hook：广播插件事件（plugin.emit，需要 manifest 里的 plugin.emit 权限）。
        plugin.registerHook("comm_emit", hookArgs -> {
            try {
                return plugin.emit(hookArg(hookArgs, 0), hookArgs.size() > 1 ? hookArgs.get(1) : null);
            } catch (FloweriePlugin.PluginCommException e) {
                return Json.obj("ok", false, "error", Json.obj("code", e.getCode(),
                        "message", e.getMessage(), "data", e.getData()));
            }
        });

        plugin.onShutdown(ctx -> ctx.log("java 示例插件退出"));

        plugin.run();
    }

    /** 取引擎给的受控 context 里的 plugin.id（插件不自己声明身份），拿不到再退回本地 ctx。 */
    private static String ctxPluginId(Map<String, Object> args, String fallback) {
        Object context = args.get("context");
        if (context instanceof Map) {
            Object pluginInfo = ((Map<?, ?>) context).get("plugin");
            if (pluginInfo instanceof Map) {
                Object id = ((Map<?, ?>) pluginInfo).get("id");
                if (id instanceof String && !((String) id).isEmpty()) {
                    return (String) id;
                }
            }
        }
        return fallback;
    }

    /** 读本插件 storage 里的昵称（与 ctx.storageGet 同一份文件）。 */
    private static String readNickname(FloweriePlugin plugin) {
        try {
            Object value = plugin.context().storageGet("nickname");
            return value instanceof String ? (String) value : "";
        } catch (Exception e) {
            return "";
        }
    }

    /** 插件渲染页的 HTML：{{ nickname }} 由引擎 escape 后替换（受控模板变量）。 */
    private static String settingsForm(String pluginId) {
        return "<h2>插件渲染页</h2>"
                + "<p class=\"who\">这份 HTML 来自插件进程（webui.page），不是磁盘文件。</p>"
                + "<form class=\"card\" method=\"post\" action=\"/panel/plugins/webui/"
                + pluginId + "/dynamic\">"
                + "<input type=\"hidden\" name=\"plugin_action\" value=\"save\">"
                + "<label>昵称 <input name=\"nickname\" value=\"{{ nickname }}\""
                + " maxlength=\"64\"></label>"
                + "<button type=\"submit\">保存</button></form>"
                + "<p class=\"msg\">{{ message }}</p>";
    }

    // ---------------- Plugin-to-Plugin 通信（§九 示例契约） ----------------

    /** get_status：handler 收到**完整请求模型**，返回值就是 CALL 的 result（与其它语言示例同形）。 */
    private static Object getStatus(FloweriePlugin plugin, Map<String, Object> request) {
        String pluginId = "";
        Object target = request.get("target");
        if (target instanceof Map) {
            Object id = ((Map<?, ?>) target).get("plugin_id");
            if (id instanceof String) {
                pluginId = (String) id;
            }
        }
        if (pluginId.isEmpty()) {
            // 引擎总是填 target；拿不到时退回 SDK 上下文（exec runtime 的 initialize 不带 plugin_id）
            pluginId = plugin.context().pluginId();
        }
        Object traceId = request.get("trace_id");
        Object hopCount = request.get("hop_count");
        Object params = request.get("params");
        return Json.obj(
                "plugin_id", pluginId,
                "runtime", "java",
                "trace_id", traceId instanceof String ? traceId
                        : (traceId == null ? "" : String.valueOf(traceId)),
                "hop_count", hopCount instanceof Number ? ((Number) hopCount).intValue() : 0,
                "echo", params == null ? new LinkedHashMap<String, Object>() : params);
    }

    /** hook 参数 → 字符串（缺失/类型不对一律退化成空串，不抛异常）。 */
    private static String hookArg(List<Object> args, int index) {
        Object value = args != null && args.size() > index ? args.get(index) : null;
        if (value instanceof String) {
            return (String) value;
        }
        return value == null ? "" : String.valueOf(value);
    }

    /** hook 参数 → plugin.call 的 params（不是对象就给空对象）。 */
    @SuppressWarnings("unchecked")
    private static Map<String, Object> hookParams(List<Object> args, int index) {
        Object value = args != null && args.size() > index ? args.get(index) : null;
        return value instanceof Map ? (Map<String, Object>) value : new LinkedHashMap<>();
    }
}
