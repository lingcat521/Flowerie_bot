# go-cqhttp 逆向（OneBot 11 客户端档案）

> 任务书：`/storage/emulated/0/协议.txt` §三/§七/§八/§十三/§十四/§十六/§二十三。
> 本文件是 **go-cqhttp** 这一列的客户端级事实档案；归一化侧结论见 [../../message-model.md](../../message-model.md)。

## Source

| 项 | 值 |
| :--- | :--- |
| 仓库 | `Mrs4s/go-cqhttp`（本地 `~/proto_src/go-cqhttp`）|
| 版本 | `a5923f1`（浅克隆 HEAD，2026-09-25 取）|
| 工程状态 | 仓库已归档（README 声明停止维护），但**是很多实现的字段基线**，仍必须覆盖 |
| 语言 / 规模 | Go / 121 文件（含 `docs/` 内置 API 文档）|
| 关键源码 | `coolq/cqcode.go`（段→CQ/数组）、`coolq/converter.go`（群消息字段）、`coolq/event.go`（事件编码/上报）、`coolq/api.go`（Action 与响应包封）、`pkg/onebot/supported.go`（Action 支持清单）、`internal/msg/element.go`（CQ 转义与中间表示）|
| 实机抓包 | **无**（本环境无协议端）→ 本文件所有结论为 `[CODE]`，fixture 标 `captured: false` |

## Evidence（证据等级）

- `[CODE]`：逐行取自上述源码（每条结论后附文件:行）。
- `[DOC]`：仓库内置文档 / OneBot 11 规范。
- 无任何 `[INFERENCE]` 被当作兼容性结论；标记为 UNKNOWN 的一律不写进矩阵的能力格。

## Observed Behavior（客户端实际行为）

### 1. 上报格式是**可配置**的（同一客户端两种 wire 形态）

`coolq/event.go L24-31`：`base.PostFormat ∈ {"string","array"}` 决定 `message` 是 CQ 字符串还是段数组。
→ 归一化层必须两种都吃；fixture 里两种都要有（本目录先用 array）。

### 2. 消息段构造（`coolq/cqcode.go L62-280 toElements()`）

| 内部元素 | 段 type | data 字段（**类型按源码**）| 行号 |
| :--- | :--- | :--- | :--- |
| ReplyElement | `reply` | `id`（字符串数字）；`ExtraReplyData=true` 时**额外** `seq/qq/time/text` | L78-95 |
| TextElement | `text` | `text` | L99-104 |
| LightAppElement | `json` | `data`（原始字符串）| L105-110 |
| AtElement | `at` | `qq`；Target==0 时是**字符串 `"all"`** | L111-119 |
| RedBagElement | `redbag` | `title`（**非规范段**，见 Known Differences）| L120-126 |
| ForwardElement | `forward` | `id`（resid）| L127-133 |
| FaceElement | `face` | `id` | L134-140 |
| VoiceElement | `record` | `file`, `url`（**无 name/path**）| L141-148 |
| ShortVideoElement | `video` | `file`, `url`（**无 name**）| L149-156 |
| GroupImageElement | `image` | `file`=`md5+".image"`, `subType`, `url`；闪照加 `type:"flash"`；特效加 `type:"show"`+`id` | L157-181 |
| FriendImage/GuildImage | `image` | `file`, `url`（+闪照 `type`）| L182-200 |
| DiceElement | `dice` | `value` | L205-211 |
| FingerGuessingElement | `rps` | `value` | L212-218 |
| MarketFaceElement | **`text`** | `text`=表情名（**降级，不是 mface**）| L226-233 |
| ServiceElement | `xml` **或** `json` | `data`+`resid`；内容不含 `"<?xml"` 时**只把 type 改成 json，resid 仍留在 data 里** | L235-246 |
| AnimatedSticker | `face` | `id` + `type:"sticker"`（扩展）| L219-225 |
| GroupFileElement | `file` | `path`, `name`, `size`（**字符串**）, `busid`（**字符串**）| L248-258 |
| LocalImage | `image` | `file`, `url` | L259-273 |

**两个配置会改变 wire 形态**（`coolq/cqcode.go L89-95` / `L108-112`）：
`ExtraReplyData` 让 `reply` 多出 4 个字段；`RemoveReplyAt` 会**删掉** reply 后面紧跟的同人 `at` 段。

