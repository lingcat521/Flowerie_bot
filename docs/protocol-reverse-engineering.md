# 协议逆向工作记录（Protocol Reverse Engineering）

> 任务书 §22 交付物①，同时作为**跨会话可复用的工作记忆**：已逆向事实、文件路径、行号、待办与恢复步骤都记在这里，避免依赖对话上下文。核对版本 **v2.3.0**。
> 证据等级：`[CODE]` 源码 / `[DOC]` 文档 / `[FIXTURE]` 真实事件 / `[MVP]` 本地 MVP / `[INFERENCE]` 推断 / `[UNKNOWN]` 无证据。
> **逐客户端现行事实入口**（本文只保留跨客户端对照与工作记录）：[onebot11/napcat.md](reverse-engineering/onebot11/napcat.md)、[onebot11/llbot.md](reverse-engineering/onebot11/llbot.md)、[onebot11/go-cqhttp.md](reverse-engineering/onebot11/go-cqhttp.md)、[onebot11/lagrange.md](reverse-engineering/onebot11/lagrange.md)、[milky/llbot-milky.md](reverse-engineering/milky/llbot-milky.md)、[milky/lagrange-milky.md](reverse-engineering/milky/lagrange-milky.md)。

## 0. 复现环境（本地源码区，工作区之外）

`~/proto_src/`（`git clone --depth 1`，2026-09-25 获取，2026-09-26 复核 HEAD 未变，共 **17 个仓库**）：NapCatQQ `0b4cfe6`、SnowLuma `fe245d8`、Lagrange.Core `20c2ba0`、LagrangeV2 `7011cdf`、LLBot `9f374f6`、NoneBot2 `4510ce2`、adapter-onebot `58bb487`、OneBot11-spec `d4456ee`、Milky-spec（= SaltifyDev/milky）`151dd90`、Milky-doc（= Lagrange.Milky.Document）`98e96e5`、go-cqhttp `a5923f1`、Kovi `9decea5`、Koishi `5525cfd`、milky-python-sdk `805b194`、ROneBot `b39550f`、onebot（v12 规范）`d533f0f`、Lagrange.Doc `3a76e60`。逐仓库获取状态与失败记录见 [source-acquisition.md](source-acquisition.md)。

| 调查状态 | 仓库 |
| :--- | :--- |
| 已逆向（有结论，见 §3/§4/§6）| NapCatQQ、LLBot（OneBot 11 + Milky 双实现）、LagrangeV2 / Lagrange.Core 内嵌 `Lagrange.Milky/`、go-cqhttp |
| 只取到规范 / 文档 | OneBot11-spec、Milky-spec、onebot（v12）、Milky-doc、Lagrange.Doc（页面自称过时）|
| **未调查**（不得据此推断行为）| SnowLuma、NoneBot2、adapter-onebot、Kovi、Koishi、ROneBot、milky-python-sdk |
| **不可得** | `LagrangeDev/Lagrange.OneBot`（HTTP 404）、`whitechi73/OpenShamrock`（账号与仓库均 404）|

## 1. 本地 MVP 事实清单 [MVP]

文件：`/storage/emulated/0/bot.py`（1797 行，UTF-8，可读；工作区之外的历史基线）。与 Flowerie 的逐项差异见 [mvp-analysis.md](mvp-analysis.md)。

| 主题 | 事实 | 行号 |
| :--- | :--- | :--- |
| 连接 | 反向 WS 服务端（`websockets.serve`），无鉴权、无 ack | L1747-1786 |
| 发送 | HTTP `POST {HTTP_API_BASE}/send_group_msg`，`message` 为**纯字符串**；成功 = HTTP 200 且 `retcode==0` | L691-740 |
| 事件入口 | `_process_event`：`post_type=message` → `_handle_message`；`notice/group_upload` → 缓存待取文件；`notice/notify/poke` → `_handle_poke` | L1258-1278 |
| 消息模型 | `data.message` 为**段数组**；text→文本、at→`data.qq`、reply→`data.qq` 判是否回机器人 | L787-813 |
| **poke** | 字段回退链：`target_id → target → to_user_id → user_id`；只在 `target==bot` 时回复 | L1213-1256 |
| 文件（notice）| `group_upload` → `data.file{name,id,size,busid}`；再 `GET /get_file?file_id=` → **`{retcode:0,data:{base64}}`** | L815-829, L931-969 |
| 文件（消息段）| 段 `type=file`，`data.url` + `data.file`（名）；`/` 开头则拼 `HTTP_API_BASE`；同一 base64 信封 | L971-1014 |
| 合并转发 | 段 `type=forward`：优先 `data.messages`（内联），否则 `data.id` → `GET /get_forward_msg?message_id=`；文本**递归**收集任意 `{text:str}`，sender 取 `sender.user_id` | L1016-1075 |
| JSON 卡片 | 段 `type=json`，原始串在 `data.data`（回退 `content`/`text`）；递归收集字符串，黑名单跳过 `url/jumpUrl/preview/icon/appid/uin/scene/token/ctime/width/height/forward/autoSize` | L1078-1128 |
| 识图 | **完全没有**（grep `image`/`vision` 零命中）| — |

