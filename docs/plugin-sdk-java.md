# Java SDK（dev.flowerie.sdk）

> 总览与通用规则：[plugin-sdk.md](plugin-sdk.md)｜协议：[plugin-protocol.md](plugin-protocol.md)｜能力矩阵：[plugin-sdk-capabilities.md](plugin-sdk-capabilities.md)
> 源码 `sdk/java/src/main/java/dev/flowerie/sdk/`（`FloweriePlugin.java` + `Json.java`）· 示例 `examples/multilang-sdk/java/`（最小插件实测）与 `examples/java-plugin/`（契约/WebUI 用例）· CI 实测：`tests/sdk/test_minimal_plugins.py::test_build_load_ready_and_api[java]`、`tests/sdk/test_minimal_paths.py::test_plugin_communication_path[typescript->java]`、`tests/test_plugin_sdk_contract.py::test_handshake_declares_protocol_and_capabilities[java]`、`tests/test_plugin_webui_multilang.py::test_webui_page_receives_engine_context[java]`

## 1. 安装与引入
- **零第三方依赖**：只用 JDK（`java.io/nio/util/regex`）；SDK 就是两个源文件 `FloweriePlugin.java` + `Json.java`（自研 JSON，`Json.java:14`），不打包 jar、不用 Maven/Gradle/Gson。
- 工具链 **JDK 11+**：源码用了 `List.of`（`FloweriePlugin.java:49`）、`var`（:280）、`Files.readString/writeString`（:270/:286）；CI 装 Java 17（`.github/workflows/ci.yml:96-99`）。
- 引入：把这两个源文件和插件源码一起 `javac`（§8），不必拷进插件目录；SDK 定位用 `FLOWERIE_JAVA_SDK_DIR` → `FLOWERIE_SDK_JAVA` → `FLOWERIE_SDK_DIR` → `FLOWERIE_REPO_ROOT` → `GITHUB_WORKSPACE`，都不命中就从插件目录逐级向上找仓库根（`examples/multilang-sdk/java/build.sh:37-63`）；入口认 `JAVA_BIN`（`run.sh:15`）。

## 2. 最小插件（可直接复制）
清单逐字取自 `examples/java-plugin/manifest.json`（只删行：`author`/`description`/`webui.*` 权限与 `web_ui` 段；`api_version` 写 `"1"` 或 `1` 都能过校验，`src/plugins/manifest.py:165` 会 `str()` 归一）：
```json
{ "id": "java_demo", "name": "Java 示例插件", "version": "1.0.0",
  "runtime": "exec", "entry": "run.sh", "api_version": "1",
  "permissions": ["send_message", "plugin.emit"] }
```
入口逐字取自 `examples/java-plugin/src/Plugin.java`（省略处已标出；多语言版见 `examples/multilang-sdk/java/src/MinimalPlugin.java`）：
```java
import dev.flowerie.sdk.FloweriePlugin;
import dev.flowerie.sdk.Json;

public final class Plugin {
    public static void main(String[] args) throws Exception {
        FloweriePlugin plugin = new FloweriePlugin();
        plugin.onStartup(ctx -> ctx.log("启动 " + ctx.pluginId()));               // :18-22
        plugin.onMessage((ctx, event) -> "ping".equals(event.get("text"))
                ? Json.obj("type", "send_message",                                   // 引擎只读 action["payload"]
                           "payload", Json.obj("group_id", event.get("group_id"), "message", "pong"))
                : null);                                                              // 不匹配回 null = 无动作
        // 省略：registerHook / webUI()（:42-129，见 §6）、on("*")（:97）
        plugin.onShutdown(ctx -> ctx.log("java 示例插件退出"));
        plugin.run();
    }
}
```

## 3. 事件注册（出处 `FloweriePlugin.java`）
| 事件 / 钩子 | 本语言写法 |
| :--- | :--- |
| initialize / shutdown / 主循环 / `message` | `plugin.onStartup(ctx -> …)` :446 · `onShutdown` :452 · `plugin.run()` :546 · `plugin.onMessage((ctx, event) -> 动作或 null)` :458（**message 只投给这里** :656-657）|
| `command` / `notice` / `request` / `lifecycle` / `schedule` | `onCommand` / `onNotice` / `onRequest` / `onLifecycle` / `onSchedule`，都是 `onEvent("<名>", …)` 的别名（:476-498）；任意事件用 `plugin.onEvent("test.event", (ctx, event) -> null)` :464 |
| health / 控制面 hook | `plugin.onHealth(ctx -> true)` :470（返回 false 即不健康）· `plugin.registerHook(name, args -> …)` :501（名字须匹配 `^[a-z_][a-z0-9_]{0,63}$` :690）|
| 插件间事件 | `plugin.on("name", event -> …)`，`"*"` 订阅全部 :903（与引擎事件是两条通道）|

## 4. API 表（出处 `FloweriePlugin.java` / `Json.java`）
| 能力 | 本语言签名 / 写法 |
| :--- | :--- |
| 生命周期 / 上下文 / 日志 | `onStartup` :446 · `onShutdown` :452 · `run()` :546 · `plugin.context()` :541 · `ctx.pluginId()` :244 · `ctx.log(msg)` :248（stderr）｜ 动作（副作用出口）：`ctx.action("send_message", Map.of("group_id", …, "message", …))` :380；事件钩子里直接 `return Json.obj("type", "send_message", "payload", payload)`（`MinimalPlugin.java:583`）|
| 存储 / 配置 / 权限 | `storageGet` :265 · `storageSet` :273 · `storageDelete` :290 · `storageList` :294 · `configGet` :331 · `configSet` :343 · `permissionCheck` :366 |
| 控制面 / WebUI / JSON | `ctx.info()` :373 · `registerHook` :501 · `webUI()` :512-537 · `Json.obj/parse/dump/get`（`Json.java:172/27/39/158`）|
| 插件间通信 / 错误 | `call` :797 · `callAsync` :842 · `emit` :864 · `cancel` :886 · `on` :903 · `expose` :916 · `commContext` :937 · `PluginCommException` :77 · `CallOptions` :134 |

