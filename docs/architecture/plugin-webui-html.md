# ADR-008：插件 WebUI —— 从 DSL 迁移到真实 HTML

- **状态**：已实施（Phase 1 核心）｜**日期**：2026-09-25｜**对应任务书**：`web_ui&sdk.txt` 第 1 份（§1–§24）
- 审计底稿：[../plugin-webui-migration.md](../plugin-webui-migration.md)｜使用文档：[../plugin-webui.md](../plugin-webui.md)

## 要回答的问题

主 WebUI 已经完成"真实 HTML/CSS 文件"的架构升级（`webui_render/templates/*.html` +
`static/panel.css` + `render_template()` 的 `{{占位符}}` 替换），但插件 WebUI 仍停留在：

```text
插件 webui_page() → Python Dict DSL → plugin_dsl.render_plugin_dsl() → Python 拼 HTML → 浏览器
```

任务书要求把插件 WebUI 也迁到真实 HTML 文件体系，**同时**保持外部插件 API 尽量稳定、
不许把安全边界换成"任意文件服务器"。

## 决策

### 1. 两种页面形态并存，逐页选择（DSL 降级为 deprecated 兼容层）

| 形态 | 声明 | 渲染 | 定位 |
| :--- | :--- | :--- | :--- |
| **HTML 页面（推荐）** | `web_ui.pages[].file` + `web_ui.static` | loader 读文件 → 净化 → 模板变量 → 面板壳 | 新插件默认 |
| **DSL 页面（兼容层）** | 不写 `file`（旧写法） | 插件 hook 返回 dict → `render_plugin_dsl` | 已 deprecated，**不删** |

保留兼容层不是偷懒：仓库里有真实依赖（`tests/plugins/webui_example` 夹具 + 5 个测试文件 +
三份文档教旧 API），任务书 §15 要求"有依赖就走兼容层"，并禁止"代码删了但文档还教旧 API"。

### 2. URL 里永远只有 **page id**，文件名只能来自 manifest

```text
GET /panel/plugins/webui/<pid>/<page_id>      ← page_id 是 manifest 里的声明
        ↓
manifest.web_ui.pages[].file（相对路径，静态校验）
        ↓
webui_loader：禁绝对路径/../反斜杠/隐藏段 → realpath 必须落在插件 webui 根内 → 读文件
```

**被否决的做法**：`/panel/plugins/webui/<pid>/<任意路径>` → `open()`。那等于把插件目录
（含 `main.py`、`.env`、其他插件）变成可下载的文件服务器 —— 任务书 §6 明令禁止。

### 3. 安全边界从"插件不能输出 HTML"改成"插件 HTML 必须过净化"

- **白名单净化**（`webui_security.sanitize_plugin_html`，基于标准库 `html.parser`）：
  只保留结构/表单/表格/文本类标签；`script/style/iframe/object/embed/meta/base/template/svg` 丢弃；
  **任何 `on*` 事件属性丢弃**；URL 属性只允许 http(s)/mailto/站内相对路径，
  `javascript:`/`vbscript:`/`data:` 一律拒绝；`style` 走旧 DSL 同款黑名单；
  **表单 `action` 只允许站内**（防把带登录态的表单 POST 到外部站点）；
  `<link rel=stylesheet>` 只允许**本插件** static 前缀。**丢弃项全部进报告**（测试与运维可见）。
- **顺序**：**先净化、后替换变量** —— 变量值由模板渲染器 escape，无法借替换注入标记。
- **浏览器侧兜底**：插件页面响应带 CSP `default-src 'none'; form-action 'self'; base-uri 'none'` +
  `nosniff` + `no-referrer`。
- **模板**：只支持扁平 `{{ key }}`（内置键 + 插件 `vars`）；无循环/条件/表达式/函数调用；
  **不用 Jinja2、不用 eval/exec**（任务书 §7）。

### 4. 零 JS 政策不因迁移而放宽

