# tests/e2e —— Plugin WebUI 真浏览器 E2E（任务书 §8 / §26 / §28 / §31）

真 Chromium（Python Playwright）+ 真 WebUI 服务器（aiohttp 子进程，与 `main.py` 同一套组装）
+ 真插件子进程 + 真 Core Router。**没有 Mock Core、没有 Mock 插件**。

* 装不上浏览器 / 缺服务端依赖 / 缺语言工具链 -> `BLOCKED BY ENVIRONMENT: …` **skip**，理由写明缺什么
  （`pytest -q -rs` 会打印）；**绝不写 PASS**。
* 已经落地的东西就真跑：引擎层（真 PluginManager + 真插件进程）在最小环境里也能跑。

## 1. 文件

| 文件 | 作用 |
| :--- | :--- |
| `_harness.py` | **可复用启动夹具**：环境探测（缺什么写清楚）、可执行位可用的工作目录、插件铺设与真构建、真服务器子进程、HTTP 客户端 + 表单登录、§28 三条链路的编排与阻塞判定 |
| `_serve.py` | 服务器引导进程：真 `Settings` -> `SettingsRepository` -> `ConfigService`（注册管理员）-> `PluginManager`（真插件进程）-> `WebUIServer.start()` |
| `conftest.py` | pytest 夹具：`webui_server`（会话级真服务器）、`browser_provider`（惰性 Chromium）、`logged_in`（真表单登录）、`chain_runner`（按链路拉服务器）、`rig_ctx`（引擎层真 Rig） |
| `test_plugin_webui_browser.py` | §8 渲染断言（document.title / #plugin-name / #plugin-status / #settings-form / #communication-panel）、§7 CSS 真加载、§9 零 JS（浏览器侧实证）、无 JS 表单交互（fill/select_option/check/click） |
| `test_plugin_webui_chains.py` | §28 三条链路（浏览器端到端） |
| `test_plugin_chain_engine.py` | 同一批链路的**引擎侧**验证：真 PluginManager + 真插件进程 + 真 Core Router（不需要浏览器/HTTP） |
| `fixtures/plugins/webui_e2e_py/` | E2E 入口插件（index / settings / communication 三页 + 跨插件调用）；**页面元素 id 就是断言契约** |

## 2. 怎么跑

### 本机 / 开发机

```bash
pip install -r requirements.txt pytest pytest-asyncio
pip install playwright
playwright install --with-deps chromium      # Linux 需要 sudo 装系统依赖；无 sudo 时用 playwright install chromium
pytest -q -rs tests/e2e
```

只跑不需要浏览器的部分（引擎层，任何环境都能跑）：

```bash
pytest -q -rs tests/e2e/test_plugin_chain_engine.py
```

### 本机（Termux / Android 沙箱）实测结论

| 层 | 本机状态 | 缺什么（实测） |
| :--- | :--- | :--- |
| 引擎层（真插件进程 + Core Router） | **真跑** | 无（3 passed） |
| 服务器层（真 WebUIServer） | **BLOCKED BY ENVIRONMENT** | `pydantic` / `pydantic-settings`：pydantic v2 需要 pydantic-core 的 Rust 扩展，Android/aarch64 上 PyPI 没有匹配 wheel，本机也没有编译器 |
| 浏览器层（Playwright + Chromium） | **BLOCKED BY ENVIRONMENT** | `playwright` 包：PyPI 没有 android 平台 wheel（pip 明确报 `No matching distribution`）；即使手工解开 manylinux aarch64 wheel，Playwright 驱动是自带的 Linux/glibc Node 可执行文件（PT_INTERP=`/lib/ld-linux-aarch64.so.1`，Android 上不存在；且是非 PIE 的 ET_EXEC，Android linker 直接拒绝：`unexpected e_type: 2`）→ Chromium 浏览器也就无从启动 |
| 语言工具链 | `python` 可用；`node` 在沙箱里被引擎的环境变量白名单挡住（缺 LD_PRELOAD=libtermux-exec）；`go` / `rustc` / `javac` 未安装 | 见 skip 理由（与 `tests/sdk/harness.py:missing_reason` 同一份口径） |

结论：浏览器用例在本机一律 `BLOCKED BY ENVIRONMENT` skip，**不给 PASS**；真浏览器证据由 CI 产出。

## 3. 页面契约（任何插件 WebUI 入口都要满足）

路由：`GET|POST /panel/plugins/webui/<plugin-id>/<page>`（先登录：`POST /panel/login` 拿 `fb_token` Cookie）。

| 页面 | 必须有的元素 id |
| :--- | :--- |
| `index` | `#plugin-name` `#plugin-status`（另建议 runtime / version / sdk-version） |
| `settings` | `#settings-form`（含 text / number / checkbox / select / submit：`#setting-greeting` `#setting-count` `#setting-notify` `#setting-mode` `#settings-submit`） |
| `communication` | `#communication-panel`（表单 `#communication-target` `#communication-method` `#communication-request` `#communication-route` `#communication-submit`；结果 `#communication-response` `#communication-target-runtime` `#communication-request-id` `#communication-trace-id` `#communication-message`） |

交互约定（零 JS：只有服务端渲染，靠 `<form method="post">` + `<a href>`）：

* `settings` 的提交按钮：`<button type="submit" name="plugin_action" value="save">`；保存后把**插件进程里真实的状态**重新渲染回页面。
* `communication` 的提交按钮：`<button type="submit" name="plugin_action" value="call">`；插件用 `plugin.call(target, method, params)` 真调用目标插件，
  `#communication-target-runtime` 必须写**目标插件自报的 runtime**（go / java / rust / typescript / python），
  `#communication-trace-id` 必须是随请求发给目标、并由目标原样带回的关联 id（E2E 用它证明回包真的来自目标进程）。

