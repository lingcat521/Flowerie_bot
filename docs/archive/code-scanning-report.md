# Code Scanning 告警审计与修复 · 最终报告

> 对应任务书 §18。数据来源：GitHub Code Scanning API（`state=open`）+ 逐条 alert 详情（含 taint 消息）。
> 结论口径：**不以清零为目标**，逐条给出判定与证据。

## 一、总体

| 项 | 数值 |
| :--- | :--- |
| 审计起点（open） | **56 条**（7 类规则） |
| 终点（open） | **50 条**（3 类规则；CodeQL 分析落在 `e8d6f86`） |
| 收敛轨迹 | 56 → 52（`5abfcf6`）→ 51（`d16a316`）→ **50**（`e8d6f86`） |
| 剩余 50 条的构成 | `py/path-injection` 32（**暂时无法证明**，已加固）+ `py/url-redirection` 17 + `py/full-ssrf` 1（**误报**，附证明测试） |
| 已消除 | `py/insecure-temporary-file` ×2、`actions/missing-workflow-permissions` ×2 |
| 第二轮真修 | `py/redos`、`py/clear-text-logging-sensitive-data`（首轮修法不彻底，复跑后复现；已按「形状可证」重修，**均已在最新分析中关闭**） |
| 判定为误报 | `py/url-redirection` ×17、`py/full-ssrf` ×1 —— **已通过 Code Scanning API 逐条标记 `dismissed`（false positive）**，评论写明理由与证明测试文件；可随时撤销 |
| 标记误报后的 open | **32 条**（全部为 `py/path-injection` 的「暂时无法证明」；如实保留为 open，不做误报标记） |
| 真漏洞已修 | `py/path-injection`（uninstall 越界删除、`_file_*` 包含性检查失效）、`py/redos`、`py/insecure-temporary-file` ×2、`actions/missing-workflow-permissions` ×2、`py/clear-text-logging` ×1 |
| 新增回归测试 | **6 个文件、26 条**（全部零依赖，本地可跑；另把 1 条「测试里不得留危险正则」的仓库级闸门并入其中） |

## 二、逐类结论

### 1. py/path-injection（32 条，error/high）

**判定：真漏洞 + 工具无法证明的加固项**

- **真漏洞**：`PluginManager.uninstall(plugin_id)` 直接用 WebUI 表单传入的 id 拼路径并 `shutil.rmtree`；
  `_file_read/_file_write/_file_list` 的 `os.path.commonpath([base, target]) != base` 是拿
  「由 id 推导出的 base」去比 —— id 带 `../` 时 base 已在 `plugin_dir` 之外，检查形同虚设。
  校验只存在于 `plugins/manifest.py` 的 `_ID_RE`（解析清单时），删除/文件入口没有。
- **修复**：新增 `_PLUGIN_ID_RE`（与 manifest 同源）+ `_plugin_base()`（先校验 id，再对 `plugin_dir`
  做 realpath + commonpath 包含性检查）；`uninstall` 与三处 file 操作全部改用。
- **进一步（§9 情况 B）**：把 `os.path.basename()` 净化与正则校验**内联到 sink 同函数**（共 4 处），
  让 CodeQL 的局部数据流也能看出污染被切断。
- **残余**：其余 sink 的安全性仍主要依赖上层校验，CodeQL 局部数据流可能继续报 ——
  属任务书 §10 的「**暂时无法证明**」，已在 `docs/security.md` 如实声明（不伪装成误报）。

### 2. py/url-redirection（17 条，error/medium）

**判定：误报（False Positive）**

- 全部 `web.HTTPFound(...)` 的目标都以**硬编码 `/panel` 开头**（f-string 与字符串拼接两种写法都查了）；
- 插入查询串的片段全部受约束：`quote()` 转义、`isdigit()` 门禁（群号）、上游已 quote 的成品串
  （`gid_q` / `_catq`）、或先过 `ConfigService.CATEGORY_ORDER` 白名单的分类名 `cat`；
