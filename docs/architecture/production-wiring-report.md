# 生产链路报告（road.txt §十一）

> 配套审计：`docs/architecture/production-wiring-audit.md`（修复前快照 + 五分判据取证）
> 基线 `ecdcf86` → 交付 `0576580`：4 个提交、12 个文件、+430 / −7 行。
> 原则：**从生产副作用反向验证调用链**；回答不了「谁调用 / 为什么进生产 / 生命周期 / 依赖从哪注入 /
> 什么副作用」的，就不接线。

## 1. 修复前

| 链路 | 状态 | 原因 |
| :--- | :--- | :--- |
| `STORAGE_BACKEND=postgres` → `PostgresMemoryRepository` → `MemoryManager` | ✅ 已接线 | 组合根显式选择并注入 |
| `STORAGE_BACKEND=postgres` → Blossom Memory | ❌ **断链** | `main.py` 调 `BlossomMemoryManager(config, embedding=, reranker=)` 不传 repository → `blossom_memory.py:169` 永远自建 `SQLiteBlossomMemoryRepository`；配置项**无法影响**实现（判据⑤） |
| `Configuration` → `InstanceRegistry` → `AdapterInstance` → Parser/Sender | ❌ **断链** | 三个类与测试都在，但生产只用单实例 `make_adapters`；registry 零生产调用者 |
| `TransportContract` / `WebSocketTransport` / `HTTPTransport` / `RetryPolicy` | ⚠️ 预留 | 生产仍是旧栈（`MilkyClient` / `NapCatForwardClient` / `WebSocketServer`）；且 `transports.py` 写死 `extra_headers`，在 websockets 17.1 下必炸 |
| `old_ai_tmp.py` | ✅ 已清除 | 历史提交 `7410dcf` 删除；本轮复核零活引用 |
| `EventDispatcher` | ⚠️ 未声明 | 在中层 SDK 内但 `__all__` 未导出、文档无记载、只有测试调用 |

## 2. 修复后（实际生产链）

```text
main.py
 ├─ load_config() → ConfigService.apply_persisted() → validate_config() → init_logging()
 ├─ STORAGE_BACKEND=postgres ?
 │     → PostgresMemoryRepository(DATABASE_URL) → MemoryManager(repository=…)
 ├─ BLOSSOM_MEMORY_ENABLED ?
 │     → _build_blossom_repository(config)                    [新增]
 │         ├─ sqlite  → None（管理器自建 SQLite，行为不变）
 │         └─ postgres→ PostgresBlossomMemoryRepository(DATABASE_URL)
 │                      └─ BlossomMemoryManager(repository=…)  [新增注入]
 ├─ AIClient(config, memory_manager) ─┐ async with
 ├─ Sender(config, outgoing_adapter) ─┘
 ├─ make_adapters(BOT_QQ, sender, protocol) → adapters.parser
 ├─ make_instance_registry(config, parser=adapters.parser)     [新增]
 │     └─ InstanceRegistry{ primary: AdapterInstance(parser 同源, channel=None) }
 ├─ PolicyEngine / MemoryManager / StickerManager / McpToolManager / PersonaManager
 ├─ MemeKnowledgeManager / MemeSummaryService / PluginManager / WebUIServer
 ├─ MessageRouter(…, event_parser=adapters.parser, sender=sender, blossom_memory=…)
 ├─ await message_router.start() → await instance_registry.connect_all()   [新增]
 ├─ ws_server.run()（MilkyClient | NapCatForwardClient | WebSocketServer）
 └─ shutdown（顺序）
      instance_registry.disconnect_all()  [新增] → message_router.stop() → ws_server.shutdown()
      → web_ui.stop() → file_parser.close() → plugin_manager.shutdown()
      → memory_manager.close() → blossom_memory.close()（关掉注入的 PG 连接池）
      → settings_repo.close() → sticker_manager.close() → meme_manager.close() → tool_manager.close()
```

副作用路径不变：协议事件 → Adapter/parser → InternalEvent → MessageRouter → AI/Services →
Sender → 协议出口；Core 仍只见 `InternalEvent` / `MessageSender`。

## 3. 仍然未接线的代码（四类，不混在一起）

