# 重构保护网：模块 ↔ 测试映射（自动生成）

用途：拆某个模块前，先跑它对应的测试文件；同时在表 2 里看**测试是否直接触碰了私有成员**（拆分风险点）。

## 表 1：模块 → 引用它的测试

| 源码模块 | 测试文件数 | 测试文件（前 4，完整清单见 json 同源数据） |
| :--- | ---: | :--- |
| `src/repositories/settings_repository.py` | 20 | `acceptance_check.py`, `_serve.py`, `harness.py`, `test_config_persistence.py` |
| `src/plugins/manager.py` | 18 | `_serve.py`, `harness.py`, `test_api_gap_messages.py`, `test_api_gap_whitebox.py` |
| `src/adapters/milky_parser.py` | 18 | `test_milky_real.py`, `test_client_contract_matrix.py`, `test_cross_protocol_equivalence.py`, `test_fixtures_corpus.py` |
| `src/adapters/onebot_parser.py` | 18 | `test_onebot11_real.py`, `test_adapter_segment_normalization.py`, `test_client_contract_matrix.py`, `test_cross_protocol_equivalence.py` |
| `src/services/config_service.py` | 14 | `acceptance_check.py`, `_serve.py`, `test_config_blossom_off_chain.py`, `test_config_persistence.py` |
| `src/plugins/manifest.py` | 11 | `test_api_gap_blackbox.py`, `test_plugin_comm_bus.py`, `test_plugin_comm_paths.py`, `test_plugin_manifest.py` |
| `src/core/sanitizer.py` | 10 | `test_blossom_memory.py`, `test_installer_ssrf_proof.py`, `test_mcp_multi.py`, `test_mcp_security.py` |
| `src/services/memory_manager.py` | 10 | `test_bounded_state.py`, `test_cancellation.py`, `test_concurrency.py`, `test_memory_gate.py` |
| `src/services/web_ui.py` | 9 | `acceptance_check.py`, `_serve.py`, `test_web_password.py`, `test_web_ui.py` |
| `src/services/ai_client.py` | 9 | `test_ai_client.py`, `test_ai_reliability.py`, `test_mcp.py`, `test_mcp_quota.py` |
| `src/config.py` | 8 | `acceptance_check.py`, `_serve.py`, `test_config_service_full.py`, `test_config_validation.py` |
| `src/core/message_assembler.py` | 8 | `test_face_context.py`, `test_image_source_compat.py`, `test_media_segments.py`, `test_multimsg_card.py` |
| `src/repositories/meme_knowledge_repository.py` | 6 | `acceptance_check.py`, `test_meme_knowledge.py`, `test_meme_summary.py`, `test_persona_manager.py` |
| `src/repositories/base.py` | 6 | `test_concurrency.py`, `test_memory_gate.py`, `test_postgres_backend.py`, `test_prompt_injection_memory.py` |
| `src/models.py` | 6 | `test_concurrency.py`, `test_context_manager.py`, `test_cooldown_manager.py`, `test_meme_summary.py` |
| `src/core/reply_plan.py` | 6 | `test_milky_end_to_end.py`, `test_multi_reply_core.py`, `test_multi_reply_dispatch.py`, `test_multi_reply_e2e.py` |
| `src/services/persona_manager.py` | 5 | `acceptance_check.py`, `test_persona_isla.py`, `test_persona_manager.py`, `test_persona_seed_sync.py` |
| `src/services/meme_knowledge_manager.py` | 5 | `acceptance_check.py`, `test_meme_knowledge.py`, `test_meme_summary.py`, `test_persona_manager.py` |
| `src/repositories/env_store.py` | 5 | `acceptance_check.py`, `test_config_service_full.py`, `test_env_store.py`, `test_web_ui_panel.py` |
| `src/plugins/runtime.py` | 5 | `test_api_gap_blackbox.py`, `test_plugin_comm_bus.py`, `test_plugin_comm_paths.py`, `test_plugin_multilang.py` |
| `src/repositories/sqlite_repository.py` | 5 | `test_cancellation.py`, `test_concurrency.py`, `test_persona_manager.py`, `test_repository.py` |
| `src/core/message_router.py` | 5 | `test_meme_summary.py`, `test_name_mention_reply.py`, `test_persona_manager.py`, `test_resource_model.py` |
| `src/core/policy_engine.py` | 4 | `test_bounded_state.py`, `test_meme_summary.py`, `test_persona_manager.py`, `test_router_regression.py` |
| `src/adapters/onebot12_parser.py` | 4 | `test_client_contract_matrix.py`, `test_fixtures_corpus.py`, `test_onebot12_adapter.py`, `test_protocol_roundtrip.py` |
| `src/services/mcp_tool_manager.py` | 4 | `test_mcp.py`, `test_mcp_multi.py`, `test_mcp_security.py`, `test_prompt_injection_regression.py` |
| `src/services/mcp_client.py` | 4 | `test_mcp.py`, `test_mcp_multi.py`, `test_mcp_security.py`, `test_mcp_ssrf_dns.py` |
| `src/core/reply_dispatch.py` | 4 | `test_milky_end_to_end.py`, `test_multi_reply_dispatch.py`, `test_multi_reply_e2e.py`, `test_native_reply_tool.py` |
| `src/sdk/event.py` | 4 | `test_multi_reply_sdk.py`, `test_sdk_listener.py`, `test_sdk_matcher.py`, `test_sdk_permissions.py` |
| `src/plugins/permissions.py` | 4 | `test_plugin_comm_bus.py`, `test_plugin_comm_model.py`, `test_plugin_permissions.py`, `test_plugin_webui_consistency.py` |
| `src/adapters/onebot/adapter.py` | 4 | `test_plugin_manager.py`, `test_sdk_adapter.py`, `test_sdk_capabilities.py`, `test_sdk_lagrange.py` |
| `src/adapters/resource.py` | 3 | `test_milky_real.py`, `test_onebot11_real.py`, `test_resource_model.py` |
| `src/adapters/container.py` | 3 | `test_adapter_contract.py`, `test_bootstrap.py`, `test_milky_protocol_selection.py` |
| `src/adapters/capabilities.py` | 3 | `test_adapter_contract.py`, `test_capability_model.py`, `test_pec_experiment.py` |
| `src/adapters/__init__.py` | 3 | `test_adapters.py`, `test_bootstrap.py`, `test_router_migration.py` |
| `src/repositories/blossom_memory_repository.py` | 3 | `test_blossom_memory.py`, `test_postgres_backend.py`, `test_repos_create_dirs.py` |
| `src/adapters/onebot/transformer.py` | 3 | `test_bootstrap.py`, `test_code_scanning_redos.py`, `test_sdk_message.py` |
| `src/utils/expiring_map.py` | 3 | `test_bounded_state.py`, `test_circuit_breaker_isolation.py`, `test_sticker_manager.py` |
| `src/adapters/client_profile.py` | 3 | `test_client_contract_matrix.py`, `test_milky_serializer.py`, `test_onebot_serializer.py` |
| `src/services/group_nicknames.py` | 3 | `test_group_nicknames.py`, `test_group_nicknames_persona.py`, `test_web_ui_nicknames.py` |
| `src/utils/metrics.py` | 3 | `test_logging_trace.py`, `test_metrics_cardinality.py`, `test_metrics_format.py` |
| `src/core/memory_parser.py` | 3 | `test_memory_parser.py`, `test_prompt_injection_memory.py`, `test_prompt_injection_regression.py` |
| `src/services/persona_presets.py` | 3 | `test_persona_isla.py`, `test_persona_manager.py`, `test_persona_seed_sync.py` |
| `src/plugins/__init__.py` | 3 | `test_plugin_comm_bus.py`, `test_plugin_comm_model.py`, `test_plugin_comm_paths.py` |
| `src/transport/action_channels.py` | 2 | `test_milky_real.py`, `test_onebot11_real.py` |
| `src/adapters/proto.py` | 2 | `test_adapter_contract.py`, `test_bootstrap.py` |
| `src/adapters/onebot_serializer.py` | 2 | `test_client_contract_matrix.py`, `test_onebot_serializer.py` |
| `src/transport/onebot_response.py` | 2 | `test_client_contract_matrix.py`, `test_onebot_response_contract.py` |
| `src/core/cooldown_manager.py` | 2 | `test_concurrency.py`, `test_cooldown_manager.py` |
| `src/core/context_manager.py` | 2 | `test_context_manager.py`, `test_proactive_probability.py` |
| `src/adapters/testkit/__init__.py` | 2 | `test_cross_protocol_equivalence.py`, `test_pec_experiment.py` |
| `src/services/config_schema.py` | 2 | `test_env_template.py`, `test_multi_reply_protocol.py` |
| `src/utils/task_manager.py` | 2 | `test_graceful_shutdown.py`, `test_task_manager.py` |
| `src/services/prompt_builder.py` | 2 | `test_group_style_rules.py`, `test_prompt_builder_nickname.py` |
| `src/utils/trace.py` | 2 | `test_logging_trace.py`, `test_plugin_comm_model.py` |
| `src/core/budget_manager.py` | 2 | `test_meme_summary.py`, `test_router_regression.py` |
| `src/services/sender.py` | 2 | `test_milky_end_to_end.py`, `test_ws_send_channel.py` |
| `src/plugins/protocol.py` | 2 | `test_plugin_comm_model.py`, `test_plugin_protocol.py` |
| `src/plugins/runner/python_runner.py` | 2 | `test_plugin_data_dir.py`, `test_sdk_lagrange.py` |
| `src/services/webui_render/plugin_dsl.py` | 2 | `test_plugin_dsl.py`, `test_plugin_webui_integration.py` |
| `src/plugins/webui_loader.py` | 2 | `test_plugin_webui_html.py`, `test_plugin_webui_protocol.py` |
| `src/plugins/webui_security.py` | 2 | `test_plugin_webui_html.py`, `test_plugin_webui_protocol.py` |
| `src/services/prompt_manager.py` | 2 | `test_prompt_manager.py`, `test_web_ui_persona_knowledge.py` |
| `src/adapters/compat.py` | 2 | `test_protocol_roundtrip.py`, `test_router_migration.py` |
| `src/repositories/sticker_repository.py` | 2 | `test_repos_create_dirs.py`, `test_sticker_manager.py` |
| `src/sdk/message.py` | 2 | `test_sdk_adapter.py`, `test_sdk_message.py` |
| `src/services/webui_render/theme.py` | 2 | `test_web_ui_panel.py`, `test_webui_assets.py` |
| `src/services/webui_render/pages.py` | 2 | `test_web_ui_persona_knowledge.py`, `test_webui_assets.py` |
| `src/transport/ws_server.py` | 2 | `test_ws_lifecycle.py`, `test_ws_send_channel.py` |
| `src/adapters/contract.py` | 1 | `test_adapter_contract.py` |
| `src/utils/banner.py` | 1 | `test_banner.py` |
| `src/services/blossom_memory.py` | 1 | `test_blossom_memory.py` |
| `src/utils/circuit_breaker.py` | 1 | `test_circuit_breaker_isolation.py` |
| `src/services/env_template.py` | 1 | `test_env_template.py` |
| `src/services/webui_panels/nickname_panel.py` | 1 | `test_group_nicknames_persona.py` |
| `src/services/group_style_rules.py` | 1 | `test_group_style_rules.py` |
| `src/utils/logging_setup.py` | 1 | `test_logging_trace.py` |
| `src/services/webui_render/markdown_mini.py` | 1 | `test_markdown_mini.py` |
| `src/services/meme_summary.py` | 1 | `test_meme_summary.py` |
| `src/adapters/milky_serializer.py` | 1 | `test_milky_serializer.py` |
| `src/transport/milky_response.py` | 1 | `test_milky_serializer.py` |
| `src/adapters/instance.py` | 1 | `test_multi_instance.py` |
| `src/core/reply_sender.py` | 1 | `test_multi_reply_core.py` |
| `src/sdk/bot.py` | 1 | `test_multi_reply_sdk.py` |
| `src/transport/ws_forward_client.py` | 1 | `test_napcat_ws_forward.py` |
| `src/services/reply_tool.py` | 1 | `test_native_reply_tool.py` |
| `src/core/ai_gateway.py` | 1 | `test_native_reply_tool.py` |
| `src/adapters/outgoing.py` | 1 | `test_outgoing_routing.py` |
| `src/plugins/comm.py` | 1 | `test_plugin_comm_model.py` |
| `src/plugins/installer.py` | 1 | `test_plugin_installer.py` |
| `src/repositories/postgres_blossom_repository.py` | 1 | `test_postgres_backend.py` |
| `src/repositories/postgres_memory_repository.py` | 1 | `test_postgres_backend.py` |
| `src/core/active_chat_manager.py` | 1 | `test_proactive_probability.py` |
| `src/core/command_handler.py` | 1 | `test_prompt_manager.py` |
| `src/core/repeat_detector.py` | 1 | `test_repeat_detector.py` |
| `src/services/file_parser.py` | 1 | `test_resource_model.py` |
| `src/adapters/milky_resource_fetcher.py` | 1 | `test_resource_model.py` |
| `src/adapters/onebot/resource_fetcher.py` | 1 | `test_resource_model.py` |
| `src/sdk/errors.py` | 1 | `test_sdk_adapter.py` |
| `src/sdk/listener.py` | 1 | `test_sdk_listener.py` |
| `src/sdk/matcher.py` | 1 | `test_sdk_matcher.py` |
| `src/sdk/permissions.py` | 1 | `test_sdk_permissions.py` |
| `src/services/sticker_manager.py` | 1 | `test_sticker_manager.py` |
| `src/services/storage_migrate.py` | 1 | `test_storage_backend.py` |
| `src/transport/__init__.py` | 1 | `test_transport_contract.py` |
| `src/services/vision.py` | 1 | `test_vision_redirect.py` |
| `src/services/webui_render/nicknames.py` | 1 | `test_web_ui_nicknames.py` |
| `src/services/web_ui_assets.py` | 1 | `test_web_ui_persona_knowledge.py` |
| `src/services/webui_render/assets.py` | 1 | `test_webui_assets.py` |
| `src/services/webui_render/config_panel.py` | 1 | `test_webui_blossom.py` |

