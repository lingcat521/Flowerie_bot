# Plugin WebUI（插件自有管理控制台）

> 插件可以拥有自己的**管理页面**（多页 / 表单 / 任务 / 日志 / 文件）。**零 JavaScript** 是硬红线。
> 两种形态共用同一套权限与安全边界：**真实 HTML 页面（推荐）** 与 **旧 DSL（deprecated 兼容层）**，
> 逐页选择、可共存。协议（`webui.page/action/asset` + 受控 context + 6 项权限）见
> [plugin-webui-protocol.md](plugin-webui-protocol.md)；可复制示例见
> [../examples/plugins/html_webui_demo/](../examples/plugins/html_webui_demo/README.md)。

## 1. 启用（三步）

① manifest 声明 `permissions: ["web_ui"]` + `web_ui.pages`（HTML 页再加 `file`，见 §2）；② Web UI
「插件」页批准 **web_ui** → 启用；③ 插件 tab 出现 **Plugin WebUI** 入口 → 点击进入（上传/下载需额外
批准 `web_ui.files`）。原理：插件**永远拿不到**主 WebUI 的 token / DOM / 其它插件数据；插件输出（HTML 或
DSL）都经**白名单净化**后才进浏览器，并由 CSP `default-src 'none'` + `nosniff` + `no-referrer` 兜底。

## 2. manifest 声明

```json
{"id": "music_plugin", "permissions": ["web_ui", "web_ui.files"],
 "web_ui": {"static": "static", "entry": "webui_page", "pages": [
   {"id": "overview", "title": "总览", "file": "pages/index.html"},
   {"id": "settings", "title": "设置", "file": "pages/settings.html", "description": "基础设置"}]}}
```

| 字段 | 规则 |
| :--- | :--- |
| `pages` | ≤8 页；id `^[a-z][a-z0-9_-]{0,31}$`；title 1~64 字符；**不写** `file`/`render` 即旧 DSL 页 |
| `pages[].file` | 相对**插件 webui 根**，必须以 `.html` 结尾；禁绝对路径 / `..` / 反斜杠 / 隐藏段 |
| `pages[].render` | `"file"` 或 `"plugin"`（与 `file` 互斥）；`plugin` = HTML 由插件进程经 `webui.page` 返回 |
| `static` | 选填，默认 `static`；只能是插件内的相对目录 |
| `entry` | 数据钩子函数名（默认 `webui_page`）；纯静态 HTML 页面可省略；未知字段一律拒绝（manifest 同策略） |

## 3. 真实 HTML 页面（推荐）

```text
my_plugin/ ├── manifest.json ├── main.py（可选：数据钩子） └── webui/{pages/index.html, pages/settings.html, static/style.css}
```

- **模板变量**：`{{ name }}`；内置键只有 `plugin_id / plugin_name / page_id / page_title /
  page_description / message`，加上数据钩子返回的 `vars`；值**一律 HTML escape**，未知键替换为空并记入
  渲染报告；**没有**循环/条件/表达式/函数调用（禁 `eval`/`exec`）。
- **数据钩子（可选）**：返回 `{"vars": {...}, "message": "..."}`；没有钩子页面照常渲染（纯静态合法）；
  钩子报错/超时（4s）→ 页面仍渲染、顶部显示「插件数据钩子异常：…」（不静默吞掉）；返回带 `type` 的
  DSL 组件树会被拒绝（提示改用 `vars`，不做隐性回退）。

```html
<h1>{{ plugin_name }}</h1>
<form method="post" action="/panel/plugins/webui/<pid>/settings">
  <input type="text" name="greeting" value="{{ greeting }}">
  <button type="submit" name="plugin_action" value="save">保存</button>
</form>
```

- **POST / action**：`<button name="plugin_action" value="save">` → action=`save`，其余字段进 `values`；
  不带 `plugin_action` 的 POST → action=`submit`；GET → action=`get`，query 进 `params`。
