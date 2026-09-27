# Phase 0 只读审计：插件子系统（God Class 判定）

- 仓库：/storage/emulated/0/Flowerie_bot（审计期间 **零写入**：未 edit/write 任何仓库文件，未 commit，未跑 pytest）
- 审计范围：`src/plugins/`（manager / runtime / runner.python_runner / comm / router / permissions / manifest / installer / webui_loader / webui_security / protocol + http_action）
- 证据规则：所有结论带 `文件:行`；无法验证的写 UNKNOWN
- 行号基准：审计时刻的工作区快照（manager.py 2766 行 / python_runner.py 1568 行）；若行号漂移以符号名+小节锚点为准

---

## 1. 范围清单（文件 → 行数）

| 文件 | 行数 | 主要类 | 备注 |
| :--- | ---: | :--- | :--- |
| `src/plugins/manager.py` | **2766** | `PluginManager` | 本报告主目标；81 方法（26 公开 / 55 私有）、`__init__` 23 个实例属性、9 个构造参数 |
| `src/plugins/runner/python_runner.py` | **1568** | `PluginApi`(169 方法) / `PluginRunner`(42) / `PluginCommApi`(9) | 子进程侧脚本（不是包：`src/plugins/runner/` 无 `__init__.py`，靠 PEP 420 命名空间包被测试 import） |
| `src/plugins/comm.py` | 618 | 无状态类，纯常量 + DTO/校验函数 | 协议模型层 |
| `src/plugins/runtime.py` | 500 | `PluginRuntime`(28 方法) | 单插件子进程运行时 |
| `src/plugins/router.py` | 458 | `PluginRouter` / `PluginBus` / `PluginInstance` | 插件间通信路由与投递 |
| `src/plugins/permissions.py` | 394 | `PermissionManager` + 权限表 | 权限唯一检查点 |
| `src/plugins/manifest.py` | 376 | `PluginManifest` | 清单校验 |
| `src/plugins/installer.py` | 357 | `PluginInstaller` | 安装（zip/url/单 JSON） |
| `src/plugins/webui_security.py` | 342 | `_Sanitizer` + 净化/模板函数 | HTML/CSS 净化 |
| `src/plugins/protocol.py` | 169 | 常量 + 协商函数 | Plugin Protocol v1 事实来源 |
| `src/plugins/http_action.py` | 139 | 无状态，HTTP 动作 + SSRF | 与 manager 解耦 |
| `src/plugins/webui_loader.py` | 101 | 路径/读取函数 | 插件 WebUI 文件闸门 |
| `src/plugins/__init__.py` | 17 | — | — |
| 合计 | **7805** | | （`wc -l src/plugins/*.py src/plugins/runner/*.py` = 7805） |

外部依赖面（审计中实测）：
- `PluginManager` 由组合根 `main.py:182-187` 构造（9 个注入参数），被 `src/core/message_router.py:187-189`、`src/services/webui_panels/plugin_panel.py`、`src/services/webui_panels/plugin_webui_static.py` 使用。
- `src/plugins/manager.py` 被 **22 个测试侧文件**引用（实测 `grep -rl plugins.manager tests/` 得 22 个测试侧文件，含 `tests/sdk/harness.py`、`tests/e2e/_serve.py`、`tests/webui/conftest.py` 三个测试基础设施；口径差异见附录 C）。
- `src/plugins/` 内部无环：除 `manager.py` 外，没有任何模块 import 或引用 `manager`（唯一提及是注释：runtime.py:13/148/368、permissions.py:7/325、manifest.py:17、protocol.py:6）。

---

## 2. 候选类职责域拆解表

### 2.1 `PluginManager`（src/plugins/manager.py:59-2688）

统计（本次实测命令见附录 A）：
- 方法 **81** = 公开 26 + 私有 55（另 6 个 `@classmethod/@staticmethod`）
- `__init__`（62-98）实例属性 **23**（config, repository, sender, _start_ts, _plugin_services, memory_manager, state_provider, installer, _runtimes, _manifest_cache, _started, _sent_message_ids, _context_manager, _ai_client, _matchers, _bot, _bot_factory, _schedules, _comm_router, _comm_bus, _schedule_tasks, _shutdown_tasks, _shutdown_drain_timeout）
- 构造依赖 **9**（config, repository, sender, memory_manager, state_provider, installer, context_manager, bot_factory, ai_client；后 7 个可空）
- 私有方法调用点 **144 处 / 54 个不同私有方法**（最热：`_manifest_of` 15、`_sender_forward` 11、`_webui_granted` 9、`_run_action` 8、`_webui_call` 7、`_mark_status` 6、`_stop_runtime` 5、`_webui_supports` 5）
- 类级常量（经 `self.X` 访问）：16 个（`_SENDER_ACTIONS` 之外的 `_MSG_FRIEND_EXT`/`_DATA_EXT`/`_PLUGIN_EXT`/`_MEM_EXT`/`_MCP_EXT`/`_AI_EXT`/`_SOCIAL_EXT`/`_GROUP_EXT`/`_EXT_NS` + WEBUI_* 4 个 + `_DB_FILE`/`_DB_SCHEMA_V`）

| # | 职责域 | 入口方法（证据 文件:行） | 状态所有权 | 谁在调用它 | 可独立测试 |
| :-- | :--- | :--- | :--- | :--- | :--- |
| D1 | **插件文件空间（WebUI files 权限）** | `plugin_webui_dir` manager.py:136、`webui_save_upload`:147、`webui_read_file`:178、`_plugin_base`:802 | 无自有状态（读 `config.PLUGIN_DIR`） | `src/services/webui_panels/plugin_panel.py:84,107` | ✅ 已有 `tests/test_plugin_webui_files.py`（直接构造 manager，无子进程） |
| D2 | **WebUI DSL 页面渲染** | `plugin_webui_page`:195、`_plugin_webui_page_context`:242、`_webui_template_context`:261、`_webui_html_hook_vars`:272 | 借 `_runtimes`/`_manifest_cache` | `plugin_panel.py:136`（`plugin_webui_render` 内回落 DSL） | ✅ `tests/test_plugin_webui_html.py`、`test_plugin_dsl.py`（后者测 `src/services/webui_render/plugin_dsl.py`） |
| D3 | **WebUI Protocol（webui.page/action/asset）** | `plugin_webui_render`:310、`plugin_webui_asset`:591、`plugin_webui_static_file`:427、闸门 `_webui_approved`:464 / `_webui_granted`:470、`_webui_engine_context`:524、`_webui_apply_writes`:564 | 无自有状态；经 `_runtimes` 走子进程 | `plugin_panel.py:136`、`plugin_webui_static.py:39,63` | ✅ `tests/test_plugin_webui_protocol.py`、`test_plugin_webui_gate.py`、`test_plugin_webui_consistency.py` |
| D4 | **注册表视图 + manifest 解析缓存** | `_manifest_of`:643、`list_plugins`:669、`get_plugin`:695 | `_manifest_cache`（dict，进程内） | 几乎全部内部域 + WebUI 面板 (`plugin_panel.py:41,155` 直调私有 `_manifest_of`) | ✅ `tests/test_plugin_manager.py` |
| D5 | **发现（≠执行）** | `discover`:702、`refresh`:738 | 写 settings.db 注册表 | main.py:258 `start_all`→discover；面板 `refresh`(plugin_panel.py:183) | ✅ `tests/sdk/harness.py`、`test_plugin_manifest.py` |
| D6 | **安装 / 卸载** | `install_upload`:765、`install_url_async`:779、`_register_installed`:788、`uninstall`:818、`_plugin_base`:802 | `installer`（注入，自持 plugins_dir） | `plugin_panel.py:202,214,248` | ✅ `tests/test_plugin_installer.py`、`test_installer_ssrf_proof.py`、`test_plugin_path_injection.py` |
| D7 | **启用 / 禁用 / 保护级别** | `enable`:843、`disable`:912、`set_protection`:928、`_protection_level`:935 | 写注册表 + `_runtimes` | `plugin_panel.py:230,239,259`；测试直调 `_protection_level`(test_plugin_manager.py:261) | ✅ `tests/test_plugin_manager.py` |
| D8 | **运行时生命周期** | `start_all`:978、`shutdown`:1014、`_drain_shutdown_tasks`:1029、`_stop_runtime`:1051、`_start_runtime`:940、`_mark_status`:1069、`_on_runtime_exit`:1080 | `_runtimes`、`_shutdown_tasks`、`_started`、`_shutdown_drain_timeout` | main.py:258,286；测试直调 `_start_runtime`/`_stop_runtime`（test_plugin_comm_bus.py:168,315） | ✅ `tests/test_graceful_shutdown.py`、`test_plugin_runtime.py`、`test_plugin_comm_bus.py` |
| D9 | **事件分发（含 SDK matcher）** | `dispatch_event`:1087、`_match_plugin_payload`:1131 | `_matchers`、`_bot`（惰性单例） | `src/core/message_router.py:189`（**每条入站事件**） | ✅ `tests/test_plugin_manager.py:98`（真 OneBotAdapter） |
| D10 | **声明式 JSON 插件规则匹配** | `_declarative_match`:1153、`_rule_matches`:1176（classmethod）、`_substitute`:1249 | 无状态（纯函数，输入 manifest+payload） | D9 内 | ✅ `tests/test_plugin_dsl.py`、`test_api_gap_blackbox.py` |
| D11 | **Plugin Protocol 反向 op（插件→引擎）** | `_handle_engine_op`:1263、`_engine_op_comm`:1307、`_identity_dict`:1339 | 读注册表 + `_comm_router` | runtime 注入回调（manager.py:952） | ✅ `tests/test_plugin_protocol.py:295-300`（直调 `_handle_engine_op`） |
| D12 | **Action 执行（唯一副作用出口）** | 入口 `_handle_action`:1348 → `_execute_action`:1358（**权限门**）→ `_run_action`:2152；族处理 `_ext_*` 1444-2103；`_sender_forward`:2610；`_http_ext`:2553；`_file_read/write`:2653/2672；`_action_send_many`:2104 | `_sent_message_ids`（撤回白名单，200 上限） | runtime 回调注册 manager.py:951；`dispatch_event` 直调 1118/1125 | ✅ `tests/test_sdk_capabilities.py`（30 处 `_handle_action`）、`test_plugin_manager.py:350-391`、`test_sdk_social.py`、`test_sdk_lagrange.py` |
| D13 | **轻量调度器** | `schedule_register/cancel/list`（_run_action 内 2329-2367）、`_schedule_loop`:2491、`_dispatch_schedule`:2524、`_cancel_schedule`:2536、`cancel_all_schedules`:2545 | `_schedules`、`_schedule_tasks` | 仅 D12 内部；shutdown 调 cancel_all_schedules(1016) | ⚠️ 部分：无专属测试文件（grep `schedule_register` 仅 `tests/test_api_gap_blackbox.py` 覆盖） |
| D14 | **KV 存储（repository）** | `kv_get/set/delete/list`（_run_action 2368-2391） | 无（走 `repository`） | D12 + `_ext_data` 转发 1453-1456 | ✅ `tests/test_sdk_capabilities.py:60-71` |
| D15 | **插件自带 JSON "DB"** | `_db_path`:1422、`_db_load`:1427、`_db_save`:1437（`data.json`，路径 = WebUI 目录） | 文件系统（插件目录内） | `_ext_data` 1457-1513 | ⚠️ 无专属测试文件 |
| D16 | **插件间通信编排（Core 侧）** | `_register_comm_instance`:957、`comm_snapshot`:972、`_engine_op_comm`:1307 | `_comm_router`、`_comm_bus`（自持，manager.py:92-93） | 面板/验收：`tests/test_plugin_comm_bus.py:221`、`tests/e2e/test_plugin_chain_engine.py:102` | ✅ `tests/test_plugin_comm_bus.py`（真进程） |

