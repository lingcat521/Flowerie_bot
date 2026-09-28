# Plugin WebUI 第二阶段测试说明（任务书《plugin_to_webui》）

> 任务书：~`~/storage/emulated/0/plugin_to_webui.txt~`~　·　报告：~`~docs/plugin-webui-report.md~`~
> 一句话：**本轮证明 Browser → Plugin WebUI → Plugin Runtime → Plugin SDK → Core Router → 另一个插件 → 回 Browser
> 这条链路真实可用；QQ/P2P 与本轮无关，缺失环境如实 BLOCKED。**

## 1. 现状审计结论（§3，先查再改）

| 问题 | 结论（有证据）|
| :--- | :--- |
| Plugin WebUI 是 DSL 还是 HTML | 两者都有：HTML 文件页（~`~web_ui.pages[].file~`~）、插件渲染页（~`~render="plugin"~`~，经 ~`~webui.page~`~ 返回 HTML）、旧 DSL 兼容页 |
| 是否已有 HTML 页面 | 有：~`~examples/plugins/html_webui_demo~`~（index + settings 两页 + static CSS）|
| 静态资源如何暴露 | ~`~GET /panel/plugins/webui/{pid}/static/{path}~`~（插件 ~`~webui/static/~`~）+ ~`~.../asset/{path}~`~（~`~webui.asset~`~ 动态资源）|
| 路由如何注册 | ~`~src/services/web_ui.py~`~：~`~GET/POST /panel/plugins/webui/{pid}/{page}~`~、~`~.../upload/{pid}/{page}~`~、~`~.../files/{pid}/{name}~`~ |
| 是否允许 JavaScript | **不允许**（零 JavaScript 策略：~`~src/services/web_ui_assets.py~`~、~`~src/services/webui_render/*~`~ 明确"只输出 HTML/CSS"）→ 本轮交互一律 form POST + 服务端渲染 |
| WebUI 与 Plugin Runtime 如何通信 | 页面渲染走 ~`~webui.page~`~（或 HTML 文件 + 模板变量），提交走 POST → ~`~webui.action~`~ → 插件钩子 |
| 插件间通信 API 如何调用 | 插件钩子里用 SDK 的 ~`~plugin.call / plugin.emit / plugin.on~`~（第 4 份任务书），经 Core Router |
| 五种 SDK 是否已有 WebUI 能力 | 有（~`~webui.page/action/asset~`~ 五语言同名同义，~`~tests/test_plugin_webui_multilang.py~`~ 已有真进程一致性用例）|

本轮**不重复实现**这些既有能力，只补：专用三页测试插件、五语言最小 WebUI 页面、~`~tests/webui/~`~ 与
~`~tests/e2e/~`~ 的真服务器/真浏览器验收、CI 阶段与报告。

## 2. 测试目录

~`~~~~text
examples/plugin-webui-test/          专用 WebUI 测试插件（index / settings / communication 三页）
examples/multilang-sdk/<lang>/       五种语言最小插件的最小 WebUI（同一套 API）
tests/webui/                         真 Web UI 服务器 + 真 PluginManager + 真插件进程（无 Mock Core）
tests/e2e/                           真浏览器 E2E（Playwright；装不上就 BLOCKED BY ENVIRONMENT）
~~~~`~

## 3. 安全边界（本轮**必须**覆盖）

路径穿越（~`~../~`~、~`~../../~`~、~`~/etc/passwd~`~、编码/双重编码、绝对路径、符号链接）、跨插件文件隔离、
Secret 泄漏（HTML/CSS/JSON/错误响应里不得出现 ~`~TEST_SECRET/TEST_API_KEY/TEST_TOKEN~`~）、XSS/HTML 注入
（~`~<script>alert(1)</script>~`~、~`~<img src=x onerror=...>~`~）、模板注入、多插件隔离（页面/CSS/config/API/session/文件/plugin id）。

## 4. 环境与阻塞口径

- 本机（Termux 沙箱）：Python 真跑；Go/Rust/JDK 缺失；浏览器（Playwright/Chromium）装不上 → 相关项 **BLOCKED BY ENVIRONMENT**。
- CI（Ubuntu）：五种语言工具链齐全，WebUI HTTP/安全/隔离真跑；浏览器 E2E 由 CI 安装 Chromium 后真跑。
- **QQ/P2P = BLOCKED BY ENVIRONMENT**（无真实 QQ/NapCat/OneBot P2P 环境），且与本轮 WebUI 结论**分开陈述**。

