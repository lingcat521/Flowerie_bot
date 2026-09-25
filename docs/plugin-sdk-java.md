# Java SDK（dev.flowerie.sdk）

> 任务书第 2 份 §八 / §十五。协议规范：[plugin-protocol.md](plugin-protocol.md)；
> 能力矩阵：[plugin-sdk-capabilities.md](plugin-sdk-capabilities.md)；总览：[plugin-sdk.md](plugin-sdk.md)。
> 源码：`sdk/java/src/main/java/dev/flowerie/sdk/`（`FloweriePlugin.java` + `Json.java`）；
> 示例：`examples/java-plugin/`。

## 1. 定位与依赖

- **零第三方依赖**：只用 JDK（`java.io` / `java.nio` / `java.util` / `java.util.regex`）；
- 构建：`javac`（示例的 `run.sh` 把 SDK + 示例一起编到临时 classes 目录，`java` 直接跑）；
- 需要 JDK 8+（CI 用 runner 镜像自带的 `javac` / `java`）。

## 2. 最小示例

```java
import dev.flowerie.sdk.FloweriePlugin;
import dev.flowerie.sdk.Json;

import java.util.Map;

public final class Plugin {
    public static void main(String[] args) throws Exception {
        FloweriePlugin plugin = new FloweriePlugin();

        plugin.onStartup(ctx -> ctx.log("启动 " + ctx.pluginId()));
        plugin.onMessage((ctx, event) -> "ping".equals(event.get("text"))
                ? Json.obj("type", "send_group_msg",
                           "params", Json.obj("group_id", event.get("group_id"), "message", "pong"))
                : null);
        plugin.registerHook("status", hookArgs ->
                Json.obj("counter", plugin.context().storageGet("counter")));

        // Plugin WebUI Protocol：页面 / 动作 / 资源（lambda 形参别叫 args：会与 main(String[] args) 重名）
        plugin.webUI()
                .page(webuiArgs -> Json.obj("html", "<h2>设置</h2>",
                        "vars", Json.obj("nickname", "")))
                .action(webuiArgs -> {
                    Object form = webuiArgs.get("form");
                    Object nickname = form instanceof Map ? ((Map<?, ?>) form).get("nickname") : null;
                    return Json.obj("message", "已保存",
                            "storage_set", Json.obj("nickname", nickname));
                })
                .asset(webuiArgs -> Json.obj("content_type", "text/css",
                        "body", "body{color:#1f6feb}"));

        plugin.run();
    }
}
```

## 3. API 一览

| 能力 | 用法 |
| :--- | :--- |
| 生命周期 | `onStartup / onShutdown` · `run()` |
| 事件 | `onMessage` · `onCommand / onNotice / onRequest / onLifecycle / onSchedule` · `onEvent(name, fn)` |
| 心跳 | `onHealth(ctx -> boolean)` |
| 动作 | `ctx.action("send_group_msg", Map.of(...))` |
| 存储 | `ctx.storageGet/Set/Delete/List` |
| 配置 | `ctx.configGet()` / `ctx.configSet(Map)` |
| 权限 | `ctx.permissionCheck("send_message")` |
| 上下文 | `ctx.info()` |
| 日志 | `ctx.log("...")`（stderr） |
| 控制面 hook | `registerHook(name, handler)` |
| WebUI Protocol | `plugin.webUI().page(...).action(...).asset(...)` |

## 与 Python SDK 的能力对照

| 能力 | 本 SDK | Python（runner） |
| :--- | :--- | :--- |
| 必需方法 | initialize / event / health / shutdown | 同 |
| 可选能力（11 项） | context.get · config.get · config.set · permission.check · storage.get/set/delete/list · webui.page/action/asset | **完全相同**（`test_handshake_declares_protocol_and_capabilities` 是相等断言，不是子集） |
| 反向通道 | 插件 → 引擎的 engine op / action | 同 |
| 控制面 hook | 具名处理器（插件 WebUI 数据钩子） | `def status(...)` |
| WebUI Protocol | 页面/动作/资源三通道 | 同 |

差异只在**语言习语**：Python 的 `PluginApi` 另有 160+ 个动作包装方法，其它语言统一用
`action("send_group_msg", {...})` 得到同样效果（协议层没有差别）。

## 自查命令

```bash
python3 -m pytest tests/test_plugin_sdk_contract.py -q -rs -k <lang>
python3 -m pytest tests/test_plugin_webui_multilang.py -q -rs -k <lang>

# 本机缺工具链时会打印 SKIP 原因（不是 pass）；CI 装了 go/rustc/javac/node，全跑
```

## 已知限制

- 引擎按**连接**识别插件身份：插件**不能**（也不需要）自己声明 plugin_id；
- 只有声明过的可选方法才会被引擎调用（能力握手门控），声明与实现必须一致；
- stdout 只能放协议 JSON（一行一个），日志一律 stderr；
- 零依赖是刻意设计：为的是「任何语言只要能说 JSON-Lines 就能当插件」，不为 SDK 引入运行时。
