# Lagrange.Milky 逆向（协议作者本人的实现，内嵌）

> 任务书 ~/storage/emulated/0/协议.txt §四/§十/§二十三。规范基线见 [../../milky-protocol.md](../../milky-protocol.md)；
> 既有的段/事件对照见 [../../protocol-reverse-engineering.md](../../protocol-reverse-engineering.md) §6。

## Source

| 项 | 值 |
| :--- | :--- |
| 仓库 | `LagrangeDev/Lagrange.Core` `20c2ba0` 与 `LagrangeDev/LagrangeV2` `7011cdf`（**同一份实现的两次快照**）|
| 位置 | 两份仓库各自内嵌 `Lagrange.Milky/`（**不是**独立仓库；`LagrangeDev/Lagrange.OneBot` 已 404，与本实现无关）|
| 语言 / 规模 | C# / 119 个 .cs |
| 关键源码 | `Api/Handlers/Message/SendGroupMessageHandler.cs`（发送入口与响应字段）、
`Api/Handlers/{Group,Friend,File,System}/`（Action 面）、`Models/Segments/` 与
`Entity/Segment/`（**两份副本段集合不同**）、`Events/`、`Converters/`（段↔内部元素）|
| 实机抓包 | **无** → 全部 `[CODE]` |

## Version

- Core 副本 `20c2ba0`：`Models/Segments/` 11 个文件（Text/Mention/MentionAll/Image/Record/Video/File/Forward/Reply/LightApp + SegmentBase）
  —— **没有** Face / MarketFace / Xml；
- V2 副本 `7011cdf`：`Entity/Segment/` 15 个文件（多出 FaceSegment / MarketFaceSegment / XmlSegment / ISegment）。
- **两份布局不能混用**（此前已在 protocol-reverse-engineering.md C2 记录过这一点，本文件沿用）。

## Evidence

`[CODE]` 源码逐行；`[DOC]` Milky 规范（SaltifyDev/milky `151dd90`）。
两者在出站段集合上**互相印证**：规范 `OutgoingSegment` 联合体与这里的 `OutgoingSegmentBase` 子类一一对应。

## Observed Behavior

### 1. 发送入口与响应（`Api/Handlers/Message/SendGroupMessageHandler.cs`）

```csharp
[ApiHandler("send_group_message")]
public sealed class SendGroupMessageHandler(BotContext lagrange, MilkyConverter converter) ...
    var chain = await _converter.FromOutgoingSegmentsAsync(request.Message, MessageType.Group, request.GroupId, ct);
    var message = await _lagrange.SendGroupMessage(request.GroupId, chain).WaitAsync(ct);
    return new MilkyApiResponse<Result>(new Result {
        MessageSeq = (long)message.Sequence,
        Time = message.Time,
    });
// Result: { "message_seq": long, "time": long }
```

要点：端点名 `send_group_message`（Flowerie 的 `_MILKY_ACTIONS` 映射正是 `send_group_msg → send_group_message`）；
**响应有两个字段**（`message_seq` + `time`）—— Flowerie 目前只取 `message_seq`（够用，但 `time` 是已知可用字段）。

### 2. 段集合（两份副本的差异见 Version）

- 出站段基类 `OutgoingSegmentBase`：与规范 `OutgoingSegment` 的 10 种一一对应；
- V2 副本另有 `FaceSegment` / `MarketFaceSegment` / `XmlSegment`（Core 副本没有）；
- 段转换集中在 `Converters/`（`MilkyConverter.FromOutgoingSegmentsAsync`），不是散落在 handler 里。

### 3. Action 面（`Api/Handlers/` 目录）

`Group/`（含 `SendGroupNudgeHandler` / `SendGroupMessageReactionHandler`）、`Friend/`（含 `SendFriendNudgeHandler`）、
`File/`（上传/删除/重命名/移动/取下载链接）、`System/` —— 每个 action 一个 handler 类，由 `ApiHandlerAttribute` 登记。

## Normalized Behavior（Flowerie 现状 [MVP]）

- 入站：Milky 事件/段归一化见 [../../milky-protocol.md](../../milky-protocol.md) 与 `src/adapters/milky_parser.py`（G1-G4 已 CLOSED）；
- 出站：本轮新增 `src/adapters/milky_serializer.py`（按规范出站联合体），档案 `LAGRANGE_MILKY`；
- 响应：`src/transport/milky_response.py` 解析 `{status, retcode, data|message}`。

## Known Differences

| 维度 | Lagrange.Milky [CODE] | LLBot 的 Milky [CODE] | 影响 |
| :--- | :--- | :--- | :--- |
| 段集合 | Core 副本无 Face/MarketFace/Xml；V2 副本有 | 有 market_face/xml/markdown（入站）| 不能假设"Milky 客户端都支持同一批段" |
| mention 私聊 | 未核对 | **私聊不产出元素**（outgoing.ts 的 `&& isGroup`）| 出站序列化器按档案处理（`mention_group_only`）|
| 发送响应 | `{message_seq, time}` | 未核对（common/api.ts 只给包封）| 只依赖 `message_seq` 是安全子集 |

## Unknowns

1. Core 副本缺 Face/MarketFace/Xml 是**版本差异**还是**有意裁剪**（两份快照时间不同，未查提交历史）；
2. `MessageType.Group` 之外的发送路径（私聊/临时会话）的响应字段是否相同；
3. Action 全集（`Api/Handlers/` 下 handler 数量 vs 规范 API 清单）未逐条比对；
4. 实机抓包：**BLOCKED BY EXTERNAL DEPENDENCY**。

## Tests

| 文件 | 覆盖 |
| :--- | :--- |
| `tests/test_milky_serializer.py` | 出站段形状（对照规范联合体）、LLBot 客户端规则、入站→出站往返（不许静默消失）、响应包封 |
| `tests/fixtures/milky/`（9 个事件 + `actions/` 2 个响应）| 入站段/事件/临时会话/请求类 + 响应包封，全部带 provenance |
| `tests/test_milky_*.py`（既有）| G1-G4 的入站归一化（未改动，保持 CLOSED）|