- 插件 WebUI 的 `{pid}/{page}` 来自 aiohttp 路由段（不含 `/`），凑不出 `scheme://host`。
- **证明**：`tests/test_no_open_redirect.py` 固定两条不变量（目标必须以 `/panel` 开头；不得存在
  「整串来自变量」的重定向）。第三项（插入片段是否转义）**故意不做静态断言**并写明理由。

### 3. py/insecure-temporary-file（2 条，error/high）

**判定：真漏洞（测试内）** → `tempfile.mktemp` 改为 `mkstemp` + `os.close`（竞态 + 已弃用）。

### 4. actions/missing-workflow-permissions（2 条，warning/medium）

**判定：真问题** → `ci.yml` / `acceptance.yml` 增加 `permissions: contents: read`（最小权限）。

### 5. py/full-ssrf（1 条，error/critical）

**判定：误报** —— `installer.py` 下载路径已有三层防线且都在 sink 之前：
`validate_mcp_server_url`（字面量校验）+ `_check_dns`（解析结果校验，抗 DNS rebinding）
+ `follow_redirects=False`（拒绝 3xx 二次跳转）。
**证明**：`tests/test_installer_ssrf_proof.py`（顺序不变量 + 13 类载荷全拒 + 正常 https 放行）。
**残余风险**：DNS 校验与建连之间存在 TOCTOU 窗口（未做连接后校验），如实声明。

### 6. py/redos（1 条，error/high）

**判定：真漏洞（实测坐实）** —— `_CQ` 正则 `(?:,[^\[\]]*)*` 内外两层 star 划分不唯一。
实测（`[CQ:0,` + N 个逗号）：10/14/18 个逗号 = 0.2 / 3.7 / 60.4 ms（×16 递增），
**40 个逗号直接卡死进程**（审计时第一次运行该正则的命令无任何输出）。
**修复**：每个参数以非逗号起头 → 线性（2000 个逗号 0.008 ms），语义 5 组样例一致。

### 7. py/clear-text-logging-sensitive-data（1 条，error/high）

**判定：真漏洞** —— 验收脚本把 `DEEPSEEK_API_KEY` 明文打进 CI 日志。
**修复**：新增 `_masked_key()`，只回显 `已配置(长度=.., 前缀=..)`。

## 三、回归测试（5 个文件 / 19 条）

| 文件 | 条数 | 覆盖 |
| :--- | ---: | :--- |
| `tests/test_installer_ssrf_proof.py` | 4 | SSRF 三层防线顺序、13 类载荷、正常放行 |
| `tests/test_plugin_path_injection.py` | 5 | id 正则语义（从源码 AST 取真实正则）、越界全拒、合法放行、校验先于拼路径、内联净化 |
| `tests/test_code_scanning_redos.py` | 4 | 正则无歧义、2000 逗号 < 1s、语义一致、禁止 mktemp |
| `tests/test_no_open_redirect.py` | 2 | 站内重定向前缀不变量、无变量整串重定向 |
| `tests/test_webui_assets.py`（追加） | 4 | 静态资源 sink 层文件名白名单 |

## 四、如实声明

1. **未做真机/运行时渗透验证**：以上判定基于代码路径与单元/结构性测试，不是黑盒攻击验证。
2. **CodeQL 复跑已完成**：56 → 52 → 51 → **50**。六条真漏洞（`redos`、`clear-text-logging`、
   `insecure-temporary-file` ×2、`missing-workflow-permissions` ×2）全部关闭；中途 `redos` 与
   `clear-text-logging` 曾在下一轮分析里**复现**（首轮修法不彻底），重修后才真正关闭 ——
   过程与教训见 `docs/security.md` 的「第二轮」。剩余 50 条均为误报或「暂时无法证明」，
   已逐条给出证明测试与残余风险声明。
3. **两项残余风险**（见 `docs/security.md`）：installer 的 TOCTOU 窗口；CodeQL 局部数据流
   不识别跨函数自定义校验导致的「暂时无法证明」。
