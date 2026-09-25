# Plugin WebUI 迁移审计（DSL → 真实 HTML）

- **状态**：Phase 0 审计完成（迁移实施进行中）｜**日期**：2026-09-25
- **任务书**：`/storage/emulated/0/web_ui&sdk.txt` 第 1 份 §3 强制要求"先完整审计、不要直接开始改"；
  本文件就是那次审计的记录，后续所有改动都指向这里。
- 证据等级沿用全项目约定：`[CODE]` 源码行号 / `[DOC]` 文档 / `[FIXTURE]` 夹具 / `[MVP]` / `[UNKNOWN]`。

## 1. 审计方式（可复现）

```bash
grep -rn "webui_page|plugin_dsl|render_plugin_dsl|web_ui\.pages|plugin_webui" --include=*.py --include=*.md src/ tests/ docs/
python3 -m pytest tests/test_plugin_dsl.py tests/test_plugin_webui_integration.py \
    tests/test_plugin_webui_files.py tests/test_plugin_webui_gate.py \
    tests/test_plugin_webui_consistency.py tests/test_plugin_manifest.py -q
```

## 2. 当前**主** WebUI 的真实架构（迁移要对齐的目标形态）

| 组成 | 位置 | 说明 |
| :--- | :--- | :--- |
| 页面模板 | `src/services/webui_render/templates/*.html`（4 个：login / panel / register / register_closed）| **真实 HTML 文件**，改结构不用碰 Python |
| 样式 | `src/services/webui_render/static/panel.css`（1 个）| 真实 CSS 文件，可被浏览器缓存 |
| 资源读取 | `src/services/webui_render/assets.py` | `render_template()` + `_MEIPASS` 兼容（PyInstaller 打包后路径不同）|
| 数据注入 | `src/services/webui_render/pages.py` | 准备数据 + **`{{占位符}}` 替换**（这就是插件要复用的受控模板机制）|
| JS 政策 | 全部模板/静态资源 | **零 `<script>`、无 onclick 内联脚本** → 主 WebUI 仍是 No-JS 架构 `[CODE]` |

**结论（任务书 §9 的"先确认主 WebUI 是否允许 JS"）**：主 WebUI 目前**不允许 JS**，
因此插件 WebUI 也保持 **HTML + CSS + GET/POST**，不引入 JS 沙箱 —— 这条不是猜测，是 grep 结果。

## 3. 旧 Plugin WebUI 完整调用链（逐段）

```text
浏览器 GET/POST /panel/plugins/webui/<pid>/<page>
   │  src/services/web_ui.py:168-169（路由注册，GET + POST）
   ▼
PluginPanelMixin._handle_panel_plugin_webui        src/services/webui_panels/plugin_panel.py:114
   │  ├─ _check_token(request)                      → 未登录跳 /panel
   │  ├─ pid / page 正则校验 [a-z][a-z0-9_-]{0,31}   → 非法即跳回
   │  ├─ POST：读表单 plugin_action / values         → action 默认 "submit"；GET 时 action="get"
   │  ▼
PluginManager.plugin_webui_page(pid, page, action, params, values)   src/plugins/manager.py:184
   │  ├─ 插件存在且 enabled
   │  ├─ approved_permissions 必须含 "web_ui"        → 否则"未批准 web_ui 权限"
   │  ├─ manifest.web_ui.pages 里必须存在该 page id   → 否则"页面不存在"
   │  ├─ runtime hook 调用（manifest.web_ui.entry，默认 webui_page），**超时 4s**
   │  └─ 返回值必须是 dict（DSL），否则"插件返回了非法响应"
   ▼
render_plugin_dsl(dsl)                             src/services/webui_render/plugin_dsl.py:28
   │  组件注册表 _RENDERERS：container/heading/text/stats/alert/button/form/table/…（v1 全集）
   │  安全：先 html.escape 再结构化；URL scheme 白名单（http/https/mailto/相对）；
   │        on* 属性全禁；style 黑名单（expression/url(/javascript/@import/behavior）；嵌套深度 ≤16
   ▼
render_plugin_webui_page(...)                      src/services/webui_render/plugin_webui.py:8
   │  页面壳：breadcrumb + h1 + hint + 插件内多页 tab（零 JS 链接）+ DSL 区域（或错误块）
   ▼
web.Response(text=html, content_type="text/html")  plugin_panel.py:158
```

文件空间（**不经过 DSL**，独立通道）：

