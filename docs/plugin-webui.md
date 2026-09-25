# Plugin WebUI（插件自有管理控制台）

> 插件可以拥有自己的**管理页面**（多页面/表单/任务/日志/文件）。**零 JavaScript** 是硬红线。
>
> **两种页面形态**（同一套权限与安全边界）：
> 1. **真实 HTML 页面（推荐）**：`webui/pages/*.html` + `webui/static/*.css`，manifest 用 `file` 声明；
>    数据由受控模板变量 `{{ var }}` 注入（自动 escape），交互走 GET/POST —— 见 §3.5；
> 2. **旧 DSL（兼容层，已 deprecated）**：插件 `webui_page` hook 返回结构化 dict，主进程渲染 —— 见 §4。
>
> 二者可共存（逐页选择）；新插件请直接用 HTML。
> 完整可复制示例：[../examples/plugins/html_webui_demo/](../examples/plugins/html_webui_demo/README.md)。
>
> **插件用自己的语言实现页面**（Python / TypeScript / Go / Rust / Java 同一套能力）见
> [plugin-webui-protocol.md](plugin-webui-protocol.md)：`webui.page` / `webui.action` / `webui.asset`
> 三个协议方法 + 6 项 `webui.*` 权限 + 受控 context。

## 0. 一句话原理

**HTML 页面（推荐）**：

```
插件目录                       主进程                          浏览器
 webui/pages/x.html    →  manifest 声明 file → 路径校验 →   ← GET 页面
 webui/static/x.css       webui_loader 读取 → 白名单净化 →      ← CSS/图片（同源）
 webui_page() 可选数据    模板 {{ var }} 取值并 escape  →       → POST action
```

**旧 DSL（兼容层）**：

```
插件(独立进程)                   主进程                   浏览器
 webui_page(page,action,   →  权限检查 → DSL 校验 →    ← 表单 POST/GET（零 JS）
  params,values)              受控渲染(无 JS)  ←
 返回 DSL dict                HTML
```

两条路径的共同点：插件**永远拿不到**主 WebUI 的 token/DOM/其他插件数据；
插件输出（HTML 或 DSL）都经**白名单净化**后才进浏览器，且由 CSP 兜底（`default-src 'none'`）。

## 1. 启用（三步）

1. manifest 声明 `permissions: ["web_ui"]` + `web_ui.pages`（HTML 页面再加 `file`，见 §2）
2. Web UI「插件」页 → 批准 **web_ui** 权限 → 启用
3. 插件 tab 出现 **Plugin WebUI** 入口 → 点击进入

> 文件能力（上传/下载）需额外批准 `web_ui.files`。

## 2. manifest 声明

**HTML 页面（推荐）**：

```json
{
  "id": "music_plugin",
  "permissions": ["web_ui", "web_ui.files"],
  "web_ui": {
    "static": "static",
    "entry": "webui_page",
    "pages": [
      {"id": "overview", "title": "总览", "file": "pages/index.html"},
      {"id": "settings", "title": "设置", "file": "pages/settings.html", "description": "基础设置"}
    ]
  }
}
```

**旧 DSL 页面（兼容层）**：页面条目**不写** `file` 即为 DSL 页，行为与迁移前完全一致。

| 字段 | 规则 |
| :--- | :--- |
| `pages` | ≤8 页；id 小写字母开头/数字/下划线/短横线（≤32）；title 1~64 字符 |
| `pages[].file` | 选填。相对 **插件 webui 根**的路径，必须以 `.html` 结尾；禁止绝对路径、`..`、反斜杠、隐藏段 |
| `static` | 选填，默认 `static`；只能是插件内的相对目录 |
| `entry` | 数据钩子函数名（默认 `webui_page`；HTML 页面可省略——纯静态页面合法） |
| 严格 schema | 未知字段拒绝（manifest 整体同策略）——`file`/`static` 是本次唯一的加法 |

## 3. 数据钩子（可选）

钩子签名两种模式**完全一致**（兼容层不破坏既有插件）：


```python
def webui_page(page: str, action: str, params: dict, values: dict) -> dict | None:
    """page=页面 id；action=get/submit/任意动作（按钮 action 原样传入）；
    params=GET 查询参数；values=表单提交值（不含 plugin_ 前缀）。"""
    if page == "overview":
        return {"type": "container", "kind": "stack", "children": [
            {"type": "stats", "items": [{"label": "任务", "value": "3"}]},
            {"type": "button", "text": "开始任务", "action": "start"},
        ]}
    if page == "settings":
        return {"type": "form", "fields": [
            {"field": "text", "name": "name", "label": "插件名", "value": "音乐"},
            {"field": "checkbox", "name": "auto", "label": "自动同步", "value": "true"},
        ], "buttons": [{"type": "submit", "text": "保存"}]}
    return None   # → 页面显示"插件未返回页面内容"
```

