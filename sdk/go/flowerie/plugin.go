// Package flowerie 是 Flowerie Plugin Protocol v1 的 Go SDK（零第三方依赖，只用标准库）。
//
// 协议规范：docs/plugin-protocol.md。与 Python / TypeScript 示例的行为一致性由
// tests/test_plugin_sdk_contract.py 用**真进程 + 真管道**比对（同一批向量）。
//
// 用法：
//
//	plugin := flowerie.New()
//	plugin.OnMessage(func(ctx *flowerie.Context, ev map[string]any) any {
//	    return flowerie.Action{"type": "send_group_msg", "params": map[string]any{"group_id": 1, "message": "pong"}}
//	})
//	if err := plugin.Run(); err != nil { panic(err) }
package flowerie

import (
	"bufio"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strings"
	"sync"
)

// ProtocolVersion 是插件协议版本。
const ProtocolVersion = "1"

const (
	apiVersion      = "1"
	actionIDBase    = 1000000
	maxStorageKeys  = 200
	maxStorageValue = 64 * 1024
	maxConfigKeys   = 64
	maxConfigValue  = 8 * 1024
)

// ---------------- Plugin-to-Plugin 通信常量（任务书《通信》§五–§二十七） ----------------
//
// 入站三条方法（CALL / EVENT / CANCEL）是**引擎 → 插件**的请求；出站三条 op
// （plugin.call / plugin.emit / plugin.cancel）是**插件 → 引擎**的反向通道，沿用本 SDK
// 既有的 engine op 通道 —— 没有第二条通信路径，也没有任何绕过 Core 的私有 socket/HTTP。
const (
	// MethodPluginCall 入站：其它插件对我方发起的一次调用（§五/§六）。
	MethodPluginCall = "plugin.call"
	// MethodPluginEvent 入站：其它插件广播的事件（§九）。
	MethodPluginEvent = "plugin.event"
	// MethodPluginCancel 入站/出站：取消一次在途调用（§十八）。
	MethodPluginCancel = "plugin.cancel"
	// OpPluginEmit 出站：向其它插件广播事件（§九）。
	OpPluginEmit = "plugin.emit"
)

// 路由策略（§十三）：默认 auto；测试用 core 验证统一协议路径（跨语言一律经 Core，§十二）。
const (
	RouteAuto          = "auto"
	RouteCore          = "core"
	RouteLocal         = "local"
	DefaultCallTimeout = 5000
)

// 结构化错误码（§二十一 十个 ＋ §十七 生命周期 ＋ §二十二 循环保护）：共 12 个。
const (
	CodePluginNotFound     = "PLUGIN_NOT_FOUND"
	CodePluginNotReady     = "PLUGIN_NOT_READY"
	CodeMethodNotFound     = "METHOD_NOT_FOUND"
	CodePermissionDenied   = "PERMISSION_DENIED"
	CodeInvalidArgument    = "INVALID_ARGUMENT"
	CodeTimeout            = "TIMEOUT"
	CodeCancelled          = "CANCELLED"
	CodeSerializationError = "SERIALIZATION_ERROR"
	CodePluginError        = "PLUGIN_ERROR"
	CodeInternalError      = "INTERNAL_ERROR"
	CodePluginUnavailable  = "PLUGIN_UNAVAILABLE"
	CodePluginCallLoop     = "PLUGIN_CALL_LOOP"
)

// ErrorCodes 是全部 12 个结构化错误码（顺序与 src/plugins/comm.py 的 ERROR_CODES 一致）。
var ErrorCodes = []string{
	CodePluginNotFound, CodePluginNotReady, CodeMethodNotFound, CodePermissionDenied,
	CodeInvalidArgument, CodeTimeout, CodeCancelled, CodeSerializationError,
	CodePluginError, CodeInternalError, CodePluginUnavailable, CodePluginCallLoop,
}

// 与 Python runner 一致的边界值：序列化深度 / 嵌套处理深度 / 取消记录条数。
const (
	maxSerializationDepth = 32
	maxNestedDepth        = 16
	maxCancelledIDs       = 256
)

// Action 是插件返回给引擎的动作（唯一副作用出口）。
type Action map[string]any

type reply struct {
	ID     int             `json:"id"`
	Result json.RawMessage `json:"result,omitempty"`
	Error  string          `json:"error,omitempty"`
}

type request struct {
	ID     int             `json:"id"`
	Method string          `json:"method"`
	Params json.RawMessage `json:"params,omitempty"`
}

// message 是**入站**消息：既可能是引擎请求（method），也可能是我方请求的应答（result/error）。
// 字段名与 JSON 键大小写不敏感匹配，因此不需要 struct tag（少一层转义坑）。
type message struct {
	ID     int
	Method string
	Params json.RawMessage
	Result json.RawMessage
	Error  string
}

// Plugin 是插件主体：注册钩子后 Run() 进入协议主循环。
type Plugin struct {
	capabilities []string

	mu      sync.Mutex
	pending map[int]chan reply
	nextID  int
	out     *bufio.Writer

	// 入站请求队列（读循环 → 主循环）；等待应答期间的推迟队列见 deferred。
	requests chan message

	// 插件间通信的注册表与嵌套状态（commMu 与 mu 分开持有，两条路径不会互相等待）。
	commMu    sync.Mutex
	exposed   map[string]Handler
	subs      map[string][]Handler
	cancelled map[string]struct{}
	inbound   []inboundContext
	pumpDepth int
	deferred  []message

	ctx *Context

	startupHooks  []func(*Context)
	shutdownHooks []func(*Context)
	healthHooks   []func(*Context) bool
	messageHooks  []func(*Context, map[string]any) any
	eventHooks    map[string][]func(*Context, map[string]any) any
	namedHooks    map[string]func(args ...any) any
	webuiHooks    map[string]func(args map[string]any) any
	statusHook    func(*Context) any
}

// Context 是传给插件的上下文：storage / config / permission / action。
type Context struct {
	PluginID  string
	PluginDir string
	DataDir   string
	plugin    *Plugin
}

// New 创建一个插件（默认声明全部可选能力；引擎不会调用未声明的能力）。
func New() *Plugin {
	p := &Plugin{
		capabilities: []string{
			"config.get", "config.set", "context.get", "permission.check",
			"plugin.call", "plugin.cancel", "plugin.event",
			"storage.delete", "storage.get", "storage.list", "storage.set",
			"webui.action", "webui.asset", "webui.page",
		},
		pending:    map[int]chan reply{},
		eventHooks: map[string][]func(*Context, map[string]any) any{},
		namedHooks: map[string]func(args ...any) any{},
		webuiHooks: map[string]func(args map[string]any) any{},
		out:        bufio.NewWriter(os.Stdout),

		requests:  make(chan message, 16),
		exposed:   map[string]Handler{},
		subs:      map[string][]Handler{},
		cancelled: map[string]struct{}{},
	}
	p.ctx = &Context{PluginID: "unknown", PluginDir: mustGetwd(), DataDir: filepath.Join(mustGetwd(), "data"), plugin: p}
	return p
}

