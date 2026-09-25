# Plugin WebUI Protocol（统一 WebUI 协议 · v1）

> **WebUI 是 Plugin Protocol 的一部分**，不是某个语言 SDK 的附属：插件只负责「内容与业务」，
> Runtime 负责「托管、路由、权限、校验、净化、隔离」。三个协议方法（`webui.page` / `webui.action` /
> `webui.asset`）走 [plugin-protocol.md](plugin-protocol.md) 的同一套信封与能力声明，不另开进程、不另开端口。
>
> 实现：`src/plugins/manager.py`（三条通道）、`src/plugins/webui_loader.py`（路径校验唯一实现）、
> `src/plugins/webui_security.py`（HTML/CSS 净化唯一实现）、`src/services/webui_panels/`（HTTP 入口）、
> `src/plugins/manifest.py`（`web_ui` 校验）。使用指南见 [plugin-webui.md](plugin-webui.md)；
> 迁移审计见 [plugin-webui-migration.md](plugin-webui-migration.md)。

## 1. 协议方法（引擎 → 插件；能力组 `webui`，未声明引擎绝不调用）

| 方法 | params | result |
| :--- | :--- | :--- |
| `webui.page` | `{"page":{"id","title","description"},"context":{…}}` | `{"html":"…","vars":{…},"message":"…"}` |
| `webui.action` | `{"page":{…},"action":"save","form":{…},"context":{…}}` | 同上，另可带 `config_set` / `storage_set` |
| `webui.asset` | `{"path":"theme.css"}` | `{"content_type":"text/css","body":"…"}`（二进制用 `base64`） |

返回归一化（五种语言 SDK 同一实现）：返回**字符串** = `{"html": …}` 简写；返回**对象**只透传白名单字段
`html / vars / context / message / content_type / body / base64 / config_set / storage_set`，其余丢弃；
返回 `{"ok":false,"error":"…"}` 是**操作级**失败（未知方法/参数非法才是**协议级**错误）；引擎侧调用超时 **4s**。

## 2. 目录、manifest 与三种页面形态

```text
my-plugin/{manifest.json, plugin.py|.ts|main.go|lib.rs|Plugin.java,
           webui/pages/*.html（文件页）, webui/static/*.css|图片|文本（无 .js）}
```

```json
{"web_ui": {"static": "static", "entry": "webui_page", "pages": [
  {"id": "index", "title": "总览", "file": "pages/index.html"},
  {"id": "settings", "title": "设置", "file": "pages/settings.html"},
  {"id": "dynamic", "title": "插件渲染页", "render": "plugin"}]}}
```

| 形态 | 声明方式 | HTML 来源 |
| :--- | :--- | :--- |
| 文件页（首选） | `pages[].file`（或 `render:"file"`） | 磁盘 `webui/pages/*.html` + 受控模板变量 |
| 插件渲染页 | `pages[].render = "plugin"` | 插件进程经 `webui.page` 返回 |
| DSL 页（deprecated 兼容层） | 既不写 `file` 也不写 `render` | 插件 `web_ui.entry` hook 返回组件树 |

manifest 校验（**加载前**就拒，不等到 HTTP 请求）：页面 id `^[a-z][a-z0-9_-]{0,31}$`、页数 ≤ 8、
title 1~64 字符、未知字段拒绝；`file` 必须是插件内相对路径（禁绝对路径/`..`/反斜杠/隐藏段，
必须 `.html`），`file` 与 `render:"plugin"` **互斥**；`static` 只能是插件内相对目录。

## 3. 受控 Context（引擎 → 插件，永远只有 6 个顶层键）

```json
{"plugin":{"id":"example","name":"示例插件"},"page":{"id":"settings","title":"设置"},
 "request":{"method":"GET","action":"get"},"user":{"authenticated":true,"role":"admin"},
 "config":{},"data":{}}
```

- `config` 需要 `webui.config.read`（操作员配置，**只读**）；`data` 需要 `webui.storage.read`
  （插件 storage 快照，引擎经 `storage.list` + `storage.get` 取）；未批准就是空对象（不报错，页面照常渲染）；
- **绝不**放入面板令牌、会话、环境变量、宿主路径（安全用例逐项断言）。

给 HTML 的**模板变量**是另一条更窄的通道：引擎固定的 `plugin_id / plugin_name / page_id / page_title /
page_description / message` + 插件在 `webui.page` / 数据钩子里显式返回的 `vars`；值**一律 HTML escape**。

## 4. HTTP 路由与渲染顺序

| 方法 | 路径 | 通道 |
| :--- | :--- | :--- |
| GET | `/panel/plugins/webui/{pid}/{page}` | 渲染页面（文件页 / 插件渲染页 / DSL 兼容） |
| POST | `/panel/plugins/webui/{pid}/{page}` | 表单动作：`plugin_action` 选动作，其余字段是 form |
| GET | `/panel/plugins/webui/{pid}/static/{path}` | 磁盘静态资源（`webui/static`） |
| GET | `/panel/plugins/webui/{pid}/asset/{path}` | 插件进程生成的资源（`webui.asset`） |

