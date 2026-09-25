# Plugin WebUI Protocol（统一 WebUI 协议 · v1）

> 任务书第 3 份 §三 / §六 / §七 / §八 / §十一 / §十五 / §十七。
> 实现位置：`src/plugins/protocol.py`（方法集与能力组）、`src/plugins/manager.py`（渲染/动作/资源三条通道）、
> `src/plugins/webui_loader.py`（路径校验唯一实现）、`src/plugins/webui_security.py`（HTML/CSS 净化唯一实现）、
> `src/services/webui_panels/`（HTTP 入口）。
> 相关：[plugin-webui.md](plugin-webui.md)（Phase 1：DSL → 真实 HTML）、[plugin-protocol.md](plugin-protocol.md)（线格式）、
> [plugin-webui-migration.md](plugin-webui-migration.md)（迁移审计）。

## 1. 一句话

**WebUI 是 Plugin Protocol 的一部分，不是 Python SDK 的附属功能。**
插件只负责「内容与业务」，Flowerie Runtime 负责「托管、路由、权限、校验、净化、隔离」：

```text
Plugin（任意语言） --JSON-Lines/stdio--> Flowerie Runtime --> 真实 HTML/CSS（面板内）
```

任何实现了 Plugin Protocol v1 的语言，只要声明 `webui.page` / `webui.action` / `webui.asset` 三个能力，
就自动获得与 Python 插件**同等**的页面能力——这条由 `tests/test_plugin_webui_multilang.py` 用五种语言的
真进程钉住（本机缺 go/rustc/javac 时 skip 并打印原因，CI 上全跑）。

## 2. 不新建平行系统

插件 WebUI 复用主 WebUI 的既有架构，不额外起服务、不用 iframe、不引 JS 运行时：

| 复用项 | 位置 | 说明 |
| :--- | :--- | :--- |
| 面板壳 / 导航 | `src/services/webui_render/plugin_webui.py` | 插件页看起来就是面板的一部分 |
| 令牌校验 | 各 HTTP 处理器先过 `_check_token` | 未认证一律重定向回 `/panel` |
| CSP / 安全响应头 | 插件页响应头 | `default-src 'none'` + nosniff + no-referrer + frame-ancestors none |
| 路径校验 | `src/plugins/webui_loader.py` | 页面 / 静态 / 插件资源**共用同一套** |
| 净化 | `src/plugins/webui_security.py` | HTML 白名单、CSS 净化、模板变量 escape |

**No-JS 政策不变**（任务书 §九）：主 WebUI 是 No-JS，插件 WebUI 同样 No-JS ——
静态资源白名单里没有 `.js`，插件资源 MIME 白名单里没有 javascript / text/html / svg。
不允许因为「有 Node.js SDK」就单独放宽安全边界。

## 3. 目录与 manifest（§四/§五）

```text
my-plugin/
├── manifest.json
├── plugin.py            # 或 plugin.ts / main.go / lib.rs / Plugin.java
└── webui/
    ├── pages/
    │   ├── index.html    # 文件页：磁盘上的真实 HTML
    │   └── settings.html
    └── static/
        └── style.css     # 静态资源（磁盘）：css/图片/文本，没有 .js
```

```json
{
  "web_ui": {
    "static": "static",
    "entry": "webui_page",
    "pages": [
      { "id": "index",    "title": "总览",       "file": "pages/index.html" },
      { "id": "settings", "title": "设置",       "file": "pages/settings.html" },
      { "id": "dynamic",  "title": "插件渲染页", "render": "plugin" }
    ]
  }
}
```

三种页面形态（**只做加法**，旧的继续能跑）：

| 形态 | 声明方式 | HTML 来源 | 用途 |
| :--- | :--- | :--- | :--- |
| 文件页 | `pages[].file` | 磁盘 `webui/pages/*.html` | 静态页面 + 受控模板变量（首选） |
| 插件渲染页 | `pages[].render = "plugin"` | 插件进程经 `webui.page` 返回 | 内容依赖插件运行期状态 |
| DSL 页（deprecated） | 既不写 `file` 也不写 `render` | 插件 `web_ui.entry` hook 返回组件树 | 兼容层，**不删**（§十六） |

Manifest 校验（加载前就拒，不等到 HTTP 请求）：

- 页面 id：`^[a-z][a-z0-9_-]{0,31}$`，页面数 ≤ 8，标题 1~64 字符；
- `file` 必须是插件内的相对路径：禁止绝对路径、`..` 段、反斜杠、隐藏段（. 开头）、非 `.html`；
- `file` 与 `render: "plugin"` **互斥**（一个页面只能有一个渲染者）；
- `static` 必须是插件内的相对目录（同样禁止 `..` / 绝对路径）。

## 4. 协议方法（引擎 → 插件，§三）

三个方法属于可选能力组 `webui`，插件在 `initialize` 的 `capabilities` 里声明；**未声明引擎绝不调用**。

