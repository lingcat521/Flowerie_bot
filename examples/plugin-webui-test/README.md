# examples/plugin-webui-test —— Plugin WebUI 专用测试插件

> 任务书《plugin_to_webui》§4 / §5 / §10 / §11 / §12 / §14 / §16 / §17 的专用测试插件。
> 协议与实现说明：[docs/plugin-webui-protocol.md](../../docs/plugin-webui-protocol.md)、
> [docs/plugin-webui.md](../../docs/plugin-webui.md)、[docs/plugin-webui-test.md](../../docs/plugin-webui-test.md)。

**一句话**：一个零 JavaScript 的三页 WebUI 插件，用真实 HTML 文件 + 受控模板变量 + 表单 POST，
把 Browser → Plugin WebUI → Plugin Runtime → Plugin SDK → Core Router → 另一个插件 → 回到页面
这条链路端到端跑通，并且把失败也显示成结构化错误（不是 500、不是堆栈）。

```text
examples/plugin-webui-test/
├── manifest.json                     # id=plugin_webui_test / runtime=python / entry=main.py / web_ui.pages 三页
├── main.py                           # 插件：webui_page / webui_render / webui_action / webui_asset + 被调方法
└── webui/
    ├── pages/
    │   ├── index.html                # 文件页：插件名/版本/runtime/status/SDK 版本 + WebUI→插件能力自检
    │   ├── settings.html             # 文件页：text / number / checkbox / select / submit + round-trip 证据
    │   └── communication.html        # 插件渲染页的模板（render="plugin" → webui_render 读取它）
    ├── static/
    │   └── style.css                 # 引擎静态通道：/panel/plugins/webui/plugin_webui_test/static/style.css
    └── assets/
        ├── logo.svg                  # 非空静态文件（设计源文件；svg 不在引擎 MIME 白名单内，见「资源通道」）
        └── logo.txt                  # 同一份 logo 的可服务版本：/asset/logo.txt（webui.asset 通道）
```

## 1. manifest

```json
{
  "id": "plugin_webui_test",
  "runtime": "python",
  "entry": "main.py",
  "permissions": ["web_ui", "web_ui.files", "read_message", "plugin.call.*", "plugin.emit"],
  "web_ui": {
    "static": "static",
    "entry": "webui_page",
    "pages": [
      { "id": "index",         "title": "总览",       "file": "pages/index.html" },
      { "id": "settings",      "title": "设置",       "file": "pages/settings.html" },
      { "id": "communication", "title": "跨插件调用", "render": "plugin" }
    ]
  }
}
```

- `web_ui` 等价于 `webui.view` + `webui.action`（兼容映射，见 `src/plugins/permissions.py`）：
  管理员批准 `web_ui` 后页面可打开、表单可提交。
- `plugin.call.*`：允许调用任意插件的方法；`plugin.emit`：允许广播事件。
  撤销 `plugin.call.*` 后页面必须显示 `Status: Failed / Code: PERMISSION_DENIED`（§17，已验证）。
- manifest **没有**声明 `config.values`：操作员配置的键在 `config_get()` 里优先级高于插件覆盖层，
  声明同名键会遮蔽插件保存的值、破坏 §11 的 round-trip（引擎语义，见 runner 的 `_op_config_get`）。

## 2. 三个页面

| 页面 | 形态 | 引擎调用 | 内容 |
| :--- | :--- | :--- | :--- |
| `index` | 文件页 `file` | `webui.page`？不 —— 走 `web_ui.entry` 数据钩子 `webui_page` | Plugin Name / Plugin Version / Runtime / Status / SDK Version / Plugin ID / 权限 / 自检表单 |
| `settings` | 文件页 `file` | 同上 | name(text) / number(number) / enabled(checkbox) / mode(select) / submit + 读回证据 |
| `communication` | `render="plugin"` | `webui.page` → `webui_render` | 最近一次调用的 source/target/method/route/request_id/trace_id/response + 调用表单 + 事件日志 |

四个钩子（引擎按协议调用，插件侧一律不抛异常）：

| 钩子 | 协议方法 | 作用 |
| :--- | :--- | :--- |
| `webui_page(page_id, action, params, values)` | `web_ui.entry` 数据钩子 | 给两个文件页提供模板变量（`{"vars": {...}, "message": "..."}`） |
| `webui_render(page, context)` | `webui.page` | communication 页：读 `webui/pages/communication.html` 模板 + 渲染变量 |
| `webui_action(page, action, form, context)` | `webui.action` | 表单提交：`call` / `emit` / `save` / 自检三动作 |
| `webui_asset(path)` | `webui.asset` | `webui/static` 之外的动态资源：`theme.css` / `info.json` / `logo.txt` |

被调侧（供其它插件调用，`on_startup` 里 `api.plugin.expose`）：
`get_info` / `echo` / `set_config` / `ping` / `slow`（sleep 1.5s，用于超时）/ `boom`（故意抛异常，用于 PLUGIN_ERROR）。
事件侧：`api.plugin.on("*", ...)`——收到的最近 10 条事件记进 storage，显示在 communication 页（§14）。

