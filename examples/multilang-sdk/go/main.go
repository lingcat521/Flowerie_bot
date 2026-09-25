// minimal_go —— 任务书《插件测试》的多语言最小插件（Go 实现）。
//
// 只用 sdk/go/flowerie（零第三方依赖，仅标准库），语义与 minimal_py / minimal_ts /
// minimal_rust / minimal_java 完全一致：
//
//   - 暴露方法（plugin.Expose）：ping / get_info / echo / slow / boom / seen
//   - 事件：test.event 记录 payload 与 "[test.event] <message>" 日志行
//   - 命令：message 事件的 text 形如 /sdk@<自己的 plugin_id> <命令>；
//     发给别人的命令返回 nil（不回动作 —— 引擎的 message 事件是广播的）
//   - 动作：{"type":"send_message","payload":{"group_id":<事件里的 group_id>,"message":"<结果 JSON>"}}
//     引擎执行动作时读的是 action["payload"]（见 src/plugins/manager.py:_execute_action），
//     写成 action["params"] 会拿到空 payload —— 消息发不出去。
//
// 构建：./build.sh（真编译，产物 .build/plugin）；运行：./run.sh（exec 该产物，runtime=exec）。
package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"html"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/lingcat521/Flowerie_bot/sdk/go/flowerie"
)

const (
	sdkVersion     = "1.0.0"      // get_info 的 sdk_version
	runtimeName    = "go"         // get_info / ping 的 runtime
	fallbackID     = "minimal_go" // initialize 之前的兜底 plugin_id
	commandPrefix  = "/sdk"       // 命令前缀（完整形式 /sdk@<plugin_id> <命令>）
	eventLogPrefix = "[test.event] "
	slowMillis     = 1500 // slow 探针的睡眠时长（TIMEOUT 探针的对照面）
	probeTimeoutMs = 200  // /sdk errors 里 TIMEOUT 探针的调用超时
)

// ---------------- 进程内状态 ----------------

// pluginState 是插件自己的状态（§四：test.event 的记录放这里，see seen 命令可读）。
type pluginState struct {
	mu     sync.Mutex
	events []any
	logs   []string
}

func (s *pluginState) record(payload map[string]any, line string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.events = append(s.events, payload)
	s.logs = append(s.logs, line)
}

func (s *pluginState) eventsSnapshot() []any {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]any, len(s.events))
	copy(out, s.events)
	return out
}

func (s *pluginState) logsSnapshot() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]string, len(s.logs))
	copy(out, s.logs)
	return out
}

// minimal 是本插件的全部依赖：SDK 插件对象 + 状态。
type minimal struct {
	plugin *flowerie.Plugin
	state  *pluginState
}

func main() {
	app := &minimal{plugin: flowerie.New(), state: &pluginState{}}

	// §二 暴露方法：被其它插件的 plugin.call 调用的一面。
	methods := []struct {
		name    string
		handler flowerie.Handler
	}{
		{"ping", app.ping},
		{"get_info", app.getInfo},
		{"echo", app.echo},
		{"slow", app.slow},
		{"boom", app.boom},
		{"seen", app.seen},
	}
	for _, method := range methods {
		if err := app.plugin.Expose(method.name, method.handler); err != nil {
			fmt.Fprintf(os.Stderr, "[minimal_go] 暴露方法 %s 失败: %v\n", method.name, err)
			os.Exit(1)
		}
	}

	app.plugin.OnStartup(app.onStartup)
	app.plugin.OnShutdown(app.onShutdown)
	app.plugin.OnHealth(func(ctx *flowerie.Context) bool { return true })
	// test.event 是引擎事件（dispatch_event），走 On 的「引擎事件钩子」分支。
	app.plugin.On("test.event", app.onTestEvent)
	app.plugin.OnMessage(app.onMessage)

	// §23/§12 WebUI：与其它四种语言**同一套** API（plugin.WebUI().Page / .Action）。
	// HTML 文件页的模板变量（manifest 的 web_ui.entry，与其它语言同名同义）。
	app.plugin.RegisterHook("webui_page", func(args ...any) any {
		pluginID := app.pluginID()
		if len(args) > 0 && textOf(args[0]) == "communication" {
			return map[string]any{"vars": app.communicationVars(pluginID)}
		}
		return map[string]any{"vars": app.webuiVars(pluginID)}
	})
	// 插件渲染页（index / communication）：Plugin 取受控 context 的 plugin id。
	app.plugin.WebUI().Page(func(args map[string]any) any {
		pluginID := ctxPluginID(args, app.pluginID())
		if pageID(args["page"]) == "communication" {
			context, _ := args["context"].(map[string]any)
			form := contextForm(context)
			if isCallAction(context) && len(form) > 0 {
				vars := app.applyCall(form, pluginID)
				return map[string]any{"html": app.communicationHTML(vars), "vars": vars}
			}
			vars := app.communicationVars(pluginID)
			return map[string]any{"html": app.communicationHTML(vars), "vars": vars}
		}
		return map[string]any{"html": webuiHTML(pluginID), "vars": app.webuiVars(pluginID)}
	}).Action(func(args map[string]any) any {
		// 调用页的 POST（按钮 name=plugin_action value=call）-> 真调用 -> 重渲染。
		pluginID := ctxPluginID(args, app.pluginID())
		action := textOf(args["action"])
		if pageID(args["page"]) != "communication" {
			return map[string]any{"ok": false, "error": "未知动作: " + action}
		}
		form, _ := args["form"].(map[string]any)
		if form == nil {
			form = map[string]any{}
		}
		var vars map[string]any
		if action == "call" || stringField(form, "plugin_action") == "call" {
			vars = app.applyCall(form, pluginID)
		} else {
			vars = app.communicationVars(pluginID)
			vars["message"] = "未知动作: " + action
		}
		return map[string]any{"html": app.communicationHTML(vars), "vars": vars,
			"message": vars["message"]}
	})

	if err := app.plugin.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "[minimal_go] 协议主循环退出: %v\n", err)
		os.Exit(1)
	}
}