- 超时 4s；异常/非法返回 → 安全错误页（绝不把异常/HTML 交给浏览器）
- **动态性**：每次请求都重新调用 → 插件可展示实时状态/任务进度/日志
- 表单提交 = `action="submit"` + `values`（字段名→值）；按钮 = `action` 传按钮值
- 文件上传后：`params/files`（逗号分隔文件名）+ `msg` 提示

## 3.5 真实 HTML 页面（新，推荐）

目录结构（页面与静态资源都必须落在**自己插件**的目录内）：

```text
my_plugin/
├── manifest.json
├── main.py                 # 可选：数据钩子（没有也能渲染纯静态页面）
└── webui/
    ├── pages/
    │   ├── index.html
    │   └── settings.html
    └── static/
        └── style.css
```

### 模板变量（受控）

- 语法：`{{ name }}`；内置键只有这些：`plugin_id` / `plugin_name` / `page_id` /
  `page_title` / `page_description` / `message`，加上数据钩子返回的 `vars`
- 值**一律 HTML escape**；未知键替换为空并记入渲染报告（页面不会因为缺变量而崩）
- **没有**循环/条件/表达式/函数调用（禁止 `eval`/`exec`/任意对象访问）

```html
<h1>{{ plugin_name }}</h1>
<form method="post" action="/panel/plugins/webui/<pid>/settings">
  <input type="text" name="greeting" value="{{ greeting }}">
  <button type="submit" name="plugin_action" value="save">保存</button>
</form>
```

### 数据钩子（可选）

HTML 页面下钩子返回 **vars / message**（而不是 DSL 组件树）：

```python
return {"vars": {"greeting": "你好"}, "message": "已保存"}
```

- 没有钩子 → 页面照常渲染（**纯静态页面是合法用法**）
- 钩子报错/超时 → 页面仍然渲染，顶部显示「插件数据钩子异常：…」（不静默吞掉）
- 返回带 `type` 的 DSL 组件树 → 被拒绝并提示改用 `vars`（避免隐性回退到旧架构）

### POST / action

| 提交方式 | 行为 |
| :--- | :--- |
| `<button name="plugin_action" value="save">` | action=`save`，其余表单字段进 `values` |
| 不带 `plugin_action` 的 POST | action=`submit` |
| GET | action=`get`，query 进 `params` |

action 只经「插件运行时 → 插件的 `webui_page`」，**不会进 Core**。

### 静态资源

`/panel/plugins/webui/<pid>/static/<path>` → 只读该插件自己的 `webui/static`（`web_ui.static` 可改名）。
允许 `.css` / 图片 / 文本类；**不允许 `.js`**（零 JS 政策）。`.css` 会被净化
（`@import`、外链 `url()`、`expression(` 一律剔除）。

CSS 作用域约定：选择器写在 `.flowerie-plugin-webui` 之下（插件内容都在这个容器里）。

### 安全边界（HTML 路径）

| 面 | 处理 |
| :--- | :--- |
| 路径 | URL 只有 page id；文件名来自 manifest；绝对路径 / `..` / 反斜杠 / 隐藏段 / symlink 逃逸一律拒绝 |
| HTML | 白名单净化：`<script>` `<style>` `on*` `javascript:` `vbscript:` `data:` `<iframe>` `<object>` `<embed>` `<meta>` `<base>` 丢弃 |
| 表单 | `<form action>` 只允许**站内**路径（防止把带登录态的表单 POST 到外部站点）|
| 样式表 | `<link rel=stylesheet>` 只允许**本插件** static 前缀；外链丢弃 |
| 模板 | 值 escape；未知键记报告；不支持表达式 |
| 响应头 | CSP `default-src 'none'` + `nosniff` + `no-referrer`（浏览器侧兜底）|
| 权限 | 与 DSL 页面一致：`web_ui` 才能看页面；`web_ui.files` 才能上传/下载 |

## 4. 旧 DSL 组件（兼容层，已 deprecated）