- **静态资源**：`/panel/plugins/webui/<pid>/static/<path>` 只读该插件自己的 `webui/static`；
  允许 `.css` / 图片 / 文本，**不允许 `.js`**；`.css` 会被净化（`@import`、外链 `url()`、
  `expression(` 一律剔除）。CSS 选择器建议写在 `.flowerie-plugin-webui` 之下（插件内容都在该容器里）。

## 4. 旧 DSL 组件（兼容层，已 deprecated）

### 展示 / 表单 / 操作 / 容器（渲染器全集，与 `plugin_dsl._RENDERERS` 双向比对）

| type | 字段 / 说明 |
| :--- | :--- |
| `text` | text |
| `heading` | text, level(1-6) |
| `markdown` | text（受限渲染：无 raw HTML / iframe / 可执行 URL） |
| `code` | text |
| `badge` | text, variant(info/ok/warn/err) |
| `alert` | text, variant(同上) |
| `progress` | value(0-100) |
| `image` | src(http/https/相对), alt |
| `divider` | —（分隔线） |
| `stats` | items:[{label,value}] |
| `log` | lines:[string] |
| `table` | headers:[…], rows:[[…] 或 {col:val}] |
| `form` | fields + buttons(submit/reset), action/method |
| `field` | field: text/textarea/number/password/select/checkbox/radio/switch/slider/date/color；name/label/value/options({value,label} 或 "v|标签") |
| `button` | text + action（提交动作 → 重渲染） |
| `link` | text + href（http/https/mailto/相对；危险 scheme 拒绝） |
| `container` | kind: card/section/grid(columns)/stack/columns/accordion/tabs + children |
| `card` | 等价 container(kind=card) 的快捷写法 |
| `tabs` | 服务端分区块 tabs（多页切换用页面导航实现）+ children |
| `grid` | columns(1-4) + children |

交互（分页/搜索/过滤/排序/条件显示/任务刷新）= **每次请求重渲染**：插件把状态放进返回的 DSL。
组件表与实现由 `tests/test_plugin_webui_consistency.py` 双向比对（文档承诺 = 实现存在）。

## 5. 权限与安全边界

| 权限 | 能力 |
| :--- | :--- |
| `web_ui`（= `webui.view` + `webui.action`） | 访问 / 查看 / 交互插件页面 |
| `web_ui.files` | 上传 / 下载（仅插件自身 webui 空间） |

- **HTML 路径**：白名单净化（`<script>` `on*` `javascript:` `vbscript:` `data:` `<iframe>`
  `<object>` `<embed>` `<meta>` `<base>` 丢弃并记报告）；`<form action>` 只允许**站内**路径，
  `<link rel=stylesheet>` 只允许**本插件** static 前缀，模板变量一律 escape；**DSL 路径**：渲染器吸收并
  转义（script / 事件属性 / 危险 scheme / SVG / iframe / mXSS）；
- 文件**只能**落在插件自己的 `webui/`（名称、扩展名、魔数、大小全白名单校验 + 穿越/symlink 防护）；
  插件**不能**读其它插件数据、主进程敏感数据、浏览器 Cookie 或改主面板/全局主题；访问一律要求管理员
  登录 + 插件启用 + 权限批准，**不存在任何 JavaScript 权限**。

## 6. 证据与复现命令

`tests/test_plugin_webui_html.py`（**68 passed**）：manifest 非法路径/穿越/未知字段/页面上限、模板变量与
escaping、静态 CSS/图片/穿越/跨插件/敏感文件/`.js`、GET/POST/表单/错误/重渲染、15 类 XSS + 属性注入 +
模板注入 + CSS 注入、示例插件真渲染；`test_plugin_webui_multilang.py`（**31 条**）五语言同一套请求真进程；
DSL 兼容层回归 `test_plugin_dsl.py`(10) / `test_plugin_webui_integration.py`(4) /
`test_plugin_webui_files.py`(6) / `test_plugin_webui_gate.py`(8) —— **不删、不降标准**。

```bash
python3 -m pytest tests/test_plugin_webui_html.py tests/test_plugin_webui_consistency.py -q
python3 -m pytest tests/test_plugin_dsl.py tests/test_plugin_webui_integration.py tests/test_plugin_webui_files.py tests/test_plugin_webui_gate.py -q
```
