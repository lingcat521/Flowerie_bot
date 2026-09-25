# Flowerie 统一消息模型（Unified Message Model）v1

> 任务书 §十三/§二十一：Core 与 Plugin 只面对 **Normalized Event**，不得出现 `if napcat` / `if lagrange`。
>
> 本文只写**已被源码证据支持**的部分；每行标注证据等级。没有证据的维度一律写 `[UNKNOWN]`，不猜。

## 1. 设计原则（由证据倒逼出来的三条）

1. **按语义建模，不按段类型名建模** `[CODE]`：同一个用户动作在不同协议里是不同的段名 ——
   戳一戳在 Milky 是事件 `group_nudge`、在 NapCat 是 `poke` 段 + GreyTip 元素、在 LLBot 的 OneBot 是 `shake` 段；
2. **保留原始协议维度** `[CODE]`：合并转发在 OneBot 侧可能表现为 `forward` / `node` / `json(app=com.tencent.multimsg)` /
   `light_app` / Milky 的 `ForwardSegment` —— 归一化时**必须记录来源形态**，否则无法反向发送；
3. **信息缺失要显式** `[CODE]`：LLBot 的 `shake{}` 段**不带目标**，Milky 的 `group_nudge` 带 `receiver_id`；
   归一化层要把「目标未知」表达成显式状态，而不是补 0 或猜。

## 2. 归一化实体（NormalizedEvent / NormalizedSegment）

```text
NormalizedEvent
 ├── kind: message | notice | request | lifecycle
 ├── scene: group | private | temp            # temp 来自 Milky TempMessage / LLBot message_scene=temp [CODE]
 ├── group_id / actor_id / target_id?          # target 缺失时显式为 None（不许猜）
 ├── message_id / timestamp
 ├── segments: [NormalizedSegment]             # 仅 message
 ├── notice: {kind, sub_kind, ...}             # 仅 notice（含 poke/nudge）
 ├── raw: {protocol, client?, payload}         # 原始负载整包保留，供适配层反查
 └── evidence: {protocol, shape}               # 记录它原本长什么样（见原则 2）
```

```text
NormalizedSegment（kind 为语义类型，attrs 为已归一字段）
 ├── text        {text}
 ├── mention     {user_id, display?}                       # Milky: Text 元素 atType=One [CODE]
 ├── mention_all {}
 ├── reply       {message_id, sender_id?, time?, quoted_segments?}   # Milky 内联 quoted_segments [CODE]
 ├── image       {source, file_id?, url?, width?, height?, size?, is_sticker}  # is_sticker 来自 sub_type/subType [CODE]
 ├── face        {face_id, is_large?}                      # QQ 表情
 ├── market_face {emoji_id, package_id?, key?, summary?, url?}          # 商城表情
 ├── file        {file_id?, name?, size?, url?, path?}     # 各家字段集不同 [CODE]
 ├── audio       {source, duration?}
 ├── video       {source, duration?, thumb?}
 ├── forward     {forward_id, title?, preview[]?, summary?, nodes?}     # 形态多样 [CODE]
 ├── json_card   {app, payload}                            # app 必须保留（见原则 1）[CODE]
 ├── xml         {payload}
 ├── markdown    {content}
 ├── poke        {poke_type?, poke_id?, target?}           # NapCat poke 段 / OneBot 规范段 [CODE]
 ├── shake       {target: None}                            # LLBot 的窗口抖动，无目标 [CODE]
 └── unknown     {raw_type, raw_data}                      # 未建模的段，但绝不丢
```

## 3. 证据映射表（协议 → 归一化）