func mustGetwd() string {
	dir, err := os.Getwd()
	if err != nil {
		return "."
	}
	return dir
}

// ---------------- 钩子注册 ----------------

// OnStartup 注册启动钩子（initialize 时调用）。
func (p *Plugin) OnStartup(fn func(*Context)) *Plugin { p.startupHooks = append(p.startupHooks, fn); return p }

// OnShutdown 注册退出钩子。
func (p *Plugin) OnShutdown(fn func(*Context)) *Plugin {
	p.shutdownHooks = append(p.shutdownHooks, fn)
	return p
}

// OnHealth 注册心跳钩子（Python 侧对应 health_check）：返回 false 即视为不健康。
func (p *Plugin) OnHealth(fn func(*Context) bool) *Plugin {
	p.healthHooks = append(p.healthHooks, fn)
	return p
}

// 与 Python SDK 的具名钩子对齐（协议层就是 event 名字，On() 是通用入口）
func (p *Plugin) OnCommand(fn func(*Context, map[string]any) any) *Plugin {
	return p.On("command", fn)
}

// OnNotice 注册通知事件钩子。
func (p *Plugin) OnNotice(fn func(*Context, map[string]any) any) *Plugin {
	return p.On("notice", fn)
}

// OnRequest 注册请求事件钩子。
func (p *Plugin) OnRequest(fn func(*Context, map[string]any) any) *Plugin {
	return p.On("request", fn)
}

// OnLifecycle 注册生命周期事件钩子。
func (p *Plugin) OnLifecycle(fn func(*Context, map[string]any) any) *Plugin {
	return p.On("lifecycle", fn)
}

// OnSchedule 注册定时事件钩子。
func (p *Plugin) OnSchedule(fn func(*Context, map[string]any) any) *Plugin {
	return p.On("schedule", fn)
}

// OnMessage 注册消息钩子（可返回 Action / []Action / nil）。
func (p *Plugin) OnMessage(fn func(*Context, map[string]any) any) *Plugin {
	p.messageHooks = append(p.messageHooks, fn)
	return p
}

// On 注册钩子：按 handler 的动态类型分派到两条互不相同的通道 ——
//
//	plugin.On("command", func(ctx *flowerie.Context, ev map[string]any) any { ... })
//	    引擎事件钩子（既有行为；OnCommand / OnNotice / OnRequest / OnLifecycle / OnSchedule 走的也是这里）
//	plugin.On("weather.updated", func(request map[string]any) any { ... })
//	    插件间事件订阅（《通信》§九，等价于 OnPluginEvent）
//
// 为什么合成一个方法：本 SDK 的引擎事件钩子早就占用了 On 这个名字，而《通信》§二十七
// 要求的插件事件订阅也叫 On；两者签名不同，用动态分派同时保住「既有插件代码一行不改」
// 与「协议 API 名字与其它四种语言一致」。不认识的 handler 类型写 stderr（不静默吞掉）。
func (p *Plugin) On(event string, handler any) *Plugin {
	switch typed := handler.(type) {
	case Handler:
		return p.OnPluginEvent(event, typed)
	case func(map[string]any) any:
		return p.OnPluginEvent(event, Handler(typed))
	case func(*Context, map[string]any) any:
		p.eventHooks[event] = append(p.eventHooks[event], typed)
		return p
	default:
		fmt.Fprintf(os.Stderr, "[flowerie] On(%q): 不支持的 handler 类型 %T\n", event, handler)
		return p
	}
}

// RegisterHook 注册控制面可调用的 hook（插件 WebUI 的数据钩子走同一通道）。
func (p *Plugin) RegisterHook(name string, fn func(args ...any) any) *Plugin {
	p.namedHooks[name] = fn
	return p
}


// WebUI 是 Plugin WebUI Protocol 的注册入口（任务书第 3 份 §六）：
//
//	plugin.WebUI().Page(func(args map[string]any) any { return "<h1>hi</h1>" })
//
// 处理器拿到引擎给的受控参数（page/context，action 时还有 action/form），
// 返回 string（= html 简写）或 map[string]any（html/vars/message/... 白名单字段）。
// 路由、权限、校验、净化、隔离全部由引擎负责，插件只负责内容。
type WebUI struct {
	p *Plugin
}

// WebUI 返回 WebUI 注册器。
func (p *Plugin) WebUI() *WebUI { return &WebUI{p: p} }

// Page 注册页面处理器（webui.page）。
func (w *WebUI) Page(fn func(args map[string]any) any) *WebUI {
	w.p.webuiHooks["webui.page"] = fn
	return w
}

// Action 注册动作处理器（webui.action）。
func (w *WebUI) Action(fn func(args map[string]any) any) *WebUI {
	w.p.webuiHooks["webui.action"] = fn
	return w
}

// Asset 注册资源处理器（webui.asset）。
func (w *WebUI) Asset(fn func(args map[string]any) any) *WebUI {
	w.p.webuiHooks["webui.asset"] = fn
	return w
}

// Context 暴露上下文（测试与嵌入场景）。
func (p *Plugin) Context() *Context { return p.ctx }

// ---------------- 协议主体 ----------------

// Run 进入协议主循环（读到 stdin 关闭或 shutdown 后返回）。
//
// 读与处理分离：读循环跑在独立 goroutine 里，**应答**（没有 method 的行）由读循环立即投递，
// 请求则排队交给当前 goroutine 顺序处理。这样处理函数内部发起的反向请求
// （reverse：engine op / action）在等待应答期间才能被及时唤醒——读写挤在同一个循环里
// 会自己把自己锁死（实测 CI：permission.check 一发起就 "fatal error: all goroutines are asleep - deadlock!"）。
func (p *Plugin) Run() error {
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)
	readDone := make(chan error, 1)
	go func() {
		defer close(p.requests)
		for scanner.Scan() {
			line := strings.TrimSpace(scanner.Text())
			if line == "" {
				continue
			}
			var msg message
			if err := json.Unmarshal([]byte(line), &msg); err != nil {
				continue // 非法行跳过，不断连（协议容错）
			}
			if msg.Method == "" {
				p.deliver(msg) // 引擎对我方请求的应答
				continue
			}
			p.requests <- msg
		}
		readDone <- scanner.Err()
	}()
	for {
		msg, ok := p.nextRequest()
		if !ok {
			break
		}
		if p.handle(msg) {
			return nil // shutdown：主循环结束，读循环随进程退出
		}
	}
	return <-readDone
}

// nextRequest 取下一条要处理的引擎请求：先清「等待应答期间被推迟」的消息，再阻塞读入站队列
// （推迟的消息保持相对顺序，先于后到的消息处理，主循环看到的顺序不会乱）。
func (p *Plugin) nextRequest() (message, bool) {
	p.commMu.Lock()
	if len(p.deferred) > 0 {
		msg := p.deferred[0]
		p.deferred = p.deferred[1:]
		p.commMu.Unlock()
		return msg, true
	}
	p.commMu.Unlock()
	msg, ok := <-p.requests
	return msg, ok
}

