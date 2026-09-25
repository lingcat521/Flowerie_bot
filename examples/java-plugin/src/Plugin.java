import dev.flowerie.sdk.FloweriePlugin;
import dev.flowerie.sdk.Json;

import java.util.Map;

/** Java 示例插件：与 Python / TypeScript / Go / Rust 示例**语义完全一致**。 */
public final class Plugin {

    private Plugin() {
    }

    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        FloweriePlugin plugin = new FloweriePlugin();

        plugin.onStartup(ctx -> ctx.log("java 示例插件启动 plugin_id=" + ctx.pluginId()));

        plugin.onMessage((ctx, event) -> {
            if ("ping".equals(event.get("text"))) {
                return Json.obj("type", "send_group_msg",
                        "params", Json.obj("group_id", event.get("group_id"), "message", "pong"));
            }
            return null;
        });

        // 命令事件（与 Python 的 on_command 对齐）：/ping → pong
        plugin.onCommand((ctx, event) -> {
            if ("/ping".equals(event.get("text"))) {
                return Json.obj("type", "send_group_msg",
                        "params", Json.obj("group_id", event.get("group_id"), "message", "pong"));
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
                .page(webuiArgs -> Json.obj("html", settingsForm(plugin.context().pluginId()),
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
                    return Json.obj("html", settingsForm(plugin.context().pluginId()),
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

        plugin.onShutdown(ctx -> ctx.log("java 示例插件退出"));

        plugin.run();
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
}
