# 安全模型（Security Model）

> 最后更新 v2.2.2（场景：识图 SSRF 校验/重定向每跳校验/UA；路径安全化；配置双格式）。
> 安全边界与防护设计（含 Review 已知边界）如下。
> 插件开发侧的接口性安全规范见 [plugin-developer-guide.md](https://github.com/lingcat521/Flowerie_bot/blob/main/docs/plugin-developer-guide.md)，本节侧重架构性保证。

---

## Review 已知边界（2025-09 全库审查确认——记录而非隐藏）

**设计内信任边界（已确认合理）**：
- 插件子进程与主进程同 OS 用户/文件系统：插件可直接读 `.env`/配置中的密钥落盘值
  （`DEEPSEEK_API_KEY` 等）。防护=权限批准流程 + 子进程环境白名单 + `python -I` 隔离；
  文件系统级沙箱为后续演进方向（不影响当前隔离承诺：插件**不能**影响其他插件/主进程数据面）。
- 插件 AI 视觉调用可请求 loopback（NapCat 本地图片信任边界；图片 URL 私网/元数据默认拒绝）。
- 管理后台自身无 TLS（`WEB_UI_ALLOW_LAN` 明文部署；Cookie over HTTPS 需前置反代）。

**已知限制（低危，择机修复）**：
- DNS-rebinding TOCTOU：插件 HTTP 校验 IP 后连接时重新解析（标准缓解需连接绑定）。
- `_load_module` 仅校验 entry 最终组件 symlink（中间组件穿越由 manifest 正则由安装器兜底）。
- `blossom_memory` 每日限额读-改-写非原子（单进程内近似，可接受）。
- `trace` 读取全局日志尾部（限制为插件批准后可见，无写权限）。

1. 三层安全边界（互不绕过）

Flowerie 的提示词注入防护按**权限层级**隔离，低层指令不能覆盖高层策略：

```
Runtime Security Policy    （运行时安全策略 / 输入安全声明 / 记忆铁律）   ← 最高，不可覆盖
        ↓
Persona                    （人格 system_prompt + 全局说话风格规则）     ← 继承，但不可突破
        ↓
Admin Response Rules       （ADMIN_RESPONSE_RULES 补充发言规则）         ← 只做风格补充
        ↓
Memory / MCP / Plugin / Knowledge  （用户记忆 / 工具结果 / 插件输出 / 知识）← 全部视为不可信外部输入
```

- **Runtime Security Policy**：安全声明、记忆协议/记忆安全铁律、知识区边界，由系统框架（AIClient）
  组装，**任何人格、自定义 Prompt、插件输出都无法覆盖**。
- **Persona**：人格内容属于"指令区"（管理员配置），但与 `ADMIN_RESPONSE_RULES` 一样**不能覆盖安全策略**，
  且知识区内容永远标记为不可信上下文知识。
- **Memory / MCP / Plugin / Knowledge**：一律当作**不可信外部输入**处理，互不信任、互不绕过
  ——记忆写入过 `validate_memory_content` 闸门，MCP/插件工具结果与群聊知识过 `sanitize_untrusted_text`
  清洗（注入句式替换为占位符、控制字符与零宽字符清理），且注入为不可信区段，不混入指令区。

---

## 2. 插件安全

### 2.1 安装防护（ZIP / URL）

- **ZIP**：校验压缩包大小（≤5MB，`PLUGIN_URL_MAX_BYTES`）与解压后总大小（≤50MB，`PLUGIN_ZIP_MAX_UNZIPPED_BYTES`，
  防 Zip Bomb）、文件数（`PLUGIN_ZIP_MAX_FILES`）与目录深度；成员名禁止绝对路径与 `..` 段（防 **ZIP Slip / 路径穿越**）；
  拒绝**符号链接**成员；缺 `manifest.json` 或混合多个顶层目录直接拒绝；manifest 严格 schema 校验，未知字段拒绝。
- **URL 下载**：**SSRF 防护**——拒绝内网/回环/私网/链路本地/组播/保留地址、`.local` 主机、userinfo、
  DNS 解析结果命中内网（防 rebinding）；**不跟随重定向**；Content-Length 预检 + 流式大小中止 + 超时 +
  Content-Type/扩展名检查（仅 `.zip` / `.json`）。
- 安装后插件一律处于 **disabled**，由管理员启用并批准权限。

### 2.2 权限强制（PermissionManager）

任何动作（action）在真正执行前都会过 PermissionManager；未批准 → 拒绝并记录 `plugin_permission_denied` 日志。
**关闭插件保护（Unsafe）也不会绕过权限检查**。插件返回「动作」而非直接执行副作用，插件永远无法绕过权限。
（权限列表与保留权限见 [plugin-developer-guide.md](plugin-developer-guide.md) §9。）

### 2.3 进程隔离与运行时限制

- 插件运行在**独立子进程**：Python 用 `python -I` 隔离模式，Node 用子进程，环境变量白名单不含任何 API Key / Token；
  插件不能 `import Flowerie` 内部模块、不能访问 Flowerie 数据库。
- stdin/stdout **JSON-Lines 协议**；崩溃 / 超时被隔离标记 `crashed`，Flowerie 继续运行。
- 资源限制：输出累计上限、单事件动作数上限、入口文件与 manifest 大小、注册表插件总数上限。

### 2.4 保护级别不变式

`PLUGIN_PROTECTION=normal|relaxed|unsafe`。保护级别**只影响运行时资源限制**（超时/输出/动作数），
**任何级别都不豁免**：manifest 校验、管理员权限（Web UI 认证）、进程隔离、日志、崩溃保护、
资源限制、**权限强制（PermissionManager）**。普通 QQ 用户永远不能安装/启用插件或修改权限。

---

## 3. Web UI 认证安全

### 3.1 注册 Bootstrap Lock

- 系统一旦初始化（`.env` 或 `settings.db` 存在管理凭据），公开注册**永久关闭**：
  GET/POST `/panel/register` 与 `/api/register` 一律 403 / 展示「注册已关闭」（无表单）。
- 只有 `UNINITIALIZED` 状态才能创建**第一个**管理员；并发注册用 `admin_bootstrap` 表**原子 CAS** 保证仅一个成功。
- 历史已有凭据自动视为已初始化（绝不因升级而重开注册）。
- 初始化后改账号走登录态 `/panel/account/credentials`（需当前密码）；注销（`/panel/account/unregister`，需当前密码）
  = 显式重置，系统回到 `UNINITIALIZED` 才可重新注册。

### 3.2 登录限流与哈希

- 密码只存 **scrypt 哈希**（`data/settings.db`，优先于 `.env`），永不写明文 / 日志；旧明文兼容比较用恒定时间。
- 登录失败：同一 IP 连续 5 次锁 1 分钟（`_login_fails` 时间窗）。

### 3.3 CSRF 防护设计

- JSON API 走 `Authorization: Bearer <token>`（无 cookie → 天然防 CSRF）。
- 无 JS 面板走 Cookie 会话（`fb_token`，`httponly` + `SameSite=Strict`）。
- 所有管理接口必须管理员 token；未认证一律重定向回 `/panel`。

---

## 4. NapCat WebSocket token 脱敏

`NAPCAT_ACCESS_TOKEN`（forward 模式鉴权）**绝不写入日志**：含 access_token 的 URL 经 `redact_ws_url` 剥离查询串后才
进入日志 / UI（仅显示 scheme + host + path）。插件 URL 下载与 WS 日志同样只记录脱敏后的查询串。

---

## 5. 主动发言概率与管理员规则不可覆盖安全策略

- 主动发言概率（`PROACTIVE_MESSAGE_*` / `ACTIVE_CHAT_*`）只控制**是否/何时**触发回复，**不改变内容安全边界**；
  所有输出仍受安全策略 / 清洗 / 记忆校验约束。
- `ADMIN_RESPONSE_RULES` 仅为**风格补充**（优先级：安全策略 > 人格 > 人格内置规则 > 本条），
  **不能覆盖安全策略**——运行时记忆校验 / 注入清洗 / 预算限制等不会被任何提示文本绕过。

---

## 6. 其它防护

- **知识防污染**：群聊梗知识按群隔离、过清洗闸门；MCP 工具元数据按不可信外部输入处理（防 tool description 注入）。
- **Secret 脱敏**：API Key 只在 UI 显示掩码，留空提交不覆盖；日志不记录密钥明文。
- **双层熔断 / 预算**：AI 熔断 + 群级熔断、三层 AI 预算，防风暴与滥用。
- **SSRF 通用防线**：MCP / 图片 / 插件 URL 均走地址校验与本地-内网白名单。

## Bot SDK 安全边界（v1.3.0）

- **三层隔离**：插件（上层）→ 领域层（中层，零 OneBot 命名）→ OneBot 适配层（下层，
  唯一 import OneBot 语义处）。**插件不接触 OneBot payload / HTTP endpoint / 网络库**；
  所有网络能力经主进程动作出口，SSRF 防护与权限门继续生效。
- **CQ 码阉割**：`[CQ:at,qq=x]` 等段码在中层转换为结构化 `at_list` / `images`，
  插件见不到底层格式；发送侧插件用 `BotMessage`（text/at/image/reply），由下层拼段。
- **撤回边界**：`delete_message` 权限仅允许撤回**本 bot 已发送并记录**的消息
  （`_sent_message_ids` 上限 200）；未记录的 message_id 一律拒绝（防删他人消息）。
- **群管理**：`group_manage` 权限（mute/kick）单独授权；建议只给受信任插件，
  并在命令上加 `rule(is_group_admin=True)` 守卫。
- **匹配注册**：`matcher_register`（read_message）只影响事件筛选与投递，
  不授予任何副作用。

## v1.4 新增边界

- **请求处理**（request_handle）：好友/加群同意是**社交副作用**——只批准给明确处理
  申请场景的插件；approve 必须回传原 flag（伪造 flag 无效）。
- **调度器**（scheduler）：定时任务在主进程执行（asyncio Task）；**间隔下限 1 秒**
  （防刷）；插件进程异常不影响调度器；shutdown 全部清理。任务数不设上限 → 文档
  建议每插件 ≤20 个任务；同插件同名注册幂等（覆盖）。
- **KV**（storage）：plugin_kv 表**按插件命名空间隔离**（key 前缀 plugin_id），
  其他插件不可读；单值 64KB；值为 JSON 或字符串。
- **AI**（ai_chat）：**独立于主聊天预算与三层限频**——插件可无限制消耗 token！
  仅在信任插件批准，且建议命令级冷却（cool_down）自限频。
- **HTTP 扩展**：PUT/DELETE/HEAD 与下载**全部复用** http_action 防线
  （字面量 + DNS 双闸、头过滤、不重定向）；下载 ≤10MB 且只能写插件目录
  （save_to 相对路径校验 + 真实路径公共前缀校验）。
- **记忆写入**：mem_update/mem_clear 复用现有 MemoryManager（审计与 TTL 不变）。

## v1.5 新增边界（社交/群管语义 API）

- **群写操作**（whole_ban/rename/card/title/公告/精华 pin）：统一 group_manage 权限；
  建议只给受信任插件并在命令上叠加 rule(is_group_admin=True) 守卫。
- **修改 Bot 资料**（bot_profile）：能改昵称/签名——全局可见副作用，仅批准明确用途的插件。
- **好友与自我信息**（friends/like/devices/login_info/status）：read_user_info；
  like（点赞）为社交副作用，注意频控（同指标可复用 cool_down）。
- **好友/加群请求处理**（request_handle）：approve 必须回传原 flag；正式环境建议
  人工审核后批准。
- **富内容**（card/markdown/button）：按键/卡片为 QQ 官方 Bot 能力，网关不支持时
  主进程返回明确错误（绝不静默丢弃）；插件应允许失败降级为纯文本。
- **动作名白名单**：PluginApi.call 的 action 名由主进程 `_SENDER_ACTIONS` 白名单校验，
  未登记动作一律拒绝（防任意端点调用）。


## v1.6-1.7 安全补充（变化记录）

- **开关治理**：AI/MEMORY/PROACTIVE/REPEAT/ANTI_SPAM/花语记忆均为真实门控（关=不产生对应副作用）；花语记忆默认关闭=零模型资源
- **花语记忆（BlossomMemory）**：记忆文本/检索结果按不可信数据处理（sanitize 兜底+prompt 段声明低于系统规则）；API URL 复用 MCP 同款 SSRF 校验；指标低基数（仅 result 标签）
- **MCP legacy 单 server SSRF 校验缺口修复**（v1.6）：`MCP_SERVER_URL` 现与多 server 一致校验（URL/超时/最大调用/工具名白名单）
- **存储后端**：默认 SQLite；`STORAGE_BACKEND=postgres` 需自备 PG（psycopg 软依赖）；迁移工具失败安全（源库不动）
- **OneBot 耦合红线**：端点名只存在于 `src/services/sender.py` + 适配层；语义层/插件永不接触端点串（白盒测试锁定）
- **零 JS**：Web UI 全部原生 `<details>`/表单 POST（黑盒验证 0 命中）

安全规则的**权威版本**仍以本文档为准；权限映射总表见 [api.md](https://github.com/lingcat521/Flowerie_bot/blob/main/docs/api.md)。

## Code Scanning 告警审计（2026-09）

> 对 GitHub Code Scanning 的全部 open 告警逐条审计：区分真实漏洞与误报，
> 真漏洞最小修复 + 回归测试，误报给出证明与理由。**不以"清零"为目标** ✔。

审计起点：**56 条 open 告警**（7 类规则）。

| 规则 | 数量 | 判定 | 处理 |
| :--- | ---: | :--- | :--- |
| `py/path-injection` | 32 | **真漏洞**（`uninstall` 可越界删除、`_file_*` 的包含性检查拿 id 推导出的 base 去比） | 新增 `_PLUGIN_ID_RE` + `_plugin_base()`（**先校验 id，再对 `plugin_dir` 做 realpath + commonpath**），`uninstall` 与三处 file 操作全部改用它；回归测试 5 条 |
| `py/url-redirection` | 17 | **误报** | 逐条核对：目标全部以硬编码 `/panel` 开头（f-string 与字符串拼接两种写法都查），插入片段经 `quote()` / `isdigit()` / 上游已 quote 的成品串 / `CATEGORY_ORDER` 白名单约束；插件页 `{pid}/{page}` 来自路由段（不含 `/`）→ 不构成开放重定向。新增 2 条不变量测试 |
| `py/insecure-temporary-file` | 2 | **真漏洞** | `tempfile.mktemp`（竞态 + 已弃用）→ `mkstemp` + `os.close` |
| `actions/missing-workflow-permissions` | 2 | **真漏洞** | `ci.yml` / `acceptance.yml` 增加 `permissions: contents: read`（最小权限） |
| `py/full-ssrf` | 1 | **误报** | `installer.py` 的下载已有三层防线且都在 sink 之前：`validate_mcp_server_url`（字面量）+ `_check_dns`（解析结果，抗 rebinding）+ `follow_redirects=False`；新增证明性测试（顺序不变量 + 13 类载荷全拒 + 正常 https 放行） |
| `py/redos` | 1 | **真漏洞**（实测坐实） | `_CQ` 正则 `(?:,[^\[\]]*)*` 内外两层 star 划分不唯一 → 指数回溯：实测 10/14/18 个逗号 = 0.2/3.7/60.4 ms，40 个直接卡死进程；修复为每个参数以非逗号起头（线性，2000 个逗号 0.008 ms），语义 5 组样例保持一致 |
| `py/clear-text-logging-sensitive-data` | 1 | **真漏洞** | 验收脚本把 `DEEPSEEK_API_KEY` 明文打进 CI 日志 → 新增 `_masked_key()` 只回显长度与前缀 |

### 已知残余风险（如实声明，不当作误报）

- **DNS 校验与建连之间的 TOCTOU 窗口**：`installer` 先解析并校验 IP、再由 httpx 建连（会二次解析），
  理论上存在 DNS rebinding 的时间差。当前依赖"解析一次即校验"降低概率，未做连接后校验。
- **CodeQL 不识别跨函数的自定义校验**：`py/path-injection` 的 32 条中，多数 sink 的安全性由
  `_plugin_base()`（另一个方法）或上游 manifest 的 id 校验保证 —— 局部数据流看不到，故仍会报。
  这类属于「**暂时无法证明**」而非误报（任务书 §10 要求区分）：代码已加固，如要让 CodeQL 认可，
  需把校验内联到 sink 处或使用 CodeQL 认识的 sanitizer 形态。

### 第二轮：两条告警在下次分析里复现后的真修（经验教训）

首轮修复后重跑 CodeQL，`py/redos` #84 与 `py/clear-text-logging-sensitive-data` #9 **在新分析里又出现了**。
两条各自暴露了一个思路问题：

1. **「实测线性」≠「形状安全」**。第一版修法 `(?:,[^\[\],][^\[\]]*)*` 只堵住了「纯逗号」这一条路径
   （实测 N 到 100 仍 < 0.01 ms），但**量词套量词的形状还在**，只是靠 CPython 的 `REPEAT_ONE` 优化才不爆。
   静态分析不管引擎优化，所以它照旧报 —— **它报得没错**。最终改成单一字符集重复
   `r"\[CQ:([^\[\]]+)\]"`（整个模式只有一个量词 → 划分点唯一），动作名/参数改在 `_cq_parts` 里切分，
   并用对历史正则的差分用例锁住等价性。结论口径：判「误报」要区分**引擎优化带来的安全**
   与**形状可证的安全**，前者不能拿来当「误报」的证据。
2. **CodeQL 不认自定义脱敏函数**。验收脚本曾用 `_masked_key(v)` 回显「长度 + 前 3 位」，
   从安全角度已很克制，但它返回的仍是**从密钥派生的字符串**，数据流上仍是敏感数据到日志 sink。
   改法不是去争辩「算不算泄露」，而是**从源头切断**：日志实参只允许由比较得到的布尔结论挑选常量文案，
   密钥值本身根本不进日志参数；并用 `tests/test_no_secret_in_logs.py` 把这个不变量钉住。
3. **一致性约束**：以后新增日志时，敏感值只能以「布尔/枚举结论」形式出现（如「已配置与否」），
   不得出现前缀、后四位、哈希前段等任何片段。
### 回归测试（本地可跑，零依赖）

| 文件 | 覆盖 |
| :--- | :--- |
| `tests/test_installer_ssrf_proof.py` | SSRF 三层防线的顺序不变量 + 13 类载荷全拒 + 正常 https 放行 |
| `tests/test_plugin_path_injection.py` | 从源码 AST 取**真实** `_PLUGIN_ID_RE` 测语义；越界 id 全拒；合法 id 放行；`uninstall` 校验先于拼路径；`_plugin_base` 双保险 |
| `tests/test_code_scanning_redos.py` | 正则**形状不变量**（全模式只允许一个量词、不得有分组量词）；4 类病态输入（含 4000 逗号、20000 字符动作名）< 1s；对**历史正则**的差分等价（9 组合法输入）；刻意容忍的畸形输入行为固定；测试里不得再出现 `mktemp` |
| `tests/test_no_secret_in_logs.py` | `rec()`/`print()` 实参里不得出现敏感来源派生表达式（纯比较除外）；敏感来源不得进入字符串格式化；脱敏函数必须不存在 |
| `tests/test_no_open_redirect.py` | 重定向目标必须以 `/panel` 开头；不存在"整串来自变量"的重定向 |
| `tests/test_webui_assets.py`（追加） | 静态资源 sink 层文件名白名单（拒绝 `../`、分隔符、非 `.css`） |