```text
POST /panel/plugins/webui/upload/<pid>/<page>   → plugin_panel.py:60  → manager.webui_save_upload
GET  /panel/plugins/webui/files/<pid>/<name>    → plugin_panel.py:95  → manager.webui_read_file
权限：web_ui.files（与 web_ui 分开）；目录：<plugin_dir>/<pid>/webui/（manager.py:125）
校验：文件名正则 ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$、扩展名白名单 10 种、≤10MB、
      图片魔数核验、同名拒绝、路径必须落在插件 webui 根内（manager.py:136-181）
```

## 4. 旧 DSL 引用点清单（14 个文件）

| 类别 | 文件 |
| :--- | :--- |
| 实现 | `src/plugins/manager.py`（plugin_webui_page）、`src/plugins/manifest.py`（_validate_web_ui）、`src/services/web_ui.py`（路由）、`src/services/webui_panels/plugin_panel.py`、`src/services/webui_render/plugin_dsl.py`、`src/services/webui_render/plugin_webui.py` |
| 测试 | `tests/test_plugin_dsl.py`(10)、`tests/test_plugin_webui_integration.py`(4)、`tests/test_plugin_webui_files.py`(6)、`tests/test_plugin_webui_gate.py`(8)、`tests/test_plugin_webui_consistency.py`(5)、`tests/test_code_scanning_redos.py`（引用扫描）|
| 夹具 | `tests/plugins/webui_example/`（manifest.json + plugin.py，`webui_page` 返回 DSL）`[FIXTURE]` |
| 文档 | `docs/plugin-webui.md`、`docs/web-ui.md`、`docs/development.md` |

## 5. 现有安全边界清单（迁移**不能**弱化，只能加强）

| 边界 | 现状 | 迁移后 |
| :--- | :--- | :--- |
| 身份 | `_check_token`（面板登录态）| 不变 |
| 权限 | `web_ui` 批准才能看页面；`web_ui.files` 才能上传/下载 | 不变（**不新增隐式权限**）|
| 参数 | pid/page 正则白名单；action ≤64 字符 | 不变 + page→file 必须来自 manifest 声明 |
| 插件输出 | **只允许 DSL dict**，插件不能输出 HTML/JS | 改为"允许 HTML 文件，但必须过安全边界"（任务书 §8）|
| DSL 渲染 | escape + URL 白名单 + on* 禁用 + style 黑名单 + 深度上限 | 新 HTML 路径必须有同等或更强的净化（`webui_security`）|
| 文件空间 | 目录锁定 + 名称/扩展名/大小/魔数校验 | 不变 |
| 超时 | hook 4s | 不变（HTML 页面不走 hook 时更快）|
| 错误 | 任何异常降级为错误页，绝不把原始输出交给浏览器 | 不变 |

## 6. 现有测试基线（迁移前，必须保持不退化）

```text
tests/test_plugin_dsl.py               10 个用例
tests/test_plugin_webui_integration.py  4
tests/test_plugin_webui_files.py        6
tests/test_plugin_webui_gate.py         8
tests/test_plugin_webui_consistency.py  5
tests/test_plugin_manifest.py          19
实测：102 passed（+ test_plugin_manager 等，本地 stubplug 环境）
```

> 任务书 §19：**不允许删除这些测试来换绿灯**。迁移的做法是"旧 DSL 保留为 deprecated 兼容层"，
> 因此这些用例应当继续全绿 —— 它们同时是兼容层的回归保护。

## 7. 语言无关 Plugin Protocol 的现状（第 2 份任务书的地基）

仓库**已经有一套语言无关协议**，只是没被正式命名：

| 项 | 现状 |
| :--- | :--- |
| 线格式 | **JSON-Lines over stdio**（一行一个 JSON，UTF-8）`[DOC]` docs/plugin-developer-guide.md §31.1 |
| 方法 | `initialize` / `event` / `health` / `shutdown`（四个）|
| 实现 | `src/plugins/runner/python_runner.py`(39KB) + `node_runner.js`(8KB)；`runtime="exec"` |
| 实测覆盖 | `tests/plugins/multilang/` **13 种语言**最小可运行插件，CI 真编译真运行（`test_plugin_multilang.py`）|
| 缺口（第 2 份任务书要求但协议没有）| **Config / Storage / Logging / Context / Permission 查询 / Action 结果回执** |

**因此第 2 份任务书的正确做法**：把现有 exec JSON-Lines **形式化为 Plugin Protocol v1**
（补上述方法 + 版本协商 + 能力矩阵），再写 TS/Go/Rust/Java SDK 作为它的**真实客户端**，
而不是另造一套 stdio/JSON-RPC 或 Mock 一个"跨语言通信"。

## 8. 迁移决策（本轮已定）