| 方法 | 引擎发什么 | 插件回什么 |
| :--- | :--- | :--- |
| `webui.page` | `{"page": {"id","title","description"}, "context": {...}}` | `{"html": "...", "vars": {...}, "message": "..."}` |
| `webui.action` | `{"page": {...}, "action": "save", "form": {...}, "context": {...}}` | 同上，另可带 `config_set` / `storage_set` |
| `webui.asset` | `{"path": "theme.css"}` | `{"content_type": "text/css", "body": "..."}`（二进制用 `base64`） |

返回值的归一化（五语言 SDK 同一实现）：

- 返回**字符串** = `{"html": ...}` 的简写；
- 返回**对象**只透传白名单字段：`html / vars / context / message / content_type / body / base64 /
  config_set / storage_set`，其余字段一律丢弃（不把插件内部对象塞进协议）；
- 返回 `{"ok": false, "error": "..."}` = **操作级错误**（方法认识、这次没成功）；
  未知方法 / 参数非法才是**协议级** `error`。
## 5. HTTP 路由（§八）

| 方法 | 路径 | 通道 |
| :--- | :--- | :--- |
| GET | `/panel/plugins/webui/{pid}/{page}` | 渲染页面（文件页 / 插件渲染页 / DSL 兼容） |
| POST | `/panel/plugins/webui/{pid}/{page}` | 表单动作：`plugin_action` 选动作，其余字段是 form |
| GET | `/panel/plugins/webui/{pid}/static/{path}` | 磁盘静态资源（`webui/static`） |
| GET | `/panel/plugins/webui/{pid}/asset/{path}` | 插件进程生成的资源（`webui.asset`） |

四个入口都先过面板令牌（未认证重定向 `/panel`），再过权限（未批准一律 404，**不泄露插件是否存在**）。
表单只能 `method="post"` 且 CSP 里 `form-action 'self'`：POST 永远不能绕过权限，
也不能「直接调用内部 Python/Node/Go/Rust/Java 对象」——它只能变成一次协议方法调用。

**渲染顺序固定**：先净化（白名单）→ 再替换受控变量（值 escape）→ 再套面板壳。
所以变量里带 `{{ }}` / `<script>` 都只会变成文本，不可能二次求值或注入标记。

## 6. 受控 Context（§七）

引擎发给插件的 `context` **永远只有 6 个顶层键**（`PluginManager.WEBUI_CONTEXT_KEYS`）：

```json
{
  "plugin":  {"id": "example", "name": "示例插件"},
  "page":    {"id": "settings", "title": "设置"},
  "request": {"method": "GET", "action": "get"},
  "user":    {"authenticated": true, "role": "admin"},
  "config":  {},
  "data":    {}
}
```

- `config` 需要 `webui.config.read`：给的是操作员配置（manifest `config.values`，**只读**）；
- `data` 需要 `webui.storage.read`：给的是插件自己的 storage 快照（引擎经 `storage.list` + `storage.get` 取）；
- 未批准就是空对象（不是报错，页面照样能渲染）；
- **绝不**放入面板令牌、会话、环境变量、宿主路径 —— 安全用例逐项断言（Context 泄露 / Token 泄露）。

给 HTML 的**模板变量**是另一条通道（更窄）：引擎固定的 `plugin_id / plugin_name / page_id / page_title /
page_description / message`，加上插件在 `webui.page` / 数据钩子里**显式**返回的 `vars`。
页面里写 `{{ nickname }}`，值一定经过 HTML escape。

## 7. 权限（§十五）

| 权限 | 管什么 | 强制点 | 兼容映射 |
| :--- | :--- | :--- | :--- |
| `webui.view` | 打开页面 / 读静态与动态资源 | `plugin_webui_render` / `plugin_webui_asset` | 老清单的 `web_ui` 等价 |
| `webui.action` | 提交表单动作（POST） | `plugin_webui_render(action != "get")` | 老清单的 `web_ui` 等价 |
| `webui.config.read` | context 里带操作员配置 | `_webui_engine_context` | 无 |
| `webui.config.write` | 动作把配置写回插件覆盖层 | `_webui_apply_writes` → `config.set` | 无 |
| `webui.storage.read` | context 里带插件存储快照 | `_webui_engine_context` | 无 |
| `webui.storage.write` | 动作写插件存储 | `_webui_apply_writes` → `storage.set` | 无 |

判定只有一处实现：`src/plugins/permissions.py::webui_permission_granted`。
写权限被拒 / 写失败**不静默**：面板壳会把告警显示给管理员（`result["warnings"]`）。

## 8. 资源与隔离（§十一）

- 路径校验唯一实现：`webui_loader.validate_relative`（相对路径、白名单扩展名、禁止 `..` / 绝对路径 / 反斜杠 / 隐藏段）
  + `resolve_within`（`realpath` 必须仍在插件目录内 → 防 symlink 逃逸）；
