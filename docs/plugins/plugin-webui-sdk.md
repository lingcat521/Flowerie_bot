# 插件 Web UI SDK

Python、TypeScript、Go、Rust 和 Java 插件可以用同一种组件结构生成管理页。插件决定展示内容和提交后的业务逻辑，Flowerie 负责渲染 HTML、跟随管理面板主题、校验表单和显示字段错误。页面在没有浏览器 JavaScript 的情况下即可操作。

## 声明并注册页面

把下面的字段加入插件的 `manifest.json`，启用插件时批准对应权限。

```json
{
  "permissions": ["webui.view", "webui.action"],
  "web_ui": {
    "pages": [{"id": "settings", "title": "设置", "render": "plugin"}]
  }
}
```

在 `webui.page` 中返回构造器生成的页面对象。在 `webui.action` 中处理已经校验的 `form`。动作可以返回 `message`，也可以返回完整的新 `view` 更新表单和组件。页面返回的值会转义后作为文本显示。现有 HTML、CSS 资源和 DSL 页面可以与这些页面一起注册。

| SDK | 注册入口 | 页面构造入口 | 完整设置页示例 |
| --- | --- | --- | --- |
| Python | `webui_render(page, context)` / `webui_action(page, action, form, context)`，也可用 `api.webui_page/action` 注册 | `from flowerie_sdk import webui`，调用 `webui.page(*blocks, form=...)` | [Python](../../examples/multilang-sdk/python/plugin.py) |
| TypeScript | `plugin.webui.page/action` | `webuiView.page(blocks, form, options)` | [TypeScript](../../examples/multilang-sdk/typescript/src/index.ts) |
| Go | `plugin.WebUI().Page/Action` | `flowerie.WebUIPage(form, blocks...)`，搭配 `WebUIForm`、`WebUIField`、`WebUIChoice`、`WebUITable` 和 `WebUIText` | [Go](../../examples/multilang-sdk/go/main.go) |
| Rust | `plugin.webui().page/action` | `webui_view::page(blocks, Some(form))`，无表单时传 `None` | [Rust](../../examples/multilang-sdk/rust/src/main.rs) |
| Java | `plugin.webUI().page/action` | `FloweriePlugin.WebUIView.page(blocks, form)`，无表单时传 `null` | [Java](../../examples/multilang-sdk/java/src/MinimalPlugin.java) |

Python 插件发布包应包含 `plugin_sdk/flowerie_sdk/` 的副本，放在入口文件同级。一个带状态和表单的页面可以这样写。

```python
from flowerie_sdk import webui

def webui_render(page, context):
    settings = context["data"].get("settings", {})
    return webui.page(
        webui.text("日报设置", "status"),
        form=webui.form("save", [
            webui.field("limit", "每日报告上限", "integer",
                        required=True, value=settings.get("limit", 10)),
            webui.field("enabled", "启用日报", "boolean",
                        value=settings.get("enabled", False)),
        ]),
    )

def webui_action(page, action, form, context):
    return {"message": "已保存", "storage_set": {"settings": form}}
```

这个示例要在清单里再声明并批准 `webui.storage.read` 和 `webui.storage.write`。写入 `config_set` 需要 `webui.config.write`。失败时宿主展示写入反馈。旧权限 `web_ui` 兼容页面访问和提交。

## 表单与组件

每页可声明一个表单，包含 1–32 个字段。字段名与动作名以字母开头，后续可用字母、数字和 `_.-`，总长度最多 64。宿主保留 `plugin_` 前缀及 `get` 动作名。

| 字段类型 | 插件收到的值 |
| --- | --- |
| `text` / `textarea` | 字符串，最多 2,000 字符，可选字段留空时为 `""` |
| `integer` | JSON 整数，范围 ±9,007,199,254,740,991，可选字段留空时为 `null` |
| `boolean` | JSON 布尔值，未勾选为 `false`，必填时必须勾选 |
| `select` | 声明的字符串选项，可选字段留空时为 `""`。最多 50 个 `{value, label}` 选项 |

表单只传给动作声明过的字段。校验失败会保留提交值并显示字段错误，动作处理器仅在校验通过时运行。设置 `required` 可要求非空输入。插件可以在动作内继续进行业务校验，并用 `{ok: false, error: "…"}` 返回失败原因。

页面可放最多 16 个包含文字、状态、日志或表格的组件。文字组件使用 `text`、`status` 或 `log` 类型。表格支持 1–12 列、最多 500 行，每页 1–50 行，默认每页 20 行。分页由宿主对插件返回的行切片。组件内容与表单渲染后的 HTML 总计最多 512 KiB。

直接实现插件协议时，可按如下结构返回 `view`。它沿用 [WebUI 协议 v1](plugin-webui-protocol.md) 的 `webui.page` / `webui.action` 通道。

```json
{
  "view": {
    "blocks": [
      {"type": "table", "columns": ["任务"], "rows": [["日报"], ["周报"]], "page_size": 1}
    ],
    "form": {
      "action": "save",
      "submit": "保存",
      "fields": [{"type": "boolean", "name": "enabled", "label": "启用日报", "value": false}]
    }
  }
}
```
