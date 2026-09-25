# Plugin WebUI 迁移审计（DSL → 真实 HTML）

> **状态：DONE**（Phase 0 审计 + Phase 1 落地，2026-09-25）。使用文档 [plugin-webui.md](plugin-webui.md)、
> 协议 [plugin-webui-protocol.md](plugin-webui-protocol.md)。证据等级：`[CODE]` 源码 / `[DOC]` 文档 /
> `[FIXTURE]` 夹具 / `[MVP]` / `[UNKNOWN]`。

## 1. 审计结论（先审计、后动手）

主 WebUI 模板**零 `<script>`、无内联 onclick** → 插件 WebUI 保持 **No-JS（HTML+CSS+GET/POST）**；仓库
早已有语言无关的 JSON-Lines 协议（13 种语言夹具真跑），因此正确做法是**把它形式化为 Plugin Protocol v1**
并补齐 Config/Storage/Context/Permission 能力，不另造传输。迁移前的调用链：`/panel/plugins/webui/<pid>/<page>` →
`plugin_panel.py`（面板令牌 + pid/page 正则 + 表单字段）→ `PluginManager.plugin_webui_page`（启用 + `web_ui`
权限 + pages 存在 + hook 4s + 必须返回 DSL dict）→ `render_plugin_dsl`（组件表 + escape/URL 白名单/on* 禁用/
style 黑名单/深度 ≤16）→ 面板壳 → HTML；文件空间是独立通道（`.../upload/`、`.../files/`，权限 `web_ui.files`）。

## 2. 迁移决策

| 决策 | 内容 |
| :--- | :--- |
| JS 政策 | 保持 **No-JS**（不存在 JS 权限） |
| 旧 DSL | 保留为 deprecated 兼容层：旧插件与 5 个旧测试文件原样全绿 |
| manifest | `pages[].file` / `pages[].render` + `web_ui.static`，**只做加法** |
| URL | `/panel/plugins/webui/<pid>/<page>` 不变（page=id，不暴露文件名） |
| 新模块 | `webui_loader.py`（路径安全）/ `webui_security.py`（净化）/ `plugin_webui_static.py` |
| 模板 | 复用主 WebUI 的 `{{占位符}}`（先净化、后 escape 替换），**不引入 Jinja2/eval** |

## 3. 不变量

① manifest 既有字段语义不变（`id/name/version/runtime/entry/permissions`），`web_ui` 只做加法；
② 旧 `webui_page` hook 继续可用、行为与错误文案不变，不删测试、不降安全标准；③ `web_ui` /
`web_ui.files` 语义不变、**不新增隐式权限**、URL 形态不变（页面 / 静态资源 / 生成资源 / 上传 / 文件下载）；④ 文件校验（名称/扩展名/大小/魔数/
穿越/symlink）不放松；Core 不知道 HTML 文件放在哪里。

## 4. 证据与复现命令

Phase 1：`tests/test_plugin_webui_html.py`（**68 passed**）、`tests/test_plugin_webui_consistency.py`
（文档组件表 ↔ `plugin_dsl._RENDERERS` 双向比对）、兼容层回归（`test_plugin_dsl.py` 等 5 个文件）。
实施中抓到两个真 bug（均有回归用例）：① 净化器把 `<meta>`/`<link>` 当区域抑制标签 → 吞掉整页正文；
② `<form action="https://evil">` 可外提交 → 现在只允许站内相对路径。

```bash
python3 -m pytest tests/test_plugin_webui_html.py tests/test_plugin_webui_consistency.py -q
```