// ---------------- 身份（§四 Plugin Identity） ----------------

// pluginID 是引擎在 initialize 里告诉我们的 plugin_id（manifest 的 id，可由部署方改名）。
func (m *minimal) pluginID() string {
	id := strings.TrimSpace(m.plugin.Context().PluginID)
	if id == "" || id == "unknown" {
		return fallbackID
	}
	return id
}

// label 是 ping 里的 label：plugin_id 把 "_" 换成 "-"（minimal_go -> minimal-go）。
func (m *minimal) label() string {
	return strings.ReplaceAll(m.pluginID(), "_", "-")
}

// ---------------- 生命周期 ----------------

func (m *minimal) onStartup(ctx *flowerie.Context) {
	ctx.Logf("minimal_go 已启动 id=%s dir=%s", m.pluginID(), ctx.PluginDir)
}

func (m *minimal) onShutdown(ctx *flowerie.Context) {
	ctx.Logf("minimal_go 已停止 id=%s events=%d", m.pluginID(), len(m.state.eventsSnapshot()))
}

// ---------------- §二 暴露方法 ----------------

// ping：{"ok":true,"plugin":"<label>","runtime":"go"}。
func (m *minimal) ping(request map[string]any) any {
	return map[string]any{"ok": true, "plugin": m.label(), "runtime": runtimeName}
}

// get_info：身份 + SDK/协议版本。
func (m *minimal) getInfo(request map[string]any) any {
	return map[string]any{
		"plugin_id":        m.pluginID(),
		"runtime":          runtimeName,
		"sdk_version":      sdkVersion,
		"protocol_version": flowerie.ProtocolVersion,
	}
}

// echo：原样返回 request.params（任意 JSON 都行）。
func (m *minimal) echo(request map[string]any) any {
	if params, ok := request["params"]; ok && params != nil {
		return params
	}
	return map[string]any{}
}

// slow：睡 1500ms 再回（TIMEOUT 探针的目标方法）。
func (m *minimal) slow(request map[string]any) any {
	time.Sleep(slowMillis * time.Millisecond)
	return map[string]any{"slept": true}
}

// boom：panic —— SDK 的 invokeHandler 兜住并回 PLUGIN_ERROR（PLUGIN_ERROR 探针）。
func (m *minimal) boom(request map[string]any) any {
	panic("minimal go plugin boom")
}

// seen：返回收到过的 test.event payload 与日志行（§四）。
func (m *minimal) seen(request map[string]any) any {
	return map[string]any{
		"events": m.state.eventsSnapshot(),
		"logs":   m.state.logsSnapshot(),
	}
}

// ---------------- §四 事件 ----------------