## 2. Flowerie 现状与缺口 [CODE]

| 层 | 文件（当前行数）| 事实 |
| :--- | :--- | :--- |
| 协议解析 | `src/adapters/onebot_parser.py`（433 行）| 已类型化：`text / at / image / reply / forward / json / face / mface / poke / shake / file / record / video / xml / markdown / miniapp / node / onlinefile / flashtransfer`；其余段原样进 `segments_summary` |
| 事件模型 | `src/adapters/proto.py`（149 行）| `InternalEvent` 字段全集与证据见 [protocol-implementation.md](protocol-implementation.md) §3、[message-model.md](message-model.md) §3 与 [adapter-architecture.md](adapter-architecture.md)（本文不再抄一份）|
| 文件 | `src/services/file_parser.py`（413 行）| `fetch_and_parse_file` → `GET {HTTP_API_BASE}/get_file` → `decode_base64_json_file_response`（L199，旧名 `decode_napcat_file_response` 已按行为改名；base64 → txt/pdf/docx/xlsx/csv，带流式上限）；`extract_forward_messages`（**强于 MVP**：嵌套展开 + `MAX_FORWARD_DEPTH/NODES/MESSAGES/FETCHES` 预算 + 同 id 缓存 + 收集转发内图片 URL）；`extract_json_card_content`（遍历**全部** json 段并去重合并）|
| 组装 | `src/core/message_assembler.py`（388 行）| `_assemble_faces`（L191）/ `_assemble_media` / `_assemble_quote` / `_assemble_forward`（转发文本 + 转发内图片走 Vision）/ `_assemble_card`（multimsg 卡片按转发拉内层，失败退回卡片文本）/ `_assemble_pending_file`（notice 配对取文件）/ `_describe_images`（**本地 `image_files` 优先，URL 兜底**）|
| poke 下游 | `src/core/message_router.py` L538 起 | `target_id → actor_id` 回退 + 白名单 + 每人冷却；与 MVP 语义一致 |
| SDK | `src/adapters/onebot/{dto,transformer,adapter}.py` | `dto.raw_message` 截断 4000；`transformer` 有 `extract_text/extract_at_list/extract_images/extract_reply_id` |

**当前仍存在的缺口（显式保留）**：

1. **OneBot 11 有 5 个段类型没有类型化字段**：`music / dice / rps / contact / location` —— 台账 `tests/fixtures/segment_inventory.json` 里 `typed=false`、`normalized=""`，解析后只进 `segments_summary`，业务层拿不到语义（Milky 侧 14 个段全部 typed）；
2. **`segments_summary` 仍无业务消费者**：只有解析器写、测试读；业务层读的是 `message_segments` 与语义字段（因此上面的缺口不会报错，只会静默少语义）；
3. **真实设备验证全缺**：以下所有结论都是源码 `[CODE]` / 文档 `[DOC]` 级，实机项 BLOCKED（[protocol-gap-closure.md](protocol-gap-closure.md) §6）；
4. **发送侧不需要** NapCat 的「FILE/VIDEO/ARK/PTT 独占一条消息」拆分（见 §9 C1 —— 那是客户端内部行为，不是调用方约束）。

## 3. NapCat 逆向结论 [CODE]

源码 `~/proto_src/NapCatQQ`（HEAD `0b4cfe6`）；逐字段档案见 [reverse-engineering/onebot11/napcat.md](reverse-engineering/onebot11/napcat.md)。

### 3.1 内部元素模型

文件 `packages/napcat-core/types/msg.ts` → `enum ElementType`（L45-79）：`TEXT=1` `PIC=2` `FILE=3` `PTT=4` `VIDEO=5` `FACE=6` `REPLY=7` **`GreyTip=8`**（注释：小灰条，含**拍一拍(Poke)**、撤回提示）`WALLET=9` **`ARK=10`** **`MFACE=11`** `LIVEGIFT=12` `STRUCTLONGMSG=13` `MARKDOWN=14` `GIPHY=15` **`MULTIFORWARD=16`** `INLINEKEYBOARD=17` `INTEXTGIFT=18` `CALENDAR=19` `YOLOGAMERESULT=20` `AVRECORD=21` `FEED=22` `TOFURECORD=23`（注释：在线文件的 id 是这个）`ACEBUBBLE=24` `ACTIVITY=25` `TOFU=26` `FACEBUBBLE=27` `SHARELOCATION=28` `TASKTOPMSG=29` `ONLINEFOLDER=30` `RECOMMENDEDMSG=43` `ACTIONBAR=44`。

