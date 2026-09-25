# Go SDK（github.com/lingcat521/Flowerie_bot/sdk/go/flowerie）

> 总览与通用规则：[plugin-sdk.md](plugin-sdk.md)｜协议：[plugin-protocol.md](plugin-protocol.md)｜能力矩阵：[plugin-sdk-capabilities.md](plugin-sdk-capabilities.md)
> 源码 `sdk/go/flowerie/plugin.go` · 示例 `examples/multilang-sdk/go/`（契约/WebUI 用例另跑 `examples/go-plugin/`）· CI 实测：`tests/sdk/test_minimal_plugins.py::test_build_load_ready_and_api[go]`、`tests/sdk/test_minimal_paths.py::test_plugin_communication_path[typescript->go]`、`tests/test_plugin_sdk_contract.py::test_handshake_declares_protocol_and_capabilities[go]`、`tests/test_plugin_webui_multilang.py::test_webui_page_receives_engine_context[go]`

## 1. 安装与引入
- 工具链 **Go ≥ 1.21**（`sdk/go/flowerie/go.mod:3`）；缺工具链时 `build.sh:26-28` 直接 exit 1，不假装构建成功。
- **零第三方依赖**：只用标准库（`plugin.go:1,15-29`），`build.sh:89` 用 `GOPROXY=off`，让「需要下载依赖」变成硬失败而不是悄悄联网。
- 引入：模块路径 `github.com/lingcat521/Flowerie_bot/sdk/go/flowerie`（`go.mod:1`），插件 `go.mod` 用 `require` + `replace` 指向仓库内该目录（`examples/go-plugin/go.mod:5-7`）；多语言示例则由 `build.sh` 在 `.build/src` 生成临时模块。
- 环境变量：SDK 源码不读任何环境变量；构建期按 `FLOWERIE_SDK_GO` → `FLOWERIE_REPO_ROOT` → `<插件>/../../../sdk/go/flowerie` → 逐级向上 → `GITHUB_WORKSPACE` 找 SDK（`build.sh:9-14,31-64`），无 `HOME` 时兜底 `GOCACHE`（`build.sh:82-85`）；运行期插件进程只拿到引擎白名单环境（`src/plugins/runtime.py:40-41`），`FLOWERIE_GO_BIN`（`run.sh:9`）只在手工跑 run.sh 时有效。

## 2. 最小插件（可直接复制）
清单由 `examples/multilang-sdk/go/manifest.json` 精简（省略 `author`/`description`/`web_ui` 与其余权限；`src/plugins/manifest.py:125` 的七个必填字段一个不少）：
```json
{ "id": "minimal_go", "name": "Minimal Go 插件", "version": "1.0.0",
  "runtime": "exec", "entry": "run.sh", "api_version": 1,
  "permissions": ["read_message", "send_message", "web_ui"] }
```
入口取自 `examples/go-plugin/main.go`（结构）与 `examples/multilang-sdk/go/main.go:615-621`（动作形状）：
```go
package main

import "github.com/lingcat521/Flowerie_bot/sdk/go/flowerie"

func main() {
	plugin := flowerie.New()
	plugin.OnStartup(func(ctx *flowerie.Context) { ctx.Logf("启动 %s", ctx.PluginID) })
	plugin.OnMessage(func(ctx *flowerie.Context, ev map[string]any) any {
		if text, _ := ev["text"].(string); text == "ping" {
			return flowerie.Action{"type": "send_message",   // 引擎只读 action["payload"]，且只执行白名单动作
				"payload": map[string]any{"group_id": ev["group_id"], "message": "pong"}}
		}
		return nil                                        // 不匹配回 nil = 无动作
	})
	if err := plugin.Run(); err != nil {
		panic(err)
	}
}
```

## 3. 事件注册（`plugin.go:行`）
| 事件 / 钩子 | 本语言写法 |
| :--- | :--- |
| `message` | `plugin.OnMessage(fn)` :238（fn 可返回 `Action` / `map[string]any` / `[]Action` / `nil`，:668-682）|
| `command` / `notice` / `request` / `lifecycle` / `schedule` | `OnCommand` :213 · `OnNotice` :218 · `OnRequest` :223 · `OnLifecycle` :228 · `OnSchedule` :233（都落到 `On(name, fn)` :253）|
| 任意引擎事件（如 `test.event`）| `plugin.On("test.event", func(*flowerie.Context, map[string]any) any)` :253-261 |
| `initialize` / `health` / `shutdown` | `OnStartup` :198 · `OnHealth` :207（返回 false 即不健康）· `OnShutdown` :201 |
| 控制面 hook（WebUI 文件页数据）| `plugin.RegisterHook(name, func(args ...any) any)` :269（名字须匹配 `^[a-z_][a-z0-9_]{0,63}$`，:501-503）；派生钩子 / matcher 无——Go 侧统一写 `On("<事件名>", …)`（:253-265）|

