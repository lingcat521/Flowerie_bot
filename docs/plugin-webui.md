# Plugin WebUI（插件自有管理控制台）

> 插件可以拥有自己的**管理页面**（多页面/tab/表格/表单/任务/日志/文件）——
> **零 JavaScript 绝对红线**：插件描述 UI（结构化 DSL），主进程渲染。
> 快速示例见 [quick-start.md](quick-start.md) 插件部分；组件/协议本文档为唯一权威。

## 0. 一句话原理

```
插件(独立进程)                   主进程                   浏览器
 webui_page(page,action,   →  权限检查 → DSL 校验 →    ← 表单 POST/GET（零 JS）
  params,values)              受控渲染(无 JS)  ←
 返回 DSL dict                HTML
```

插件**绝不输出 HTML/JS**——只返回 JSON DSL；渲染器先安全转义再结构化（详见下文「安全」）。

## 1. 启用（三步）

1. manifest 声明 `permissions: ["web_ui"]` + `web_ui.pages`（见 §2）
2. Web UI「插件」页 → 批准 **web_ui** 权限 → 启用
3. 插件 tab 出现 **Plugin WebUI** 入口 → 点击进入

> 文件能力（上传/下载）需额外批准 `web_ui.files`。

## 2. manifest 声明

```json
{
  "id": "music_plugin",
  "permissions": ["web_ui", "web_ui.files"],
  "web_ui": {
    "entry": "webui_page",
    "pages": [
      {"id": "overview", "title": "总览"},
      {"id": "settings", "title": "设置", "description": "基础设置"}
    ]
  }
}
```

- `pages`：≤8 页；id 小写字母开头/数字/下划线/短横线（≤32）；title 1~64 字符
- `entry`：插件模块内的**页面函数名**（默认 `webui_page`；仅合法函数名）
- **严格 schema**：未知字段拒绝（manifest 整体同策略）

## 3. 页面函数（hook）

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

## 4. DSL 组件（唯一集合）

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

- 插件**不能**：输出任意 HTML/`<script>`/事件属性/`javascript:`/`data:`/`vbscript:`/SVG/iframe/mXSS 类负载（渲染器吸收并转义）
- 插件**不能**：读取其他插件数据/主进程敏感数据/浏览器 Cookie/修改主面板与全局主题
- 文件**只能**：插件自己的 `webui/` 目录；扩展名+魔数+名称+大小全部白名单校验
- 所有页面访问都要求管理员登录（`_check_token`）+ 插件启用 + 权限批准

## 8. 测试锚点

- 渲染器安全全套：`tests/test_plugin_dsl.py`（19 用例：script/on*/javascript/data/vbscript/SVG/iframe/mXSS/属性注入/动态 value/style/深度）
- 集成：`tests/test_plugin_webui_integration.py`（真插件 hook→DSL→渲染/多页/动作/恶意 DSL）
- 文件：`tests/test_plugin_webui_files.py`（11 用例：穿越/坏名/扩展名/魔数/大小）