## 表 2：测试直接触碰的私有成员（按对象名前缀可靠归因）

| 源码模块 | 触碰次数 Top | 真实例子 |
| :--- | :--- | :--- |
| `src/plugins/manager.py` | `_handle_action`×30, `_runtimes`×16, `_servers`×8, `_execute_action`×8, `_manifest_of`×7, `_comm_bus`×7, `_handle_engine_op`×7, `_matchers`×7 | tests/test_api_gap_messages.py:61 mgr._run_action; tests/test_api_gap_messages.py:275 mgr._manifest_of; tests/test_api_gap_messages.py:297 mgr._runtimes |
| `src/plugins/runtime.py` | `_limits`×8, `_on_exit`×1, `_cleanup`×1, `_build_command`×1 | tests/test_api_gap_blackbox.py:80 rt._limits; tests/test_api_gap_blackbox.py:81 rt._limits; tests/test_api_gap_blackbox.py:110 rt._limits |
| `src/services/config_service.py` | `_download_image`×3, `_running`×1 | tests/test_meme_summary.py:274 svc._running; tests/test_vision_redirect.py:39 svc._download_image; tests/test_vision_redirect.py:55 svc._download_image |

## 表 3：没有任何测试直接 import 的 src 模块（39 个）

- `main.py`
- `src/__init__.py`
- `src/adapters/onebot/dto.py`
- `src/adapters/testkit/test_protocol.py`
- `src/core/ai_guard_mixin.py`
- `src/core/name_mention.py`
- `src/core/poke_manager.py`
- `src/plugins/http_action.py`
- `src/plugins/router.py`
- `src/repositories/__init__.py`
- `src/sdk/__init__.py`
- `src/sdk/adapter.py`
- `src/services/system_status.py`
- `src/services/toxic_detector.py`
- `src/services/webui_panels/__init__.py`
- `src/services/webui_panels/account_panel.py`
- `src/services/webui_panels/appearance_panel.py`
- `src/services/webui_panels/auth_panel.py`
- `src/services/webui_panels/config_panel.py`
- `src/services/webui_panels/knowledge_panel.py`
- `src/services/webui_panels/mcp_panel.py`
- `src/services/webui_panels/persona_panel.py`
- `src/services/webui_panels/plugin_panel.py`
- `src/services/webui_panels/plugin_webui_static.py`
- `src/services/webui_panels/prompt_panel.py`
- `src/services/webui_render/__init__.py`
- `src/services/webui_render/account.py`
- `src/services/webui_render/appearance.py`
- `src/services/webui_render/category_constants.py`
- `src/services/webui_render/knowledge.py`
- `src/services/webui_render/persona.py`
- `src/services/webui_render/plugin_webui.py`
- `src/services/webui_render/plugins.py`
- `src/services/webui_render/util.py`
- `src/services/webui_static.py`
- `src/transport/contract.py`
- `src/transport/milky_ws_client.py`
- `src/transport/transports.py`
- `src/utils/logger.py`

> 未直接 import ≠ 未覆盖：可能被间接覆盖或由集成测试走。判死代码前必须查引用（见子代理 D 的报告）。