**域的规模占比**（逐行区间实测，附录 A 脚本）：D12 Action 域 **1345 行 / 48.6%**；D1-D3 WebUI 域 **512 行 / 18.5%**；D4-D8 注册表+安装+生命周期 **444 行 / 16.0%**；D9-D11 分发+声明式+反向 op **261 行 / 9.4%**；其余为模块级辅助（2691-2766）。

### 2.2 `PluginRuntime`（src/plugins/runtime.py:48-497）→ 单域

方法 28（公开 13 / 私有 15），实例属性 23，构造参数 5（plugin_id, manifest, plugin_dir, protection, on_exit）。职责：**一个插件子进程的传输 + 请求-响应 + 生命周期**（`start`:83、`request`/`_request_now`:290/304、`_reader_loop`:379、`shutdown`:145、`_kill`:165、`close_transport_now`:215、`health_check`:491）。回调是**注入**的（`set_action_handler`/`set_engine_op_handler` runtime.py:367/371，由 manager.py:951-952 注入），runtime.py **不 import manager**（imports 仅 manifest/permissions/protocol：runtime.py:29-32）→ 无反向依赖。

### 2.3 `PluginApi`（python_runner.py:195-906）→ 纯外观（facade）

169 方法（168 公开 + `__init__`），**零个 `_` 私有辅助**；属性 4 个且只在 `__init__` 赋值（`_send_action`:200、`plugin_id`:201、`_runner`:203、`plugin`:205）；构造依赖 3 个。159/169 的方法体是同一形态 `return self._send_action("<方法名>", payload)`（动作名 = 方法名，0 处不一致），8 个转发 `self._runner._*`，1 个通用逃生口 `call()`:683。方法体行数直方图：≤2 行 159 个、3 行 7 个、4-5 行 3 个、**>5 行 0 个**（来源：子审计 §2，本报告已抽查复核：`sed -n '195,907p' … | grep -cE "^    (async )?def "` = 169、`docs/api.md` 表行数 = 169）。

### 2.4 `PluginRunner`（python_runner.py:908-1554）→ 多域

方法 42（公开 8 / 私有 34），属性 11 + 类属性 `_ACTION_ID_BASE`:949，构造参数 3（纯 str）。11 个职责域：stdio 传输 / 模块加载 / 握手与会话协商 / 协议路由 / hook 签名适配 / P2P 总线 / 反向 op RPC / storage 持久化 / config overlay 持久化 / WebUI 响应归一 / 错误与隔离（`try:` 25 处、`except` 24 处、`# noqa: BLE001` 8 处）。子进程脚本，被 runtime.py:246 以 `python3 -I` 拉起。

### 2.5 其余模块

| 类/模块 | 域数 | 结论要点 |
| :--- | :-- | :--- |
| `PermissionManager` permissions.py:344 | 1 | 纯判定（`check`:363、`denied_reason`:373、`limits`:384）+ 模块级权限表 permissions.py:29-282；无 IO、无状态耦合 |
| `PluginManifest` manifest.py:75 | 1 | 校验+值对象；类方法 `load`/`from_dict`/`to_dict` |
| `PluginInstaller` installer.py:81 | 1 | 安装流程；依赖 plugins_dir（构造参数 1） |
| `PluginRouter` router.py:88 / `PluginBus` router.py:198 | 各 1 | 路由表（register/unregister/resolve/authorize）与投递（call/emit/cancel/统计）；Router 不依赖 manager，Bus 经 `inst.runtime.comm_request`（runtime.py:335）投递 |
| `comm.py` / `protocol.py` / `webui_loader.py` / `webui_security.py` / `http_action.py` | 0（无状态） | 常量 + 纯函数，无类状态，拆无可拆 |

---

## 3. 上帝类判定（拆 / 部分拆 / 不拆）

| 目标 | 判定 | 一句话理由（标准驱动，非行数） | 预估风险 |
| :--- | :--- | :--- | :--- |
| `PluginManager` | **部分拆** | 9 个构造依赖 + 23 个实例属性 + 14 个职责域 + 同时管业务/IO/状态/协议/错误处理（WebUI 512 行、Action 1345 行、生命周期 444 行各有独立生命周期与独立测试边界），但 **D12 的"唯一副作用出口+唯一权限门"必须保持单体语义**，不能按族拆成互相独立的执行器 | **高**：5 个测试用 AST/源码文本直接钉死 manager.py 的符号与出现次数（§4.4），任何"搬文件"都会红；权限门位置一旦移动，拒绝语义（`denied:True` 原样回传，manager.py:1354-1356）会静默改变 |
| `PluginApi` | **不拆** | 零私有辅助、4 个只读属性、159/169 方法体同形态转发 → 没有可分离的职责，方法数=**接口宽度**不是复杂度；且它被 4 个 AST 测试 + 1 个文档生成器当作"API 清单"逐方法枚举（`n.body`），拆/挪会让 `docs/api.md`（169 行表）与 SDK 五语言对齐静默降级 | **高**：mixin 拆分对这些测试是**必红**；`__getattr__` 动态表同样必红（test_api_gap_whitebox.py 的"每个方法都要有 docstring"） |
| `PluginRunner` | **部分拆（仅叶子域）** | 确实多域混合（11 域、24 个 except），但所有域被**一条阻塞式可重入读循环**焊死（`_readline`:941 ← `_send_action_inner`:958 / `_send_engine_op`:1036 / `run`:1538，共享 `_req_id`:922 与 `_pump_nested`:1123）；只有与循环无共享状态的叶子域可安全外移 | **中**：`tests/test_plugin_data_dir.py:4,10` 直接构造 `PluginRunner(pd,"plugin.py","my_plugin")`，`tests/sdk/harness.py:252` 以子进程拉起该文件 → 构造签名与文件路径是硬接口 |
| `PluginRuntime` | **不拆** | 单一主语"一个插件子进程"，28 方法/23 属性全服务于传输+请求响应+生命周期；回调经 setter 注入（367/371）而非反向 import → 无职责域冲突 | 低 |
| `comm.py` / `protocol.py` / `permissions.py` / `manifest.py` / `installer.py` / `webui_loader.py` / `webui_security.py` / `http_action.py` | **不拆** | 无状态或单域；`comm.py`/`protocol.py` 是跨语言协议事实来源（5 个 SDK 对齐由 `tests/test_plugin_sdk_contract.py` 钉住），拆分即制造第二事实来源 | 低 |
| `PluginRouter` / `PluginBus` | **不拆** | 各持一个清晰的表/计数器，公开方法少且语义单一；`PluginInstance` 是只读视图 | 低 |

