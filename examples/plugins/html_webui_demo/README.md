# HTML WebUI 示例插件（html_webui_demo）

任务书第 1 份 §20 要求的"可直接复制运行"的完整示例。

```text
html_webui_demo/
├── manifest.json          # web_ui.pages[].file 声明页面；web_ui.static 声明静态目录
├── main.py                # webui_page(page, action, params, values) → {"vars": {...}}
└── webui/
    ├── pages/
    │   ├── index.html     # 真实 HTML（{{ 占位符 }} 由受控模板渲染）
    │   └── settings.html
    └── static/
        style.css          # 选择器限定在 .flowerie-plugin-webui 之下
```

## 试跑

```bash
# 1) 把整个目录复制到 Flowerie 的插件目录
cp -r examples/plugins/html_webui_demo /path/to/plugins/

# 2) 在 Web UI「插件」页启用插件并批准 web_ui（+ 需要文件上传时再批 web_ui.files）

# 3) 打开
#    http://127.0.0.1:8080/panel/plugins/webui/html_webui_demo/index
```

## 迁移要点（旧 DSL → 真实 HTML）

| | 旧（DSL，仍可用但已 deprecated） | 新（真实 HTML） |
| :--- | :--- | :--- |
| 页面结构 | 插件 `webui_page` 返回 DSL dict | `webui/pages/*.html` 真实文件 |
| 声明 | `web_ui.pages[].id/title` | 增加 `web_ui.pages[].file`（+ `web_ui.static`）|
| 数据 | DSL 组件字段 | `{"vars": {...}}` → `{{ name }}`（自动 HTML escape）|
| 交互 | 表单 POST → DSL 重渲染 | 表单 POST → 同一套 action → HTML 重渲染 |
| 样式 | 无（用主面板样式） | `webui/static/*.css`（服务端净化 + 作用域约定）|
| 安全 | 插件不能输出 HTML | 插件输出 HTML，但过白名单净化 + 路径校验 + 权限边界 |
