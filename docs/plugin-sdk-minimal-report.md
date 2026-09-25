# 多语言 SDK 最小化插件实测报告（任务书《插件测试》）

> 任务书：`/storage/emulated/0/插件测试.txt`　·　契约：`docs/plugin-sdk-minimal-test.md`
> 核心要求：**不要证明"SDK 代码存在"，要证明"开发者真的可以用这个 SDK 写出一个能运行的插件"。**

## 1. 交付物

| 层 | 位置 | 说明 |
| :--- | :--- | :--- |
| 最小插件 | `examples/multilang-sdk/{python,typescript,go,rust,java}/` | 每种语言一个极简插件，只依赖该语言 SDK：`ping/get_info/echo/slow/boom/seen` + `test.event` + `/sdk@<自己>` 命令 |
| 构建 | 各语言 `build.sh` / `run.sh` | Build 与 Load 分开：build.sh 真编译进 `.build/`，run.sh 只 exec 产物 |
| 验收 | `tests/sdk/{harness.py,test_minimal_plugins.py,test_minimal_paths.py}` | 真仓库 + 真引擎公开面（discover/enable/start_all/dispatch_event/shutdown）+ 真插件进程 |
| SDK 补齐 | `src/plugins/runner/python_runner.py` | 自定义事件类型（`test.event`）此前会被静默丢弃 → 现在分派给 `on_<event>` / `on_event` 钩子 |

## 2. §十七 验收表

（本机与 CI 的真实结果；`SKIP` 一律写明原因，绝不当 PASS）

| 测试 | TypeScript | Go | Rust | Java | Python |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Build | **PASS** | **PASS** | **PASS** | **PASS** | **PASS**（无需构建）|
| Load | **PASS** | **PASS** | **PASS** | **PASS** | **PASS** |
| Ready | **PASS** | **PASS** | **PASS** | **PASS** | **PASS** |
| Ping | **PASS** | **PASS** | **PASS** | **PASS** | **PASS** |
| Info | **PASS** | **PASS** | **PASS** | **PASS** | **PASS** |
| Echo | **PASS** | **PASS** | **PASS** | **PASS** | **PASS** |
| Event | **PASS** | **PASS** | **PASS** | **PASS** | **PASS** |
| Call | **PASS** | **PASS** | **PASS** | **PASS** | **PASS** |
| Error | **PASS** | **PASS** | **PASS** | **PASS** | **PASS** |
| Permission | **PASS** | **PASS** | **PASS** | **PASS** | **PASS** |
| Shutdown | **PASS** | **PASS** | **PASS** | **PASS** | **PASS** |

三条核心链路：**TS → Go**、**TS → Java**、**TS → TS**（见 §4）。

## 3. 本机（Termux 沙箱）结果

`pytest -q tests/sdk/` → **9 passed / 37 skipped**：Python 一列 11 行全 PASS，
其余四种语言**全部 SKIP 并写明原因**（不是 PASS）：

| 语言 | 本机状态 | 原因（缺什么）|
| :--- | :--- | :--- |
| TypeScript | SKIP | **BLOCKED BY ENVIRONMENT**：引擎按环境变量白名单启动插件进程，Termux 前缀里的 node 需要 `libtermux-exec` 的 `LD_PRELOAD` 才能 exec（白名单是安全不变式，不为测试放宽）|
| Go | SKIP | **BLOCKED BY ENVIRONMENT**：本机无 go 工具链（Termux 的 go 在非标准前缀下不可用；官方 tarball 是 ET_EXEC，Android 拒绝执行）|
| Rust | SKIP | **BLOCKED BY ENVIRONMENT**：本机无 rustc（官方 channel 没有 aarch64-linux-android 宿主编译器，且无 cc/ld）|
| Java | SKIP | **BLOCKED BY ENVIRONMENT**：本机无 JDK（Termux 包按 `/data/data/com.termux` 前缀编译，无法在本沙箱运行）|

另外本沙箱 `/storage`（FUSE）不支持执行位、禁止硬链接（容器方案 udocker 因此无法解包镜像）——
这些都不影响验收口径：编译型语言的证据一律以 CI 为准。

## 4. 跨语言链路结果（CI 真跑）

| 链路 | 结果 | 说明 |
| :--- | :--- | :--- |
| **TS → Go** | **PASS** | 最低验收路径：TS 插件 `plugin.call("minimal_go","ping")` 经 Core 到达真 Go 插件 |
| **TS → Java** | **PASS** | 最低验收路径（`echo` 原样返回 `{"hello":"world"}`）|
| **TS → TS** | **PASS** | 最低验收路径：两个真 TS 插件进程（第二实例 `minimal_ts_2`）|
| Python → Go | PASS（扩展）| 任务书"如果对应语言 Runtime 已完成也增加" |
| Python → TypeScript | PASS（扩展）| 同上 |
| Go → Rust | PASS（扩展）| 同上 |
| Rust → Java | PASS（扩展）| 同上 |

