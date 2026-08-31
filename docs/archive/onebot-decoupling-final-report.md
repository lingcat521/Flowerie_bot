# OneBot 解耦最终验收报告（Phase 1-7）

> 结论：**目标达成**。Flowerie 核心业务与 OneBot 协议层已通过**新增抽象边界 + 渐进迁移**
> 完成解耦（零重写、零删除、行为等价）；所有剩余 OneBot 依赖均在允许的
> adapter / sender / sdk 边界内。Legacy Compatibility Layer 常驻保留。

## 1. 最终架构

```
OneBot WS（napcat_forward_client / websocket_server）      ← 边界：仅透传+日志
        │  dict
        ▼
OneBotEventParser（src/adapters/onebot_parser.py）        ← 唯一 raw 读取点
        │  InternalEvent（领域语义：kind/scope/actor_id/text/mentions/images/
        │                reply_id/notice_kind/target_id/notice_file/...）
        ▼
MessageRouter（src/core/message_router.py）               ← 零 OneBot 字段判断
        │
        ├─ compat.build_group_message → GroupMessage       ← Legacy 兼容层（保留）
        │        │
        │        ▼ Context / AI / 人格 / 记忆 / MCP / 知识库 / 限流 / 权限（冻结区，零 OneBot）
        │
        └─ 插件通道 dispatch_event(event.kind, payload)    ← 领域 payload（kind/scope/at_list/...）
Sender（src/services/sender.py）                          ← 出口唯一边界（端点 + HTTP/Token/重试）
        ▲
组合根（src/adapters/container.py）：Settings → Sender → make_adapters → Adapters{parser, sender}
```

**依赖方向（单向）**：`core → adapters(契约) ← adapter 实现；冻结层（services*/repositories）
不 import 任何消息边界（扫描断言保障）。

## 2. 残余 OneBot 允许耦合清单（Phase 7 扫描核实）

| 位置 | 内容 | 性质 | 状态 |
| --- | --- | --- | --- |
| `src/adapters/onebot_parser.py` | 唯一 `raw.get("post_type/sub_type/message_type")` | 边界转换 | ✅ 允许 |
| `src/adapters/proto.py / compat.py` | 注释/构造参数名（raw_message） | 命名 | ✅ 允许 |
| `src/services/sender.py` | 全部 HTTP 端点 + OneBot payload | 出口边界 | ✅ 允许 |
| `src/core/napcat_forward_client.py` / `websocket_server.py` | `post_type` 仅日志/指标 label | 透传 | ✅ 允许 |
| `src/sdk/onebot/`（dto/transformer/adapter） | OneBot 结构（插件通道适配层） | 适配层 | ✅ 允许 |
| `src/models.py:69` `GroupMessage.raw_message` 字段名 | 命名遗留（冻结区，字段语义领域） | 命名 | ✅ 允许（不改） |
| `src/services/file_parser.py:396` `self_id` 局部变量名 | 命名（值=boot_qq 自 ID 对比） | 命名 | ✅ 允许（冻结） |
| `src/sdk/event.py` / `__init__.py` | 层约束注释（「不得出现 post_type」校验说明） | 注释 | ✅ 允许 |
| `src/plugins/manager.py:36` | `src.sdk.onebot.adapter.OneBotAdapter`（插件通道 IPC 适配） | 适配层 | ✅ 允许 |

**字段级读取（post_type/sub_type/message_type 作为数据访问）：仅 1 处 = onebot_parser（边界）**；
全库 `raw_data[` / `raw_data.get` 业务读取：**0**（自动测试断言）。

## 3. 测试结果

| 项目 | 结果 |
| --- | --- |
| 本地 pytest（stdlib 子集） | **185 passed**（含 Phase 3-6 新增 41：adapters 12 / bootstrap 7 / migration 16 / sdk social 等） |
| ruff check . | **0 错误** |
| CI（Python 3.9 + 3.12，全量 754） | **success**（3.9 与 3.12 均绿） |
| 黑盒 Acceptance（37 项） | **success**（36 PASS + pytest 全绿 + ruff + JS 零检查 + 人格/知识/启动） |
| git diff --check | 干净 |

### Phase 1-6 各阶段验收
| Phase | 范围 | 验收 |
| --- | --- | --- |
| 1 | 审计（耦合点 8 文件 21 处） | 报告落盘 docs/onebot-coupling-audit.md |
| 2 | 设计（InternalEvent/Protocols/兼容策略） | 设计落盘 docs/phase2-internal-event-design.md（方案 A 演进，未实施改字段） |
| 3 | 边界（proto/parser/10 测试） | CI 绿（评审通过） |
| 4 | 组合根注入（main.py +8 行） | CI 绿；契约校验启动期生效 |
| 5 | Router 接入（±69 行超 50 红线——已报告获准） | CI+Acceptance 双绿 |
| 6 | poke/upload + assembler（审计 ±30 行≤50） | CI+Acceptance 双绿（修复 3 处实现/桩） |
| 7 | 最终验收（本次） | 扫描+测试通过，文档封口 |

## 4. 回滚路径（自动化回滚预案）

1. **单提交回滚**（推荐）：`git revert a8cfa69`（Phase 6）与 `git revert a229726`（Phase 5）——
   两步即回到 Phase 4 状态（router 全旧行为，组合根保留但无消费者，行为 100% 旧版）。
   注意：Phase 6 修复（poke 调用点等）随 6 一起回滚；FakeAssembler 桩回滚亦无需处理
   （2e6868b 基线桩）。
2. **版本回滚**：`git checkout` 到 `4e2a82a`（Phase 5 后）或 `8b0bbeb`（Phase 4 后）；
   数据库/配置无 schema 变更，直接切换即可。
3. **软回滚（不动代码）**：`main.py` 将 `MessageRouter(event_parser=...)` 改为
   `event_parser=None`（router 自建 OneBotEventParser，行为不变且无感知）；
   `adapters` 对象保留但无人消费——零风险。Compatibility Layer（compat.py）常驻，
   任何阶段都不构成回滚障碍。
4. 上游网关回滚：NapCat → Lagrange 仅需换 HTTP_BASE/WS 地址（适配层不变）。

## 5. 冻结声明

- Legacy Compatibility Layer（compat.py + convert_legacy）：**保留**（通过完整 Acceptance 前不删）
- 冻结区零改动：file_parser（仅命名级自 ID 对比保留）/ 人格 / AI / 记忆 / MCP / 知识库 /
  限流 / 权限 / WebUI / repositories
- 无 Phase 8 计划；本报告为解耦工作封口