四个入口都先过面板令牌（未认证重定向 `/panel`），再过权限（未批准一律 404，**不泄露插件是否存在**）。
表单只能 `method="post"` 且 CSP `form-action 'self'`：POST 永远不能绕过权限，也不能直接调用内部对象 ——
它只能变成一次协议方法调用。**渲染顺序固定**：先净化（白名单）→ 再替换受控变量（值 escape）→ 再套面板壳，
所以变量里带 `{{ }}` / `<script>` 只会变成文本。

## 5. 权限（`permissions.py::webui_permission_granted` 是唯一判定实现）

| 权限 | 管什么 | 兼容映射 |
| :--- | :--- | :--- |
| `webui.view` | 打开页面 / 读静态与动态资源（能力 `webui.page` / `webui.asset` 的闸门） | 老清单的 `web_ui` 等价 |
| `webui.action` | 提交表单动作（POST，引擎调 `webui.action`） | 老清单的 `web_ui` 等价 |
| `webui.config.read` | context 里带操作员配置 | 无 |
| `webui.config.write` | 动作把配置写回插件自己的覆盖层（`config_set`） | 无 |
| `webui.storage.read` | context 里带插件存储快照 | 无 |
| `webui.storage.write` | 动作写插件存储（`storage_set`） | 无 |

写权限被拒 / 写失败**不静默**：面板壳把告警显示给管理员；No-JS 政策不变 —— 静态资源白名单里没有
`.js`，插件资源 MIME 白名单里没有 javascript / text/html / svg，**不存在任何 JavaScript 权限**。

## 6. 资源与隔离

- 路径校验唯一实现：`webui_loader.validate_relative`（相对路径、扩展名白名单、禁 `..`/绝对路径/
  反斜杠/隐藏段）+ `resolve_within`（`realpath` 必须仍在插件目录内 → 防 symlink 逃逸）；
- 静态文件与插件资源是**两条通道、同一套规则**：同一批扩展名白名单（**没有 .js**）、同一套 MIME
  白名单、同一处 CSS 净化（`sanitize_plugin_css`）；大小上限：静态 **4 MiB**、插件资源 **256 KiB**；
- `content_type` 必须与扩展名一致，否则拒绝（防「声明 css 实发 html」）；
- 插件 A 只能读自己的 `webui/`（URL 里的 `{pid}` 决定目录，跨插件引用一律 404）；Core 源码 /
  其它插件目录 / `.env` / 数据库都不在可解析的根里。

## 7. 安全测试面（20 类，全部真打 Runtime：真 `PluginManager` + 真插件子进程 + 真管道）

1–5 穿越（`../`、`../../`、绝对路径）/ symlink 逃逸 / 跨插件访问 → `test_static_and_asset_reject_traversal`、
`test_symlink_escape_is_rejected`、`test_cross_plugin_access_is_rejected`；6–16 XSS / HTML 注入 / `on*` 属性注入 /
`javascript:` `data:` `vbscript:` / `iframe` `object` `embed` → `test_plugin_html_is_sanitized`（参数化）；
17–18 模板注入（变量写 `{{ }}`）/ CSS 注入（`@import`、`url(javascript:)`、`expression`）→
`test_template_injection_in_vars_is_escaped`、`test_css_injection_is_stripped`；19 Action 越权 / 写权限被拒 →
`test_action_requires_webui_action_permission`、`test_write_without_permission_is_refused_and_reported`；
20 未启用/未登录访问 + Context/Token 泄露 → `test_disabled_plugin_is_not_reachable`、
`test_context_has_only_declared_keys`、`test_rendered_page_never_contains_host_secrets`；
+ 资源类型 / 大小上限 / 旧 DSL 兼容 → `test_asset_rejects_executable_types`、`test_asset_size_limit`、
`test_legacy_dsl_page_still_works`。

## 8. 与旧 DSL 的关系

旧 DSL 页（无 `file` / `render`）继续可用：`web_ui.entry` hook 返回组件树 → `render_plugin_dsl`，
**降级为 deprecated 兼容层**（[plugin-webui.md](plugin-webui.md) §4）：不删实现、不删测试、不降低安全标准；
新插件一律用真实 HTML。两种形态不允许混用（HTML 页面返回组件树会被明确拒绝，不做隐性回退）。

## 9. 证据与复现命令

| 证据 | 覆盖 |
| :--- | :--- |
| `tests/test_plugin_webui_multilang.py`（**31 条**：5 语言 × 6 类请求 + 汇总） | 五种语言同一套 WebUI 请求真进程：能力声明 / 页面 context / action 保存 / 未知动作错误 / asset / 文件页数据钩子 |
| `tests/test_plugin_webui_protocol.py`（**43 passed**） | 真 Manager + 真插件进程，§7 的 20 类安全问题 |
| `tests/test_plugin_webui_html.py`（**68 passed**）/ `tests/webui/`（103 条收集） | Phase 1 HTML 迁移与安全矩阵（回归）/ HTTP 层：令牌、路由、静态、隔离、动作 |

```bash
python3 -m pytest tests/test_plugin_webui_protocol.py -q   # 引擎侧协议 + 安全
python3 -m pytest tests/test_plugin_webui_multilang.py -q -rs  # 五语言一致性（缺工具链会打印原因）
python3 -m pytest tests/test_plugin_webui_html.py -q       # HTML 迁移回归
```