### A. 真正应该接线
**无遗留。** 本轮已把两条真断点接完（Blossom PG、InstanceRegistry）。
其余候选逐条核过判据后分别归入 B/C/D。

### B. 有意测试/契约代码
- `src/adapters/testkit/`（适配器契约测试工具箱）；
- 各 `tests/plugins/*/flowerie_sdk/`（插件自带 SDK 副本，模拟真实部署形态）；
- `tests/fixtures/plugin_protocol_vectors.json`（跨语言协议向量）。

### C. 未来能力/预留
- **Transport 抽象**：`TransportContract` / `WebSocketTransport` / `HTTPTransport` / `RetryPolicy`
  —— 契约尚未收口鉴权/生命周期/协议语义差异，**本轮不迁移生产连接栈**（任务书明确：不为形式上的
  "全部接线"强行迁移）。已修掉它的 websockets 14+ 兼容缺陷，边界记录在审计文档 §2.3；
- `src/adapters/onebot12_parser.py`：预留骨架/契约测试用途（见 §6）；
- MCP 的 `resource` / `prompt`：v1 明确返回 not supported（不是断链，是诚实接口）。

### D. 死代码
- `old_ai_tmp.py`（762 行的旧单体现 AIClient）：已由历史提交 `7410dcf` 删除；
  本轮复核 `find` / `git ls-files` 无此文件，仓库内仅存**历史审计记录**的文字提及；
- 本轮未发现新的、证据充分的死代码（不凭"没人 import"就删）。

## 4. 修改文件（每个文件为什么改）

| 文件 | 为什么改 |
| :--- | :--- |
| `main.py` | `_storage_backend` / `_build_blossom_repository`（§二）；注入 registry 并接上启动/关闭生命周期（§三） |
| `src/adapters/container.py` | 新增 `make_instance_registry`：兼容单实例的生产装配层（parser 同源、无全局单例） |
| `src/adapters/__init__.py` | 导出 `make_instance_registry` |
| `src/transport/transports.py` | `websockets_connector` 兼容 websockets 14+（`additional_headers`，回退 `extra_headers`） |
| `src/sdk/__init__.py` / `src/sdk/listener.py` | `EventDispatcher` / `EventListener` 公开声明 + 生命周期与 Plugin Bus 边界 |
| `scripts/check_imports.py` | 自检脚本补根模块 first-party 判定（`import main` 被误判成 third-party） |
| `tests/test_blossom_backend_wiring.py`（新） | §二的 7 条接线测试（不需要真 PG） |
| `tests/test_multi_instance.py` | §三追加 4 条装配/生命周期/零串台/静态护栏 |
| `tests/test_transport_contract.py` | §四追加 2 条（新参数优先 + 旧版本回退） |
| `tests/test_sdk_listener.py` | §六追加 1 条公开面测试 |
| `docs/architecture/production-wiring-audit.md`（新） | §一 审计（修复前调用图 + 五分判据取证） |

## 5. 测试结果

| 项 | 结果 |
| :--- | :--- |
| 本机全量 `pytest -q -rs`（真 pydantic + 真 httpx） | 2 failed, 2353 passed, 169 skipped, 1 xfailed, 13 warnings in 337.67s (0:05:37) |
| 本机静态自检 `scripts/check_imports.py` | 383 文件 **0 问题**（含本次新增规则） |
| `ruff` | 本机无 ruff（Android aarch64 无 wheel）；由 CI 的 `ruff check .` 把关 |
| 相关专项 | `tests/test_*postgres* / test_multi_instance / test_transport_contract / test_sdk_listener / test_blossom*` 全绿 |
| CI | 全部 success（7/7）：Analyze (actions) · Analyze (javascript-typescript) · Analyze (python) · accept · test (3.12) · test (3.9) · webui-e2e |

## 6. 不要把 OneBot12 算进问题

**OneBot12 当前属于未纳入生产支持范围，因此不作为断链或修复项。**

- `src/adapters/onebot12_parser.py` 是预留骨架 / 契约测试用途；
- 本轮**没有**为它接入 transport、**没有**修改生产协议选择、**没有**宣称已支持；
- 生产协议选择仍是 `QQ_PROTOCOL=onebot|milky`（`main.py` 的三选一），一字未动。