**总判定一句话**：插件子系统的"上帝"不是 169 方法的 `PluginApi`（那是外观），也不是 `PluginRuntime`（单主语），而是 **`PluginManager` 这一个类同时扮演 14 个角色**——最该拆的是它的 **WebUI 宿主（512 行）**与****动作族执行体（1345 行）**，最不该碰的是**权限门与 AST 钉死的符号表**。


---

## 4. 拆分方案（仅针对判定"部分拆"的 PluginManager / PluginRunner）

### 4.0 总原则

1. **不用 mixin**（任务书点名的"靠 mixin 维持体积"）：一律 **组合 + 同名薄委托**，`PluginManager` 的公开发面与现有私有"事实公开面"（§4.4）签名一字不改。
2. **权限门只保留一处**：`_execute_action`（manager.py:1358-1382）继续是所有插件 action 的**唯一入口与唯一 `PermissionManager.check` 调用点**（manager.py:1368）。新拆出的族处理器**不得**自行判权。
3. **保留"动作名白名单 + NS"原地不动**：`_SENDER_ACTIONS`(manager.py:2705)、8 个 `*_EXT` 集合(1386-1414)、`_EXT_NS`(1415)、`_PLUGIN_ID_RE`(56) 以及 8 个 `async def _ext_*` 名字**必须继续出现在 manager.py 源码里**，否则 5 个 AST/文本测试直接红（证据见 §4.4）。
4. 每一步一个提交，独立可回滚；每步只搬代码不改语义。

### 4.1 新组件 A：`PluginScheduler`（新文件 `src/plugins/scheduler.py`）

| 项 | 内容 |
| :--- | :--- |
| **真正拥有的职责** | 定时任务的注册/去重/取消/派发：`schedule_register` 的 kind 校验（interval 1-86400 / delay / daily HH:MM，manager.py:2334-2346）、同插件同名覆盖（2348-2350）、`_schedule_loop`(2491)、`_dispatch_schedule`(2524)、`_cancel_schedule`(2536) |
| **真正拥有的状态** | `_schedules`(manager.py:89 迁出)、`_schedule_tasks`(94 迁出)；**唯一 owner**，manager 不再直接持有 |
| **注入依赖**（窄接口，避免新上帝） | `dispatch(sid) -> Awaitable`（由 manager 提供的回调，内部即 `rt.dispatch_event("schedule", …)` 等价物）+ `logger` |
| **manager 侧保留** | `cancel_all_schedules()`(2545) 作为委托（`shutdown` 1016 调用它，保持公开面不变） |
| **迁移步骤** | ① 新建 scheduler.py，把 4 个方法+2 个 dict 原样搬入，签名不变；② manager.`__init__` 改成 `self._scheduler = PluginScheduler(self._dispatch_schedule_via_runtime)`；③ `_run_action` 的 3 个 `schedule_*` 分支改为调 `self._scheduler.register(...)`（保持 2357-2367 的返回体逐字不变，含 `schedule_id = f"{plugin_id}:{name}"` 格式）；④ 删除 manager 里已迁出的私有方法 |
| **保护测试** | `tests/test_plugin_manager.py`、`tests/test_graceful_shutdown.py`、`tests/test_api_gap_blackbox.py`；**新增** 一个 scheduler 专属测试（当前无，属缺口）断言：同插件同名幂等覆盖、interval 边界拒绝、cancel 越权（他人 schedule_id）拒绝、shutdown 后无残留 task |
| **回滚点** | 单提交；失败即 revert，无跨模块状态迁移 |

### 4.2 新组件 B：`PluginWebUIHost`（新文件 `src/plugins/webui_host.py`）— 搬走 512 行（18.5%）

| 项 | 内容 |
| :--- | :--- |
| **真正拥有的职责** | D1 文件空间（136-193）、D2 页面/DSL 渲染（194-441）、D3 WebUI Protocol（442-641）：`plugin_webui_dir`/`webui_save_upload`/`webui_read_file`/`plugin_webui_page`/`plugin_webui_render`/`plugin_webui_page_file`/`plugin_webui_static_root`/`plugin_webui_static_file`/`plugin_webui_asset` + 其私有辅助（`_plugin_webui_page_context`/`_webui_template_context`/`_webui_html_hook_vars`/`_webui_supports`/`_webui_approved`/`_webui_granted`/`_webui_call`/`_webui_operator_config`/`_webui_storage_snapshot`/`_webui_engine_context`/`_webui_read_payload`/`_webui_apply_writes`） |
| **真正拥有的状态** | **无自有状态**（全部经注入读取）：`plugin_dir`、`runtimes.get`、`manifest_of`、`approved_permissions`、`plugin_base` |
| **注入依赖（窄）** | `plugin_root: Callable[[], str]`、`runtime_of: Callable[[str], Optional[PluginRuntime]]`、`manifest_of: Callable[[dict], Optional[PluginManifest]]`、`approved_of: Callable[[str], set]`、`plugin_base: Callable[[str], Optional[str]]`、`config`（只读） |
| **为什么它可独立测试** | 现有 8 个测试文件全部是"真 manager + 真子进程 + 真管道"（`tests/test_plugin_webui_*.py`、`tests/webui/`），注入窄接口后既可用真 manager 也可用桩 |
| **迁移步骤** | ① manager 保留 9 个公开方法为**同名委托**（webui_panels 与测试零改动：`plugin_panel.py:84,107,136`、`plugin_webui_static.py:39,63`）；② 私有辅助**同名搬走**（`_webui_approved`/`_webui_engine_context` 被测试直调，见 §4.4 —— 若希望测试零改动，manager 侧保留 1 行转发）；③ 逐段搬运，每段一次提交 |
| **保护测试** | `tests/test_plugin_webui_files.py`、`test_plugin_webui_gate.py`、`test_plugin_webui_html.py`、`test_plugin_webui_protocol.py`、`test_plugin_webui_consistency.py`、`test_plugin_webui_integration.py`、`test_plugin_webui_multilang.py`、`test_webui_plugin_panel.py`、`tests/webui/`（102 passed 基线） |
| **风险** | 中：`_webui_approved`/`_webui_engine_context` 是测试直调的私有面（test_plugin_webui_protocol.py:444-456）；`tests/test_webui_plugin_panel.py:148` 直调 `_protection_level`（属 D7，不随本组件走） |
| **回滚点** | 单提交；委托层保证调用方零感知 |

### 4.3 新组件 C：`src/plugins/actions/` 包（把 `_run_action` 330 行/40 个内联分支拆成族）

**目标形态**（每个模块 = 一个 action 家族，函数签名统一 `async def handle(ctx: ActionContext, action: str, payload: dict) -> dict`）：

| 新模块 | 搬走的内容（现 manager.py 行号） | 覆盖动作（现证据） |
| :--- | :--- | :--- |
| `actions/messaging.py` | 2180-2235（send_message/send_private_message/send_reply、send_many→2104-2151、delete_message、get_message、get_group_history、get_context） | 撤回白名单 `_sent_message_ids`（2197-2200）随之迁入 `SentMessageLog`（新小类，200 上限） |
| `actions/group.py` | 2242-2328（get_group/get_user/get_group_member(s)/group_ban/group_kick/group_admin/is_group_admin/is_group_owner/handle_friend_request/handle_group_request）+ `_ext_group` 1986-2027 | 群管理 |
| `actions/schedule.py` | 2329-2367 | 仅调度**转调** `PluginScheduler`（§4.1） |
| `actions/kv.py` | 2368-2391（kv_get/set/delete/list）+ `_ext_data` 中 cache_* 1450-1456 | KV/缓存 |
| `actions/data.py` | `_ext_data` 1444-1587（db_*/resource_*/runtime_status/metrics/trace/health/plugin_test/NS） | 运维/自省 |
| `actions/memory.py` | 2405-2418、2448-2469 + `_ext_memory` 1696-1724 | 记忆 |
| `actions/ai.py` | 2392-2404（ai_chat）+ `_ext_ai` 1796-1909 | AI |
| `actions/mcp.py` | `_ext_mcp` 1725-1795 | MCP |
| `actions/social.py` | 2419-2431（random_*/now/format_time）+ `_ext_social` 1910-1985 | 社交/工具 |
| `actions/plugin_ops.py` | `_ext_plugin` 1589-1695 | 插件运行时语义 |
| `actions/sender.py` | `_sender_forward` 2610-2652 + 表格导入 | 语义动作→Sender 端点 |
| `actions/files.py` | `_file_read`/`_file_write` 2653-2689 | ⚠️ **不许搬出 manager.py**：`tests/test_plugin_path_injection.py:79-81` 断言 manager.py 内恰好 4 处 `_safe_id = os.path.basename(str(plugin_id or` 与 3 处 `base = self._plugin_base(_safe_id)`（见 §4.4）→ 本族**留在原地**，仅登记进新分发表 |
| `actions/http.py` | `_http_ext` 2553-2609 + `http_request`（已在外部的 http_action.py:1-139） | HTTP |
| `actions/registry.py` | 纯数据：`{action_name: (family_module, permission_key)}` 只读分发表 | **不搬** `*_EXT`/`_SENDER_ACTIONS`/`_EXT_NS` 本体（AST 测试钉在 manager.py），registry 只 import/接收它们 |