### 页面 DOM 钩子（浏览器 E2E 用）

| 选择器 | 位置 |
| :--- | :--- |
| `#plugin-name` `#plugin-version` `#plugin-runtime` `#plugin-status` `#plugin-sdk-version` | index |
| `#self-test-form` `#self-test-result` | index（§10 三个动作） |
| `#setting-name` `#setting-number` `#setting-enabled` `#setting-mode` | settings（读回值，round-trip 断言用） |
| `#settings-form` `#config-json` `#storage-json` `#settings-json` | settings |
| `#communication-panel` `#call-form` `#call-status` `#call-code` `#call-request` `#call-response` `#event-log` | communication |

## 3. 数据落盘（§11 config round-trip）

```text
settings 表单 POST（plugin_action=save）
      ↓ webui.action（或未声明 webui.action 能力时的 webui_page 回落，两条路共用同一实现）
   api.config_set({name, number, enabled, mode})   → <plugin>/data/config.json        （插件覆盖层）
   api.storage_set("settings", {values, saved_at}) → <plugin>/data/storage/settings.json（快照）
      ↓ 重新打开 settings 页
   读值优先级：api.config_get() 覆盖层 → storage 快照 → 内置默认值
```

跨插件调用记录也落 storage：`last_call`（最近一次 call/emit，重新打开 communication 页仍可见）、
`events`（最近 10 条收到的事件）。

## 4. 跨插件调用与结构化错误（§12 / §14 / §16 / §17）

表单字段：`target`（插件 id）、`method`（RPC 方法；emit 时是事件名）、`params`（JSON 文本）、
`route`（select：auto / local / core）、`timeout_ms`（100~30000，默认 5000）、
`plugin_action`（`call` 或 `emit`，两个提交按钮）。

- `call` → `api.plugin.call(target, method, params, timeout=..., route=...)`；
- `emit` → `api.plugin.emit(method, params)`，页面显示 `{ok, delivered, failed}`（引擎还会回 `trace_id`）。

失败**永远**是结构化 `{code, message}`，页面渲染成：

```text
Status: Failed
Code: PLUGIN_NOT_FOUND      # 或 PLUGIN_NOT_READY / METHOD_NOT_FOUND / PERMISSION_DENIED /
                            #    INVALID_ARGUMENT / TIMEOUT / CANCELLED / SERIALIZATION_ERROR /
                            #    PLUGIN_ERROR / INTERNAL_ERROR / PLUGIN_UNAVAILABLE / PLUGIN_CALL_LOOP
```

- 不抛异常给引擎（不会变成 500）：错误只是页面上的两个文本行；
- 不显示堆栈 / 绝对路径 / 密钥：`_redact()` 去掉 Traceback 尾巴与绝对路径，本地异常只暴露异常类型名；
- 未知 `plugin_action` 返回协议级操作错误 `{"ok": false, "error": ...}`（引擎渲染错误块，不是 500）。

**request_id / trace_id 的诚实说明**：引擎不会把响应模型透给调用方，插件看不到自己那次调用的
`request_id`/`trace_id`。所以本插件的 `echo`（以及 test.webui 里的对端）会在**返回值里回传**
`request_id`/`trace_id`/`route`/`source`，页面据此显示；对端不回传时页面如实显示「（对端未回传）」——
不编造 id。`route` 显示的是本次请求的策略（`route=core` 时引擎仍走统一协议路径）。
`emit` 的 `trace_id` 由引擎在返回值里给出，属于真实值。

## 5. 资源通道（static / asset）

| 通道 | URL | 来源 | 说明 |
| :--- | :--- | :--- | :--- |
| 静态 | `/panel/plugins/webui/plugin_webui_test/static/style.css` | `webui/static/` 磁盘文件 | `.css` 过 `sanitize_plugin_css`；扩展名白名单 `.css/.png/.jpg/.jpeg/.gif/.webp/.txt/.json/.md/.csv/.ico`（**没有 .js**） |
| 动态 | `.../asset/theme.css` | 插件进程生成（`webui_asset`） | `.css` 通道，颜色随 `settings.mode` 变化 |
| 动态 | `.../asset/info.json` | 插件进程生成 | 二进制通道（`base64` 字段），JSON 内容含 plugin_id/version/runtime/status |
| 动态 | `.../asset/logo.txt` | `webui/assets/logo.txt` | 演示「webui/static 之外的插件文件」经 `webui.asset` 提供 |

**为什么目录里既有 `logo.svg` 又有 `logo.txt`**：`logo.svg` 是任务书 §4 要求的非空静态文件（设计源文件），
但引擎的两条资源通道都**不接受 `.svg`**（静态扩展名白名单没有 svg；`webui.asset` 的 MIME 白名单同样没有 svg ——
No-JS/SVG 政策）。所以页面与测试引用的是可服务的 `logo.txt`；`logo.svg` 只作为源文件保留。
两条通道都做了路径校验（`webui_loader.validate_relative` + `resolve_within`），
`../main.py` / `../../manifest.json` / `/etc/passwd` / `logo.svg` / `theme.js` 一律拒绝（已验证）。

