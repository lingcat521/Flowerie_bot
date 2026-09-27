# WebUI 与配置域 · Phase 0 只读审计报告

- 审计对象：仓库 /storage/emulated/0/Flowerie_bot（Python，Flowerie QQ Bot）
- 阶段：**Phase 0 只读审计**（未修改仓库任何文件；未执行 pytest；未提交）
- 审计范围：src/services/web_ui.py、src/services/webui_panels/、src/services/webui_render/、
  src/services/config_service.py、src/services/config_schema.py、src/services/web_ui_assets.py、
  src/services/webui_static.py（转发模块）
- 证据规则：结论一律带 文件:行号；不确定项写入第 8 节 UNKNOWN，不作推断
- 辅助分析脚本（只读，不修改仓库；位于 work/audit/）：
  analyze_self.py、analyze_host_deps.py、analyze_sizes.py、analyze_routes.py
  （Python AST 静态解析：宿主依赖 / 方法数 / 路由表与 handler 比对）

---

## 1. 范围清单（文件 → 行数）

### 1.1 核心与转发模块

| 文件 | 行数 | 备注 |
|---|---|---|
| src/services/web_ui.py | 400 | WebUIServer（聚合 11 个 mixin） |
| src/services/config_service.py | 698 | 25 方法（11 公开 / 14 私有） |
| src/services/config_schema.py | 341 | 纯数据声明（SCHEMA + 枚举 + 范围） |
| src/services/web_ui_assets.py | 51 | 渲染层聚合再导出（薄转发） |
| src/services/webui_static.py | 45 | no_store_html 中间件 + /panel/static/{name} |
| **小计** | **1535** | |

### 1.2 webui_panels/（12 个 py，共 1694 行）

| 文件 | 行数 | 职责 |
|---|---|---|
| webui_panels/plugin_panel.py | 271 | 插件管理（保护级别/扫描/上传/URL/启停/卸载/配置） |
| webui_panels/appearance_panel.py | 252 | 主题/背景色/背景图/透明度 |
| webui_panels/persona_panel.py | 180 | 人格 CRUD/全局/群绑定/发言规则 |
| webui_panels/auth_panel.py | 173 | 登录/注册/token/JSON API |
| webui_panels/config_panel.py | 165 | 配置保存 + 模型连通性测试（ping） |
| webui_panels/mcp_panel.py | 153 | MCP server 结构化编辑/测试 |
| webui_panels/account_panel.py | 148 | 用户状态/注销/改密/状态卡 |
| webui_panels/knowledge_panel.py | 128 | 群聊知识 CRUD（按群隔离） |
| webui_panels/nickname_panel.py | 78 | 群特色昵称（表单解析 + 渲染调用） |
| webui_panels/plugin_webui_static.py | 70 | 插件 WebUI 静态/动态资源两条通道 |
| webui_panels/prompt_panel.py | 53 | 群聊自定义 Prompt（全局/按群） |
| webui_panels/__init__.py | 23 | mixin 聚合导出 |

### 1.3 webui_render/（16 个 py + 资源，共 2163 行 py）