**关键设计（保住"权限检查不可绕过、拒绝语义不变"）**：

1. `_execute_action`(1358) → `pm.check`(1368) → 拒绝时 `{"ok":False,"denied":True,"error":reason}`(1372-1373) → 允许时才进 `self._dispatch_action(action_type, payload)`。**新分发表只在 `pm.check` 通过后被触达**。
2. **必须新增一条"内部派发"通道**（不带权限门）：现状 `_ext_data`/`_ext_plugin`/`_ext_memory` 有 **7 处**直接回调 `self._run_action(...)`（manager.py:1453、1455、1456、1595、1699、1701、1703）。今天是"只检查最外层动作名，内层别名（`cache_get`→`kv_get`、`memory_get`→`get_memory`）不再检查"。拆分后必须复刻这一语义：`dispatch_internal(action_type, payload)` 走同一张表但**跳过** `pm.check`。**如果误让内层走 `_execute_action`，会新增一次判权、可能把原本允许的别名调用变成拒绝（语义变更，违反硬约束）**——这是本次拆分最大的语义陷阱，需要一条专门的保护测试。
3. 拒绝路径日志（`plugin_permission_denied`，1370-1371）与 `denied:True` 原样回传（1354-1356 的注释）保持逐字不变。
4. `log`/`test` 与 NS 动作（`execute_process`/`webhook`，2479-2480）保持各自返回文案不变。

**ActionContext**（每请求构造的只读视图，避免族处理器抓 manager）：
`plugin_id`、`sender`、`repository`、`memory_manager`、`ai_client`、`state_lookup`、`runtimes`（只读 getter）、`scheduler`、`sent_messages`、`config`、`logger`。

**迁移步骤（每批一提交）**：M3a 建包 + ActionContext + 分发表，`_run_action` 改成"查表 → 调 handler"，**先把手写 if-链改成表驱动但 handler 仍是 manager 自己的方法**（纯机械变换，风险最低）→ 跑全量插件测试；M3b 逐族把方法体移入 `actions/*.py`（一次一族，manager 保留同名 `async def _ext_*()` 薄委托以满足 test_api_gap_whitebox.py:38-45）；M3c 处理 7 处 re-entrant 调用为 `dispatch_internal`。

**保护测试**：`tests/test_sdk_capabilities.py`（30 处 `_handle_action`）、`tests/test_api_gap_messages.py`、`tests/test_api_gap_whitebox.py`、`tests/test_api_gap_blackbox.py`、`tests/test_api_gap_consistency.py`、`tests/test_sdk_social.py`、`tests/test_sdk_lagrange.py`、`tests/test_sdk_gap.py`、`tests/test_plugin_manager.py:350-391`、`tests/test_plugin_permissions.py`、`tests/test_api_sender_consistency.py`；**新增**：(a) 别名内部派发不重复判权（用未批准 `plugin.call.*` 的插件调 `cache_get`，断言与拆分前一致）；(b) 全动作名清单 ⊢ 分发表（防搬家漏动作）。

**风险**：高（唯一副作用出口 + 权限门 + 40 个分支的返回文案）。
**回滚点**：M3a 是纯机械变换，可单独 revert；M3b 按族 revert。

### 4.4 拆分必须保留的"事实公开面"（测试/文档/生产代码依赖）

**(a) 测试直调的私有成员（11 个，实测统计）**

| 私有成员 | 证据（测试 文件:行） | 调用点数 |
| :--- | :--- | ---: |
| `_execute_action` | tests/test_plugin_manager.py:156,350,369,374,377,387,389,391 | 8 |
| `_handle_action` | tests/test_sdk_capabilities.py:60,62,65,66,68,70,71 … | 30 |
| `_handle_engine_op` | tests/test_plugin_protocol.py:295,298,300 … | 7 |
| `_manifest_of` | tests/test_plugin_webui_gate.py:56、test_api_gap_messages.py:275、test_plugin_webui_html.py:122 … | 7 |
| `_protection_level` | tests/test_webui_plugin_panel.py:148、test_plugin_manager.py:261 | 2 |
| `_run_action` | tests/test_api_gap_messages.py:61、test_api_gap_whitebox.py:79 | 2 |
| `_sender_forward` | tests/test_sdk_lagrange.py:145 | 1 |
| `_start_runtime` | tests/test_plugin_comm_bus.py:168、test_plugin_comm_paths.py:119 | 2 |
| `_stop_runtime` | tests/test_plugin_manager.py:495,532、test_plugin_comm_bus.py:315 … | 4 |
| `_webui_approved` | tests/test_plugin_webui_protocol.py:444,456 | 2 |
| `_webui_engine_context` | tests/test_plugin_webui_protocol.py:445,455 | 2 |

测试直调的公开成员（15 个）：`comm_snapshot, disable, discover, dispatch_event, enable, get_plugin, list_plugins, plugin_webui_asset, plugin_webui_page, plugin_webui_render, plugin_webui_static_file, refresh, set_protection, shutdown, uninstall`。
模块级符号：`from src.plugins.manager import _SENDER_ACTIONS`（tests/test_sdk_lagrange.py:5）、`import src.plugins.manager as M`（tests/test_sdk_lagrange.py:141）。

**(b) 生产代码直调私有方法（反向依赖）**：`src/services/webui_panels/plugin_panel.py:29`（`_protection_level`）、`:41` 与 `:155`（`_manifest_of`）—— 拆分类时这两个私有名必须仍然存在（保留转发或提升为公开名 + 同步改 3 处调用点）。

**(c) AST / 源码文本测试（"搬文件即红"的硬约束）**

| 测试 | 断言内容 | 证据 |
| :--- | :--- | :--- |
| `tests/test_api_sender_consistency.py` | 从 **manager.py** AST 取 `_SENDER_ACTIONS`（表键 = 动作名、值 = sender 方法）(:19-34)；取带 `NS` 名字集合(:37-49)；取所有 `*_EXT` 集合(:77-90)；断言（PluginApi 的 `_send_action` 动作 ∪ `*_EXT`）− 本地工具 ⊂ permissions.py 键(:91-93)；断言 NS ∩ sender 表 = ∅(:94-97) | 文件:20,38,77 |
| `tests/test_api_gap_whitebox.py` | 断言 manager.py 源码文本里含 8 个 `async def _ext_*` 与 8 个 `*_EXT` 名字 | :38-45 |
| `tests/test_plugin_path_injection.py` | `MANAGER = "src/plugins/manager.py"`(:18)；`_PLUGIN_ID_RE` 必须在 manager.py 顶层(:25-33)；`uninstall` 内校验先于拼路径(:54-59)；`_plugin_base` 内两段断言(:65-69)；**恰好 4 处** `_safe_id = os.path.basename(str(plugin_id or` 与 **恰好 3 处** `base = self._plugin_base(_safe_id)`(:79-81) | :18,33,79-81 |
| `tests/test_api_consistency.py` | 从 manager.py AST 取 `_SENDER_ACTIONS`(:15-30)；`docs/api.md` 方法集 ⊆ `PluginApi` 的方法集(:89-100) | :16 |
| `tests/test_api_gap_consistency.py` | `docs/api.md` 必须含全部 gap 方法(:84-87) | :84 |
| `tests/test_plugin_sdk_contract.py` | 五种语言 SDK 源码里必须出现同一批能力名，python 侧路径 = `src/plugins/runner/python_runner.py`(:245-256) | :245-256 |
| `scripts/gen_api_md.py` | AST 解析 `python_runner.py` 里名为 `PluginApi` 的 ClassDef 的 `n.body` 生成 `docs/api.md`（169 行表）；并从方法体的 `self._send_action("x"…)` / `self._runner._y(…)` 推导说明文字 | :26,47-52 |

**(d) 文档承诺的公开接口**：`docs/security.md:51`（"动作名白名单：由 `_SENDER_ACTIONS` 登记表校验"）、`docs/plugin-sdk.md:95`（"Python 的 PluginApi 另有 160+ 个动作包装方法"）、`docs/api.md:3`（"由 scripts/gen_api_md.py 生成"）、`docs/plugin-final-report.md:104,123`（"PluginApi 的 160+ 方法一个没删，只做加法"）、`docs/plugin-webui-migration.md:12`（`PluginManager.plugin_webui_page` 调用链）、`docs/plugin-webui-protocol.md:101`、`docs/plugin-developer-guide.md:763,774`（`from src.plugins.manager import PluginManager` 示例）。

---

## 5. 依赖问题（反向 / 循环 / 隐式 self 状态耦合）