// onTestEvent：记录 payload + 日志行，并**尽力**用 SDK 的日志通道打一行同样的内容。
func (m *minimal) onTestEvent(ctx *flowerie.Context, event map[string]any) any {
	payload := flattenPayload(event)
	line := eventLogPrefix + textOf(payload["message"])
	m.state.record(payload, line)

	// ① SDK 原生日志（Go SDK 的日志出口是 stderr：Context.Logf，stdout 只放协议 JSON）。
	ctx.Logf("%s", line)
	// ② 引擎侧日志（与 Python 的 api.log("info", ...) 同一条动作通道）。
	//    尽力而为：失败只记一行 stderr，不影响事件处理。
	if _, err := ctx.Action("log", map[string]any{"level": "info", "message": line}); err != nil {
		ctx.Logf("log 动作失败（不影响 test.event 记录）: %v", err)
	}
	return nil
}

// ---------------- WebUI 最小页面（任务书《plugin_to_webui》§23） ----------------
// 五种语言共用**同一套** WebUI API：页面由插件经 webui.page 返回 HTML（No-JS：只有 HTML + CSS）。
// 路由 / 权限 / 校验 / 净化 / 隔离全部由引擎负责，插件只负责内容。
// Plugin 与 Runtime 取自受控 context 与 SDK 值，不写死在 HTML 里（部署方改名后页面自动跟随）。

const (
	languageName = "Go"              // 页面上的 Language
	sdkName      = "sdk/go/flowerie" // 页面上的 SDK（import 的那份 SDK 源码）
)

// webuiVars WebUI 模板变量（HTML 文件页的数据钩子与插件渲染页共用一份）。
func (m *minimal) webuiVars(pluginID string) map[string]any {
	return map[string]any{
		"language":  languageName,
		"sdk":       sdkName + " " + sdkVersion,
		"plugin_id": pluginID,
		"runtime":   runtimeName,
	}
}

// ctxPluginID 受控 context 里的 plugin id（引擎按连接识别身份；拿不到才退回 SDK 的 plugin id）。
func ctxPluginID(args map[string]any, fallback string) string {
	context, _ := args["context"].(map[string]any)
	pluginInfo, _ := context["plugin"].(map[string]any)
	if id, ok := pluginInfo["id"].(string); ok && id != "" {
		return id
	}
	return fallback
}

// webuiHTML 最小 WebUI 页面：<h2>插件页</h2> + Language / SDK / Plugin / Runtime 四项。
func webuiHTML(pluginID string) string {
	style := "/panel/plugins/webui/" + pluginID + "/static/style.css"
	return "<link rel=\"stylesheet\" href=\"" + html.EscapeString(style) + "\">" +
		"<h2>插件页</h2>" +
		"<dl class=\"flowerie-webui lang-" + runtimeName + "\" id=\"plugin-info\">" +
		"<dt>Language</dt><dd class=\"language\">" + html.EscapeString(languageName) + "</dd>" +
		"<dt>SDK</dt><dd class=\"sdk\">" + html.EscapeString(sdkName+" "+sdkVersion) + "</dd>" +
		"<dt>Plugin</dt><dd class=\"plugin\">" + html.EscapeString(pluginID) + "</dd>" +
		"<dt>Runtime</dt><dd class=\"runtime\">" + html.EscapeString(runtimeName) + "</dd>" +
		"</dl>"
}

// ---------------- WebUI 调用页（任务书《plugin_to_webui》§12/§28） ----------------
// 页面契约见 tests/e2e/README.md §3：元素 id 就是断言契约；零 JS：form POST + 服务端渲染。
// 真调用：plugin.call -> 引擎 Core Router -> **目标插件进程** -> 结果回本页（失败也如实显示）。
// 关联 id：随请求发给目标、由目标原样带回（echo 原样回 params 即往返证明）；拿不到就如实标注。

const (
	defaultRequest = `{"hello": "world"}` // 默认请求（与 tests/e2e 的链路请求同形）
	callTimeoutMs  = 2500                // 引擎给 webui.action 的上限是 4s，这里留足余量
	traceKey       = "_e2e_trace"        // 随请求往返的关联 id（与 tests/e2e 夹具插件同一约定）
	unreturned     = "（对端未回传）"
)

var (
	callSeq     uint64
	commMethods = []string{"ping", "echo", "get_info", "no_such_method"}
	commRoutes  = []string{"auto", "core", "local"}
)