| 决策 | 内容 | 理由 |
| :--- | :--- | :--- |
| JS 政策 | 插件 WebUI 保持 **No-JS**（HTML+CSS+GET/POST）| 主 WebUI 无 `<script>`（§2）；任务书 §9 的分支判定 |
| 旧 DSL | **保留为 deprecated 兼容层**，新插件默认 HTML | `tests/plugins/webui_example` 与 5 个测试文件依赖它；任务书 §15 要求在"有依赖"时走兼容层 |
| manifest | `web_ui.pages[]` 增加 `file`（相对 webui 根）；`id/title/pages 上限` 保持不变；`entry` 仅 DSL 兼容层使用 | 任务书 §5；对外契约只增不改 |
| URL | `/panel/plugins/webui/<pid>/<page>` **不变**（page=id，不暴露文件名）| 任务书 §6：不能变成任意文件服务器 |
| 新模块 | `src/plugins/webui_loader.py` / `webui_security.py` / `webui_static.py` + `src/services/webui_panels/plugin_webui_static.py` | 任务书 §12/§17：不要让逻辑全堆进 `PluginPanelMixin`，也不要让 Core 知道 HTML 放哪 |
| 模板 | 复用主 WebUI 的 `{{占位符}}` 机制（`webui_render/assets.render_template` 同款），**不引入 Jinja2/eval** | 任务书 §7：受控变量替换、禁止任意代码执行 |

## 8.5 Phase 1 完成记录（真实数字，2026-09-25）

| 项 | 结果 |
| :--- | :--- |
| 新模块 | `src/plugins/webui_loader.py`（路径安全）、`webui_security.py`（HTML/模板/CSS 净化）、
  `src/services/webui_panels/plugin_webui_static.py`（静态资源 mixin）|
| manifest | `web_ui.pages[].file` + `web_ui.static`（**只做加法**，旧声明零改动）|
| 路由 | `GET /panel/plugins/webui/{pid}/static/{path}`（注册在 `{page}` 之前）；页面路由不变 |
| 旧 DSL | 保留为 deprecated 兼容层；`tests/plugins/webui_example` 与 5 个旧测试文件**原样全绿** |
| 示例 | `examples/plugins/html_webui_demo/`（manifest + main.py + 2 页 HTML + css + README）|
| 测试 | `tests/test_plugin_webui_html.py` **68 用例**（任务书 §18 矩阵超额覆盖）|
| 回归 | 插件/WebUI 子集 203 passed；架构 Gate 74 passed；全量 1271 passed / 19 failed（本地缺依赖基线）/ 37 skipped，**零新增失败** |
| 文档 | `plugin-webui.md` 新增 §3.5（HTML 页面）+ §7/§8 更新；`web-ui.md` / `plugin-developer-guide.md` 加指引 |

实施中抓到的两个真 bug（都有回归用例）：

1. **净化器把整页正文吞掉**：`<meta>` / `<link>` 这类 void 标签被当成「区域抑制」标签，
   抑制计数永不归零 → 之后所有文本被丢。修法：区分「区域抑制」与「只丢标签」两套集合；
2. **表单可提交到外部站点**：`<form action="https://evil">` 原本被放行 → 现在 `action/formaction`
   只允许站内相对路径。
## 9. 后续阶段与任务书门槛的对应

| 阶段 | 产出 | 对应门槛 |
| :--- | :--- | :--- |
| Phase 1 | 新目录规范 + manifest `file` + loader/security/static + HTML 页面路由 + POST action | 任务书 1 §4-§14、§21 架构/安全/功能 |
| Phase 2 | Plugin Protocol v1（形式化 exec 协议 + 补 Config/Storage/Logging/Context）+ TS/Go/Rust/Java SDK + 示例 | 任务书 2 §三-§十五 |
| Phase 3 | WebUI Protocol 进 Plugin Protocol（五语言同一套 page/action/asset/context）| 任务书 3 §三-§十九 |
| 每阶段 | 测试数字 + ADR + 最终报告；CI 三项全绿 | 三份任务书共同的"最终报告必须回答"清单 |

## 10. 不变量（迁移期间必须保持）

1. `manifest.json` 的**既有字段语义不变**（`id/name/version/runtime/entry/permissions`），`web_ui` 只做**加法**；
2. 旧 `webui_page` hook 的插件**继续可用**（走兼容层），其行为与错误文案不变；
3. `web_ui` / `web_ui.files` 两个权限的语义不变，不新增隐式权限；
4. `/panel/plugins/webui/...` 三个 URL 形态不变（页面/上传/下载）；
5. 文件空间校验（名称/扩展名/大小/魔数/穿越）不放松；
6. **Core 不得知道 HTML 文件放在哪里**；插件 WebUI 不得 import OneBot/Milky。