### 5.1 循环依赖：**无**（实测）

- `src/plugins/` 内部 import 方向：`manager → {runtime, router, comm, installer, manifest, permissions, http_action, webui_loader, webui_security, protocol}`；`router → {comm, permissions}`；`comm → protocol`；`runtime → {manifest, permissions, protocol}`；`installer/manifest/webui_*` 不依赖同类。
- 反向验证：在除 manager.py 外的所有插件模块里 grep `manager|PluginManager`，**命中的全部是注释**：`src/plugins/runtime.py:13,148,368`、`src/plugins/permissions.py:7,325`、`src/plugins/manifest.py:17`、`src/plugins/protocol.py:6`。函数内延迟 import 也不存在到 manager 的（manager.py 内的函数级 import 只有 29 处，全部指向 `permissions/protocol/webui_security/webui_loader/metrics/blossom_memory/reply_plan/http_action/collections/glob/shlex/httpx`，见附录 A 清单）。
- 结论：**没有环，也不需要靠延迟 import 打破环**。唯一"回指"是运行期回调注入（manager.py:951-952 `set_action_handler`/`set_engine_op_handler`；runtime.py:367/371 定义），属正确的控制反转。

### 5.2 反向依赖（不是 import 环，但拆分时必须处理）

| 反向依赖 | 证据 | 影响 |
| :--- | :--- | :--- |
| 生产代码调 manager **私有**方法 | `src/services/webui_panels/plugin_panel.py:29`（`_protection_level()`）、`:41`、`:155`（`_manifest_of(row)`） | 把 D4/D7 迁走会同时改 3 处生产调用点；建议保留同名委托 |
| 测试调 manager 私有方法（11 个） | §4.4(a) 表 | 同上；"私有"事实上是公开面 |
| 插件子进程侧回指 runner 私有属性 | python_runner.py:166,172 读 `self._runner._cancelled`（定义 :930） | PluginCommApi 与 PluginRunner 的封装泄漏；拆 runner 时不能只搬 `_cancelled` |
| `PluginApi.` → `PluginRunner._storage_*` 私方法 | python_runner.py:210,214,218,222,226,230 | 8 个 `_runner._*` 直调；storage/config 外移时必须改这 8 处（在 PluginApi 内部，影响面可控） |

### 5.3 隐式 self 状态耦合（带行号）

1. **分发器 ↔ 族处理器互相调用（re-entrant）**：`_ext_data` → `self._run_action("kv_get"/"kv_set"/"kv_delete")`（manager.py:1453、1455、1456）；`_ext_plugin` → `_run_action("http_request")`（1595）；`_ext_memory` → `_run_action("get_memory"/"write_memory"/"kv_delete")`（1699、1701、1703）。这是 §4.3 的核心陷阱。
2. **两处重复登记路径**：`_start_runtime`:954 与 `start_all`:1001 各自调用 `_register_comm_instance`，而 `start_all` 对 `runtime == "json"` 走的是**内联构造 PluginRuntime 副本**（994-1003），与 `_start_runtime`(946-955) 构造逻辑重复 —— 任何"运行时工厂"抽取必须同时覆盖这两条路径，否则 json 插件掉出 comm 路由。
3. **注册表整行 upsert 是共享写面**：`_mark_status`(1073-1078)、`enable`(886-891)、`disable`(918-923)、`_register_installed`(792-797) 各写 6 个字段的**整行**；若把注册表写权分给新组件，会出现"后写覆盖先写"的竞争（例如 `_mark_status` 会把 `approved_permissions` 重新按逗号切分写回）。
4. **`_sent_message_ids` 的隐式跨插件共享**：撤回白名单是 **manager 级单列表**（81、2197-2200、2213、2221），不是 per-plugin；把 messaging 族抽出时必须整体搬走这个列表，**不能**变成 per-plugin 状态（否则"只能撤回本 bot 消息"的语义被放大为"可撤回他人消息"）。
5. **`_bot` 惰性单例**：`_match_plugin_payload`(1134-1135) 首次调用时构造，依赖 `sender`+`_bot_factory`+`_context_manager` 三者同时存在；拆 D9 时不能把该惰性构造留在 manager 而把匹配逻辑搬走（会变成跨对象隐式状态）。
6. **`_manifest_cache` 以 `pid` 为键、以 `raw` 文本比对失效**（659-666）：`_manifest_of` 是 15 处调用的共享缓存，拆 D4 时若两个组件各自持有缓存，会出现"禁用后陈旧 manifest 仍可用于渲染"的一致性缺口（`disable` 924 与 `uninstall` 829 手动 `pop` 缓存即为此）。


---

## 6. 重复逻辑与死代码候选（带引用证据）

> 判定口径：`grep` 全仓（src/tests/docs/scripts/sdk，排除 `__pycache__`）确认无第二处引用才称"死"；只重复未死称"近重复"。

### 6.1 死代码（已确认无引用）

| # | 符号 | 证据 | 说明 |
| :-- | :--- | :--- | :--- |
| D-1 | `PluginApi._send_action_safe` | `src/plugins/runner/python_runner.py:970-974`；全仓 grep 只有定义行自身（唯一"引用"是 :972 方法体内部） | `__init__` 实际装配的是**非 safe** 变体（:931 `PluginApi(self._send_action_inner, …)`）。⚠️ 它是同步 action 路径唯一的 try/except 包装，删除会改变"若将来改绑它"的崩溃语义 → **只标记不删** |
| D-2 | `PluginManager.plugin_webui_page_file` | `src/plugins/manager.py:410`；全仓 grep 命中数 = 1（自身定义） | 公开方法，删除即公开面变更；建议先在 CHANGELOG 标 deprecated |
| D-3 | `self._plugin_services` | 写：`manager.py:72`（初始化）、`manager.py:1665`（`plugin_service` 分支写字典）；**全仓无任何读取** | 只写不读的实例状态（默认值 `{}` 永不消费）→ 死亡状态 |
| D-4 | `PluginManager.install_url` | `manager.py:775-777` 无条件 `raise RuntimeError`；全仓无调用者（WebUI 走 `install_url_async`：`plugin_panel.py:214`） | 有意的"同步占位"守卫；属**死接口**，保留与否需产品决定 |
| D-5 | `_ext_group` 别名表中的 2 个自反别名 | `manager.py:1990-1991`：`"group_title": "group_title"`、`"group_honor": "group_honor"` —— 但 `_run_action` 在 `:2154` **先**判 `_SENDER_ACTIONS`（`group_title` 见 :2737、`group_honor` 见 :2715），这两条别名分支**不可达** | 分派优先级导致的不可达分支（详见 6.3） |
| D-6 | `_ext_social` 别名表中的 1 个自反别名 | `manager.py:1916`：`"like": "like"`；`like` 在 `_SENDER_ACTIONS`(:2728) 且 `:2154` 先判 → **不可达** | 同上 |
| D-7 | `_run_action` 的 `webhook` 内联分支 | `manager.py:2479-2480` `if action_type in ("execute_process", "webhook")`；但 `webhook` ∈ `_PLUGIN_EXT`(:1399) 且 `:2166` 先判 → `webhook` 永远到不了 2479 | `execute_process` 仍可达（不在任何 `*_EXT`），**不能整行删** |

### 6.2 近重复 / 重复逻辑（建议合并，但属语义变更 → 需单独评审）

| # | 位置 A | 位置 B | 重复度 |
| :-- | :--- | :--- | :--- |
| R-1 | `get_group` manager.py:2242-2247 | `get_group_info` manager.py:2442-2447 | 逻辑逐行相同，**仅错误文案里的动作名不同**（`"get_group 需要 group_id"` vs `"get_group_info 需要 group_id"`）；两者都返回 `{ok, group_id, info}` |
| R-2 | `get_context` manager.py:2236-2241 | `get_group_history` manager.py:2230-2235 | `get_context` = `get_group_history` 固定 `count=10` 且不接受 count 参数 |
| R-3 | `_webui_operator_config` manager.py:501-504 | `_handle_engine_op` 的 `config.get` 分支 manager.py:1302-1305 | **4 行逐字相同**（`cfg = (manifest.config …) or {}` / `values` 解包）；两处都声称是"同一来源"（:495 注释），但实现是两份 |
| R-4 | `_mark_status` 整行 upsert manager.py:1073-1078 | `_register_installed`:792-797 / `enable`:886-891 + 回滚:900-904 / `disable`:918-923 | 5 处重复"6 字段整行 upsert"模板（字段集与默认值需手工保持一致，现已是隐患面） |
| R-5 | 运行时构造 `_start_runtime` manager.py:946-955 | `start_all` 的 json 内联构造 manager.py:994-1003 | 同一构造逻辑两条路径（后者还额外做 `_mark_status("running")`）；抽取时必须同时覆盖，否则 json 插件掉出 comm 路由 |
| R-6 | 事件权限表 `_EVENT_PERMISSION` manager.py:48-49 | 事件分发处 `required = _EVENT_PERMISSION.get(event_type, "read_message")` :1096 | 单一来源，**非**重复；列出以免误判 |
| R-7 | `_EXT_NS` manager.py:1415-1417（9 个名字） | `_MSG_FRIEND_EXT` manager.py:1386-1390（15 个名字） | 实测 **`_EXT_NS` ⊂ `_MSG_FRIEND_EXT`（可推导子集）**，却独立维护两份；且 `tests/test_api_sender_consistency.py:46,85` 对二者有不同处理，合并会动测试 |
| R-8 | 重复错误文案 | `"sender 未注入（不可用）"` ×3（manager.py:2193、2217 及第三处）、`"插件运行中未加载（重启后重试）"` ×2 | 文案重复而非逻辑重复；统一文案可能被断言文案的测试捕获 → 低优先级 |
| R-9 | 两套持久化机制共存于同一 API 面 | repository KV（manager.py:2368-2391，键 ≤128 字符 / 值 ≤64KB，落 settings.db）vs 插件自带 `data.json`（manager.py:1422-1442，无键上限 / 文件 ≤256KB，落插件目录） | 语义、限额、生命周期都不同；拆 D12 时**不能**合并成一个"存储"组件 |
| R-10 | 冗余函数内 import | `os`：manager.py:138,149,180,1423,1438,1563,1605,1951,1976；`time`:1446；`asyncio`:1577,1684；`glob`:1561；`shutil as _shutil`:853 | 模块级已 import（:17-25）；纯卫生问题（ruff `F811` 不覆盖函数内 import），零语义影响 |

