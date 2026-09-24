# Changelog

本文件记录 Flowerie_bot 的版本变更。版本号遵循 [Semantic Versioning](https://semver.org/)。

> **维护状态：停更一年（2026-09-04 起）** —— 仓库不归档；停更期间的兼容性维护以 2.2.2xx 递增发布。
> 早期版本的日期为补记（以版本号顺序为准）。

**版本速览**：2.2.22222 · 2.2.2222 · 2.2.222 · 2.2.2 · 2.2.0 · 2.1.4 · 2.1.2 · 2.1.1 · 2.1.0 · 2.0.1 · 2.0.0 · 1.7.0 · 1.6.0 · 1.5.0 · 1.4.0 · 1.3.0 · 1.2.0

---

## [2.2.22222] - 2026-09-25

> 维护性更新（停更期间）：**无破坏性变更** —— 安全整改 + 原生多条回复 + Milky 能力补齐 + Web UI 修复 + 文档；
> 新能力均默认关闭，关闭时行为与之前完全一致。

### 安全 —— Code Scanning 全量审计（6 类真漏洞修复并关闭）

- 逐条审计 7 类规则共 56 条 open 告警：修复 6 类真漏洞，18 条已举证误报经 API 标记 `dismissed`，其余 32 条如实保留为 open 并标注「暂时无法证明」——**不以清零为目标**
- 越界删除：`PluginManager.uninstall` 可直接用 WebUI 传入的 `../` id 拼路径 `rmtree`；`_file_*` 的包含性检查拿「id 推导出的 base」去比，等于没查 → 新增 `_PLUGIN_ID_RE` + `_plugin_base()`（先校验 id，再对 `plugin_dir` 做 realpath + commonpath），并把净化内联到 sink 同函数
- ReDoS：CQ 码正则的两层 star（嵌套量词）划分不唯一 → 指数回溯（实测 40 个逗号卡死进程）；终版改为单一字符集重复（全模式仅一个量词）+ `_cq_parts` 切分（形状可证线性，不靠引擎优化）
- 日志泄露：验收脚本不再回显密钥片段（日志实参只允许由比较得到的布尔结论挑常量文案）
- 测试里 `tempfile.mktemp` → `mkstemp`；两个 workflow 补 `permissions: contents: read`
- 新增 6 个回归测试文件 / 26 条：SSRF 三层防线顺序、越界 id 全拒、正则形状不变量与仓库级「量词套量词」闸门、站内重定向前缀不变量、日志不得含敏感派生表达式、静态资源文件名白名单
- 报告：`docs/archive/code-scanning-report.md`；逐条判定与残余风险：`docs/security.md`

### 新增 —— 原生多条回复（Multi-Reply）

- **一次回复拆成 1~N 条独立消息逐条发送**，默认关闭（关闭时行为与之前完全一致）
- 新增核心对象 `ReplyPlan`（`src/core/reply_plan.py`）与协议无关的发送编排
  `send_plan`（`src/core/reply_sender.py`）：只接收"怎么发一条"的回调，所有协议共用同一套；
  间隔用可注入的 sleep（可测），失败策略 stop/continue，`MultiReplyError` 携带已发送条数
- SDK：`Bot.send_many` / `Bot.reply_many` / `Event.reply_many`（`src/sdk/` 与 `plugin_sdk/` 双份同步）；
  插件动作 `send_many`（权限同 `send_message`），插件侧不必自己写 for 循环
- AI：模型可输出 `{"messages": [...]}` 结构化多条（允许 json 围栏）；**未开启开关或解析失败一律降级单条**，
  不做换行/标点猜测；提示词仅在开启时注入，并写明条数与每条字数上限
- 配置：`MULTI_REPLY_ENABLED` / `MAX_MESSAGES` / `INTERVAL_MODE` / `MIN_INTERVAL` / `MAX_INTERVAL`
  （进 `config_schema.SCHEMA` → Web UI「配置 → AI」自动出现，热更新）
- 限制不被绕过：条数受 `MULTI_REPLY_MAX_MESSAGES` 约束，且**每条都计一次连续回复**，
  因此 `MAX_CONSECUTIVE_REPLIES` 与冷却照常生效
- 顺手拆分防上帝类：`reply_dispatch.py`（回复分发 mixin）与 `ai_guard_mixin.py`（AI 准入守卫）
  从 `message_router.py` 拆出（682 → 635 行，上限 650）

### 测试

- 新增 `tests/test_multi_reply_core.py`（14）、`tests/test_multi_reply_sdk.py`（4）、`tests/test_multi_reply_ai.py`（5）

### 变更 —— Milky 协议能力补齐

- 出站调用统一入口 `Sender._post`：Milky 模式统一做动作名映射（36 个端点）、Bearer 鉴权、字符串消息自动转 OutgoingSegment 数组；主发送路径不再绕过统一入口（端到端测试抓到的真 bug）
- 能力缺失显式化：`_MILKY_UNSUPPORTED`（9 项）不发请求、直接返回明确错误，便于上游如实降级
- 新增 `tests/test_milky_mapping.py`、`tests/test_milky_end_to_end.py`（假协议端全链路，含 Multi-Reply）
- 文档：`docs/milky-protocol.md` 同步官方 API（协议 1.3，5 组 65 动作），并列出尚未接线的 32 个动作

### 修复 —— Web UI

- **花语记忆总开关 OFF 时整组不再渲染**：此前模型/密钥/参数 14 个键照旧显示（与渲染层注释「总开关 OFF → 全部配置不渲染」不符）；现在 OFF 只留总开关 + 一行提示，ON 后全部展开
- 主题液态玻璃导致的 1px 排版塌陷（选择器断行）

### 文档

- 精简 Code Scanning 审计报告（96 → 47 行）与安全文档小节，事实一条不丢
- `docs/api.md` 由 `scripts/gen_api_md.py` 重生成（161 方法）
- 版本号 / 测试数 / 目录结构等过时表述同步（测试数 1045 → **1121**）

### 测试

- CI：Python 3.9 / 3.12 + PostgreSQL；`ruff check` + `pytest` + 验收脚本；当前 **1121 个测试**

---
## [2.2.2222] - 2026-09-17

### 新增

- **首次启动释放的 .env 模板与 Web UI 配置页同源**：新增 src/services/env_template.py，
  以 config_schema.SCHEMA 为单源渲染（21 个分组标题 / 165 项配置各自的说明 / 必填·密钥·需重启 三类标记），
  替代原先只取 pydantic Field.description（大多为空）的导出——构建产物首次运行释放的 .env
  现在与手工维护的 .env_example 同样详细，且两处永不漂移。
  main._default_env_text 改为调用该模块（旧实现 1563 字符 -> 345 字符）。

- **任意语言插件（`runtime: "exec"`）13 种语言实测**：仓库新增 `tests/plugins/multilang/`（C · C++ · Go · Rust ·
  Java · C# · Kotlin · PHP · Lua · Ruby · Perl · R · TypeScript，每种一份最小可运行插件）与
  `tests/test_plugin_multilang.py`——CI 里**逐语言真实编译 + 启动子进程**跑完整协议
  （initialize 握手 → message 事件 → 断言返回值 → shutdown），缺工具链则自动 skip（不误报失败）；
  `ci.yml` 补装 `lua5.4` 与 `r-base-core`（runner 镜像自带其余 11 种），13 种**全部真实执行**。
  JVM/.NET/tsc 三类用 3 行 `run.sh` 包装（产物不是可执行文件），脚本语言走 shebang + 执行位。

### 变更

- **Web UI 默认开启（仅本机回环）**：`WEB_UI_ENABLED` 默认 `false → true`（`.env_example` 同步），
  而 `WEB_UI_ALLOW_LAN` **仍默认 `false`** —— 只监听 `127.0.0.1`，不对外暴露；
  首次启动进入注册页创建管理员即可。配套加固：Web UI 端口被占用时只记错误日志、
  bot 继续运行（此前默认关闭，不会遇到这种情况）。
- **默认模型统一为 deepseek-flash**（聊天 / 视觉识图 / 引战检测）：
  官方 /models 当前只提供 deepseek-flash 与 deepseek-v4-pro，
  原默认 deepseek-v4-flash 与视觉默认 deepseek-v4-flash-vision-exp 均已不在列表中。
  VISION_MODEL / TOXIC_MODEL 由此前的「留空回退 DeepSeek」改为显式默认值（回退语义不变）。
  已存在的 .env 与 settings.db 里的旧模型名不会被默认值覆盖，需自行更新。
- **Web UI 平板 / 电脑排版修复（随 2.2.222 合入主线）**：外观页「卡片效果」与人格页「当前绑定」
  两处 .row 嵌套解除 —— 桌面端标签回到左标签列并带上分隔线，手机端渲染逐项一致。

### 文档

- **新增 **插件开发指南 §31「任意语言插件」**（13 种语言完整最小实现）**：exec 协议三分钟说明、
  目录与 manifest 字段表、**13 种语言逐份完整最小实现**（源码与 CI 实测夹具逐字一致）、构建与入口速查、
  按出现频率排序的排查清单、不用真 QQ 的自测方法 —— 目标是不用 Python/Node 也不用扒源码。
- **本轮文档整理（去重 + 更新过时）**：`docs/sdk.md` 把散落两处的三张能力矩阵
  （端点映射/权限、网关兼容、v2.1 缺口台账）收拢为**附录 A**（内容一行未减），并修掉重复的 `## 14` 编号、
  头部版本号（v1.3.0 → 当前）；`docs/web-ui.md` 更新「相关文件」表（模板/CSS/静态路由/渲染层）与
  分辨率自适应五档断点、缓存策略；`docs/development.md` 目录树补 `templates/` `static/` `assets.py`
  `webui_static.py` 与测试数；`docs/README.md` 同步各文档范围；README 徽章与测试数同步 1038 → 1045。

- 全量同步过时文档：README / docs 索引 / Web UI 文档的版本号、runtime 说明（补任意语言 exec）、
  页签数（七个 -> **八个**，补「群昵称」）；插件开发指南新增 §4.5 与 §31（13 种语言清单 + 落地经验）。
- **文档去重与死链修复**：根目录 `AUDIT.md` 与 `docs/archive/architecture-audit.md` 内容 90% 重复，
  已合并为后者一份（保留两版各自的独有章节）并删除根文件；修复 3 条死链
  （README / development.md 指向已移动的 architecture-audit.md 与 qwq-final-report.md）；
  README 由 263 行精简到 222 行（Web UI 页签详解、插件链接三连、文档目录等改为指向权威文档），
  **所有被删细节均已确认存在于对应权威文档**；测试数与版本号等漂移值同步（930 → 1038）。


- **Web UI 改用标准 HTML 文件**：面板的 CSS 与页面壳从 Python 字符串搬到真实文件
  （`src/services/webui_render/static/panel.css` + `templates/*.html`），Python 只填 `{{占位符}}`；
  每页体积 ~17KB → ~1.1KB，CSS 变成可缓存外链；新增 `/panel/static/{name}` 路由
  （文件名白名单防穿越 + `?v=内容指纹` 长缓存）；PyInstaller 补 `--add-data`，
  `static/` 与 `templates/` 会打进发布包（不改会发布即白屏）。
- **分辨率自适应（PC / 平板 / 手机）**：补齐五档断点 —— 宽屏 PC ≥1440px 内容区放宽到 1200px、
  平板横屏 861~1023px 收紧内边距、平板竖屏 ≤860px 全部堆叠单列、手机 ≤720px 按钮全宽与字号收紧、
  小屏 ≤420px 主题卡单列；静态审计确认**无任何 ≥320px 的固定宽度**（360px 手机不会横向溢出）。
- **面板不再被浏览器缓存**：aiohttp 默认不发缓存头，浏览器会启发式缓存整页 HTML，
  导致「代码更新 + 进程重启，页面还是旧布局」；现在对 HTML 统一发 `Cache-Control: no-store`
  （静态资源照常缓存），并在面板页脚显示**样式指纹**便于核对服务端版本。

### 修复

- **登录页看不到输入框（严重）**：面板 CSS 文件里保留着 `{{THEME_VARS}}` 占位符（本该由 Python 注入
  `.theme-default{--input-bg:...}` 等主题变量），但静态路由把文件**原样**返回 → 变量整段失效 →
  `input` 的背景/边框解析失败变成「透明无边框」（看起来就是没有输入框），按钮 `background:var(--accent)`
  失效 + `color:#fff` 变成白底白字。现改由 `panel_asset_body()` 返回**注入变量后**的 CSS，并加回归测试。
- **改了服务端浏览器仍用旧样式**：CSS 曾设 `immutable/max-age=1年`，而「资源怎么生成」变了、文件内容没变时
  URL 不变 → 浏览器永不回源（手机上还无法强刷）。现：① 缓存策略改 `no-cache + ETag`（每次回源校验，未变 304）；
  ② 引用 URL 追加**资源代际** `?v=<内容指纹>-<代际>`，代际一变 URL 就变，用户零操作拿到新样式。
- **面板 HTML 被浏览器缓存**：aiohttp 默认不发缓存头 → 出现「代码更新＋进程重启，页面还是旧布局」。
  现对 `text/html` 统一发 `Cache-Control: no-store`（背景图等静态资源照常缓存），面板页脚显示样式指纹。
- **按项目护栏拆分**：`web_ui.py` 触到 430 行上限（防上帝类回归），新增 `src/services/webui_static.py`
  承载静态资源路由与 `no-store` 中间件，`web_ui.py` 433 → 394 行（不放宽限制）。

- **Web UI 响应式布局（宽屏/平板/手机自适应）**：此前只有 720px/420px 两个断点，平板宽度（800~1000px）没有适配。
  现在补齐 980px/860px 断点，并把 `.row` 从「flex + 固定 300px 标签列」改为
  `grid: minmax(180px,260px) minmax(0,1fr)`，窄屏自动堆叠为单列。
- **启动横幅换字体**：ASCII 艺术字由 figlet `standard` 换成 `big`。原字体的 `W` 顶部断开成两截
  （看着像两个 V），而旁边的 O/E/R 都是紧凑方块，所以特别突兀；`big` 的 W 中间相连、一眼可辨，
  宽度 60 列（80 列终端仍放得下），纯 ASCII 红线不变。
- **同类缺陷一并修掉**（审计出的 5 类、18 处）：
  1. 裸 `<table>` 没有样式（只有 `.plugin-table` 有）→ 列宽塌缩成竖条；
     现为所有 `table` 补基础样式（边框/表头底色/单元格间距），群规则表与群昵称表加类名与 thead/tbody；
  2. `<pre>` 没有样式 → 示例文本横向溢出；现改为自动换行 + 底色 + 圆角；
  3. `.row` 只放标签列（右边空一半）→ 管理员规则列表改为 `<ul class="rules">` 卡片式列表，
     插件配置说明行改用 `.row.single` 整行铺满；
  4. 13 处写死的 `style="max-width:NNNpx"` → 改为宽度工具类（`.w-sm/.w-gid/.w-md/.w-lg`），
     窄屏自动变全宽；
  5. 行内混排的「群号 + 下拉 + 按钮」表单 → 改为 `.form-inline` / `.rule-add` 网格，窄屏堆叠。
- **群特色昵称页改为卡片式**：原来是「群号 / 人设 / 专属昵称」三列表格，宽屏上很散；
  现为响应式卡片网格（`auto-fill minmax(260px,1fr)`），每张卡片显示群号 + 人设徽标（群级/具体人设）+ 昵称输入框，
  底部「新增 / 覆盖」也是卡片。表单字段名不变（`nick_<gid>` / `nick_<gid>__<persona>`），行为与测试断言不变。

### 测试

- 新增 tests/test_env_template.py（10 用例，纯函数、零第三方依赖）。
- 新增 tests/test_plugin_multilang.py（13 种语言参数化黑盒端到端 + 夹具自检）与
  tests/test_banner.py（16 用例）；CI 的 pytest 计数 **930 → 1038**，跳过数 **0**。
- **发布流程加固**：资产上传由 `softprops/action-gh-release` 改为逐文件 + 重试
  （`gh release upload --clobber`，每文件最多 5 次）——此前 GitHub 偶发 500（Unicorn 错误页）
  会中断整步，出现「11 个资产其实都传上去了、job 却是红的」假失败。

## [2.2.222] - 2026-09-17

### 新增 —— 任意语言插件（runtime: "exec"）

- **插件语言不再受限**：entry 直接作为进程执行（编译产物，或带 shebang 的可执行脚本），
  主进程**不经 shell、不假设任何语言** —— Go / Rust / C / C++ / C# / PHP / Ruby / Java / JS / TS……
  只要实现同一套 stdin/stdout JSON-Lines 协议（Plugin API v1），它就是合法插件
- **多平台分包**：新增 platform（any/linux/windows/darwin/android）与 arch（any/x64/arm64/x86）
  两个 manifest 字段（**仅 exec 允许声明**）；与宿主不匹配时拒绝启用，并说明具体原因
- **入口大小分级**：脚本类（python/node）保持 1MB 上限；exec 编译产物放宽到 **32MB**
  （解压后总量仍受 50MB 上限约束）
- **执行位自动补齐**：ZIP 安装与运行时各补一次 chmod +x（Windows 无需）；
  不支持执行位的文件系统（FUSE/sdcardfs）会给出可操作提示
- **零行为变更**：python / node / json 三种 runtime 完全不受影响；权限模型、进程隔离、
  超时与输出上限一律照旧

### 新增 —— Web UI 平板 / 电脑排版修复

- 外观页「卡片效果」与人格页「当前绑定」两处 .row 嵌套解除：
  桌面端标签回到左标签列并带上分隔线，手机端渲染逐项一致

### 测试

- 新增 tests/plugins/minimal_exec_plugin/（POSIX shell 插件）：真启动子进程、真跑
  initialize / event / shutdown 协议，证明「任意语言无需语言专用 runner」
- manifest 测试补齐 exec 的平台/架构校验、非法值拒绝、平台不匹配用例


## [2.2.2] - 2026-09-04

> 📦 **封版（最终版）——维护状态：停更一年（2026-09-04 起）**
>
> 由于 bug 太多懒得修，本项目封版停更一年，来年再更新。**仓库不会归档**，来年见。
> **已发布版本也不保证可用性**；期间遇到问题可提 Issue（不保证修复）。

### 修复

- `VISION_ENABLED` 识图总开关（SCHEMA 注册修复）
- `/panel?tab=nicknames` 白名单修复（点「群昵称」跳配置页的 bug）

### 本版内容

- 群昵称 × 人设隔离 / 用户状态页连通性测试 / OneBot 兼容 全量

## [2.2.0] - 2026-09-03

> 🔄 **维护状态：恢复更新**（此前 v2.1.4 的"停更一年"说明撤销——Flowerie 继续开发）

### 新增 —— OneBot v11 全平台兼容（本版核心）

- **图片识图 file 优先**：`image.file` 标准字段本地读取（绕开 NT CDN 302/UA/引用过期——真·换实现不用改代码）；
  URL 兜底；`file://` / 相对路径容错
- **发送通道 auto**：`SEND_VIA_WS=auto`（默认）WS 优先 → HTTP 自动回退；`true/false` 显式；旧布尔配置兼容
- 连接三模式（反向 WS / 正向 WS / HTTP）；能力探测 + 明确降级（无端点显式报错）
- docs/onebot-compatibility.md 兼容矩阵

### 修复

- `_use_ws` 布尔 `False` 被 `or` 短路成 auto（旧布尔配置失效）→ 显式布尔关闭正确

### 兼容声明

> NapCat / Lagrange / LLOneBot / Koishi 等 OneBot v11 实现：同一 Flowerie 直接跑；能力有的用、没有显式报错。

## [2.1.4] - 2026-09-02

> 📦 **维护状态：停更一年（2026-09-03 起）**——由于 bug 太多懒得修，本项目停更一年，来年再更新。
> 已发布版本可继续使用；期间遇到问题可提 Issue（不保证修复）。

### 修复 —— 实战验证（Termux 真机）

- **WS 发送通道**（`SEND_VIA_WS`）：NapCat 只开 WebSocket（不开 3000 HTTP）也能发消息；
  OneBot action/echo 请求-响应匹配；HTTP 路径保留（默认 false 零行为变化）
- **图片识图恢复**：NT 图 URL 302→CDN 重定向（每跳 SSRF 校验跟随）+ 浏览器 UA/Referer
- **名字唤起必回**：文本含 `BOT_NICKNAME` / 群特色昵称 = 点名（不带 @ 也必回）
- **日志落盘修复**：RotatingFileHandler 不建目录 → 自动建 `logs/`（之前静默无日志文件）
- sender 失败输出完整原因（`message_send_action_failed`）+ vision `last_error`
- websockets 新版 ServerConnection 兼容

## [2.1.2] - 2026-09-02

### 修复 —— 配置列表持久化双格式崩溃（`config_persisted_apply_failed`）

- **根因**：Web UI 保存列表到 settings.db 为 JSON 数组（`[786368680]`），启动 `apply_persisted`
  的 `_coerce` / `_validate` 仅按逗号 split → `ValueError`（ALLOWED_GROUP_IDS / TOXIC_GROUP_IDS）
- **修复**：list-int / list-str 均「JSON 数组优先（元素类型校验）+ 逗号列表兜底（.env 旧写法）」
  ——与 pydantic（`List[int]` 强制 JSON）双向兼容，两种 .env 写法都能启动
- 回归：`test_coerce_accepts_json_list_from_db`（coerce/validate 双格式钉死）


## [2.1.1] - 2026-09-01

### 新增 —— 群特色昵称（BOT_NICKNAME 按群隔离）

- 每个群可设专属称呼（Web UI 新增「群昵称」tab：列表/新增/批量改/留空恢复默认，零 JS）
- 注入链：group nickname store（`./data/nicknames.json`，原子持久化 / ≤20 字 / 控制字符剥离）
  → AiGateway → 常规与工具路径 → system prompt【本群专属称呼】段（与默认相同不注入 = 零行为变化）
- 指令菜单随群昵称；默认仍为 `BOT_NICKNAME=花璃`
- 配置：`GROUP_NICKNAMES_PATH`（schema 注册）；与 Web UI 共享同一 store 实例
- 一致性加固：动作表↔Sender 方法、NS↔端点、动作↔权限映射 三项防回归测试（poke 类断链永久拦截）

### 修复

- poke 群戳路由（`send_poke` 端点实际存在——能力不再被"无端点"埋没）
- webui_panels 导出遗漏（NicknamePanelMixin）、message_router 行数守护（650）/ is_secret 类评审发现 4 项
- 图片 SSRF 默认拒绝私网/元数据 + 登录限速对面板登录生效（安全加固）

## [2.1.0] - 2026-09-01

### 新增 —— Plugin WebUI（插件自有管理控制台，零 JS 红线）

- 受控 DSL：25+ 组件 / 页面 / tab / breadcrumb / 文件 / 权限（`web_ui` + `web_ui.files`）
- 渲染器先转义后结构化；URL scheme / 属性 / style 白名单；上传魔数·大小·名称·穿越 四道闸
- `webui_page(page, action, params, values)` hook（4s 超时 / 异常降级）；路由 GET/POST 零 JS 重渲染
- 一致性钉死：docs 组件表 ↔ 渲染器双向（`test_plugin_webui_consistency`）

### 新增 —— API/SDK 缺口池全覆盖（~180 项）

- PluginApi 60 → **160 个语义方法**（消息/好友/群/社交/文件/AI/Memory/MCP/插件/Web/数据/运行时/开发）
- 无端点能力一律**显式** `not supported in v1`（绝不静默、绝不假功能）；可用者为本地实现或复用生产客户端
- SDK：gap_sdk 层（分面 ai/memory/mcp/db/cache/task/i18n/config/mock + 上下文 + TaskManager 专用后台 loop 真跑）
- Matcher 组合器 `rule_or` / `rule_all` / `rule_not`（主进程 any_of/all_of/not 真支持）
- 权限 +2（`plugin_admin`）；`scripts/gen_api_md.py` 自动生成 api.md（永不漂移）

### 修复 —— 全库白盒 Review（28 条发现）

- **启动崩溃**：config.py 错位校验（启用花语记忆 + 重排即 NameError）
- **功能失效**：`sender._headers` 未定义（表情包图片发送）、语义记忆检索死代码、`group_res` 参数名、
  PluginRuntime hook 通道缺失（WebUI 页 / 插件互调）、重复回复误杀、纯记忆回合重试空转
- **安全**：图片下载 SSRF（默认拒绝私网/元数据/重定向）、登录限速失效（爆破）、Excel zip 炸弹预检、
  MCP 鉴权头透传、跟踪日志路径、sticker 上下文清洗、service 注册名校验

### 测试

- **930 单测（CI pytest 3.9/3.12 + PG）+ 37 项黑盒验收** 全绿；本轮新增黑盒/白盒 ~120 项
  （真进程黑盒、白盒审计 37、一致性 6、DSL 安全 19、文件 11、gate 8 等）

## [2.0.1] - 2026-08-31

### 修复 ——"保存被拦截 / 关不掉 / 什么都没填也报错"

- **根因**：`BLOSSOM_MEMORY_*_API_KEY` / `DATABASE_URL` 为 secret 型但 `is_secret=False`
  → 空/短值不过保密跳过 → 误报"值不合法"；修复后扫描 0 残留
- `_chain_needs_secret` 优先读本次提交值（区分关闭开关 vs 错误提交）
- 每日提取上限放宽 (0,500)；全配置保存路径回归测试补齐

## [2.0.0] - 2026-08-30

### 架构重构（v2 主线）

- 语义层与 OneBot 低耦合：端点串只在 `sender.py` + 适配层；语义层零 `/send_` `/get_` 字符串
- Web UI 零 JS 化（HTML + CSS + 表单）；模型 / API 配置行链状态徽标
- 花语记忆：SQLite 默认 + PostgreSQL 可选；BlossomMemory（向量 / 重排 / 每日限额 / 提取）
- 配置保存智能：保密跳过 / 热重载分组 / 校验提示


## [1.7.0] - 2026-08-29

### 新增 —— 拉格朗日能力对齐 + 低耦合

- 群文件 / 公告 / 精华 / 荣誉 / 资料（`group_folder_*`、`group_notice_*`、`essence_list` 等 ~15）
- `_SENDER_ACTIONS` 转发表（22+ 动作 → 端点；参数白名单；不支持显式报错）
- SDK 语义门面（`group(user)` / `user(me)` / 顶层动作）；OneBot 端点耦合审计测试

## [1.6.0] - 2026-08-28

### 新增 —— Web UI 开关治理 + 持久记忆

- 面板全部配置组可折叠（零 JS `details` 元素）；开关状态可视化；余额预警
- 持久记忆（SQLite；可选 PostgreSQL）；LivingMemory → 花语记忆 BlossomMemory
- 文档二层结构：quick-start（10 分钟）+ 完整参考分离

## [1.5.0] - 2026-08-28

> 注：本版内容原并入 1.6.0 段，本次整理按语义归位。

### 新增（能力对标主流网关；形态自有——语义化分组上下文，端点只在适配层）

- **群操作上下文** `bot.group(gid)`：members / member / mute / kick / set_admin / whole_ban /
  rename / set_card / set_title / send_notice / get_notice / files / files_in / file_url / config /
  config_set / pin / unpin / resource
- **用户与自我**：`bot.user(uid)`（like / tap / card / info）、`bot.me`（info / devices / status / profile）
- **顶层语义动作**：`bot.tap`（戳）/ `bot.emoji`（表情回应）/ `bot.pin` + `bot.unpin`（精华）/
  `bot.like` / `bot.friends`
- **富内容 Builder**：`BotMessage().card(json)` / `.markdown(text)` / `.button(label, action)`
  （合并 keyboard 段；底层转 json/markdown/keyboard 段，网关支持度见 sdk.md 兼容矩阵）
- 权限新增 `bot_profile`（改 Bot 资料）；群写复用 group_manage、读复用 read_group_info、
  好友/自我复用 read_user_info（总计 23）
- 管理端 `_SENDER_ACTIONS` 转发表（22 语义动作 → Sender 端点；参数白名单清洗；
  不支持端点返回明确错误——换网关即激活）

### 修复

- **`_handle_action` 权限拒绝解析错误**：拒绝响应此前被伪装成 `ok=True`（插件误以为成功）
  ——现在原样回传 `{ok: False, denied: True, error}`
- **SDK 注册动作失败不再阻断插件启动**：matcher / schedule 注册被拒时降级为日志

### 测试

- +6：语义动作转发表（18 组端点参数断言）、不支持端点语义、权限拒绝传播、
  SDK 分组上下文转发、富 Builder 出段合并；本地 152 通过、ruff 0

## [1.4.0] - 2026-08-27

### 新增（高频能力补齐；原则：OneBot 已有直接包装，没有的自造但要轻）

- **请求处理**：好友 / 加群请求同意与拒绝（`handle_friend_request` / `handle_group_request`）
- **定时任务**：`bot.schedule(interval=60 / delay=10 / daily="09:30")`；
  主进程轻量调度（asyncio Task，无 cron 依赖）；`schedule_cancel` / `list`
- **等待与多轮**：`bot.wait_for` / `ask` / `confirm` / `select`（插件侧 Session）
- **命令系统**：`event.args`（shlex 参数拆分）；子命令 = 命令名含 `.`；
  `bot.cool_down(key, seconds)` 命令级冷却（限频 / 防刷）
- **KV / 插件缓存**：`bot.kv_get/set/delete/list`（plugin_kv 表按插件隔离；权限 storage）
- **HTTP 扩展**：PUT / DELETE / HEAD（复用既有 SSRF 防线）+ `http_download`（≤10MB 落插件目录）
- **记忆**：`mem_update` / `mem_clear`
- **AI（受限）**：`bot.ai_chat(message, system)`（权限 ai_chat；独立于聊天预算，建议自限频）
- **工具类**：`random_choice` / `random_int` / `now` / `format_time`（内建）
- **多媒体消息**：`BotMessage` 支持 `video()` / `voice()` / `file()`（可带名字）/
  `add_segment()`（通用段，如键盘 UI 平台相关透传）
- 事件负载 + `trace_id`；`event.trigger` / `schedule_id`
- 权限新增：`request_handle` / `scheduler` / `storage` / `ai_chat`

### 修复

- 插件事件负载真正领域化（`kind/scope/text/at_list/images`；CQ 码在下层阉割）；
  `_plugin_event_type` 返回领域 kind（不再 group_message / meta_event）
- `route` 等待队列先于 api 检查（wait_for 未 attach 亦可接收）
- delay 调度触发即清理；shutdown 清理全部调度任务（防泄漏）

### 测试

- +14：KV 往返/隔离、请求处理、调度注册/触发/cancel/list、工具、HTTP 扩展、AI（注入与未注入）、
  记忆、cool_down、args（引号）、等待消息（命中与超时）、schedule 装饰器与路由、多媒体 Builder；
  本地 147 通过、ruff 0

## [1.3.0] - 2026-08-27

### 新增

- **Bot SDK（插件生态第一阶段，三层架构）**：
  - 上层 `plugin_sdk/flowerie_sdk/`：FlowerieBot（send / reply / recall / get_message /
    get_context / 群 API / 权限）+ Matcher 装饰器（command / keyword / regex / prefix / exact）
    + Builder（add_text / at / image / reply）；插件零依赖 HTTP / JSON / SQLite，不接触 OneBot payload
  - 中层 `src/sdk/`：BotEvent（kind/scope 领域语义，零 OneBot 命名）/ BotMessage /
    Matcher（priority 大者先 + block + 可扩展 Rule）/ EventDispatcher（优先级 / 异常隔离 /
    stop / shutdown）/ PermissionChecker（user / group_member / group_admin / group_owner /
    bot_admin / bot_owner，复用 ADMIN_QQ_IDS）/ BotAdapter 抽象
  - 下层 `src/sdk/onebot/`：DTO 瘦身 + Transformer（OneBot raw → BotEvent，CQ 码阉割为
    at_list / images / reply_id；BotMessage → 段数组出站）+ OneBotAdapter（复用 Sender；
    错误统一 BotError 体系：BotAPIError / BotTimeoutError / BotPermissionError /
    MessageNotFoundError / UnsupportedOperationError）
- **消息 API 扩展**：send_reply（引用回复）/ delete_message（撤回，仅限本 bot 已发送记录）/
  get_message / get_group_history / get_context（复用 ContextManager）
- **群 API**：get_group_member(s) / is_group_admin / is_group_owner / group_ban / group_kick（OneBot11）
- **事件投递领域化**：kind / scope / text / at_list / images / reply_id / notice_kind；
  notice / request / lifecycle 钩子（on_notice / on_request / on_lifecycle）
- 新权限：delete_message / read_message_history / group_manage
- 文档：docs/sdk.md（三层架构与 API）、docs/api.md（API 总表）、docs/plugins.md（插件开发入口）

### 变更

- 插件事件负载字段（post_type / message_type / notice_type / sub_type →
  kind / scope / notice_kind；CQ 段不再下沉，改用 at_list / images）
- `NAPCAT_WS_AUTH_MODE`（header / query 互斥鉴权，默认 header 单通道）见 v1.2.x 说明

### 测试

- 新增 SDK 测试（+24）：BotMessage / Transformer CQ 阉割 / Event kind 映射 / Matcher 5 型
  + priority + Rule async / Listener 优先级·隔离·stop / Adapter 错误语义·超时·context
  复用 / Permission / 端到端 SDK 插件（@command → event.reply 全链路 + 未命中不投递）
- 并发 100 事件 / matcher 不互相污染

## [1.2.0] - 2026-08-26

### 新增

- **插件系统（Plugin System v1）**：受控插件运行时。导航栏新增「插件」页（Web UI）。
  支持 Python（`plugin.py`）、Node.js（`index.js` / `package.json`）与 JSON 声明式插件
  （`runtime=json`，`declarations` 规则，无代码执行）。
  安装途径：Web UI 上传 ZIP / URL 下载安装（SSRF 防护 + 大小限制）、本地目录 `plugins/` 自动发现
  （发现 ≠ 自动执行，默认 disabled）。插件运行在独立子进程（`python -I` 隔离 / `node` 子进程），
  stdin/stdout JSON-Lines 协议，崩溃 / 超时被隔离标记 `crashed`。
  相关配置：`PLUGIN_DIR` / `PLUGIN_PROTECTION` / `PLUGIN_URL_MAX_BYTES` / `PLUGIN_URL_TIMEOUT` /
  `PLUGIN_ZIP_MAX_UNZIPPED_BYTES` / `PLUGIN_ZIP_MAX_FILES` / `PLUGIN_MAX_COUNT`。
  详见 [docs/plugin-developer-guide.md](docs/plugin-developer-guide.md)。
- **第三官方人格「艾拉（Isla）」**：内置 persona `id=isla`（《可塑性记忆》风格原创改编，
  不复制原作台词，温柔克制 / 自贬 / 关键时刻决断路线），与 flowerie / atri 并列。`PERSONA_DEFAULT=flowerie` 保持默认。
- **管理员补充发言规则配置**：`ADMIN_RESPONSE_RULES`（每行一条；Web UI「人格」页编辑；
  优先级：安全策略 > 人格 > 人格内置规则 > 本条；不能覆盖安全策略）。
- **主动发言概率配置化**：`PROACTIVE_MESSAGE_*` 全套（上下文随机回复概率全部可配置）与
  `ACTIVE_CHAT_PROBABILITY` / `ACTIVE_CHAT_INTERVAL_MIN/MAX_SECONDS` /
  `ACTIVE_CHAT_CONSECUTIVE_COOLDOWN_SECONDS`。默认值 = 原硬编码值，行为零变化。
- **NapCat WebSocket 正向模式**：`NAPCAT_WS_MODE=forward`（Flowerie 客户端连接 NapCat 正向 WS，
  需 `NAPCAT_WS_URL=ws://` 或 `wss://` + 可选 `NAPCAT_ACCESS_TOKEN` 鉴权），
  含超时 / 重连退避 / 心跳 / 连接失败处理。

### 变更

- **发言规则配置化**：说话风格规则归属各 Persona（`system_prompt` 内嵌），新增管理员补充规则 `ADMIN_RESPONSE_RULES`；
  全局规则仍以「全局说话风格 & 标点规则」最高优先级注入。
- **Web UI**：面板页签由六个增至七个（新增「插件」）；「人格」页新增管理员补充发言规则编辑；
  「用户状态」页新增修改登录账号表单；「配置」页新增主动发言概率与 NapCat WS 配置。
- **版本号**：1.1.0 → 1.2.0。

### 安全

- **Web UI 注册 Bootstrap Lock**：系统一旦初始化（`.env` 或 `settings.db` 存在管理凭据），公开注册永久关闭
  （GET/POST `/panel/register` 与 `/api/register` 一律 403 / 展示「注册已关闭」）；
  只有 `UNINITIALIZED` 状态才能注册第一个管理员；并发注册用 `admin_bootstrap` 表原子 CAS 保证仅一个成功；
  改账号走登录态 `/panel/account/credentials`（需当前密码）；注销（`/panel/account/unregister`，需当前密码）
  = 显式重置回到 `UNINITIALIZED`；历史已有凭据自动视为已初始化。
- **插件安全**：安装 ZIP 防护（ZIP Slip / Zip Bomb / 符号链接 / 路径穿越 / manifest 注入）、
  URL 下载 SSRF 防护、权限强制（PermissionManager）、进程隔离、日志脱敏；
  保护级别（`PLUGIN_PROTECTION`）任何级别都不豁免 manifest 校验 / 管理员权限 / 进程隔离 / 日志 /
  崩溃保护 / 资源限制 / 权限检查。
- **NapCat WS token 脱敏**：`NAPCAT_ACCESS_TOKEN` 绝不写入日志（URL 查询串剥离后记录）。

## [1.1.0] 及更早

更早版本的变更记录见 [docs/archive/](docs/archive/) 与对应 Release 说明。