| 归一化 kind | OneBot 11（规范/NoneBot） | NapCat | LLBot(OneBot) | SnowLuma | Milky（作者实现/LLBot） |
| :--- | :--- | :--- | :--- | :--- | :--- |
| text | `text{text}` `[DOC]` | `text` `[CODE]` | `text` `[CODE]` | `text` `[CODE]` | `text{text}` `[CODE]` |
| mention | `at{qq}` `[DOC]` | `at{qq,name?}` `[CODE]` | `at{qq}` `[CODE]` | `at{qq}` `[CODE]` | **Text 元素 atType=One → `mention{user_id,name}`** `[CODE]` |
| mention_all | `at{qq=all}` `[DOC]` | `at{qq=all}` `[CODE]` | `at{qq=all}` `[CODE]` | `at{uid=all,targetUin=0}` `[CODE]` | `mention_all{}` `[CODE]` |
| image | `image{file,url?}` `[DOC]` | `image{file,path?,url?,name?,thumb?,sub_type?,summary?}` `[CODE]` | `image{file,subType,url,file_size}` `[CODE]` | `image{...}` `[CODE]` | `image{resource_id,temp_url,width,height,summary,sub_type}` `[CODE]` |
| face | `face{id}` `[DOC]` | `face{id,resultId?,chainCount?}` `[CODE]` | `face{id,sub_type}` `[CODE]` | `face{id}` `[CODE]` | `face{face_id}`（副本 A；规范另有 `is_large` since 1.1）`[CODE]`/`[DOC]` |
| market_face | 非标准 | `mface{emoji_package_id,emoji_id,key,summary}` `[CODE]` | `mface{...,url}` `[CODE]` | `mface` `[CODE]` | `market_face{url}`（**副本 A 实现只有 url**；规范另有 emoji_package_id/emoji_id/key/summary）`[CODE]`/`[DOC]` |
| file | `file{file,url?,file_id?}` `[DOC]` | FileBase（**无 file_id**）`[CODE]` | `file{file,url(file://),file_id,path,file_size}` `[CODE]` | `file{fileId,url}` `[CODE]` | `file{file_id,file_name,file_size,file_hash?}`（**无 url**）`[CODE]` |
| forward | `forward{id}` / `node{...}` `[DOC]` | ARK(`app=com.tencent.multimsg`) 或 MULTIFORWARD/`forward{id,content?}` `[CODE]` | `forward`（由 MultiForward XML 或 Ark 而来）`[CODE]` | `forward` `[CODE]` | `ForwardSegment{forward_id,title,preview,summary}`（独立段）`[CODE]` |
| json_card | `json{data}` `[DOC]` | `json{data,config?}`（**app 分流**）`[CODE]` | `json{data}`（不分流，交给上层）`[CODE]` | `json{data}` `[CODE]` | **`LightAppSegment{app_name,json_payload}`**（独立段；**app 在 payload 内**，`com.tencent.multimsg` 判定同样适用）`[CODE]` |
| xml | `xml{data}` `[DOC]` | `xml{data}` `[CODE]` | — `[UNKNOWN]` | `xml` `[CODE]` | `XmlSegment{service_id,xml_payload}`（**仅副本 A**）`[CODE]` |
| markdown | 非标准 | `markdown{content}`（并**短路**其它元素）`[CODE]` | `markdown`（未细读）`[UNKNOWN]` | `markdown` `[CODE]` | `markdown{content}` —— **规范有（since 1.3）、两份内嵌实现都无**`[DOC]`（Flowerie 已按内容并入 `text`）|
| poke | **`poke{type,id}` 是规范段**（NoneBot adapter 有工厂）`[CODE]` | `poke{type,id}` 段 + notice + GreyTip(8) 元素 `[CODE]` | **`face(faceType=Poke)` → `shake{}`** `[CODE]` | `poke` 段 `[CODE]` | **事件** `group_nudge{group_id,sender_id,receiver_id,display_action,display_suffix,display_action_img_url}` `[CODE]×2` |
| 闪传/在线文件 | — `[UNKNOWN]` | `flashtransfer{fileSetId}`、`onlinefile{msgId,elementId,fileName,fileSize,isDir}` `[CODE]` | — `[UNKNOWN]` | `flash_file` `[CODE]` | — `[UNKNOWN]` |
| inline_keyboard | — `[UNKNOWN]` | ElementType.INLINEKEYBOARD(17) `[CODE]` | — | `inline_keyboard` 段 `[CODE]` | — `[UNKNOWN]` |

