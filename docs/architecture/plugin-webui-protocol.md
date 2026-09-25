# ADR-010 Plugin WebUI Protocol（把 WebUI 变成协议的一部分）

**状态**：已实施 · **日期**：2026-09-25 · **对应任务书**：第 3 份（统一 Plugin WebUI SDK）§三–§十九
**前置**：[ADR-008](plugin-webui-html.md)（DSL → 真实 HTML）、[ADR-009](plugin-sdk-protocol.md)（Plugin Protocol v1）

## 要回答的问题

1. 五种语言的插件如何获得**同等**的页面能力，而不是只有 Python 能写页面？
2. 谁负责 HTTP、路由、权限、净化、资源隔离？（插件自己起服务器，还是 Runtime 托管？）
3. 页面与插件之间如何交互，才能既"零 JS"又不牺牲动态能力？

## 决定了什么

**WebUI 是 Plugin Protocol 的一部分**：协议新增三个可选方法（能力组 `webui`），
插件只声明"页面/动作/资源"，Runtime 负责托管：

| 方法 | 方向 | 语义 |
| :--- | :--- | :--- |
| `webui.page` | 引擎 → 插件 | 给受控 context，回 HTML（+ vars/message） |
| `webui.action` | 引擎 → 插件 | 表单提交（action + form + context），回 HTML/vars/message，可带 `config_set` / `storage_set` |
| `webui.asset` | 引擎 → 插件 | 插件进程生成的资源（动态 CSS/图片），MIME 白名单 + 尺寸上限 |

- **三种页面形态**：文件页（`pages[].file`）/ 插件渲染页（`pages[].render = "plugin"`）/
  DSL 兼容页（无 file/render，deprecated 但保留）。
- **六项 `webui.*` 权限**各有强制点：view / action / config.read / config.write / storage.read / storage.write；
  老清单的 `web_ui` 映射为 view + action（行为不变）。
- **受控 context 只有 6 个顶层键**（plugin/page/request/user/config/data），config 与 data 分别受读权限门控；
  绝不放入令牌、会话、环境变量、宿主路径。
- HTTP 入口复用主 WebUI：同一面板壳、同一令牌校验、同一 CSP（`default-src 'none'`），**No-JS 不变**。

### 被否决的方案

| 方案 | 为什么否决 |
| :--- | :--- |
| 插件自己起 HTTP 服务器 / 注册蓝图 | 与任务书 §十 冲突；插件将获得任意路由与响应头能力，权限与隔离无法统一强制 |
| 用一个 iframe 把插件页面嵌进面板 | No-JS 下 iframe 无法通信；且会把"跨插件 DOM/API"风险引进来 |
| 把页面 HTML 交给插件自己净化 | 净化必须由 Runtime 收口（单一实现），否则每个 SDK 都要复刻一遍安全逻辑 |
| 为 WebUI 单独造一套协议（与 Plugin Protocol 平行） | 会导致"再来一次多语言适配"；实测把三个方法挂在既有协议上，五语言只各加了 `webui()` 注册器 |
| 允许 JS（例如给插件一个沙箱运行时） | 与主 WebUI 的 No-JS 硬约束冲突；任务书 §九 明确"不能因为 Node.js SDK 而放宽安全边界" |

## 诚实边界（这次**没有**证明什么）

- 插件资源白名单**不含** svg / 字体 / js：这是 No-JS 的保守选择，不是能力上限的技术证明；
- 20 类安全用例覆盖的是**协议与渲染管线**（真 Manager + 真插件进程）；
  HTTP 路由层的令牌/CSP 断言在 `tests/test_webui_plugin_panel.py`（需 aiohttp，CI 跑）；
- 多语言一致性证明了"五种语言语义一致"，没有证明"任意语言都一致"（后者依赖协议本身，属推论）。

## 实施中踩到的坑

1. **`_manifest_of` 只认注册表原始行**：WebUI 路径传进去的是 `list_plugins()` 的**视图行**
   （没有 `manifest_json`）→ 真实运行时插件页面一律报「manifest 不可解析」。
   Phase 1 单测因为 monkeypatch 掉了 `_manifest_of` 一直没暴露；Phase 3 的"真 Manager + 真插件进程"
   用例当场抓到。现在视图行会回查注册表。
2. **显式 `{"ok": false}` 被归一化成成功**：五语言 SDK 的返回值归一器一开始只认"有内容就算成功"，
   插件返回的操作级错误会被吞掉 —— 现在显式 false 原样回传（并有测试钉住）。
3. **Rust `format!` 的花括号**：要输出引擎的 `{{ var }}` 必须写 `{{{{ var }}}}`，否则模板变量不会被替换。
4. **权限提示语**：把 `web_ui` 改名为 `webui.view` 时，既有用例断言的字样消失 ——
   提示语保留旧名字（"旧权限名 web_ui"），既有断言不用改、语义更清楚。