### 3.2 OneBot 段词汇表与字段 schema

`packages/napcat-onebot/types/message.ts`（482 行）的 `OB11MessageDataType`：`text image music video record file at reply json face mface markdown node forward xml poke dice rps miniapp contact location onlinefile flashtransfer`。

| 段 | 字段（逐字取自 typebox schema）|
| :--- | :--- |
| `text` / `face` / `at` / `reply` / `poke` / `json` / `xml` / `markdown` | `text`；`face{id,resultId?,chainCount?}`（连击数）；`at{qq,name?}`；`reply{id?,seq?}`；`poke{type,id}`；`json{data(Union),config?}`；`xml{data}`；`markdown{content}` |
| `mface` / `miniapp` / `onlinefile` / `flashtransfer` | `mface{emoji_package_id(Number),emoji_id(String),key(String),summary(String)}`；`miniapp{data}`（注释：json 类）；`onlinefile{msgId,elementId,fileName,fileSize,isDir}`；`flashtransfer{fileSetId}`（QQ 闪传）|
| `node` / `forward` | `node{id?,user_id?,uin?,nickname,name?,content,source?,news?,summary?,prompt?,time?}`；`forward{id,content?}`（用于上报）|
| `dice`/`rps` / `contact` / `location` | `result`；`contact{type,id}`；`location{lat,lon,title?,content?}` |
| `image` / `record`/`video`/`file` | FileBase + `image` 另有 `summary?`、`sub_type?`；**FileBase**（`FileBaseDataSchema` L80-86）：`file`（必填，路径/URL/`file://`）、`path?`、`url?`、`name?`、`thumb?` |

### 3.3 合并转发与 JSON 卡片的真实实现（最重要）

文件 `packages/napcat-onebot/action/msg/SendMsg.ts`（514 行）：

- **发送合并转发**（L324-346）：节点转 protobuf → `UploadForwardMsgV2(...)` 拿 **`resid`** → `ForwardMsgBuilder.fromPacketMsg(resid, ...)` 造 JSON → **以 `ElementType.ARK` 元素发送**（`arkElement.bytesData`）；
- **接收识别**（L289-297）：`element.arkElement.bytesData` 解析后，**只有 `json.app === com.tencent.multimsg`** 才是合并转发卡片：`resid = json.meta.detail.resid`、`uuid = json.meta.detail.uniseq || json.extra.filename`，再用 `FetchForwardMsgRaw(resId)` 拉内层（内层 `actionCommand === MultiMsg`）；
- **发送分组规则**（L411-431，⚠️ 已更正，见 §9 C1）：`FILE` / `VIDEO` / `ARK` / `PTT` 被拆成**独占一条消息** —— 但这是 `handleForwardedNodes`（**合并转发节点路径**）内部行为，**不是**对普通 `send_group_msg` 调用方的约束；
- **node 内容校验**（L392-397）：`node.content` 混入非 node 段时，NapCat 记 error 并 `continue` —— **整个节点被丢弃**（调用方唯一可见的真实约束）。

→ 直接推翻两个常见假设："合并转发是一个 segment" 与 "所有 `type:json` 语义相同"。

### 3.4 其他可用入口（后续按需深入）

入站解析类 `packages/napcat-core/packet/message/element.ts`（742 行）里的 `PacketMsg{Text,At,Reply,Face,MarkFace,Pic,Video,Ptt,File,LightApp,MarkDown,MultiMsg}Element`，每类实现 `static parseElement(elem)`（L71/109/152/212/307/345/453/543/580/667/691/716）；出站构造 `packages/napcat-core/types/element.ts` 的 `Send*Element`（L338-389）；消息转换 `packages/napcat-core/packet/message/converter.ts`（173 行，`packetMsgToRaw`）；事件类 `packages/napcat-onebot/event/notice/OB11*NoticeEvent.ts`（poke 是 `OB11PokeEvent.ts`）。

## 4. LLBot（Milky + OneBot 11 双实现）[CODE]

源码 `~/proto_src/LLBot`（HEAD `9f374f6`，`src/` 796 文件、`test/` 238 文件）。它是**唯一同时实现 OneBot 11 与 Milky 的客户端**，也是 Milky 实现层的最佳可得证据（Lagrange.Milky 独立仓库不可得 → 该列靠 LLBot `[CODE]` + 规范 `[DOC]` 互证）。逐字段档案见 [reverse-engineering/onebot11/llbot.md](reverse-engineering/onebot11/llbot.md) 与 [reverse-engineering/milky/llbot-milky.md](reverse-engineering/milky/llbot-milky.md)。

