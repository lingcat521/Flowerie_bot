# 协议逆向工作记录（Protocol Reverse Engineering）

> 任务书 §22 交付物①，同时作为**跨会话可复用的工作记忆**：所有已逆向事实、文件路径、行号、
> 待办与恢复步骤都记在这里，避免依赖对话上下文。
>
> 证据等级：`[CODE]` 源码 / `[DOC]` 文档 / `[FIXTURE]` 真实事件 / `[MVP]` 本地 MVP / `[INFERENCE]` 推断 / `[UNKNOWN]` 无证据。

## 0. 复现环境（本地源码位置）

源码区在工作区之外：`~/proto_src/`（361M，2026-09-25 获取，均为 `git clone --depth 1`）。

| 项目 | 路径 | HEAD | 状态 |
| :--- | :--- | :--- | :--- |
| NapCatQQ | `~/proto_src/NapCatQQ` | `0b4cfe6` | SOURCE_OBTAINED |
| SnowLuma | `~/proto_src/SnowLuma` | `fe245d8` | SOURCE_OBTAINED（未调查） |
| Lagrange.Core | `~/proto_src/Lagrange.Core` | `20c2ba0` | SOURCE_OBTAINED（未调查） |
| LagrangeV2 | `~/proto_src/LagrangeV2` | `7011cdf` | SOURCE_OBTAINED（未调查） |
| LLBot | `~/proto_src/LLBot` | `9f374f6` | SOURCE_OBTAINED（**调查中**） |
| NoneBot2 | `~/proto_src/NoneBot2` | `4510ce2` | SOURCE_OBTAINED（未调查） |
| adapter-onebot | `~/proto_src/adapter-onebot` | `58bb487` | SOURCE_OBTAINED（未调查） |
| OneBot11 规范 | `~/proto_src/OneBot11-spec` | `d4456ee` | SOURCE_OBTAINED（未调查） |
| Milky 规范 | `~/proto_src/Milky-spec` | `151dd90` | SOURCE_OBTAINED |
| Lagrange.Milky（实现） | — | — | **AUTH_REQUIRED / 仓库不存在**（只有 .Document） |

## 1. 本地 MVP 事实清单 [MVP]

文件：`/storage/emulated/0/bot.py`（1797 行，UTF-8，可读）。

| 主题 | 事实 | 行号 |
| :--- | :--- | :--- |
| 连接 | 反向 WS 服务端（`websockets.serve`），无鉴权、无 ack | L1747-1786 |
| 发送 | HTTP `POST {HTTP_API_BASE}/send_group_msg`，`message` 为**纯字符串**；成功 = HTTP 200 且 `retcode==0` | L691-740 |
| 事件入口 | `_process_event`：`post_type=message` → `_handle_message`；`notice/group_upload` → 缓存待取文件；`notice/notify/poke` → `_handle_poke` | L1258-1278 |
| 消息模型 | `data.message` 为**段数组**；text→文本、at→`data.qq`、reply→`data.qq` 判是否回机器人 | L787-813 |
| **poke** | 字段回退链：`target_id → target → to_user_id → user_id`；只在 `target==bot` 时回复 | L1213-1256 |
| 文件（notice） | `group_upload` → `data.file{name,id,size,busid}`；再 `GET /get_file?file_id=` → **`{retcode:0,data:{base64}}`** | L815-829, L931-969 |
| 文件（消息段） | 段 `type=file`，`data.url` + `data.file`（名）；`/` 开头则拼 `HTTP_API_BASE`；同一 base64 信封 | L971-1014 |
| 合并转发 | 段 `type=forward`：优先 `data.messages`（内联），否则 `data.id` → `GET /get_forward_msg?message_id=`；文本**递归**收集任意 `{text:str}`，sender 取 `sender.user_id` | L1016-1075 |
| JSON 卡片 | 段 `type=json`，原始串在 `data.data`（回退 `content`/`text`）；递归收集字符串，黑名单跳过 `url/jumpUrl/preview/icon/appid/uin/scene/token/ctime/width/height/forward/autoSize` | L1078-1128 |
| 识图 | **完全没有**（grep `image`/`vision` 零命中） | — |

## 2. Flowerie 现状 [CODE]