// awaitReply 等待我方请求的应答（§八 嵌套不丢消息）：期间引擎投递进来的
// plugin.call / plugin.event / plugin.cancel **原地**处理 —— 若在这里把消息丢掉，
// A 调用 B、B 又回调 A 时 A 永远收不到回调，§二十二 的环保护也就没有真实链路可观察。
func (p *Plugin) awaitReply(ch chan reply) (reply, bool) {
	for {
		select {
		case msg, ok := <-ch:
			if !ok {
				return reply{}, false
			}
			return msg, true
		case msg, ok := <-p.requests:
			if !ok {
				return reply{}, false
			}
			p.pumpNested(msg)
		}
	}
}

// pumpNested 处理「等待应答期间」到达的引擎请求：插件间通信三条入站方法就地处理，
// 其它请求（initialize / event / health / hook / storage / ...）推迟给主循环。
func (p *Plugin) pumpNested(msg message) {
	switch msg.Method {
	case MethodPluginCall, MethodPluginEvent, MethodPluginCancel:
		p.commMu.Lock()
		p.pumpDepth++
		depth := p.pumpDepth
		p.commMu.Unlock()
		defer func() {
			p.commMu.Lock()
			p.pumpDepth--
			p.commMu.Unlock()
		}()
		if depth > maxNestedDepth {
			// 不静默丢弃：回一条结构化应答（真正的环保护在引擎侧按 hop_count 判定，§二十二）
			p.replyCommResult(msg.ID, commErrorResponse(newCommError(
				CodeInternalError, "嵌套处理深度超过上限（>16）", map[string]any{"depth": depth})))
			return
		}
		p.handle(msg)
	default:
		p.commMu.Lock()
		p.deferred = append(p.deferred, msg)
		p.commMu.Unlock()
	}
}

func (p *Plugin) deliver(msg message) {
	p.mu.Lock()
	ch, ok := p.pending[msg.ID]
	if ok {
		delete(p.pending, msg.ID)
	}
	p.mu.Unlock()
	if ok {
		ch <- reply{ID: msg.ID, Result: msg.Result, Error: msg.Error}
	}
}