### 6.3 分派优先级（拆分前必须固化的语义，附实测）

`_run_action` 的判定顺序是**固定优先级**：`_SENDER_ACTIONS`(:2154) → `_MSG_FRIEND_EXT`(:2156) → `_GROUP_EXT`(:2158) → `_SOCIAL_EXT`(:2160) → `_AI_EXT`(:2162) → `_MEM_EXT`(:2164) → `_PLUGIN_EXT`(:2166) → `_DATA_EXT`(:2168) → `_MCP_EXT`(:2170) → 内联分支(:2172-2480)。

实测交叉重叠（脚本见附录 A，AST 提取表字面量）：

| 名字 | 声明处 1 | 声明处 2 | 实际生效路径 | 后果 |
| :--- | :--- | :--- | :--- | :--- |
| `group_title` | `_GROUP_EXT` manager.py:1412 | `_SENDER_ACTIONS` manager.py:2737 | Sender（先判） | `_ext_group` 别名分支(:1990) 不可达 |
| `group_honor` | `_GROUP_EXT` manager.py:1414 | `_SENDER_ACTIONS` manager.py:2715 | Sender | `_ext_group` 别名分支(:1991) 不可达 |
| `like` | `_SOCIAL_EXT` manager.py:1407 | `_SENDER_ACTIONS` manager.py:2728 | Sender | `_ext_social` 别名分支(:1916) 不可达 |
| `webhook` | `_PLUGIN_EXT` manager.py:1399 | 内联分支 manager.py:2479 | `_ext_plugin` | 内联 `"not implemented"` 分支不可达 |

规模：8 个族集合共 **100** 个动作名（`_MSG_FRIEND_EXT` 15、`_DATA_EXT` 20、`_PLUGIN_EXT` 14、`_MEM_EXT` 8、`_MCP_EXT` 6、`_AI_EXT` 9、`_SOCIAL_EXT` 15、`_GROUP_EXT` 13），`_SENDER_ACTIONS` **37** 条，`_run_action` 内联分支 **48** 个动作名；三组之间除上述 4 个名字外互不重叠。

---

## 7. 性能热点（只找不改）

> 说明：全部为**静态证据**（调用链 + 行号），本次审计未做 profiling、未跑压测。

| # | 热点 | 证据 | 影响面 |
| :-- | :--- | :--- | :--- |
| P-1 | **每条入站事件一次全表 SQL** | `dispatch_event` manager.py:1097 `for row in self.repository.list_plugins()`；调用者是 `src/core/message_router.py:187-189`（`process_event` 内、业务分支之前，**每事件必跑**）；`list_plugins` 实现 `src/repositories/settings_repository.py:327-333`（持锁 SELECT 全表 + 逐行 dict） | 消息高频路径；插件数为 0 也照查 |
| P-2 | **每个 action 再一次 SQL** | `_execute_action` manager.py:1361 `row = self.repository.get_plugin(plugin_id)`；实现 settings_repository.py:318-325 | 与 P-1 叠加：一次消息 + N 个 action = N+1 次查询 |
| P-3 | `get_plugin` 是 O(插件数) 线性扫描 | manager.py:695-699 遍历 `list_plugins()`(:669-693)，后者每行都调 `_manifest_of`(:674) 并构造 13 字段 dict | 被 9 处调用（`_webui_approved`:466、`_ext_data`:1529,1539、`_ext_plugin`、`_register_installed`:789、`enable`:846、`disable`:914、`uninstall`:825、`_mark_status`:1070） |
| P-4 | **manifest 缓存命中也要重新序列化** | manager.py:660 `(isinstance(m, PluginManifest) and m.to_json() != raw)` —— 每次查询都对整份 manifest 做一次 `json.dumps`；`_manifest_of` 有 15 处调用，含 `dispatch_event`:1104 的**每插件每事件** | 高频路径上的重复计算（可按 `raw` 字符串身份/hash 比较替代） |
| P-5 | **WebUI 存储快照 = 最多 200 次子进程往返** | manager.py:506-522：`storage.list`(:511) 后对每个 key 串行 `self._webui_call(..., timeout=2.0)`(:517)；`_webui_call``:483` 是真子进程 `rt.request` | WebUI 控制面（非消息路径），但一次页面渲染可达数百次 IPC × 2s 超时上限 |
| P-6 | **async 方法里的阻塞 IO** | `/proc` 读：manager.py:1519-1525（`resource_usage`）、1552-1554（`health`）；日志文件：1565-1568（`trace`，`f.readlines()[-50:]` **整文件读入**再取尾 50 行）；插件 `data.json`：1429-1432（`_db_load`）、1440-1442（`_db_save`，含 `os.replace`）；`_file_write`:2686 | 这些都在事件循环线程内同步执行 → 阻塞所有消息处理 |
| P-7 | 调度无全局上限 | `_schedules`/`_schedule_tasks` manager.py:89,94 只按 `(plugin_id, name)` 去重(:2348-2350)，无条数上限；`schedule_register` 每次 `asyncio_create_task`:2354 | 恶意/失控插件可注册大量 interval(min 1s) 任务 → task 膨胀 |
| P-8 | `dispatch_event` 每插件复制一次 payload | manager.py:1111 `payload = {**payload, "matched": hits}`（原地重绑定，后续插件看到的是"被覆写过的 payload"——同时是**语义**隐患：上一插件的 matched 会被带进下一插件的 payload 变量） | 轻微性能 + 潜在串味 |
| P-9 | `_sent_message_ids` 每次发送做 O(n) 截断 | manager.py:2199-2200（>200 时整表切片） | 有界（200），可忽略；列此以证明"有界" |
| P-10 | 子进程侧（python_runner.py） | `asyncio.run` 每个 async hook 新建/销毁事件循环（:1021、:1223，且 :1019/:1222 函数内重复 `import asyncio`）；`inspect.signature()` 每次调用都算（:1008、:1213）；storage 每次操作 `os.makedirs`（:1233-1236 ← :1241/:1264/:1291）+ 每次写 `os.listdir` 全目录扫描（:1264）；config 每次访问重读文件（:1304-1310）；`config_get` 每次一次引擎往返（:1319-1320）；"async" hook 里的 `sys.stdin.readline()` 是同步阻塞（:958、:1036） | 插件侧吞吐；与主进程 P-1/P-2 叠加 |

**未发现**的问题（避免误伤）：无"每请求新建 HTTP client"——`http_action.plugin_http_request` 是每次调用新建（`src/plugins/http_action.py` 内），但插件 HTTP 动作本身是低频控制面；manager 未持有任何连接池；`_manifest_cache` 以 plugin_id 为键（有界），禁用/卸载时显式 pop（:829、:924）；`_cancelled` 在 runner 侧 256 上限 + clear（python_runner.py:1206-1207）。

---

## 8. UNKNOWN / 未验证项

