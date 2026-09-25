// Go 示例插件：与 Python / TypeScript / Rust / Java 示例**语义完全一致**。
// 编译运行：run.sh（go build → 执行）；协议规范见 docs/plugin-protocol.md。
package main

import (
	"errors"
	"sync"
	"time"

	"github.com/lingcat521/Flowerie_bot/sdk/go/flowerie"
)

func main() {
	plugin := flowerie.New()

	plugin.OnStartup(func(ctx *flowerie.Context) {
		ctx.Logf("go 示例插件启动 plugin_id=%s", ctx.PluginID)
		// 插件间通信的暴露方法与事件订阅（任务书第 4 份 §九）：必须在 initialize 里注册，
		// 否则引擎投递进来的 plugin.call 会以 METHOD_NOT_FOUND 结束。
		registerComm(plugin, ctx)
	})

	plugin.OnMessage(func(ctx *flowerie.Context, ev map[string]any) any {
		if text, _ := ev["text"].(string); text == "ping" {
			return flowerie.Action{
				"type": "send_group_msg",
				"params": map[string]any{
					"group_id": ev["group_id"],
					"message":  "pong",
				},
			}
		}
		return nil
	})

	// 命令事件（与 Python 的 on_command 对齐）：/ping → pong
	plugin.OnCommand(func(ctx *flowerie.Context, ev map[string]any) any {
		if text, _ := ev["text"].(string); text == "/ping" {
			return flowerie.Action{
				"type": "send_group_msg",
				"params": map[string]any{
					"group_id": ev["group_id"],
					"message":  "pong",
				},
			}
		}
		return nil
	})

	// 控制面 hook：插件 WebUI 的数据钩子走同一条通道
	plugin.RegisterHook("status", func(args ...any) any {
		value, ok := plugin.Context().StorageGet("counter")
		var n any
		if ok {
			if m, isMap := value.(map[string]any); isMap {
				n = m["n"]
			}
		}
		return map[string]any{"counter": n}
	})

	// ---------------- Plugin-to-Plugin 通信的 hook（任务书第 4 份 §九） ----------------
	// comm_call：args=[target, method, params]，可选第 4 个参数是超时（毫秒）、第 5 个是 route。
	// 失败**不抛出**，回 {"ok":false,"code":<错误码>,"message":<消息>}，让引擎侧能断言错误码。
	plugin.RegisterHook("comm_call", func(args ...any) any {
		options := []flowerie.CallOption{}
		if timeout := commArgInt(args, 3); timeout > 0 {
			options = append(options, flowerie.WithTimeout(timeout))
		}
		if route := commArgString(args, 4); route != "" {
			options = append(options, flowerie.WithRoute(route))
		}
		result, err := plugin.Call(commArgString(args, 0), commArgString(args, 1),
			commArgMap(args, 2), options...)
		if err != nil {
			return commFailure(err)
		}
		return map[string]any{"ok": true, "result": result}
	})

	// comm_emit：args=[name, payload]，返回广播结果 {ok, delivered, failed, trace_id}。
	plugin.RegisterHook("comm_emit", func(args ...any) any {
		result, err := plugin.Emit(commArgString(args, 0), commArgValue(args, 1))
		if err != nil {
			return commFailure(err)
		}
		failed := result.Failed
		if failed == nil {
			failed = []map[string]any{}
		}
		return map[string]any{
			"ok":        true,
			"delivered": result.Delivered,
			"failed":    failed,
			"trace_id":  result.TraceID,
		}
	})

	// comm_cancel：args=[request_id, reason]，取消自己发起的一次在途调用（§十八）。
	plugin.RegisterHook("comm_cancel", func(args ...any) any {
		if err := plugin.Cancel(commArgString(args, 0), commArgString(args, 1)); err != nil {
			return commFailure(err)
		}
		return map[string]any{"ok": true, "cancelled": true}
	})


	// ---------------- Plugin WebUI Protocol（任务书第 3 份 §六） ----------------
	// 页面 / 动作 / 资源三条通道；路由、权限、校验、净化、隔离全部由引擎负责。

	// HTML 文件页的模板变量（走 web_ui.entry 数据钩子）
	plugin.RegisterHook("webui_page", func(args ...any) any {
		return map[string]any{"vars": map[string]any{"nickname": readNickname(plugin)}}
	})

	plugin.WebUI().
		Page(func(args map[string]any) any {
			return map[string]any{
				"html": settingsForm(ctxPluginID(args, plugin.Context().PluginID)),
				"vars": map[string]any{"nickname": readNickname(plugin)},
			}
		}).
		Action(func(args map[string]any) any {
			action, _ := args["action"].(string)
			if action != "save" {
				return map[string]any{"ok": false, "error": "未知动作: " + action}
			}
			form, _ := args["form"].(map[string]any)
			nickname, _ := form["nickname"].(string)
			if len([]rune(nickname)) > 64 {
				nickname = string([]rune(nickname)[:64])
			}
			return map[string]any{
				"html":        settingsForm(ctxPluginID(args, plugin.Context().PluginID)),
				"vars":        map[string]any{"nickname": nickname},
				"message":     "已保存",
				"config_set":  map[string]any{"nickname": nickname},
				"storage_set": map[string]any{"nickname": nickname},
			}
		}).
		Asset(func(args map[string]any) any {
			if path, _ := args["path"].(string); path == "theme.css" {
				return map[string]any{"content_type": "text/css",
					"body": "body { color: #1f6feb; }"}
			}
			return map[string]any{"ok": false, "error": "资源不存在"}
		})

	plugin.OnShutdown(func(ctx *flowerie.Context) {
		ctx.Logf("go 示例插件退出")
	})

	if err := plugin.Run(); err != nil {
		panic(err)
	}
}

