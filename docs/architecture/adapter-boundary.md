# ADR-003：Adapter 边界与契约测试

- **状态**：已实施（首版）｜**日期**：2026-08-09｜**对应 Gate**：D（并为 E/F 铺路）
- **后续**：本 ADR 的"登记一行即自动获得 12 项契约保护"已由 [ADR-004](test-protocol-experiment.md) 实测验证
  （虚拟协议登记后契约从 36 项涨到 48 项，且 Core / Services / SDK / 既有插件改动数 = 0）

## 边界是什么

```
Plugin / Plugin SDK（plugin_sdk/ + src/sdk/，零协议命名）
        ↓ 只认领域对象（BotEvent / BotMessage / Capability）
Adapter 层（src/adapters/）
        ├── proto.py          契约：InternalEvent / EventParser / MessageSender
        ├── onebot_parser.py  OneBot 11 事件 → InternalEvent
        ├── milky_parser.py   Milky 事件 → InternalEvent
        ├── onebot12_parser.py OneBot 12 骨架（NOT_REAL_DEVICE_VALIDATED）
        ├── capabilities.py   能力模型 + 协议描述符（Gate G/H）
        ├── contract.py       契约夹具（本 ADR 的主角）
        ├── container.py      组合根：解析器 + 发送出口 + 描述符
        └── onebot/           OneBot 实现（DTO/Transformer/Adapter）
        ↓ 只经统一出口
Transport 层（src/transport/）：连接 / 收发 / 重连 / 动作通道（唯一读协议开关处）
        ↓
Core / Services（src/core、src/services）：不认识协议名，只处理领域字段
```

## 契约测试（Gate D）怎么做的

`src/adapters/contract.py` 定义 `AdapterUnderTest`：解析器 + 描述符 + 样本 + 源码标记。
`tests/test_adapter_contract.py` 用**同一组 12 项**对每个登记适配器各跑一遍：

| # | 契约项 | 判定方式 |
| --- | :--- | :--- |
| 1 | descriptor | id/version/transports/note/capabilities 齐备 |
| 2 | protocol identity | 原生判别字段（post_type / event_type / type）必须在 raw_data 里可追溯 |
| 3 | lifecycle | 解析器可重复使用；组合根按 protocol 选对解析器与描述符 |
| 4 | capability declaration | 18 项全覆盖 + 覆盖率 ≥95% + 状态合法 |
| 5 | message normalization | 群消息样本 → scope/group_id/actor_id/message_id/text/mentions/is_mentioned |
| 6 | event normalization | 通知样本 → kind=notice 且 notice_kind 非空 |
| 7 | send mapping | **静态探查**：源码里存在该协议的发送映射标记 |
| 8 | action mapping | **静态探查**：存在动作映射与不支持清单标记 |
| 9 | unknown segment | 未知段 type+payload 原样保留 |
| 10 | unknown event | 未知事件 kind 可见、raw 保真 |
| 11 | raw preservation | raw_data 与输入逐字段相等（消息/通知/未知事件三类样本）|
| 12 | error handling | 畸形输入（None/str/int/list/脏字段）不抛异常 |

**为什么 7/8 是静态探查**：真正的"发出去并被收到"需要实机（缺口台账 G5/G6，当前 BLOCKED）。
静态探查只能证明"映射存在"，这一点在契约里写清楚，不冒充实机验证。

## 被否决的方案

- **为两个适配器各写一套测试**：会随协议数量线性膨胀，且新增协议时容易漏测；
  契约夹具把"新协议"变成"加一条登记"，12 项自动生效（与 Gate E 的 PEC=0 配套）。
- **把契约测试写成端到端（起真实 WS/HTTP）**：本机与 CI 都没有客户端，会退化成 mock 互测，
  价值低于"契约 + 实机联调"两段式。

## 本轮由契约测试抓出的真实缺陷（值得记录）

| 缺陷 | 触发 | 修复 |
| :--- | :--- | :--- |
| 三个解析器对**非 dict 输入**（字符串/数字）抛 `ValueError: dictionary update sequence` | 契约第 12 项 | 新增共享 `proto.as_event_dict()`，三个解析器统一使用 |
| Milky 段数组里混入 `None`/数字时 `dict(None)` 抛 `TypeError` | 契约第 12 项 | 只保留 dict 元素 |
| Milky 对脏 `peer_id`/`sender_id`（如 `"abc"`）`int()` 抛 `ValueError` | 契约第 12 项 | 新增共享 `proto.to_int()` + `_int_or()`，18 处转换全部替换（残留裸 `int()` = 0）|
| 契约测试里的假 sender 手写不全（漏 24 个方法） | 契约第 3 项 | 改为**从 MessageSender 反射自动补齐**，契约演进时自动覆盖 |

> 这一节是"契约测试值不值"的最好回答：三个解析器的崩溃点都是**先有契约才发现**的。
