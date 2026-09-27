# Phase 0 机械扫描（自动生成：import 图 / 重复 / 并发放 / 性能模式）

## A. 模块 import 图与循环依赖（**已修正**）

**模块级 import 图无环（96 个模块 / 0 组循环依赖）** —— 详见 `imports.md`。

先前本文件报出的 `src.adapters.{resource, milky_resource_fetcher, onebot/resource_fetcher}` 一组"环"，
经复核是**函数内延迟 import** 造成的假阳性：`src/adapters/resource.py:330-331` 在 `build_resource_fetcher()`
函数体内 import 两个协议 fetcher（代码注释写明"函数内的 import 是刻意的：避免形成循环导入"），
而两个 fetcher 在模块级 import `src.adapters.resource`。

→ 结论：**不是循环依赖，但是架构气味**（基类/组合根模块反向引用具体实现）。Phase 2 可考虑把工厂搬到
`src/adapters/resource_factory.py` 之类的中立模块，消除这个"刻意延迟导入"。

全仓函数内延迟 import 共 **47 处**（含 main.py 的按需导入、postgres 后端按需导入、milky/onebot 解析器
按需导入等合理用法），完整清单见 `imports.md`。

## B. 完全同形的重复函数体（归一化后 >=160 字符）
- 2 处: src/services/webui_panels/plugin_panel.py:233 _handle_panel_plugins_disable | src/services/webui_panels/plugin_panel.py:242 _handle_panel_plugins_uninstall
- 2 处: src/transport/transports.py:270 _record_error | src/transport/transports.py:406 _record_error
（近似重复需人工判断，见子代理报告）

## C. HTTP client 新建点（16 处）
- src/plugins/http_action.py:98 AsyncClient(...)  [在 async 函数内=True]
- src/plugins/installer.py:161 AsyncClient(...)  [在 async 函数内=True]
- src/plugins/manager.py:1763 AsyncClient(...)  [在 async 函数内=True]
- src/plugins/manager.py:1781 AsyncClient(...)  [在 async 函数内=True]
- src/plugins/manager.py:2586 AsyncClient(...)  [在 async 函数内=True]
- src/services/ai_client.py:26 AsyncClient(...)  [在 async 函数内=True]
- src/services/blossom_memory.py:57 AsyncClient(...)  [在 async 函数内=False]
- src/services/blossom_memory.py:89 AsyncClient(...)  [在 async 函数内=False]
- src/services/file_parser.py:40 AsyncClient(...)  [在 async 函数内=False]
- src/services/mcp_client.py:55 AsyncClient(...)  [在 async 函数内=False]
- src/services/sender.py:32 ClientSession(...)  [在 async 函数内=True]
- src/services/webui_panels/config_panel.py:54 AsyncClient(...)  [在 async 函数内=True]
- src/services/webui_panels/config_panel.py:74 AsyncClient(...)  [在 async 函数内=True]
- src/services/webui_panels/config_panel.py:93 AsyncClient(...)  [在 async 函数内=True]
- src/services/webui_panels/mcp_panel.py:82 ClientSession(...)  [在 async 函数内=True]
- src/transport/transports.py:458 ClientSession(...)  [在 async 函数内=True]

## D. 裸 asyncio.create_task（未保存引用，2 处）
- src/plugins/runtime.py:406  asyncio.create_task(self._handle_action_line_sem(msg))
- src/plugins/runtime.py:411  asyncio.create_task(self._handle_engine_op_sem(msg))

## E. async 函数内的同步阻塞调用（精确匹配：time.sleep / requests / urllib / subprocess / socket / open，8 处）
- src/adapters/resource.py:223 in fetch(): open()
- src/plugins/manager.py:1520 in _ext_data(): open()
- src/plugins/manager.py:1552 in _ext_data(): open()
- src/plugins/manager.py:1566 in _ext_data(): open()
- src/plugins/manager.py:1963 in _ext_social(): open()
- src/plugins/manager.py:2606 in _http_ext(): open()
- src/services/sticker_manager.py:76 in _index_file(): open()
- src/services/vision.py:221 in describe_image_file(): open()

## F. 实例级容器（45 处，需确认是否有上限/TTL/清理）
- src/adapters/instance.py:93 self._instances
- src/adapters/resource.py:292 self._by_kind
- src/core/policy_engine.py:33 self.groups
- src/models.py:35 self.repeat_cache
- src/models.py:36 self.msg_timestamps
- src/plugins/manager.py:72 self._plugin_services
- src/plugins/manager.py:77 self._runtimes
- src/plugins/manager.py:78 self._manifest_cache
- src/plugins/manager.py:81 self._sent_message_ids
- src/plugins/manager.py:84 self._matchers
- src/plugins/manager.py:89 self._schedules
- src/plugins/manager.py:94 self._schedule_tasks
- src/plugins/router.py:98 self._instances
- src/plugins/router.py:207 self._inflight
- src/plugins/runner/python_runner.py:924 self._handlers
- src/plugins/runner/python_runner.py:926 self._event_handlers
- src/plugins/runner/python_runner.py:928 self._inbound
- src/plugins/runtime.py:66 self._pending
- src/plugins/webui_security.py:116 self.out
- src/plugins/webui_security.py:117 self.report
- src/plugins/webui_security.py:119 self._open
- src/repositories/meme_knowledge_repository.py:172 self._lock
- src/sdk/listener.py:31 self._listeners
- src/sdk/message.py:26 self._extra
- src/services/blossom_memory.py:173 self._daily_extracted
- src/services/group_nicknames.py:40 self._data
- src/services/group_style_rules.py:24 self._data
- src/services/mcp_tool_manager.py:81 self.schemas
- src/services/mcp_tool_manager.py:92 self._tool_owner
- src/services/mcp_tool_manager.py:160 self._tool_owner
- src/services/meme_knowledge_manager.py:50 self._buffers
- src/services/meme_knowledge_manager.py:51 self._buffer_activity
- src/services/meme_summary.py:75 self._retry_count
- src/services/web_ui.py:84 self._tokens
- src/services/web_ui.py:85 self._login_fails
- src/transport/transports.py:99 self._pending
- src/transport/ws_server.py:36 self._pending
- src/utils/expiring_map.py:33 self._data
- src/utils/metrics.py:22 self._values
- src/utils/metrics.py:50 self._counts
- src/utils/metrics.py:51 self._sums
- src/utils/metrics.py:82 self._counters
- src/utils/metrics.py:83 self._histograms
- src/utils/metrics.py:103 self._lock
- src/utils/task_manager.py:24 self._tasks