| 层 | 文件 | 事实 |
| :--- | :--- | :--- |
| 协议解析 | `src/adapters/onebot_parser.py`（157 行） | 段处理：`text` / `at` / `image`(url→images, file→image_files, 剥 `file://`) / `reply`(id+qq) / `forward`·`json` → **只记 `segments_summary` 元组**；其余段一律进 summary。**`file`/`face`/`mface`/`poke`/`record`/`video` 没有专门处理** |
| 事件模型 | `src/adapters/proto.py` | `InternalEvent`：`text/mentions/images/image_files/reply_id/is_reply_to_bot/has_reply_to_other/has_at_others/message_segments/segments_summary/notice_file/notice_kind/target_id/operator_id/raw_data` |
| 文件 | `src/services/file_parser.py`（416 行） | `fetch_and_parse_file(file_id,file_name)` → `GET {HTTP_API_BASE}/get_file` → `decode_napcat_file_response`（base64 → txt/pdf/docx/xlsx/csv，带流式上限）；`extract_forward_messages`（**强于 MVP**：嵌套展开 + `MAX_FORWARD_DEPTH/NODES/MESSAGES/FETCHES` 预算 + 同 id 缓存 + 收集转发内图片 URL）；`extract_json_card_content` |
| 组装 | `src/core/message_assembler.py` | `_assemble_forward`（转发文本 + 转发内图片走 Vision）、`_assemble_card`、`_assemble_pending_file`（notice 配对取文件）、`_describe_images`（**本地 `image_files` 优先，URL 兜底**） |
| poke 下游 | `src/core/message_router.py` L532-560 | `target_id → actor_id` 回退 + 白名单 + 每人冷却；与 MVP 语义一致 |
| SDK | `src/sdk/onebot/{dto,transformer,adapter}.py` | `dto.raw_message` 截断 4000；`transformer` 有 `extract_text/extract_at_list/extract_images/extract_reply_id` |

### Flowerie 明确缺口（待按证据修）

1. **`face` / `mface` / `poke` 消息段 / `onlinefile` / `markdown` 完全未建模**（只有 summary 元组，无消费者）；
2. **JSON 卡片不区分 `app`** —— NapCat 证据表明 `app=com.tencent.multimsg` 的卡片是**合并转发**，语义完全不同；
3. `segments_summary` 通道**没有消费者**（写了但没人读）；
4. 发送侧是否满足 NapCat 的「FILE/VIDEO/ARK/PTT 必须独占一条消息」规则 **未核对**。

## 3. NapCat 逆向结论 [CODE]

源码：`~/proto_src/NapCatQQ`（HEAD `0b4cfe6`）。

### 3.1 内部元素模型

文件：`packages/napcat-core/types/msg.ts` → `enum ElementType`（L45-79）：

`TEXT=1` `PIC=2` `FILE=3` `PTT=4` `VIDEO=5` `FACE=6` `REPLY=7` **`GreyTip=8`**（源码注释：小灰条，
包括**拍一拍(Poke)**、撤回提示） `WALLET=9` **`ARK=10`** **`MFACE=11`** `LIVEGIFT=12` `STRUCTLONGMSG=13`
`MARKDOWN=14` `GIPHY=15` **`MULTIFORWARD=16`** `INLINEKEYBOARD=17` `INTEXTGIFT=18` `CALENDAR=19`
`YOLOGAMERESULT=20` `AVRECORD=21` `FEED=22` `TOFURECORD=23`（注释：在线文件的 id 是这个）`ACEBUBBLE=24`
`ACTIVITY=25` `TOFU=26` `FACEBUBBLE=27` `SHARELOCATION=28` `TASKTOPMSG=29` `ONLINEFOLDER=30`
`RECOMMENDEDMSG=43` `ACTIONBAR=44`

### 3.2 OneBot 段词汇表与字段 schema

文件：`packages/napcat-onebot/types/message.ts`（482 行）。`OB11MessageDataType`：
`text image music video record file at reply json face mface markdown node forward xml poke dice rps miniapp contact location onlinefile flashtransfer`。

