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
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
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

	ctx *Context

	startupHooks  []func(*Context)
	shutdownHooks []func(*Context)
	healthHooks   []func(*Context) bool
	messageHooks  []func(*Context, map[string]any) any
	eventHooks    map[string][]func(*Context, map[string]any) any
	namedHooks    map[string]func(args ...any) any
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
			"storage.delete", "storage.get", "storage.list", "storage.set",
		},
		pending:    map[int]chan reply{},
		eventHooks: map[string][]func(*Context, map[string]any) any{},
		namedHooks: map[string]func(args ...any) any{},
		out:        bufio.NewWriter(os.Stdout),
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

// On 注册任意事件的钩子。
func (p *Plugin) On(event string, fn func(*Context, map[string]any) any) *Plugin {
	p.eventHooks[event] = append(p.eventHooks[event], fn)
	return p
}

// RegisterHook 注册控制面可调用的 hook（插件 WebUI 的数据钩子走同一通道）。
func (p *Plugin) RegisterHook(name string, fn func(args ...any) any) *Plugin {
	p.namedHooks[name] = fn
	return p
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
	requests := make(chan message, 16)
	readDone := make(chan error, 1)
	go func() {
		defer close(requests)
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
			requests <- msg
		}
		readDone <- scanner.Err()
	}()
	for msg := range requests {
		if p.handle(msg) {
			return nil // shutdown：主循环结束，读循环随进程退出
		}
	}
	return <-readDone
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
		return nil, err
	}
	msg, ok := <-ch
	if !ok {
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

// 占位：确保 io 被使用（Scanner 出错时返回 Err）。
var _ = io.EOF
