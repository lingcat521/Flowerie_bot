# Flowerie 统一消息模型（Unified Message Model）

> Core/Plugin 只面对**归一化事件**（不得出现 `if napcat` / `if lagrange`）；本文只写**已被源码证据支持**的部分，无证据的维度标 `[UNKNOWN]`，不猜。

## 1. 实现载体：`InternalEvent`（`src/adapters/proto.py:43`）

主流程唯一的事件模型是 **`InternalEvent`**（早期设计名 `NormalizedEvent` / `NormalizedSegment` 在代码中不存在）；
段不建类型树，而是落到**语义载体字段**，Core 只读这些字段（`proto.py:76-95`）：

| 载体 | 覆盖语义 | 关键点 |
| :--- | :--- | :--- |
| `text` / `mentions` / `is_mentioned` | text / mention / mention_all | @ 列表含 `all`；派生 `is_reply_to_bot` / `has_at_others` / `has_reply_to_other` |
| `images` / `image_files` | image | url 列表与本地 file 路径（识图优先 file） |
| `faces` | face / market_face | `kind` 区分；商城表情字段更窄 |
| `pokes` | poke / shake | 消息段形态的戳一戳；LLBot `shake` 的 `target=None` 为显式状态（`onebot_parser.py:340-342`） |
| `files` | file / onlinefile / flashtransfer | `sub_type` 区分；字段 `file_id`/`name`/`size`/`url`/`path` |
| `json_cards` | json / miniapp / Ark | 保留 `app` 与是否合并转发标记 |
| `forwards` | forward / node | `id` + 是否内联 |
| `records` / `videos` / `xmls` | record / video / xml | G3 新增；`xmls` 只保真 `raw_xml`，**不解析** |
| `reply_id` / `reply_ref` / `reply_segments` / `reply_text` | reply | Milky 内联被引段；OneBot 只有 id |
| `notice_kind` / `request_*` / `lifecycle_kind` | notice / request / lifecycle | 请求类含 `request_scene`/`request_id`/`request_uid`/`request_filtered`/`comment` |
| `segments_summary` / `message_segments` / `raw_data` | 兜底与保真 | 未建模段原样进 `segments_summary`(`(wire_type, data)`) + `raw_data`，绝不丢；`raw_data` 业务层禁读 |

事件级字段：`kind`(message|notice|request|lifecycle)、`scope`(group|private)、`scene`(group|friend|temp|stranger)、`context_group_id`（临时会话来源群）、`group_id`、`actor_id`、`target_id`、`message_id`、`timestamp`、`event_id`。

### 三条设计原则（由证据倒逼）

1. **按语义建模，不按段类型名建模**：同一用户动作在不同协议里段名不同——戳一戳在 Milky 是事件
   `group_nudge`、在 NapCat 是 `poke` 段 + GreyTip 元素、在 LLBot 的 OneBot 是 `shake` 段。
2. **保留原始协议维度**：合并转发在 OneBot 侧可能是 `forward` / `node` / `json(app=com.tencent.multimsg)` /
   `light_app`，Milky 侧是 `ForwardSegment`——归一化必须记录来源形态，否则无法反向构造。
3. **信息缺失要显式**：LLBot `shake{}` 不带目标，Milky `group_nudge` 带 `receiver_id`；「目标未知」表达为显式状态，不补 0 不猜。

## 2. 证据映射表（协议 → 归一化语义）