- 每条链路都验了：`ping` 的结果、`echo` 的原样返回、以及 **AUTO / LOCAL / CORE 三种路由策略结果一致**（§七）。
- §六 的完整例子（TS 依次调用 Go ping → Java echo → TS2 ping）由
  `test_typescript_chain_go_and_java` 验过。

## 5. §十八 17 问

（待填）


## 5. §十八 17 问

1. **四种语言 SDK 是否真的被实际插件使用？**
   是。`examples/multilang-sdk/{typescript,go,rust,java}/` 各是一个只用该语言 SDK
   （`sdk/<lang>/`）写成的插件；`tests/sdk/` 的每一行结论都来自这些真插件进程，
   不是 SDK 单测、也不是别的语言代跑。
2. **最小插件是否可以独立启动？**
   可以。`tests/sdk/harness.py::standalone_probe` 不经引擎、直接按协议喂
   `initialize → health → shutdown`，断言 14 项能力、`ok:true` 与退出码 0；
   失败时把子进程 stderr 一起带回（`test_minimal_plugin_starts_standalone`）。
3. **是否真实加载进 Flowerie？**
   是。测试用真仓库（`SettingsRepository`）+ 真引擎的公开 API `discover → enable → 启动`，
   插件状态必须变成 `running`（READY）才算通过。
4. **是否真实收到 Event？**
   是。`dispatch_event("test.event", {"message":"hello"})` 后查插件自己的 `seen()`：
   `events` 里有 payload、`logs` 里有 `[test.event] hello`。
5. **是否真实调用 SDK API？**
   是。`ping/get_info/echo/seen/slow/boom` 全部经 SDK 的 `expose` 注册、由引擎的
   `plugin.call` 投递；事件处理经 SDK 的 event 分派；动作用 SDK 的动作形状回给引擎。
6. **是否真实调用其他语言插件？**
   是。命令 `/sdk@<自己> ping <target>` 由插件内的 `plugin.call` 发起，经 Core Router
   到达另一个语言的真插件进程，结果回到动作里被断言。
7. **TS → Go 是否成功？** 见 §4（`tests/sdk/test_minimal_paths.py`）。
8. **TS → Java 是否成功？** 见 §4。
9. **TS → TS 是否成功？** 见 §4（两个真 TS 插件进程，同语言同样经 Core）。
10. **Permission 是否生效？**
    生效。`tests/sdk/test_minimal_plugins.py::test_permission_and_target_lifecycle`：
    允许 / 拒绝（`PERMISSION_DENIED`）/ 目标不存在（`PLUGIN_NOT_FOUND`）/
    目标未启动（`PLUGIN_UNAVAILABLE`）四种都断言到结构化错误码 —— **不是** timeout / connection refused。
11. **Error 是否正确传递？**
    正确。`/sdk errors` 一次触发六种错误，返回的是**该语言原生错误模型**的观察结果
    （`{"native":…,"code":…,"message":…}`），错误码原样保留、一个不少。
12. **Shutdown 是否正常？**
    正常。协议 `shutdown` + 引擎 SIGTERM 后：插件进程消失、`/proc` 扫描无残留、
    `standalone_probe` 的退出码为 0（`test_shutdown_is_clean`）。
13. **哪些测试在真实环境执行？**
    CI（Ubuntu 24.04 + Python 3.9/3.12 + node + go + rustc + javac）：`tests/sdk/` 全部
    语言真跑（见 §2/§3 的表与 §6 的 CI 记录）。
14. **哪些因为环境缺失而 SKIPPED？**
    本机 Termux 沙箱：缺 go/rustc/JDK，且引擎按环境变量白名单启动插件进程时前缀内的 node 起不来
    （缺 `libtermux-exec` 的 `LD_PRELOAD`）—— 这些行全部标
    **BLOCKED BY ENVIRONMENT** 并写明缺什么，**不是 PASS**。CI 上没有任何一条因此跳过。
15. **CI 是否通过？** 见 §6（含红→绿记录）。
16. **是否产生新的 regression？**
    没有。新增用例之外，旧套件全绿（CI 总数与 skip 数见 §6）。