### 3. 事件字段（逐字取自源码）

**群消息**（`coolq/converter.go L62-125`）：
`anonymous:null`（显式 null）、`font:0`、`group_id`（int）、`message_seq`（**客户端原始 seq**）、
`raw_message`、`user_id`、`message_id`（**数据库 global id**，与 message_seq 不同命名空间）、
`sender{age:0, area:"", level:"", sex:"unknown", user_id, role, nickname, card, title}`。
匿名时：`sub_type:"anonymous"`、`anonymous{flag:"<id>|<nick>", id, name}`、`sender.nickname="匿名消息"`，
且 **sender 不再有 role/card/title**。

**好友私聊**（`coolq/event.go L88-99`）：`message_id`（数据库 id）、`user_id`、`target_id`（自身）、
`message`、`raw_message`、`font:0`、`sender{user_id,nickname,sex:"unknown",age:0}`。

**群临时会话**（`coolq/event.go L136-172`）：`sub_type:"group"`、**`temp_source`**、
`message_id`（**直接用客户端 seq，未入库** —— 与好友私聊不一致）、`sender{user_id, group_id, nickname, sex:"unknown", age:0}`。
来源群放在 **`sender.group_id`**，顶层没有 `group_id`。

**群文件上传通知**（`coolq/event.go L112-124`）：`notice/group_upload`，`file{id:path, name, size:int, busid:int, url}`。

**事件编码**（`coolq/event.go L42-73`）：手写 `fmt.Fprintf`，字段顺序固定为
`post_type → <detail>_type → time → self_id → [sub_type] → 其余`；`time`/`self_id` 是数字。

### 4. Action 与响应

- 支持清单：`pkg/onebot/supported.go L5-91` **86 个 Action**（含 guild 系列、`_get_group_notice`、
  `.ocr_image`、`get_supported_actions` —— 最后一个意味着**可以运行时问客户端支持什么**）。
- 响应包封：`coolq/api.go L2141-2143 OK()` → `{"data":…,"retcode":0,"status":"ok","message":""}`；
  `L2146-2155 Failed()` → `{"data":null,"retcode":code,"msg":…,"wording":…,"message":<wording>,"status":"failed"}`
  （**三个消息字段同时出现**）。
- `get_msg`（`L1676-1706`）：`message_id`(int) / `message_id_v2`(string，DB 内部 id，`GetID() string`) /
  `real_id` = `message_seq` = 客户端 seq / `group`(bool) / `sender{user_id,nickname}` / `time`。

## Observed Behavior · 发送侧（Flowerie → Client，任务书 §十四 的第二个方向）

来源：`coolq/cqcode.go L404-1010`（`ConvertStringMessage` / `ConvertObjectMessage` /
`ConvertElements` / `ConvertElement` / `convertV11` / `reply` / `voice` / `at` /
`makeImageOrVideoElem`）与 `coolq/api.go L738`（`CQSendGroupMessage`）。

### 1. 入参形态与兜底

- `message` 既可以是 **CQ 字符串**也可以是**段数组**（`ConvertObjectMessage` L411-417）；
- 段数组里的未知类型 → `ConvertElement` 落到 `default: unsupported message type` →
  `ConvertElements` L434-466 在 `IgnoreInvalidCQCode=false`（默认）时**把该段发成字面 CQ 文本**并记 warning；
- `reply` 被**提到消息最前**，且一条消息**只接受一个** reply（第二个只记 warning 丢弃）。

### 2. 各段的发送侧字段（case 表 L608-880）

