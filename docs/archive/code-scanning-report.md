# Code Scanning 告警审计与修复 · 最终报告

> 归档文档（历史快照，内容不再更新）。撰写时的版本与结论不代表当前状态，当前事实以 docs/ 现行文档为准。

> 对应任务书 §18。数据源：Code Scanning API（`state=open`）+ 逐条 alert 详情（含 taint 消息）。
> 口径：**不以清零为目标**，逐条给判定与证据；操作细节与残余风险见 [`../security.md`](../security.md)。

## 一、总体

| 项 | 值 |
| :--- | :--- |
| 起点 → 终点 | **56 条 open**（7 类规则）→ **50 条**（分析落在 `e8d6f86`）→ 标记举证误报后 **open 32** |
| 收敛轨迹 | 56 → 52（`5abfcf6`）→ 51（`d16a316`）→ 50（`e8d6f86`） |
| 真漏洞（全部关闭） | `py/path-injection`（越界删除 + 包含性检查失效）、`py/redos`、`py/clear-text-logging-sensitive-data`、`py/insecure-temporary-file` ×2、`actions/missing-workflow-permissions` ×2 |
| 误报（已 `dismissed`） | `py/url-redirection` ×17、`py/full-ssrf` ×1 —— 评论写明理由与证明测试文件，可随时撤销 |
| 保持 open | **32 条**，全为 `py/path-injection` 的「**暂时无法证明**」（已加固，不标误报） |
| 新增回归测试 | **6 文件 26 条**，零依赖、本地可跑 |

## 二、逐类结论

| # | 规则 | 数 | 判定 | 依据 / 处理 |
| ---: | :--- | ---: | :--- | :--- |
| 1 | `py/path-injection` | 32 | 真漏洞 + 无法证明 | `uninstall(plugin_id)` 直接用 WebUI 传入的 id 拼路径 `shutil.rmtree`；`_file_*` 的 `commonpath([base,target]) != base` 拿「id 推导出的 base」去比 —— id 带 `../` 时 base 已在 `plugin_dir` 之外，检查形同虚设（校验只在 `manifest._ID_RE` 解析清单时做）。**修复**：`_PLUGIN_ID_RE`（与 manifest 同源）+ `_plugin_base()`（先校验 id，再对 `plugin_dir` realpath + commonpath），并把 `basename` 净化与正则**内联到 sink 同函数**（4 处，§9 情况 B）。**残余**：其余 sink 靠上层函数保证，局部数据流看不到 → §10「暂时无法证明」 |
| 2 | `py/url-redirection` | 17 | **误报** | 所有 `HTTPFound` 目标都以**硬编码 `/panel` 开头**（f-string 与拼接两种写法都核过）；插入片段受 `quote()`、`isdigit()`（群号）、上游已 quote 的成品串（`gid_q`/`_catq`）、`CATEGORY_ORDER` 白名单约束；插件页 `{pid}/{page}` 来自路由段（不含 `/`），凑不出 `scheme://host`。**证明**：`tests/test_no_open_redirect.py` |
| 3 | `py/insecure-temporary-file` | 2 | **真漏洞** | 测试里 `tempfile.mktemp`（竞态 + 已弃用）→ `mkstemp` + `os.close` |
| 4 | `actions/missing-workflow-permissions` | 2 | **真问题** | `ci.yml` / `acceptance.yml` 加 `permissions: contents: read`（最小权限） |
| 5 | `py/full-ssrf` | 1 | **误报** | `installer.py` 下载三层防线且都在 sink 之前：`validate_mcp_server_url`（字面量）+ `_check_dns`（解析结果，抗 rebinding）+ `follow_redirects=False`（拒 3xx）。**证明**：`tests/test_installer_ssrf_proof.py`。**残余**：DNS 校验↔建连 TOCTOU 窗口 |
| 6 | `py/redos` | 1 | **真漏洞**（修两次） | `_CQ` 的 `(?:,[^\[\]]*)*` 两层 star 划分不唯一 → 指数回溯：`[CQ:0,` + N 逗号，10/14/18 = 0.2/3.7/60.4 ms（×16），**40 个逗号卡死进程**。首版「参数以非逗号起头」只堵一条路径、**形状未变**（靠 CPython `REPEAT_ONE`），下轮分析复现；终版 = 单一字符集重复 `r"\[CQ:([^\[\]]+)\]"` + `_cq_parts` 切分，等价性由「期望结果表」锁住 |
| 7 | `py/clear-text-logging-sensitive-data` | 1 | **真漏洞**（修两次） | 验收脚本把 `DEEPSEEK_API_KEY` 打进 CI 日志。首版 `_masked_key()` 只回显长度 + 前 3 位，但 CodeQL 不认自定义脱敏函数（返回值仍是密钥派生串），下轮复现；终版**从源头切断**：日志实参只由比较得到的布尔结论挑常量文案，函数删除 |

## 三、回归测试（6 文件 / 26 条，零依赖）

| 文件 | 条 | 覆盖 |
| :--- | ---: | :--- |
| `tests/test_plugin_path_injection.py` | 5 | id 正则语义（AST 取真实正则）、越界全拒、合法放行、校验先于拼路径、内联净化 |
| `tests/test_no_open_redirect.py` | 2 | 站内重定向前缀不变量、无「整串来自变量」重定向 |
| `tests/test_installer_ssrf_proof.py` | 4 | SSRF 三层防线顺序、13 类载荷全拒、正常放行 |
| `tests/test_code_scanning_redos.py` | 8 | 形状不变量（仅一个量词 / 无分组量词）、4 类病态输入 < 1s、期望结果表、畸形输入行为固定、仓库级「量词套量词」闸门、禁 `mktemp` |
| `tests/test_no_secret_in_logs.py` | 3 | 日志实参无敏感派生表达式、敏感源不进字符串格式化、脱敏函数不存在 |
| `tests/test_webui_assets.py`（追加） | 4 | 静态资源 sink 层文件名白名单 |

## 四、如实声明

1. **未做真机/运行时渗透验证**：判定基于代码路径与单元/结构性测试，不是黑盒攻击验证。
2. **复跑已完成**：56 → 52 → 51 → 50，六条真漏洞全部关闭 —— 其中 `redos` 与 `clear-text-logging`
   曾在下一轮分析里**复现**（首轮修法不彻底），重修后才真正关闭。剩余 50 条 = 18 条误报（已 dismissed）
   + 32 条「暂时无法证明」（保持 open，不伪装成误报）。
3. **两项残余风险**：installer 的 DNS TOCTOU 窗口；CodeQL 局部数据流不识别跨函数自定义校验。
4. **一条教训**：判「误报」要区分**引擎优化带来的安全**与**形状可证的安全**，前者不能当证据。