### 4.1 Milky 入站映射（`src/milky/transform/message/incoming.ts`，252 行）

消息外壳（L8-56）：`message_scene` = `friend` / `group` / **`temp`（临时会话）**；字段 `peer_id`、`message_seq`(=msgSeq)、`sender_id`(=senderUin)、`time`、`segments[]`，群消息额外带 `group` / `group_member`。

| NTQQ 元素 | Milky 段 | 字段（逐字取自源码）|
| :--- | :--- | :--- |
| `Text`（`atType=All` / `=One` / 其它）| `mention_all` / `mention` / `text` | ``；`{user_id, name}`（**`@` 藏在 Text 元素里，不是独立元素**）；`{text}` |
| `Face` | `face` | `face_id`(=faceIndex.toString()), `is_large`(faceType===3) |
| `Reply` | `reply` | `message_seq`, `sender_id`, `time`, **`segments`（内联被引消息的段数组）** |
| `Pic` / `Ptt` / `Video` | `image` / `record` / `video` | `resource_id`(fileUuid), **`temp_url`**, `width`, `height`, `summary`, `sub_type`(`sticker`/`normal`，picSubType===1→sticker)；`record{resource_id,temp_url,duration}`；`video{resource_id,temp_url,width,height,duration}` |
| `File` | `file` | `file_id`(fileUuid), `file_name`, `file_size` |
| `MultiForward` | `forward` | `forward_id`(resId), `title`, `preview[]`, `summary`（**从 `xmlContent` 解析 XML** 得到）|
| `MarketFace` | `market_face` | `emoji_package_id`, `emoji_id`, `key`, `summary`(=faceName), `url`（拼出 `gxh.vip.qq.com/.../raw300.gif`）|
| `Ark`（`app=com.tencent.multimsg`）/ `Ark`（其它 app）| **`forward`** / **`light_app`** | `forward_id`(= `meta.detail.resid`), `title`(=detail.source), `preview[]`(=detail.news[].text), `summary`；`{app_name(=app), json_payload(=原始 bytesData)}` |
| `markdownElement` | `markdown` | `content` —— **短路整个循环**：只要有 markdown 元素，其它元素全部忽略（L61-69）|

转发内层结构（L244-252）：`{ message_seq, sender_name, avatar_url, time, segments[] }`。

**互证价值**：LLBot 与 NapCat 各自独立地对 Ark 做 `app === com.tencent.multimsg` 判定，一个映射成 `forward`、一个映射成 ARK 元素 —— 说明"JSON/Ark 必须按 `app` 分流"是**客户端共识**，不是某一家的私有行为。

### 4.2 Milky 出站映射与对发送侧的直接约束（`src/milky/transform/message/outgoing.ts`，131 行）

| Milky 出站段 | 客户端处理 |
| :--- | :--- |
| `text{text}` / `face{face_id,is_large}` | `SendElement.text(text)`；`SendElement.face(+face_id, is_large ? 3 : undefined)` |
| `mention{user_id}`（**仅群**）/ `mention_all`（**仅群**）| 先 `getGroupMemberByUin` 取名 → `SendElement.at(uin, AtType.One, @名字)`；`SendElement.at(0, AtType.All, @全体成员)` |
| `reply{message_seq}` | 按 seq 先查本地 store，miss 则 `getSingleMsg` 拉服务器；需要 senderUin/senderUid/msgTime/clientSeq；**若在转发内还要 rawPb** |
| `image{uri, sub_type, summary}` / `record{uri}` / `video{uri, thumb_uri}` | `resolveMilkyUri(uri)` 下载 buffer → 写临时文件 → `SendElement.pic/ptt/video`；`sub_type=sticker` → picSubType=1；**发送后删除临时文件** |
| `forward{messages[], title, preview, summary, prompt}` | 递归转换每个节点（`isInsideForward=true`）→ `SendElement.forward(nodes, ...)`；节点带 senderUin/senderName/elements/msgSeq(自增)/msgTime |
| `light_app{json_payload}` | `SendElement.ark(json_payload)` |

**对 Flowerie 发送侧的直接约束**：① **媒体不是"给个 URL 就行"** —— Milky 的 `uri` 必须由应用侧先下载成字节再交给客户端上传，且要写临时文件、发完即删；② **`@` 需要群成员名片**（多一次 API 调用），且**仅在群聊可用**；③ **逐段容错** —— 单个段转换失败只记日志、继续处理后面的段（不整条消息失败）；④ `forward` 的节点需要自造 msgSeq，且**转发内的 reply 需要 rawPb**（内层引用与顶层不同）。