## 6. 已知引擎限制：裸属性占位符会被净化器丢弃

**现象**：文件页里写 `<input type="checkbox" name="x" value="1" {{ x_checked }}>` 或
`<option value="auto" {{ auto_selected }}>`，渲染结果里**既没有 `checked` 也没有占位符**。

**原因**：`src/plugins/manager.py::plugin_webui_render` 的顺序是「**先净化、后替换变量**」，
而 `webui_security._Sanitizer.handle_starttag` 只保留白名单属性：裸占位符 `{{ x_checked }}` 被
`html.parser` 解析成属性名 `{{`（不在白名单）→ 连同后面两个 token 一起丢弃。
变量替换发生在净化之后，此时已经没有那个占位符了，所以既不报错也不生效
（`render_plugin_template` 的 `unresolved` 报告也因此是空的）。

复现（一条命令，不需要起服务）：

```bash
cd <repo> && python3 -c "from src.plugins.webui_security import sanitize_plugin_html as s; print(s('<input type=\"checkbox\" name=\"x\" value=\"1\" {{ x_checked }}>')[0])"
# 实际输出: <input type="checkbox" name="x" value="1">     <- checked 与占位符都没了
```

同一问题也影响仓库自带的 `examples/plugins/html_webui_demo`（它的 `notify_checked` 变量同样不生效）。

**本插件的处理**（不改 Core）：用 class + 显式文本表达状态，四类状态都有机器可读的锚点：

- `#setting-enabled` = `true` / `false`，`#setting-mode` = `auto` / `manual` / `debug`；
- checkbox 的 `class="is-on" / "is-off"`，三个 option 的 `class="is-selected" / "is-unselected"`；
- `#settings-json` 里是归一化后的四个值。

**若要真正修**（建议，未在本轮改动）：在 `webui_security` 的 start-tag 属性处理里把「名字是
`{{` 且后面紧跟 `key }}`」的 token 规范成一个受控标记属性（例如
`data-flowerie-bool="key:checked"`），再在 `render_plugin_template` 里：值为空 → 删掉整个标记属性，
值非空 → 换成白名单内的小写属性名（checked/selected/disabled/readonly/multiple/required）。
属性名来自固定白名单、值只做 escape，安全面不扩大；需要同步补 `tests/test_plugin_webui_html.py` 的用例。

## 7. 本机验证（真 runner / 真 PluginManager / 真 Core Router）

插件本身只有 stdlib 依赖，本机（Termux + Python 3.14）就能全跑：

```bash
# ① manifest 能被 PluginManifest.load 加载（顺带打印三页声明）
cd <repo> && python3 -c "from src.plugins.manifest import PluginManifest as M; m=M.load('examples/plugin-webui-test/manifest.json'); print(m.id, m.runtime, m.entry, m.permissions); print([(p['id'], p.get('file'), p.get('render')) for p in m.web_ui['pages']])"

# ② main.py 能编译
python3 -m py_compile examples/plugin-webui-test/main.py

# ③ 真链路验证（真 PluginManager + 真 runner 子进程 + 真 Core Router + 一个 echo 对端插件）
python3 ~/webui_verify/verify_plugin_webui_test.py
```

`③` 的实际输出（本机 Python 3.14.6，2026-09 实测）：**66 passed / 0 failed**，覆盖
manifest 加载、三页渲染（模板变量全解析）、§10 三个动作、§11 round-trip（含 `data/config.json` 落盘内容断言）、
§12 call（含 source/target/method/route/request_id/trace_id 与 response 里的 `hello`）、
§14 emit（`delivered=1` + 对端真的收到事件）、§16 六种结构化错误（PLUGIN_NOT_FOUND / METHOD_NOT_FOUND /
PLUGIN_ERROR / TIMEOUT / INVALID_ARGUMENT×2，且页面无堆栈与路径）、§17 未批准 `plugin.call.*` →
`PERMISSION_DENIED`、未批准 `web_ui` → 页面不可渲染、§18 静态与动态资源穿越/扩展名拒绝、
§21 XSS 与模板注入不生效、§7 CSS 非空且已净化，另含：**自调用**（`target=plugin_webui_test`，真实 request_id/trace_id 回传）、
**被调侧**（对端插件调用本插件的 `get_info()`）、**未声明 `webui` 能力时文件页 POST 回落 `webui_page` 数据钩子**
（同一份保存逻辑，落盘与回读一致）。

> 该脚本放在仓库外（`~/webui_verify/verify_plugin_webui_test.py`），仓库内的正式用例见
> `tests/webui/`（HTTP + 真 WebUIServer）与 `tests/e2e/`（真浏览器）。

## 8. 挂载

```bash
cp -r examples/plugin-webui-test <Flowerie 插件目录>/plugin_webui_test   # 目录名必须等于插件 id
```

然后在面板「插件」页启用并批准权限（`web_ui` 必须批准，否则页面 404 且不泄露插件是否存在），
访问 `/panel/plugins/webui/plugin_webui_test/index`。
