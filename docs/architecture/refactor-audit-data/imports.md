# 循环依赖与延迟导入（只统计模块级 import）

模块级 import 图：96 个模块，循环依赖组 = **0**

- 模块级 import 图**无环**；src/adapters/resource.py 与两个协议 fetcher 之间的环是靠**函数内延迟 import** 规避的（见下），属架构气味而非硬违规

## 函数内延迟 import（47 处）

- `main.py:101 in main() -> src.services.blossom_memory`
- `main.py:123 in main() -> src.adapters.outgoing`
- `main.py:165 in main() -> src.plugins.manager`
- `main.py:188 in main() -> src.services.group_nicknames`
- `main.py:189 in main() -> src.services.group_style_rules`
- `main.py:217 in main() -> src.core.budget_manager`
- `main.py:243 in main() -> src.transport.milky_ws_client`
- `main.py:247 in main() -> src.transport.ws_forward_client`
- `main.py:44 in _default_env_text() -> src.config`
- `main.py:45 in _default_env_text() -> src.services.env_template`
- `main.py:69 in main() -> src.utils.banner`
- `main.py:91 in main() -> src.repositories.postgres_memory_repository`
- `src/adapters/compat.py:47 in convert_legacy() -> src.adapters.onebot_parser`
- `src/adapters/container.py:54 in make_parser() -> src.adapters.milky_parser`
- `src/adapters/container.py:57 in make_parser() -> src.adapters.onebot_parser`
- `src/adapters/contract.py:171 in testproto_under_test() -> src.adapters.testkit.test_protocol`
- `src/adapters/instance.py:157 in make_instance() -> src.transport.action_channels`
- `src/adapters/outgoing.py:71 in prepare_outgoing() -> src.adapters.milky_serializer`
- `src/adapters/outgoing.py:74 in prepare_outgoing() -> src.adapters.onebot_serializer`
- `src/adapters/resource.py:330 in build_resource_fetcher() -> src.adapters.milky_resource_fetcher`
- `src/adapters/resource.py:331 in build_resource_fetcher() -> src.adapters.onebot.resource_fetcher`
- `src/core/message_router.py:205 in _plugin_payload() -> src.utils.trace`
- `src/plugins/comm.py:354 in new_trace_id() -> src.utils.trace`
- `src/plugins/manager.py:1269 in _handle_engine_op() -> src.plugins.protocol`
- `src/plugins/manager.py:1297 in _handle_engine_op() -> src.plugins.permissions`
- `src/plugins/manager.py:1546 in _ext_data() -> src.utils.metrics`
- `src/plugins/manager.py:1826 in _ext_ai() -> src.utils.metrics`
- `src/plugins/manager.py:1855 in _ext_ai() -> src.services.blossom_memory`
- `src/plugins/manager.py:1873 in _ext_ai() -> src.services.blossom_memory`
- `src/plugins/manager.py:2106 in _action_send_many() -> src.core.reply_plan`
- `src/plugins/manager.py:2107 in _action_send_many() -> src.core.reply_sender`
- `src/plugins/manager.py:2562 in _http_ext() -> src.plugins.http_action`
- `src/plugins/manager.py:2577 in _http_ext() -> src.plugins.http_action`
- `src/plugins/manager.py:2751 in _rule_from() -> src.sdk.matcher`
- `src/plugins/manager.py:401 in plugin_webui_render() -> src.plugins.webui_security`
- `src/plugins/manager.py:436 in plugin_webui_static_file() -> src.plugins.webui_security`
- `src/plugins/manager.py:471 in _webui_granted() -> src.plugins.permissions`
- `src/plugins/manager.py:599 in plugin_webui_asset() -> src.plugins.webui_loader`
- `src/plugins/manager.py:637 in plugin_webui_asset() -> src.plugins.webui_security`
- `src/services/env_template.py:111 in default_env_text() -> src.services.config_schema`
- `src/services/env_template.py:112 in default_env_text() -> src.services.webui_render.category_constants`
- `src/services/web_ui.py:257 in _handle_doc_quickstart() -> src.services.webui_render.markdown_mini`
- `src/services/webui_panels/config_panel.py:104 in _ping_embedding() -> src.services.blossom_memory`
- `src/services/webui_panels/config_panel.py:121 in _ping_reranker() -> src.services.blossom_memory`
- `src/services/webui_panels/plugin_panel.py:151 in _handle_panel_plugin_webui() -> src.services.webui_render.plugin_dsl`
- `src/services/webui_panels/plugin_panel.py:161 in _handle_panel_plugin_webui() -> src.services.webui_render.plugin_webui`
- `src/services/webui_render/plugin_dsl.py:98 in _markdown() -> src.services.webui_render.markdown_mini`