### 展示
| type | 字段 |
| --- | --- |
| `text` | text |
| `heading` | text, level(1-6) |
| `markdown` | text（受限渲染：无 raw HTML/iframe/可执行 URL） |
| `code` | text |
| `badge` | text, variant(info/ok/warn/err) |
| `alert` | text, variant(同上) |
| `progress` | value(0-100 数值) |
| `image` | src(http/https/相对), alt |
| `divider` | — |
| `stats` | items:[{label,value}] |
| `log` | lines:[string] |
| `table` | headers:[...], rows:[[...] 或 {col:val}] |

### 表单（`field` 组件可单独用 / 包裹在 `form` 内）
| 组件 | 说明 |
| --- | --- |
| `form` | fields + buttons(submit/reset)，action/method |
| `field` | field: text/textarea/number/password/select/checkbox/radio/switch/slider/date/color；name/label/value/options({value,label} 或 "v|标签") |

### 操作
| type | 说明 |
| --- | --- |
| `button` | text + action（提交动作→重渲染） |
| `link` | text + href（http/https/mailto/相对；危险 scheme 拒绝） |

### 容器
| type | 说明 |
| --- | --- |
| `container` | kind: card/section/grid(columns)/stack/columns/accordion/tabs + children |
| `card` | 等价 container(kind=card)（快捷卡片） |
| `tabs` | 服务端分区块 tabs（多页切换用页面导航实现） + children |
| `grid` | columns(1-4) + children |

> 交互（分页/搜索/过滤/排序/条件显示/任务状态刷新）= **每次请求重渲染**：
> 插件把状态放进返回的 DSL（如：`button text="下一页" action="next"`；搜索框+表单提交）。

## 5. 交互模式（全部零 JS）

| 动作 | 实现 |
| --- | --- |
| 表单提交 | POST → `webui_page(page, "submit", params, values)` → 新 DSL |
| 按钮动作 | POST（隐藏 `plugin_action`）→ action 原样传给插件 |
| 导航/刷新/翻页/搜索 | GET 链接/表单（query 参数进 `params`） |
| 上传 | multipart 表单 → 插件空间（扩展名/魔数/大小/名称校验）→ `params/files` |
| 下载 | GET `/panel/plugins/webui/files/{pid}/{name}`（web_ui.files + 穿越防护） |

## 6. 权限（与功能分离）

| 权限 | 能力 |
| --- | --- |
| `web_ui` | 访问/查看/交互插件页面 |
| `web_ui.files` | 上传/下载（仅插件自身 webui 空间） |

**不存在任何 JavaScript 权限**——再高的权限也不能获得 JS 执行能力。

## 7. 安全边界（硬性）

两条路径的硬性边界（**迁移没有放松任何一条**）：

- **DSL 路径**：插件不能输出任意 HTML/`<script>`/事件属性/`javascript:`/`data:`/`vbscript:`/SVG/iframe/mXSS 类负载（渲染器吸收并转义）
- **HTML 路径**：插件可以提供 HTML，但必须过**白名单净化**（同上清单全部丢弃并记报告）+ CSP 兜底；
  模板变量一律 escape；样式表只允许本插件 static；表单只能提交回站内
- 插件**不能**：读取其他插件数据/主进程敏感数据/浏览器 Cookie/修改主面板与全局主题
- 文件**只能**：插件自己的 `webui/` 目录；扩展名+魔数+名称+大小全部白名单校验
- 所有页面访问都要求管理员登录（`_check_token`）+ 插件启用 + 权限批准

## 8. 测试锚点

**HTML 路径（新）**：

- `tests/test_plugin_webui_html.py`（**68 用例**）：manifest 非法路径/穿越/绝对路径/未知字段/页面上限；
  模板变量与 escaping；缺失页面；静态 CSS/图片/穿越/跨插件/敏感文件/`.js`；GET/POST/表单/错误/重渲染；
  15 类 XSS payload + 属性注入 + 模板注入 + CSS 注入；端到端「插件 HTML 里的 `<script>` 不出现在响应里」；
  以及**随仓库发布的示例插件真的能渲染**（`examples/plugins/html_webui_demo/`）

**DSL 兼容层（旧，必须继续全绿）**：

- 渲染器安全全套：`tests/test_plugin_dsl.py`（10 用例：script/on*/javascript/data/vbscript/SVG/iframe/mXSS/属性注入/动态 value/style/深度）
- 集成：`tests/test_plugin_webui_integration.py`（真插件 hook→DSL→渲染/多页/动作/恶意 DSL）
- 文件：`tests/test_plugin_webui_files.py`（上传/下载的穿越/坏名/扩展名/魔数/大小）
- 访问 gate：`tests/test_plugin_webui_gate.py`（未启用/未批准/未声明/未知页/异常降级）
