# Plugin WebUI 第二阶段最终报告（任务书《plugin_to_webui》）

> 任务书：`/storage/emulated/0/plugin_to_webui.txt`　·　测试说明：`docs/plugin-webui-test.md`
> 结论口径：只写 **PASS / FAIL / BLOCKED / SKIPPED / UNKNOWN**（任务书 §35）。

## 1. 环境（§33.1）

| 项 | 本机（Termux/Android 沙箱）| CI（Ubuntu 24.04）|
| :--- | :--- | :--- |
| Python | 3.14.6（真跑）| 3.9 / 3.12（真跑）|
| Node | v24（真跑 TS 直执行分支）| 20（走 tsc 分支）|
| Go | 无 → **BLOCKED**（Termux 的 go 在非标准前缀不可用；官方 tarball 是 ET_EXEC 被 Android 拒）| 1.22（真编译真跑）|
| Rust | 无 → **BLOCKED**（无 aarch64-linux-android 宿主编译器，且无 cc/ld）| stable（真编译真跑）|
| JDK | 无 → **BLOCKED**（Termux 包按 `/data/data/com.termux` 前缀编译，无法在本沙箱运行）| 17（真编译真跑）|
| Browser / Playwright | 皆无 → **BLOCKED**（PyPI 无 playwright android wheel；手工解包后驱动 node 的 PT_INTERP 指向 `/lib/ld-linux-aarch64.so.1`，Android 无此 loader，linker 报 `unexpected e_type: 2`；apt 无 chromium 候选）| Playwright + Chromium（`playwright install --with-deps chromium`），真跑浏览器用例 |

## 2. WebUI 测试矩阵（§33.2 / §27）

| 项目 | Python | TypeScript | Go | Rust | Java |
| :--- | :--- | :--- | :--- | :--- | :--- |
| WebUI 被发现（manifest `web_ui` 段 + 页面声明）| PASS | PASS | PASS | PASS | PASS |
| HTTP 加载（真 WebUIServer 黑盒）| PASS | PASS | PASS | PASS | PASS |
| 真浏览器渲染 | 见 §3 / §6.2 | 同左 | 同左 | 同左 | 同左 |
| HTML + CSS + static assets | PASS | PASS | PASS | PASS | PASS |
| WebUI → Plugin Action + Config Round-trip | PASS | PASS | PASS | PASS | PASS |
| Plugin RPC（WebUI → plugin.call）+ Plugin Event（WebUI → emit）| PASS | PASS | PASS | PASS | PASS |
| Permission（允许/拒绝）| PASS | PASS | PASS | PASS | PASS |
| Security（穿越/Secret/XSS/模板注入）| PASS | PASS | PASS | PASS | PASS |
| Cross-plugin isolation | PASS | PASS | PASS | PASS | PASS |

说明：`tests/webui/` 的黑盒 HTTP 层用 Python 插件（`plugin_webui_test` + `minimal_py` 三份部署）真跑全部行；五种语言的 WebUI **能力**由 `tests/test_plugin_webui_multilang.py`（真进程 × 五语言，既有）与 `tests/sdk/`（§23 五语言最小 WebUI 页）覆盖并在 CI 真跑。

## 3. E2E 链路（§33.3 / §28）

| 链路 | 状态 | 证据 |
| :--- | :--- | :--- |
| E2E-1/2/3 三条跨语言链路（Python WebUI→Go、TS WebUI→Java、Go WebUI→Rust，均回 Browser）| **PASS（CI `webui-e2e` 21 passed，§6.2）**；本机 BLOCKED（无浏览器/工具链，§1）| `tests/e2e/test_plugin_webui_chains.py`（E2E-1/2/3）；入口 communication 页五语言已补齐（`examples/multilang-sdk/*/manifest.json` 均有 index + communication），CI 有 node/javac/go/rustc |
| 引擎层同批链路（无浏览器也能真跑）| **PASS（本机真跑）** | `tests/e2e/test_plugin_chain_engine.py`：三页契约 id 齐全、settings POST→真插件进程→读回、communication POST→`plugin.call`→Core Router→另一个真插件进程→回页面，`comm_snapshot` 显示 `calls_ok≥1`、`by_route={"core":…}`、目标 READY |

## 4. 安全测试（§33.4，逐项）