// newCallID 本页这次调用的关联 id（插件侧生成）。
func newCallID() string {
	seq := atomic.AddUint64(&callSeq, 1)
	return fmt.Sprintf("%x%02x", time.Now().UnixNano(), seq)
}

// pageID 取 page 的 id（引擎给的是对象 {id,title,description}）。
func pageID(page any) string {
	if obj, ok := page.(map[string]any); ok {
		if id, ok := obj["id"].(string); ok && id != "" {
			return id
		}
	}
	if text, ok := page.(string); ok && text != "" {
		return text
	}
	return "index"
}

// contextForm 引擎若把表单塞进 context（当前版本不塞；webui.action 的 form 才是常规通道）。
func contextForm(context map[string]any) map[string]any {
	if form, ok := context["form"].(map[string]any); ok {
		return form
	}
	return map[string]any{}
}

func isCallAction(context map[string]any) bool {
	request, _ := context["request"].(map[string]any)
	action, _ := request["action"].(string)
	return action == "call"
}

// stringField 取 map 里的字符串字段（缺失/类型不对一律空串）。
func stringField(obj map[string]any, key string) string {
	value, _ := obj[key].(string)
	return value
}

// engineBlock 对端回传的引擎字段：_engine 块（夹具约定）与顶层平铺（README §3 约定）都认。
func engineBlock(result any) map[string]any {
	obj, ok := result.(map[string]any)
	if !ok {
		return map[string]any{}
	}
	out := map[string]any{}
	if engine, ok := obj["_engine"].(map[string]any); ok {
		for key, value := range engine {
			out[key] = value
		}
	}
	for _, key := range []string{"request_id", "trace_id", "route"} {
		if value, ok := obj[key]; ok && value != nil && out[key] == nil {
			out[key] = value
		}
	}
	return out
}

// observedRuntime 目标插件**自报**的 runtime：先看回包，再问一次 get_info；拿不到就留空。
func (m *minimal) observedRuntime(target, routePolicy string, result any) string {
	if obj, ok := result.(map[string]any); ok {
		if runtime := stringField(obj, "runtime"); runtime != "" {
			return runtime
		}
	}
	info, err := m.plugin.Call(target, "get_info", map[string]any{},
		flowerie.WithTimeout(callTimeoutMs), flowerie.WithRoute(routePolicy))
	if err != nil {
		return ""
	}
	if obj, ok := info.(map[string]any); ok {
		return stringField(obj, "runtime")
	}
	return ""
}

// callTarget 真调用目标插件；任何失败都变成页面可渲染的结构化结果。
func (m *minimal) callTarget(target, method, requestText, routePolicy string) map[string]any {
	payload := map[string]any{}
	if trimmed := strings.TrimSpace(requestText); trimmed != "" {
		if err := json.Unmarshal([]byte(trimmed), &payload); err != nil {
			return map[string]any{"response_ok": "error", "error_code": "INVALID_ARGUMENT",
				"error": "INVALID_ARGUMENT: request 不是合法 JSON: " + err.Error()}
		}
	}
	if payload == nil {
		return map[string]any{"response_ok": "error", "error_code": "INVALID_ARGUMENT",
			"error": "INVALID_ARGUMENT: request 必须是 JSON 对象"}
	}
	callID := newCallID()
	params := map[string]any{}
	for key, value := range payload {
		params[key] = value
	}
	params[traceKey] = callID // 发给目标；echo 原样带回 -> 证明回包来自目标进程
	result, err := m.plugin.Call(target, method, params,
		flowerie.WithTimeout(callTimeoutMs), flowerie.WithRoute(routePolicy))
	if err != nil {
		code := errorCode(err)
		body := map[string]any{"ok": false, "error": map[string]any{
			"code": code, "message": err.Error()}}
		return map[string]any{"response": jsonString(body), "response_ok": "error",
			"error_code": code, "error": code + ": " + err.Error(),
			"request_id": callID, "request_id_source": "插件侧 call id（调用失败）",
			"trace_id": callID, "trace_id_source": "插件侧（调用失败，无回包）"}
	}
	traceBack := ""
	if obj, ok := result.(map[string]any); ok {
		traceBack = stringField(obj, traceKey)
		if traceBack == "" {
			traceBack = stringField(obj, "trace_id")
		}
	}
	engine := engineBlock(result)
	engineRequestID := stringField(engine, "request_id")
	engineTraceID := stringField(engine, "trace_id")
	engineRoute := stringField(engine, "route")
	traceID := engineTraceID
	traceSource := "引擎（目标插件回传）"
	if traceID == "" {
		traceID = traceBack
		traceSource = "目标插件原样回传（随请求往返）"
	}
	if traceID == "" {
		traceID = callID
		traceSource = "插件侧（无回包）"
	}
	requestID := engineRequestID
	requestSource := "引擎（目标插件回传）"
	if requestID == "" {
		requestID = callID
		requestSource = "插件侧 call id"
	}
	route := engineRoute
	routeSource := "引擎（目标插件回传）"
	if route == "" {
		route = routePolicy
		routeSource = "调用方请求的路由策略"
	}
	return map[string]any{"response": jsonString(map[string]any{"ok": true, "result": result}),
		"response_ok": "ok",
		"target_runtime": m.observedRuntime(target, routePolicy, result),
		"request_id": requestID, "request_id_source": requestSource,
		"trace_id": traceID, "trace_id_source": traceSource,
		"route": route, "route_source": routeSource}
}

