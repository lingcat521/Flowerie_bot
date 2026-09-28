# Plugin WebUI 真浏览器 E2E 报告（任务书 §8 / §26 / §28 / §31）

> 任务书：`/storage/emulated/0/plugin_to_webui.txt`　·　产物：`tests/e2e/`　·　本报告：`docs/plugin-webui-e2e-report.md`
> 一句话：**浏览器 E2E 的测试代码、可复用启动夹具与 CI 口径全部落地，本机实测过能跑的部分都真跑了**；
> 本机（Termux / Android 沙箱）**装不上 Playwright/Chromium、也起不了真 WebUI 服务器**（缺 pydantic），
> 因此**浏览器层与服务器层在本机一律 `BLOCKED BY ENVIRONMENT`（写清缺什么，绝不 PASS）**；
> **引擎层（真 PluginManager + 真插件进程 + 真 Core Router）在本机真跑通过**；CI 上三条链路真浏览器真跑（21 passed，见 §6）。

## 1. 环境实测（先查再写；每条都带命令与原始结果）

| 探测项 | 命令 | 实测结果（本机 = Android/Termux 沙箱，Python 3.14.6，`android-24-arm64_v8a`） |
| :--- | :--- | :--- |
| Playwright 包 | `pip install playwright` | **失败**：`ERROR: Could not find a version that satisfies the requirement playwright (from versions: none)` —— PyPI 没有 android 平台 wheel（`pip index versions playwright` 同样报 no matching distribution） |
| Playwright 驱动 | 手工 `pip download playwright --platform manylinux2014_aarch64` 后解包 | 下载成功（47.9 MB，1.63.0）；驱动 `playwright/driver/node` = 122 893 672 字节 ELF，`PT_INTERP=/lib/ld-linux-aarch64.so.1`（**Android 上不存在这个 loader**）；`chmod +x` 后执行 → `error: "…/driver-node" has unexpected e_type: 2`（Android linker 拒绝非 PIE 的 ET_EXEC）→ **浏览器驱动无法运行** |
| 系统浏览器 | `apt-get install -s chromium`；`which chromium chromium-browser google-chrome` | 无候选包；无任何系统 Chromium/Chrome 可执行文件（apt 本身也因 `$PREFIX` 指向不存在的 `/data/data/com.termux` 而不可用） |
| 服务端依赖 | `pip install pydantic` | **失败**：pydantic-core 需要 Rust 扩展，`maturin` 报 `Target triple not supported by rustup: aarch64-unknown-linux-android`，本机也没有 rustc/cargo → **真 WebUI 服务器（`src/config.py` 依赖 pydantic-settings）起不来** |
| 可装的依赖 | `pip install aiohttp` | **成功**（PyPI 有 `cp314 android_24_arm64_v8a` wheel，aiohttp 3.14.3）——但 pydantic 缺失仍然挡住真服务器 |
| 语言工具链 | `which go rustc javac java node python3` | `python3` ✓；`node v24.18.0` 存在但引擎的环境变量白名单不含 `LD_PRELOAD=libtermux-exec` → 插件进程拉不起来（与 `tests/sdk/harness.py:missing_reason` 同一口径）；`go` / `rustc` / `javac` **未安装** |
| 文件系统 | 写 + `chmod +x` + 执行探针 | 仓库所在的 `/storage` 是 FUSE（无执行位）；夹具因此提供"可执行位可用"的工作目录解析（`E2E_WORK_ROOT` → 系统临时目录 → 仓库内 `.e2e-work/`） |

## 2. 本机实测结果（有真数字，不含推测）

```text
$ pytest -q -rs tests/e2e
...sssssssssssssssss                                                     [100%]
3 passed, 18 skipped in ~4s
```

**3 passed = 引擎层真跑**（`test_plugin_chain_engine.py`，不需要浏览器、不需要 HTTP 服务器）：

1. 三个页面在**真插件进程**里渲染出契约里的全部元素 id，且没有 `<script>`；
2. 设置表单 POST -> 插件 `webui.action` -> 真插件进程写状态 -> 重新渲染读回（Round-trip 真）；
3. 通信页 POST -> `plugin.call` -> **真 Core Router -> 另一个插件进程** -> 结果回到页面变量；
   引擎统计（`comm_snapshot()`）真数字：`calls_ok >= 1`、`by_route["core"] >= 1`、目标实例 `READY`。

**18 skipped = 全部 `BLOCKED BY ENVIRONMENT`**，逐条理由（`-rs` 原样输出）：