| 段 | 读取的字段 | 备注（含扩展）|
| :--- | :--- | :--- |
| `text` | `text` | `SplitURL` 打开时 URL 会被拆成多个 text 段 |
| `at` | `qq`（缺失回退 `target`）、`name` | `qq=="all"` → AtAll |
| `image` | `file`、`type` ∈ {`flash`, `show`}、`id`、`subType`、`c`、`cache` | `file` 支持 http / file:// / base64:// / base16384:// / hex / 裸路径 |
| `record` | `file`（+`cache`）| 自动转 SILK/AMR；**发送侧没有 url** |
| `video` | `file`、`cover`、`cache` | 无 ftyp 头会自动转码 |
| `file` | `path`、`name`、`size`、`busid` | 与上报侧同构 → **可往返** |
| `reply` | `id`（数字）或 `text`+`user_id/qq`（+`time/seq`）| `id` 走客户端自己的 DB（global id），需先收过那条消息 |
| `face` | `id`；`type=="sticker"` → 动画表情 | |
| `poke` | `qq` | go-cqhttp 自有段（规范没有）|
| `dice` / `rps` | `value` | 越界（dice>6 / rps>2）→ 报错 |
| `xml` / `json` | `data`、`resid` | `resid` 会被 `ParseInt` |
| `share` / `music` | `url/title/content/image` / `type+id`（`qq/163/custom`）| `custom` 会自造 XML |
| `cardimage` | `source/icon/brief/minwidth/maxwidth/minheight/maxheight` + image | **发送专用扩展段**（上报侧没有）|
| `forward` | `id` | 只能按 id 下载已存在的转发；空 id/过期 → 报错（**不能自造节点**）|

### 3. 由此得到的跨客户端差异（已写进 client_profile.go-cqhttp.quirks）

- `record` / `video`：**上报有 `url`、发送只读 `file`** —— 同一个段在两个方向字段不同，
  归一化层不能假设"收到的形状能原样发回去"；
- `reply.id`：go-cqhttp 是**客户端 DB global id**，而 `message_seq`（上报字段）是客户端 seq ——
  拿上报的 `message_seq` 去当 `reply.id` 会引用错消息；
- `file` 段：go-cqhttp 用 `path`，NapCat 用 `file_id` 命名空间 → **不能跨客户端复用**；
- `poke` 段：go-cqhttp `qq` / NapCat `{type,id}` / LLBot `shake` —— 三家三种写法；
- 未知段的兜底由**客户端**决定（go-cqhttp 变字面 CQ 文本），我们只标记不复刻。

## Normalized Behavior · 出站（本轮新增）

`src/adapters/onebot_serializer.py` + `src/adapters/client_profile.py` 把上面这张表变成可执行规则：
档案里**有证据**的字段才保留，其余字段移除并记 note（`dropped_field`）；
档案未验证的段原样传递并记 note（`unknown_segment_passthrough` / `segment_unsupported_by_profile`）。
测试：`tests/test_onebot_serializer.py`（6 条单元 + 8 条 fixture 往返）。
**尚未接入发送热路径**（需要 profile 配置开关 + CI 验证，下一轮）—— `Sender.send_msg_raw()` 行为不变。

## Normalized Behavior（Flowerie 现状 [MVP]）

用本目录 fixture 真跑 `OneBotEventParser` 的结果（2026-09-25）：

| fixture | 归一化结果 |
| :--- | :--- |
| group_message_media_array | `records` / `videos` / `images` / `image_files` 都命中；段里的 `url`、`subType`、`type:flash` 原样保留；`dice` / `rps` 作为段原样保留 |
| group_message_file_segment | `files` 命中，`path/name/size/busid` 原样保留 |
| group_message_service_xml / _json | `xmls` 命中；json 形态按 json 段保留（含 resid）|
| group_message_marketface_as_text | 就是 `text` 段（客户端已降级，归一化无需特殊处理）|
| group_message_anonymous | `text` 命中；`anonymous` 块与 `sub_type` **只保留在 `raw_data`**（未提升为语义字段）|
| private_temp_message | `scene="temp"` ✓；`context_group_id` **本轮修复**（见下）|
| notice_group_upload | `notice_kind="group_upload"` + `notice_file{id,name,size,busid,url,resource}` ✓ |

**本轮修掉的真缺口（跨客户端差异）**：go-cqhttp 的临时会话来源群在 `sender.group_id`（顶层没有），
而归一化层原先只认顶层 —— 结果 `context_group_id=None`，上下文群丢失。
修复：`src/adapters/onebot_parser.py` 在 `scene=="temp"` 时先看顶层、再看 `sender.group_id`（有则记，无则留空，不推断）。
测试：`tests/test_temp_scene.py::test_onebot_gocqhttp_temp_uses_sender_group_id` 与
`::test_gocqhttp_fixture_matches_top_level_shape`（两种客户端形态必须归一到同一结果）。

## Known Differences（与其他客户端 / 规范）