> **Milky 列的"作者实现"有**两份布局不同**的内嵌副本，勿混用**（均为 `[CODE]`，见 protocol-reverse-engineering.md §6.1 / §9 C2）：
> - **副本 A** `LagrangeV2/Lagrange.Milky/Entity/Segment/`：15 个文件 / **13 种** incoming（含 face / market_face / xml，无 markdown）；
> - **副本 B** `Lagrange.Core/Lagrange.Milky/Models/Segments/`：11 个文件 / **10 种** incoming（无 face / market_face / xml / markdown）。
>
> 且**实现字段比规范窄**（副本 A 的 `market_face` 只有 `url`、`face` 只有 `face_id`）——
> 解析一律**逐字段兜底**，不得假定字段存在；上表标注 A/B 差异处即为此。

## 4. 由模型直接得出的实现要求（P4 的输入）

1. **Adapter 负责**：识别「同语义不同形态」（如 `shake`/`poke`/`group_nudge` → `poke` 语义 + `target` 可能为 None）；
2. **Core 只处理 NormalizedSegment**，`if protocol == ...` 一律不允许出现在 Core（任务书 §十六）；
3. **反向发送**需要 `evidence.shape`：例如收到的是 ARK 形态的合并转发，回复时必须按 ARK 形态构造（Milky 则用 ForwardSegment）`[CODE]`；
4. **未建模段一律进 `unknown`**，保留 `raw_type/raw_data`，绝不丢消息（任务书 §十八.9）；
5. **`json_card.app` 必须保留** —— 它是区分小程序/卡片/合并转发的唯一可靠依据（NapCat 与 LLBot 独立互证）`[CODE]×2`。

## 5. 尚未确定的维度（显式列出，避免以后被当成"已支持"）

- `[UNKNOWN]` SnowLuma / LLBot 的 `markdown` 完整字段与是否短路；
- ~~Milky 请求类事件字段级映射~~ **已解决（G2）**：`request_scene` / `request_id` / `request_uid` /
  `request_filtered` / `comment` 已进入 `InternalEvent`；`group_invitation` 由 notice 纠正为 request；
  两协议都不存在的字段保持空（`tests/test_request_events.py`）；
- `[UNKNOWN]` Milky 其余通知类事件（撤回 / 管理变动 / 禁言 / 精华 / 群名 …）同样只做了 kind 归一化，业务侧未消费（`notice_kind` 保留具体 event_type）；
- `[UNKNOWN]` Lagrange.Core 原生（非 Milky）元素模型（本轮只深入了它内嵌的 Milky 实现）；
- `[UNKNOWN]` 各家对 `reply` 的定位能力（Milky 内联被引段；OneBot 只给 id → 需要额外 API 拉取）；
- ~~`[UNKNOWN]` `temp`（临时会话）~~ **已解决（G1）**：`InternalEvent.scene` + `context_group_id` 已建模；
  Milky `temp`（规范 L284-291）与 OneBot `private/sub_type=group`（规范 L16）归一为同一形态，
  Core 只处理群会话（`_handle_message` 首行 scope 判断）这一边界已写入 `tests/test_temp_scene.py`；
  NapCat / SnowLuma 侧是否发送 temp 事件仍属 `[UNKNOWN]`（无实机、无源码证据）；
- `[UNKNOWN]` 表情类段在**发送**方向各家是否接受（本轮只核对了 NapCat 与 Milky 的接收侧与部分发送侧）。
- **已知缺口（不是 `[UNKNOWN]`，而是"证据已得、尚未消费"）**：
  - ~~Milky `reply.segments` 未被消费~~ **已解决（G4）**：`reply_ref` / `reply_segments` / `reply_text` 三字段；
    `reply_id`（= Milky `message_seq`）保持不变；组装层仅在有内联文本时渲染引用，OneBot 侧为空；
  - ~~`record` / `video` / `xml` 未建模~~ **已解决（G3）**：`InternalEvent.records/videos/xmls` 三个段载体，
    两侧解析器复用同一组归一化函数；未知字段进各载体的 `extra`（§5.4）；
    XML 只保真保存 `raw_xml`，**不解析**（§5.3），组装层只报存在与长度。
