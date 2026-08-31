# qwq1 审计（Web UI / 花语记忆）

> **命名注**：本文为 qwq 任务审计实录，按 qwq 原文使用示例名 LivingMemory；
> 最终落地命名为 **花语记忆 BlossomMemory**（见 configuration/memory/qwq-final-report）。


> 结论：架构已有良好基础（配置优先级链/Repository 接口/内存分层/无 JS 折叠先例/资源上限治理）。
> 本轮是**增量产品化**：6 个开关补全 + BlossomMemory（花语记忆，原 qwq 示例名 LivingMemory）（Embedding/Vector/Reranker 新抽象，默认 OFF）
> + Web UI 折叠推广 + 群知识管理强化。**不建议迁移 PostgreSQL**（见 §11）。

## 1. 配置读取与优先级（问题 1-2）
- 读源：`src/config.py`（pydantic-settings：代码默认 + `.env`）→ 启动时 `ConfigService.apply_persisted()`（settings.db）覆盖。
- 优先级：**Persistent(settings.db) > .env > Code Default**；特例（P4-1 修复）：`.env` 文件 mtime > db updated_at → `.env` 新值优先并同步回 db（防止本地手工改被 UI 旧值压掉）。
- 校验：仅 SCHEMA 内键、类型/范围校验通过才应用；非法跳过不阻断启动；secret 显示层 `_mask` 脱敏。

## 2. 热更与重启（问题 3-4）
- `apply_persisted`/账号保存均在启动期 `setattr(config)`；config_schema 第 4 位 `hot` 标记已存在（UI 标注）。
- 运行时组件绝大多数持有同一 Settings 实例并**即时读属性** → `setattr` 后**行为热生效**（概率/阈值/开关类）。
- **必须重启**：连接类（HTTP_API_BASE/WS 地址/API key 通道初始化）、资源初始化类（sticker 扫描、MCP client fail-fast、未来的 embedding client——**本轮 BlossomMemory（花语记忆，原 qwq 示例名 LivingMemory） 开关须在初始化层门控**）。

## 3. 现有 enabled 开关（问题 5）
已有 6 个（全部 `config_schema` 已注册、UI 可改、运行逻辑接入）：
`POKE_REPLY_ENABLED / ARCHIVE_ENABLED / STICKER_ENABLED / MCP_ENABLED / WEB_UI_ENABLED / MEME_LEARNING_ENABLED`

**缺失且应补**（qwq §20 清单对照）：
| 开关 | 现状 | 建议实现 |
| --- | --- | --- |
| `AI_ENABLED` | 无（始终走 AI） | 默认 true；关→跳过 AI 回复/Provider 请求，普通功能不受影响 |
| `MEMORY_ENABLED` | 无（始终读写） | 默认 true；关→不读/写长期记忆（短期 Context 不受影响） |
| `LIVING_MEMORY_ENABLED` | 无 | **默认 false**；off→零初始化/零调用 |
| `PROACTIVE_CHAT_ENABLED` | 无（仅概率参数，循环常驻） | 默认 true；关→不启动主动聊天循环 |
| `REPEAT_ENABLED` | 无（复读检测常驻） | 默认 true；关→跳过复读检测 |
| `ANTI_SPAM_ENABLED` | 无（冷却常驻） | 默认 true；关→跳过冷却/防刷逻辑 |
| `FILE_PARSING_ENABLED` | 无（按文件类型走） | 默认 true（文件解析是核心功能，开关仅停用自动 fetch）；建议不加（天然必须）→ 文档记录 |
| `KNOWLEDGE_LEARNING_ENABLED` | `MEME_LEARNING_ENABLED` 已存在 | 复用重命名别名（不删旧键，UI 显示「群梗/知识学习」） |
| `MESSAGE_ARCHIVE_ENABLED` | `ARCHIVE_ENABLED` 已存在 | 复用 |

## 4. SQLite 表（问题 6）：14 张
`memory / memory_kv / meme_knowledge / meme_summary_state / prompt_config / app_config /
webui_prefs / personas / group_persona / persona_global / plugins / admin_bootstrap /
plugin_kv / sticker_index`；已有索引：`idx_memory_ug`（memory 按 user+group）。