### 4.3 LLBot 的 OneBot 11 入站（`src/onebot11/transform/message/incoming.ts`，327 行）与 NapCat 的差异

| 元素 | OneBot 段与字段（逐字）| 与 NapCat 的差异 |
| :--- | :--- | :--- |
| `picElement` | `image{file, **subType**(camelCase), url(生成), file_size}` | NapCat 是 `sub_type`（snake_case）→ **同语义不同名** |
| `videoElement` / `fileElement` | `video{file, url(file://或空), path, file_size}`；`file{file, url(file://或空), **file_id**(fileUuid), path, file_size}` | NapCat 只有 FileBase（`file/path/url/name/thumb`），**没有 `file_id`** |
| `pttElement` | `record{file, url(生成), file_size}` | NapCat 同段名，字段更少 |
| `arkElement` | **`json{data: bytesData}`** —— OneBot 侧**不区分 app** | NapCat 同样原样透传 bytesData（分流发生在客户端内部）|
| `faceElement` | 分三路：`faceType=Poke 且 faceIndex=1` → **`shake{}`**；`faceIndex=Dice` → `dice{result}`；`faceIndex=RPS` → `rps{result}`；否则 → `face{id, **sub_type**(faceType)}` | NapCat 的 `face` 是 `{id, resultId?, chainCount?}` → **字段集不同** |
| `marketFaceElement` / `markdownElement` | `mface{summary, **url**(拼 gxh.vip.qq.com), emoji_id, emoji_package_id, key}`；（markdown 见 incoming.ts L244 起，本轮未细读）| NapCat 的 mface **没有 url** |

### 4.4 交叉结论：同一个用户动作，三种协议形态（最重要的一节）

**「戳一戳 / poke」在三个实现里完全不同**：

| 来源 | 形态 | 字段 |
| :--- | :--- | :--- |
| OneBot 11（MVP / Flowerie 处理的那个）| `notice` + `notice_type=notify` + `sub_type=poke` | `user_id`, `target_id`（MVP 回退 `target`/`to_user_id`）, `group_id` |
| NapCat | ① `notice` 的 `OB11PokeEvent`；② 消息里的 **`poke{type,id}` 段**；③ 内部 `GreyTip=8` 元素 | 段形态 `{type,id}` |
| **LLBot 的 OneBot11** | **`face` 元素 `faceType=Poke` → `shake{}` 段**（无 id、无目标！）| `` |
| **Milky（LLBot 实现）** | **事件** `group_nudge` / `friend_nudge` | 群：`{group_id, sender_id, **receiver_id**, display_action, display_suffix, display_action_img_url}`；友：`{user_id, is_self_send, is_self_receive, display_action, …}` |

→ 归一化层必须把「戳一戳」抽象成**一个语义事件**（谁戳谁、在哪个会话），而不是照搬某家的字段；尤其 LLBot 的 `shake` 段**不带目标**，只能从 sender/受话人推断 → 这类信息差必须在 Adapter 里显式处理 `[CODE]`。

**「表情」有三类，且各家字段不同**：

| 类别 | NapCat | LLBot(OneBot) | LLBot(Milky) |
| :--- | :--- | :--- | :--- |
| QQ 表情 | `face{id, resultId?, chainCount?}` | `face{id, sub_type}` | `face{face_id, is_large}` |
| 商城表情 | `mface{emoji_package_id, emoji_id, key, summary}` | 同 + **`url`** | `market_face{…, url}` |
| 图片形式表情 | `image{sub_type}`（FileBase 扩展）| `image{subType}` | `image{sub_type: sticker}` |

→ 归一化层至少要能区分这三类，并把 `id`/`face_id`/`faceIndex`、`sub_type`/`subType`、`summary`/`faceName` 收敛成统一字段 `[CODE]`（已落地：`InternalEvent.faces`，渲染见 `message_assembler._assemble_faces`）。

## 5. 待调查清单（含第一步命令）

