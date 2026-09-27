# Phase 0 性能热点与并发放（只读分析；Phase 4 的输入，需 benchmark 才能声称提升）

## 1. HTTP client 生命周期（16 个新建点，逐个判定）

| 位置 | 所属函数 | 生命周期 / 频率 | 判定 |
| :--- | :--- | :--- | :--- |
| src/services/sender.py:32 | Sender.__aenter__ | 每个 Sender 实例一个 aiohttp.ClientSession | ✅ 合理（长生命周期） |
| src/services/ai_client.py:26 | AIClient.__aenter__ | 每个 AIClient 一个 httpx.AsyncClient | ✅ 合理（长生命周期） |
| src/services/file_parser.py:40 / mcp_client.py:55 / blossom_memory.py:57,89 | 构造期 | 实例级 | ✅ 合理 |
| src/services/webui_panels/config_panel.py:54,74,93 | _ping_chat/_ping_vision/_ping_toxic | 每次点面板「测试」按钮新建 | ✅ 可接受（人工低频） |
| src/services/webui_panels/mcp_panel.py:82 | _mcp_ping | 每次面板 ping 新建 aiohttp session | ✅ 可接受（人工低频） |
| src/plugins/installer.py:161 | PluginInstaller.install_from_url | 每次安装新建 | ✅ 可接受（低频 + 有 SSRF 防线要独立配置） |
| src/plugins/manager.py:2586 | PluginManager._http_ext（下载） | 每次下载新建 | ⚠️ 中频；下载本身耗时长，收益有限 |
| src/plugins/manager.py:1763,1781 | PluginManager._ext_mcp（mcp_status / mcp_call） | **每次 MCP 工具调用新建 AsyncClient** | ⚠️ **Phase 4 候选**：连接池无法复用，插件高频调用时握手开销重复 |
| src/plugins/http_action.py:98 | 插件 http_request 动作 | **每次插件 HTTP 动作新建 AsyncClient** | ⚠️ **Phase 4 候选**：同上，且插件可能循环调用 |
| src/transport/transports.py:458 | ClientSession (未接线模块) | — | 见死代码清单 |

结论：核心链路（Sender / AIClient）的连接池生命周期**已经是合理的**；只有插件侧的 `http_request` / `mcp_call` 是「每次新建」。
Phase 4 若要改，必须保持现有超时/取消/SSRF 语义，并给出 before/after 的连接复用证据（例如同一进程内多次调用的握手次数）。

## 2. async 函数内的同步 IO（8 处，逐个判定）

| 位置 | 内容 | 数据量 | 判定 |
| :--- | :--- | :--- | :--- |
| src/adapters/resource.py:223 | `open(path,'rb').read(max_bytes)` 读协议侧资源 | 可为 MB 级图片/文件 | ⚠️ 真阻塞候选 |
| src/services/sticker_manager.py:76 | `f.read()` 整个表情包文件（索引期循环调用） | MB 级 × N | ⚠️ 真阻塞候选 |
| src/services/vision.py:221 | `f.read()` 整张图片 + base64 | MB 级 | ⚠️ 真阻塞候选 |
| src/plugins/manager.py:1566 | `f.readlines()[-50:]` 读日志文件 | **整文件读入再切片** | ⚠️ 真问题：既阻塞又浪费内存（应改 deque(maxlen=50) 或尾部 seek） |
| src/plugins/manager.py:2606 | `open(target,'wb').write(data)` 落盘下载内容 | MB 级 | ⚠️ 写盘阻塞候选 |
| src/plugins/manager.py:1520,1552 | 读 /proc/<pid>/status、/proc/self/status | 几 KB，只读匹配行 | ✅ 可接受 |
| src/plugins/manager.py:1963 | 读图片头 32 字节（魔数校验） | 32 B | ✅ 可接受 |

## 3. 并发放（已确认的真实问题，Phase 1 修复项）

| 位置 | 问题 | 证据 |
| :--- | :--- | :--- |
| src/plugins/runtime.py:406 | 裸 `asyncio.create_task(self._handle_action_line_sem(msg))`：**任务引用未保存** | 无强引用的 Task 可能被 GC 中途取消；异常也无处取（Task exception was never retrieved） |
| src/plugins/runtime.py:411 | 同上（`_handle_engine_op_sem`） | 同上 |
| src/plugins/runtime.py:_cleanup（~:182） | 只 cancel `_pending` futures 与 reader/stderr 任务，**不追踪上面两个 action 任务** | 插件 stop/shutdown 时这两个任务可能仍在跑 |

→ Phase 1 修法：用 `self._inflight: set[Task]` 保存引用 + done 回调 discard，`_cleanup()`/`shutdown()` 里 cancel + await（与上一轮修的 manager 侧 `_drain_shutdown_tasks` 同一模式）。

## 4. 重复逻辑（完全同形 2 组 + 待人工确认）

- src/services/webui_panels/plugin_panel.py:233 / :242（`_handle_panel_plugins_disable` / `_uninstall`）
- src/transport/transports.py:270 / :406（`_record_error`，该模块本身未接线）
- 近似重复（时间格式化 / 文本截断 / 路径净化 / 重试装饰器）由子代理报告补充。