## 5. 存储 / 配置 / 权限（通用语义见 [plugin-sdk.md §5](plugin-sdk.md#5-存储配置与权限)）
- 存储：`storageGet/Set/Delete/List` 都抛 checked `IOException`；键须匹配 `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`（`FloweriePlugin.java:45`），值 ≤64 KiB/键、≤200 键（:41-42），落插件 `data/storage/<key>.json`（:252-262）。
- 配置：`configGet()` = 操作员配置（引擎 op）+ 插件覆盖层，**操作员的值优先**（:329-339）；`configSet(Map)` 只写覆盖层（≤8 KiB/值、≤64 键，:43-44）。
- 权限：`permissionCheck("send_message")` 只读查管理员已批准集合，无法提权（:366）；权限先写进 manifest `permissions`（`src/plugins/manifest.py:168-181`）。

## 6. WebUI
`manifest.json` 的 `web_ui` 段（`examples/java-plugin/manifest.json:22-42`）：`static` 静态目录 + `entry` 文件页模板变量钩子名 + `pages[]`（`file` = 磁盘 `.html`，`render:"plugin"` = HTML 由插件进程给，都不写 = 旧 DSL；校验规则见 [plugin-webui-protocol.md](plugin-webui-protocol.md) §3）。
```java
plugin.registerHook("webui_page", hookArgs ->                       // 文件页模板变量（Plugin.java:60-61）
        Json.obj("vars", Json.obj("nickname", readNickname(plugin))));
plugin.webUI()                                                      // Plugin.java:63-93
        .page(webuiArgs -> Json.obj("html", settingsForm(…), "vars", Json.obj("nickname", readNickname(plugin))))
        // 省略：.action(webuiArgs -> {…}) 读 form，回 html/vars/message/config_set/storage_set（:67-86）
        // 省略：.asset(webuiArgs -> {…}) 回 content_type/body，未知 path 回 {"ok":false,"error"}（:87-93）
```

## 7. 插件间通信
`call(target, method, params, opts)` :797 · `callAsync(...)` :842 · `emit(name, payload)` :864 · `cancel(requestId, reason)` :886 · `on(name, handler)` :903 · `expose(method, handler)` :916；失败一律 `PluginCommException`（:77，`getCode()`/`getMessage()`/`getData()`），不自动重试。`CallOptions`（:134）默认 timeout 5000ms、route `auto`，出站自动带 `trace_id`/`hop_count`（:812-813），`commContext()` :937 读当前链路。通用语义见 [plugin-sdk.md §7](plugin-sdk.md#7-插件间通信)。

## 8. 构建与运行
- 构建（`examples/multilang-sdk/java/build.sh`）：查 `javac`（:27-29，缺则打印「BLOCKED BY ENVIRONMENT」并非零退出）→ 定位 SDK（:37-63）→ `javac -encoding UTF-8 -d "$CLASSES_DIR" <SDK>/Json.java <SDK>/FloweriePlugin.java "$HERE/src/MinimalPlugin.java"`（:72-75）→ 校验 `.build/classes/MinimalPlugin.class`（:79）。
- 运行：`sh run.sh` → `exec java -Dfile.encoding=UTF-8 -cp .build/classes MinimalPlugin`（`run.sh:21`）；产物不存在或 `java` 不在时 exit 1（:10-19），`JAVA_BIN` 可换 java。
- `examples/java-plugin/` 没有 build.sh：`run.sh:4-12` 启动时 `javac` 编到 `$FLOWERIE_JAVA_BUILD_DIR`（默认 `mktemp -d`）再 `exec java -cp … Plugin`；CI 真跑 `pytest -q -s tests/sdk/`（`.github/workflows/ci.yml:68-69`）。

## 9. 常见错误
| 症状 | 原因 → 处理（出处）|
| :--- | :--- |
| 动作被拒（理由「未知 action，不允许执行（白名单外）」）| 把动作写成 `{"type":"send_group_msg","params":{…}}`：引擎只执行白名单动作，且只读 `action["payload"]`（`src/plugins/manager.py:1327-1329`、`src/plugins/permissions.py:363-379`）→ 写 `Json.obj("type","send_message","payload", payload)`（`examples/multilang-sdk/java/src/MinimalPlugin.java:583`）|
| `onEvent("message", …)` 收不到消息 | 源码只把 `message` 投给 `onMessage` 注册的钩子（:656-657）→ 用 `plugin.onMessage(...)`，`onEvent(name, …)` 接其它事件 |
| javac 报「变量 args 已定义」| lambda 形参不能与 `main(String[] args)` 重名（CI 抓到）→ 形参改名，仓库示例统一用 `hookArgs` / `webuiArgs`（`Plugin.java:42,64`）；报 unreported exception `IOException` 则因为 `storageGet/Set`、`configGet/Set`、`permissionCheck` 都是 checked `IOException`（:265-366）而 `LifecycleHandler.handle` 不声明 throws（:197-199）→ 在 lambda 内 try/catch（`Plugin.java:44-51`）|
| 插件「启动了但引擎说协议错误 / 没有响应」| 往 stdout 打了非协议内容（stdout 是协议通道，日志走 stderr）→ 一律 `ctx.log(...)` 或 `System.err`（:216-218,:248-250）|
