# 协议缺口封口台账（Protocol Gap Closure）

> 任务书 `complete&expand.txt` A 部分 §2/§11/§12 要求：**先建台账，再改代码**；每个 Gap 必须走完
> DoD 九段链（Source → Model → Fixture → Unit → Round-trip/Reverse → Real → Docs → CI → CLOSED），
> 缺任何一段都不许标 `CLOSED`。本文件是缺口状态的**唯一权威表**，所有数字必须来自真实测试输出。

## 0. 状态词表（任务书 §2 给定）

`OPEN` / `IN_PROGRESS` / `SOURCE_VERIFIED` / `IMPLEMENTED` / `FIXTURE_VERIFIED` /
`INTEGRATION_VERIFIED` / `CLOSED` / `BLOCKED` / `UNKNOWN`

## 1. 基线（本阶段开始时实测，2026-08-09）

| 项 | 值 |
| :--- | :--- |
| pytest | 837 passed / 19 failed（全部为缺依赖）/ 13 skipped |
| CI | Push on main / Acceptance / CI 三项 success |
| 测试文件 | 126 |
| fixtures | 7 个（带 `_provenance`）|
| HEAD | `65068c7` |

## 2. 缺口总表

| ID | 缺口 | 初始状态 | 目标 | 证据要求 | 当前状态 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **G1** | Milky `message_scene=temp` | incomplete（`scope=""`）| complete | source + fixture + test | **IMPLEMENTED / FIXTURE_VERIFIED**（Docs 已更新，待 CI 绿 → CLOSED）|
| **G2** | Milky 请求类事件字段级映射 | incomplete（只有 kind/request_kind）| complete | source + fixture + test | OPEN |
| **G3** | Milky `record` / `video` / `xml` | incomplete（仅 `segments_summary`）| complete/explicit | source + fixture + test | OPEN |
| **G4** | Milky `reply.segments` | incomplete（只消费 message_seq）| complete | source + fixture + test | OPEN |
| **G5** | Milky 多媒体发送（upload→resource_id→send）| no real validation | complete | source + real device | OPEN（依赖实机）|
| **G6** | 实机 Integration Test（OneBot11 10 + Milky 12）| missing | complete | integration test | OPEN（依赖实机）|
| **G7** | OpenShamrock | SOURCE_UNAVAILABLE | researched/validated | source/device | OPEN（重试 + 文档研究）|
| **G8** | OneBot v12 | not implemented | researched + mapped | spec/source | OPEN |

## 3. DoD 逐项（任务书 §12 表）

| Gap | Source | Model | Fixture | Unit | Roundtrip | Real | Docs | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| G1 temp | ✓ | ✓ | ✓ | ✓ | ✓ | --（不适用）| ✓ | IMPLEMENTED |
| G2 request | | | | | | | | OPEN |
| G3 media/XML | | | | | | | | OPEN |
| G4 reply.segments | | | | | | | | OPEN |
| G5 media send | | | | | | | | OPEN |
| G6 real integration | | -- | -- | -- | -- | | | OPEN |
| G7 OpenShamrock | | | | | | | | OPEN |
| G8 OneBot12 | | | | | | | | OPEN |

## 4. G1 封口记录（Milky `message_scene=temp`）

**证据（Source Verified）**
- `[DOC]` Milky 规范 `protocol/src/ir/common.ts` L266-291：`IncomingMessage` 以 **`message_scene`** 判别
  `friend / group / temp`；**temp 变体**字段为 `peer_id` / `message_seq` / `sender_id` / `time` / `segments`
  + **可选** `group` 实体（L158-168 `GroupEntity.group_id`）—— 群是**实体**，不是 `group_id` 标量。
- `[DOC]` 同一枚举 L23 / L31 亦为 `friend / group / temp` —— **规范里没有 `group_temp`**。
- `[CODE]` LLBot `src/milky/transform/event.ts` L78-80：temp 场景 `message_scene: "temp"`、`peer_id: data.peerUin`。
- `[DOC]` OneBot 11 `event/message.md` L16：私聊 `sub_type=group` 即**群临时会话**；L10-22 的私聊字段表里
  **没有 `group_id`** —— 实现若额外提供，只能当作上下文，不能当协议保证。

**Model（Implemented）**
- `InternalEvent` 新增两个归一化字段：`scene`（会话类型：`group` / `friend` / `temp` / `stranger`）、
  `context_group_id`（非群会话的上下文群，如临时会话来源群）。
- Milky：`temp` → `scope="private"` + `scene="temp"` + `actor_id=sender_id` + `context_group_id=group.group_id`（可选）；
  旧别名 `group_temp` 归一成规范值 `temp`。
- OneBot：`message_type=private & sub_type=group` → `scene="temp"`；若实现带了 `group_id` → 记为 `context_group_id`
  且**不**写入 `group_id`（不冒充群会话）。
- Core 边界（实测并写入测试）：`message_router._handle_message` 首行 `if event.scope != "group": return` ——
  **Core 当前只处理群会话**；因此 temp 归一化为"私聊范围"是正确的，既没有 `scope=""` 的信息丢失，
  也不冒充群消息。插件事件投递在 scope 判断之前，仍能拿到 `kind=message`。

**Fixture / Test（Fixture Verified）**
- `tests/fixtures/milky/temp_message_scene.json`（含 group 实体）、`tests/fixtures/onebot11/private_group_temp.json`（规范纯样本，无 group_id）。
- `tests/test_temp_scene.py`：**11 个用例** —— Milky 带群实体 / 不带群实体（optional）/ `group_temp` 别名归一 /
  friend+group 不回归 / OneBot temp / OneBot 实现带 group_id → 上下文 / OneBot friend+group 不回归 /
  跨协议等价（Milky temp ≡ OneBot temp）/ 两个 fixture 解析 + provenance / round-trip 稳定。

**变更文件**：`src/adapters/proto.py`、`src/adapters/milky_parser.py`、`src/adapters/onebot_parser.py`、
`tests/test_temp_scene.py`、`tests/fixtures/milky/temp_message_scene.json`、`tests/fixtures/onebot11/private_group_temp.json`。

## 5. 量化指标（任务书 §19/§20/§21）

| 指标 | 定义 | 当前 | 目标 |
| :--- | :--- | :--- | :--- |
| Gap Closure Rate | CLOSED / 8 | 0/8（G1 待 CI 转 CLOSED）| 8/8 或明确 BLOCKED |
| Real Integration Coverage | 实机验证能力 / 要求验证能力 | 0%（无实机）| ≥90% 或 BLOCKED |
| 新增测试（G1–G5）| 任务书 §17 | G1 = 11（要求 ≥3）| ≥19 累计 |

> 本文件随每个 Gap 的推进更新；**没有真实测试输出支撑的数字一律不写**。