| 段 | 字段（逐字取自 typebox schema） |
| :--- | :--- |
| `text` | `text` |
| `face` | `id`, `resultId?`, `chainCount?`（连击数） |
| `mface` | `emoji_package_id`(Number), `emoji_id`(String), `key`(String), `summary`(String) |
| `at` | `qq`, `name?` |
| `reply` | `id?`, `seq?` |
| `poke` | `type`, `id` |
| `json` | `data`(Union), `config?` |
| `xml` | `data` |
| `markdown` | `content` |
| `miniapp` | `data`（注释：json 类） |
| `onlinefile` | `msgId`, `elementId`, `fileName`, `fileSize`, `isDir` |
| `flashtransfer` | `fileSetId`（QQ 闪传） |
| `node` | `id?`, `user_id?`, `uin?`, `nickname`, `name?`, `content`, `source?`, `news?`, `summary?`, `prompt?`, `time?` |
| `forward` | `id`, `content?`（用于上报） |
| `dice`/`rps` | `result` |
| `contact` | `type`, `id` |
| `location` | `lat`, `lon`, `title?`, `content?` |
| `image` | FileBase + `summary?`, `sub_type?` |
| `record`/`video`/`file` | FileBase |

**FileBase**（`FileBaseDataSchema` L80-86）：`file`（必填，路径/URL/`file://`）、`path?`、`url?`、`name?`、`thumb?`

### 3.3 合并转发与 JSON 卡片的真实实现（最重要）

文件：`packages/napcat-onebot/action/msg/SendMsg.ts`（514 行）

- **发送合并转发**（L324-346）：把节点转成 protobuf → `UploadForwardMsgV2(...)` 拿 **`resid`** →
  用 `ForwardMsgBuilder.fromPacketMsg(resid, ...)` 造 JSON → **以 `ElementType.ARK` 元素发送**（`arkElement.bytesData`）。
- **接收识别**（L289-297）：`element.arkElement.bytesData` 解析后，**只有 `json.app === com.tencent.multimsg`**
  才是合并转发卡片：`resid = json.meta.detail.resid`、`uuid = json.meta.detail.uniseq || json.extra.filename`，
  再用 `FetchForwardMsgRaw(resId)` 拉内层（内层 `actionCommand === MultiMsg`）。
- **发送分组规则**（L413-420）：`FILE` / `VIDEO` / `ARK` / `PTT` 会被拆成**独占一条消息**，不能与其他段混发。

→ 直接推翻两个常见假设："合并转发是一个 segment" 与 "所有 `type:json` 语义相同"。

### 3.4 其他可用入口（后续按需深入）

- 入站解析类：`packages/napcat-core/packet/message/element.ts`（742 行）里的
  `PacketMsg{Text,At,Reply,Face,MarkFace,Pic,Video,Ptt,File,LightApp,MarkDown,MultiMsg}Element`，
  每个类实现 `static parseElement(elem)`（L71/109/152/212/307/345/453/543/580/667/691/716）；
- 出站构造：`packages/napcat-core/types/element.ts` 的 `Send*Element`（L338-389）；
- 消息转换：`packages/napcat-core/packet/message/converter.ts`（173 行，`packetMsgToRaw`）；
- 事件类：`packages/napcat-onebot/event/notice/OB11*NoticeEvent.ts`（poke 是 `OB11PokeEvent.ts`）。

## 4. LLBot（Milky + OneBot 双实现）[CODE]

源码：`~/proto_src/LLBot`（HEAD `9f374f6`，`src/` 796 文件、`test/` 238 文件）。
它是**唯一同时实现 OneBot 11 与 Milky 的客户端**，也是 Milky 实现层的最佳可得证据
（Lagrange.Milky 实现仓库不可得 → 该列只能靠 LLBot 的 [CODE] + 规范 [DOC] 互证）。

### 4.1 Milky 入站映射（`src/milky/transform/message/incoming.ts`，252 行）

消息外壳（L8-56）：`message_scene` = `friend` / `group` / **`temp`（临时会话）**；字段 `peer_id`、
`message_seq`(=msgSeq)、`sender_id`(=senderUin)、`time`、`segments[]`，群消息额外带 `group` / `group_member`。