// communicationVars 调用页的全部模板变量（名字与引擎侧断言一致：response_ok / target_runtime …）。
func (m *minimal) communicationVars(pluginID string) map[string]any {
	return map[string]any{
		"plugin_name": pluginID, "plugin_id": pluginID, "plugin_status": "running",
		"plugin_runtime": runtimeName, "plugin_sdk_version": sdkVersion,
		"target": "", "method": "echo", "request": defaultRequest, "route_policy": "auto",
		"response": "", "response_ok": "", "error": "", "error_code": "", "target_runtime": "",
		"request_id": "", "request_id_source": "", "trace_id": "", "trace_id_source": "",
		"route": "", "route_source": "", "message": "",
	}
}

// applyCall 把表单变成一次真调用 + 一页可渲染的变量（任何分支都必须渲染得出来）。
func (m *minimal) applyCall(form map[string]any, pluginID string) map[string]any {
	target := strings.TrimSpace(stringField(form, "target"))
	method := strings.TrimSpace(stringField(form, "method"))
	if method == "" {
		method = "ping"
	}
	requestText := stringField(form, "request")
	if requestText == "" {
		requestText = stringField(form, "params")
	}
	if requestText == "" {
		requestText = defaultRequest
	}
	routePolicy := strings.TrimSpace(stringField(form, "route"))
	if routePolicy == "" {
		routePolicy = "auto"
	}
	vars := m.communicationVars(pluginID)
	vars["target"] = target
	vars["method"] = method
	vars["request"] = requestText
	vars["route_policy"] = routePolicy
	if target == "" {
		vars["response_ok"] = "error"
		vars["error_code"] = "INVALID_ARGUMENT"
		vars["error"] = "INVALID_ARGUMENT: 请填写目标插件 id"
	} else {
		for key, value := range m.callTarget(target, method, requestText, routePolicy) {
			vars[key] = value
		}
	}
	if textOf(vars["response_ok"]) == "ok" {
		vars["message"] = "Status: OK · 调用完成"
	} else {
		code := textOf(vars["error_code"])
		if code == "" {
			code = flowerie.CodePluginError
		}
		vars["message"] = "Status: Failed · Code: " + code
	}
	return vars
}

// htmlEsc 本语言原生的 HTML 转义（插件不假设引擎一定会替自己转义动态数据）。
func htmlEsc(value any) string {
	return html.EscapeString(textOf(value))
}

func containsString(values []string, needle string) bool {
	for _, value := range values {
		if value == needle {
			return true
		}
	}
	return false
}

func optionsHTML(values []string, current string) string {
	var builder strings.Builder
	for _, value := range values {
		builder.WriteString(`<option value="` + htmlEsc(value) + `"`)
		if current == value {
			builder.WriteString(" selected")
		}
		builder.WriteString(">" + htmlEsc(value) + "</option>")
	}
	if current != "" && !containsString(values, current) {
		// 自定义方法名也要能原样回填提交
		builder.WriteString(`<option value="` + htmlEsc(current) + `" selected>` + htmlEsc(current) + "</option>")
	}
	return builder.String()
}