17. **每种 SDK 当前还有什么限制？**
    - **取消**：同步阻塞中的 handler 无法被强制打断（CANCEL 在 handler 返回后生效）。
    - **同语言 Local 优化**：Flowerie 一个插件一个进程，引擎侧实际总走 Core Router；SDK 保留了
      `route` 策略与 Local 通道（`auto/local/core` 三种策略的结果已断言一致）。
    - **`runtime=node` 的 `node_runner.js`** 不参与插件间通信（用 `runtime=exec` + 任一语言 SDK 全支持）。
    - **日志到引擎**：各语言 SDK 的日志默认走 stderr；要进引擎日志需用 SDK 的动作通道（插件侧已记录
      固定格式的日志行，验收不依赖日志通道差异）。
    - **本机沙箱**：`/storage`（FUSE）不能 exec 文件、本机缺 go/rustc/JDK、禁硬链接（容器方案不可用），
      因此编译型语言的真编译只能由 CI 采信。

## 6. CI（真数字，最终提交 `54dfe97`）

| workflow / 步骤 | 结果 | 关键数字 |
| :--- | :--- | :--- |
| `CI` · Ruff check | **success** | All checks passed!（3.9 与 3.12 两个 job）|
| `CI` · SDK 语言矩阵（`pytest -q -s tests/sdk/`）| **success** | **46 passed，0 skipped** —— 五种语言真 build、真启动、真调用、真关闭；§十七 表与 §五 表就打印在这一步 |
| `CI` · 全量 pytest | **success** | **2136 passed / 22 skipped** |
| `Acceptance` | **success** | **37/37 通过**（pytest 2178 passed / 26 skipped + ruff clean）|
| `Push on main` | **success** | CodeQL（actions / javascript-typescript / python）全过 |

### 6.1 红 → 绿（如实记录，五轮）

| commit | 结果 | 根因 | 修复 |
| :--- | :--- | :--- | :--- |
| `f373b5b` | 红 | ① Ruff 3 条（F401 ×2、B007）；② harness 把插件拷到仓库外导致 SDK 相对路径失效；③ 缺诊断手段 | 修 Ruff；构建时铺出与仓库一致的布局；新增独立启动探针（带回 stderr）|
| `35f552f` | 红（35 passed / 11 failed）| ① 10 条链路用例把 `ping` 的 label 写死成 `minimal-xx`（契约是"被调方自己的 plugin_id 换下划线"）；② Java 把引擎事件注册到了 `plugin.on`（那是插件间事件订阅）| 断言改为由被调方 id 推导；Java 改用 `onEvent` |
| `36ebac3` | 红（10 failed，全是 Java）| ① Java 的 `onEvent` lambda 调用了返回 void 的方法，javac 报 "bad return type in lambda expression"；② harness 把**失败的构建结果也缓存**了，导致后续用例把"编译失败"演成"initialize 超时" | lambda 返回 null；构建失败不进缓存（直接断言失败）|
| `9a4be87` | 红 | Ruff B011：`assert False` | 改成 `raise AssertionError` |
| `54dfe97` | **绿** | —— | —— |

> 这五轮里，只有"Java 事件注册通道"是真的 SDK 用法错误，其余都是测试/harness 自身的问题 ——
> 而它们**只有 CI 能抓**（本机四种语言全 SKIP）。这正是"skip 不等于 pass"的价值。

## 7. §十六 禁止事项自查

| # | 禁止 | 结论 |
| :--- | :--- | :--- |
| 1 | 只写 SDK 不写实际插件 | 未违反：五种语言各一个真插件（`examples/multilang-sdk/`）|
| 2 | 只编译不运行 | 未违反：验收全部要求真启动、真 READY、真事件、真调用、真关闭；Build 只是第一行 |
| 3 | 用 Mock Plugin 冒充真实 SDK 测试 | 未违反：跨语言用例全起真进程；协议端替身只记录插件发出的消息，不代答 |
| 4 | 用 Python 代替其他语言插件 | 未违反：每语言用各自 SDK；Python 只作为"另一个插件"参与链路 |
| 5 | 测试代码直接调用 Core 内部 API | 未违反：只用 `SettingsRepository` 与 `PluginManager` 的公开方法（`discover/enable/start_all/dispatch_event/shutdown/get_plugin/disable`）|
| 6 | 绕过 SDK 直接调用 Plugin Runtime | 未违反：测试不手写协议行；唯一例外是"独立启动探针"，它**只是诊断**（§十七 的每一行仍由真引擎驱动）|
| 7 | 删除失败测试 | 未违反：只新增，失败一律留痕（本轮红→绿记录见 §6）|
| 8 | 把环境缺失标成 PASS | 未违反：本机缺失项全部 `SKIP(BLOCKED BY ENVIRONMENT：…)` |
| 9 | 不同语言使用不同 Plugin Protocol | 未违反：五种语言同一份 JSON-Lines 协议与同一套能力声明（14 项，契约测试是相等断言）|
| 10 | 为了测试修改 Core 逻辑制造成功结果 | 未违反：本轮只给 Python runner 补了"自定义事件分派"（`test.event` 此前会被丢弃），属于 SDK 能力补齐，没有放宽任何权限或校验 |