| NTQQ 元素 | Milky 段 | 字段（逐字取自源码） |
| :--- | :--- | :--- |
| `Text`（`atType=All`） | `mention_all` | `{}` |
| `Text`（`atType=One`） | `mention` | `user_id`, `name`（**@ 藏在 Text 元素里，不是独立元素**） |
| `Text` | `text` | `text` |
| `Face` | `face` | `face_id`(=faceIndex.toString()), `is_large`(faceType===3) |
| `Reply` | `reply` | `message_seq`, `sender_id`, `time`, **`segments`（内联被引消息的段数组）** |
| `Pic` | `image` | `resource_id`(fileUuid), **`temp_url`**, `width`, `height`, `summary`, `sub_type`(`sticker`/`normal`，picSubType===1→sticker) |
| `Ptt` | `record` | `resource_id`, `temp_url`, `duration` |
| `Video` | `video` | `resource_id`, `temp_url`, `width`, `height`, `duration` |
| `File` | `file` | `file_id`(fileUuid), `file_name`, `file_size` |
| `MultiForward` | `forward` | `forward_id`(resId), `title`, `preview[]`, `summary`（**从 `xmlContent` 解析 XML** 得到） |
| `MarketFace` | `market_face` | `emoji_package_id`, `emoji_id`, `key`, `summary`(=faceName), `url`（拼出 `gxh.vip.qq.com/.../raw300.gif`） |
| `Ark`（`app=com.tencent.multimsg`） | **`forward`** | `forward_id`(= `meta.detail.resid`), `title`(=detail.source), `preview[]`(=detail.news[].text), `summary` |
| `Ark`（其他 app） | **`light_app`** | `app_name`(=app), `json_payload`(=原始 bytesData) |
| `markdownElement` | `markdown` | `content` —— **短路整个循环**：只要有 markdown 元素，其它元素全部忽略（L61-69） |

转发内层结构（L244-252）：`{ message_seq, sender_name, avatar_url, time, segments[] }`。

**互证价值**：LLBot 与 NapCat 各自独立地对 Ark 做 `app === com.tencent.multimsg` 判定，
一个映射成 `forward`、一个映射成 ARK 元素 —— 说明「JSON/Ark 必须按 `app` 分流」是**客户端共识**，
不是某一家的私有行为 → Flowerie 的归一化层必须保留 `app` 这一维。

### 4.3 Milky 出站映射（`src/milky/transform/message/outgoing.ts`，131 行）[CODE]

| Milky 出站段 | 客户端处理 |
| :--- | :--- |
| `text{text}` | `SendElement.text(text)` |
| `mention{user_id}`（**仅群**） | 先 `getGroupMemberByUin` 取名 → `SendElement.at(uin, AtType.One, @名字)` |
| `mention_all`（**仅群**） | `SendElement.at(0, AtType.All, @全体成员)` |
| `face{face_id,is_large}` | `SendElement.face(+face_id, is_large ? 3 : undefined)` |
| `reply{message_seq}` | 按 seq 先查本地 store，miss 则 `getSingleMsg` 拉服务器；需要 senderUin/senderUid/msgTime/clientSeq；**若在转发内还要 rawPb** |
| `image{uri, sub_type, summary}` | `resolveMilkyUri(uri)` 下载 buffer → 写临时文件 → `SendElement.pic(...)`；`sub_type=sticker` → picSubType=1；**发送后删除临时文件** |
| `record{uri}` | 同上下载 → `SendElement.ptt` |
| `video{uri, thumb_uri}` | 下载视频（+可选缩略图）→ `SendElement.video` |
| `forward{messages[], title, preview, summary, prompt}` | 递归转换每个节点（`isInsideForward=true`）→ `SendElement.forward(nodes, ...)`；节点带 `senderUin/senderName/elements/msgSeq(自增)/msgTime` |
| `light_app{json_payload}` | `SendElement.ark(json_payload)` |

**对 Flowerie 发送侧的直接约束（P4 要用）**：

1. **媒体不是"给个 URL 就行"**：Milky 的 `uri` 必须由应用侧先下载成字节再交给客户端上传，且要写临时文件、发完即删；
2. **@ 需要群成员名片**（多一次 API 调用），且**仅在群聊可用**；
3. **逐段容错**：单个段转换失败只记日志、继续处理后面的段（不整条消息失败）；
4. `forward` 的节点需要自造 msgSeq，且**转发内的 reply 需要 rawPb**（内层引用与顶层不同）。
### 4.2 待办（LLBot 剩余部分）

- `src/milky/transform/message/outgoing.ts`（131 行）：Milky → NTQQ 的发送映射；
- `src/onebot11/action/**`：OneBot 侧段定义与 `file/GetFile.ts`、`file/GetImage.ts` 的取值方式；
- `src/ntqqapi/helper/message{Parsing,Building}.ts`（422/456 行）：更底层的 NTQQ 元素编解码；
- `src/milky/transform/event.ts`（470 行）：Milky 事件（含 poke 类通知）的映射。
### 4.4 LLBot 的 OneBot11 入站（`src/onebot11/transform/message/incoming.ts`，327 行）[CODE]