| 归一化语义 | OneBot 11（规范/NoneBot） | NapCat | LLBot(OneBot) | SnowLuma | Milky（作者实现/LLBot） |
| :--- | :--- | :--- | :--- | :--- | :--- |
| text | `text{text}` `[DOC]` | `text` `[CODE]` | `text` `[CODE]` | `text` `[CODE]` | `text{text}` `[CODE]` |
| mention / mention_all | `at{qq}` / `at{qq=all}` `[DOC]` | `at{qq,name?}` / `at{qq=all}` `[CODE]` | `at{qq}` / `at{qq=all}` `[CODE]` | `at{qq}` / `at{uid=all,targetUin=0}` `[CODE]` | **Text atType=One → `mention{user_id,name}`** / `mention_all{}` `[CODE]` |
| image | `image{file,url?}` `[DOC]` | `image{file,path?,url?,name?,thumb?,sub_type?,summary?}` `[CODE]` | `image{file,subType,url,file_size}` `[CODE]` | `image{...}` `[CODE]` | `image{resource_id,temp_url,width,height,summary,sub_type}` `[CODE]` |
| face | `face{id}` `[DOC]` | `face{id,resultId?,chainCount?}` `[CODE]` | `face{id,sub_type}` `[CODE]` | `face{id}` `[CODE]` | `face{face_id}`（副本 A；规范另有 `is_large` since 1.1）`[CODE]`/`[DOC]` |
| market_face | 非标准 | `mface{emoji_package_id,emoji_id,key,summary}` `[CODE]` | `mface{...,url}` `[CODE]` | `mface` `[CODE]` | `market_face{url}`（**副本 A 只有 url**；规范另有 emoji_package_id/emoji_id/key/summary）`[CODE]`/`[DOC]` |
| file | `file{file,url?,file_id?}` `[DOC]` | FileBase（**无 file_id**）`[CODE]` | `file{file,url(file://),file_id,path,file_size}` `[CODE]` | `file{fileId,url}` `[CODE]` | `file{file_id,file_name,file_size,file_hash?}`（**无 url**）`[CODE]` |
| forward | `forward{id}` / `node{...}` `[DOC]` | ARK(`app=com.tencent.multimsg`) 或 MULTIFORWARD / `forward{id,content?}` `[CODE]` | `forward`（由 MultiForward XML 或 Ark 而来）`[CODE]` | `forward` `[CODE]` | `ForwardSegment{forward_id,title,preview,summary}`（独立段）`[CODE]` |
| json_card | `json{data}` `[DOC]` | `json{data,config?}`（**app 分流**）`[CODE]` | `json{data}`（不分流，交上层）`[CODE]` | `json{data}` `[CODE]` | **`LightAppSegment{app_name,json_payload}`**（独立段；**app 在 payload 内**）`[CODE]` |
| xml | `xml{data}` `[DOC]` | `xml{data}` `[CODE]` | — `[UNKNOWN]` | `xml` `[CODE]` | `XmlSegment{service_id,xml_payload}`（**仅副本 A**）`[CODE]` |
| markdown | 非标准 | `markdown{content}`（并**短路**其它元素）`[CODE]` | `markdown`（未细读）`[UNKNOWN]` | `markdown` `[CODE]` | `markdown{content}`——规范有（since 1.3）、两份内嵌实现都无 `[DOC]`（Flowerie 按内容并入 `text`） |
| poke | **`poke{type,id}` 是规范段**（NoneBot adapter 有工厂）`[CODE]` | `poke{type,id}` 段 + notice + GreyTip(8) 元素 `[CODE]` | **`face(faceType=Poke)` → `shake{}`** `[CODE]` | `poke` 段 `[CODE]` | **事件** `group_nudge{group_id,sender_id,receiver_id,display_action,display_suffix,display_action_img_url}` `[CODE]×2` |
| 闪传/在线文件、inline_keyboard | — `[UNKNOWN]` | `flashtransfer{fileSetId}`、`onlinefile{msgId,elementId,fileName,fileSize,isDir}`、ElementType.INLINEKEYBOARD(17) `[CODE]` | — `[UNKNOWN]` | `flash_file`、`inline_keyboard` 段 `[CODE]` | — `[UNKNOWN]` |

> Milky 列的"作者实现"有**两份布局不同的内嵌副本，勿混用**（`[CODE]`，见 protocol-reverse-engineering.md §6.1/§9 C2）：
> **副本 A** `LagrangeV2/Lagrange.Milky/Entity/Segment/` 15 文件 / **13 种** incoming（含 face、market_face、xml，无 markdown）；
> **副本 B** `Lagrange.Core/Lagrange.Milky/Models/Segments/` 11 文件 / **10 种** incoming（无 face / market_face / xml / markdown）。
> 且**实现字段比规范窄**（副本 A 的 `market_face` 只有 `url`、`face` 只有 `face_id`）——解析一律**逐字段兜底**，不得假定字段存在。