| 目标 | 第一步 |
| :--- | :--- |
| SnowLuma | 在 `~/proto_src/SnowLuma` 里 `git grep -n "OneBot"` 再 `head`，找它的协议实现目录 |
| NoneBot2 + adapter-onebot | 在 `~/proto_src/adapter-onebot` 里 grep `raw_message` / `message_type`，看它如何兼容非标准字段 |
| Kovi / Koishi / ROneBot / milky-python-sdk | 生态 SDK，**消费同一套 wire 形态**：除非发现独特字段，否则不逐个逆向（`docs/client-compatibility.md` §6.2）|
| OneBot 11 规范 | 逐段核对 `[DOC]` 列（`~/proto_src/OneBot11-spec`）|
| Milky | 规范 `~/proto_src/Milky-spec/protocol/src/ir/api/*.ts`；实现以 §6 的**内嵌副本**为准（独立仓库不存在）|
| LLBot 剩余未细读 | `src/onebot11/action/**`（含 `file/GetFile.ts`、`file/GetImage.ts`）、`src/ntqqapi/helper/message{Parsing,Building}.ts`（422/456 行）、`src/milky/transform/event.ts`（470 行，Milky 事件含 poke 类通知）|

## 6. Lagrange.Milky 实现（协议作者本人实现）[CODE]

**重要更正**（见 §9 C2）：Milky 的**实现**并非不可得 —— 它内嵌在 `Lagrange.Core` 与 `LagrangeV2` 的 `Lagrange.Milky/` 目录里（119 个 .cs），无需单独仓库；`LagrangeDev/Lagrange.Milky` 这个独立仓库确实不存在（`ls-remote` exit 128），但结论是"实现源码在别处且已获得"。档案见 [reverse-engineering/milky/lagrange-milky.md](reverse-engineering/milky/lagrange-milky.md)。

### 6.1 段类型（作者实现，⚠️ **两份内嵌副本布局不同**，勿混用）

段：`TextSegment` `MentionSegment` `MentionAllSegment` `FaceSegment` `ImageSegment` `RecordSegment` `VideoSegment` `FileSegment` `MarketFaceSegment` **`LightAppSegment`** `ForwardSegment` `ReplySegment` `XmlSegment` + 基类 `SegmentBase` / 接口 `ISegment`。

| 副本 | 路径 | 文件数 | incoming 段 |
| :--- | :--- | ---: | :--- |
| A | `LagrangeV2/Lagrange.Milky/Entity/Segment/` | 15 | **13 种**：text / mention / mention_all / face / reply / image / record / video / file / forward / market_face / light_app / xml（`ISegment.cs` L6-18 的 typeDiscriminator；**无 markdown**）|
| B | `Lagrange.Core/Lagrange.Milky/Models/Segments/` | 11 | **10 种**：text / mention / mention_all / reply / image / record / video / file / forward / light_app（**没有** face / market_face / xml / markdown）|

**两副本字段宽度也不同**：副本 A 的 `market_face` 只有 `url`、`face` 只有 `face_id`；规范（`common.ts` L323-326 / L366-372）另有 `is_large` / `emoji_id` / `summary` 等 —— **实现比规范窄**，解析必须逐字段兜底（`milky_parser` 已如此），不能假定字段存在。

**关键结论**：① **没有 poke / nudge 段** —— 戳一戳在 Milky 里**只有事件**（§6.2），不是消息段；② **有 `LightAppSegment`** —— 与 LLBot 的 `light_app` 对应，"Ark/轻应用"是**独立段类型**（不是靠 `app` 字段在同一个 json 段里分流）；③ **有 `XmlSegment`**（OneBot 的 `xml` 段在 Milky 有对应）；④ 消息实体分 `FriendMessage` / `GroupMessage` / **`TempMessage`**（临时会话，与 LLBot 的 `temp` 场景一致）。

### 6.2 戳一戳事件（`Entity/Event/GroupNudgeEvent.cs`，全文 26 行）

`group_nudge` 事件的 data 字段（`[JsonPropertyName]` 逐一对应）：`group_id` / `sender_id` / `receiver_id` / `display_action` / `display_suffix` / `display_action_img_url` → 与 LLBot 的 `transformGroupNudgeEvent` **逐字段一致** → 两条独立来源互证 Milky 规范 `[CODE]×2`。

### 6.3 与另外两家的对照（归一化输入）

| 维度 | Milky（作者实现）| NapCat（OneBot）| LLBot（OneBot）|
| :--- | :--- | :--- | :--- |
| 戳一戳 | **事件** `group_nudge{group_id,sender_id,receiver_id,display_*}` | `poke{type,id}` 段 + notice | `shake{}` 段（**无目标**）|
| 轻应用/卡片 | **独立段** `LightAppSegment` | `json{data,config?}`（靠 app 分流）| `json{data}` / `miniapp{data}` |
| 合并转发 | **独立段** `ForwardSegment` | ARK 元素（app=com.tencent.multimsg）| `forward` / `light_app` |
| 临时会话 | `TempMessage` 实体 | — | `message_scene=temp` |

→ 归一化层不应以「段类型名」为准，而应以**语义**为准：同一个 `LightAppSegment` 在 OneBot 侧可能表现为 `json`、`miniapp`，甚至是「合并转发」（取决于 `app`）`[CODE]`。