| 项 | 结果 | 证据（`tests/webui/`，真服务器 + 真引擎）|
| :--- | :--- | :--- |
| Path Traversal | **PASS** | 8 种形态用 `http.client` **原样发 Request-URI**：`../`、`../../`、`/etc/passwd`、`..%2f`、`%2e%2e%2f`、双重编码、`....//`、`%2fetc%2fpasswd`、反斜杠、绝对路径 → 全部拒绝；真建 symlink 指 `/etc/passwd` → 404 |
| Cross Plugin Access + 多插件隔离（§22）| **PASS** | 三插件并行：页面身份标记/CSS/config/上传/下载/page id/session/文件/plugin id 逐项隔离；交叉下载必须失败；同名 communication 页的 form action 只指向请求方自己的 plugin id；会话 token 不落页面 |
| Secret Leakage | **PASS** | 10 个响应面扫描 `TEST_SECRET/TEST_API_KEY/TEST_TOKEN` → 0 命中（HTML/CSS/JSON/错误响应/静态资源）|
| XSS / Template Injection | **PASS** | `<script>alert(1)</script>`、`<img src=x onerror=...>` 按零 JS 策略转义/拒绝，用真 HTML 解析器判定属性位 `on*`（不被文本里的同名字符串骗过）；`{{ 6*7 }}` 不被求值，未解析占位符不产生越权内容 |

## 5. 回归（§33.5）

| 项 | 结果 |
| :--- | :--- |
| `pytest -q tests/webui/`（本机真跑，pydantic 用替身）| **102 passed / 1 xfailed / 0 failed** |
| `tests/sdk/`（本机）| 9 passed / 37 skipped（Python 真跑；其余四语言 BLOCKED BY ENVIRONMENT）|
| `tests/e2e/`（本机）| 3 passed / 18 skipped（skip 全部 BLOCKED BY ENVIRONMENT 并写明缺什么）|
| CI 口径（`tests/sdk` 46 / `tests/webui` 102+1xfail / `tests/e2e` 21 / 全量与 Acceptance）| 见 §6.2 |

## 6. CI

### 6.1 本轮红 -> 绿（如实记录每一轮根因；末次修复 `792dc1e`，结果见 6.2）

| commit | 结果 | 根因 | 修复 |
| :--- | :--- | :--- | :--- |
| `d317617` | 红 | ① Ruff I001（新测试的一行超长导入）；② `tests/e2e` 把 manifest runtime（`exec`）当成语言名断言 | 按 CI 建议换行；加 `MANIFEST_RUNTIME` 映射 |
| `adbec21` | 红 | 我在子代理仍在编辑时 `git add -A`，把中间态 `examples/multilang-sdk/go/main.go` 提交了 → Go 最小插件编译失败 | 改为"等子代理收工 + 只 add 明确文件" |
| `5279fef` | 红 | ① Java 最小插件引用了未定义的 `hookArg`（子代理中途失败留下的悬空引用）；② 隔离用例的专属标记 `communication-panel` 因新增 communication 页而不再专属 | 补 `hookArg` helper；隔离用例改用 `settings` 页 + 同名页的 form action 必须指向请求方自己的 id（更强的证据）|
| `e23e52c` | 红 | WebUI/E2E 夹具构造 `Settings` 时缺必填字段（`DEEPSEEK_API_KEY`/`BOT_QQ`）——本机 pydantic 是桩，CI 才是真闸门 | 夹具显式传测试哑值 |
| `21f0131` | 红 | ① 仓库 ReDoS 扫描拦下新示例里的绝对路径正则；② CSP 用例把"Playwright 因 CSP 抛错"当成失败；③ fixture 的 trace 单元格混入说明文字 | 改成线性字符串扫描；CSP 用例改为显式断言"必须因 CSP 失败"；说明移到兄弟单元格 |
| `0fcb6bf` | 红 | 五语言 communication 页的 `trace_id`/`request_id` 单元格里嵌了 `<small>` 说明 → `inner_text()` 带出说明，E2E"裸 id 随请求往返"断言误判；另有未使用的 `re` 导入 | 五语言统一把说明移出 id 单元格；删导入 |

### 6.2 最终结果（commit `c56bbc1`，三项 workflow 全绿）

| workflow / 步骤 | 结果 | 真实数字 |
| :--- | :--- | :--- |
| `CI` · Ruff check（3.9 与 3.12）| **success** | All checks passed! |
| `CI` · SDK 语言矩阵 | **success** | **46 passed** (86.34s)：五语言真 build/真启动/真调用/真关闭 |
| `CI` · Plugin WebUI（http/static/security/isolation/action/communication）| **success** | **102 passed / 1 xfailed** (4.42s)，真 WebUIServer + 真 PluginManager + 真插件进程 |
| `CI` · 全量 pytest（不含 sdk/webui/e2e）| **success** | **2136 passed / 22 skipped** |
| `CI` · `webui-e2e`（真 Chromium）| **success** | **21 passed** (115.23s)：`playwright install --with-deps chromium` + §8 DOM 断言 + §28 三条链路 |
| `Acceptance` | **success** | **37/37 通过**；pytest **2288 passed / 39 skipped / 1 xfailed**；ruff clean |
| `Push on main` | **success** | CodeQL（actions / javascript-typescript / python）全过 |

