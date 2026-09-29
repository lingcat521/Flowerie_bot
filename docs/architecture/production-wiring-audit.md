# 生产链路接线审计（road.txt §一：修复前）

> 方法：以 `main.py` 为唯一 Composition Root，**从生产副作用反向验证调用链**；
> 每一条都回答「谁调用它 / 为什么该进生产 / 生命周期谁管 / 依赖从哪注入 / 产生什么副作用」。
> 判据五分：①有生产调用者 ②只有测试调用 ③预留/契约实现 ④真断点 ⑤配置项是否真能影响实现。
> 基线：`b2daf04` 之后的 2.4.0 主干；本文件是**修复前**快照，修复进展见各节「本轮」标注。

## 1. 修复前：实际生产调用图

```text
main.py
 └─ load_config() → validate_config() → init_logging()
     ├─ SettingsRepository(settings.db) → ConfigService.apply_persisted()
     ├─ STORAGE_BACKEND=postgres ?
     │     ├─ PostgresMemoryRepository(DATABASE_URL) → MemoryManager(repository=…)   [✅ 已接线]
     │     └─ （Blossom Memory 这条**没接**：见 §2.1）
     ├─ BLOSSOM_MEMORY_ENABLED ? → BlossomMemoryManager(config)  ← 总是自建 SQLite
     ├─ AIClient(config, memory_manager) ─┐
     ├─ Sender(config, outgoing_adapter) ─┤ async with
     │    └─ make_adapters(BOT_QQ, sender, protocol) → Adapters{parser, sender}  ← 单实例
     ├─ PolicyEngine / MemoryManager / StickerManager / McpToolManager / PersonaManager
     ├─ MemeKnowledgeManager / MemeSummaryService / PluginManager / WebUIServer
     ├─ MessageRouter(..., event_parser=adapters.parser, sender=sender)
     └─ ws_server.run()   ← 三选一：MilkyClient | NapCatForwardClient | WebSocketServer
          └─ 副作用：收事件 → MessageRouter → AI/Service → Sender → 协议出口
```

## 2. 五条线的判定

### 2.1 Blossom Memory 的 PostgreSQL 后端 —— **A. 真正应该接线（本轮已修）**

| 项 | 事实 |
| :--- | :--- |
| 谁调用 | `main.py:118` 调 `BlossomMemoryManager(config, embedding=, reranker=)`，**不传 repository** |
| 实现是否存在 | `src/repositories/postgres_blossom_repository.py:16 PostgresBlossomMemoryRepository` 存在且完整（schema/CRUD/TTL） |
| 现状 | `blossom_memory.py:169 self.repository = repository or SQLiteBlossomMemoryRepository(db)` → **postgres 配置下也永远落 SQLite** |
| 测试覆盖 | 只有 `tests/test_postgres_backend.py:41`（需真 PG，CI postgres service） |
| 判据⑤ | `STORAGE_BACKEND=postgres` **无法影响** Blossom 实现 → 真断点 |
| 生命周期 | 仓库由 `BlossomMemoryManager.close()` 关闭（`blossom_memory.py:287-292`），注入后归属不变 |
| **本轮** | 已修：`745ee98`（组合根 `_build_blossom_repository` + 7 条测试） |

### 2.2 Multi-instance Adapter —— **A. 真正应该接线（待办）**

| 项 | 事实 |
| :--- | :--- |
| 已有实现 | `src/adapters/instance.py`：`AdapterInstance`（解析器/描述符/发送出口/配置各自独立）+ `InstanceRegistry`（非单例，重名报错）+ `make_instance()` |
| 生产调用者 | **无**。`main.py:131 make_adapters(...)` 只产出单实例 `Adapters{parser, sender}` |
| 只有测试 | `tests/test_multi_instance.py`（`InstanceRegistry()` / 串台=0 断言） |
| 判定 | 设计已承诺「OneBot11 #1/#2 + Milky #1 并存」，生产却没有装配层入口 → **真断点**（按任务书：可先做**兼容单实例**的装配层，保证以后加实例不用重写 Core） |
| 边界 | Core 仍只见 `InternalEvent` / `MessageSender`；不得引入全局单例；不得改 Plugin SDK |

### 2.3 Transport 抽象（`TransportContract` / `WebSocketTransport` / `HTTPTransport` / `RetryPolicy`）—— **C. 未来能力/预留，但有一处真 API 缺陷**

| 项 | 事实 |
| :--- | :--- |
| 生产调用者 | **无**：`main.py` 的 ws_server 仍是 `MilkyClient` / `NapCatForwardClient` / `WebSocketServer`（旧栈） |
| 谁在用 | 仅 `src/transport/__init__.py` 导出 + `tests/test_transport_contract.py` |
| 真缺陷 | `transports.py:441 websockets.connect(url, extra_headers=…)`；实测本机/CI 的 **websockets 17.1** 签名只有 `additional_headers`（没有 `extra_headers`）→ 一旦被生产使用会直接 TypeError；`ws_forward_client.py:134-140` 已有正确兼容写法 |
| 判定 | 契约尚未具备替换生产连接栈的条件（鉴权/生命周期/协议语义差异未收口）→ **不强行迁移**，按任务书记录边界并修掉 API 兼容缺陷 |

### 2.4 `old_ai_tmp.py` —— **D. 死代码（已在历史提交清除）**

| 项 | 事实 |
| :--- | :--- |
| 文件 | `find . -name old_ai_tmp.py` 无结果；`git ls-files` 不跟踪 |
| 删除提交 | `7410dcf chore: 删三处已确认的死代码（P0-4a）`（早于本轮） |
| 残留引用 | 仅 `docs/architecture/refactor-audit*.md` 的**历史审计记录**（记录它存在过、可删），不是活引用 |
| **本轮** | 复核确认零活引用；无需再动手（任务书要求的「删除」已由历史提交完成） |

### 2.5 `EventDispatcher`（`src/sdk/listener.py:27`）—— **B. 有意的中层 SDK 组件（缺声明，待办）**

| 项 | 事实 |
| :--- | :--- |
| 定义 | `EventListener` + `EventDispatcher`（types/priority/stop/异常隔离/shutdown），零 OneBot 语义 |
| 生产调用者 | 无；`src/sdk/__init__.py` 的 `__all__` **未导出**；`plugin_sdk` 不使用；文档无记载 |
| 只有测试 | `tests/test_sdk_listener.py`（8 条） |
| 判定 | 位于中层 SDK（`src/sdk/`）但从未声明为公开 API → 既不能当死代码直接删（它是 SDK 层的一部分），也不能算已接线。按任务书「属于正式 SDK 就保留 + 明确生命周期 + 与 Plugin Bus 不冲突」处理：**公开声明 + 写清与 Plugin Bus 的分工** |

## 3. 明确不计入问题

- **OneBot 12**：`onebot12_parser.py` 是预留骨架/契约测试用途，**未纳入生产支持范围**，
  因此不作为断链或修复项：不接 transport、不改生产协议选择、不宣称已支持。
- 测试夹具 / 契约实现（`src/adapters/testkit/`、各 `tests/plugins/*` 的 SDK 副本）：有意为之，不是断链。