1. **UNKNOWN**：仓库外部（不在本仓 tree 内）的第三方插件是否 import `PluginApi` 或继承 `PluginManager`——只能验证本仓（0 处子类化）。因此"PluginApi 方法可否改名"无法闭环。
2. **UNKNOWN**：拆分后 `_execute_action` 内层别名派发的**真实放行差异**未实测（只做了静态调用链分析：manager.py:1368 判权 → :1375 `_run_action` → :1453 等 7 处直调 `_run_action`）。§4.3 建议的新增保护测试就是为了把这个 UNKNOWN 变成可执行断言。
3. **UNKNOWN**：`_run_action` 的"105 分支"口径未复现——本次实测为 **40 个 `if action_type` 顶层分支 + 48 个内联动作名 + 118 条控制流语句（if/elif/for/while/try/except）**。105 可能来自其它计数口径（含家族内部 if），**未验证**（分支计数口径的澄清见附录 F.4）。
4. **UNKNOWN**：审计期间未运行 pytest / ruff / 任何插件子进程，因此"当前提交的测试基线是否全绿"、"拆分的实际性能收益"均未验证。全部分支/行数为静态统计。
5. **UNKNOWN**：`_send_action_safe`(:970) 是否原本应被装配（:931 装配的是 inner）——源码无注释说明。
6. **UNKNOWN**：`plugin_webui_page_file`(:410) 是否为外部集成（非本仓调用）保留的兼容 API——无法验证。
7. **未验证**：`tests/` 与 `docs/` 中对 `PluginManager` 成员的使用统计基于正则 `mgr|manager|pm|plugin_manager|m2` 前缀变量名（脚本见附录 A）；若某测试用别的变量名（如 `self._mgr`）持有 manager，会漏计未覆盖的成员。
8. **未验证**：`window` 与跨语言 SDK（node/go/rust/java/ts）的一致性影响——本次未审计 `node_runner.js` 与 `sdk/*`；已知 `tests/test_plugin_sdk_contract.py:245-256` 要求 5 种语言源码同时出现同名能力，任何"只改 Python 侧"的方案都有连带义务。
9. **环境限制**：写报告只能落到 `work/audit/`（会话工作区）；仓库内 `docs/` 未写入任何内容（按要求保持只读）。

---

## 附录 A：审计使用的命令（可复现）

```bash
# 0) 基线：提交 + 工作树干净（确认审计零写入）
cd /storage/emulated/0/Flowerie_bot
git rev-parse HEAD            # e8ce351b051b925a06dd6d05832ae9df80beb1c0
git status --porcelain        # 空

# 1) 规模
wc -l src/plugins/*.py src/plugins/runner/*.py | sort -rn

# 2) 结构（类/方法/小节）
grep -n "^class \|^    def \|^    async def \|# ====" src/plugins/manager.py

# 3) PluginManager 表面统计（方法/私有调用点/属性）
python3 - <<'PY'   # 见会话记录：正则 ^    (async )?def 统计 81/26/55；self\.X 计数得 144 私有调用点 / 39 数据引用
PY

# 4) _run_action 规模
awk 'NR>=2152 && NR<=2481' src/plugins/manager.py | grep -cE "^        if action_type"   # 40
awk 'NR>=2152 && NR<=2481' src/plugins/manager.py | grep -c "if \|for \|while \|try:\|except "  # 118

# 5) 族集合与重叠（AST 提取 frozenset/dict 字面量）
python3 - <<'PY'   # 8 个 *_EXT 共 100 名；_SENDER_ACTIONS 37；重名 3 个 + webhook
PY

# 6) 测试直调私有面
grep -rn "_execute_action\|_handle_action\|_run_action" tests/   # 及 11 个私有成员脚本统计

# 7) AST/文本钉死 manager.py 的测试
grep -rn 'src/plugins/manager.py' tests/ --include=*.py
grep -rn 'python_runner.py' tests/ scripts/ --include=*.py

# 8) 循环依赖验证
grep -rn "manager\|PluginManager" src/plugins/*.py | grep -v "^src/plugins/manager.py"
grep -rn "src.plugins.manager\|plugins import manager" --include=*.py src tests

# 9) 函数内 import 清单
grep -nE "^        (import|from) |^            (import|from) " src/plugins/manager.py

# 10) CI / lint 约束
grep -n "ruff\|pytest" .github/workflows/ci.yml .github/workflows/acceptance.yml
grep -n -A12 "\[tool.ruff" pyproject.toml
```

## 附录 B：拆分安全网（按 §4 方案，跑测顺序）

```
M1 调度器：      tests/test_plugin_manager.py tests/test_graceful_shutdown.py tests/test_api_gap_blackbox.py
M2 WebUI 宿主：   tests/test_plugin_webui_{files,gate,html,protocol,consistency,integration,multilang}.py
                 tests/test_webui_plugin_panel.py tests/webui/
M3 actions 包：   tests/test_sdk_{capabilities,social,lagrange,gap}.py tests/test_api_gap_{messages,whitebox,blackbox,consistency}.py
                 tests/test_api_sender_consistency.py tests/test_plugin_manager.py tests/test_plugin_permissions.py
全程必跑（AST 门）：tests/test_api_consistency.py tests/test_plugin_path_injection.py
                     tests/test_plugin_sdk_contract.py tests/test_architecture_gates.py
```

## 附录 C：与同工作区其它审计产物的关系

`work/audit/` 下已有同一 Phase 0 其它子审计的产物（`test-guard-map.md`、`perf-findings.md`、`mechanical.md`、`imports.md`、`scan.md` 等），非本报告作者所写。本报告的所有数字均在本仓独立复算；其中 `src/plugins/manager.py` 被 22 个测试侧文件引用（本报告实测；test-guard-map.md 记 18，差异在 harness/conftest/_serve）的口径与 `test-guard-map.md` 一致（交叉验证通过，未直接引用其数据）。


---

## 附录 D：router/comm ↔ manager 耦合再验证（补充证据，Q5 直接回答）

| 检查 | 命令 | 结果 |
| :--- | :--- | :--- |
| router/comm 是否含动作名分派表（与 `_run_action` 重复？） | `grep -nE '"(send_message|kv_get|group_ban|http_request|ai_chat|mem_update)"' src/plugins/router.py src/plugins/comm.py` | **零命中** → 无重复分派，两个模块只做协议模型与投递 |
| PluginBus 是否读取 manager 的权限/身份 | `PluginBus.call` 签名 `call(caller_id, request, *, approved=())`（router.py:230-231） | 权限集合**由调用方传入**（manager.py:1324 `approved=approved`）；Bus 内无 manager 引用 |
| router 依赖的是什么 | `_capabilities_of` router.py:429-432、`_supports` router.py:434-443 | 用 `getattr` 鸭子类型读 `inst.runtime.capabilities` / `runtime.supports` → 依赖 **PluginRuntime 的鸭子类型**，不依赖 manager |
| 身份从哪来 | manager.`_identity_dict`:1339-1345 读 `_comm_router.get(plugin_id)`；`_register_comm_instance`:957-970 由清单+握手写入 | 方向为 manager → router（单向） |
| 是否存在隐式环 | 上述 + §5.1 全模块 grep | **无环**；管理器只做"登记 + 编排 + 传权限"，路由/超时/环保护都在 router.py（manager.py:90-91 注释与实现一致） |

补充：`src/plugins/comm.py:46` 只 import `protocol`；`src/plugins/router.py:23-26` 只 import `comm`/`permissions`/logging。二者对 `Protocol/Plugin SDK 兼容面`的意义是"常量与 DTO 事实来源"（`PLUGIN_OPS`/`MESSAGE_KINDS`/`ERROR_CODES`/`DATA_TYPES`/`DTO_FIELDS`），**拆分时不得搬迁或改名**（`tests/test_plugin_comm_model.py`、`tests/test_plugin_protocol.py` 逐项比对，且 `python_runner.py:100` 注释声明与 `comm.py` 同源、由测试逐项对照）。


---

## 附录 E：动作面交叉核对与两套插件间通信机制（本次审计最重要的重复面发现）

### E.1 动作名总数 181，与权限表一一对应（守护住"权限不可绕过"）

| 口径 | 数量 | 证据 |
| :--- | ---: | :--- |
| 8 个家族集合（去重后并集） | 100 | manager.py:1386-1414（`_MSG_FRIEND_EXT` 15 / `_DATA_EXT` 20 / `_PLUGIN_EXT` 14 / `_MEM_EXT` 8 / `_MCP_EXT` 6 / `_AI_EXT` 9 / `_SOCIAL_EXT` 15 / `_GROUP_EXT` 13） |
| `_SENDER_ACTIONS` 键 | 37 | manager.py:2705-2746（`awk` 计数 37） |
| `_run_action` 内联分支动作名 | 48 | manager.py:2172-2480 |
| 三者重叠 | −4 | `group_title` / `group_honor` / `like`（家族×sender）+ `webhook`（家族×内联） |
| **去重合计** | **181** | 100+37+48−4 |
| `permissions.ACTION_PERMISSIONS` 键数 | **181** | `python3` 提取 permissions.py 中 `ACTION_PERMISSIONS` 段（到 `_UNIMPLEMENTED`）的 `"key":` 行 = 181 |

→ **每个可派发动作名都有权限行，没有死权限行、也没有无权限分支**。这条等式是"权限门不可绕过"的结构保证，拆 `_run_action` 时必须保持 181 这个数字不变（任何遗漏都会让某个动作落进最后的 `未知 action` 兜底，行为从"执行"变成"报错"）。

### E.2 方法数口径澄清（81 vs 87）

- **81** = `PluginManager` 的类方法数（4 空格缩进 `def`）：`grep -cE "^    (async )?def " src/plugins/manager.py` → 81（公开 26 + 私有 55），与任务书给的 81 一致。
- **87** = 该文件**全部** `def ` 行：81 + 4 个模块级函数（`_json_dumps`:2691、`_json_loads`:2696、`_rule_from`:2749、`asyncio_create_task`:2755）+ 2 个嵌套闭包（`send_one`:2133、`after_sent`:2137）。两种口径都对，指代不同。