## 4. API 表（`sdk/go/flowerie/plugin.go`）
| 能力 | 本语言签名 / 写法 |
| :--- | :--- |
| 创建 · 运行 · 上下文 | `flowerie.New() *Plugin` :164 · `(*Plugin).Run() error` :318 · `(*Plugin).Context() *Context` :308 · `Context{PluginID,PluginDir,DataDir}` :156-160 |
| 动作 · 日志 | `(*Context).Action(actionType string, params map[string]any) (map[string]any, error)` :730 · `(*Context).Logf(format string, args ...any)` :757（stderr）｜ 存储 · 配置 · 权限 · 上下文查询：`StorageGet` :796 · `StorageSet` :813 · `StorageDelete` :840 · `StorageList` :849 · `ConfigGet([]string)` :883 · `ConfigSet(map[string]any)` :907 · `PermissionCheck(string) (bool, error)` :735 · `Info()` :745 |
| 插件间通信 | `Expose(method, Handler)` :1025 · `Call(target, method, params, opts...)` :1074 · `Emit(name, payload)` :1140 · `Cancel(requestID, reason)` :1179 · `OnPluginEvent` :1042 · `Handler` :980 · `CommError` :947 · `CommCode(err)` :965 · `WithTimeout/WithRoute/WithRequestID/WithMetadata` :993/:999/:1005/:1010 |
| WebUI · 常量 | `WebUI().Page/.Action/.Asset` :287/:290/:296/:302 · `ProtocolVersion` :32 · `ErrorCodes` :84 · `Action` :98 · `RouteAuto/RouteCore/RouteLocal` :61-63 |

## 5. 存储 / 配置 / 权限（通用语义见 [plugin-sdk.md §5](plugin-sdk.md#5-存储配置与权限)）
- 存储落 `<data_dir>/storage/<key>.json`（:779-793）：键 ≤64 且首字符字母数字、只允许 `. _ -`（:763-777），值 ≤64 KiB、最多 200 键（:37-38,:822-835）。
- `ConfigGet(keys)` :883 返回「操作员值 + 插件覆盖层，操作员优先」；`ConfigSet` :907 只写 `<data_dir>/config.json` 覆盖层（键 ≤64、值 ≤8 KiB，:39-40），改不动操作员配置。
- `PermissionCheck` :735 是只读查询，插件无法提权；权限先写进 manifest `permissions`。

## 6. WebUI
`web_ui` 段（`examples/multilang-sdk/go/manifest.json:17-24`）：`static` 静态目录 + `entry` 文件页数据钩子 + `pages[]`——`{ "id", "render": "plugin" }` 是插件渲染页，文件页写 `"file"`（对比 `examples/go-plugin/manifest.json:22-42`）。
```go
plugin.WebUI().
	Page(func(args map[string]any) any { return map[string]any{"html": "<h2>设置</h2>", "vars": map[string]any{}} }).
	Action(func(args map[string]any) any { return map[string]any{"message": "已保存", "storage_set": map[string]any{}} }).
	Asset(func(args map[string]any) any { return map[string]any{"content_type": "text/css", "body": "…"} })
```
> 真实处理器见 `examples/go-plugin/main.go:112-146`（文件页模板变量走 `RegisterHook("webui_page", …)`）；多语言示例只注册了 Page/Action。

## 7. 插件间通信
`plugin.Call(target, method, params, opts...)` :1074 · `Emit` :1140 · `OnPluginEvent(name, Handler)` :1042 · `Expose` :1025 · `Cancel` :1179；失败一律 `*flowerie.CommError`，用 `flowerie.CommCode(err)` :965 取 12 个结构化错误码之一。`plugin.On` 一条入口服务两条通道：handler 是 `func(map[string]any) any` 收插件事件，是 `func(*flowerie.Context, map[string]any) any` 收引擎事件（:253-266）。通用语义见 [plugin-sdk.md §7](plugin-sdk.md#7-插件间通信)。

## 8. 构建与运行
- 构建 `sh build.sh`：在 `.build/src` 生成临时 `go.mod`（绝对路径 `replace` SDK）后跑 `GOFLAGS=-mod=mod GOPROXY=off GOWORK=off CGO_ENABLED=0 go build -trimpath -o "$BUILD_DIR/plugin" .`（`build.sh:68-91`），产物 `<插件目录>/.build/plugin`。
- 运行 `sh run.sh` → `exec "${FLOWERIE_GO_BIN:-<插件目录>/.build/plugin}"`（`run.sh:9,17`）；manifest 写 `"runtime": "exec"` + `"entry": "run.sh"`；缺工具链/产物：无 `go` 时 `build.sh:26-29` 提示装 Go ≥ 1.21 并 exit 1；没构建就跑 `run.sh` 是 exit 3（`run.sh:11-15`，**绝不隐式编译**）；找不到 SDK 源码 exit 1 并提示用 `FLOWERIE_SDK_GO=…` 指路。

## 9. 常见错误
| 症状 | 原因 → 处理（出处）|
| :--- | :--- |
| 动作不报错但消息发不出去 | 写了 `"params"` 或 `send_group_msg`：引擎只读 `action["payload"]`（`src/plugins/manager.py:1329`），未知动作直接 `{"ok":false,"error":"未知 action"}`（`manager.py:2450`）。→ 用 §2 的 `send_message` + `payload` |
| 钩子「注册了」却毫无反应 | `On` 的 handler 签名不认识时只往 stderr 打一行、**不注册**（:262-264）；`RegisterHook` 名字含大写/`.`/超 64 字符报「hook 名非法」（:501-503,:615-626）|
| WebUI 回「插件未注册 webui.page 处理器」/「没有返回内容」 | 没注册对应通道（:519-525），或 handler 返回 `nil` / 非法类型（:649-652）；`storage.set` 报「值超过上限」/「键数量超过上限」则是值 >64 KiB、键数 ≥200（:37-38,:822-835），键非法（非字母数字开头、含其它字符、>64）见 :763-777 |
| 本机跑不动 `tests/sdk/`（SKIP）| 缺 `go`，或 Termux 下引擎按白名单裁剪环境（不含 `LD_PRELOAD`）→ 测试 skip 并打印原因（`tests/sdk/harness.py:42-55`、`src/plugins/runtime.py:40-41`）|