* 浏览器 / 服务器用例（11 条 + 1 条浏览器夹具）：`未安装 Playwright Python 包（pip install playwright）：ModuleNotFoundError: No module named 'playwright'` 或 `本机跑不起真 WebUI 服务器 —— 缺 Python 服务端依赖：pydantic, pydantic_settings（pydantic v2 依赖 pydantic-core 的 Rust 扩展；Android/aarch64 上 PyPI 没有匹配 wheel，本机也没有编译器 —— CI 用 pip install -r requirements.txt 即可）`；
* §28 链路：E2E-1 `本机缺 go（CI 有）`；E2E-2 `Termux 沙箱下引擎按白名单裁剪插件进程环境变量（不含 LD_PRELOAD），前缀内的 node 无法被启动（CI 无此限制）；本机缺 javac, java（CI 有）`；E2E-3 `本机缺 go；本机缺 rustc`。

### 额外旁证（本机探针，不进仓库）

用真 `PluginManager` + 真插件进程直接渲染夹具插件的三页（绕过 HTTP/浏览器），实测：

* `index`：`id="plugin-name"` / `id="plugin-status"` 都在；净化报告 `drop_decl, drop_tag:html, drop_tag:head, drop_tag:meta, drop_tag:title, drop_tag:body`（**这就是 `document.title` 为空的根因**）；`<link rel="stylesheet">` 保留；
* `settings` POST：`message="设置已保存"`，`greeting/count/mode/notify` 全部按提交值写进插件进程状态；
* `communication` POST（目标 = `minimal_py`）：`calls_ok=2`、`by_route={"core":2}`、回包 `{"ok":true,"result":{"_e2e_trace":"1e2d…","hello":"world"}}`、关联 id 原样往返；
* 静态资源：`style.css` 471 字节，`text/css; charset=utf-8`。

### 服务器层本机实测（drill：本机注入 pydantic 替身，**不进仓库、CI 不用**）

本机装不上 `pydantic`（见 §1），真 `WebUIServer` 起不来。为了**验证夹具自身**（而不是给验收降标准），
本机用 `PYTHONPATH` 注入一份 pydantic/pydantic-settings 的最小替身（放在工作目录，仓库里没有这份文件），
让**真的** `src/config.py:Settings` 类、真 `ConfigService`、真 `PluginManager`、真 `WebUIServer`、真 aiohttp 起来跑一遍：

```text
$ PYTHONPATH=<drill-stub>:. pytest -q -rs tests/e2e
5 passed, 16 skipped in ~26s        # 多出的 2 条 = HTTP 页面契约 + canonical 插件页面契约（真服务器）
```

drill 里真跑出来的东西（都是真服务器 + 真插件进程，只有 pydantic 是替身）：

* `POST /panel/login` 表单登录 -> 302 + `Set-Cookie: fb_token=…`，后续请求带 Cookie 访问插件页面 200；
  **drill 抓到一个真 bug 并已修**：`urllib` 默认跟随重定向会把 302 上的 `Set-Cookie` 丢掉 ——
  夹具现在显式不跟随 3xx（见 `_harness.py:_NoRedirect`）；
* 夹具插件三页 HTTP 200，契约里的元素 id **一个不缺**；`static/style.css` 200 + `text/css; charset=utf-8`（471 字节）；
  `settings` 表单 POST 后页面回读出提交值（`设置已保存` + `HTTP round-trip`）；
* **canonical 插件（`examples/plugin-webui-test`，本机 drill 时已落地）**：`#communication-panel` 在、
  提交 `target=webui_e2e_py / method=echo / params={"hello":"world"}` -> `#call-status = Status: OK`，
  `#call-response` 里带回 `hello/world`，并且 `#call-request-id` / `#call-trace-id` 显示的是
  **引擎真实的 request_id / trace_id**（`610966a9…` / `570855e7…`）—— 两个真插件进程 + 真 Core Router 的端到端证据。

> 也就是说：**浏览器层本机无法验证**（缺 Playwright/Chromium，见 §1），但浏览器用例之外的全部代码路径
> （服务器组装、登录、路由、渲染、契约 id、表单 POST、跨插件调用、静态资源）都在本机真跑过，且在 CI 上由 21 passed 覆盖。

## 3. 交付物