| 元素 | OneBot 段与字段（逐字） | 与 NapCat 的差异 |
| :--- | :--- | :--- |
| `picElement` | `image{file, **subType**(camelCase), url(生成), file_size}` | NapCat 是 `sub_type`（snake_case）→ **同语义不同名** |
| `videoElement` | `video{file, url \|\| file://path, path, file_size}` | NapCat 只有 FileBase（`file/path/url/name/thumb`） |
| `fileElement` | `file{file, url(file://或空), **file_id**(fileUuid), path, file_size}` | **NapCat 的 FileBase 没有 `file_id`** |
| `pttElement` | `record{file, url(生成), file_size}` | NapCat 同段名，字段更少 |
| `arkElement` | **`json{data: bytesData}`** —— OneBot 侧**不区分 app** | NapCat 同样原样透传 bytesData（分流发生在客户端内部） |
| `faceElement` | 分三路：`faceType=Poke && faceIndex=1` → **`shake{}`**；`faceIndex=Dice` → `dice{result}`；`faceIndex=RPS` → `rps{result}`；否则 → `face{id, **sub_type**(faceType)}` | NapCat 的 `face` 是 `{id, resultId?, chainCount?}` → **字段集不同** |
| `marketFaceElement` | `mface{summary, **url**(拼 gxh.vip.qq.com), emoji_id, emoji_package_id, key}` | NapCat 的 mface **没有 url** |
| `markdownElement` | （见文件 L244 起，本轮未细读） | — |

### 4.5 交叉结论：同一个用户动作，三种协议形态（最重要的一节）

**「戳一戳 / poke」在三个实现里完全不同**：

| 来源 | 形态 | 字段 |
| :--- | :--- | :--- |
| OneBot 11（MVP / Flowerie 现在处理的那个） | `notice` + `notice_type=notify` + `sub_type=poke` | `user_id`, `target_id`（MVP 回退 `target`/`to_user_id`）, `group_id` |
| NapCat | ① `notice` 的 `OB11PokeEvent`；② 消息里的 **`poke{type,id}` 段**；③ 内部 `GreyTip=8` 元素 | 段形态 `{type,id}` |
| **LLBot 的 OneBot11** | **`face` 元素 `faceType=Poke` → `shake{}` 段**（无 id、无目标！） | `{}` |
| **Milky（LLBot 实现）** | **事件** `group_nudge` / `friend_nudge` | 群：`{group_id, sender_id, **receiver_id**, display_action, display_suffix, display_action_img_url}`；友：`{user_id, is_self_send, is_self_receive, display_action, …}` |

→ 归一化层必须把「戳一戳」抽象成**一个语义事件**（谁戳谁、在哪个会话），而不是照搬某家的字段；
  尤其 LLBot 的 `shake` 段**不带目标**，只能从 `sender/受话人` 推断 → 这类信息差必须在 Adapter 里显式处理 `[CODE]`。

**「表情」有三类，且各家字段不同**：

| 类别 | NapCat | LLBot(OneBot) | LLBot(Milky) |
| :--- | :--- | :--- | :--- |
| QQ 表情 | `face{id, resultId?, chainCount?}` | `face{id, sub_type}` | `face{face_id, is_large}` |
| 商城表情 | `mface{emoji_package_id, emoji_id, key, summary}` | 同 + **`url`** | `market_face{…, url}` |
| 图片形式表情 | `image{sub_type}`（FileBase 扩展） | `image{subType}` | `image{sub_type: sticker}` |

→ 归一化层至少要能区分这三类，并把 `id`/`face_id`/`faceIndex`、`sub_type`/`subType`、`summary`/`faceName` 收敛成统一字段 `[CODE]`。
## 6. Lagrange.Milky 实现（协议作者本人实现）[CODE]

**重要更正**：Milky 的**实现**并非不可得 —— 它内嵌在 `Lagrange.Core` 与 `LagrangeV2` 仓库的
`Lagrange.Milky/` 目录里（119 个 .cs 文件），无需单独仓库。`LagrangeDev/Lagrange.Milky` 这个独立
仓库确实不存在（`ls-remote` exit 128），但结论不是「没有实现源码」，而是「实现源码在别处且已获得」。

