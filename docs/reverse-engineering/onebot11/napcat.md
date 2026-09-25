# NapCat 逆向（OneBot 11 客户端档案）

> 任务书 `/storage/emulated/0/协议.txt` §三/§七/§八/§十三/§二十三。
> 归一化侧结论见 [../../message-model.md](../../message-model.md)；逐格矩阵见
> [../../client-compatibility.md](../../client-compatibility.md) §4 与 §4.2。

## Source

| 项 | 值 |
| :--- | :--- |
| 仓库 | `NapNeko/NapCatQQ`（本地 `~/proto_src/NapCatQQ`）|
| 版本 | `0b4cfe6`（浅克隆 HEAD，2026-09-25 取）|
| 语言 / 规模 | TypeScript / 1020 文件 |
| 关键源码 | `packages/napcat-onebot/api/msg.ts`（消息事件构造与段转换）、
`packages/napcat-onebot/types/message.ts`（**段与事件的 TypeBox schema**，字段级事实）、
`packages/napcat-onebot/action/OneBotAction.ts`（响应包封）、
`packages/napcat-onebot/action/msg/SendMsg.ts`（发送侧元素分组，见 §3.3 与 C1 更正）|
| 实机抓包 | **无**（本环境没有协议端）→ 全部为 `[CODE]`，fixture 标 `captured: false` |

## Version

- 本轮核对：`0b4cfe6`。此前的元素模型/合并转发结论来自同一份源码（client-compatibility.md §1-§3）。

## Evidence

`[CODE]` 源码逐行；`[DOC]` OneBot 11 规范；`[MVP]` 本仓库实现。
下面每条结论都带 `文件:行`，可复核。

## Observed Behavior

### 1. 消息事件字段（`api/msg.ts L1115-1176` + `types/message.ts L374-410`）

```text
initializeMessage()：self_id / user_id / time / message_id=message_seq=real_id=msg.id /
  real_seq=msg.msgSeq / message_type / sender{user_id,nickname,card} / raw_message='' /
  font=14 / sub_type='friend' / message=[] / message_format='array' /
  post_type = (self_id==sender) ? 'message_sent' : 'message'
handleGroupMessage()  ：sub_type='normal'、group_id=parseInt(peerUin)、group_name、sender.role/nickname
handlePrivateMessage()：sub_type='friend'、sender.nickname（好友资料）
handleTempGroupMessage()：sub_type='group'、**顶层 group_id = 来源群**、temp_source=0、
  nickname 兜底 '临时会话'（失败分支硬编码 group_id=284840486 —— [CODE] 里的兜底常量，实机未验证）
```

要点（与 go-cqhttp 相对，见 Known Differences）：

- **`font` 硬编码 14**（go-cqhttp 是 0）；`message_id = message_seq = real_id`，真实序列另给 `real_seq`（字符串）；
- `sender` 恒有 `user_id/nickname/card`；群消息才有 `role`；**不写** `sex/age/area/level`（go-cqhttp 会写死 `sex:"unknown"/age:0`）；
- 自发送 → `post_type='message_sent'`（另有 `message_sent_type` 字段）；
- 扩展字段：`group_name`、`message_format`、`emoji_likes_list`、`raw`、`target_id`。

### 2. 段 schema（`types/message.ts L3-27 枚举 + L30-340 各 schema`）

| 段 | NapCat 字段 [CODE] | 备注 |
| :--- | :--- | :--- |
| `text` | `{text}` | |
| `face` | `{id, resultId?, chainCount?}` | 连击/结果 id 是 NapCat 扩展 |
| `mface` | `{emoji_package_id, emoji_id, key, summary}` | **go-cqhttp 没有这个段**（降级 text） |
| `at` | `{qq, name?}` | |
| `reply` | `{id?, seq?}`，**seq 优先** | go-cqhttp 用 `id`（DB global id） |
| `image` | FileBase + `{summary?, sub_type?}` | **`sub_type` 下划线**（go-cqhttp 是 `subType`）|
| `record`/`video`/`file` | FileBase `{file, path?, url?, name?, thumb?}` | 与 go-cqhttp 的 file 段字段集不同 |
| `music` | id 版 `{type,id}`；自定义版 `{type,url,audio?,title?,image,content?}` | 自定义音频字段是 `audio`（go-cqhttp 读 `voice`）|
| `poke` | `{type, id}` | go-cqhttp 是 `qq` |
| `dice`/`rps` | `{result}` | **go-cqhttp 是 `value`** |
| `json` | `{data: string\|object, config?: {token}}` | `data` 允许**对象**；go-cqhttp 只当字符串 |
| `xml` | `{data}` | 无 resid |
| `markdown` / `miniapp` / `contact` / `location` / `onlinefile` / `flashtransfer` | 各自的 schema | **go-cqhttp 全都没有** |
| `node` / `forward` | 节点（发）/ 转发（收） | |