| 文件 | 职责 |
| :--- | :--- |
| `tests/e2e/_harness.py` | **可复用启动夹具**：环境探测（缺什么写清楚）、工作目录解析（执行位）、插件铺设与真构建、真服务器子进程 + HTTP 客户端 + 表单登录、§28 三条链路的编排与阻塞判定 |
| `tests/e2e/_serve.py` | 真服务器引导进程（真 Settings/SettingsRepository/ConfigService/PluginManager/WebUIServer，127.0.0.1 临时端口，SIGTERM 干净收尾） |
| `tests/e2e/conftest.py` | pytest 夹具：`webui_server` / `browser_provider`（惰性 Chromium）/ `logged_in` / `chain_runner` / `rig_ctx` |
| `tests/e2e/test_plugin_webui_browser.py` | §8 渲染断言 + §7 CSS + §9 零 JS（浏览器侧实证）+ 无 JS 表单交互 + 未登录重定向 + canonical 插件契约 |
| `tests/e2e/test_plugin_webui_chains.py` | §28 三条链路（真浏览器端到端） |
| `tests/e2e/test_plugin_chain_engine.py` | 同批链路的引擎侧验证（无浏览器也能真跑） |
| `tests/e2e/fixtures/plugins/webui_e2e_py/` | E2E 入口插件（index / settings / communication + 跨插件调用），页面 id 即断言契约 |
| `tests/e2e/README.md` | 安装与运行方式（本机 + CI）、页面契约、环境变量、已知缺口 |

## 4. §8 / §7 / §9 断言映射

| 任务书要求 | 落在哪里 | 断言 |
| :--- | :--- | :--- |
| `document.title` | `test_document_title_contract` | 现状壳是片段 → 必须为空串；插件文件里的 `<title>` 不得成为浏览器标题；给 `E2E_EXPECT_DOCUMENT_TITLE` 时严格相等；壳的 `h1.page-title` 必须存在 |
| `#plugin-name` / `#plugin-status` | `test_index_page_renders_plugin_name_and_status` | 可见 + 文本来自插件进程（runtime=python 真值）+ 页面无 `<script>` |
| `#settings-form` | `test_settings_form_visible_with_required_controls` | 表单可见，text/number/checkbox/select/submit 五种控件都在 |
| `#communication-panel` | `test_communication_panel_visible` | 面板 + 表单 + 结果区全部 id 都在 |
| CSS 真加载（§7） | `test_css_stylesheet_is_loaded_and_applied` | `style.css` HTTP 200 + `text/css`，并且 `getComputedStyle` 证明样式**生效**（font-weight=600），无 4xx 资源 |
| 零 JS（§9） | `test_zero_javascript_policy_in_real_browser` | 页面无 script；用 `add_script_tag` 注入内联脚本，CSP `default-src 'none'` 必须让它**不执行** |
| 无 JS 交互（fill/select_option/check/click） | `test_settings_form_roundtrip_without_js`、`test_navigation_between_plugin_pages_by_links` | 表单 POST 后服务端重渲染，状态从插件进程读回；页面间靠 `<a href>` 导航 |
| 先登录 | `test_plugin_page_requires_login` + `form_login()` | 未登录访问插件页 -> 回登录页；所有用例先走真表单登录（fill + click） |

## 5. §28 三条链路

| 链路 | 入口 WebUI 插件 | 目标插件 | 本机 | CI |
| :--- | :--- | :--- | :--- | :--- |
| E2E-1 Browser -> Python WebUI -> Python 插件 -> **Go** 插件 -> 回 Browser | `tests/e2e` 夹具插件 `webui_e2e_py` | `examples/multilang-sdk/go`（`minimal_go`，真 `go build`） | **BLOCKED**（缺 go） | **真跑** |
| E2E-2 Browser -> **TS** WebUI -> TS 插件 -> **Java** 插件 -> 回 Browser | `examples/multilang-sdk/typescript`（communication 页已补齐） | `examples/multilang-sdk/java` | **BLOCKED**（node 被环境白名单挡 + 缺 javac/java） | **真跑** |
| E2E-3 Browser -> **Go** WebUI -> Go 插件 -> **Rust** 插件 -> 回 Browser | `examples/multilang-sdk/go`（communication 页已补齐） | `examples/multilang-sdk/rust` | **BLOCKED**（缺 go/rustc） | **真跑** |

CI（commit `c56bbc1`）：`webui-e2e` 作业 **21 passed**，三条链路都在真 Chromium 里跑通（§6）。

链路断言（每一层都真）：`#communication-response` 必须含请求原样回显（`"hello"/"world"`）、
`#communication-trace-id` 必须出现在回包里（**证明回包真的来自目标进程**）、
`#communication-target-runtime` 必须等于目标插件**自报**的 runtime（go/java/rust）、
`#communication-response-ok == "ok"`、`#communication-error` 为空、无页面脚本错误、无 4xx 资源。

> 入口插件要满足的**页面契约**写在 `tests/e2e/README.md` §3：`#communication-panel` +
> `#communication-{target,method,request,route,submit,response,target-runtime,request-id,trace-id,message}`。
> 五语言 manifest 现已全部声明 `index` + `communication` 两页（`examples/multilang-sdk/*/manifest.json`），
> E2E-2 / E2E-3 不再缺入口页、不需要改测试；也可用
> `E2E_CHAIN2_ENTRY` / `E2E_CHAIN2_TARGET`（同理 CHAIN1/CHAIN3）指到别的插件包。

