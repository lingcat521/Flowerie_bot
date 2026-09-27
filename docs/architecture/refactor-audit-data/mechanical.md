# Phase 0 机械审计数据（自动生成；证据 = 文件:行）

## 1. God Class 候选（按 方法数 × √跨度 排序，Top 25）

| 类 | 位置 | 类跨度(行) | 方法 | 公共 | 实例属性 | self 私有调用 |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| `PluginApi` | `src/plugins/runner/python_runner.py:195` | 712 | 169 | 168 | 4 | 2 |
| `PluginManager` | `src/plugins/manager.py:59` | 2630 | 81 | 26 | 23 | 85 |
| `Sender` | `src/services/sender.py:15` | 498 | 61 | 54 | 6 | 7 |
| `PluginRunner` | `src/plugins/runner/python_runner.py:908` | 647 | 42 | 8 | 11 | 38 |
| `SettingsRepository` | `src/repositories/settings_repository.py:20` | 393 | 38 | 35 | 2 | 4 |
| `ConfigService` | `src/services/config_service.py:80` | 619 | 25 | 11 | 3 | 15 |
| `OneBotAdapter` | `src/adapters/onebot/adapter.py:20` | 199 | 43 | 40 | 3 | 5 |
| `PluginRuntime` | `src/plugins/runtime.py:48` | 449 | 28 | 13 | 23 | 26 |
| `MessageRouter` | `src/core/message_router.py:44` | 600 | 19 | 4 | 25 | 16 |
| `WebUIServer` | `src/services/web_ui.py:71` | 330 | 17 | 4 | 15 | 67 |
| `MemeKnowledgeRepository` | `src/repositories/meme_knowledge_repository.py:20` | 239 | 19 | 15 | 2 | 5 |
| `MemoryManager` | `src/services/memory_manager.py:40` | 317 | 16 | 10 | 7 | 5 |
| `AIClient` | `src/services/ai_client.py:16` | 397 | 14 | 8 | 7 | 3 |
| `PersonaManager` | `src/services/persona_manager.py:36` | 237 | 18 | 14 | 6 | 4 |
| `MemeKnowledgeManager` | `src/services/meme_knowledge_manager.py:36` | 256 | 16 | 14 | 8 | 3 |
| `MessageAssembler` | `src/core/message_assembler.py:17` | 372 | 13 | 1 | 5 | 11 |
| `Bot` | `src/sdk/bot.py:15` | 131 | 21 | 19 | 3 | 4 |
| `ContextManager` | `src/core/context_manager.py:16` | 292 | 14 | 8 | 3 | 5 |
| `MessageSender` | `src/adapters/proto.py:106` | 44 | 35 | 35 | 0 | 0 |
| `PostgresMemoryRepository` | `src/repositories/postgres_memory_repository.py:14` | 160 | 17 | 13 | 2 | 4 |
| `PolicyEngine` | `src/core/policy_engine.py:17` | 115 | 20 | 19 | 10 | 0 |
| `PluginPanelMixin` | `src/services/webui_panels/plugin_panel.py:19` | 253 | 13 | 0 | 0 | 3 |
| `FileParser` | `src/services/file_parser.py:32` | 382 | 10 | 7 | 2 | 3 |
| `PluginBus` | `src/plugins/router.py:198` | 260 | 12 | 4 | 3 | 9 |
| `BotMessage` | `src/sdk/message.py:10` | 128 | 17 | 13 | 9 | 1 |

## 2. 超长 / 高分支函数（按 行数 + 2×分支 排序，Top 25）

| 函数 | 位置 | 行数 | 分支 | 参数 |
| :--- | :--- | ---: | ---: | ---: |
| `_run_action` | `src/plugins/manager.py:2152` | 330 | 105 | 3 |
| `render_persona_tab` | `src/services/webui_render/persona.py:7` | 297 | 10 | 16 |
| `serialize_segments` | `src/adapters/onebot_serializer.py:45` | 205 | 52 | 1 |
| `_handle_message` | `src/core/message_router.py:237` | 229 | 37 | 1 |
| `main` | `main.py:64` | 236 | 16 | 0 |
| `guarded_chat` | `src/core/ai_gateway.py:94` | 205 | 29 | 2 |
| `validate_config` | `src/config.py:454` | 152 | 55 | 1 |
| `_ext_data` | `src/plugins/manager.py:1444` | 144 | 42 | 3 |
| `_fill_message` | `src/adapters/onebot_parser.py:256` | 156 | 31 | 2 |
| `extract_forward_messages` | `src/services/file_parser.py:228` | 122 | 31 | 1 |
| `serialize_milky_segments` | `src/adapters/milky_serializer.py:41` | 116 | 28 | 1 |
| `build_system_prompt` | `src/services/prompt_builder.py:62` | 140 | 15 | 14 |
| `_ext_ai` | `src/plugins/manager.py:1796` | 113 | 28 | 3 |
| `_ext_plugin` | `src/plugins/manager.py:1589` | 106 | 30 | 3 |
| `_install_zip` | `src/plugins/installer.py:203` | 105 | 30 | 2 |
| `decode_bytes` | `src/services/file_parser.py:88` | 109 | 27 | 2 |
| `_scan_segments` | `src/adapters/milky_parser.py:215` | 104 | 24 | 3 |
| `render_knowledge_tab` | `src/services/webui_render/knowledge.py:7` | 137 | 6 | 7 |
| `is_toxic` | `src/services/toxic_detector.py:26` | 119 | 13 | 1 |
| `render_plugin_tab` | `src/services/webui_render/plugins.py:20` | 128 | 8 | 5 |
| `from_dict` | `src/plugins/manifest.py:117` | 89 | 26 | 3 |
| `plugin_webui_render` | `src/plugins/manager.py:310` | 99 | 20 | 5 |
| `chat_once` | `src/services/ai_client.py:41` | 117 | 9 | 16 |
| `_rule_matches` | `src/plugins/manager.py:1176` | 71 | 31 | 3 |
| `chat_with_messages` | `src/services/ai_client.py:209` | 100 | 16 | 4 |

## 3. 单文件代码行 Top 15

| 文件 | 代码行 | 物理行 |
| :--- | ---: | ---: |
| `src/plugins/manager.py` | 2549 | 2766 |
| `src/plugins/runner/python_runner.py` | 1255 | 1568 |
| `src/services/config_service.py` | 626 | 698 |
| `src/core/message_router.py` | 504 | 643 |
| `src/plugins/comm.py` | 483 | 618 |
| `src/config.py` | 470 | 605 |
| `src/plugins/runtime.py` | 430 | 500 |
| `src/services/sender.py` | 425 | 512 |
| `src/plugins/router.py` | 383 | 458 |
| `src/transport/transports.py` | 381 | 470 |
| `src/adapters/onebot_parser.py` | 371 | 433 |
| `src/services/file_parser.py` | 365 | 413 |
| `src/repositories/settings_repository.py` | 361 | 412 |
| `src/services/ai_client.py` | 361 | 412 |
| `src/services/web_ui.py` | 347 | 400 |