### E.3 ⚠️ 两套并存的插件间通信机制（重复逻辑 + 语义分叉，本次审计最高优先级发现）

| | 新通道（Core Router / Communication Bus） | 旧通道（Runtime hook 直投） |
| :--- | :--- | :--- |
| 触发 | 引擎 op `plugin.call`/`plugin.emit`/`plugin.cancel`（点号命名） | **action** `plugin_call`/`plugin_event`/`plugin_service`（下划线命名） |
| 入口 | manager.py:1277-1278 → `_engine_op_comm`:1307-1337 | manager.py:1658-1693（`_ext_plugin` 内联分支） |
| 投递 | `self._comm_bus.call/emit/cancel`:1324/1334/1335 → router.py:230/340/388 → `runtime.comm_request`(runtime.py:335) | `self._runtime_hook_call(tgt_rt, "on_plugin_event", ev)`:1686 |
| 权限 | `approved` 集合传入 Bus（manager.py:1324），`call_permission_granted`/`emit_permission_granted`（router.py:186/191） | **无 call/emit 权限判定**，只校验"目标存在且 enabled/已加载"（1672-1680） |
| 环保护 | `hop_count`/`MAX_HOP_COUNT`(comm.py:66) + `PLUGIN_CALL_LOOP`(comm.py:88) | **无**（`ev` 里只塞了 `trace_id`，1675-1677） |
| 超时 | `DEFAULT_TIMEOUT_MS` 5000 / `MAX_TIMEOUT_MS` 60000（comm.py:69-70，可协商） | 硬编码 `timeout=3.0`（1686） |
| 统计 | `comm_snapshot()`（manager.py:972-976，被两份验收测试断言） | 无计数 |
| 服务注册 | 无（service 概念属旧通道） | `self._plugin_services[sname]`:1665 —— **只写不读**（全仓无读取点，见 §6.1 D-3），注册后无解析路径 |

**证据**：manager.py:1658-1693（旧通道全貌）、manager.py:1307-1337（新通道全貌）、permissions.py:128-129（两条路径的动作都在权限表中）、comm.py:49-99（新通道的常量与守卫）。

**对本次重构的含义**：
1. 这是**重复逻辑**（两套 P2P 投递）而非死代码——两者都在权限表中、都可能被插件调用（旧通道命名是 SDK 的历史动作名，可能仍有插件在用 → 不能删）。
2. 新通道的安全能力（权限、环保护、超时、统计）**旧通道一个都没有**；这是安全语义分叉，不是单纯重复。Phase 0 只登记，**是否收敛必须单独立项**（收敛会改变行为语义，超出"不改行为"约束）。
3. 拆 `_ext_plugin` 时，这段 36 行必须**整体**作为一个单元迁移（它同时写 `_plugin_services` 并读 `_runtimes`/`get_plugin`），拆一半会造成"注册了但投不出去"或反之。

---

## 附录 F：支撑模块的死代码 / 重复逻辑 / 性能补充（每条均在本仓独立复核）

### F.1 死代码（复核命令：排除定义文件自身后全仓 grep，含 src/tests/docs/scripts/sdk/examples）

| 符号 | 定义 | 外部引用 |
| :--- | :--- | :--- |
| `protocol.value_size` | src/plugins/protocol.py:164 | **0** |
| `protocol.all_methods` | protocol.py:87 | **0** |
| `protocol.group_of` | protocol.py:139 | **0** |
| `protocol.valid_config_key` | protocol.py:96 | **0** |
| `protocol.encode_line` / `decode_line` | protocol.py:100 / :105 | 仅 docs/plugin-protocol.md:22,27（**无代码引用**） |
| `comm.PLUGIN_OP_TO_METHOD` | comm.py:55 | **0**（与 protocol.PLUGIN_METHODS 重复声明，且无人消费） |
| `webui_security.TAG_ATTRS["img_"]` | webui_security.py:56 | **0**，且值为空 `frozenset()` → 疑似 `img` 的笔误残留 |
| `PluginManager.plugin_webui_page_file` | manager.py:410 | **0**（见 §6.1 D-2） |
| `PluginApi._send_action_safe` | python_runner.py:970 | **0**（见 §6.1 D-1） |
| `PluginManager._plugin_services` | manager.py:72 / 写 :1665 | **0 读取点**（见 §6.1 D-3；与附录 E.3 旧通道互证） |

注：`protocol.py` 的常量（`API_VERSION`、`ACTION_ID_BASE`、`valid_storage_key`）只在 docs / 单个测试里出现，属"文档/测试独有"而非严格死亡 —— 处理时**不应**直接删（会动 docs 与 tests），仅登记。

### F.2 重复逻辑（跨模块，均为"同一算法两份实现"）

| 重复对 | 证据 | 差异 |
| :--- | :--- | :--- |
| DNS/SSRF 校验两份 | `installer.py:346-357`（`_check_dns`，调用点 :157）vs `http_action.py:46-58`（`_check_dns`，调用点 :43、:80） | 算法相同（host → port → `loop.getaddrinfo` → `validate_mcp_resolved_ips`），错误风格不同（返回 tuple vs 抛 `PluginHttpError`）；两文件各自 import 同一套 `src.core.sanitizer` 助手（installer.py:28、http_action.py:13） |
| `ACTION_ID_BASE = 1_000_000` 三处声明 | protocol.py:79、runtime.py:36（`_ACTION_ID_BASE`）、python_runner.py（子进程侧另有同名常量，见 §1） | 属**协议常量跨进程复制**，有测试钉住 → 不得"去重"为 import（runner 以 `python -I` 启动，仓库代码不在 sys.path） |
| `router.route_for()` 三分支塌缩 | router.py:169-182：`ROUTE_CORE`(:178)、`ROUTE_LOCAL`(:181)、默认(:182) **全部 return `comm.ROUTE_CORE`**；而 `comm.py:60-63` 仍定义 3 种策略 | 有意为之（:172-175 注释说明引擎侧无 local 通道），**不是 bug**；但属"多分支同结果"，可折叠为常量+注释 |
| 两套插件间通信 | 见附录 E.3 | 本次审计最高优先级重复面 |

### F.3 性能补充（跨模块，静态证据）

| # | 热点 | 证据 |
| :-- | :--- | :--- |
| PF-1 | HTTP 动作**每次调用新建 `httpx.AsyncClient`**（新连接池/TLS，无复用） | http_action.py:98-100（`async with httpx.AsyncClient(`），配合 `follow_redirects=False` |
| PF-2 | 每次 HTTP 动作一次 DNS | http_action.py:80 → :52 `asyncio.get_running_loop().getaddrinfo` |
| PF-3 | WebUI 静态/页面读取是**同步阻塞**且从 async 处理器直调 | `webui_loader.py:78-80` `read_page` / `:86-88` `read_static` 用阻塞 `open().read()`；调用链 `src/services/webui_panels/plugin_webui_static.py:27 async def` → `:39` → manager.`plugin_webui_static_file`(manager.py:427 是 **sync def**) → :434 `read_static` |
| PF-4 | HTML/CSS 净化在主事件循环上做 CPU 活 | webui_security.py:270（每次 new `_Sanitizer`）、manager.py:404-405 调用点 |
| PF-5 | `plugin.call` 每次约 2 遍全量深拷贝/重建 | comm.py:255 `sanitize_value` 在 :495、:523、:528、:547、:552 被反复调用 |
| PF-6 | 线性扫描 | router.py:121-133 `instances_of` + `get`（`resolve` 最多 2 次遍历） |

**反向结论（无问题）**：10 个支撑模块**未发现无界缓存** —— router.py:207 `_inflight` 在 finally pop(:318)、`_stats` 键固定(:208-213)；runtime.py:66 `_pending` 在 finally pop(:329)、`_stderr_tail` 上限 4096(:191)、`_output_bytes` 超限即杀(:387-394)。

### F.4 `_run_action` 分支计数口径（消除"105 分支"歧义）

| 口径 | 数量 | 命令 |
| :--- | ---: | :--- |
| 任意缩进的 `if action_type` 条件 | **52** | `awk 'NR>=2152 && NR<=2482 && /if action_type/'` |
| 顶层（8 空格）条件 | **49** | = 9 条族集合分派(2154-2170) + 40 条动作名分支(2172-2481) |
| 嵌套（12 空格）条件 | 2 | 2186（`send_private_message` 选择目标）、2313（`is_group_owner` 角色判断） |
| 去重后的动作名 | **181** | 见附录 E.1 |
| 控制流语句总数（if/elif/for/while/try/except） | 118 | `awk 'NR>=2152 && NR<=2481' | grep -c "if \|for \|while \|try:\|except "` |

→ 任务书所说"105 分支"未在任何单一口径下复现；建议以 **181 个动作名 / 49 条顶层条件**作为拆分工作量的口径（覆盖完整、可机器校验）。