路径：`~/proto_src/LagrangeV2/Lagrange.Milky/`（`Lagrange.Core` 里同名目录内容一致）。

### 6.1 段类型（`Entity/Segment/`，作者实现，共 15 个文件）

`TextSegment` `MentionSegment` `MentionAllSegment` `FaceSegment` `ImageSegment` `RecordSegment`
`VideoSegment` `FileSegment` `MarketFaceSegment` **`LightAppSegment`** `ForwardSegment` `ReplySegment`
`XmlSegment` + 基类 `SegmentBase` / 接口 `ISegment`

**关键结论**：

1. **没有 poke / nudge 段** —— 戳一戳在 Milky 里**只有事件**（见 6.2），不是消息段；
2. **有 `LightAppSegment`** —— 与 LLBot 的 `light_app` 对应，说明「Ark/轻应用」在 Milky 里是**独立段类型**，
   与 `ForwardSegment` 并列（而不是靠 `app` 字段在同一个 json 段里分流）；
3. **有 `XmlSegment`** —— OneBot 的 `xml` 段在 Milky 里也有对应；
4. 消息实体分 `FriendMessage` / `GroupMessage` / **`TempMessage`**（临时会话，与 LLBot 的 `temp` 场景一致）。

### 6.2 戳一戳事件（`Entity/Event/GroupNudgeEvent.cs`，全文 26 行）

```csharp
public class GroupNudgeEvent(long time, long selfId, GroupNudgeEventData data)
    : EventBase<GroupNudgeEventData>(time, selfId, "group_nudge", data) { }

public class GroupNudgeEventData(long groupID, long senderId, long receiverId,
    string displayAction, string displaySuffix, string displayActionImgUrl)
{
    [JsonPropertyName("group_id")]               public long GroupID { get; }
    [JsonPropertyName("sender_id")]              public long SenderID { get; }
    [JsonPropertyName("receiver_id")]            public long ReceiverID { get; }
    [JsonPropertyName("display_action")]         public string DisplayAction { get; }
    [JsonPropertyName("display_suffix")]         public string DisplaySuffix { get; }
    [JsonPropertyName("display_action_img_url")] public string DisplayActionImgUrl { get; }
}
```