| 文件 | 行数 | 备注 |
|---|---|---|
| webui_render/plugin_dsl.py | 319 | 插件 DSL → HTML（受控渲染） |
| webui_render/config_panel.py | 311 | render_config_sections + MCP 编辑器 + _render_config_row |
| webui_render/persona.py | 304 | **render_persona_tab 单函数 297 行 / 16 参数** |
| webui_render/theme.py | 255 | THEMES（7 主题）/ PANEL_CSS / background_rules |
| webui_render/plugins.py | 147 | render_plugin_tab（128 行） |
| webui_render/knowledge.py | 144 | **render_knowledge_tab 137 行** |
| webui_render/account.py | 135 | render_account_tab |
| webui_render/markdown_mini.py | 121 | 迷你 markdown + render_doc（读 docs/） |
| webui_render/appearance.py | 100 | render_appearance |
| webui_render/nicknames.py | 80 | render_nicknames_tab |
| webui_render/pages.py | 62 | 登录/注册/面板壳 |
| webui_render/assets.py | 55 | 读 static/templates + render_template |
| webui_render/plugin_webui.py | 42 | 插件页壳 |
| webui_render/__init__.py | 42 | 再导出 |
| webui_render/category_constants.py | 36 | CATEGORY_ORDER / CATEGORY_LABELS（被 config_service 与 env_template 反向依赖） |
| webui_render/util.py | 10 | **_esc 被重复定义两次** |
| （资源）static/panel.css | 238 | 真实文件 + THEME_VARS 占位符 |
| （资源）templates/*.html | 23+24+22+18 | login/panel/register/register_closed |

**范围内合计（py）**：400+1694+2163+698+341+51+45 = **5392 行**（另含 238 行 CSS、87 行 HTML 模板）。

---

## 2. 候选类职责域拆解表

### 2.1 WebUIServer（src/services/web_ui.py:71-400）

**结构指标（AST 实测）**：本类自有方法 17（公开 4 / 私有 13）；经 11 个 mixin 继承后**类方法总数 97**（私有 93 / 公开 4）；
实例属性 15（web_ui.py:79-98，含 _runner/_site）；构造依赖 10（web_ui.py:75-78）；
生产 fan-in 1（main.py:202），测试/e2e fan-in 9 文件（tests/test_web_ui.py、test_web_ui_panel.py、
test_web_ui_persona_knowledge.py、test_webui_auth_bootstrap.py、test_web_password.py、test_webui_plugin_panel.py、
tests/webui/conftest.py、tests/e2e/_serve.py、tests/acceptance_check.py）。
**被 11 个 mixin 访问的宿主成员 198 次（其中私有 159 次）**。

| 职责 | 证据（文件:行） | 状态所有权 | 谁在调用它 | 可独立测试 |
|---|---|---|---|---|
| 会话 token 表（token→过期时间） | web_ui.py:84,100-107,109-119 | **自己持有**（内存 dict _tokens） | auth_panel.py:31,69,133,170；account_panel.py:124,125,144 | 是（test_web_ui.py:192-204） |
| 登录失败计数（ip→时间戳） | web_ui.py:85,121-129 | **自己持有**（_login_fails） | auth_panel.py:22,34,50,126,139,158；account_panel.py:119 | 是（test_web_ui.py:337-342 已测 429） |
| 凭据解析 + 校验 + 明文迁移 | web_ui.py:131-155 | 外部（ConfigService.repository + Settings） | auth_panel.py:30,132；account_panel.py:41,117,118 | 是（test_web_password.py 全套） |
| 路由表装配（54 条） | web_ui.py:157-226 | 无状态 | aiohttp；start() 调用 | 是（tests/webui/conftest.py:224 已有真服务器夹具） |
| 运行态生命周期（AppRunner/TCPSite） | web_ui.py:86-87,377-400 | 自己持有 | main.py:202；测试夹具 | 是 |
| 监听地址策略 | web_ui.py:366-375 | 无状态（读 config） | start()；测试直调 | 是（test_web_ui.py:44-56） |
| 面板外观偏好存取（webui_prefs） | web_ui.py:228-251 | 状态在 settings.db；**访问器在宿主** | appearance 写 15 次、mcp 写 1 次、_panel_page 读 8 次 | 是 |
| 面板壳组装（tab 分发 + 主题变量 + 背景 CSS） | web_ui.py:297-364 | 无状态 | _handle_panel（:291） | 部分（须构造整个 server；test_web_ui_panel.py 已覆盖） |
| 日志页 HTML 片段 | web_ui.py:339-341 | 无状态 | _panel_page | 否（渲染层无对应函数） |
| 新手文档页 | web_ui.py:253-259 | 无状态 | 路由 /panel/docs/quick-start | 否（每次读盘，见 §7） |

**判定：不拆**（本类自身 400 行、4 个公开方法，是合格的薄门面）；但作为「类」它的耦合面 = 97 方法 / 159 次私有访问，
真正的上帝痕迹分布在 mixin ↔ 宿主之间（见 §5.1）。

### 2.2 11 个 mixin（webui_panels/）

| Mixin | 文件:行 | 方法数 | 自己持有的状态 | 职责域 | 可独立测试 |
|---|---|---|---|---|---|
| AccountPanelMixin | account_panel.py:26 | 6 | **无**（0 实例属性） | 账户卡/注销/改密/状态聚合 | 否（依赖宿主 7 成员） |
| AppearancePanelMixin | appearance_panel.py:76 | 9 | **无**（写入宿主 _set_pref） | 外观偏好 + 背景图 IO | 否 |
| AuthPanelMixin | auth_panel.py:18 | 12 | **无**（改宿主 _tokens） | 登录/注册/JSON API | 否 |
| ConfigPanelMixin | config_panel.py:13 | 7 | 无 | 配置保存 + 5 类模型 ping | 否 |
| KnowledgePanelMixin | knowledge_panel.py:15 | 8 | 无（_meme_manager 注入） | 群知识 CRUD | 否 |
| McpPanelMixin | mcp_panel.py:17 | 7 | 无（写宿主 _set_pref:124） | MCP JSON 编辑/测试 | 否 |
| NicknamePanelMixin | nickname_panel.py:31 | 5 | 无（getattr 取两个 store） | 群昵称 | 否 |
| PersonaPanelMixin | persona_panel.py:13 | 9 | 无 | 人格/发言规则/Prompt | 否 |
| PluginPanelMixin | plugin_panel.py:19 | 13 | 无 | 插件生命周期管理 | 否 |
| PluginWebUIStaticMixin | plugin_webui_static.py:22 | 2 | 无 | 插件资源两条通道 | 否 |
| PromptPanelMixin | prompt_panel.py:10 | 2 | 无 | 群 Prompt 读写 | 否 |

**关键事实：11 个 mixin 合计实例属性 0 个**（AST 实测），全部状态都在宿主或注入的 manager 里。
因此它们**不是**「上帝类换了个文件住」（每个文件只做一个域、方法 2-13 个、无方法重名），
但它们是「上帝类的成员函数换了个文件写」——宿主内部面没有被收窄（见 §5.1）。

### 2.3 ConfigService（config_service.py:80-698）

| 职责 | 证据 | 状态所有权 | 谁在调用它 | 可独立测试 |
|---|---|---|---|---|
| schema 声明（兼容别名） | config_service.py:88-93 | 外部（config_schema） | web_ui.py:271、config_panel.py:146,157 | 是 |
| 面板视图数据组装 | config_service.py:125-143、654-698 | 无状态（读 config+repo） | web_ui.py:353、auth_panel.py:75,96、persona_panel.py:38、knowledge_panel.py:28、plugin_panel.py:31 | 是（test_config_service_full.py:47） |
| 校验 + 规范化 | config_service.py:520-586、588-615、506-518、478-498 | 无状态 | update/update_many/apply_persisted | 是（test_config_validation.py 全套） |
| 持久化双写（.env 原子 + settings.db） | config_service.py:443-454、643-652、617-641 | repo/env_store 注入 | update/update_many | 是（test_config_persistence.py 全套） |
| 启动期合并优先级链 | config_service.py:154-205 | 无状态 | main.py 启动 | 是（test_config_persistence.py:27-211） |
| **管理员账号（注册/改密/注销/Bootstrap Lock/明文迁移）** | config_service.py:48-77、206-255、257-280、282-306、308-313、315-344、346-366 | 状态在 repo + .env + Settings | auth_panel.py:45,58,144,153,164、account_panel.py:121,141、web_ui.py:134-135,152 | 是（test_webui_auth_bootstrap.py:32-208、test_web_password.py） |

**判定：部分拆**（校验/持久化 与 管理员账号 是两套不同职责：前者强依赖 SCHEMA，后者完全不依赖 SCHEMA）。
**行数红线**：tests/test_web_ui_persona_knowledge.py:457 硬编码 src/services/config_service.py 上限 700，当前 **698 行 → 仅剩 2 行余量**。

### 2.4 config_schema.py 与渲染层

- **config_schema.py**：纯数据（SCHEMA 232 行 + _ENUM_VALUES/_ENUM_OPTIONS/_RANGES），**无方法、无状态**；
  消费者：config_service.py:26-31、src/services/env_template.py:111-114（**非 WebUI 消费者**）、
  经 ConfigService 别名间接被 webui_render/config_panel.py:3-8 使用。判定：**不拆**。
- **webui_render/**：全部无状态纯函数，无 God class 迹象。唯一结构问题是 3 个长函数：
  render_persona_tab（persona.py:7-303，297 行/16 参数）、render_knowledge_tab（knowledge.py:7-143，137 行）、
  render_plugin_tab（plugins.py:20-147，128 行）。判定：**包不拆，函数内部拆块**。


---

## 3. 上帝类判定（拆 / 部分拆 / 不拆）

| 候选 | 判定 | 一句话理由 | 预估风险 |
|---|---|---|---|
| **WebUIServer（聚合类）** | **部分拆** | 400 行/4 公开方法看似薄门面，但它把「会话 token 表 + 登录限速计数 + 凭据校验 + 外观偏好存取 + tab 分发 + 路由表 + 生命周期」7 个域的状态与逻辑攥在一处，被 11 个 mixin 以 198 次（159 私有）访问——形态上已从上帝类变成「上帝基类」 | 中：拆 AuthService 会动 43 处 _check_token 调用点与 5 种未认证响应语义（401 JSON / 302 / 登录页 / 403 / 404），必须逐路由保留 |
| **11 个 Mixin 本身** | **不拆** | 每个文件只做一个域、方法 2-13 个、实例属性 0 个、方法名无冲突（AST 实测 0 重名），是真横切而非「换个文件住的上帝类」；改组合式 handler 要重命名 80 个方法 + 54 条路由，收益低 | 低（不动）；但 1 处 mixin↔mixin 横向依赖与 3 处未接线必须修（§5.1、§6.2） |
| **ConfigService** | **部分拆** | 25 方法里 7 个（hash/verify/register_user/admin_initialized/change_credentials/_effective_credentials_safe/unregister_account/migrate_plaintext_password 计 8 个入口）是**账号与凭据域**，与配置 schema 零耦合；同时文件距 700 行红线只剩 2 行，不拆就再放不进新功能 | 中：hash_password/verify_password/is_hashed_password 是模块级函数且被 tests/test_web_password.py:16 与 web_ui.py:34 直接 import，必须保留再导出 |
| **config_schema** | **不拆** | 纯数据表，零方法零状态，单一来源已被 env_template.py:111 复用 | 低 |
| **webui_render 包** | **不拆包** | 全部无状态纯函数；按域分文件已到位 | 低 |
| **webui_render 三个长函数** | **部分拆**（函数内拆块） | render_persona_tab 297 行/16 参数超出可审阅范围；但它是纯函数，保持调用签名即零风险 | 低 |
| **web_ui_assets.py / webui_static.py** | **不拆** | 51 行纯再导出（兼容旧 import 路径）、45 行中间件+一条路由，职责单一 | 低 |

---

## 4. 拆分方案（按优先级；含迁移步骤 + 测试保护 + 回滚点）

> 原则：**先补测试再动代码**；每步可单独合并、单独回滚。回滚点统一为「改动前的基线 commit」
> （Phase 0 只读，未执行任何 git 操作，仅登记为流程要求）。

### S1（最高优先）修 3 条断链 + 1 处未接线（不涉及拆分，纯 bug）

- **S1-1 群专属发言规则永不生效**：main.py:193 创建 group_style_rules，main.py:240 只注入给 message_router，
  main.py:202-207 的 WebUIServer(...) 参数表里没有它 → nickname_panel.py:38-39 的 _style_rule_store 恒为 None
  → persona_panel.py:68-70 保存永远返回「未初始化」、render/persona.py:73-76 永远渲染空表。
  步骤：main.py:202-207 增加 group_style_rules=group_style_rules；nickname_panel.py:38-39 改为构造期注入 + 类型注解。
  保护测试：新增「注入 store 后 POST /panel/persona/grouprules → 302 且 store.all() 含该群」；store 本身已有 tests/test_group_style_rules.py。
  风险：低。
- **S1-2 昵称页保存 404**：render/nicknames.py:74 表单 POST /panel/nicknames，54 条注册路由里没有它（§6.2 清单）。
  步骤：build_app 注册 POST /panel/nicknames → _handle_panel_nicknames_save，**同时必须补 _check_token**
  （nickname_panel.py:41,69 是全项目仅有的 2 个无鉴权 panel handler，见 §6.3）。
- **S1-3 知识配置保存 404**：render/knowledge.py:137 表单 POST /panel/knowledge/config，无该路由
  （_handle_panel_knowledge_config 定义在 knowledge_panel.py:41，未注册）。步骤：注册 POST /panel/knowledge/config。
- **S1-4 插件 DSL 默认表单目标 404**：plugin_dsl.py:151,255 默认 /panel/plugin-actions 无路由。
  步骤：render_plugin_dsl(dsl, default_action=...) 由 plugin_panel.py:151-152 传入 /panel/plugins/webui/{pid}/{page}
  （docs/plugin-webui.md:48、docs/plugin-developer-guide.md:586 已是此契约）；保留旧默认值作为参数缺省，避免打断 tests/test_plugin_dsl.py:57。
- 回滚点：S1-1..S1-4 各自一个 commit，互不依赖。

### S2 抽 AuthService + SessionStore（WebUIServer 的真实状态外移）

- **新组件**：src/services/webui_auth.py
  - SessionStore：**真正拥有** token 表与登录失败计数（web_ui.py:84-85,100-129 迁入）。
    接口：issue() / resolve(request) / revoke(token) / revoke_all() / login_blocked(ip) / record_fail(ip)；
    构造参数 ttl_seconds、max_tokens=512、fail_limit=5、fail_window=60（收纳 web_ui.py:67-68 的模块常量）。
  - AuthService：**真正拥有**凭据解析与校验（web_ui.py:131-155 迁入）+ 复用 ConfigService 的账号方法。
    接口：verify_admin(user,pwd) / effective_credentials() / credential_source()。
- 迁移步骤（顺序不可颠倒）：
  1. 新增 webui_auth.py（纯新增、行为不变），在 WebUIServer.__init__ 建好 self._sessions / self._auth，
     并**暂时保留** _tokens/_login_fails/_verify_admin 等旧名作为转发属性（是否有测试直接访问待确认，见 UNKNOWN-3）。
  2. 43 处 self._check_token(request) 机械替换为 self._sessions.resolve(request)，**逐面板文件提交**（一次一个文件）。
  3. appearance/mcp 的 16 处 _set_pref 等 S3 的 PrefStore 落地后再动。
- **硬约束（架构 Gate）**：新模块**不得 import aiohttp**（tests/test_architecture_gates.py:24-41 的 KNOWN_SERVICES_AIOHTTP 白名单
  只许缩小不许增长，且白名单过期同样失败）。若必须用 aiohttp 类型，改用鸭子类型，或同步评审更新白名单。
- 保护测试：test_web_ui.py:192-204（401/200）、:337-342（429 限速）、test_webui_auth_bootstrap.py:32-208（Bootstrap Lock 全流程）、
  test_web_password.py（哈希/迁移/会话撤销）、tests/webui/conftest.py:224（真服务器 cookie 登录）。
- 风险：**4 种未认证响应形态必须逐条保留**（200 登录页 / 302 → /panel / 403 文本 / 404 文本 / 401 JSON），
  因此**不建议**把鉴权改成单一 aiohttp 中间件（会抹平差异，直接踩 test_web_ui.py:282-285 与 tests/webui 的断言）。

### S3 抽 PrefStore（外观与 mcp_test_ 偏好）

- **新组件**：src/services/webui_prefs.py 的 PrefStore（包装 config_service.repository 的 get_pref/set_pref/delete_pref/list_prefs）。
  拥有：键约定（bg_color__theme、bg_size、panel_style、mcp_test_name）+ 批量写 set_many(dict) → 一次事务。
- 迁移：web_ui.py:228-251（_pref/_set_pref/_get_prefs）→ PrefStore；appearance_panel.py:146-156,170-178,223,247 的 16 处写、
  mcp_panel.py:124 的 1 处写、appearance_panel.py:171 与 mcp_panel.py:49 的 2 处列出。
- 附带收益：修掉 §7-3「一次保存 7-8 次独立事务」。
- 保护测试：test_web_ui_panel.py:350-362（主题/颜色跨重启仍在）、同文件主题默认背景相关用例（:249 起）。
- 风险：低。_get_prefs() 的键与默认值（web_ui.py:236-251）是渲染层输入契约，须逐字保留。
- **注意**：config_service.repository 被 4 处直接穿透（account_panel.py:40、appearance_panel.py:171,173、mcp_panel.py:49），
  且 tests/test_web_ui_persona_knowledge.py:543 直接用 svc.repository.get_config(...) 断言 → **repository 是对外契约，不能改名**。

### S4 从 ConfigService 抽 AdminAccountService（配置与账号分家）

- **新组件**：src/services/admin_account.py
  - 真正拥有：scrypt 哈希算法与参数（config_service.py:41-45,48-77）、Bootstrap Lock 的 CAS 流程（206-255,257-280）、
    改密（282-306）、注销（315-344）、明文迁移（346-366）。
  - 显式依赖：repository + env_store（构造注入），**不需要** config / SCHEMA。
  - ConfigService 保留同名方法作为**一行转发**，保证 auth_panel.py:58,164、account_panel.py:121,141 与 14 个测试文件零改动。
  - 模块级 hash_password/verify_password/is_hashed_password 迁到 admin_account.py，并在 config_service.py 顶部再导出
    （保持 tests/test_web_password.py:16 可导入）。
- 收益：config_service.py 698 → 约 500 行，回到 tests/test_web_ui_persona_knowledge.py:457 的红线内。
- 保护测试：test_webui_auth_bootstrap.py（10 用例，含注册竞态 :82、注销撤销会话 :196）、test_web_password.py、
  test_config_persistence.py、test_config_service.py、test_config_service_full.py。
- 风险：中。注册/注销要同时写 .env + settings.db + Settings 内存并含回滚（config_service.py:241-248），必须整块搬迁，不要顺手重构。

### S5 render_persona_tab 内部分块（保持签名不变）

- 目标：persona.py:7-303 → 同文件内 8 个 _block_* 私有函数；主函数只编排，且 persona.py:303 的拼接顺序必须保持。
- 可选：16 参数收敛为 1 个 dataclass；若做，需保留原关键字签名（persona_panel.py:53-61 是关键字调用）。
- 保护测试：test_web_ui_persona_knowledge.py:425-440（标签配对）、:526-548（人格页配置表单与说明文本）、
  acceptance_check.py:385-417（真 HTTP）。
- 风险：低（纯渲染、无状态）。

### S6 渲染层去重（可选，与拆分解耦）

- plugins.py:135-139 改用 config_panel.py:260-310 的 _render_config_row（现被 knowledge.py:134、persona.py:41 正确复用）；
  差异（secret 掩码/需重启 badge/min-max）需先确认契约（UNKNOWN-5）。
- 合并 3 份图片扩展名→MIME 表（§6.1-1）与 8 处布尔真值集合（§6.1-3）。
- 删除 §6.2 的死代码：util.py:8-9 重复定义、config_panel.py:109/115/117 空常量、plugins.py:13-17 未使用常量，零风险。

### S7 路由表外置（低优先）

- build_app（web_ui.py:157-226）的 54 条注册外置为 webui_routes.build_routes(server) -> list[(method, path, handler)]，
  让路由变更不再碰宿主文件，并把本次的路由比对脚本固化成测试：
  「已定义的 _handle* 集合 − 已注册集合」必须为空或落在显式白名单里（可防 §6.2 的断链复发）。
- 风险：低。


---

## 5. 依赖问题

### 5.1 重点问题：是否出现「WebUIServer → Mixin → Mixin 反过来访问 WebUIServer 的几十个内部属性」？

**结论：不是「每个 mixin 几十个属性」，而是「11 个 mixin 共用同一份宿主内部面」——量化如下（AST 实测，行号＝访问点）。**

宿主被访问的**成员总数 = 17**（10 个状态 + 8 个方法 + 3 个非私有成员，其中 _login_fails 仅宿主内部使用），
**访问次数 = 198（私有 159）**：

- 状态：_tokens(web_ui.py:84)、_started_at(88)、_data_dir(90)、_tool_manager(92)、_persona_manager(94)、
  _meme_manager(95)、_prompt_manager(96)、_plugin_manager(98)、_status_provider(83)、_login_fails(85，仅宿主内)
- 方法：_issue_token(100)、_check_token(109)、_login_blocked(121)、_record_login_fail(126)、
  _effective_credentials(131)、_verify_admin(140)、_pref(228)、_set_pref(232)
- 非私有：config(79)、config_service(81)、group_nicknames(80)

**逐个 mixin 明细（成员:行号）**

| Mixin | 文件 | 宿主成员数 | 访问次数（私有） | 明细（含行号） |
|---|---|---|---|---|
| AccountPanelMixin | account_panel.py | 7 | 14（10） | _check_token:113,135；_effective_credentials:41,117；_record_login_fail:119；_tokens:124,125,144（**写**）；_tool_manager:49；_verify_admin:118；config_service:40,62,121,141 |
| AppearancePanelMixin | appearance_panel.py | 5 | 23（21） | _check_token:79,168,183,191；_set_pref:146,148,149,150,151,152,156,170,174,175,176,177,178,223,247（**写 15 次**）；_pref:210；_data_dir:207；config_service:171,173 |
| AuthPanelMixin | auth_panel.py | 10 | 29（19） | _login_blocked:22,50,126,158；_verify_admin:30,132；_issue_token:31,133；_record_login_fail:34,139；config_service:45,58,75,86,96,144,153,164；_check_token:65,73,78,91,112；_tokens:69,170（**写**）；_started_at:95；_status_provider:98,100；config:33,136 |
| ConfigPanelMixin | config_panel.py | 3 | 10（2） | _check_token:20,143；config:47,66,86,105,122；config_service:153,157,164 |
| KnowledgePanelMixin | knowledge_panel.py | 3 | 20（18） | _check_token:43,58,67,85,106,119；_meme_manager:18,22,23,31,70,80,88,96,109,115,122,127；config_service:28,52 |
| McpPanelMixin | mcp_panel.py | 4 | 7（4） | _check_token:99；_tool_manager:37,40；config_service:20,31,49；_set_pref:124（**写**） |
| NicknamePanelMixin | nickname_panel.py | 2 | 2（1） | _persona_manager:60；config:48；另 getattr(self,"group_nicknames"):35、getattr(self,"group_style_rules"):39、getattr(self,"_status_provider"):52（**绕过静态类型**） |
| PersonaPanelMixin | persona_panel.py | 6 | 36（30） | _persona_manager:17,19,20,22,25,28,109,112,117,125,127,134,145,149,158,161,168,176,179（19 次）；_check_token:65,85,94,106,121,131,155,165；config_service:38,89,100,114；_prompt_manager:33,34,36；config:27,42；**_style_rule_store:44,68（真横切到另一个 mixin）** |
| PluginPanelMixin | plugin_panel.py | 3 | 42（39） | _check_token:62,97,119,178,189,206,218,234,243,252,264；_plugin_manager:22,25,29,30,35,41,56,84,107,125,136,137,155,180,183,191,202,208,214,220,230,236,239,245,248,258,259（28 次）；config_service:31,257,270 |
| PluginWebUIStaticMixin | plugin_webui_static.py | 2 | 7（7） | _check_token:26,54；_plugin_manager:32,34,39,60,63 |
| PromptPanelMixin | prompt_panel.py | 2 | 8（8） | _check_token:13,33；_prompt_manager:16,20,25,36,44,49 |
| **合计** | | | **198（159）** | 其中 _check_token 一项占 **43 次 / 10 个文件** |

**定性判定**

- **真横切（保留，但换形态）**：self._check_token 共 43 处 —— 每个 HTTP 入口都要过关，是标准横切关注点；
  正确形态是显式依赖对象（S2 的 SessionStore.resolve），而不是宿主私有方法。这 43 处没有任何一处需要其它宿主内部状态。
- **伪横切（必须收窄）**：
  - _tokens 被 auth_panel.py:69,170 与 account_panel.py:124,125,144 **直接 pop/clear**（写权限散落 3 处，另 web_ui.py:399 的 stop()）；
    「改密/注销即撤销全部会话」的业务决策与实现都泄漏到 handler。
  - _set_pref 被 appearance（15 次）与 mcp（1 次）写、被 _panel_page 读 —— 外观偏好与 MCP 测试状态挤在同一个偏好多宝箱。
  - **Mixin → Mixin（唯一实例）**：persona_panel.py:44,68 使用 self._style_rule_store，而该 property 定义在 nickname_panel.py:38-39
    → PersonaPanelMixin 单独实例化即 AttributeError（只有聚合进 WebUIServer 才能工作）。这正是任务书点名的形态，其余都是 Mixin → 宿主。
  - _started_at（web_ui.py:88 用 AnnAssign 定义）只被 auth_panel.py:95 读一次 —— 为了 1 行 uptime 把宿主状态暴露给认证域。
- **跨对象私有成员穿透**（非 mixin）：plugin_panel.py:29 调 _plugin_manager._protection_level()（定义 manager.py:935）、
  plugin_panel.py:41 调 _plugin_manager._manifest_of()（manager.py:643）、mcp_panel.py:40 与 account_panel.py:52 的
  getattr(mgr, "_servers")（mcp_tool_manager.py:90）、persona_panel.py:22 的 self._persona_manager.repository.list_group_bindings()
  → 4 处依赖私有名/私有字段取数，重构任一 manager 内部结构都会静默失效。

### 5.2 反向依赖 / 分层倒置

1. **services → render（方向倒置）**：config_service.py:32-35 从 src/services/webui_render.category_constants 导入分类常量；
   src/services/env_template.py:111-114 也从同一渲染模块取 SCHEMA/分类常量 → 「配置分类元数据」的真实归属既不是
   config_service 也不是 webui_render，三处消费者被路径绑死（迁移需同时改 config_service.py:32、env_template.py:112、
   webui_render/config_panel.py:3-8）。
2. **渲染层内部跨模块私有依赖**：knowledge.py:3 与 persona.py:3 直接 from ...config_panel import _render_config_row
   （下划线私有函数的跨模块复用）→ 拆 config_panel 会同时打断 2 个模块；建议提升为公开的 render_config_row。
3. **循环依赖：未发现**。webui_render/* 不 import webui_panels 或 config_service（grep 命中 0）；config_service 也不 import webui_panels。
   唯一倒置是第 1 条（单向，非环）。

### 5.3 权限口径三处不一致（鉴权边界，实锤）

- 权威判定：webui_permission_granted（src/plugins/permissions.py:324-329）+ 别名表 WEBUI_PERMISSION_ALIASES（:269-272）：
  webui.view / webui.action 都接受旧名 web_ui；manager 的所有 WebUI 入口都走它（manager.py:207,248,328,332,606）。
- 面板层却是**字面量成员判断**（3 处口径各异）：
  - plugin_panel.py:38 判断 approved_permissions 里是否含字面量 "web_ui" → 决定插件页是否显示 WebUI 入口链接
  - plugin_webui_static.py:36 同样判断字面量 "web_ui" → 静态资源 404
  - plugin_panel.py:58 判断字面量 "web_ui.files" → 上传/下载放行
- 后果：管理员只批准新名 webui.view 时，页面能开（manager.py:328 放行），但插件页不显示入口（plugin_panel.py:38）、
  静态资源 404（plugin_webui_static.py:36）——同一权限三种口径。
- 另一处不对称（**语义等价、非漏洞**）：_handle_panel_plugin_webui_asset（plugin_webui_static.py:48-70）自身不查 enabled/权限，
  而 _handle_panel_plugin_webui_static（:34-37）查；但 manager.plugin_webui_asset 内部已收口
  （manager.py:602-610 校验 enabled + webui.view + 能力声明）→ 行为等价，属纵深防御层次不一致。

### 5.4 其它隐式 self 状态耦合

- _login_fails 达到 512 个 IP 时**整体 clear**（web_ui.py:127-128）→ 轮换 IP 的爆破可重置所有计数（限速可被绕过）；
  有界，但与同行注释「保留最近失败窗口语义」不符。
- web_ui.py:274 与 :278 复用同一 query 参数 edit（MCP 编辑下标 vs 人格编辑 id）——语义重载，非数字时靠
  except ValueError（:275-276）兜底；拆路由时必须保留这一兼容行为。
- _panel_page 用 request.query 的 tab 白名单（web_ui.py:267-268）与 cat 白名单（:271-272）作为唯一分区约束；
  tab 列表同时硬编码在 render/pages.py:10-19（_TABS）与 pages.py:21-25（_TITLES），两处需同步（新增 tab 时易漏）。


---

## 6. 重复逻辑与死代码候选（带引用证据）

### 6.1 重复逻辑 / 重复常量

| # | 重复内容 | 位置 1 | 位置 2 | 位置 3 / 备注 |
|---|---|---|---|---|
| 1 | 图片扩展名 → MIME 表 | webui_panels/appearance_panel.py:23-29（_CONTENT_TYPES） | plugins/webui_loader.py:22 | plugins/manager.py:444-450（WEBUI_ASSET_MIME）；另 render/appearance.py:75 硬编码 accept 列表 |
| 2 | 插件保护级别字面量 | config_schema.py:242,250（PLUGIN_PROTECTION 枚举） | render/plugins.py:34（("normal","relaxed","unsafe")） | render/plugins.py:10-12 标签 + plugin_panel.py:52（protection == "unsafe"） |
| 3 | 布尔真值集合 ("true","1") | config_panel.py:27,124,135,144,274 | plugin_dsl.py:235 | config_service.py:548,624（共 8 处） |
| 4 | HTML 转义入口 | webui_render/util.py:6-9（**同一函数定义两次**） | nicknames.py:6（from html import escape） | plugin_dsl.py:52（esc）；markdown_mini.py:5；web_ui.py:26（_html.escape，用于 :330,:341 直接拼 HTML） |
| 5 | 配置行 HTML 两份实现 | config_panel.py:260-310（_render_config_row，被 knowledge.py:134、persona.py:41 复用） | plugins.py:135-139 自建 row single 布局 | 后者缺 secret 掩码/需重启 badge/min-max/step，功能不等价 |
| 6 | 凭据解析算法两份 | web_ui.py:131-138（_effective_credentials） | config_service.py:308-313（_effective_credentials_safe） | 另有第三处判定 admin_initialized（config_service.py:257-280） |
| 7 | 敏感值掩码两份 | account_panel.py:65-67（_masked：前 4 + **** + 后 4） | config_service.py:691-698（_mask，同算法） | render/config_panel.py:278-279 只展示已掩码值 |
| 8 | 「前缀_群号」表单键解析两份 | persona_panel.py:71-79（rule_<gid>） | nickname_panel.py:15-28（nick_<gid> 或 nick_<gid>__<pid>） | 两处都再单独处理「group_id + 值」的新增行 |
| 9 | MCP 工具数统计两份 | mcp_panel.py:34-44（_mcp_tool_counts） | account_panel.py:46-58（_mcp_status） | 都读 getattr(mgr,"_servers")[].schemas 长度 |
| 10 | 群号 datalist / option 生成 | render/persona.py:77（gidlist） | render/nicknames.py:53-55（gidlist + persona 选项） | |
| 11 | 面板静态资源名校验两份 | webui_static.py:33 | theme.py:248（panel_asset_body 内再校验） | 后者注释自称纵深防御（theme.py:247） |
| 12 | 配置键集合硬编码散落 | plugin_panel.py:268-269（5 个 PLUGIN_*） | render/plugins.py:129-130（同 5 个键，第三份） | knowledge_panel.py:47-50（8 个 MEME_*）+ persona_panel.py:98（3 个 PERSONA_*），同一份键集在两处维护 |

### 6.2 死代码 / 断链候选

| # | 内容 | 证据 | 判定 |
|---|---|---|---|
| 1 | _esc 重复定义（第 1 个定义被第 2 个覆盖） | webui_render/util.py:6-7 vs :8-9 | 死代码，可删 |
| 2 | _PROTECTION_WARN 定义后从未引用（同文本在 HTML 里内联重复） | render/plugins.py:13-17 定义；:44-48 内联同样文案；全仓 grep 仅 1 处命中定义 | 死代码 |
| 3 | 空常量 + 永不生效的分支 | config_panel.py:109（_BLOSSOM_SUB_SWITCH_KEYS 无人引用）、:115（_BLOSSOM_SUB_CONFIG_KEYS = {}）、:117（_BLOSSOM_ADVANCED_KEYS 无人引用）→ :71 的门控与 :128-136 的 _blossom_sub_switch_on 恒为 True | 死代码（删除行为等价） |
| 4 | 已定义但**未注册**的 handler 3 个 | knowledge_panel.py:41（_handle_panel_knowledge_config）；nickname_panel.py:41、:69（_handle_panel_nicknames / _handle_panel_nicknames_save）——与 web_ui.py:157-226 的 54 条路由比对得出 | 断链（配套表单见 #5） |
| 5 | 指向不存在路由的表单 | render/knowledge.py:137（action="/panel/knowledge/config"）；render/nicknames.py:74（action="/panel/nicknames"） | 用户可见 404：「保存知识配置」「保存全部修改」按钮 |
| 6 | 插件 DSL 默认表单目标无路由 | plugin_dsl.py:151,255 默认 /panel/plugin-actions（54 条路由中无此路径） | 断链；文档契约是 post 到 /panel/plugins/webui/{pid}/{page}（docs/plugin-webui.md:48、docs/plugin-developer-guide.md:586） |
| 7 | __all__ 声明了未导入的名字 | webui_render/__init__.py:37 含 "hex_to_rgb"，但本模块未导入（只有 web_ui_assets.py:35 导入）→ from src.services.webui_render import * 会 AttributeError | 隐性缺陷 |
| 8 | 类体内孤立字符串（等同注释）+ 残留注释 | config_service.py:94-103（无赋值与 docstring 作用）、:105-107；:457 注释指向已移走的枚举代码 | 清理候选 |
| 9 | _style_rule_store 永远 None（未接线） | nickname_panel.py:38-39 + main.py:193,202-207,240 | 功能死（见 S1-1） |
| 10 | 兼容再导出 MAX_UPLOAD_BYTES | web_ui.py:61（noqa: F401） | **不是死代码**：tests/test_web_ui_panel.py:21 直接 import，属契约 |

**注（诚实标注）**：#5 的两条表单虽然在真实浏览器里点下去是 404，但测试只断言「表单 action 字符串存在」
（tests/test_web_ui_persona_knowledge.py:560 断言 action="/panel/knowledge/config"），且 acceptance_check 只覆盖
/panel/knowledge/add（acceptance_check.py:401），所以现有测试锁定了这个「断链契约」——修 S1-3 时需要同步调整该断言。

### 6.3 附带发现（超出拆分范围）

- **未鉴权写端点（潜在）**：nickname_panel.py:41 与 :69 两个 handler 体内既无 _check_token 也无 _login_blocked
  （全项目仅此 2 个 panel handler 如此）；当前未注册所以不可达，**若按 S1-2 直接注册就会变成未认证写入口**。
- **noqa 密度**：范围内 34 处 noqa（33 × BLE001 宽泛 except + 1 × F401），集中在
  config_service.py:189,198,231,241,246,252,303,330,335,361,453（11 处）与
  plugin_panel.py:26,42,49,89,159、appearance_panel.py:87,138,198,221,241（各 5 处）。
  本次重构不应新增 noqa；其中 config_service.py:198,231,246,252,303,335,361 是裸 except（无说明注释），可评估收窄。

---

## 7. 性能热点（只找不改，全部带行号）

1. **每次面板渲染的 SQLite 往返**：_get_prefs() 逐键读 8 次（web_ui.py:237,240,244,245,247,248,249,250 → :229 → settings_repository.py:173-176）；
   配置页再叠加 list_configs()（config_service.py:127 → settings_repository.py:160-163）与
   _get_mcp_test_status() 的 list_prefs() 全表扫描（mcp_panel.py:49 → settings_repository.py:192-195）。
2. **账号页约 26 次单键查询**：_config_status 对 _API_KEYS 的 15 个键逐个 get_value（account_panel.py:62 → config_service.py:145-152，每次 1 条 SELECT）
   + _credential_info 3 次（account_panel.py:40-41 → web_ui.py:134-135）+ 上面的 8 次 pref。
3. **一次外观保存 = 7-8 次独立写事务**：appearance_panel.py:146,148,149,150,151,152,156（+247）→ 每次 set_pref 都是 INSERT+commit
   （settings_repository.py:178-185），无批量事务。
4. **render_config_sections 的 O(n²)**：_blossom_model_status_badge 对**每个配置行**都重建一次
   cur = {x["key"]: ... for x in cfgs}（config_panel.py:26；调用点 :73），_blossom_sub_switch_on 每行再线性扫 cfgs（:128-136）。
   BlossomMemory 分类约 20 键 → 约 400 次重复字典构建/扫描。
5. **全量 list_configs 后只取几项**：persona_panel.py:38-40（只取 3 个 PERSONA_* 键）、knowledge_panel.py:28-29（MEME_* 前缀）、
   plugin_panel.py:31-32（PLUGIN_* 前缀）——每次都要跑完约 200 键的 schema 循环 + 1 次全表查询。
6. **插件页重复劳动**：_render_plugin_page 连续调用两次 list_plugins()（plugin_panel.py:25 与 :35）；
   list_plugins 对每个插件解析 manifest（manager.py:669-693 → :674），且 _manifest_of 即使命中缓存也要做
   m.to_json() != raw 的反序列化比较（manager.py:659-660）→ 一次渲染 = 2×N 次 manifest 再序列化。
7. **每次请求读盘的文档页**：/panel/docs/quick-start → web_ui.py:257-258 → markdown_mini.py:114-121
   （os.path.isfile + open(...).read()，无缓存，且未用 with 关闭，靠 GC）。
8. **背景图缓存自相矛盾**：每次渲染带 ?v=<unix 秒>（web_ui.py:308），而响应头是
   Cache-Control: private, max-age=3600（appearance_panel.py:203）→ 跨秒必重新下载，max-age 形同虚设。
9. **每次连通性测试新建 client**：config_panel.py:54,74,93（httpx.AsyncClient）、:111 与 :128（Embedding/Rerank 客户端，有 finally close）、
   mcp_panel.py:82（aiohttp.ClientSession）——管理员点击级频率，可接受但可复用连接池。
10. **每次 admin_initialized() 全量解析 .env**：config_service.py:269-277 → env_store.py:38-42（dotenv_values 重新读盘+解析）；
    注册页/注册 POST 单请求内最多 3 次（auth_panel.py:45,144,153）。
11. **status_provider 每次渲染都重算群列表**：main.py:196-201（sorted(groups.keys())），调用点
    auth_panel.py:98、persona_panel.py:48-50、nickname_panel.py:52-54。
12. **无界缓存核查结论：未发现无界缓存**。_tokens 有 512 上限清理（web_ui.py:103-104）；_login_fails 到 512 整体 clear
    （web_ui.py:127-128，语义问题见 §5.4）；PluginManager._manifest_cache 按 plugin id 且有失效点（manager.py:78,829,924）。

---

## 8. UNKNOWN / 未验证项

1. **UNKNOWN（未运行测试）**：Phase 0 未执行 pytest，因此「现有 WebUI/配置测试是否全绿」、本机是否具备真 pydantic
   （tests/webui/conftest.py:200 注释称本机是 stub、CI 才是真闸门）均未验证。
2. **UNKNOWN（真实渲染）**：零 JS 交互在真机浏览器上的表现、CSS 主题切换、details 折叠行为未验证。
3. **UNKNOWN（测试直接访问宿主私有成员）**：已确认测试会直调 handler（tests/test_web_ui_persona_knowledge.py:70-172）
   与 svc.repository.get_config（:543），但**是否还有测试直接读写 server._tokens / server._login_fails 未逐文件核对**
   → 直接决定 S2 能否删除旧属性名，动 AuthService 前必须先 grep 确认。
4. **UNKNOWN（category_constants 归属迁移）**：config_service.py:32 与 env_template.py:111-114 都从 webui_render 取分类常量；
   是否存在其它（未列举的）消费者（docs/scripts/插件）未全仓核对。
5. **UNKNOWN（插件配置行字段契约）**：plugins.py:135-139 与 _render_config_row 的差异（secret/badge/min-max）
   是否为有意设计（插件配置项全是 int/str、无 secret），未与插件文档核对 → 影响 S6 能否直接复用。
6. **UNKNOWN（plugin_panel.py:29 的私有调用）**：_protection_level 是否计划公开，未见 TODO/issue 记录。
7. **UNKNOWN（性能实测）**：以上热点均为静态推断（调用点 + SQL），**未做任何 profiling**；
   面板渲染的实际耗时与「哪个最值得优化」缺少量化排序。
8. **UNKNOWN（数据规模）**：SCHEMA 约 200 键、群数量、知识条数对 §7-4/§7-5 的影响程度未测（测试用假数据）。
9. **已人工核对纠正的静态分析假象**：_started_at 用 AnnAssign 定义（web_ui.py:88），第一版 AST 脚本未计入，
   已人工确认它是宿主属性（auth_panel.py:95 读取）。
10. **未验证**：54 条路由中是否还存在本次之外的「有 handler、无路由」或「有路由、无 handler」残留
    （本次脚本按 _handle* 命名约定比对，非该约定的辅助函数不在比对范围）。
11. **UNKNOWN（WebUI 禁用路径）**：main.py:195 的 if config.WEB_UI_ENABLED 之外是否还有别处构造/复用 WebUIServer
    （如 scripts、docs 示例），未全仓核对。


---

## 9. 兼容面清单（拆分时必须保持的对外契约）

### 9.1 HTTP 路由（54 条，web_ui.py:157-226）

- 入口/壳：GET /、GET /webui（均 302 → /panel）、GET /panel、GET /panel/docs/quick-start、GET /panel/static/{name}
- 认证：POST /panel/login、GET|POST /panel/register、GET /panel/logout
- JSON API（脚本/自动化用；测试断言 401/403/429/200）：POST /api/login、POST /api/register、POST /api/logout、
  GET|PUT /api/config、GET /api/status、GET /api/logs（tests/test_web_ui.py:192-372）
- 配置/测试：POST /panel/save（兼容单键 key/value 与分组表单，config_panel.py:150-164）、POST /panel/test/model
- 外观：POST /panel/appearance、POST /panel/appearance/restore、POST /panel/appearance/delete-image、GET /panel/background
- 账户：POST /panel/account/unregister、POST /panel/account/credentials
- MCP：POST /panel/mcp/edit
- 人格（8 条）：POST /panel/persona/config|default|global|save|delete|group|admin-rules|grouprules
- Prompt：POST /panel/prompt/global、POST /panel/prompt/group
- 知识：POST /panel/knowledge/view|add|save|delete|clear
- 插件：POST /panel/plugins/refresh|upload|install-url|enable|disable|uninstall|protection|config；
  GET|POST /panel/plugins/webui/{pid}/{page}；POST /panel/plugins/webui/upload/{pid}/{page}；
  GET /panel/plugins/webui/files/{pid}/{name}；GET /panel/plugins/webui/{pid}/static/{path}；
  GET /panel/plugins/webui/{pid}/asset/{path}
  （**静态路由必须先于 {page} 注册**，web_ui.py:169-174 有注释说明原因）
- 失败形态差异（必须逐路由保留）：401 JSON（auth_panel.py:66,74,79,92,113）、302 → /panel（如 persona_panel.py:66）、
  200 登录页（web_ui.py:262-263）、403 文本（appearance_panel.py:192）、404 文本（plugin_webui_static.py:31,33,37）

### 9.2 handler 方法名（测试/夹具直接调用，不能重命名）

_handle_panel_persona_*（tests/test_web_ui_persona_knowledge.py:70-223）、_handle_panel_knowledge_*
（同文件 :148-195）、_handle_panel（:531）、_handle_panel_appearance_save 等（tests/test_web_ui_panel.py 大量直调）。

### 9.3 模板变量（render_template 的 {{var}}，render/assets.py:50-55）

- panel.html：css_rev（出现 2 次）、bg_rules、body_class、inline_style、tabs、page_title、msg_html、body_html（pages.py:52-61）
- login.html / register.html / register_closed.html：css_rev、msg_html（pages.py:31,40）
- 硬约束：模板文件名（panel.html / login.html / register.html / register_closed.html）与 css_rev = PANEL_ASSET_VER
  （theme.py:237）在 tests/test_webui_assets.py:51-72 有断言
- panel.css 的 {{THEME_VARS}} 占位符必须在服务端替换（theme.py:228,240-255；tests/test_webui_assets.py:31-38）

### 9.4 Python import 面（跨模块契约）

- from src.services.web_ui import WebUIServer（main.py:31）与 MAX_UPLOAD_BYTES（tests/test_web_ui_panel.py:21；web_ui.py:61）
- from src.services.config_service import ConfigService, hash_password, verify_password, is_hashed_password（tests/test_web_password.py:16）
- ConfigService.SCHEMA / CATEGORY_ORDER / CATEGORY_LABELS / _ENUM_VALUES / _ENUM_OPTIONS / _RANGES 类属性别名
  （config_service.py:88-93；使用点 web_ui.py:271、config_panel.py:146,157）
- ConfigService.default_env_path（@staticmethod）；config_service.repository 属性
  （account_panel.py:40、appearance_panel.py:171,173、mcp_panel.py:49、tests/test_web_ui_persona_knowledge.py:543）——**不可改名/不可私有化**
- 渲染层函数名与签名：render_panel_page(*, ...) 全关键字（pages.py:43-44）、
  render_config_sections(configs, active_cat, mcp_edit, mcp_test_status, mcp_tool_counts, category_order, category_labels)
  （config_panel.py:37-38；测试用 category_order/category_labels 注入解耦，tests/test_webui_blossom.py:93-108）、
  _blossom_on 与 _blossom_sub_switch_on（tests/test_webui_blossom.py:3-5 直接 import 私有名）、
  render_plugin_dsl（tests/test_plugin_dsl.py、tests/test_plugin_webui_integration.py）、
  render_doc 与 render_md（tests/test_markdown_mini.py）、render_nicknames_tab 与 apply_nicknames_form
  （tests/test_web_ui_nicknames.py:11-20 用 importlib 直载 nickname_panel.py → **该文件不能引入 pydantic 链**）
- 渲染层常量：PANEL_CSS / PANEL_CSS_REV / PANEL_ASSET_VER / THEMES / THEME_ORDER / theme_*（web_ui_assets.py:27-41 再导出；
  tests/test_webui_assets.py:15-20）
- API 契约：/api/status 返回 version/uptime_seconds/config_count/metrics（auth_panel.py:93-109；tests/test_web_ui.py:346-383）

### 9.5 架构 Gate（静态检查，会直接失败的那种）

- tests/test_architecture_gates.py:24-41（KNOWN_SERVICES_AIOHTTP）：**只许缩小不许增长**，且白名单过期（实际缩小）同样失败
  → 新增任何 import aiohttp 的 services 模块都会被 Gate P 拦下；S2 的 SessionStore/AuthService **必须不 import aiohttp**
  （用鸭子类型取 header/cookie），或同步评审更新白名单（等于改测试）。
- tests/test_web_ui_persona_knowledge.py:442-463：web_ui.py ≤ 430、web_ui_assets.py ≤ 120、config_service.py ≤ 700、
  ai_client.py ≤ 430、message_router.py ≤ 650 → 只有先做 S4，config_service.py 才有新增空间。
- tests/test_web_ui_persona_knowledge.py:466-516：拆分后类结构与 @staticmethod 必须保留
  （点名 AccountPanelMixin 的 5 个方法 + _bg_color_pref_key / _mcp_server_error / _fmt_ts / effective_host 的 @staticmethod）。

---

## 10. 重点问题直答（对应任务书点名的 5 问）

1. **是否出现「Mixin 反过来访问 WebUIServer 几十个内部属性」？**
   数值上：11 个 mixin 合计 198 次访问宿主成员（私有 159），宿主内部面 17 项，其中 _check_token 一项占 43 次。
   单看每个 mixin 是 2-42 次、2-10 个成员，**没有任何一个 mixin 达到「几十个内部属性」**；但 11 个 mixin 共享同一份
   未被收窄的宿主内部面。**唯一真正的 Mixin → Mixin 反向依赖**是 persona_panel.py:44,68 用 nickname_panel.py:38-39
   定义的 _style_rule_store。判定：**不是「上帝类换了个文件住」（职责域是干净的），但是「上帝基类」**——
   错在状态与横切逻辑仍归宿主，不在 mixin 的粒度（详见 §5.1）。
2. **路由/鉴权/会话/token/登录失败计数/静态资源/面板分区/渲染的边界在哪？哪些该变成显式依赖对象？**
   - **该抽**：SessionStore（token 表 + 登录失败计数，web_ui.py:84-85,100-129）、AuthService（凭据解析+校验+迁移，
     web_ui.py:131-155）→ 它们是宿主仅有的两块真实状态与安全关键逻辑，且可独立测试（S2）。
     PrefStore（web_ui.py:228-251 + 16 处写）→ 消除跨域共用的偏好多宝箱与 7-8 次写事务（S3）。
   - **不值得动**：路由表（web_ui.py:157-226，纯粹装配，外置成函数即可，S7 可选）；
     no_store_html 中间件与 /panel/static（webui_static.py:11-45，45 行、职责单一、登录页也要用它）；
     面板分区（tab/cat 白名单，web_ui.py:267-272）与渲染层（webui_render/*，无状态纯函数）。
   - **不建议**：把鉴权改成单一 aiohttp 中间件——4 种未认证响应形态（200 登录页/302/403/404/401 JSON）是既有契约。
   - **顺带必修**：面板层 3 处权限字面量判断与 manager 的别名判定口径不一致（§5.3）。
3. **webui_panels 与 webui_render 是否职责重叠（同一份数据两处拼 HTML）？**
   **整体不重叠**：panels 负责取数 + POST 处理 + 重定向消息，render 负责纯 HTML 拼装；11 个 panel 里只有 3 处例外
   （web_ui.py:258 文档页外壳、:330 消息条、:340-341 日志 pre 由宿主直接拼 HTML）。
   真正的重复是配置行渲染两份（config_panel.py:260-310 vs plugins.py:135-139）与 12 类重复常量/算法（§6.1）。
4. **ConfigService 与 config_schema 的边界是否混在一起？是否存在一次请求多次读配置？**
   - config_schema 是纯数据、零逻辑，边界干净；**混在一起的是 ConfigService 内部**：配置校验/持久化（12 方法）
     与管理员账号凭据（8 方法）两个域共存，且 _display/_field_meta/_mask 把「面板视图数据」也放进了 service（§2.3）。
   - 重复 IO 确实存在：同一请求内 _get_prefs 8 次单键查询、账号页约 26 次单键查询、外观保存 7-8 次独立写事务、
     persona/knowledge/plugin 页各自跑一遍全量 list_configs 只取几项、admin_initialized 每次全量解析 .env（§7）。
5. **兼容面（拆分时必须保持）**：54 条路由 + 逐路由失败形态、handler 方法名、4 个模板文件名与 8+2 个模板变量、
   web_ui_assets 的再导出常量、ConfigService 的类属性别名与 repository 属性、渲染层函数签名与私有名
   （_blossom_on 等被测试直接 import）、两类架构 Gate（aiohttp 白名单 + 行数上限）——详见 §9。


---

## 附：只读合规声明（可核验）

- 本次审计对仓库 /storage/emulated/0/Flowerie_bot **只执行读操作**：read/grep/wc/head/tail/sed -n/find/grep -r，
  以及用 python3 以 ast 静态解析源码（**未 import 仓库模块**，未产生 .pyc）。
- 核验命令与结果（2026-09-28 02:16:21 +0800）：find /storage/emulated/0/Flowerie_bot -newermt '-45 minutes' -type f
  （排除 .git）→ 命中 **1** 个文件：.pytest_cache/v/cache/nodeids（owner u0_a0，时间 02:15:18）。
  该文件**不是本次审计写入**（本轮未执行 pytest；同目录另有并行审计产物 core-audit-phase0.md / plugins-godclass-audit.md，
  时间同为 02:15，判断为并行进程的 pytest 运行），如实记录以便上级核对。
- 未执行 git 任何写操作（无 add/commit/checkout/stash）；未新增/修改/删除仓库内任何文件。
- 报告与 4 个分析脚本全部写在 work/audit/ 下（仓库之外）。