## 3. 由模型直接得出的实现要求

1. **Adapter** 识别「同语义不同形态」（`shake`/`poke`/`group_nudge` → poke 语义，`target` 可为 None）；**Core 只处理语义载体字段**，`if protocol == ...` 不得出现在 Core。
2. **反向发送**需要来源形态（收到 ARK 形态的合并转发须按 ARK 构造，Milky 用 ForwardSegment）；**未建模段一律进 `segments_summary` + `raw_data`**，绝不丢消息；**`json_card.app` 必须保留**——它是区分小程序/卡片/合并转发的唯一可靠依据（NapCat 与 LLBot 独立互证 `[CODE]×2`）。

## 4. Gate I：类型化覆盖率台账

实测（2026-08-09；台账 `tests/fixtures/segment_inventory.json`）：**typed 33 / known 38 = 86.8%** ✅（复现：`pytest tests/test_normalized_coverage.py -q`，覆盖率由台账算出并打印，不手填）

| 协议 | 已知段类型 | 已类型化 | 来源 |
| :--- | :--- | :--- | :--- |
| OneBot 11 家族 | 24 | 19 | `[CODE]` NapCat `OB11MessageDataType` 枚举 23 项 + LLBot 的 `shake` |
| Milky | 14 | 14 | `[CODE]` LagrangeV2 `Entity/Segment/`（13 种 incoming）+ `[DOC]` 规范的 `markdown` |
| **合计** | **38** | **33** | 每条带来源证据 |

- **仍未类型化（5 项，全在 OneBot 11 家族）**：`music`、`dice`、`rps`、`contact`、`location`——不进业务模型但**绝不丢**：原样进 `segments_summary`、`raw_data` 逐字段保真（`test_untyped_entries_are_safely_carried_by_unknown_segment` 逐条验证）。
- **防假绿**：台账必须覆盖两个协议枚举里的**每一个**类型（漏一个红灯，堵住"删条目刷覆盖率"）；每个 typed 声明都用最小样本喂**真解析器**，断言落到承诺的载体，且解析器源码里必须真的出现该类型名。

## 5. 尚未确定的维度（显式列出，避免被当成"已支持"）

- `[UNKNOWN]` Milky 其余通知类事件（撤回/管理变动/禁言/精华/群名…）只做了 kind 归一化，业务侧未消费（`notice_kind` 保留具体 event_type）。
- `[UNKNOWN]` 未细读的模型细节：SnowLuma / LLBot 的 `markdown` 完整字段与是否短路、Lagrange.Core 原生（非 Milky）元素模型、各家对 `reply` 的定位能力（Milky 内联被引段；OneBot 只给 id，需额外 API 拉取）。
- `[UNKNOWN]` NapCat / SnowLuma 是否发送 temp 事件（无实机、无源码证据）；表情类段在**发送**方向各家是否接受（只核对了 NapCat 与 Milky 的接收侧与部分发送侧）。

## 6. 已解决的缺口（原 `[UNKNOWN]`，保留结论与回归测试）

- **G1 temp 会话**：`InternalEvent.scene` + `context_group_id` 已建模；Milky `temp` 与 OneBot `private/sub_type=group` 归一为同一形态；Core 只处理群会话（`src/core/message_router.py:238`）——`tests/test_temp_scene.py`。
- **G2 请求类字段**：`request_scene` / `request_id` / `request_uid` / `request_filtered` / `comment` 进入 `InternalEvent`；`group_invitation` 由 notice 纠正为 request；两协议都不存在的字段保持空——`tests/test_request_events.py`。
- **G3 record/video/xml**：三个段载体（未知字段进各载体 `extra`）；XML 只保真 `raw_xml` **不解析**，组装层只报存在与长度——`tests/test_media_segments.py`。
- **G4 Milky 内联引用**：`reply_ref` / `reply_segments` / `reply_text` 三字段；`reply_id`（= Milky `message_seq`）不变；仅在有内联文本时渲染引用，OneBot 侧为空——`tests/test_reply_inline.py`。

