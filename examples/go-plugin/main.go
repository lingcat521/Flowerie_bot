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

	plugin.OnShutdown(func(ctx *flowerie.Context) {
		ctx.Logf("go 示例插件退出")
	})

	if err := plugin.Run(); err != nil {
		panic(err)
	}
}