// ctxPluginID 取引擎给的受控 context 里的 plugin.id（插件不自己声明身份），拿不到再退回本地 ctx。
func ctxPluginID(args map[string]any, fallback string) string {
	context, _ := args["context"].(map[string]any)
	pluginInfo, _ := context["plugin"].(map[string]any)
	if id, _ := pluginInfo["id"].(string); id != "" {
		return id
	}
	return fallback
}

// readNickname 读本插件 storage 里的昵称（与 ctx.StorageGet 同一份文件）。
func readNickname(p *flowerie.Plugin) string {
	value, ok := p.Context().StorageGet("nickname")
	if !ok {
		return ""
	}
	text, _ := value.(string)
	return text
}

// ---------------- Plugin-to-Plugin 通信（任务书第 4 份 §五–§二十七） ----------------
//
// 与 Python / TypeScript / Rust / Java 示例同名同义：启动时 expose("get_status")，提供
// comm_call / comm_emit / comm_cancel 三个 hook；调用一律经 Core Router（没有第二条通道，§十二）。

// 示例自己的观察窗口（seen 方法可见）：收到过哪些调用/事件。引擎串行投递，这里只做示例级保护。
var (
	commMu     sync.Mutex
	commCalls  []map[string]any
	commEvents []map[string]any
)

// goOnlyObject 是只能在 Go 进程里存在的类型：跨插件边界必须被拒绝（§十九 -> SERIALIZATION_ERROR）。
type goOnlyObject struct {
	OnlyHere string
}

// registerComm 注册暴露的方法与事件订阅（§五/§九）：由 OnStartup 在 initialize 时调用。
func registerComm(plugin *flowerie.Plugin, ctx *flowerie.Context) {
	expose := func(method string, handler flowerie.Handler) {
		if err := plugin.Expose(method, handler); err != nil {
			ctx.Logf("expose %s 失败: %v", method, err)
		}
	}

	// 契约方法：别的插件（含其它语言）调用它，回执里带上请求模型里的 trace_id / hop_count。
	expose("get_status", func(request map[string]any) any {
		params := commParams(request)
		commMu.Lock()
		commCalls = append(commCalls, params)
		commMu.Unlock()
		return map[string]any{
			"plugin_id": commTargetPluginID(request, ctx.PluginID),
			"runtime":   "go",
			"trace_id":  commString(request, "trace_id"),
			"hop_count": commInt(request, "hop_count"),
			"echo":      params,
		}
	})

	// 观察窗口（与 Python 侧测试插件模板同名同义）：调用次数 / 收到的事件 / 已取消的 request_id。
	expose("seen", func(request map[string]any) any {
		commMu.Lock()
		defer commMu.Unlock()
		events := make([]map[string]any, len(commEvents))
		copy(events, commEvents)
		return map[string]any{
			"calls":     len(commCalls),
			"events":    events,
			"cancelled": plugin.CancelledRequests(),
		}
	})

	// 错误路径的对手方：handler panic -> 结构化 PLUGIN_ERROR（SDK 兜住，不杀进程、不断连）。
	expose("boom", func(request map[string]any) any {
		panic("go 示例插件内部炸了")
	})

	// 超时路径的对手方：睡 1.5s；调用方用 timeout=200ms 就能拿到 TIMEOUT（§十八）。
	expose("slow", func(request map[string]any) any {
		time.Sleep(1500 * time.Millisecond)
		return map[string]any{"slept": true}
	})

	// 序列化路径的对手方：Go 内部对象（struct）不能跨插件边界 -> SERIALIZATION_ERROR（§十九）。
	expose("lang_object", func(request map[string]any) any {
		return map[string]any{"bad": goOnlyObject{OnlyHere: "go"}}
	})

	// 环保护（§二十二）的对手方：ping / pong 互相回弹，超过最大 hop 由引擎终止。
	expose("ping", func(request map[string]any) any {
		return map[string]any{"bounced": commBounce(plugin, request, "pong")}
	})
	expose("pong", func(request map[string]any) any {
		return map[string]any{"bounced": commBounce(plugin, request, "ping")}
	})

	// 订阅事件（§九）："*" 匹配全部；收到的记在内存里，供 seen 查询。
	plugin.On("*", func(request map[string]any) any {
		commMu.Lock()
		if len(commEvents) < 32 { // 有界：示例不无限增长
			commEvents = append(commEvents, map[string]any{
				"name":    request["name"],
				"payload": request["payload"],
			})
		}
		commMu.Unlock()
		return map[string]any{"ok": true}
	})
}

