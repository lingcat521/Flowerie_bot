# 架构决策记录（ADR）索引

> 任务书 B 部分 §44 要求：架构阶段的每个关键决策都必须有 ADR —— 记录**为什么这样做**，
> 以及**哪些方案被否决**。本目录的 ADR 是"当时为什么这么定"的权威记录；行为细节以代码与
> [验收 Dashboard](acceptance-metrics.md) 为准。

| ADR | 主题 | 对应 Gate | 状态 |
| :--- | :--- | :--- | :--- |
| [ADR-001 传输层抽象](transport-abstraction.md) | Transport 与 Core 解耦：连接/收发/重连/动作通道全部下沉 `src/transport/`；Core 零传输库依赖 | C、P、Q | 已实施 |
| [ADR-002 能力模型](capability-model.md) | 能力五态 `supported/partial/emulated/unsupported/unknown`；`unknown ≠ unsupported`；能力查询不靠猜 | G、H | 已实施 |
| [ADR-003 Adapter 边界与契约测试](adapter-boundary.md) | Adapter 层职责边界 + 12 项契约夹具（登记一行即自动获得回归保护） | D | 已实施 |
| [ADR-004 虚拟协议实验](test-protocol-experiment.md) | 发明 TestProtocolAdapter 测量新增协议成本：**PEC = 0**；8 项最小接入实验 | E、F | 已实施 |
| [ADR-005 传输契约](transport-contract.md) | 8 项 TransportContract（connect/disconnect/send/receive/request/authentication/error/reconnect）；WS 8/8、HTTP 6 + 2 N/A；契约不绑网络库（懒加载 + I/O 注入） | Q | 已实施 |
| [ADR-006 多实例](multi-instance.md) | 多实例而非单例：`InstanceRegistry` 是普通对象；每实例自己的解析器/通道/配置；**Cross-talk = 0 是测出来的**；源码禁止 `current_protocol`/`current_ws`/`global_adapter` | S | 已实施 |
| [ADR-007 资源抽象](resource-model.md) | `ResourceRef`（三种来源归一）+ `ResourceFetcher`（协议差异只在 Adapter）+ `decode_bytes`（纯解码）；**Core 不再依赖 `file_id`/`resource_id`**；顺手修掉"Milky 文件走 OneBot 端点"的串协议缺陷 | R | 已实施 |

## 配套文档

| 文档 | 内容 |
| :--- | :--- |
| [acceptance-metrics.md](acceptance-metrics.md) | **验收 Dashboard**：八项绝对门槛 + Gate A–Z 实测值 + 逐提交 CI 真实记录（红色提交也如实保留）|
| [transport-contract.md](transport-contract.md) | Gate Q 的 8 项契约与两个参考实现的逐项实测（含 N/A 理由）|

## 写一份新 ADR 的约定

1. 文件命名 `<主题>.md`（不写序号前缀，序号只在本索引与标题里维护）；
2. 开头一行写**状态 / 日期 / 对应 Gate**；
3. 必须包含三部分：**要回答的问题**、**决定了什么（含被否决的方案与原因）**、**诚实边界**（这次**没有**证明什么）；
4. 所有数字必须来自真实命令输出（测试、CI、扫描），并标注证据等级 `[CODE]/[DOC]/[FIXTURE]/[MVP]/[INFERENCE]/[UNKNOWN]`；
5. 实施中踩到的坑单独一节 —— 后人的成本主要在这里。

## 其余架构文档

- [../adapter-architecture.md](../adapter-architecture.md)：Adapter 分层架构的**当前**说明（面向接入者）；
- [../message-model.md](../message-model.md)：归一化消息模型字段与四协议映射表；
- [../protocol-gap-closure.md](../protocol-gap-closure.md)：A 部分 G1–G8 缺口封口台账（含 BLOCKED 证据）。