// communicationHTML 调用页 HTML（零 JS）：表单 + 结果区；元素 id 见 tests/e2e/README.md §3。
func (m *minimal) communicationHTML(v map[string]any) string {
	base := "/panel/plugins/webui/" + htmlEsc(v["plugin_id"])
	runtime := textOf(v["target_runtime"])
	if runtime == "" {
		runtime = unreturned
	}
	return `<link rel="stylesheet" href="` + base + `/static/style.css">` +
		`<h1 id="plugin-name">` + htmlEsc(v["plugin_name"]) + `</h1>` +
		`<p id="plugin-status" class="status">状态：` + htmlEsc(v["plugin_status"]) + `</p>` +
		`<section id="communication-panel" class="card">` +
		`<h2>跨插件调用（Browser → ` + htmlEsc(languageName) +
		` 插件 → Core Router → 目标插件 → 回本页）</h2>` +
		`<form id="communication-form" method="post" action="` + base + `/communication">` +
		`<label for="communication-target">目标插件（target plugin）</label>` +
		`<input type="text" id="communication-target" name="target" value="` +
		htmlEsc(v["target"]) + `" placeholder="minimal_go">` +
		`<label for="communication-method">方法（method）</label>` +
		`<select id="communication-method" name="method">` +
		optionsHTML(commMethods, textOf(v["method"])) + `</select>` +
		`<label for="communication-route">路由策略（route）</label>` +
		`<select id="communication-route" name="route">` +
		optionsHTML(commRoutes, textOf(v["route_policy"])) + `</select>` +
		`<label for="communication-request">请求参数（request，JSON 对象）</label>` +
		`<textarea id="communication-request" name="request" rows="3">` +
		htmlEsc(v["request"]) + `</textarea>` +
		`<button type="submit" id="communication-submit" name="plugin_action" value="call">调用</button>` +
		`</form>` +
		`<table id="communication-result">` +
		`<tr><th>target plugin</th><td id="communication-target-out">` + htmlEsc(v["target"]) + `</td></tr>` +
		`<tr><th>method</th><td id="communication-method-out">` + htmlEsc(v["method"]) + `</td></tr>` +
		`<tr><th>request</th><td><pre id="communication-request-out">` + htmlEsc(v["request"]) + `</pre></td></tr>` +
		`<tr><th>response</th><td><pre id="communication-response">` + htmlEsc(v["response"]) + `</pre></td></tr>` +
		`<tr><th>request_id</th><td id="communication-request-id">` + htmlEsc(v["request_id"]) +
		` <small id="communication-request-id-source">` + htmlEsc(v["request_id_source"]) +
		`</small></td></tr>` +
		`<tr><th>trace_id</th><td id="communication-trace-id">` + htmlEsc(v["trace_id"]) + `</td>` +
		`<td><small id="communication-trace-id-source">` + htmlEsc(v["trace_id_source"]) +
		`</small></td></tr>` +
		`<tr><th>route</th><td id="communication-route-out">` + htmlEsc(v["route"]) +
		` <small id="communication-route-source">` + htmlEsc(v["route_source"]) +
		`</small></td></tr>` +
		`<tr><th>目标运行时（观察值）</th><td id="communication-target-runtime">` + htmlEsc(runtime) + `</td></tr>` +
		`<tr><th>结果</th><td id="communication-response-ok">` + htmlEsc(v["response_ok"]) + `</td></tr>` +
		`<tr><th>错误</th><td id="communication-error">` + htmlEsc(v["error"]) + `</td></tr>` +
		`</table>` +
		`<p id="communication-message">` + htmlEsc(v["message"]) + `</p>` +
		`</section>` +
		`<nav id="plugin-nav"><a id="nav-index" href="` + base + `/index">Index</a>` +
		`<a id="nav-communication" href="` + base + `/communication">Communication</a></nav>`
}

// ---------------- §五/§六 命令 ----------------

// onMessage：message 事件 -> 只认发给自己的命令 -> 结果用动作回给引擎。
func (m *minimal) onMessage(ctx *flowerie.Context, event map[string]any) any {
	command := m.addressedToMe(textOf(event["text"]))
	if command == "" {
		return nil // 不是发给自己的命令：不回任何动作（事件是广播给所有插件的）
	}

	message := ""
	if result, err := m.runCommand(command); err != nil {
		message = jsonString(map[string]any{
			"ok":      false,
			"code":    errorCode(err),
			"message": err.Error(),
		})
	} else {
		message = jsonString(result)
	}

	return flowerie.Action{
		"type": "send_message",
		"payload": map[string]any{
			"group_id": event["group_id"],
			"message":  message,
		},
	}
}