- 静态文件与插件资源是**两条通道、同一套规则**：同一批扩展名白名单（**没有 .js**）、
  同一套 MIME 白名单、同一处 CSS 净化（`sanitize_plugin_css`）、大小上限（静态 4 MiB / 插件资源 256 KiB）；
- `content_type` 必须与扩展名一致，否则拒绝（防「声明 css 实发 html」）；
- 插件 A 只能读自己的 `webui/`：URL 里的 `{pid}` 决定目录，跨插件引用一律 404；
- 插件读不到 Core 源码 / 其它插件目录 / `.env` / 数据库文件 —— 这些路径根本不在可解析的根里。

## 9. 安全测试（§十二：20 类）

全部**真打 Runtime**（真 `PluginManager` + 真插件子进程 + 真管道）：

| # | 攻击面 | 用例 |
| :--- | :--- | :--- |
| 1–2 | `../` / `../../` | `test_static_and_asset_reject_traversal`（参数化 7 种形态） |
| 3 | 绝对路径 | 同上（`/etc/passwd`） |
| 4 | symlink 逃逸 | `test_symlink_escape_is_rejected` |
| 5 | 跨插件文件 | `test_cross_plugin_access_is_rejected` |
| 6 | XSS（`<script>`） | `test_plugin_html_is_sanitized` |
| 7 | HTML 注入 | 同上（`<iframe>` / `<object>` / `<embed>` 参数化） |
| 8 | 属性注入（`onerror` / `onmouseover`） | 同上 |
| 9–11 | `javascript:` / `data:` / `vbscript:` | 同上 |
| 12 | 模板注入 | `test_template_injection_in_vars_is_escaped` |
| 13 | 脚本注入（事件属性 / 内联） | `test_plugin_html_is_sanitized` |
| 14–16 | `iframe` / `object` / `embed` | 同上 |
| 17 | CSS 注入（`@import` / `url(javascript:)` / `expression`） | `test_css_injection_is_stripped` |
| 18 | Action 越权 | `test_action_requires_webui_action_permission` / `test_write_without_permission_is_refused_and_reported` |
| 19 | Session 越权 | `test_disabled_plugin_is_not_reachable`（HTTP 层令牌校验见 `tests/test_webui_plugin_panel.py`） |
| 20 | Context / Token 泄露 | `test_context_has_only_declared_keys` / `test_config_and_storage_are_gated_by_permission` / `test_rendered_page_never_contains_host_secrets` |
| + | 资源类型 / 大小上限 | `test_asset_rejects_executable_types` / `test_asset_size_limit` |
| + | 旧 DSL 兼容不破 | `test_legacy_dsl_page_still_works` / `test_manifest_rejects_conflicting_page_declarations` |

## 10. 多语言一致性（§十三）

`tests/test_plugin_webui_multilang.py` 用**同一套请求**跑五种语言的示例插件真进程：

```text
Register Page（能力声明 + manifest 三页）
Load HTML（webui.page → html + vars）
Load Asset（webui.asset → text/css）
Receive Context（表单 action 里出现引擎给的 plugin.id）
Submit Action（save → vars/message/config_set/storage_set）
Receive Result / Handle Error（未知动作 → 操作级错误）
数据钩子（web_ui.entry → vars）
Shutdown（契约测试已有）
```

**CI 证据**（run [36132261166](https://github.com/lingcat521/Flowerie_bot/actions/runs/36132261166) · commit `42427a0` · 三项工作流全绿）：
五种语言**全部 RUNNABLE 并全绿**，整仓 **1829 passed / 22 skipped**（22 条是缺协议端环境的实机用例）。
本机（仅 python + node）：13 passed / 18 skipped，skip 会打印缺哪个工具链。

CI 装了 go / rustc / javac，所以这五列在 CI 上是**真跑**的；本机缺工具链时打印
`SKIP(本机缺工具链 …)`，绝不当作通过。

## 11. 与旧 DSL 的关系（§十六）

旧 DSL 页面（无 `file` / `render`）继续可用：`web_ui.entry` hook 返回组件树 → `render_plugin_dsl`。
它被**降级为 deprecated 兼容层**（[plugin-webui.md](plugin-webui.md) §4），但：
不删实现、不删测试、不降低安全标准；新插件一律用真实 HTML。
DSL 与 HTML 不允许混用（HTML 页面若返回组件树，引擎明确拒绝并提示，不做隐性回退）。

## 12. 自查命令

```bash
# 引擎侧 WebUI Protocol（真 Manager + 真插件进程，20 类安全用例）
python3 -m pytest tests/test_plugin_webui_protocol.py -q

# 多语言一致性（本机只有 node 时会 skip go/rust/java 并打印原因）
python3 -m pytest tests/test_plugin_webui_multilang.py -q -rs

# Phase 1 的真实 HTML 迁移用例（回归）
python3 -m pytest tests/test_plugin_webui_html.py -q
```
