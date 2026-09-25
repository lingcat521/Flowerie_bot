// Go 示例插件：与 Python / TypeScript / Rust / Java 示例**语义完全一致**。
// 编译运行：run.sh（go build → 执行）；协议规范见 docs/plugin-protocol.md。
package main

import (
	"github.com/lingcat521/Flowerie_bot/sdk/go/flowerie"
)

func main() {
	plugin := flowerie.New()

	plugin.OnStartup(func(ctx *flowerie.Context) {
		ctx.Logf("go 示例插件启动 plugin_id=%s", ctx.PluginID)
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


	// ---------------- Plugin WebUI Protocol（任务书第 3 份 §六） ----------------
	// 页面 / 动作 / 资源三条通道；路由、权限、校验、净化、隔离全部由引擎负责。

	// HTML 文件页的模板变量（走 web_ui.entry 数据钩子）
	plugin.RegisterHook("webui_page", func(args ...any) any {
		return map[string]any{"vars": map[string]any{"nickname": readNickname(plugin)}}
	})

	plugin.WebUI().
		Page(func(args map[string]any) any {
			return map[string]any{
				"html": settingsForm(plugin.Context().PluginID),
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
				"html":        settingsForm(plugin.Context().PluginID),
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

// readNickname 读本插件 storage 里的昵称（与 ctx.StorageGet 同一份文件）。
func readNickname(p *flowerie.Plugin) string {
	value, ok := p.Context().StorageGet("nickname")
	if !ok {
		return ""
	}
	text, _ := value.(string)
	return text
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