// addressedToMe 判断命令是否发给本插件：/sdk@<自己的 plugin_id> <命令>。
// 返回 "" 表示不是发给自己的（调用方不回动作）；兼容老形式 "/sdk <命令>"。
func (m *minimal) addressedToMe(text string) string {
	if strings.HasPrefix(text, commandPrefix+"@") {
		head, rest, found := strings.Cut(text[len(commandPrefix)+1:], " ")
		if head != m.pluginID() {
			return "" // 别人的命令：不回动作
		}
		if !found {
			rest = ""
		}
		return commandPrefix + " " + rest
	}
	if strings.HasPrefix(text, commandPrefix+" ") {
		return text // 兼容老形式（验收测试只用寻址形式）
	}
	return ""
}

// runCommand 执行一条命令（text 已归一成 "/sdk <命令> ..." 形式）。
// 失败返回 error：*flowerie.CommError（SDK/引擎的结构化错误）或 *commandError（参数问题）。
func (m *minimal) runCommand(text string) (any, error) {
	if !strings.HasPrefix(text, commandPrefix+" ") {
		return nil, commandErrorf("空命令")
	}
	after := text[len(commandPrefix)+1:]
	head, rest, _ := strings.Cut(after, " ")
	argv := []string{}
	if rest != "" {
		argv = strings.Split(rest, " ") // 与 Python 最小插件的 rest.split(" ") 逐字对齐
	}

	switch head {
	case "ping":
		target, err := needArg(argv, 0, "target")
		if err != nil {
			return nil, err
		}
		return m.plugin.Call(target, "ping", map[string]any{})

	case "info":
		return m.getInfo(nil), nil

	case "echo":
		var params any = map[string]any{}
		if rest != "" {
			if err := json.Unmarshal([]byte(rest), &params); err != nil {
				return nil, commandErrorf("echo 的参数不是合法 JSON: %v", err)
			}
		}
		return m.echo(map[string]any{"params": params}), nil

	case "seen":
		target, err := needArg(argv, 0, "target")
		if err != nil {
			return nil, err
		}
		return m.plugin.Call(target, "seen", map[string]any{})

	case "call":
		target, err := needArg(argv, 0, "target")
		if err != nil {
			return nil, err
		}
		method, err := needArg(argv, 1, "method")
		if err != nil {
			return nil, err
		}
		params := map[string]any{}
		if len(argv) > 2 && argv[2] != "" {
			if err := json.Unmarshal([]byte(argv[2]), &params); err != nil {
				return nil, commandErrorf("call 的参数不是合法 JSON 对象: %v", err)
			}
		}
		return m.plugin.Call(target, method, params)

	case "route":
		route, err := needArg(argv, 0, "route")
		if err != nil {
			return nil, err
		}
		target, err := needArg(argv, 1, "target")
		if err != nil {
			return nil, err
		}
		method, err := needArg(argv, 2, "method")
		if err != nil {
			return nil, err
		}
		return m.plugin.Call(target, method, map[string]any{}, flowerie.WithRoute(route))

	case "chain":
		t1, err := needArg(argv, 0, "t1")
		if err != nil {
			return nil, err
		}
		t2, err := needArg(argv, 1, "t2")
		if err != nil {
			return nil, err
		}
		t3, err := needArg(argv, 2, "t3")
		if err != nil {
			return nil, err
		}
		first, err := m.plugin.Call(t1, "ping", map[string]any{})
		if err != nil {
			return nil, err
		}
		second, err := m.plugin.Call(t2, "echo", map[string]any{"hello": "world"})
		if err != nil {
			return nil, err
		}
		third, err := m.plugin.Call(t3, "ping", map[string]any{})
		if err != nil {
			return nil, err
		}
		return map[string]any{"t1": first, "t2": second, "t3": third}, nil

	case "errors":
		granted, err := needArg(argv, 0, "granted")
		if err != nil {
			return nil, err
		}
		denied, err := needArg(argv, 1, "denied")
		if err != nil {
			return nil, err
		}
		return m.errorProbes(granted, denied), nil
	}

	return nil, commandErrorf("未知命令: %s", head)
}

