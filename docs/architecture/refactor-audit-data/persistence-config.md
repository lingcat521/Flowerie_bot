# Phase 0：持久层 / 配置层 / utils 审计（子代理未覆盖的空白）

## 1. SettingsRepository（393 行 / 38 方法 / 被 20 个测试文件 import）

方法按前缀分布：get×10、delete×7、set×6、list×6、upsert×2、clear/try/mark/close 各 1。

**关键词：它不是一个「设置仓库」，而是 6~7 个数据域的 CRUD 大杂烩** ——

- prompt（提示词）、config（配置项）、pref（偏好）、persona（人格 + 全局/群绑定）、
- plugin（插件表 + 插件 KV）、bootstrap 标记、连接生命周期（close / _pragma / _init_schema）。

判定：**是上帝类（God Module 型：一个类什么都知道）**，但它是被依赖最广的模块（20 个测试文件直接 import），
拆分风险高 → 建议放到 Phase 2，且必须先补「面向行为的测试」再动结构（禁止改 SQL / 改语义）。

## 2. 多后端实现：不是重复代码，应保留

| 抽象 | 实现 A | 实现 B | 同名方法 | 差异 |
| :--- | :--- | :--- | ---: | :--- |
| MemoryRepository(ABC) | SQLiteMemoryRepository(16) | PostgresMemoryRepository(17) | 15 | 仅 _pragma vs _conn/_row |
| BlossomMemoryRepository(ABC) | SQLiteBlossomMemoryRepository(11) | PostgresBlossomMemoryRepository(11) | 10 | 仅 _conn |

→ 这是**同一接口的两个后端实现**（STORAGE_BACKEND=sqlite|postgres 切换），属正当多态，**不合并**。
→ 但 postgres_blossom_repository.py 全仓**只有测试引用**（非测试代码 0 引用）→ 死代码候选（待子代理 D 交叉确认）。

## 3. 配置层：双份字段清单 + 已经发生的漂移

- src/config.py：Settings 声明 **173** 个字段（类跨度 337 行）；validate_config() **152 行 / 55 分支**，
  全部用 getattr(config, 字段名, 默认值) 手写逐项校验（不是遍历元数据表）。
- src/services/config_schema.py：**171** 个字段的元数据表（_ENUM_VALUES / _ENUM_OPTIONS / _RANGES），供 WebUI 表单使用。
- **可验证的漂移**：WEB_UI_USERNAME、WEB_UI_PASSWORD 两个字段在 Settings 里声明了，但没有 schema 元数据
  （反向差集 = 0，即 schema 没有多余字段）。

判定：**重复清单（Phase 3 卫生项）** —— 同一份「字段真相」维护两遍且已漂移；validate_config 里的
getattr(..., 默认值) 会把「字段拼错/缺失」静默变成默认值（任务书第八节点名的「不必要的 getattr」）。

## 4. utils 层

| 文件 | 行数 | 被 import | 判定 |
| :--- | ---: | ---: | :--- |
| utils/logging_setup.py | 193 | **51** | 核心基础设施，勿动 |
| utils/metrics.py | 148 | 16 | 保留 |
| utils/expiring_map.py | 100 | 6 | 保留（有界缓存工具） |
| utils/trace.py | 42 | 7 | 保留 |
| utils/banner.py | 192 | 5 | 保留 |
| utils/circuit_breaker.py | 110 | 4 | 保留（熔断语义受保护） |
| utils/task_manager.py | 90 | 3 | 保留 |
| utils/logger.py | 15 | **0** | **死代码候选**（git grep 全仓 0 引用，与可达性分析一致） |

## 5. 本层性能观察

- SQLiteMemoryRepository._pragma() / _init_schema() 在构造期执行（一次性）→ 无问题。
- SettingsRepository 的 get_config / list_configs 等高频读路径是否重复 IO，需在 Phase 4 用调用点计数验证（Phase 0 不下结论）。

