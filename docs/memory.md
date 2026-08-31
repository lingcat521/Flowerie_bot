# 记忆系统（Memory / 花语记忆 / Knowledge）

## 分层边界

| 层 | 载体 | 生命周期 | 存储 |
| --- | --- | --- | --- |
| Context | 最近 N 条对话（内存 deque） | 短期（进程内） | 内存 + 周期备份 |
| Memory | 长期个人事实（user+group 隔离） | 长期（TTL 分级） | `memory` 表（SQLite/PG） |
| Knowledge | 群梗/黑话/群事实（群隔离） | 长期（上限治理） | `meme_knowledge` 表 |
| 花语记忆 | 语义检索层（Embedding+向量+可重排） | 长期（TTL/上限/日额度） | `blossom_memory` 表 |

## 花语记忆（BlossomMemory）

```
消息/事实
  ↓ 自动提取（每日限额，默认关）
Embedding(HTTP, OpenAI-compatible)
  ↓ cosine top-k（群隔离：只检索本群）
可选 Rerank（HTTP）
  ↓ sanitize（不可信数据清洗）
注入 system prompt【检索到的历史记忆】段（声明来源不可信、低于系统安全规则）
```

- 默认关闭（`BLOSSOM_MEMORY_ENABLED=false`）＝零模型资源
- 治理：MAX_ENTRIES / TTL_DAYS / DAILY_EXTRACT_LIMIT / 自动清理；索引 (group_id, kind, target_id)
- 配置缺失 fail-fast（同 MCP 策略）；指标低基数（result 标签）