## 7. 已落地的代码修复（P4 进度）

| 提交 | 层 | 内容 | 证据 | 验证 |
| :--- | :--- | :--- | :--- | :--- |
| `529e6ae` | Adapter | `InternalEvent` 新增 `faces/pokes/files/json_cards/forwards`；`onebot_parser` 归一化 `json`（含 app+is_forward_card）/ `face` / `mface` / `poke` / `shake` / `file` / `forward`，且**同时保留 `segments_summary` 旧通道** | NapCat schema、LLBot 段字段、Milky 作者实现、SnowLuma codecs、NoneBot 工厂 | 本地 25 条绿 + **CI 全绿** |
| `4a6a157` | 组装 | multimsg 卡片按**合并转发**拉取内层（`app=com.tencent.multimsg` → `meta.detail.resid` → 复用 `_assemble_forward`），失败/无 resid 退回卡片文本 | NapCat `SendMsg.ts` L289-297、LLBot `incoming.ts` L210-235 | 新测试 6 条 + 本地 stub 注入真跑 6/6 |

**原"尚未落地"清单的现状（2026-09 复核）**：

1. **表情进入业务层** —— 已落地：`message_assembler._assemble_faces`（L191-226）把 `faces` 渲染成一句上下文（上限 3 条，逐字段兜底）；
2. **Milky 侧适配** —— 已落地：G1 `scene/context_group_id`、G3 `records/videos/xmls`、G4 `reply_ref/reply_segments/reply_text` 全部进入正式模型（见 [protocol-gap-closure.md](protocol-gap-closure.md) §4）；
3. **多段合并** —— 已落地：卡片文本由 `file_parser.extract_json_card_content` 遍历**全部** json 段去重合并；multimsg 成功时同条消息里的其它卡片**不**再渲染（`_assemble_card` 注释 + `tests/test_multimsg_card.py` 锁定）；
4. **发送侧「FILE/VIDEO/ARK/PTT 独占一条」** —— 结案为**不需要**（§9 C1），不再列为待办。

**仍未落地（下一步的真实缺口）**：① `segments_summary` 没有业务消费者，且 OneBot 11 的 `music/dice/rps/contact/location` 五个段只有 summary（§2 缺口 1–2）；② 实机验证（G5/G6，BLOCKED）。

### 本地验证技巧（压缩后复用）

本机缺 pydantic/pydantic_settings/httpx，无法直接 import 依赖 `src.config` 的模块。`~/stubplug.py` 是 pytest 插件，在 `pytest_configure` 里向 `sys.modules` 注入最小 stub（`pydantic.Field/field_validator/BaseModel`、`pydantic_settings.BaseSettings/SettingsConfigDict`、`httpx.Timeout/Limits/AsyncClient`），于是依赖 pydantic 的测试也能在本地跑真实代码路径（早期脚本示例：`~/verify_multimsg.py`）：

```bash
PYTHONPATH=$HOME python3 -m pytest -p stubplug tests/test_multimsg_card.py tests/test_face_context.py -q
```

**教训（已被 CI 抓到过）**：本地脚本里修过的 stub 语义**必须同步改到测试文件里** —— `tests/test_multimsg_card.py` 的 stub 一度比真实实现更宽松（对非 json 消息也返回卡片文本），导致 `test_non_json_segments_ignored` 只在 CI 上失败（本地因缺依赖没跑到）。依赖齐全的机器直接跑 `python3 -m pytest`，无需该插件。

## 8. 上下文压缩后的恢复步骤

1. 读本文件（尤其 §3/§4/§5/§6）—— 全部逆向事实与下一步都在这，逐客户端细节在 `docs/reverse-engineering/`；
2. `ls ~/proto_src` 确认源码区仍在（若被清理，按 [source-acquisition.md](source-acquisition.md) 重跑 `~/clone_sources.sh`）；
3. 继续 §5 的待调查项与 §7 的"仍未落地"；
4. 每完成一个客户端，更新 `docs/reverse-engineering/<协议>/<客户端>.md` 与 `docs/client-compatibility.md` 对应列；
5. 落代码前先补 fixture（任务书 §17-A），改动只在 Adapter 层，Core 不得 import 客户端。

> 早期交付记录：`095ac6e` → `docs/source-acquisition.md`；`951e666` → `docs/client-compatibility.md`（v1，NapCat 列 `[CODE]`）；本文件即 `docs/protocol-reverse-engineering.md`。

## 9. 更正记录（corrections）

> 任务书 §20：状态变化与更正必须**显式记录**，禁止静默替换。本节按时间倒序累积。

