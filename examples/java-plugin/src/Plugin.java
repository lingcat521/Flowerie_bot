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

        plugin.onShutdown(ctx -> ctx.log("java 示例插件退出"));

        plugin.run();
    }
}