被调方的互操作约定（可选但推荐）：引擎把整条 forward 请求交给被调 handler，里面有
@BT@request_id@BT@ / @BT@trace_id@BT@ / @BT@route@BT@ / @BT@source@BT@ —— 被调插件的 @BT@echo@BT@ 把它们**平铺**回传（@BT@app("request_id")@BT@…），
调用方页面就能显示**引擎真实 id**（@BT@examples/plugin-webui-test@BT@ 按这个约定读 @BT@result["request_id"]@BT@）；
不回传时页面如实显示"对端未回传"，绝不编造。夹具插件的 @BT@echo@BT@ 两种形状都回传（顶层 + @BT@_engine@BT@ 块）。

满足这份契约的入口插件会被链路用例直接驱动，不需要改测试：
`examples/plugin-webui-test`（任务书 §4）、`examples/multilang-sdk/{typescript,go}`（§23，需要 `communication` 页面）。

## 4. 环境变量

| 变量 | 作用 |
| :--- | :--- |
| `E2E_WORK_ROOT` | 工作根目录（必须支持执行位；默认系统临时目录，最后兜底仓库内 `.e2e-work/`） |
| `E2E_SCREENSHOT_DIR` | 给了就保存链路截图（CI artifact 便于排障） |
| `E2E_EXPECT_DOCUMENT_TITLE` | 面板壳补上 `<title>` 后，用它把 `document.title` 断言变成严格相等 |
| `E2E_CHAIN{1,2,3}_ENTRY` / `E2E_CHAIN{1,2,3}_TARGET` | 覆盖链路两端的插件 id（对接别的插件包时用） |

## 5. 已知缺口（本机实测，写清楚而不是绕过）

1. **`document.title` 目前是空串**：插件页面路由返回的是面板壳片段，没有 `<html>/<head>/<title>`；
   插件页面文件里的 `<title>` 会被净化器丢弃（`drop_tag:title`），**标题文本会作为正文显示出来**。
   建议面板壳补 `<title>`；补上后设置 `E2E_EXPECT_DOCUMENT_TITLE` 即可切到严格断言。
2. **模板变量不能出现在标签属性位置**：`<input ... {{ notify_checked }}>` 会被 HTMLParser 当成名为 `{{` 的属性丢掉
   （`drop_attr`），所以"根据状态回显 checked/selected"的写法目前**静默失效**（仓库自带的 `examples/plugins/html_webui_demo` 原先就这么写，现已改成「静态 checkbox + 文本状态回显」）。
   需要条件属性时，要么让插件返回整页 HTML（`render: "plugin"`），要么给模板引擎加受控的条件语法。
3. **插件看不到引擎侧的 `request_id` / `trace_id`**：SDK 的 `plugin.call()` 只把 `result` 交给插件（失败抛结构化错误），
   所以页面上显示的 `request_id` 是**插件侧 call id**（页面上如实标注），`trace_id` 是随请求往返的关联 id。
   引擎侧的 request_id / trace_id / route 由 `test_plugin_chain_engine.py` 通过 `comm_snapshot()` 断言（真实数字）。
4. **`examples/multilang-sdk/{python,typescript,go,rust,java}` 都有 `index` 与 `communication` 两个
   `render: "plugin"` 页面** —— §28 的三条链路（Python→Go / TS→Java / Go→Rust）在 CI 上**真跑**：
   `CI / webui-e2e` 装真 Chromium 后 21 passed（含三条链路），日志见
   [plugin-webui-report.md](../../docs/plugin-webui-report.md) §3/§6。

## 6. CI 阶段（已落地）

`.github/workflows/ci.yml` 里已有独立 job **`webui-e2e`**：装 Chromium（`playwright install --with-deps chromium`）
并跑 `pytest -q -rs -s tests/e2e/`；`test` 作业则跑 `tests/webui/`（真服务器黑盒）与全量 pytest。
下面保留一份等价片段，便于迁移到其它 CI。

现有 `test` 作业已经会收集 `tests/e2e`：没装 Playwright 时这些用例全部 **skip（BLOCKED）**，
`-rs` 会把理由打进日志 —— 也就是说"没装浏览器"不会让流水线变红，但会**如实报 BLOCKED**。
要让浏览器 E2E 真跑，加一个独立阶段：

```yaml
  webui-e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - uses: actions/setup-go@v5
        with:
          go-version: "1.22"
      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: "17"
      - uses: dtolnay/rust-toolchain@stable
      - name: Install dependencies
        run: |
          pip install --upgrade pip
          pip install -r requirements.txt pytest pytest-asyncio ruff
          pip install playwright
          playwright install --with-deps chromium
      - name: Plugin WebUI browser E2E (real Chromium + real plugins)
        run: pytest -q -rs tests/e2e
        env:
          E2E_SCREENSHOT_DIR: ${{ github.workspace }}/e2e-screenshots
      - name: Upload E2E screenshots
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: webui-e2e-screenshots
          path: e2e-screenshots
          if-no-files-found: ignore
```

> 建议把 `webui-e2e` 单独成 job（不要塞进 `test` 矩阵）：浏览器下载与系统依赖（`--with-deps` 需要 sudo）
> 只在 Ubuntu 上做，且失败时能一眼看出是浏览器链路的问题。