> 39 skipped 与 22 skipped 都是**既有**实机集成用例（无真实协议端环境），与上一阶段口径一致；本轮新增的 webui / sdk / e2e 用例**一条都没有被跳过**（浏览器链路在 CI 上真跑 21 passed）。

## 7. 环境阻塞（§33.6，单列，不与 WebUI 结论混写）

**QQ / P2P Real Integration: BLOCKED BY ENVIRONMENT** —— 当前测试环境没有真实 QQ / NapCat / Any 协议端 / OneBot P2P 链路。
本轮所有 Plugin WebUI / Plugin RPC / Plugin Event 结论**均不依赖** QQ，也**不得**被表述为 QQ 实机验证；实机集成用例在 CI 上保持 skip 并打印缺失条件。

## 8. §32 Gate 判定

| Gate | 内容 | 判定 | 依据 |
| :--- | :--- | :--- | :--- |
| A / B | 五种语言 WebUI 都能被发现 + 都能 HTTP 加载 | **PASS** | 五语言 manifest `web_ui` 段 + 页面声明（真 `PluginManifest.load` + 真 loader）；`tests/webui/` 真服务器黑盒 + `tests/sdk/` 五语言页面 |
| C | 五种语言 WebUI 都经真实浏览器渲染 | **PASS**（CI）| `tests/e2e/test_plugin_webui_browser.py`（CI 装 Chromium）；本机 BLOCKED |
| D | HTML + CSS + static assets 正确加载 | **PASS** | `test_plugin_webui_static.py`（200/text/css/非空/页面真引用/净化）|
| E / F | WebUI → Plugin Action 成功 + Config Round-trip 成功 | **PASS** | 同文件：get_info/echo/set_config；POST save → 重开读回一致 + 落盘证据（`test_plugin_webui_plugin_action.py`）|
| G / H | WebUI → Plugin → Plugin RPC 成功 + WebUI → Plugin Event 成功 | **PASS** | `test_plugin_webui_communication.py`：自调用取回引擎真 request_id/trace_id/route（A→minimal_py）；emit 去程（对端 `plugin.on` 收件）+ 回程（页面事件日志）|
| I / J | Permission denied 传递到 WebUI + 四种错误码正确传递 | **PASS**（插件间调用链）| 撤权限 → 页面 `Status: Failed` + `Code: PERMISSION_DENIED`，恢复 → OK；四种码全绿并渲染到页面；**限制**：引擎自身的页面级失败仍是中文文案（见 §9）|
| K / L / M / N | 路径穿越 / 跨插件文件隔离 / Secret leakage / XSS·HTML injection | **PASS** | §4 第 1–4 行 |
| O | 至少三条跨语言 WebUI E2E 链路通过 | **PASS**（CI `webui-e2e` 21 passed）| 三条链路均已具备页面与测试；CI 有全部工具链 |
| P | 现有 SDK 46/46 测试仍通过 | **PASS** | 见 §5 / §6.2 |
| Q | 现有全量回归无新增失败 | **PASS**（Acceptance 37/37；2288 passed）| |
| R | QQ/P2P 未具备环境时保持 BLOCKED，不伪造 PASS | **PASS** | 见 §7 |

## 9. 已实测的平台限制（如实记录，未改 Core）

1. **插件页是面板壳片段**（无 `<html>/<head>/<title>`）→ 浏览器 `document.title` 为空；页面标题由 `h1.page-title` 承担，`<title>` 单列一条 `xfail(strict=False)`（`tests/webui/test_plugin_webui_http.py::test_document_title_element_is_present`）。
2. **模板变量不能出现在标签属性位置**：`<input ... {{ x_checked }}>` 会被净化器当属性丢弃（先净化后替换变量），`examples/plugins/html_webui_demo` 的复选框回显因此静默失效（本轮插件改用 class + 显式读回行表达状态）。
3. **引擎页面级失败无 error code**（中文文案字符串）；插件间调用链路的 12 个结构化码是齐的。
4. **插件 stdout 预算是累计的 256KiB**（`src/plugins/permissions.py:394`）：实测跑满一轮 WebUI 用例后 `plugin_output_overflow bytes=267444` → 插件被杀；夹具按模块真 `enable` 重启运行法规避，建议 WebUI 渲染流量单独记账（未改）。
5. **调用方拿不到引擎 request_id/trace_id**（SDK 只回 result）→ 需要被调方回传（本轮 canonical 插件与被调契约按此实现）。