### C1（2026-08-09）：NapCat「FILE/VIDEO/ARK/PTT 独占一条」不是发送方约束

- **原表述**（本文件 §3.3 与 `client-compatibility.md` §3.3）：这类元素"必须独占一条消息，不能与其他段混发"，并被登记为 Flowerie 的**待办发送侧规则**。
- **复核证据**（`napcat-onebot/action/msg/SendMsg.ts`，514 行全文实测）：全文**仅 L417 一处** `elementType ===` 比较，且位于 `handleForwardedNodes`（L368-435）内部 —— **只服务 `node`（合并转发）路径**：NapCat 把节点内容拆成 `MixElement` + 每个 FILE/VIDEO/ARK/PTT 各自成条，分别发送后收集 `msgId`，最后由 `multiForwardMsg(...)`（L472-483）组装成一张转发卡片；**普通发送路径**（`SendMsg` → `normalize()` L53-60 → `createSendElements`）**没有**任何此类拆分。
- **结论**：① Flowerie **不需要**也**不应该**在发送侧实现该拆分（会造成重复或意外的多条消息）；② 该代码对调用方唯一有意义的推论是 **`node` 段的内容数组里只能放 `node` 段** —— 混入其他段时 NapCat 记 error 并 `continue`（L392-397），**整个节点被丢弃**；③ 已同步更正 `docs/client-compatibility.md` §3.3 与 `docs/adapter-architecture.md` §5/§7。
- **教训**：摘录源码时，**片段所在的函数与分支**与片段本身同等重要；只看"一行 filter 条件"会把"客户端内部实现"误读成"协议对调用方的约束"。

### C2（2026-08-09）：Milky 作者实现有**两份布局不同**的内嵌副本（此前文档只写了一份）

- **问题**：本文件 §6.1 与测试 docstring 曾先后只写一条路径 —— 先写 `Entity/Segment/`（15 个段），补 Milky 映射时又写成 `Models/Segments/`（10 个段），把两份**不同**的副本当成同一个"作者实现"。
- **实测结论**（两份副本都在源码区里，均为 `[CODE]`）：**副本 A / B 的路径、文件数、incoming 段集合与字段宽度都不同** —— 完整对照表见 **§6.1**（本记录不再抄一遍）；字段宽度差异导致 `milky_parser` 一律逐字段兜底（并已修 Assembler 的退化渲染）。
- **影响**：`markdown` 段规范有、两副本都无（标注 `[DOC]`，不进实现的"段清单"）；`face` / `market_face` 只在副本 A 有 —— 对 Flowerie 而言都必须能解析（同生态里两种客户端并存）。
- **教训**：同一个项目在不同仓库里的副本可能**目录布局与字段宽度都不同**；引用源码必须写清"**哪个仓库的哪份副本**"，说"实现没有某段"时要指明**是哪一份实现**。

### C3（2026-08-09）：Milky 没有 `notice_receive` —— 除消息外的事件此前全部落空

- **原实现**（`src/adapters/milky_parser.py` 旧 `_EVENT_KIND`）：只映射 `message_receive / notice_receive / lifecycle`，其余 `kind = event_type`。
- **实测**（Milky 规范 `protocol/src/ir/common.ts` 的 Event 联合，`[DOC]`）：顶层事件类型共 **21 种** —— bot_offline / message_receive / message_recall / peer_pin_change / friend_request / group_join_request / group_invited_join_request / group_invitation / friend_nudge / friend_file_upload / group_admin_change / group_essence_message_change / group_member_increase / group_member_decrease / group_disband / group_name_change / group_message_reaction / group_mute / group_whole_mute / group_nudge / group_file_upload；其中 **`notice_receive` 出现 0 次**（`grep -c` 实测）。
- **后果**：Milky 模式下 `group_nudge`（戳一戳）、`group_file_upload`（群文件）等事件的 `kind` 直接等于 event_type，**进不了路由的 notice 分支** —— 这两个功能在 Milky 模式下实际失效。
- **修复**：按事件类型归一化成领域 kind（**21 种全覆盖**），并把 `group_nudge/friend_nudge → notice_kind=poke`（actor = `sender_id`，target = `receiver_id` / `user_id`）、`group_file_upload → notice_kind=group_upload`（`notice_file{id,name,size}`）接入既有业务分支；`notice_receive` 仅保留为旧样例兼容。测试见 `tests/test_milky_event_kinds.py`（9 用例，含 21 种全覆盖断言）。
- **教训**：把"某客户端一定会发某个通用类型"当成前提是危险的 —— **规范里没有的类型必须先去数一遍**；这类"看起来在工作、实际整类事件被丢弃"的缺陷不会报错，只会静默少功能。