### 3. 发送请求与响应

- 发送 schema（`types/message.ts L347-367 OB11PostSendMsgSchema`）：`message` **或** `messages`（数组/字符串/单对象）、
  `user_id`/`group_id` 是**字符串**、`auto_escape` 是 Boolean **或** String、转发节点用 `news/summary/prompt/source/time`；
- 响应包封（`action/OneBotAction.ts L20-41`）：`createResponse(data, status, retcode, message, echo)`；
  成功 `status:'ok'`+`retcode:0`，失败 `status:'failed'`（与 go-cqhttp 同构，但**没有** `wording` 字段）。

## Normalized Behavior（Flowerie 现状 [MVP]）

用本轮新增 fixture 真跑 `OneBotEventParser`：

| fixture | 归一化结果 |
| :--- | :--- |
| `private_temp_message.json` | `scene=temp` + `context_group_id=123456`（顶层 group_id）—— 与 go-cqhttp 的 `sender.group_id` **形态不同、结果相同** |
| `group_message_dice_rps_mface.json` | `dice`/`rps` 原样保留（`result` 字段）；`faces` 归一化为 `face` + `market_face` 两种 kind |
| `group_message_new_segments.json` | `markdown.content` **并入 `text`**；`miniapp/contact/location` 原样保留在段数组（未建语义字段）|
| `message_sent_self.json` | **本轮修复**：`kind` 保留 `message_sent`，内容（text/段）现在照常解析 |

**本轮修掉的真缺口**：`post_type="message_sent"`（机器人自己发的消息）此前只解析出 kind，**内容整段丢失**
（`_fill_message` 只在 `kind=="message"` 时调用）。NapCat（`api/msg.ts L1136`）与
go-cqhttp（`event.go L84-87` / `converter.go L70-73`）都发这个 post_type，所以两边都受影响。
现在：kind 原样保留（`message_router` 只把 `"message"` 送进回复链路，不会自问自答），内容照常归一化。

## Known Differences（跨客户端）

| 维度 | NapCat [CODE] | go-cqhttp [CODE] | 归一化/序列化影响 |
| :--- | :--- | :--- | :--- |
| 临时会话来源群 | **顶层 `group_id`** + `temp_source` | **`sender.group_id`** + `temp_source` | 两种形态都要认（已修 + 等价性测试）|
| `font` | 14 | 0 | 不能当常量判断 |
| `message_id` / `message_seq` / `real_id` | 三者相同；`real_seq` 另给 | `message_id`=DB id，`message_seq`=客户端 seq | **同名不同义**：不能跨客户端假设 id 语义 |
| `dice`/`rps` 取值字段 | `result` | `value` | 序列化按档案取字段；未知则原样传 |
| `reply` | `{id?, seq?}`（seq 优先） | `{id}`=客户端 DB global id | 回复引用不能跨客户端复用 id |
| image 子类型 | `sub_type` | `subType` | 字段名大小写不同，解析按段原样保留 |
| 商城表情 | `mface` 段 | 无（降级 `text`） | 归一化两种都要收 |
| 扩展段 | markdown/miniapp/contact/location/onlinefile/flashtransfer | 无 | 只有声明过能力的客户端才可能收到 |
| 失败响应字段 | `status/retcode/message` | 另有 `msg/wording` | 解析只依赖 status/retcode，其余进日志 |

## Unknowns

1. `handleTempGroupMessage` 失败分支硬编码 `group_id=284840486` 的真实含义（源码里的兜底常量，**未实机验证**）；
2. `message_sent_type` 的取值集合（schema 只写 `Type.Optional(Type.String())`）；
3. `onlinefile` / `flashtransfer` 段的字段与语义（只看到枚举名，未展开 schema）；
4. `emoji_likes_list` 的触发条件与字段来源；
5. 实机抓包（§十九）：**BLOCKED BY EXTERNAL DEPENDENCY**（需要运行中的 NapCat 实例 + 真实账号）。

## Tests

| 文件 | 覆盖 |
| :--- | :--- |
| `tests/fixtures/napcat/`（9 个）| 段（text/at/image/record/video/xml/json/mface/dice/rps/markdown/miniapp/contact/location）、
临时会话、匿名段、自发送、通知（poke/group_upload）、ARK 合并转发 |
| `tests/test_client_contract_matrix.py` | `message_sent` 内容解析（两客户端）、NapCat 顶层 `group_id` 与 go-cqhttp `sender.group_id` 等价、`dice/rps{result}` 原样保留 |
| `tests/test_fixtures_corpus.py` | 溯源契约 + 归一化断言（含既有 NapCat 用例）|

> 新增 fixture 一律带 `_provenance{client,status,captured:false,evidence,note,version}`，
> `evidence` 精确到文件与行号；没有证据的字段不写进 fixture。
