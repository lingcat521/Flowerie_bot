# 死代码快速确认（引用证据）

| 候选 | 总引用文件 | 其中 tests | 其中 src | 其中 docs/scripts | 判定 |
| :--- | ---: | ---: | ---: | ---: | :--- |
| src/transport/transports.py | 1 | 0 | 1 | 0 | 有引用，保留 |
| src/transport/contract.py | 8 | 3 | 3 | 2 | 有引用，保留 |
| src/adapters/contract.py | 7 | 4 | 1 | 2 | 有引用，保留 |
| src/adapters/instance.py | 139 | 70 | 57 | 12 | 有引用，保留 |
| src/adapters/onebot12_parser.py | 5 | 4 | 1 | 0 | 有引用，保留 |
| src/adapters/testkit/test_protocol.py | 2 | 0 | 2 | 0 | 有引用，保留 |
| src/adapters/testkit/__init__.py | 161 | 78 | 75 | 8 | 有引用，保留 |
| src/repositories/postgres_blossom_repository.py | 1 | 1 | 0 | 0 | 仅测试引用 → 待确认 |
| src/services/storage_migrate.py | 5 | 1 | 1 | 3 | 有引用，保留 |
| src/sdk/listener.py | 2 | 2 | 0 | 0 | 仅测试引用 → 待确认 |
| src/utils/logger.py | 52 | 1 | 48 | 3 | 有引用，保留 |
| src/services/webui_render/__init__.py | 161 | 78 | 75 | 8 | 有引用，保留 |
| src/repositories/__init__.py | 161 | 78 | 75 | 8 | 有引用，保留 |
| src/__init__.py | 161 | 78 | 75 | 8 | 有引用，保留 |
| src/core/name_mention.py | 0 | 0 | 0 | 0 | 可删候选 |
| old_ai_tmp.py | 0 | 0 | 0 | 0 | 可删候选 |
| src/adapters/compat.py | 5 | 4 | 1 | 0 | 有引用，保留 |
| src/core/poke_manager.py | 1 | 0 | 1 | 0 | 有引用，保留 |
| src/services/system_status.py | 1 | 0 | 1 | 0 | 有引用，保留 |
| src/adapters/onebot/dto.py | 5 | 1 | 3 | 1 | 有引用，保留 |