// commBounce 回弹给来源插件（§二十二 环保护的对手方）：失败回结构化错误，不把调用抛出去。
func commBounce(plugin *flowerie.Plugin, request map[string]any, method string) any {
	source, _ := request["source"].(map[string]any)
	target, _ := source["plugin_id"].(string)
	if target == "" {
		return map[string]any{"ok": false, "code": "INVALID_ARGUMENT",
			"message": "请求里没有 source.plugin_id"}
	}
	result, err := plugin.Call(target, method, map[string]any{})
	if err != nil {
		return commFailure(err)
	}
	return map[string]any{"ok": true, "result": result}
}

// commFailure 把 SDK 的结构化错误转成 hook 的失败应答：错误码原样保留（§二十一）。
func commFailure(err error) map[string]any {
	var commErr *flowerie.CommError
	if errors.As(err, &commErr) && commErr != nil {
		return map[string]any{"ok": false, "code": commErr.Code, "message": commErr.Message}
	}
	return map[string]any{"ok": false, "code": "INTERNAL_ERROR", "message": err.Error()}
}

// commParams 取请求模型里的 params（缺失时给 {}，与其它语言示例一致）。
func commParams(request map[string]any) map[string]any {
	params, ok := request["params"].(map[string]any)
	if !ok || params == nil {
		return map[string]any{}
	}
	return params
}

// commTargetPluginID 取请求模型里的 target.plugin_id（引擎按连接填写，§四）；
// 拿不到时才退回 SDK 上下文 —— 与 Java/Rust 示例的兜底顺序保持一致。
func commTargetPluginID(request map[string]any, fallback string) string {
	target, ok := request["target"].(map[string]any)
	if !ok {
		return fallback
	}
	if id, ok := target["plugin_id"].(string); ok && id != "" {
		return id
	}
	return fallback
}

func commString(source map[string]any, key string) string {
	value, _ := source[key].(string)
	return value
}

func commInt(source map[string]any, key string) int {
	switch typed := source[key].(type) {
	case int:
		return typed
	case int64:
		return int(typed)
	case float64:
		return int(typed)
	}
	return 0
}

// commArgValue / commArgString / commArgMap / commArgInt：hook 的 args 是 JSON 数组解出来的 []any。
func commArgValue(args []any, index int) any {
	if index >= len(args) || args[index] == nil {
		return map[string]any{}
	}
	return args[index]
}

func commArgString(args []any, index int) string {
	value, _ := commArgValue(args, index).(string)
	return value
}

func commArgMap(args []any, index int) map[string]any {
	value, ok := commArgValue(args, index).(map[string]any)
	if !ok || value == nil {
		return map[string]any{}
	}
	return value
}

func commArgInt(args []any, index int) int {
	switch typed := commArgValue(args, index).(type) {
	case int:
		return typed
	case int64:
		return int(typed)
	case float64:
		return int(typed)
	}
	return 0
}

// settingsForm 插件渲染页的 HTML：{{ nickname }} 由引擎 escape 后替换（受控模板变量）。
func settingsForm(pluginID string) string {
	return "<h2>插件渲染页</h2>" +
		"<p class=\"who\">这份 HTML 来自插件进程（webui.page），不是磁盘文件。</p>" +
		"<form class=\"card\" method=\"post\" action=\"/panel/plugins/webui/" + pluginID + "/dynamic\">" +
		"<input type=\"hidden\" name=\"plugin_action\" value=\"save\">" +
		"<label>昵称 <input name=\"nickname\" value=\"{{ nickname }}\" maxlength=\"64\"></label>" +
		"<button type=\"submit\">保存</button></form>" +
		"<p class=\"msg\">{{ message }}</p>"
}