func (p *Plugin) write(obj any) error {
	data, err := json.Marshal(obj)
	if err != nil {
		return err
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if _, err := p.out.Write(append(data, '\n')); err != nil {
		return err
	}
	return p.out.Flush()
}

func (p *Plugin) replyResult(id int, result any) {
	raw, _ := json.Marshal(result)
	_ = p.write(reply{ID: id, Result: raw})
}

func (p *Plugin) replyError(id int, message string) {
	if len(message) > 800 {
		message = message[:800]
	}
	_ = p.write(reply{ID: id, Error: message})
}

func (p *Plugin) handle(msg message) bool {
	params := map[string]any{}
	if len(msg.Params) > 0 {
		_ = json.Unmarshal(msg.Params, &params)
	}
	switch msg.Method {
	case "initialize":
		ctxIn, _ := params["context"].(map[string]any)
		if dir, ok := ctxIn["plugin_dir"].(string); ok && dir != "" {
			p.ctx.PluginDir = dir
		}
		if dir, ok := ctxIn["data_dir"].(string); ok && dir != "" {
			p.ctx.DataDir = dir
		}
		if id, ok := ctxIn["plugin_id"].(string); ok && id != "" {
			p.ctx.PluginID = id
		}
		for _, fn := range p.startupHooks {
			fn(p.ctx)
		}
		p.replyResult(msg.ID, map[string]any{
			"ok": true, "api_version": apiVersion, "protocol_version": ProtocolVersion,
			"capabilities": p.capabilities,
		})
	case "event":
		event, _ := params["event"].(string)
		payload, _ := params["payload"].(map[string]any)
		p.replyResult(msg.ID, map[string]any{"actions": p.dispatch(event, payload)})
	case "health":
		healthy := true
		for _, fn := range p.healthHooks {
			if !fn(p.ctx) {
				healthy = false
			}
		}
		if healthy {
			p.replyResult(msg.ID, map[string]any{"ok": true})
		} else {
			p.replyResult(msg.ID, map[string]any{"ok": false, "error": "health check failed"})
		}
	case "shutdown":
		for _, fn := range p.shutdownHooks {
			fn(p.ctx)
		}
		p.replyResult(msg.ID, map[string]any{"ok": true})
		return true
	case "hook":
		name, _ := params["name"].(string)
		if !validHookName(name) {
			p.replyError(msg.ID, "hook 名非法")
			return false
		}
		fn, ok := p.namedHooks[name]
		if !ok {
			p.replyResult(msg.ID, map[string]any{"ok": true, "result": nil})
			return false
		}
		args, _ := params["args"].([]any)
		func() {
			defer func() {
				if r := recover(); r != nil {
					p.replyResult(msg.ID, map[string]any{"ok": false, "error": fmt.Sprintf("%v", r)})
				}
			}()
			p.replyResult(msg.ID, map[string]any{"ok": true, "result": fn(args...)})
		}()
	case "webui.page", "webui.action", "webui.asset":
		fn, ok := p.webuiHooks[msg.Method]
		if !ok {
			p.replyResult(msg.ID, map[string]any{"ok": false,
				"error": "插件未注册 " + msg.Method + " 处理器"})
			return false
		}
		func() {
			defer func() {
				if r := recover(); r != nil {
					p.replyResult(msg.ID, map[string]any{"ok": false, "error": fmt.Sprintf("%v", r)})
				}
			}()
			p.replyResult(msg.ID, normalizeWebuiResult(fn(params)))
		}()
	case "storage.get":
		key, _ := params["key"].(string)
		value, found := p.ctx.StorageGet(key)
		if !validKey(key) {
			p.replyResult(msg.ID, map[string]any{"ok": false, "error": "存储键非法（字母数字开头 ≤64，允许 . _ -）"})
			return false
		}
		if !found {
			value = nil
		}
		p.replyResult(msg.ID, map[string]any{"ok": true, "value": value})
	case "storage.set":
		key, _ := params["key"].(string)
		if err := p.ctx.StorageSet(key, params["value"]); err != nil {
			p.replyResult(msg.ID, map[string]any{"ok": false, "error": err.Error()})
			return false
		}
		data, _ := json.Marshal(params["value"])
		p.replyResult(msg.ID, map[string]any{"ok": true, "size": len(data)})
	case "storage.delete":
		key, _ := params["key"].(string)
		if !validKey(key) {
			p.replyResult(msg.ID, map[string]any{"ok": false, "error": "存储键非法（字母数字开头 ≤64，允许 . _ -）"})
			return false
		}
		p.replyResult(msg.ID, map[string]any{"ok": true, "deleted": p.ctx.StorageDelete(key)})
	case "storage.list":
		prefix, _ := params["prefix"].(string)
		p.replyResult(msg.ID, map[string]any{"ok": true, "keys": p.ctx.StorageList(prefix)})
	case "config.get":
		var keys []string
		if raw, ok := params["keys"].([]any); ok {
			for _, k := range raw {
				keys = append(keys, fmt.Sprintf("%v", k))
			}
		}
		values, err := p.ctx.ConfigGet(keys)
		if err != nil {
			p.replyResult(msg.ID, map[string]any{"ok": false, "error": err.Error()})
			return false
		}
		p.replyResult(msg.ID, map[string]any{"ok": true, "values": values})
	case "config.set":
		values, ok := params["values"].(map[string]any)
		if !ok {
			p.replyResult(msg.ID, map[string]any{"ok": false, "error": "config.set 需要 values 对象"})
			return false
		}
		saved, err := p.ctx.ConfigSet(values)
		if err != nil {
			p.replyResult(msg.ID, map[string]any{"ok": false, "error": err.Error()})
			return false
		}
		p.replyResult(msg.ID, map[string]any{"ok": true, "saved": saved})
	case "permission.check":
		permission, _ := params["permission"].(string)
		res, err := p.ctx.engineOp("permission.check", map[string]any{"permission": permission})
		if err != nil {
			p.replyResult(msg.ID, map[string]any{"ok": false, "error": err.Error()})
			return false
		}
		p.replyResult(msg.ID, res)
	case "context.get":
		res, err := p.ctx.engineOp("context.get", map[string]any{})
		if err != nil {
			p.replyResult(msg.ID, map[string]any{"ok": false, "error": err.Error()})
			return false
		}
		p.replyResult(msg.ID, res)
	case MethodPluginCall:
		p.handleInboundCall(msg.ID, params)
	case MethodPluginEvent:
		p.handleInboundEvent(msg.ID, params)
	case MethodPluginCancel:
		p.handleInboundCancel(msg.ID, params)
	default:
		p.replyError(msg.ID, fmt.Sprintf("未知方法: %q", msg.Method))
	}
	return false
}

func validHookName(name string) bool {
	if len(name) == 0 || len(name) > 64 {
		return false
	}
	for i, r := range name {
		ok := (r >= 'a' && r <= 'z') || r == '_' || (i > 0 && r >= '0' && r <= '9')
		if !ok {
			return false
		}
	}
	return true
}

// normalizeWebuiResult 把 WebUI 处理器返回值归一成协议应答（字符串 = html 简写）。
func normalizeWebuiResult(res any) map[string]any {
	switch typed := res.(type) {
	case string:
		return map[string]any{"ok": true, "html": typed}
	case map[string]any:
		if ok, exists := typed["ok"].(bool); exists && !ok {
			message, _ := typed["error"].(string)
			if message == "" {
				message = "插件返回 ok=false"
			}
			return map[string]any{"ok": false, "error": message}
		}
		out := map[string]any{"ok": true}
		for _, key := range []string{"html", "vars", "context", "message", "content_type",
			"body", "base64", "config_set", "storage_set"} {
			if value, ok := typed[key]; ok {
				out[key] = value
			}
		}
		return out
	case nil:
		return map[string]any{"ok": false, "error": "WebUI 处理器没有返回内容"}
	default:
		return map[string]any{"ok": false, "error": "WebUI 处理器返回了非法类型"}
	}
}

func (p *Plugin) dispatch(event string, payload map[string]any) []Action {
	actions := []Action{}
	eventObj := map[string]any{"event": event, "plugin_id": p.ctx.PluginID}
	for k, v := range payload {
		eventObj[k] = v
	}
	hooks := p.messageHooks
	if event != "message" {
		hooks = p.eventHooks[event]
	}
	for _, fn := range hooks {
		result := fn(p.ctx, eventObj)
		switch typed := result.(type) {
		case nil:
		case Action:
			actions = append(actions, typed)
		case map[string]any:
			actions = append(actions, Action(typed))
		case []Action:
			actions = append(actions, typed...)
		case []any:
			for _, item := range typed {
				if m, ok := item.(map[string]any); ok {
					actions = append(actions, Action(m))
				}
			}
		}
	}
	return actions
}

// ---------------- 反向通道：插件 → 引擎 ----------------

func (c *Context) reverse(method string, params map[string]any) (map[string]any, error) {
	p := c.plugin
	p.mu.Lock()
	p.nextID++
	id := actionIDBase + p.nextID
	ch := make(chan reply, 1)
	p.pending[id] = ch
	p.mu.Unlock()

	raw, _ := json.Marshal(params)
	if err := p.write(request{ID: id, Method: method, Params: raw}); err != nil {
		p.forget(id)
		return nil, err
	}
	msg, ok := p.awaitReply(ch)
	if !ok {
		p.forget(id)
		return nil, fmt.Errorf("connection closed")
	}
	if msg.Error != "" {
		return nil, fmt.Errorf("%s", msg.Error)
	}
	out := map[string]any{}
	if len(msg.Result) > 0 {
		_ = json.Unmarshal(msg.Result, &out)
	}
	return out, nil
}

// forget 清掉一个作废的待应答槽位（写失败/连接断开时不留悬挂 channel）。
func (p *Plugin) forget(id int) {
	p.mu.Lock()
	delete(p.pending, id)
	p.mu.Unlock()
}

func (c *Context) engineOp(op string, args map[string]any) (map[string]any, error) {
	return c.reverse("engine", map[string]any{"op": op, "args": args})
}

// Action 发起动作（副作用出口）。
func (c *Context) Action(actionType string, params map[string]any) (map[string]any, error) {
	return c.reverse("action", map[string]any{"action": actionType, "payload": params})
}

// PermissionCheck 查询已批准权限（只读；无法提权）。
func (c *Context) PermissionCheck(permission string) (bool, error) {
	res, err := c.engineOp("permission.check", map[string]any{"permission": permission})
	if err != nil {
		return false, err
	}
	granted, _ := res["granted"].(bool)
	return granted, nil
}

// Info 拉取引擎侧上下文。
func (c *Context) Info() (map[string]any, error) {
	res, err := c.engineOp("context.get", map[string]any{})
	if err != nil {
		return nil, err
	}
	if inner, ok := res["result"].(map[string]any); ok {
		return inner, nil
	}
	return res, nil
}

// Logf 写 stderr（stdout 只能放协议 JSON）。
func (c *Context) Logf(format string, args ...any) {
	fmt.Fprintf(os.Stderr, "[flowerie] "+format+"\n", args...)
}

// ---------------- storage（只落本插件自己的 data 目录） ----------------

func validKey(key string) bool {
	if len(key) == 0 || len(key) > 64 {
		return false
	}
	for i, r := range key {
		alnum := (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9')
		if i == 0 && !alnum {
			return false
		}
		if !alnum && r != '.' && r != '_' && r != '-' {
			return false
		}
	}
	return true
}

func (c *Context) storageDir() (string, error) {
	dir := filepath.Join(c.DataDir, "storage")
	return dir, os.MkdirAll(dir, 0o755)
}

func (c *Context) storagePath(key string) (string, error) {
	if !validKey(key) {
		return "", fmt.Errorf("存储键非法（字母数字开头 ≤64，允许 . _ -）")
	}
	dir, err := c.storageDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, key+".json"), nil
}

// StorageGet 读取一个键；不存在返回 (nil, false)。
func (c *Context) StorageGet(key string) (any, bool) {
	path, err := c.storagePath(key)
	if err != nil {
		return nil, false
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, false
	}
	var value any
	if json.Unmarshal(data, &value) != nil {
		return nil, false
	}
	return value, true
}

// StorageSet 写入一个键（有大小与数量上限）。
func (c *Context) StorageSet(key string, value any) error {
	path, err := c.storagePath(key)
	if err != nil {
		return err
	}
	data, err := json.Marshal(value)
	if err != nil {
		return err
	}
	if len(data) > maxStorageValue {
		return fmt.Errorf("值超过上限")
	}
	dir, _ := c.storageDir()
	entries, _ := os.ReadDir(dir)
	count := 0
	for _, e := range entries {
		if strings.HasSuffix(e.Name(), ".json") {
			count++
		}
	}
	if _, statErr := os.Stat(path); statErr != nil && count >= maxStorageKeys {
		return fmt.Errorf("存储键数量超过上限")
	}
	return os.WriteFile(path, data, 0o644)
}

// StorageDelete 删除一个键；返回是否真的删掉了。
func (c *Context) StorageDelete(key string) bool {
	path, err := c.storagePath(key)
	if err != nil {
		return false
	}
	return os.Remove(path) == nil
}

// StorageList 列出键（可按前缀过滤）。
func (c *Context) StorageList(prefix string) []string {
	dir, err := c.storageDir()
	if err != nil {
		return []string{}
	}
	entries, _ := os.ReadDir(dir)
	keys := []string{}
	for _, e := range entries {
		name := e.Name()
		if !strings.HasSuffix(name, ".json") {
			continue
		}
		key := strings.TrimSuffix(name, ".json")
		if strings.HasPrefix(key, prefix) {
			keys = append(keys, key)
		}
	}
	sort.Strings(keys)
	return keys
}

// ---------------- config（操作员值只读 + 插件覆盖层） ----------------

func (c *Context) configPath() string { return filepath.Join(c.DataDir, "config.json") }

func (c *Context) configOverlay() map[string]any {
	out := map[string]any{}
	if data, err := os.ReadFile(c.configPath()); err == nil {
		_ = json.Unmarshal(data, &out)
	}
	return out
}

// ConfigGet 返回操作员配置 + 插件覆盖层（操作员的值优先）。
func (c *Context) ConfigGet(keys []string) (map[string]any, error) {
	res, err := c.engineOp("config.get", map[string]any{})
	if err != nil {
		return nil, err
	}
	merged := c.configOverlay()
	if values, ok := res["values"].(map[string]any); ok {
		for k, v := range values {
			merged[k] = v
		}
	}
	if len(keys) == 0 {
		return merged, nil
	}
	out := map[string]any{}
	for _, k := range keys {
		if v, ok := merged[k]; ok {
			out[k] = v
		}
	}
	return out, nil
}

// ConfigSet 写入插件自己的覆盖层（改不了操作员的全局配置）。
func (c *Context) ConfigSet(values map[string]any) ([]string, error) {
	overlay := c.configOverlay()
	saved := []string{}
	for k, v := range values {
		if !validKey(k) {
			return nil, fmt.Errorf("配置键非法: %s", k)
		}
		data, _ := json.Marshal(v)
		if len(data) > maxConfigValue {
			return nil, fmt.Errorf("配置值超过上限: %s", k)
		}
		overlay[k] = v
		saved = append(saved, k)
	}
	if len(overlay) > maxConfigKeys {
		return nil, fmt.Errorf("配置键数量超过上限")
	}
	data, err := json.Marshal(overlay)
	if err != nil {
		return nil, err
	}
	sort.Strings(saved)
	return saved, os.WriteFile(c.configPath(), data, 0o644)
}

// ================= Plugin-to-Plugin 通信（任务书《通信》§五–§二十七） =================
//
// 统一抽象（与 Python / TypeScript / Rust / Java 同名同义，§二十七）：
//
//	plugin.Expose("get_status", handler)                                   // 暴露方法：别的插件可以调用我（§五）
//	result, err := plugin.Call("other.go", "get_status", map[string]any{}) // 调用别的插件（§五–§七）
//	emit, err := plugin.Emit("weather.updated", payload)                   // 广播事件（§九）
//	plugin.On("weather.updated", handler)                                  // 订阅事件（"*" 匹配全部）
//	err := plugin.Cancel(requestID, "不再需要")                             // 取消在途调用（§十八）
//
// 失败一律是 *CommError（12 个结构化错误码之一，§二十一），不退化成一句字符串；
// 参数/返回值不是语言无关的 JSON 类型 -> SERIALIZATION_ERROR（§十九/§二十）。
// SDK **不自动重试**（§八）：重试由插件自己决定，避免插件之间形成请求风暴。

// CommError 是插件间通信失败的结构化错误（§七/§二十一）：Code 一定是 ErrorCodes 之一。
type CommError struct {
	Code    string
	Message string
	Data    map[string]any
}

// Error 实现 error 接口（"CODE: message"，与 Python PluginCommError 的 str() 同形）。
func (e *CommError) Error() string {
	if e == nil {
		return "<nil>"
	}
	if e.Message == "" {
		return e.Code
	}
	return e.Code + ": " + e.Message
}

// CommCode 取出任意 error 的结构化错误码；不是 *CommError 时归 INTERNAL_ERROR（err 为 nil 返回 ""）。
func CommCode(err error) string {
	if err == nil {
		return ""
	}
	var commErr *CommError
	if errors.As(err, &commErr) && commErr != nil {
		return commErr.Code
	}
	return CodeInternalError
}

// Handler 处理一次入站插件调用/事件（§五/§九）：参数是**完整请求模型**
// （request_id / source / target / method / params / timeout / trace_id / call_id /
// hop_count / route / metadata），返回值就是 CALL 的 result；EVENT 忽略返回值。
// 返回值不是语言无关类型 -> SERIALIZATION_ERROR；handler panic -> PLUGIN_ERROR。
type Handler func(request map[string]any) any

// CallOption 调整一次 Call 的策略（§十三 route / §十八 timeout）。
type CallOption func(*callOptions)

type callOptions struct {
	timeout   int
	route     string
	requestID string
	metadata  map[string]any
}

// WithTimeout 设置本次调用的超时（毫秒；<=0 用默认 5000，§十八）。
func WithTimeout(milliseconds int) CallOption {
	return func(options *callOptions) { options.timeout = milliseconds }
}

// WithRoute 设置路由策略 auto|core|local（§十三）。跨语言一律经 Core Router（§十二）；
// local 是 SDK 侧保留的通道（同进程托管多插件时才会命中），引擎不会假装走过 local。
func WithRoute(route string) CallOption {
	return func(options *callOptions) { options.route = route }
}

// WithRequestID 提议本次调用的 request_id（引擎为准：引擎仍可覆盖）。
// 传了它，插件才能在自己的请求还在途时用 Cancel(requestID, ...) 取消它（§十八）。
func WithRequestID(requestID string) CallOption {
	return func(options *callOptions) { options.requestID = requestID }
}

// WithMetadata 附带调用元数据（原样进请求模型，引擎不解释）。
func WithMetadata(metadata map[string]any) CallOption {
	return func(options *callOptions) { options.metadata = metadata }
}

// EmitResult 是一次事件广播的结果（§九/§十：EVENT 不是 RPC，只有投递统计，没有请求-响应语义）。
type EmitResult struct {
	OK        bool
	Delivered int
	Failed    []map[string]any
	TraceID   string
	Raw       map[string]any
}

// Expose 暴露一个方法给其它插件调用（§五 CALL 的被调方）。方法名规则与 Python runner 一致：
// 字母/下划线开头，允许 . 与 _，≤96 字符；非法名返回 INVALID_ARGUMENT（不静默忽略）。
func (p *Plugin) Expose(method string, handler Handler) error {
	if !validCommName(method) {
		return newCommError(CodeInvalidArgument,
			"方法名非法（字母/下划线开头，允许 . _，≤96）: "+method,
			map[string]any{"method": method})
	}
	if handler == nil {
		return newCommError(CodeInvalidArgument, "handler 不能为空", map[string]any{"method": method})
	}
	p.commMu.Lock()
	p.exposed[method] = handler
	p.commMu.Unlock()
	return nil
}

// OnPluginEvent 订阅其它插件广播的事件（§九）；事件名 "*" 表示订阅全部。
// （plugin.On 在 handler 是插件事件签名时也会走到这里 —— 见 On 的说明。）
func (p *Plugin) OnPluginEvent(name string, handler Handler) *Plugin {
	if name != "*" && !validCommName(name) {
		fmt.Fprintf(os.Stderr, "[flowerie] OnPluginEvent(%q): 事件名非法（字母/下划线开头，允许 . _，≤96）\n", name)
		return p
	}
	if handler == nil {
		fmt.Fprintf(os.Stderr, "[flowerie] OnPluginEvent(%q): handler 不能为空\n", name)
		return p
	}
	p.commMu.Lock()
	p.subs[name] = append(p.subs[name], handler)
	p.commMu.Unlock()
	return p
}

// CancelledRequests 返回收到过 CANCEL 的 request_id（升序；有界，供插件自查，§十八）。
func (p *Plugin) CancelledRequests() []string {
	p.commMu.Lock()
	defer p.commMu.Unlock()
	ids := make([]string, 0, len(p.cancelled))
	for requestID := range p.cancelled {
		ids = append(ids, requestID)
	}
	sort.Strings(ids)
	return ids
}

// Call 调用另一个插件（§五）：成功返回该方法的 result；失败返回 *CommError。
//
// 目标可以是 "plugin.a"（任意健康实例）或 "plugin.a#instance1"（指定实例，§十六）。
// 出站请求只带 target/method/params/timeout/route/trace_id/hop_count：source 由引擎按连接
// 填写（插件无法冒充别的插件，§四），hop_count 由引擎 +1（§二十二），插件不写一行 trace 代码。
func (p *Plugin) Call(target, method string, params map[string]any, opts ...CallOption) (any, error) {
	options := callOptions{timeout: DefaultCallTimeout, route: RouteAuto}
	for _, option := range opts {
		if option != nil {
			option(&options)
		}
	}
	if strings.TrimSpace(target) == "" {
		return nil, newCommError(CodeInvalidArgument,
			"target 不能为空（plugin_id 或 plugin_id#instance）", map[string]any{})
	}
	if strings.TrimSpace(method) == "" {
		return nil, newCommError(CodeInvalidArgument, "method 不能为空", map[string]any{})
	}
	route := strings.ToLower(strings.TrimSpace(options.route))
	if route == "" {
		route = RouteAuto
	}
	if route != RouteAuto && route != RouteCore && route != RouteLocal {
		return nil, newCommError(CodeInvalidArgument,
			"未知 route 策略: "+options.route+"（允许 auto|core|local）",
			map[string]any{"route": options.route})
	}
	timeout := options.timeout
	if timeout <= 0 {
		timeout = DefaultCallTimeout
	}
	if params == nil {
		params = map[string]any{}
	}
	clean, cerr := sanitizeValue(params, 0)
	if cerr != nil {
		return nil, cerr
	}
	traceID, hopCount := p.commContext()
	args := map[string]any{
		"target":    target,
		"method":    method,
		"params":    clean,
		"timeout":   timeout,
		"route":     route,
		"trace_id":  traceID,
		"hop_count": hopCount,
	}
	if options.requestID != "" {
		args["request_id"] = options.requestID
	}
	if len(options.metadata) > 0 {
		metadata, merr := sanitizeValue(options.metadata, 0)
		if merr != nil {
			return nil, merr
		}
		args["metadata"] = metadata
	}
	res, err := p.ctx.engineOp(MethodPluginCall, args)
	if err != nil {
		return nil, newCommError(CodeInternalError, err.Error(), map[string]any{"op": MethodPluginCall})
	}
	if ok, _ := res["ok"].(bool); !ok {
		return nil, commErrorFromAny(res["error"])
	}
	return res["result"], nil
}

// Emit 向其它插件广播事件（§九）。权限拒绝/环保护/参数非法返回 *CommError（错误码原样保留）；
// 个别订阅者投递失败**不算**整体失败，记在 EmitResult.Failed（与引擎语义一致）。
func (p *Plugin) Emit(name string, payload any) (EmitResult, error) {
	if strings.TrimSpace(name) == "" {
		return EmitResult{}, newCommError(CodeInvalidArgument, "事件名不能为空", map[string]any{})
	}
	if payload == nil {
		payload = map[string]any{}
	}
	clean, cerr := sanitizeValue(payload, 0)
	if cerr != nil {
		return EmitResult{}, cerr
	}
	traceID, hopCount := p.commContext()
	res, err := p.ctx.engineOp(OpPluginEmit, map[string]any{
		"name": name, "payload": clean, "trace_id": traceID, "hop_count": hopCount,
	})
	if err != nil {
		return EmitResult{}, newCommError(CodeInternalError, err.Error(), map[string]any{"op": OpPluginEmit})
	}
	out := EmitResult{Raw: res}
	if text, ok := res["trace_id"].(string); ok {
		out.TraceID = text
	}
	out.Delivered = intField(res, "delivered")
	if failed, ok := res["failed"].([]any); ok {
		for _, item := range failed {
			if entry, ok := item.(map[string]any); ok {
				out.Failed = append(out.Failed, entry)
			}
		}
	}
	if ok, _ := res["ok"].(bool); !ok {
		return out, commErrorFromAny(res["error"])
	}
	out.OK = true
	return out, nil
}

// Cancel 取消自己发起的一次在途调用（§十八）：目标插件收到 CANCEL 后应尽可能停下。
// request_id 由引擎在响应模型里回传（也可用 WithRequestID 自己提议）。
func (p *Plugin) Cancel(requestID, reason string) error {
	if strings.TrimSpace(requestID) == "" {
		return newCommError(CodeInvalidArgument, "request_id 不能为空", map[string]any{})
	}
	res, err := p.ctx.engineOp(MethodPluginCancel, map[string]any{
		"request_id": requestID, "reason": reason})
	if err != nil {
		return newCommError(CodeInternalError, err.Error(), map[string]any{"op": MethodPluginCancel})
	}
	if ok, _ := res["ok"].(bool); !ok {
		return commErrorFromAny(res["error"])
	}
	return nil
}

// ---------------- 通信内部：入站处理 / trace / 序列化 ----------------

// inboundContext 是一次入站消息的链路上下文（trace/hop 传递，§二十二/§二十三）。
type inboundContext struct {
	traceID   string
	hopCount  int
	source    map[string]any
	requestID string
}

func (p *Plugin) pushInbound(frame inboundContext) {
	p.commMu.Lock()
	p.inbound = append(p.inbound, frame)
	p.commMu.Unlock()
}

func (p *Plugin) popInbound() {
	p.commMu.Lock()
	if len(p.inbound) > 0 {
		p.inbound = p.inbound[:len(p.inbound)-1]
	}
	p.commMu.Unlock()
}

// commContext 返回当前入站消息的 trace_id / hop_count（没有就返回零值）：出站调用自动带上，
// 嵌套调用时链路连续（§二十三），插件作者不写一行 trace 代码。
func (p *Plugin) commContext() (string, int) {
	p.commMu.Lock()
	defer p.commMu.Unlock()
	if len(p.inbound) == 0 {
		return "", 0
	}
	frame := p.inbound[len(p.inbound)-1]
	return frame.traceID, frame.hopCount
}

// handleInboundCall 处理引擎投递进来的一次 plugin.call（§五/§六/§七）：查 expose 注册表，
// 找到就调 handler（handler 收到**完整请求模型**），把返回值当 CALL 的 result 回给引擎。
func (p *Plugin) handleInboundCall(id int, params map[string]any) {
	requestID := stringField(params, "request_id")
	method := stringField(params, "method")
	source, _ := params["source"].(map[string]any)
	p.pushInbound(inboundContext{
		traceID:   stringField(params, "trace_id"),
		hopCount:  intField(params, "hop_count"),
		source:    source,
		requestID: requestID,
	})
	defer p.popInbound()

	if requestID != "" && p.takeCancelled(requestID) {
		p.replyCommResult(id, commErrorResponse(newCommError(CodeCancelled,
			"调用已被取消", map[string]any{"request_id": requestID})))
		return
	}
	handler, found := p.exposedHandler(method)
	if !found {
		p.replyCommResult(id, commErrorResponse(newCommError(CodeMethodNotFound,
			"插件未暴露方法: "+method,
			map[string]any{"method": method, "exposed": p.exposedMethods()})))
		return
	}
	result, recovered := invokeHandler(handler, params)
	if recovered != nil {
		p.replyCommResult(id, commErrorResponse(newCommError(CodePluginError,
			fmt.Sprintf("%v", recovered), map[string]any{})))
		return
	}
	clean, cerr := sanitizeValue(result, 0)
	if cerr != nil {
		p.replyCommResult(id, commErrorResponse(cerr))
		return
	}
	p.replyCommResult(id, map[string]any{"ok": true, "result": clean})
}

// handleInboundEvent 处理引擎投递进来的一次 plugin.event（§九）：投给 On/OnPluginEvent 注册的
// handler（"*" 匹配全部），回 {"ok":true,"handled":N}；单个 handler panic 只影响计数，不拖死进程。
func (p *Plugin) handleInboundEvent(id int, params map[string]any) {
	name := stringField(params, "name")
	source, _ := params["source"].(map[string]any)
	p.pushInbound(inboundContext{
		traceID:  stringField(params, "trace_id"),
		hopCount: intField(params, "hop_count"),
		source:   source,
	})
	defer p.popInbound()

	handled := 0
	for _, handler := range p.eventHandlers(name) {
		if _, recovered := invokeHandler(handler, params); recovered == nil {
			handled++
		}
	}
	p.replyResult(id, map[string]any{"ok": true, "handled": handled})
}

// handleInboundCancel 处理 CANCEL（§十八）：记下 request_id（有界），等它真正到达时回 CANCELLED。
func (p *Plugin) handleInboundCancel(id int, params map[string]any) {
	requestID := stringField(params, "request_id")
	if requestID != "" {
		p.commMu.Lock()
		if len(p.cancelled) >= maxCancelledIDs {
			p.cancelled = map[string]struct{}{} // 有界：取消记录不无限增长（与 Python runner 一致）
		}
		p.cancelled[requestID] = struct{}{}
		p.commMu.Unlock()
	}
	p.replyResult(id, map[string]any{"ok": true, "cancelled": requestID != ""})
}

// takeCancelled 判断某个 request_id 是否已被取消（取走即删，只生效一次）。
func (p *Plugin) takeCancelled(requestID string) bool {
	p.commMu.Lock()
	defer p.commMu.Unlock()
	if _, found := p.cancelled[requestID]; !found {
		return false
	}
	delete(p.cancelled, requestID)
	return true
}

func (p *Plugin) exposedHandler(method string) (Handler, bool) {
	p.commMu.Lock()
	defer p.commMu.Unlock()
	handler, found := p.exposed[method]
	return handler, found
}

// exposedMethods 返回已暴露的方法名（升序）：METHOD_NOT_FOUND 的 data.exposed 用它。
func (p *Plugin) exposedMethods() []string {
	p.commMu.Lock()
	defer p.commMu.Unlock()
	names := make([]string, 0, len(p.exposed))
	for name := range p.exposed {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

// eventHandlers 返回某个事件名的订阅者：先精确匹配，再 "*" 通配（与 Python runner 同序）。
func (p *Plugin) eventHandlers(name string) []Handler {
	p.commMu.Lock()
	defer p.commMu.Unlock()
	handlers := make([]Handler, 0, len(p.subs[name])+len(p.subs["*"]))
	handlers = append(handlers, p.subs[name]...)
	if name != "*" {
		handlers = append(handlers, p.subs["*"]...)
	}
	return handlers
}

// replyCommResult 回一条插件间通信应答：语言内部对象在这里被拦下（§十九/§二十），
// 序列化失败也要回一条结构化应答，而不是写出半条 JSON 让引擎等到超时。
func (p *Plugin) replyCommResult(id int, payload map[string]any) {
	raw, err := json.Marshal(payload)
	if err != nil {
		raw, _ = json.Marshal(commErrorResponse(newCommError(CodeSerializationError,
			"返回值不是语言无关类型: "+err.Error(), map[string]any{})))
	}
	_ = p.write(reply{ID: id, Result: raw})
}

// commErrorResponse 把结构化错误包成响应模型（§七）：code/message/data 原样保留。
func commErrorResponse(err *CommError) map[string]any {
	if err == nil {
		err = newCommError(CodeInternalError, "未知错误", map[string]any{})
	}
	return map[string]any{"ok": false, "error": map[string]any{
		"code": err.Code, "message": err.Message, "data": err.Data}}
}

// newCommError 构造结构化错误：未知错误码一律归 INTERNAL_ERROR（不留伪造码的口子）。
func newCommError(code, message string, data map[string]any) *CommError {
	if !validErrorCode(code) {
		code = CodeInternalError
	}
	if data == nil {
		data = map[string]any{}
	}
	return &CommError{Code: code, Message: message, Data: data}
}

// validErrorCode 判断错误码是否属于 §二十一 的 12 个码。
func validErrorCode(code string) bool {
	for _, known := range ErrorCodes {
		if known == code {
			return true
		}
	}
	return false
}

// commErrorFromAny 把引擎响应里的 error 字段（{code,message,data} 或协议级字符串）转成
// *CommError：错误码原样保留，绝不退化成一句字符串（§七/§二十一）。
func commErrorFromAny(raw any) *CommError {
	if entry, ok := raw.(map[string]any); ok {
		code := stringField(entry, "code")
		if code == "" {
			code = CodePluginError
		}
		message := stringField(entry, "message")
		if message == "" {
			message = code
		}
		data, _ := entry["data"].(map[string]any)
		return newCommError(code, message, data)
	}
	if raw == nil {
		return newCommError(CodePluginError, "插件调用失败", map[string]any{})
	}
	text := fmt.Sprintf("%v", raw)
	if text == "" {
		text = "插件调用失败"
	}
	return newCommError(CodePluginError, text, map[string]any{})
}

// invokeHandler 调用 handler 并把 panic 转成结构化失败（协议要求 handler 异常 -> PLUGIN_ERROR，
// 不杀进程、不断连）。recovered == nil 表示正常返回。
func invokeHandler(handler Handler, request map[string]any) (result any, recovered any) {
	defer func() {
		if r := recover(); r != nil {
			result, recovered = nil, r
		}
	}()
	return handler(request), nil
}

// sanitizeValue 把值归一成**语言无关**的 JSON 形状（§十九/§二十）：Go 内部对象
// （struct / func / chan / complex / unsafe.Pointer）、非字符串键、NaN/Inf 一律
// SERIALIZATION_ERROR —— 而不是让 json.Marshal 悄悄转换（或写出半条 JSON 后断流）。
// 允许：null / boolean / integer / number / string / array / object / bytes
// （[]byte -> {"$bytes": base64, "size": N}，与其它语言 SDK 同一份线格式）。
func sanitizeValue(value any, depth int) (any, *CommError) {
	if depth > maxSerializationDepth {
		return nil, newCommError(CodeSerializationError, "嵌套层级过深（>32）", map[string]any{})
	}
	if value == nil {
		return nil, nil
	}
	rv := reflect.ValueOf(value)
	switch rv.Kind() {
	case reflect.Bool:
		return rv.Bool(), nil
	case reflect.String:
		return rv.String(), nil
	case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64:
		return rv.Int(), nil
	case reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64:
		return rv.Uint(), nil
	case reflect.Float32, reflect.Float64:
		return checkedFloat(rv.Float())
	case reflect.Slice:
		if rv.Type().Elem().Kind() == reflect.Uint8 {
			return bytesRef(rv.Bytes()), nil
		}
		return sanitizeList(rv, depth)
	case reflect.Array:
		return sanitizeList(rv, depth)
	case reflect.Map:
		if rv.Type().Key().Kind() != reflect.String {
			return nil, newCommError(CodeSerializationError,
				"对象键必须是字符串（收到 "+rv.Type().Key().String()+"）",
				map[string]any{"key_type": rv.Type().Key().String()})
		}
		out := make(map[string]any, rv.Len())
		iter := rv.MapRange()
		for iter.Next() {
			item, err := sanitizeValue(iter.Value().Interface(), depth+1)
			if err != nil {
				return nil, err
			}
			out[iter.Key().String()] = item
		}
		return out, nil
	case reflect.Ptr, reflect.Interface:
		if rv.IsNil() {
			return nil, nil
		}
		return sanitizeValue(rv.Elem().Interface(), depth+1)
	default:
		return nil, newCommError(CodeSerializationError,
			"语言内部对象不能跨插件边界: "+rv.Type().String()+
				"（§十九 只允许 null/boolean/integer/number/string/array/object/bytes）",
			map[string]any{"actual_type": rv.Type().String()})
	}
}

// sanitizeList 递归归一数组/切片元素。
func sanitizeList(value reflect.Value, depth int) (any, *CommError) {
	out := make([]any, 0, value.Len())
	for index := 0; index < value.Len(); index++ {
		item, err := sanitizeValue(value.Index(index).Interface(), depth+1)
		if err != nil {
			return nil, err
		}
		out = append(out, item)
	}
	return out, nil
}

// bytesRef 是二进制引用的线格式（§十九），与 Python/TS/Java SDK 同一份编码。
func bytesRef(data []byte) map[string]any {
	return map[string]any{"$bytes": base64.StdEncoding.EncodeToString(data), "size": len(data)}
}

// checkedFloat 拒绝 NaN/Infinity（JSON 没有这两种数，跨语言无法表达）。
func checkedFloat(value float64) (any, *CommError) {
	if math.IsNaN(value) || math.IsInf(value, 0) {
		return nil, newCommError(CodeSerializationError,
			"NaN/Infinity 不能跨语言传输（JSON 无此类型）", map[string]any{})
	}
	return value, nil
}

func stringField(source map[string]any, key string) string {
	value, _ := source[key].(string)
	return value
}

func intField(source map[string]any, key string) int {
	switch typed := source[key].(type) {
	case int:
		return typed
	case int64:
		return int(typed)
	case float64:
		return int(typed)
	case json.Number:
		number, err := typed.Int64()
		if err == nil {
			return int(number)
		}
	}
	return 0
}

// validCommName 校验方法名/事件名（与 Python runner 同一套规则：字母/下划线开头，
// 允许 . 与 _，≤96 字符）。
func validCommName(name string) bool {
	if len(name) == 0 || len(name) > 96 {
		return false
	}
	for index, r := range name {
		if index == 0 {
			if !(r >= 'a' && r <= 'z') && !(r >= 'A' && r <= 'Z') && r != '_' {
				return false
			}
			continue
		}
		alnum := (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9')
		if !alnum && r != '_' && r != '.' {
			return false
		}
	}
	return true
}

// 占位：确保 io 被使用（Scanner 出错时返回 Err）。
var _ = io.EOF