审计用 grep 确认主 WebUI 的模板与静态里**没有任何 `<script>`** → 按任务书 §9 的分支判定，
插件 WebUI 保持 **HTML + CSS + GET/POST**：静态资源扩展名白名单**不含 `.js`**，
CSS 里的 `@import`/外链 `url()`/`expression(` 被剔除。

### 5. 静态资源独立通道 + 独立模块

`GET /panel/plugins/webui/{pid}/static/{path}`（注册在 `{page}` 路由之前）→ 新 mixin
`PluginWebUIStaticMixin`（任务书 §12/§17：不要让逻辑全堆进 `PluginPanelMixin`，也不要让 Core
知道 HTML 放在哪里）。权限与页面一致：`web_ui` + 插件启用，未批准返回 404（不泄露存在性）。

## 被否决的方案（完整）

| 方案 | 否决理由 |
| :--- | :--- |
| URL 路径直接 open() | 变成任意文件服务器，插件源码/`.env`/跨插件全可读（§6 明禁）|
| 允许插件 JS + 沙箱 | 主 WebUI 是 No-JS；为插件单独放宽安全边界违反 §9"不要凭空改变现有安全策略"|
| 立刻删除旧 DSL | 夹具/测试/文档都有依赖；§15 要求先评估再兼容 |
| 用 Jinja2 做模板 | 任意属性访问与代码执行面；§7 要求"受控变量替换" |
| 先替换变量再净化 | 变量值可能夹带标记进入净化器之前的结构位置，风险更高 |
| 让 Core/面板知道 HTML 文件路径 | 违反 §17 的架构边界（Core 不应知道 WebUI 文件布局）|

## 诚实边界（本轮**没有**做到的）

| 未做到 | 说明 |
| :--- | :--- |
| CSS 选择器不重写 | 插件 CSS 仍按普通样式表加载（会参与全局层叠）。缓解：插件内容统一包在 `.flowerie-plugin-webui`，文档要求选择器写在该类之下；**没有**做选择器自动加前缀（记录为已知限制）|
| 净化器不是浏览器级解析器 | 基于 stdlib `HTMLParser` 的白名单，畸形 HTML 可能被规范化得"不好看"，但不会产出可执行标记；已用 15 类 payload 回归 |
| 无真实浏览器人工验证 | 自动化测试打在 manager/HTTP 层；`tests/acceptance_check.py` 会起真实面板做黑盒检查，但**未**在真实浏览器里点过插件页面 |
| CSS 净化残留 | 剔除 `expression(`/`url(...)` 后可能留下孤立的 `)`（无效 CSS，浏览器忽略）；纯观感问题 |

## 证据（Phase 1 核心）

```text
新增测试 tests/test_plugin_webui_html.py        68 passed（任务书 §18 矩阵全覆盖）
插件/WebUI 回归子集                              203 passed
架构 Gate（含新文件入 aiohttp 白名单）             74 passed
全量                                            1271 passed / 19 failed（本地缺依赖基线）/ 37 skipped（零新增失败）
旧 DSL 用例（dsl/integration/files/gate/consistency） 原样全绿（未删未改语义）
```

## 实施中抓到的两个真 bug（写进来给后来人）

1. **净化器把整页正文吞掉**：把 `<meta>`/`<link>` 这类 **void 标签**也当成"区域抑制"标签
   （用于 `<script>` 这类要连内容一起丢的标签），抑制计数永不归零 → 之后的正文全被丢弃。
   修法：区分 `SUPPRESS_TAGS`（成对、连内容丢）与 `DROP_TAGS`（只丢标签）。
   这个 bug 是被"**随仓库示例插件真的能渲染**"那条用例抓到的 —— 单纯的 payload 用例照不出来。
2. **表单可以提交到外部站点**：`<form action="https://evil">` 原本被 URL 白名单放行
   （http/https 合法）→ 现在 `action/formaction` 只接受站内相对路径。