→ 与 LLBot 的 `transformGroupNudgeEvent` **逐字段一致**（`group_id/sender_id/receiver_id/display_action/
`display_suffix/display_action_img_url`）→ 两条独立来源互证 Milky 规范 `[CODE]×2`。

### 6.3 与另外两家的对照（归一化输入）

| 维度 | Milky（作者实现） | NapCat（OneBot） | LLBot（OneBot） |
| :--- | :--- | :--- | :--- |
| 戳一戳 | **事件** `group_nudge{group_id,sender_id,receiver_id,display_*}` | `poke{type,id}` 段 + notice | `shake{}` 段（**无目标**） |
| 轻应用/卡片 | **独立段** `LightAppSegment` | `json{data,config?}`（靠 app 分流） | `json{data}` / `miniapp{data}` |
| 合并转发 | **独立段** `ForwardSegment` | ARK 元素（app=com.tencent.multimsg） | `forward` / `light_app` |
| 临时会话 | `TempMessage` 实体 | — | `message_scene=temp` |

→ 归一化层不应以「段类型名」为准，而应以**语义**为准：同一个 `LightAppSegment` 在 OneBot 侧可能表现为
  `json`、`miniapp`，甚至是「合并转发」（取决于 `app`）`[CODE]`。
## 5. 待调查清单（含第一步命令）

| 目标 | 第一步 |
| :--- | :--- |
| SnowLuma | 在 `~/proto_src/SnowLuma` 里 `git grep -n "OneBot" \| head`，找它的协议实现目录 |
| Lagrange.Core | 找 `MessageElement`/`Element` 定义（C#），定位 OneBot/Milky 转换 |
| LagrangeV2 | 同上（V2 是否内置 Milky 转换） |
| NoneBot2 + adapter-onebot | `git grep -n "raw_message\|message_type" adapter-onebot`，看它如何兼容非标准字段 |
| OneBot 11 规范 | 逐段核对 `[DOC]` 列（文件在 `~/proto_src/OneBot11-spec`） |
| Milky | 只能 `[DOC]`：`~/proto_src/Milky-spec/protocol/src/ir/api/*.ts` + `Milky-doc` |

## 6. 已提交交付物

| 提交 | 内容 |
| :--- | :--- |
| `095ac6e` | `docs/source-acquisition.md`（源码获取状态） |
| `951e666` | `docs/client-compatibility.md`（协议兼容矩阵 v1，NapCat 列 `[CODE]`） |
| 本文 | `docs/protocol-reverse-engineering.md` |

尚未产出：`message-model.md`、`adapter-architecture.md`、`mvp-analysis.md`（内容已在本文 §1/§2 里成型，可直接展开）。

## 7. 已落地的代码修复（P4 进度）

| 提交 | 层 | 内容 | 证据 | 验证 |
| :--- | :--- | :--- | :--- | :--- |
| `529e6ae` | Adapter | `InternalEvent` 新增 `faces/pokes/files/json_cards/forwards`；`onebot_parser` 归一化 `json(含 app+is_forward_card)` / `face` / `mface` / `poke` / `shake` / `file` / `forward`，且**同时保留 `segments_summary` 旧通道** | NapCat schema、LLBot 段字段、Milky 作者实现、SnowLuma codecs、NoneBot 工厂 | 本地 25 条绿 + **CI 全绿** |
| `4a6a157` | 组装 | multimsg 卡片按**合并转发**拉取内层（`app=com.tencent.multimsg` → `meta.detail.resid` → 复用 `_assemble_forward`），失败/无 resid 退回卡片文本 | NapCat SendMsg.ts L289-297、LLBot incoming.ts L210-235 | 新测试 6 条 + 本地 stub 注入真跑 6/6 |

### 尚未落地的（下一步）

1. **表情进入业务层**：`faces` 目前只落到事件上，`message_assembler` 还没把它拼进上下文（QQ 表情/商城表情对 AI 是"用户发了个表情"的语义）；
2. **发送侧约束**：NapCat 的「FILE/VIDEO/ARK/PTT 必须独占一条消息」尚未在 `reply_dispatch`/`sender` 侧核对与实现；
3. **Milky 侧适配**：`src/adapters/milky_parser.py` 还没吃到本轮新增的归一化字段（`mention` 藏在 Text、`reply` 内联段、`temp` 会话）；
4. **多段合并**：多个 json 卡片/文件段目前只取第一个（`_assemble_card` 只返回一段），需要按证据决定是否全部拼进上下文。

### 本地验证技巧（压缩后复用）

本机缺 pydantic/pydantic_settings/httpx，无法直接 import 依赖 `src.config` 的模块。
验证方法：先往 `sys.modules` 注入最小 stub（`pydantic.Field/field_validator/BaseModel`、
`pydantic_settings.BaseSettings/SettingsConfigDict`、`httpx.Timeout/Limits/AsyncClient`），再 import 真实模块，
即可在本地跑真实代码路径（脚本示例：`~/verify_multimsg.py`）。
**更好的办法（已落地）**：`~/stubplug.py` 是一个 pytest 插件，在 `pytest_configure` 里注入同样的 stub，
于是依赖 pydantic 的测试也能在本地跑：

```bash
PYTHONPATH=$HOME python3 -m pytest -p stubplug tests/test_multimsg_card.py tests/test_face_context.py -q
```

**教训（已被 CI 抓到过）**：本地验证脚本里修过的 stub 语义，**必须同步改到测试文件里** ——
`tests/test_multimsg_card.py` 的 stub 一度比真实实现更宽松（对非 json 消息也返回卡片文本），
导致 `test_non_json_segments_ignored` 在 CI 上失败（本地因缺依赖没跑到）。
现在两个新测试文件都能用 stubplug 在本地跑通（14 条）。
## 8. 上下文压缩后的恢复步骤

1. 读本文件（尤其 §3/§4/§5）—— 全部逆向事实与下一步都在这；
2. `ls ~/proto_src` 确认源码区仍在（若被清理，按 source-acquisition.md 重跑 `~/clone_sources.sh`）；
3. 继续 §4/§5 的下一步；
4. 每完成一个客户端，更新 §3 样式的小节 + `docs/client-compatibility.md` 对应列；
5. 落代码前先补 fixture（任务书 §17-A），改动只在 Adapter 层，Core 不得 import 客户端。