## 6. CI 落地情况（本报告原「建议片段」已实现）

| 项 | 现状（`.github/workflows/ci.yml`）|
| :--- | :--- |
| 主 `test` 作业 | `pytest -q -rs --ignore=tests/sdk --ignore=tests/webui --ignore=tests/e2e`（ci.yml:78）—— **不再收集 `tests/e2e`**，浏览器用例不会把主流水线变红 |
| `webui-e2e` 作业 | ci.yml:82 起（`continue-on-error: true`）：node 20 / go 1.22 / java 17 / rust stable + `pip install playwright` + `python -m playwright install --with-deps chromium`，跑 `pytest -q -rs -s tests/e2e/`（ci.yml:110）|
| 真跑结果 | **21 passed**（115.23s，commit `c56bbc1`）：§8 DOM 断言 + §28 三条链路（见 `docs/plugin-webui-report.md` §6.2）|

没装 Playwright / 工具链缺失时，用例照旧 `BLOCKED BY ENVIRONMENT` skip 并由 `-rs` 把理由打进日志（绝不写 PASS）。
`E2E_SCREENSHOT_DIR` 仍被链路用例支持（给了就存截图），但 CI 目前未设置该变量、也没有上传 artifact 的步骤。

## 7. 已知缺口（本机实测发现；第 4 条已补齐）

1. **插件页面没有 `<title>`**：路由返回的是面板壳片段（无 `<html>/<head>`），`document.title` 只能是空串；
   插件文件里的 `<title>` 被净化器丢掉，**标题文本还会漏进正文**。建议壳里补 `<title>`，
   补完把 `E2E_EXPECT_DOCUMENT_TITLE` 设进 CI，断言立刻变成严格相等。
2. **模板变量不能出现在属性位置**：`<input … {{ notify_checked }}>` 被 HTMLParser 解析成名为 `{{` 的属性后丢弃（`drop_attr`），
   "按状态回显 checked/selected"目前**静默失效** —— 仓库自带的 `examples/plugins/html_webui_demo` 原先就有这个坑（现已改成文本状态回显）。
   建议：需要条件属性时由插件返回整页 HTML（`render: "plugin"`），或给模板引擎加受控条件语法。
3. **调用方插件拿不到引擎侧 request_id / trace_id（除非被调方回传）**：`api.plugin.call()` 只把 `result` 交给调用方
   （失败抛结构化错误）；引擎把整条 forward 请求交给**被调方** handler，里面有 `request_id` / `trace_id` / `route` / `source`。
   所以页面要显示引擎真实 id，只能靠**互操作约定**：被调的 `echo` 平铺回传这几个字段
   （`examples/plugin-webui-test` 正是这么读的；夹具插件的 `echo` 顶层 + `_engine` 两种形状都回传，
   本机 drill 实测 canonical 页面因此显示出了引擎真实 id）。
   对端不回传时页面如实显示"对端未回传"/"插件侧 call id"，**绝不编造**；夹具自身的链路证据（`_e2e_trace` 原样往返）
   与引擎统计（`comm_snapshot()` 的 `calls_ok` / `by_route["core"]`）由 `test_plugin_chain_engine.py` 断言。
   若要在协议层直接给出这些字段（不依赖对端自觉），需要 SDK/协议扩展（例如 `call_with_meta()` 或在响应里保留 `request_id`）。
4. **入口插件缺 `communication` 页面（已补齐）**：曾导致 E2E-2 / E2E-3 skip（唯一的非工具链原因，契约见 README §3）；
   五语言 `examples/multilang-sdk/*/manifest.json` 现均声明 `index` + `communication`，
   CI `webui-e2e` 的 21 passed 已包含三条链路（`c56bbc1`）。

## 8. 复现命令

```bash
# 本机（任何环境）：引擎层真跑
pytest -q -rs tests/e2e/test_plugin_chain_engine.py

# 全量 E2E（本机：浏览器/服务器用例 BLOCKED skip；CI：真跑）
pytest -q -rs tests/e2e

# 只跑链路
pytest -q -rs tests/e2e/test_plugin_webui_chains.py

# 本机环境实测（复现报告 §1 的证据）
pip install playwright                      # -> No matching distribution（android 无 wheel）
pip download playwright --no-deps --only-binary=:all: --platform manylinux2014_aarch64 -d /tmp/pw
python3 -c "import struct,pathlib;print(pathlib.Path('/tmp/pw').glob('*.whl'))"
pip install pydantic                        # -> pydantic-core 构建失败（无 Rust/ANDROID triple）
```
