# Plugin 三份任务书 · 最终报告（真实数字）

> 三份任务书都在 `/storage/emulated/0/web_ui&sdk.txt` 里：**① 插件 WebUI 从 DSL 迁移到真实 HTML** ·
> **② 多语言 Plugin SDK（Plugin Protocol v1）** · **③ 统一 Plugin WebUI SDK（WebUI Protocol）**。
> 本报告逐条回答每份任务书"最终报告必须回答"的清单；所有数字都能用文末命令或 CI 记录复核。
>
> **证据基线**：commit `42427a0` · CI run [36132261166](https://github.com/lingcat521/Flowerie_bot/actions/runs/36132261166)
> —— 三项工作流（`CI` / `Acceptance` / `Push on main`）**全绿**，整仓 **1829 passed / 22 skipped**
> （22 条全是缺协议端环境的实机集成用例：按任务书要求 skip 并打印原因，**不当作通过**）。
> 下文所有数字都是该基线的历史证据；**当前状态（v2.3.0）**：整仓 **2288 passed / 39 skipped**、`tests/sdk` 46、`tests/webui` 102、`tests/e2e` 21（真浏览器）。

## 0. 一页速览

| 项 | 值 |
| :--- | :--- |
| Plugin Protocol | v1 · JSON-Lines over stdio · 必需 4 方法 + 可选 11 方法（8 核心 + 3 WebUI） |
| 语言 SDK | Python（runner 内置）· TypeScript · Go · Rust · Java，**能力集合完全相等**（相等断言钉住） |
| 插件 WebUI | 真实 HTML/CSS（No-JS）· 三种页面形态（文件页 / 插件渲染页 / DSL 兼容页） |
| WebUI Protocol | `webui.page` / `webui.action` / `webui.asset` + 6 项 `webui.*` 权限 + 受控 context |
| 迁移状态 | `OLD_PLUGIN_WEBUI = DSL`（deprecated 兼容层，保留不删）· `NEW_PLUGIN_WEBUI = REAL_HTML` · `MIGRATION_STATUS = DONE`（第 1 份 Phase 1 落地；第 3 份把能力协议化给五种语言） |
| 安全回归 | `SECURITY_TESTS = 20/20` 类攻击面（**111 条用例全绿**） |
| 本轮改动规模 | `6aaa424^..HEAD`：**87 files changed, 9280 insertions(+), 54 deletions(-)** |
| 插件相关测试（收集数） | 267 条（详见 §1.3），CI 全绿 |
| CI | 三项全绿 · **1829 passed / 22 skipped**（`REGRESSION = 0 new failures`）· ruff 全绿 |

---

# 第一部分：插件 WebUI 从 DSL 迁移到真实 HTML

> 实现：[plugin-webui.md](plugin-webui.md) · 审计：[plugin-webui-migration.md](plugin-webui-migration.md) ·
> ADR：[architecture/plugin-webui-html.md](architecture/plugin-webui-html.md) · 第 3 份把它协议化的部分见 [plugin-webui-protocol.md](plugin-webui-protocol.md)。

## 1.1 §21 定量验收门槛（逐项）

| 门槛 | 结果 | 证据 |
| :--- | :--- | :--- |
| HTML WebUI 页面加载 100% | ✅ | `tests/test_plugin_webui_html.py`（68 条）+ 五个语言示例的页面 |
| 旧 DSL 新路径引用 0 | ✅ | `grep -rn render_plugin_dsl src/`：只有兼容分支（`mode == "dsl"`）引用 |
| Core → Plugin WebUI 直接耦合 0 | ✅ | `src/services/webui_panels/` 对插件子系统的 import 只有 1 处异常类型（`webui_loader.PluginWebuiPathError`），不碰插件实现/runner/协议内部 |
| OneBot/Milky import 0 | ✅ | `grep -rn 'onebot\|milky' src/plugins/runner src/plugins/protocol.py sdk/` → **0 命中** |
| 跨插件文件访问 0 | ✅ | `test_cross_plugin_access_is_rejected` / `test_static_and_asset_reject_traversal` |
| 路径穿越测试 100% PASS | ✅ | 7 种形态参数化 + symlink 逃逸 + 绝对路径（唯一实现 `webui_loader`） |
| XSS / HTML 注入 100% PASS | ✅ | 12 种负载参数化（script/事件属性/iframe/object/embed/scheme/表单外链） |
| 模板注入 100% PASS | ✅ | `test_template_injection_in_vars_is_escaped`（先净化、后替换，值 escape） |
| 静态资源越界 100% PASS | ✅ | 静态资源与插件资源**同一套**路径/白名单/净化规则 |
| 权限绕过 100% PASS | ✅ | `webui.*` 六项权限各有强制点；写权限被拒会如实告警 |
| HTML 页面 / 多页面 / CSS / 静态资源 | ✅ | 文件页 + 插件渲染页 + 三页 manifest（首页/设置/插件渲染页）|
| GET / POST / 动态重新渲染 | ✅ | 表单 `plugin_action` → 协议动作 → 重新渲染（五语言同一语义）|
| 文件上传/下载 100% PASS | ✅ | `web_ui.files` 通道（`tests/test_plugin_webui_files.py` 11 条 + CI 上面板用例 9 条）|
| 新增非预期失败 0 | ✅ | CI 1829 passed / 22 skipped（22 条全是实机 skip，附原因）|
| CI required checks 100% PASS | ✅ | 三项工作流全绿 |

## 1.2 §23 必答 20 问（逐条）

1. **主 WebUI 的真实 HTML 架构**：aiohttp + 服务端渲染 HTML（**No-JS**）+ 面板壳 mixin 拆分 + CSP/安全头 + 令牌认证；插件页与主页面共用同一套壳与静态资源架构。
2. **旧 Plugin WebUI 的 DSL 调用链**：`GET/POST /panel/plugins/webui/{pid}/{page}` → `PluginPanelMixin` → `PluginManager.plugin_webui_page()` → runtime `hook`（插件 `webui_page(page_id, action, params, values)`）→ DSL dict → `render_plugin_dsl()` → 套壳。
3. **新 Plugin WebUI 的调用链**：同一入口 → `PluginManager.plugin_webui_render()` → 三种形态之一（`file` / `render="plugin"` 走 `webui.page` / 旧 DSL）→ `webui_loader` 校验路径 → `webui_security` 净化 HTML → `render_plugin_template` 替换受控变量 → 套壳（+ CSP）。
4. **manifest 如何变化**：`web_ui.pages[].file`（HTML 页面）、`web_ui.static`（静态目录）、新增 `pages[].render = "plugin"`（插件渲染页）；全部是**加法**，未知字段仍然拒绝。
5. **HTML 页面如何发现**：URL 里的 page id → manifest 声明的页面 → `validate_relative(file, PAGE_EXTS)` → `realpath` 必须落在插件 `webui/` 根内 → 读文件（**不是**把 URL 当文件名）。
6. **HTML 模板变量如何工作**：`{{ var }}`；可用键是受控集合（`plugin_id / plugin_name / page_id / page_title / page_description / message` + 插件**显式**返回的 `vars`）；顺序固定为「先净化 → 后替换」，替换值一律 HTML escape。
7. **POST/action 如何工作**：表单 `method="post"` + `plugin_action` → 同一路由 → 令牌 + 权限（`webui.action`）→ 协议 `webui.action`（或旧数据钩子）→ 用返回的 vars/message 重新渲染。
8. **CSS/static 如何加载**：`GET /panel/plugins/webui/{pid}/static/{path}` → 扩展名白名单（**没有 .js**）→ `.css` 过 `sanitize_plugin_css`（禁 @import / 外链 url / expression）→ nosniff + no-store。
9. **文件上传/下载如何隔离**：`web_ui.files` 权限 + 只能落在插件自己的 `webui/` 目录 + 扩展名白名单 + 大小上限；下载强制 `attachment`。
10. **如何防止路径穿越**：路径校验只有一个实现（`webui_loader.validate_relative / resolve_within`）：拒绝绝对路径、`..` 段、反斜杠、NUL、隐藏段、非白名单扩展名；`realpath` 必须仍在插件根内（防 symlink 逃逸）。
11. **如何防止 HTML/XSS 注入**：白名单净化（stdlib `html.parser`）：剔除 script/iframe/object/embed/事件属性/危险 scheme/外链表单；CSP `default-src 'none'` + nosniff + no-referrer 做纵深防御。
12. **JS 策略**：**No-JS 不变**（与主 WebUI 一致）；静态资源与插件资源白名单都不含 `.js`，MIME 白名单不含 javascript / text/html / svg。
13. **旧 DSL 是否保留**：**保留**（任务书第 1 份 §15 要求降级为 deprecated 而非删除）。
14. **兼容层在哪里**：manifest 里既不写 `file` 也不写 `render` 的页面 → `PluginManager.plugin_webui_page()` → `src/services/webui_render/plugin_dsl.py`；面板壳以 `mode="dsl"` 渲染。
15. **为什么不能安全删除**：既有插件仍在用；任务书明确要求保留兼容期 —— 本轮**不删**。
16. **修改了多少文件**：第 1 份区间 `6aaa424^..8e73dc0^` = **23 files, +1760/−39**；三份任务书合计 `6aaa424^..HEAD` = **87 files, +9280/−54**。
17. **新增多少测试**：新增 3 个测试文件（`test_plugin_webui_html.py` 68 · `test_plugin_webui_protocol.py` 43 · `test_plugin_webui_multilang.py` 31）等；插件相关测试收集数合计 **267 条**（§1.3）。
18. **安全测试通过多少**：**111/111**（`test_plugin_webui_protocol.py` 43 条 + `test_plugin_webui_html.py` 68 条全绿，覆盖 20 类攻击面）。
19. **回归测试通过多少**：CI **1829 passed / 22 skipped**（22 条实机用例缺环境，skip 原因打印；既有插件/核心测试 0 新失败）。
20. **CI 是否全部通过**：**是** —— run 36132261166，`CI` / `Acceptance` / `Push on main` 三项全绿。

## 1.3 测试清单（基线 `42427a0` 收集数，可复现）

| 测试文件 | 条数 | 说明 |
| :--- | :--- | :--- |
| `tests/test_plugin_webui_html.py` | 68 | 第 1 份：manifest/HTML/模板/静态/动作/安全矩阵 |
| `tests/test_plugin_webui_protocol.py` | 43 | 第 3 份：真 Manager + 真插件进程，20 类安全 |
| `tests/test_plugin_webui_multilang.py` | 31 | 第 3 份：五语言 WebUI 一致性 |
| `tests/test_plugin_sdk_contract.py` | 53 | 第 2 份：五语言契约（50 条参数化 + 3 条静态度量）|
| `tests/test_plugin_protocol.py` | 25 | 协议本身（常量一致性 + 真子进程 + 引擎侧 op）|
| `tests/test_plugin_webui_files.py` | 11 | 文件通道（上传/下载/越界）|
| `tests/test_plugin_webui_gate.py` | 8 | 访问闸门（未启用/未批准/未声明/异常降级）|
| `tests/test_plugin_webui_consistency.py` | 5 | 文档 ↔ 渲染器 ↔ 权限 一致性 |
| `tests/test_plugin_webui_integration.py` | 4 | 真插件 → DSL → 渲染集成 |
| `tests/test_plugin_dsl.py` | 19 | 兼容层回归（DSL 不删、不退化）|
| `tests/test_webui_plugin_panel.py` | 9 | HTTP 面板（需 aiohttp：CI 跑）|
---

# 第二部分：多语言 Plugin SDK（Plugin Protocol v1）

> 协议：[plugin-protocol.md](plugin-protocol.md) · 指南：[plugin-sdk.md](plugin-sdk.md) ·
> 矩阵：[plugin-sdk-capabilities.md](plugin-sdk-capabilities.md) · 单语言：typescript / go / rust / java 各一份 ·
> ADR：[architecture/plugin-sdk-protocol.md](architecture/plugin-sdk-protocol.md)。

## 2.1 §十四 验收指标（逐项）

| 指标 | 结果 | 证据 |
| :--- | :--- | :--- |
| Plugin Protocol 有正式定义 1/1 | ✅ | `docs/plugin-protocol.md` + `src/plugins/protocol.py`（唯一事实来源，常量与 runner 逐项比对）|
| Python SDK 兼容 100% | ✅ | runner 的既有 `PluginApi` 全部保留；新增 storage/config/permission/context 与其它语言同名 API；既有插件用例 0 回归 |
| TypeScript SDK 可运行 | ✅ | CI 真跑（Node 20 → tsc 路径 + shim；Node ≥22.6 → 直接执行 .ts）|
| Go SDK 可运行 | ✅ | CI 真编译真跑（`go build`）|
| Rust SDK 可运行 | ✅ | CI 真编译真跑（`rustc --edition 2021`，零 crate）|
| Java SDK 可运行 | ✅ | CI 真编译真跑（`javac` + `java`）|
| Protocol Contract Tests 100% | ✅ | `test_plugin_protocol.py` 25 条全绿 |
| Cross-language Tests 100% | ✅ | `test_plugin_sdk_contract.py` CI 上 53 条全绿（五语言真进程）|
| Permission Tests 100% | ✅ | `permission.check` 反向通道 + 引擎侧权限门 + WebUI 六项权限 |
| Existing Plugin Regression 0 new failures | ✅ | CI 1829 passed / 22 skipped |
| Core Protocol Coupling 0 | ✅ | SDK/runner 不 import 任何协议端实现（OneBot/Milky 命中 0）|
| OneBot/Milky imports in SDK 0 | ✅ | `grep` 实测 0 |
| CI 全部通过 | ✅ | run 36132261166 三项全绿 |

## 2.2 最终报告 20 问（逐条）

1. **Plugin Protocol 放在哪里**：`src/plugins/protocol.py`（代码级单一事实来源）+ `docs/plugin-protocol.md`（规范）；runner 内联一份常量并由 `test_runner_inlined_constants_match_engine_module` 逐项比对。
2. **当前版本**：`PROTOCOL_VERSION = "1"`（`api_version = "1"`）；主版本不同 → 引擎拒绝启动（不猜兼容）。
3. **通信方式**：**JSON-Lines over stdio**（一行一个 JSON、UTF-8、写完立即 flush；stdout 只放协议，日志走 stderr）。
4. **为什么选它**：先审计了仓库既有的 exec runner（13 种语言最小插件在 CI 真跑），它已经是"任何语言都能实现"的事实协议；换成 gRPC/HTTP 会引入运行时依赖、端口与生命周期管理、以及"哪来的 HTTP 服务器"这类与任务书 §十 相冲突的问题。JSON-Lines 的取舍写在 [plugin-protocol.md](plugin-protocol.md) §1。
5. **Python SDK 是否保持兼容**：是。runner 既有钩子（`on_message` / `webui_page` / `health_check` …）与 `PluginApi` 的 160+ 方法一个没删，只做加法。
6. **TypeScript SDK 完成度**：`SUPPORTED`（14 项可选能力 + 具名钩子 + WebUI 三通道；零 npm 依赖，含无 `@types/node` 的 tsc 路径）。
7. **Go SDK 完成度**：`SUPPORTED`（零第三方依赖；读/处理分离的运行时模型修掉了反向请求自锁）。
8. **Rust SDK 完成度**：`SUPPORTED`（零 crate；自带极简 JSON 编解码）。
9. **Java SDK 完成度**：`SUPPORTED`（零第三方依赖，只用 JDK；自带极简 JSON）。
10. **Capability Matrix**：[plugin-sdk-capabilities.md](plugin-sdk-capabilities.md) —— 逐能力四态（SUPPORTED/PARTIAL/UNSUPPORTED/UNKNOWN），每个 SUPPORTED 都能指到绿色命令或 CI run。
11. **跨语言 Contract Tests**：`test_plugin_sdk_contract.py` 53 条 + `test_plugin_webui_multilang.py` 31 条，全部真进程 + 真管道（**不 mock 跨语言通信**）。
12. **Permission Tests**：`test_plugin_permissions.py` + 契约测试里的 `permission.check` 反向通道 + WebUI 六项权限用例。
13. **是否修改 Core**：没有改消息主链路/协议端适配；只新增插件子系统内的协议层与 WebUI 通道。
14. **是否修改现有插件**：否（旧 manifest 与旧钩子原样可用；`web_ui` 权限被映射为 `webui.view + webui.action`，行为不变）。
15. **是否存在 Breaking Change**：无。协议只做加法（可选 8 → 14 项，未声明的能力引擎不会调用）；旧 DSL 页面保留。
16. **CI 状态**：三项全绿（run 36132261166）。
17. **新增测试数量**：新增 53（契约）+ 43（WebUI 协议安全）+ 31（多语言 WebUI）+ 25（协议）+ 68（Phase 1 HTML）等；插件相关收集数合计 267 条。
18. **新增代码规模**：三份任务书合计 `87 files changed, +9280/−54`（其中 SDK 五语言实现约 2600 行、示例约 900 行、测试约 2100 行、文档约 2400 行）。
19. **当前已知限制**：见文末「已知限制」。
20. **下一阶段如何接入统一 WebUI SDK**：已经接入 —— 见第三部分；五种语言示例都注册了 index/settings 页与同一个 save Action。

---

# 第三部分：统一 Plugin WebUI SDK（WebUI Protocol）

> 规范：[plugin-webui-protocol.md](plugin-webui-protocol.md) · 场景：[plugin-webui.md](plugin-webui.md)。

## 3.1 §十八 验收指标（逐项）

| 指标 | 结果 | 证据 |
| :--- | :--- | :--- |
| Real HTML Plugin Pages 100% | ✅ | 三层页面形态 + 五语言示例的真实 HTML/CSS |
| Plugin WebUI Protocol 1/1 | ✅ | `docs/plugin-webui-protocol.md` + `src/plugins/protocol.py::WEBUI_METHODS` |
| 五语言 SDK WebUI 各 100% | ✅ | Python `webui_render/webui_action/webui_asset` 钩子 · TypeScript `plugin.webui.page/action/asset` · Go `plugin.WebUI().Page/Action/Asset` · Rust `plugin.webui().page/action/asset` · Java `plugin.webUI().page/action/asset`（各带示例） |
| Path Traversal Tests 100% | ✅ | 7 形态 + symlink + 绝对路径 + 跨插件 |
| XSS Tests 100% | ✅ | 12 种负载参数化（净化 + CSP 纵深） |
| Permission Tests 100% | ✅ | 六项 `webui.*` 权限各有强制点与用例 |
| Cross-plugin Isolation 100% | ✅ | 路径根 = 插件自己的 `webui/`；跨插件引用 404 |
| Action Tests 100% | ✅ | save/未知动作/写权限被拒 三类 |
| Context Escape Tests 100% | ✅ | context 只有 6 键；config/data 受权限门；令牌/环境不泄露 |
| Existing Plugin Regression 0 new failures | ✅ | CI 1829 passed / 22 skipped |
| Core → SDK WebUI coupling 0 | ✅ | 面板层只依赖 1 个异常类型；SDK 不 import 引擎代码 |
| OneBot/Milky imports 0 | ✅ | grep 0 |
| CI 100% | ✅ | 三项全绿 |

## 3.2 §十九 最终架构目标（已达成）

```text
Flowerie Core
  └─ Plugin Protocol v1（JSON-Lines / stdio）
       ├─ Plugin SDK（Python / TypeScript / Go / Rust / Java）
       └─ WebUI Protocol（webui.page / webui.action / webui.asset）
            └─ WebUI Runtime（路由 / 权限 / 净化 / 隔离）→ HTML / CSS / Assets（No-JS）
```

**核心原则已落实**：WebUI 是 Plugin Protocol 的一部分；任何语言只要实现协议就获得同等 WebUI 能力（`test_plugin_webui_multilang.py` 用五种语言真进程钉住）；插件负责内容与业务，Runtime 负责托管、安全、权限、路由与资源隔离。

## 3.3 §十二 20 类安全问题的落点

见 [plugin-webui-protocol.md](plugin-webui-protocol.md) §9 的表：每一类都对应 `tests/test_plugin_webui_protocol.py` 里的一条真实用例（真 Manager + 真插件子进程 + 真管道）。

---

# 已知限制（如实）

1. **实机集成用例 skip**：需要运行中的协议端（NapCat / Lagrange / LLBot）与真实群号 —— 本环境没有；按任务书要求 skip 并打印缺失条件，**不当作通过**（基线 22 条，当前整仓 39 条）。
2. **本机没有 go / rustc / javac**：本地只有 Python 与 TypeScript 真跑，其余三种语言在 CI 上真编译真跑（本地 skip 会打印原因）；CI 是这三种语言的唯一编译器，所以本轮有三个 bug 只有 CI 能抓到（已修复，记录在 [plugin-sdk-capabilities.md](plugin-sdk-capabilities.md) §2）。
3. **No-JS 是硬约束**：插件页面不能带 JS，`webui.asset` 的 MIME 白名单也不含 svg/字体，想用 JS 的插件当前不可行（与主 WebUI 政策一致）。
4. **插件资源上限 256 KiB / 静态 4 MiB**：超限直接拒绝，不截断。
5. **旧 DSL 兼容层仍在**（任务书要求）：它不会被新插件使用，但会在兼容期内继续存在。
6. **`webui.asset` 只服务资源**，不参与页面渲染；页面 HTML 只能来自文件页或 `webui.page`。

# 复核命令

```bash
python3 -m pytest tests/test_plugin_protocol.py -q            # 协议：常量一致性 + 真子进程 + 引擎侧 op
python3 -m pytest tests/test_plugin_sdk_contract.py -q -rs    # 五语言契约（本机缺工具链会 skip 并打印原因；CI 全跑）
python3 -m pytest tests/test_plugin_webui_html.py -q          # Phase 1：真实 HTML 迁移与安全矩阵
python3 -m pytest tests/test_plugin_webui_protocol.py -q      # Phase 3：WebUI Protocol 安全（真 Manager + 真插件进程）
python3 -m pytest tests/test_plugin_webui_multilang.py -q -rs # Phase 3：五语言 WebUI 一致性
```
