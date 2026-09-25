# Go SDK（github.com/lingcat521/Flowerie_bot/sdk/go/flowerie）

> 任务书第 2 份 §六 / §十五。协议规范：[plugin-protocol.md](plugin-protocol.md)；
> 能力矩阵：[plugin-sdk-capabilities.md](plugin-sdk-capabilities.md)；总览：[plugin-sdk.md](plugin-sdk.md)。
> 源码：`sdk/go/flowerie/plugin.go`；示例：`examples/go-plugin/`。

## 1. 定位与依赖

- **零第三方依赖**：只用标准库（bufio / encoding/json / os / sync …）；
- 构建：`go build`（`examples/go-plugin/go.mod` 用 `replace` 指向本仓库的 `sdk/go/flowerie`）；
- 运行期模型：单进程 + 两条 goroutine（读循环独立，反向请求才不会被自己锁死——见 `Run()` 注释里的实测）。

## 2. 最小示例

```go
package main

import "github.com/lingcat521/Flowerie_bot/sdk/go/flowerie"

func main() {
	plugin := flowerie.New()

	plugin.OnStartup(func(ctx *flowerie.Context) { ctx.Logf("启动 %s", ctx.PluginID) })
	plugin.OnMessage(func(ctx *flowerie.Context, ev map[string]any) any {
		if text, _ := ev["text"].(string); text == "ping" {
			return flowerie.Action{"type": "send_group_msg",
				"params": map[string]any{"group_id": ev["group_id"], "message": "pong"}}
		}
		return nil
	})
	plugin.RegisterHook("status", func(args ...any) any {
		value, _ := plugin.Context().StorageGet("counter")
		return map[string]any{"counter": value}
	})

	// Plugin WebUI Protocol：页面 / 动作 / 资源
	plugin.WebUI().
		Page(func(args map[string]any) any {
			return map[string]any{"html": "<h2>设置</h2>",
				"vars": map[string]any{"nickname": ""}}
		}).
		Action(func(args map[string]any) any {
			form, _ := args["form"].(map[string]any)
			return map[string]any{"message": "已保存",
				"storage_set": map[string]any{"nickname": form["nickname"]}}
		}).
		Asset(func(args map[string]any) any {
			return map[string]any{"content_type": "text/css", "body": "body{color:#1f6feb}"}
		})

	if err := plugin.Run(); err != nil {
		panic(err)
	}
}
```

## 3. API 一览

| 能力 | 用法 |
| :--- | :--- |
| 生命周期 | `OnStartup / OnShutdown` · `Run()` |
| 事件 | `OnMessage` · `OnCommand / OnNotice / OnRequest / OnLifecycle / OnSchedule` · `On(name, fn)` |
| 心跳 | `OnHealth(func(*Context) bool)` |
| 动作 | `ctx.Action("send_group_msg", map[string]any{...})` |
| 存储 | `ctx.StorageGet/Set/Delete/List` |
| 配置 | `ctx.ConfigGet(keys)` / `ctx.ConfigSet(values)` |
| 权限 | `ctx.PermissionCheck("send_message")` |
| 上下文 | `ctx.Info()` |
| 日志 | `ctx.Logf(...)`（stderr） |
| 控制面 hook | `RegisterHook(name, func(args ...any) any)` |
| WebUI Protocol | `plugin.WebUI().Page(...).Action(...).Asset(...)` |

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