| 维度 | go-cqhttp | NapCat [CODE，见 client-compatibility.md §3] | 归一化影响 |
| :--- | :--- | :--- | :--- |
| 商城表情 | 降级成 `text`（表情名）| `mface` 段（含 emoji_id/package_id 等）| 归一化层必须同时接受"text 里就是表情名"与"mface 段"两种，不能假设 mface 一定存在 |
| `record` | `{file,url}` | `{file,path,name}` | 语音"本地路径/文件名/下载 url"三家各不相同 → 只用共同子集（file/url）做语义，其余留原始 |
| `xml` | `{data,resid}` | `{data}` | resid 是 go-cqhttp 扩展，不能作为跨客户端必需字段 |
| `json` | `{data[,resid]}` | `{data,config}` | 同上：卡片判定要靠 `data` 内的 app 字段，不靠外层扩展键 |
| 群文件段 | `file{path,name,size*,busid*}`（size/busid 是字符串）| 文件段用 `file_id` 命名空间 | 归一化层 `files` 保留全字段；语义只取 name/size |
| `message_id` | 群/好友=DB global id，临时会话=客户端 seq，另有 `message_seq` | 直接用客户端 msgId | **同名不同义**：不得假设 `message_id` 全局同源 |
| `sender` 降级字段 | `sex="unknown"`、`age=0`、`area=""`、`level=""`、`title` 可能为空 | 未必降级 | 这些字段不能当"真实资料"用 |
| 响应包封 | `msg`+`wording`+`message` 三字段，`retcode`+`status` | 同类包封但字段更少 | 解析只依赖 `retcode`/`status`，`msg`/`wording` 仅作日志 |
| 段/通知的 file.size | 段里是 **string**、通知里是 **int** | —— | 解析层必须容错两种类型（当前归一化保留原值，不做强制转换）|

## Unknowns（明确未验证）

1. `ExtraReplyData` / `RemoveReplyAt` / `PostFormat` 三配置在真实部署里的默认组合（源码只给了开关，没有"默认值"证据）→ 两种形态都出 fixture，不猜默认。
2. `message_id_v2` 的具体形态（源码只显示 `GetID() string`；DB 后端有 leveldb/mongodb/sqlite3 三种实现）→ fixture 里标为示例值。
3. `MarketFaceElement.Name` 的确切文案（源码取名字段，未枚举取值）→ fixture 用占位文案并标注。
4. 归档后是否仍有大规模部署（影响"要不要长期兼容"的判断）→ 无数据。
5. 实机抓包（§十九）：**BLOCKED BY EXTERNAL DEPENDENCY**（需要运行中的 go-cqhttp 实例；本环境没有）。

## Tests（本客户端）

| 文件 | 覆盖 |
| :--- | :--- |
| `tests/fixtures/go-cqhttp/`（10 个）| 段（媒体/文件/xml/json/表情降级）、群消息字段、匿名、临时会话、群文件通知、`get_msg` 成功/失败响应包封 |
| `tests/test_temp_scene.py` | `sender.group_id` 形态与顶层形态等价（2 条新增）|
| `tests/fixtures/go-cqhttp/actions/`（2 个）| `get_msg` 成功包封、`Failed` 失败包封（三字段 msg/wording/message）|
| `tests/test_onebot_response_contract.py` | 响应模型矩阵（ok / async / failed / status 缺省 / 畸形组合 / 非对象），驱动生产代码 `src/transport/onebot_response.py` |

**响应模型的跨客户端结论**：`[DOC]` 规范定义了第三种状态 `async`（`retcode=1`，已受理、成败未知、`data` 恒 null），
而通道原先只认 `status=="ok"` —— 会把 `async` 误判成失败。本轮把响应解析抽成纯函数
`src/transport/onebot_response.py`（HTTP/WS 共用），`async` 如实标 `async=True`，
`status="ok"` 却给非 0 `retcode` 的畸形组合按失败处理（没有证据时**不声称成功**）。

> 每个 fixture 都带 `_provenance{client,version,source,evidence,captured:false}`，`source` 精确到文件与行号。
> 契约测试（Parse/Normalize/Serialize/Action/Response/Unknown×3）在多客户端矩阵测试里统一驱动，见
> [../../client-compatibility.md](../../client-compatibility.md) §4。
