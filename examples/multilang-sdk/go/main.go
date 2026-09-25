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
	"os"
	"strings"
	"sync"
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