// errorProbes 依次触发六种错误，每种都返回 **Go 原生**错误模型的观察结果（§九）。
// 顺序与 Python 最小插件一致：METHOD_NOT_FOUND / PLUGIN_NOT_FOUND / PERMISSION_DENIED /
// INVALID_ARGUMENT / TIMEOUT / PLUGIN_ERROR。
func (m *minimal) errorProbes(granted, denied string) map[string]any {
	probes := []struct {
		code string
		run  func() error
	}{
		{"METHOD_NOT_FOUND", func() error {
			_, err := m.plugin.Call(granted, "no_such_method", map[string]any{})
			return err
		}},
		{"PLUGIN_NOT_FOUND", func() error {
			_, err := m.plugin.Call("no_such_plugin", "ping", map[string]any{})
			return err
		}},
		{"PERMISSION_DENIED", func() error {
			_, err := m.plugin.Call(denied, "ping", map[string]any{})
			return err
		}},
		{"INVALID_ARGUMENT", func() error {
			_, err := m.plugin.Call("", "ping", map[string]any{})
			return err
		}},
		{"TIMEOUT", func() error {
			_, err := m.plugin.Call(granted, "slow", map[string]any{},
				flowerie.WithTimeout(probeTimeoutMs))
			return err
		}},
		{"PLUGIN_ERROR", func() error {
			_, err := m.plugin.Call(granted, "boom", map[string]any{})
			return err
		}},
	}

	out := map[string]any{}
	for _, probe := range probes {
		if err := probe.run(); err != nil {
			out[probe.code] = nativeError(err)
			continue
		}
		out[probe.code] = map[string]any{
			"native": nil, "code": "NO_ERROR", "message": "预期失败但调用成功了",
		}
	}
	return out
}

// nativeError 是 Go 原生错误模型的观察结果：类型名 + 结构化错误码 + 消息。
func nativeError(err error) map[string]any {
	if err == nil {
		return map[string]any{"native": nil, "code": "", "message": ""}
	}
	return map[string]any{
		"native":  fmt.Sprintf("%T", err), // *flowerie.CommError
		"code":    flowerie.CommCode(err), // 12 个结构化错误码之一
		"message": err.Error(),            // "CODE: message"
	}
}

// ---------------- 小工具 ----------------

// commandError 是命令层的参数/用法错误（对应 Python 侧的 ValueError / IndexError）。
type commandError struct{ message string }

func (e *commandError) Error() string { return e.message }

func commandErrorf(format string, args ...any) error {
	return &commandError{message: fmt.Sprintf(format, args...)}
}

// errorCode 取错误的结构化错误码：SDK 的 *flowerie.CommError 原样保留，其余归 PLUGIN_ERROR。
func errorCode(err error) string {
	var commErr *flowerie.CommError
	if errors.As(err, &commErr) && commErr != nil && commErr.Code != "" {
		return commErr.Code
	}
	return flowerie.CodePluginError
}

// needArg 取第 index 个参数（对应 Python 的 argv[index]，越界即失败）。
func needArg(argv []string, index int, name string) (string, error) {
	if index >= len(argv) || strings.TrimSpace(argv[index]) == "" {
		return "", commandErrorf("缺少参数: %s", name)
	}
	return argv[index], nil
}

// textOf 把事件字段当字符串用（字符串以外的值不 panic）。
func textOf(value any) string {
	if value == nil {
		return ""
	}
	if text, ok := value.(string); ok {
		return text
	}
	return fmt.Sprintf("%v", value)
}

// flattenPayload 取 test.event 的 payload：SDK 把 payload 平铺进事件对象，
// 这里剥掉 SDK 注入的 "event" / "plugin_id" 两个键（与 Python 最小插件同一规则）。
func flattenPayload(event map[string]any) map[string]any {
	if inner, ok := event["payload"].(map[string]any); ok {
		return inner
	}
	out := make(map[string]any, len(event))
	for key, value := range event {
		if key == "event" || key == "plugin_id" {
			continue
		}
		out[key] = value
	}
	return out
}

// jsonString 把结果序列化成回给引擎的 message 字符串：
// **键有序**（Go 的 map 序列化按 key 排序，等同 Python 的 sort_keys=True）、
// 不转义 HTML（SetEscapeHTML(false)，对齐 Python 的 ensure_ascii=False）。
func jsonString(value any) string {
	var buffer bytes.Buffer
	encoder := json.NewEncoder(&buffer)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(value); err != nil {
		fallback, _ := json.Marshal(map[string]any{
			"ok":      false,
			"code":    flowerie.CodeSerializationError,
			"message": err.Error(),
		})
		return string(fallback)
	}
	return strings.TrimSuffix(buffer.String(), "\n")
}