## 5. Memory / Context / Knowledge 边界（问题 7、17）
已天然三分（**不需要新抽象**，q wq §17 建议确认）：
- **Context**：`context_manager` 内存 deque 窗口（短期，最近 N 条，本进程生命周期）
- **Memory**：`memory` 表（user_id+group_id 事实，TTL 分级/上限/去重/矛盾替换/来源标注，审计日志）
- **Knowledge**：`meme_knowledge` 表（群梗/黑话，每群独立，24h 总结 + MCP 互联网学习，已有 sanitize 链路）

## 6. Embedding / Vector / Reranker（问题 8、11、12）
- **当前代码：无**（无任何 embedding/vector/reranker 实现或接口）→ 本轮全新增。
- 设计（按 qwq）：`EmbeddingProvider` / `Reranker` Protocol（纯接口）+ OpenAI-compatible HTTP 实现（复用现有 aiohttp + 多 key 体系），**零新依赖**；默认无内置小模型。

## 7. Repository 抽象（问题 9）
**已符合 qwq §14 模式**：`repositories/base.py` 定义 `MemoryRepository`（ABC + `MemoryNote` 载体），业务（MemoryManager）只依赖接口 → 未来 Postgres 平行实现零业务改动。Settings/Knowledge 同样走向接口（settings_repository 已有自己抽象）。

## 8. 长期状态增长风险（问题 10）
| 存储 | 现状 | 治理 |
| --- | --- | --- |
| memory 表 | TTL（model 30 天）+ 上限 + 去重 | ✅ 已治理 |
| meme_knowledge | 群上限 MAX_GROUP_MEMES + 缓冲群数上限 + 不活跃淘汰 | ✅ 已治理 |
| pending_files | 上限 100 + 10 分钟过期 | ✅ |
| context | bounded deque | ✅ |
| **BlossomMemory（花语记忆，原 qwq 示例名 LivingMemory）（新增）** | 无 | **须实现**：max sets/TTL/每日提取上限/清理任务/索引（§25 全项） |

## 9. Web UI 现状（问题 3 相关 + §6/23）
- **已有 `<details>/<summary>` 原生折叠先例**（persona.py 群聊 Prompt）——零 JS 模式可推广 ✅
- 认证：POST /api/login → bearer token（内存 TTL）；admin 权限已有；
- config_panel 目前按 category 平铺 → 改造目标：category `<details>` + 开关状态徽标 + 高级项默认折叠。
- 知识面板 `knowledge.py`：已有按群查看/搜索/删除（GET）——强化编辑（POST）即可。

## 10. Metrics（§26）
现有 label 为 `post_type/reason/...`（低基数）✅；新增语义记忆指标用 `operation/result/reason`（memory_retrieval_total 等），**禁 user/group/message/memory_id label**。

## 11. 存储决策倾向（§13-16，Phase 7 再定稿）
**倾向继续 SQLite**，理由：
1. **部署环境**：Android/Termux 单进程（本项目运行环境），Postgres/pgvector 无法部署（无服务化能力/依赖）；
2. 单进程单写者 → SQLite 并发瓶颈不存在（现有 `_lock` + 单连接已足够）；
3. Repository 接口已抽象 → 未来多实例/云端迁移路径 = 新增 `PostgresMemoryRepository`，业务不动；
4. Vector 策略：**轻量内置**——embedding 向量存 `memory_living` 表（JSON/blob）+ 纯 Python cosine 检索（内存索引，条目上限治理），**零新依赖**；上限 ~2k/组、检索 top-k 条 → 性能足够。
若未来需要：Postgres+pgvector 平行实现 + 迁移工具（schedule 到 Phase 8，仅当现库瓶颈出现）。

## 12. 审计结论 → Phase 2 输入
- 补 6 个新开关（AI/MEMORY/LIVING_MEMORY/PROACTIVE_CHAT/REPEAT/ANTI_SPAM），全部默认值保守（AI/MEMORY true，LIVING false，其余 true）
- 开关必须进运行时判断点（AI pipeline/memory pipeline/循环启动/检测器）
- 高级配置默认折叠；BlossomMemory（花语记忆，原 qwq 示例名 LivingMemory） 未开启（或配置不完整）时 UI 显示状态徽标
- config_schema 同步注册（category/type/secret/hot/desc 一致），.env 双向同步沿用现有机制（P4-1 链）
- 群知识管理：复用既有面板 + 编辑功能（POST 表单）
