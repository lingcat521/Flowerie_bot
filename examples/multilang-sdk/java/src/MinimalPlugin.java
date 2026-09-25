import dev.flowerie.sdk.FloweriePlugin;
import dev.flowerie.sdk.Json;

import java.io.IOException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * minimal_java —— 任务书《插件测试》的最小 Java 插件（runtime=exec）。
 *
 * <p>与 examples/multilang-sdk/{python,typescript,go,rust} 的最小插件**语义完全一致**：
 * <ul>
 *   <li>暴露 ping / get_info / echo / slow / boom / seen（经 SDK 的 expose 注册）；</li>
 *   <li>订阅 test.event：记录 payload + 用 SDK 日志打一行 {@code [test.event] <message>}；</li>
 *   <li>message 事件里执行 {@code /sdk@<自己的 plugin_id> <命令>}（只有寻址到自己的命令才执行），
 *       结果用动作 {@code {"type":"send_message","payload":{"group_id":…,"message":"<JSON 字符串>"}}}
 *       回给引擎（引擎执行动作时读的是 payload —— 见 src/plugins/manager.py: _execute_action）。</li>
 * </ul>
 *
 * <p>零第三方依赖：只编译 {@code sdk/java/src/main/java/dev/flowerie/sdk} 下的两个源文件 + 本文件，
 * 只用 JDK（java.io / java.util）。构建见 build.sh，入口见 run.sh。
 */
public final class MinimalPlugin {

    /** SDK 版本（与其它语言最小插件的 sdk_version 对齐）。 */
    private static final String SDK_VERSION = "1.0.0";
    /** 本插件语言标识（ping / get_info 的 runtime 字段）。 */
    private static final String RUNTIME = "java";
    /** 协议版本（SDK 常量，值 "1"）。 */
    private static final String PROTOCOL_VERSION = FloweriePlugin.PROTOCOL_VERSION;
    /** 引擎没在 initialize 里告知 plugin_id 时的兜底（正常路径用不到）。 */
    private static final String FALLBACK_PLUGIN_ID = "minimal_java";
    /** slow 探针的睡眠时长（毫秒）：调用方 200ms 超时应观察到 TIMEOUT。 */
    private static final long SLOW_MS = 1500L;
    /** WebUI 页面上的 Language 一行。 */
    private static final String LANGUAGE = "Java";
    /** WebUI 页面上的 SDK 一行（编译时 import 的那份 SDK 的包名）。 */
    private static final String SDK_NAME = "dev.flowerie.sdk";
    /** 收到过的 test.event payload（seen 用；SDK 是单线程 stdio 循环，不需要加锁）。 */
    private static final List<Object> EVENTS = new ArrayList<Object>();
    /** 收到过的 test.event 日志行（seen 用）："[test.event] <payload.message>"。 */
    private static final List<Object> LOGS = new ArrayList<Object>();

    private MinimalPlugin() {
    }

    public static void main(String[] args) throws Exception {
        final FloweriePlugin plugin = new FloweriePlugin();

        // initialize 期间注册暴露方法（引擎握手完成后即可 plugin.call 到这些方法）
        plugin.onStartup(ctx -> {
            ctx.log("minimal java 插件启动 plugin_id=" + pluginId(plugin));
            plugin.expose("ping", request -> ping(plugin));
            plugin.expose("get_info", request -> getInfo(plugin));
            plugin.expose("echo", request -> echo(request));
            plugin.expose("slow", request -> slow());
            plugin.expose("boom", request -> boom());
            plugin.expose("seen", request -> seen());
        });

        // 引擎事件 test.event（§四）：用 onEvent 注册（on() 是 plugin.event 的订阅，两条通道别混）
        plugin.onEvent("test.event", (ctx, event) -> {
            onTestEvent(plugin, event);
            return null;                       // MessageHandler.handle 返回 Object（引擎忽略事件返回值）
        });

        // 消息事件：/sdk@<自己> 命令
        plugin.onMessage((ctx, event) -> onMessage(plugin, event));

        plugin.onShutdown(ctx -> ctx.log("minimal java 插件退出"));

        // ---------- §23/§12 WebUI：与其它四种语言**同一套** API（page / action） ----------
        // HTML 文件页的模板变量（manifest 的 web_ui.entry，与其它语言同名同义）。
        plugin.registerHook("webui_page", hookArgs ->
                "communication".equals(hookArg(hookArgs, 0))
                        ? Json.obj("vars", communicationVars(pluginId(plugin)))
                        : Json.obj("vars", webuiVars(pluginId(plugin))));
        // 插件渲染页（index / communication）：Plugin 取受控 context 的 plugin id。
        plugin.webUI().page(webuiArgs -> {
            String id = ctxPluginId(webuiArgs, pluginId(plugin));
            if ("communication".equals(pageIdOf(webuiArgs.get("page")))) {
                Map<String, Object> context = castMap(webuiArgs.get("context"));
                Map<String, Object> form = contextForm(context);
                Map<String, Object> vars = isCallAction(context) && !form.isEmpty()
                        ? applyCall(plugin, form, id)
                        : communicationVars(id);
                return Json.obj("html", communicationHtml(vars), "vars", vars);
            }
            return Json.obj("html", webuiHtml(id), "vars", webuiVars(id));
        }).action(webuiArgs -> {
            // 调用页的 POST（按钮 name=plugin_action value=call）-> 真调用 -> 重渲染。
            String id = ctxPluginId(webuiArgs, pluginId(plugin));
            String action = text(webuiArgs.get("action"));
            if (!"communication".equals(pageIdOf(webuiArgs.get("page")))) {
                return Json.obj("ok", Boolean.FALSE, "error", "未知动作: " + action);
            }
            Map<String, Object> form = castMap(webuiArgs.get("form"));
            Map<String, Object> vars;
            if ("call".equals(action) || "call".equals(strField(form, "plugin_action"))) {
                vars = applyCall(plugin, form, id);
            } else {
                vars = communicationVars(id);
                vars.put("message", "未知动作: " + action);
            }
            return Json.obj("html", communicationHtml(vars), "vars", vars,
                    "message", strField(vars, "message"));
        });

        plugin.run();
    }

