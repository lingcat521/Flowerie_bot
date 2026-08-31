# Flowerie_bot 1.6.0 交付报告（Web UI 功能开关 + 花语记忆 + 存储后端）

> 验收：CI（Python 3.9/3.12，754+ 测试含 PG service 真跑）✅ success；黑盒 Acceptance（39 项）✅ success；ruff 0。

## 1. 修改前架构审计
- 配置：pydantic-settings（.env+默认）→ apply_persisted（settings.db 覆盖）；优先级 Persistent > .env > 默认（.env 较新优先双向同步）
- 已有 6 个开关；Memory/Context/Knowledge 已天然三分；Repository 接口模式已存在；无任何 embedding/vector 代码；SQLite 14 表；长期状态均有上限/TTL 治理（详见 docs/qwq1-audit-webui-livingmemory.md）

## 2-3. 新增功能开关（默认值 / 折叠）
| 开关 | 默认 | 运行时门控点 |
| --- | --- | --- |
| `AI_ENABLED` | true | guarded_chat 单点拦截（关=零 Provider 请求） |
| `MEMORY_ENABLED` | true | MemoryManager 读写单点（关=不读不写，短期 Context 不受影响） |
| `PROACTIVE_CHAT_ENABLED` | true | 主动聊天循环注册 |
| `REPEAT_ENABLED` | true | 复读检测 |
| `ANTI_SPAM_ENABLED` | true | 冷却/防刷检查 |
| `BLOSSOM_MEMORY_ENABLED` | **false** | 花语记忆总开关（OFF=零模型资源） |
| 花语记忆 4 子开关 | **false** | 向量模型/重排序/自动提取/长期检索 |
| 既有 6 开关 | 不变 | POKE/ARCHIVE/STICKER/MCP/WEB_UI/MEME_LEARNING |

**默认折叠**：全部配置分类 `<details>/<summary>`（零 JS）；花语记忆默认关闭且子开关/模型配置服务端门控渲染（OFF 时完全不显示），仅显示总开关+状态。

## 4. .env 同步机制
沿用 P4-1 链：Web UI 保存 → settings.db + .env 原子更新（保留注释）；apply_persisted 启动合并（.env mtime > db ts 时 .env 优先并回写 db）；secret 脱敏显示、留空不覆盖。

## 5-8. LivingMemory（花语记忆 BlossomMemory）架构
- **EmbeddingProvider / Reranker**：纯 Protocol + OpenAI-compatible HTTP 实现（复用 MCP 同款 SSRF 校验；零新依赖；默认无内置小模型）
- **Vector**：纯 Python cosine（内存索引，条目上限治理）；存储=SQLite（默认）/ PG（JSONB），pgvector 列为未来可选
- **管线**：提取（每日限额）→ embed → 存储(blossom_memory 表, group_id 隔离) → 检索 top-k → 可选 rerank → sanitize → 注入【检索到的历史记忆】段（**声明来源不可信、优先级低于系统安全规则**）
- **配置缺失**：validate_config fail-fast（同 MCP 策略，绝不静默降级）；UI 显示状态

## 9. SQLite / PostgreSQL 决策
**继续 SQLite（默认）+ 可选 PG 后端**：
原因：① 部署环境 Android/Termux 单进程（无 PG 服务化能力）② 单写者无并发瓶颈（现有 _lock+WAL 足够）③ Repository 接口已抽象 → PG 平行实现 `Postgres*Repository`（psycopg 软依赖）业务零改动 ④ 向量=存储+内存 cosine 与后端无关
**迁移**：`python -m src.services.storage_migrate`（幂等 ON CONFLICT DO NOTHING / 缺表跳过 / 失败源库不动 / 行数校验）；CI postgres service 真跑 PG CRUD/隔离/TTL

## 10-12. 边界 / 隔离 / 无 JS
- Memory（长期事实）/ Context（短期窗口）/ Knowledge（群梗）/ BlossomMemory（语义检索）：四层清晰；user/global 维度不启用（不为完整而强加）
- 群隔离：blossom_memory 检索只取本群（group_id 索引）；知识库按群独立 + 跨群测试
- Web UI：零 JS 验证 PASS（grep <script/onclick/fetch 等 0 命中；`<details>` 原生折叠；表单 POST）

## 13-17. 安全/资源/长跑
- **MCP legacy 单 server SSRF 校验缺口修复**（真 bug：loopback URL 曾放行 → 现与多 server 一致校验 URL/timeout/tools）
- 记忆/检索 sanitize 兜底；指标低基数（memory_*_total 仅 result 标签，禁 id 类）
- 花语记忆资源限制：MAX_ENTRIES（2000）/TTL（90 天）/DAILY_EXTRACT_LIMIT（20）/自动清理/索引；OFF=零初始化
- 模拟长跑（bounded 检查）：context deque / pending_files(100,10min) / 知识上限 / 均已有界

## 18-21. 测试结果
- 新增测试：blossom 7 + webui 3 + storage 3 + PG 2 + gate 3 + 迁移 1 ≈ **+19**
- 本地可跑子集 **204 passed**；ruff **0**；CI（3.9+3.12 全量 **success**，含 PG service）；黑盒 Acceptance **success（39/39）**

## 22-24. 文档 / diff / 剩余风险
- 文档：README（v1.6.0）+ docs/configuration.md（开关表/花语/存储）+ docs/memory.md（新）+ knowledge.md / web-ui.md / development.md 同步；最终决策见本文
- diff 概要：+~2600 行（adapters/开关/花语/存储/迁移/测试/文档），现有业务逻辑行为等价（默认值全保持）
- 剩余风险：① PG 后端需用户自备服务器（CI 已验证接口语义）② embedding/reranker API 依赖第三方可达性（fail-fast+降级已设计）③ 花语记忆为「存储+内存检索」，>2k 条/组时全量加载（上限治理兜底，未来可换 pgvector）