    // ================= WebUI 最小页面（任务书《plugin_to_webui》§23） =================
    // 五种语言共用**同一套** WebUI API：页面由插件经 webui.page 返回 HTML（No-JS：HTML + CSS）。
    // 路由 / 权限 / 校验 / 净化 / 隔离全部由引擎负责，插件只负责内容。
    // Plugin 与 Runtime 取自受控 context 与 SDK 值，不写死在 HTML 里（部署方改名后页面自动跟随）。

    /** 受控 context 里的 plugin id（引擎按连接识别身份；拿不到才退回 SDK 的 plugin id）。 */
    private static String ctxPluginId(Map<String, Object> args, String fallback) {
        Object context = args == null ? null : args.get("context");
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

    /** 本语言原生的 HTML 转义（插件不假设引擎一定会替自己转义动态数据）。 */
    private static String escapeHtml(String value) {
        StringBuilder out = new StringBuilder(value.length());
        for (int i = 0; i < value.length(); i++) {
            char ch = value.charAt(i);
            switch (ch) {
                case '&': out.append("&amp;"); break;
                case '<': out.append("&lt;"); break;
                case '>': out.append("&gt;"); break;
                case '"': out.append("&quot;"); break;
                case '\'': out.append("&#39;"); break;
                default: out.append(ch);
            }
        }
        return out.toString();
    }

    /** WebUI 模板变量（HTML 文件页的数据钩子与插件渲染页共用一份）。 */
    private static Map<String, Object> webuiVars(String pluginId) {
        return Json.obj("language", LANGUAGE, "sdk", SDK_NAME + " " + SDK_VERSION,
                "plugin_id", pluginId, "runtime", RUNTIME);
    }

    /** 最小 WebUI 页面：<h2>插件页</h2> + Language / SDK / Plugin / Runtime 四项。 */
    private static String webuiHtml(String pluginId) {
        String style = "/panel/plugins/webui/" + pluginId + "/static/style.css";
        return "<link rel=\"stylesheet\" href=\"" + escapeHtml(style) + "\">"
                + "<h2>插件页</h2>"
                + "<dl class=\"flowerie-webui lang-" + RUNTIME + "\" id=\"plugin-info\">"
                + "<dt>Language</dt><dd class=\"language\">" + escapeHtml(LANGUAGE) + "</dd>"
                + "<dt>SDK</dt><dd class=\"sdk\">"
                + escapeHtml(SDK_NAME + " " + SDK_VERSION) + "</dd>"
                + "<dt>Plugin</dt><dd class=\"plugin\">" + escapeHtml(pluginId) + "</dd>"
                + "<dt>Runtime</dt><dd class=\"runtime\">" + escapeHtml(RUNTIME) + "</dd>"
                + "</dl>";
    }

    // ============ WebUI 调用页（任务书《plugin_to_webui》§12/§28） ============
    // 页面契约见 tests/e2e/README.md §3：元素 id 就是断言契约；零 JS：form POST + 服务端渲染。
    // 真调用：plugin.call -> 引擎 Core Router -> **目标插件进程** -> 结果回本页（失败也如实显示）。

    /** 默认请求（与 tests/e2e 的链路请求同形）。 */
    private static final String DEFAULT_REQUEST = "{\"hello\": \"world\"}";
    /** 引擎给 webui.action 的上限是 4s，这里给 plugin.call 留足余量。 */
    private static final int CALL_TIMEOUT_MS = 2500;
    /** 随请求往返的关联 id（与 tests/e2e 夹具插件同一约定）。 */
    private static final String TRACE_KEY = "_e2e_trace";
    /** 目标没回传时的如实标注。 */
    private static final String UNRETURNED = "（对端未回传）";
    private static final String[] COMM_METHODS = {"ping", "echo", "get_info", "no_such_method"};
    private static final String[] COMM_ROUTES = {"auto", "core", "local"};
    /** 本页调用序号（SDK 是单线程 stdio 循环，不需要加锁）。 */
    private static long CALL_SEQ = 0;

    /** 本页这次调用的关联 id（插件侧生成）。 */
    private static String newCallId() {
        CALL_SEQ++;
        return Long.toHexString(System.nanoTime()) + Long.toHexString(CALL_SEQ);
    }

    /** 取字符串字段（缺失/类型不对一律空串）。 */
    private static String strField(Map<String, Object> obj, String key) {
        Object value = obj == null ? null : obj.get(key);
        return value instanceof String ? (String) value : "";
    }

    /** 把任意值当 Map 用（不是 Map 就给空 Map）。 */
    @SuppressWarnings("unchecked")
    private static Map<String, Object> castMap(Object value) {
        return value instanceof Map ? (Map<String, Object>) value
                : new LinkedHashMap<String, Object>();
    }

    /** 取 page 的 id（引擎给的是对象 {id,title,description}）。 */
    private static String pageIdOf(Object page) {
        String id = strField(castMap(page), "id");
        if (!id.isEmpty()) {
            return id;
        }
        return page == null ? "index" : String.valueOf(page);
    }

    /** 引擎若把表单塞进 context（当前版本不塞；webui.action 的 form 才是常规通道）。 */
    private static Map<String, Object> contextForm(Map<String, Object> context) {
        return castMap(context == null ? null : context.get("form"));
    }

    private static boolean isCallAction(Map<String, Object> context) {
        Map<String, Object> request = castMap(context == null ? null : context.get("request"));
        return "call".equals(strField(request, "action"));
    }

    /** 目标插件**自报**的 runtime：先看回包，再问一次 get_info；都拿不到就留空（不编造）。 */
    private static String observedRuntime(FloweriePlugin plugin, String target, String routePolicy,
                                          Map<String, Object> result) {
        String runtime = strField(result, "runtime");
        if (!runtime.isEmpty()) {
            return runtime;
        }
        try {
            Object info = plugin.call(target, "get_info", new LinkedHashMap<String, Object>(),
                    FloweriePlugin.CallOptions.of(CALL_TIMEOUT_MS).route(routePolicy));
            return strField(castMap(info), "runtime");
        } catch (Exception e) {   // 目标没有 get_info 时留空，不编造
            return "";
        }
    }

    /** 真调用目标插件；任何失败都变成页面可渲染的结构化结果。 */
    private static Map<String, Object> callTarget(FloweriePlugin plugin, String target,
                                                  String method, String requestText,
                                                  String routePolicy) {
        Map<String, Object> out = new LinkedHashMap<String, Object>();
        String text = requestText == null ? "" : requestText.trim();
        Object parsed = new LinkedHashMap<String, Object>();
        if (!text.isEmpty()) {
            try {
                parsed = Json.parse(text);
            } catch (RuntimeException e) {
                out.put("response_ok", "error");
                out.put("error_code", "INVALID_ARGUMENT");
                out.put("error", "INVALID_ARGUMENT: request 不是合法 JSON: " + e.getMessage());
                return out;
            }
        }
        if (!(parsed instanceof Map)) {
            out.put("response_ok", "error");
            out.put("error_code", "INVALID_ARGUMENT");
            out.put("error", "INVALID_ARGUMENT: request 必须是 JSON 对象");
            return out;
        }
        Map<String, Object> params = new LinkedHashMap<String, Object>(castMap(parsed));
        String callId = newCallId();
        params.put(TRACE_KEY, callId);   // 发给目标；echo 原样带回 -> 证明回包来自目标进程
        Object result;
        try {
            result = plugin.call(target, method, params,
                    FloweriePlugin.CallOptions.of(CALL_TIMEOUT_MS).route(routePolicy));
        } catch (Exception e) {
            String code = e instanceof FloweriePlugin.PluginCommException
                    ? ((FloweriePlugin.PluginCommException) e).getCode() : "PLUGIN_ERROR";
            out.put("response", Json.dump(Json.obj("ok", Boolean.FALSE, "error",
                    Json.obj("code", code, "message", String.valueOf(e.getMessage())))));
            out.put("response_ok", "error");
            out.put("error_code", code);
            out.put("error", code + ": " + e.getMessage());
            out.put("request_id", callId);
            out.put("request_id_source", "插件侧 call id（调用失败）");
            out.put("trace_id", callId);
            out.put("trace_id_source", "插件侧（调用失败，无回包）");
            return out;
        }
        Map<String, Object> resultMap = castMap(result);
        String traceBack = strField(resultMap, TRACE_KEY);
        if (traceBack.isEmpty()) {
            traceBack = strField(resultMap, "trace_id");
        }
        // 对端回传的引擎字段：_engine 块（夹具约定）与顶层平铺（README §3 约定）都认。
        Map<String, Object> engine = castMap(resultMap.get("_engine"));
        String engineRequestId = strField(engine, "request_id");
        String engineTraceId = strField(engine, "trace_id");
        String engineRoute = strField(engine, "route");
        if (engineRequestId.isEmpty()) {
            engineRequestId = strField(resultMap, "request_id");
        }
        if (engineTraceId.isEmpty()) {
            engineTraceId = strField(resultMap, "trace_id");
        }
        if (engineRoute.isEmpty()) {
            engineRoute = strField(resultMap, "route");
        }
        String traceId = !engineTraceId.isEmpty() ? engineTraceId
                : (!traceBack.isEmpty() ? traceBack : callId);
        String traceSource = !engineTraceId.isEmpty() ? "引擎（目标插件回传）"
                : (!traceBack.isEmpty() ? "目标插件原样回传（随请求往返）" : "插件侧（无回包）");
        boolean fromEngineRequest = !engineRequestId.isEmpty();
        out.put("response", Json.dump(Json.obj("ok", Boolean.TRUE, "result", result)));
        out.put("response_ok", "ok");
        out.put("target_runtime", observedRuntime(plugin, target, routePolicy, resultMap));
        out.put("request_id", fromEngineRequest ? engineRequestId : callId);
        out.put("request_id_source", fromEngineRequest ? "引擎（目标插件回传）" : "插件侧 call id");
        out.put("trace_id", traceId);
        out.put("trace_id_source", traceSource);
        out.put("route", engineRoute.isEmpty() ? routePolicy : engineRoute);
        out.put("route_source", engineRoute.isEmpty() ? "调用方请求的路由策略" : "引擎（目标插件回传）");
        return out;
    }

    /** 调用页的全部模板变量（名字与引擎侧断言一致：response_ok / target_runtime / trace_id …）。 */
    private static Map<String, Object> communicationVars(String pluginId) {
        Map<String, Object> vars = new LinkedHashMap<String, Object>();
        vars.put("plugin_name", pluginId);
        vars.put("plugin_id", pluginId);
        vars.put("plugin_status", "running");
        vars.put("plugin_runtime", RUNTIME);
        vars.put("plugin_sdk_version", SDK_VERSION);
        vars.put("target", "");
        vars.put("method", "echo");
        vars.put("request", DEFAULT_REQUEST);
        vars.put("route_policy", "auto");
        vars.put("response", "");
        vars.put("response_ok", "");
        vars.put("error", "");
        vars.put("error_code", "");
        vars.put("target_runtime", "");
        vars.put("request_id", "");
        vars.put("request_id_source", "");
        vars.put("trace_id", "");
        vars.put("trace_id_source", "");
        vars.put("route", "");
        vars.put("route_source", "");
        vars.put("message", "");
        return vars;
    }

    /** 把表单变成一次真调用 + 一页可渲染的变量（任何分支都必须渲染得出来）。 */
    private static Map<String, Object> applyCall(FloweriePlugin plugin, Map<String, Object> form,
                                                 String pluginId) {
        String target = strField(form, "target").trim();
        String method = strField(form, "method").trim();
        if (method.isEmpty()) {
            method = "ping";
        }
        String requestText = strField(form, "request");
        if (requestText.isEmpty()) {
            requestText = strField(form, "params");
        }
        if (requestText.isEmpty()) {
            requestText = DEFAULT_REQUEST;
        }
        String routePolicy = strField(form, "route").trim();
        if (routePolicy.isEmpty()) {
            routePolicy = "auto";
        }
        Map<String, Object> vars = communicationVars(pluginId);
        vars.put("target", target);
        vars.put("method", method);
        vars.put("request", requestText);
        vars.put("route_policy", routePolicy);
        if (target.isEmpty()) {
            vars.put("response_ok", "error");
            vars.put("error_code", "INVALID_ARGUMENT");
            vars.put("error", "INVALID_ARGUMENT: 请填写目标插件 id");
        } else {
            vars.putAll(callTarget(plugin, target, method, requestText, routePolicy));
        }
        String message;
        if ("ok".equals(strField(vars, "response_ok"))) {
            message = "Status: OK · 调用完成";
        } else {
            String code = strField(vars, "error_code");
            message = "Status: Failed · Code: " + (code.isEmpty() ? "PLUGIN_ERROR" : code);
        }
        vars.put("message", message);
        return vars;
    }

    /** 下拉选项（零 JS：select_option 交互依赖它）。 */
    private static String optionsHtml(String[] values, String current) {
        StringBuilder html = new StringBuilder();
        for (String value : values) {
            html.append("<option value=\"").append(escapeHtml(value)).append("\"")
                    .append(value.equals(current) ? " selected" : "").append(">")
                    .append(escapeHtml(value)).append("</option>");
        }
        boolean known = false;
        for (String value : values) {
            if (value.equals(current)) {
                known = true;
                break;
            }
        }
        if (!current.isEmpty() && !known) {
            // 自定义方法名也要能原样回填提交
            html.append("<option value=\"").append(escapeHtml(current)).append("\" selected>")
                    .append(escapeHtml(current)).append("</option>");
        }
        return html.toString();
    }

    /** 调用页 HTML（零 JS）：表单 + 结果区；元素 id 见 tests/e2e/README.md §3。 */
    private static String communicationHtml(Map<String, Object> v) {
        String base = "/panel/plugins/webui/" + escapeHtml(strField(v, "plugin_id"));
        String runtime = strField(v, "target_runtime");
        if (runtime.isEmpty()) {
            runtime = UNRETURNED;
        }
        return "<link rel=\"stylesheet\" href=\"" + base + "/static/style.css\">"
                + "<h1 id=\"plugin-name\">" + escapeHtml(strField(v, "plugin_name")) + "</h1>"
                + "<p id=\"plugin-status\" class=\"status\">状态："
                + escapeHtml(strField(v, "plugin_status")) + "</p>"
                + "<section id=\"communication-panel\" class=\"card\">"
                + "<h2>跨插件调用（Browser → " + escapeHtml(LANGUAGE)
                + " 插件 → Core Router → 目标插件 → 回本页）</h2>"
                + "<form id=\"communication-form\" method=\"post\" action=\"" + base
                + "/communication\">"
                + "<label for=\"communication-target\">目标插件（target plugin）</label>"
                + "<input type=\"text\" id=\"communication-target\" name=\"target\" value=\""
                + escapeHtml(strField(v, "target")) + "\" placeholder=\"minimal_go\">"
                + "<label for=\"communication-method\">方法（method）</label>"
                + "<select id=\"communication-method\" name=\"method\">"
                + optionsHtml(COMM_METHODS, strField(v, "method")) + "</select>"
                + "<label for=\"communication-route\">路由策略（route）</label>"
                + "<select id=\"communication-route\" name=\"route\">"
                + optionsHtml(COMM_ROUTES, strField(v, "route_policy")) + "</select>"
                + "<label for=\"communication-request\">请求参数（request，JSON 对象）</label>"
                + "<textarea id=\"communication-request\" name=\"request\" rows=\"3\">"
                + escapeHtml(strField(v, "request")) + "</textarea>"
                + "<button type=\"submit\" id=\"communication-submit\" name=\"plugin_action\""
                + " value=\"call\">调用</button>"
                + "</form>"
                + "<table id=\"communication-result\">"
                + "<tr><th>target plugin</th><td id=\"communication-target-out\">"
                + escapeHtml(strField(v, "target")) + "</td></tr>"
                + "<tr><th>method</th><td id=\"communication-method-out\">"
                + escapeHtml(strField(v, "method")) + "</td></tr>"
                + "<tr><th>request</th><td><pre id=\"communication-request-out\">"
                + escapeHtml(strField(v, "request")) + "</pre></td></tr>"
                + "<tr><th>response</th><td><pre id=\"communication-response\">"
                + escapeHtml(strField(v, "response")) + "</pre></td></tr>"
                + "<tr><th>request_id</th><td id=\"communication-request-id\">"
                + escapeHtml(strField(v, "request_id"))
                + " <small id=\"communication-request-id-source\">"
                + escapeHtml(strField(v, "request_id_source")) + "</small></td></tr>"
                + "<tr><th>trace_id</th><td id=\"communication-trace-id\">"
                + escapeHtml(strField(v, "trace_id"))
                + " <small id=\"communication-trace-id-source\">"
                + escapeHtml(strField(v, "trace_id_source")) + "</small></td></tr>"
                + "<tr><th>route</th><td id=\"communication-route-out\">"
                + escapeHtml(strField(v, "route"))
                + " <small id=\"communication-route-source\">"
                + escapeHtml(strField(v, "route_source")) + "</small></td></tr>"
                + "<tr><th>目标运行时（观察值）</th><td id=\"communication-target-runtime\">"
                + escapeHtml(runtime) + "</td></tr>"
                + "<tr><th>结果</th><td id=\"communication-response-ok\">"
                + escapeHtml(strField(v, "response_ok")) + "</td></tr>"
                + "<tr><th>错误</th><td id=\"communication-error\">"
                + escapeHtml(strField(v, "error")) + "</td></tr>"
                + "</table>"
                + "<p id=\"communication-message\">" + escapeHtml(strField(v, "message")) + "</p>"
                + "</section>"
                + "<nav id=\"plugin-nav\"><a id=\"nav-index\" href=\"" + base + "/index\">Index</a>"
                + "<a id=\"nav-communication\" href=\"" + base
                + "/communication\">Communication</a></nav>";
    }

    // ================= 暴露的方法（§二 契约） =================

    /** ping：{ok, plugin(label), runtime}；label = plugin_id 的 _ 换成 -。 */
    private static Object ping(FloweriePlugin plugin) {
        Map<String, Object> out = new LinkedHashMap<String, Object>();
        out.put("ok", Boolean.TRUE);
        out.put("plugin", label(plugin));
        out.put("runtime", RUNTIME);
        return out;
    }

    /** get_info：{plugin_id, runtime, sdk_version, protocol_version}。 */
    private static Object getInfo(FloweriePlugin plugin) {
        Map<String, Object> out = new LinkedHashMap<String, Object>();
        out.put("plugin_id", pluginId(plugin));
        out.put("runtime", RUNTIME);
        out.put("sdk_version", SDK_VERSION);
        out.put("protocol_version", PROTOCOL_VERSION);
        return out;
    }

    /** echo：原样返回 request.params。 */
    private static Object echo(Map<String, Object> request) {
        Object params = request.get("params");
        return params == null ? new LinkedHashMap<String, Object>() : params;
    }

    /** slow：睡 1500ms 后 {slept:true}（TIMEOUT 探针）。 */
    private static Object slow() {
        try {
            Thread.sleep(SLOW_MS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        return Json.obj("slept", Boolean.TRUE);
    }

    /** boom：抛异常（PLUGIN_ERROR 探针；SDK 把 handler 异常翻成结构化 PLUGIN_ERROR）。 */
    private static Object boom() {
        throw new IllegalStateException("minimal java plugin boom");
    }

    /** seen：{events:[收到过的 test.event payload], logs:["[test.event] <message>"]}。 */
    private static Object seen() {
        Map<String, Object> out = new LinkedHashMap<String, Object>();
        out.put("events", new ArrayList<Object>(EVENTS));
        out.put("logs", new ArrayList<Object>(LOGS));
        return out;
    }

    // ================= test.event =================

    /**
     * test.event：记录 payload。
     *
     * <p>两条投递路径都要认：plugin.event（插件间事件，params={name,payload,…}）取 payload 字段；
     * 引擎的事件派发（params.payload 平铺 + event/plugin_id）则去掉协议字段后原样记录。
     */
    private static void onTestEvent(FloweriePlugin plugin, Map<String, Object> event) {
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        Object raw = event.get("payload");
        if (raw instanceof Map) {
            for (Map.Entry<?, ?> entry : ((Map<?, ?>) raw).entrySet()) {
                payload.put(String.valueOf(entry.getKey()), entry.getValue());
            }
        } else {
            for (Map.Entry<String, Object> entry : event.entrySet()) {
                String key = entry.getKey();
                // 协议字段不属于 payload（两条投递路径的字段名并集）
                if ("name".equals(key) || "payload".equals(key) || "trace_id".equals(key)
                        || "hop_count".equals(key) || "event".equals(key)
                        || "plugin_id".equals(key)) {
                    continue;
                }
                payload.put(key, entry.getValue());
            }
        }
        EVENTS.add(payload);
        String line = "[test.event] " + text(payload.get("message"));
        LOGS.add(line);
        plugin.context().log(line);            // SDK 日志（stderr，引擎侧可见）
    }

    // ================= message 事件：/sdk 命令 =================

    /** message 事件：命中自己的命令 -> 执行 -> 用 send_message 动作把结果 JSON 回给引擎。 */
    private static Object onMessage(FloweriePlugin plugin, Map<String, Object> event) {
        String command = addressedToMe(plugin, text(event.get("text")));
        if (command == null) {
            return null;                       // 不是发给自己的命令（事件是广播的）：不回动作
        }
        Object result;
        try {
            result = runCommand(plugin, command);
        } catch (FloweriePlugin.PluginCommException e) {
            result = failure(e.getCode(), e.getMessage());
        } catch (Exception e) {                 // 含 Json.JsonException / IllegalArgumentException
            result = failure("PLUGIN_ERROR", e.getMessage() == null ? e.toString() : e.getMessage());
        }
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("group_id", event.get("group_id"));
        payload.put("message", Json.dump(result));
        // 引擎执行动作时读 action["payload"]（src/plugins/manager.py: _execute_action）
        return Json.obj("type", "send_message", "payload", payload);
    }

    /** 结构化失败（§八/§九）：message 永远是 {ok:false, code, message}。 */
    private static Map<String, Object> failure(String code, String message) {
        Map<String, Object> out = new LinkedHashMap<String, Object>();
        out.put("ok", Boolean.FALSE);
        out.put("code", code == null ? "PLUGIN_ERROR" : code);
        out.put("message", message == null ? "" : message);
        return out;
    }

    /**
     * 命令是否发给本插件：{@code /sdk@<自己的 plugin_id> ...} 才执行，别人的命令返回 null。
     *
     * <p>兼容老形式 {@code /sdk ...}（可选）；返回值统一成 {@code /sdk ...} 形式。
     */
    private static String addressedToMe(FloweriePlugin plugin, String raw) {
        if (raw.startsWith("/sdk@")) {
            String rest = raw.substring("/sdk@".length());
            int space = rest.indexOf(' ');
            String executor = space < 0 ? rest : rest.substring(0, space);
            if (!pluginId(plugin).equals(executor)) {
                return null;                   // 别人的命令：不回动作（避免多插件同时回包）
            }
            return "/sdk " + (space < 0 ? "" : rest.substring(space + 1));
        }
        if (raw.startsWith("/sdk ")) {
            return raw;
        }
        return null;
    }

    /** 命令分发（与 Python/TS/Go/Rust 最小插件同一张表）。 */
    private static Object runCommand(FloweriePlugin plugin, String text) throws Exception {
        String[] parts = text.split(" ", 3);
        if (parts.length < 2) {
            throw new IllegalArgumentException("空命令");
        }
        String head = parts[1];
        String rest = parts.length > 2 ? parts[2] : "";
        String[] argv = rest.isEmpty() ? new String[0] : rest.split(" ");
        if ("ping".equals(head)) {
            return call(plugin, arg(argv, 0), "ping", null, null, null);
        }
        if ("info".equals(head)) {
            return getInfo(plugin);
        }
        if ("echo".equals(head)) {
            return rest.isEmpty() ? new LinkedHashMap<String, Object>() : Json.parse(rest);
        }
        if ("seen".equals(head)) {
            return call(plugin, arg(argv, 0), "seen", null, null, null);
        }
        if ("call".equals(head)) {
            // 第 3 段整体是 JSON（允许带空格），不做 " " 切分
            return call(plugin, arg(argv, 0), arg(argv, 1), mapOf(afterTokens(rest, 2)), null, null);
        }
        if ("route".equals(head)) {
            return call(plugin, arg(argv, 1), arg(argv, 2), null, arg(argv, 0), null);
        }
        if ("chain".equals(head)) {
            Map<String, Object> out = new LinkedHashMap<String, Object>();
            out.put("t1", call(plugin, arg(argv, 0), "ping", null, null, null));
            out.put("t2", call(plugin, arg(argv, 1), "echo", Json.obj("hello", "world"), null, null));
            out.put("t3", call(plugin, arg(argv, 2), "ping", null, null, null));
            return out;
        }
        if ("errors".equals(head)) {
            return errors(plugin, arg(argv, 0), arg(argv, 1));
        }
        throw new IllegalArgumentException("未知命令: " + head);
    }

    /** /sdk errors：依次触发六种错误，每种都回**本语言原生错误模型**的观察结果。 */
    private static Object errors(final FloweriePlugin plugin, final String granted, final String denied) {
        Map<String, Object> out = new LinkedHashMap<String, Object>();
        out.put("METHOD_NOT_FOUND", probe(() -> call(plugin, granted, "no_such_method", null, null, null)));
        out.put("PLUGIN_NOT_FOUND", probe(() -> call(plugin, "no_such_plugin", "ping", null, null, null)));
        out.put("PERMISSION_DENIED", probe(() -> call(plugin, denied, "ping", null, null, null)));
        out.put("INVALID_ARGUMENT", probe(() -> call(plugin, "", "ping", null, null, null)));
        out.put("TIMEOUT", probe(() -> call(plugin, granted, "slow", null, null, Integer.valueOf(200))));
        out.put("PLUGIN_ERROR", probe(() -> call(plugin, granted, "boom", null, null, null)));
        return out;
    }

    /** 一次错误探针。 */
    private interface Probe {
        Object run() throws Exception;
    }

    /** 探针观察：成功算 NO_ERROR（不撒谎），失败取本语言异常类型名 + 错误码 + 消息。 */
    private static Object probe(Probe probe) {
        Map<String, Object> record = new LinkedHashMap<String, Object>();
        try {
            probe.run();
            record.put("native", null);
            record.put("code", "NO_ERROR");
            record.put("message", "预期失败但调用成功了");
            return record;
        } catch (FloweriePlugin.PluginCommException e) {
            record.put("native", e.getClass().getSimpleName());
            record.put("code", e.getCode());
            record.put("message", e.getMessage() == null ? "" : e.getMessage());
            return record;
        } catch (Exception e) {
            record.put("native", e.getClass().getSimpleName());
            record.put("code", "PLUGIN_ERROR");
            record.put("message", e.getMessage() == null ? "" : e.getMessage());
            return record;
        }
    }

    // ================= Plugin-to-Plugin（出站一律经 SDK，没有第二条通道） =================

    /** plugin.call 的统一入口：route/timeout 为 null 时用 SDK 默认（auto / 5000ms）。 */
    private static Object call(FloweriePlugin plugin, String target, String method,
                               Map<String, Object> params, String route, Integer timeoutMs)
            throws FloweriePlugin.PluginCommException {
        FloweriePlugin.CallOptions opts = new FloweriePlugin.CallOptions();
        if (route != null && !route.isEmpty()) {
            opts.route(route);
        }
        if (timeoutMs != null) {
            opts.timeout(timeoutMs.intValue());
        }
        Map<String, Object> body = params == null ? new LinkedHashMap<String, Object>() : params;
        return plugin.call(target == null ? "" : target, method == null ? "" : method, body, opts);
    }

    // ================= 小工具 =================

    /** 自己的 plugin_id：引擎在 initialize 的 context.plugin_id 里告知（身份由连接决定）。 */
    private static String pluginId(FloweriePlugin plugin) {
        String id = plugin.context().pluginId();
        if (id != null && !id.isEmpty() && !"unknown".equals(id)) {
            return id;
        }
        try {
            Object info = plugin.context().info();
            Object value = Json.get(info, "plugin_id");
            if (value instanceof String && !((String) value).isEmpty()) {
                return (String) value;
            }
        } catch (IOException e) {
            // 引擎不可用：退化为 manifest.id，不把异常抛给事件层
        }
        return FALLBACK_PLUGIN_ID;
    }

    /** ping 里的 label：plugin_id 的 _ 换成 -（如 minimal_java -> minimal-java）。 */
    private static String label(FloweriePlugin plugin) {
        return pluginId(plugin).replace('_', '-');
    }

    /** argv 取值（越界/缺失一律空串，不抛异常）。 */
    private static String arg(String[] argv, int index) {
        return argv != null && index >= 0 && argv.length > index && argv[index] != null
                ? argv[index] : "";
    }

    /** 跳过前 count 个空格分隔的 token，返回剩余文本（用于尾部 JSON；不足则空串）。 */
    private static String afterTokens(String text, int count) {
        int index = 0;
        for (int i = 0; i < count && index < text.length(); i++) {
            while (index < text.length() && text.charAt(index) == ' ') {
                index++;
            }
            while (index < text.length() && text.charAt(index) != ' ') {
                index++;
            }
        }
        while (index < text.length() && text.charAt(index) == ' ') {
            index++;
        }
        return index >= text.length() ? "" : text.substring(index);
    }

    /** JSON 文本 -> params 对象（空/非对象一律空对象）。 */
    private static Map<String, Object> mapOf(String json) {
        if (json == null || json.isEmpty()) {
            return new LinkedHashMap<String, Object>();
        }
        Object parsed = Json.parse(json);
        if (parsed instanceof Map) {
            @SuppressWarnings("unchecked")
            Map<String, Object> map = (Map<String, Object>) parsed;
            return map;
        }
        return new LinkedHashMap<String, Object>();
    }

    /** 任意值 -> 字符串（null 变空串）。 */
    /** hook 的 args 是协议数组解出来的 List&lt;Object&gt;：取第 index 个并转成字符串（缺失给空串）。 */
    private static String hookArg(List<Object> args, int index) {
        if (args == null || index < 0 || index >= args.size() || args.get(index) == null) {
            return "";
        }
        return text(args.get(index));
    }

    private static String text(Object value) {
        if (value == null) {
            return "";
        }
        return value instanceof String ? (String) value : String.valueOf(value);
    }
}

