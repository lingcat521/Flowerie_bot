# 客户端兼容矩阵（Client Compatibility Matrix）

> 任务书 §五/§八/§十四 要求：逐客户端逐能力填表，**不为了填表而编造**。实现分层与「差异停在哪一层」见 [protocol-implementation.md](protocol-implementation.md)。
> 证据等级：`[CODE]` 源码 / `[DOC]` 文档 / `[FIXTURE]` 真实事件 / `[MVP]` 本地 MVP / `[INFERENCE]` 推断 / `[UNKNOWN]` 无证据。
> **§4 是首轮快照**；**机器可核对的权威矩阵是 §4.2 / §4.3**（代码生成 + 漂移测试逐字比对）。未调查完的格子一律写 `[UNKNOWN]`，不猜。
> 证据来源（可复核）：NapCatQQ `~/proto_src/NapCatQQ` @ `0b4cfe6`；Flowerie 本仓库（见 git log）；MVP 历史对照 `/storage/emulated/0/bot.py`（2026-08-07 版，1797 行）。

## 1. NapCat 的内部元素模型 [CODE]

`packages/napcat-core/types/msg.ts` 的 `ElementType` 枚举（30+ 项，节选关键项）：

| 值 | 名称 | 说明（源码注释） |
| ---: | :--- | :--- |
| 1 / 2 / 3 / 4 / 5 | `TEXT` / `PIC` / `FILE` / `PTT` / `VIDEO` | 文本 / 图片 / 文件 / 语音 / 视频 |
| 6 / 7 | `FACE` / `REPLY` | QQ 表情 / 引用 |
| **8** | **`GreyTip`** | **「小灰条」，包括拍一拍（Poke）、撤回提示等** |
| **10** | **`ARK`** | Ark 卡片（JSON 卡片走这里） |
| **11** | **`MFACE`** | 商城表情 |
| 13 / 14 / 15 | `STRUCTLONGMSG` / `MARKDOWN` / `GIPHY` | 结构化长消息 / Markdown / Giphy 动图 |
| **16** | **`MULTIFORWARD`** | 合并转发 |
| 17 / 23 / 30 | `INLINEKEYBOARD` / `TOFURECORD` / `ONLINEFOLDER` | 内联键盘 / 在线文件 id 所在元素 / 在线文件夹 |
| 43 / 44 | `RECOMMENDEDMSG` / `ACTIONBAR` | 推荐消息 / 操作栏 |

**关键结论**：poke、撤回提示这类「小灰条」在 NapCat 内部是**同一种元素**（GreyTip=8）——
所以「收到 poke」既可能出现在 notice，也可能藏在消息元素里，不能只按 OneBot 标准猜 `[CODE]`。

## 2. NapCat 的 OneBot 段词汇表 [CODE]

`packages/napcat-onebot/types/message.ts`（482 行 typebox schema）的 `OB11MessageDataType` 共 23 种段；下表把「段清单」与「字段级 schema（逐字取自源码）」合并（未列字段的段 = 源码无字段级定义）：

| 段 | 字段 |
| :--- | :--- |
| `text` | `text` |
| `face` | `id`, `resultId?`, `chainCount?`（连击数）|
| **`mface`** | `emoji_package_id`(Number), `emoji_id`(String), `key`(String), `summary`(String) |
| `at` / `reply` | `qq`, `name?` / `id?`, `seq?` |
| `poke` / `dice` / `rps` | `type`, `id` / `result` / `result` |
| `contact` / `location` | `type`, `id` / `lat`, `lon`, `title?`, `content?` |
| `json` / `xml` | `data`(Union), `config?` / `data` |
| `markdown` / `miniapp` | `content` / `data` |
| **`onlinefile`** | `msgId`, `elementId`, `fileName`, `fileSize`, `isDir`（`flashtransfer` 为 `fileSetId`）|
| `node` | `id?`, `user_id?`, `uin?`, `nickname`, `name?`, `content`, `source?`, `news?`, `summary?`, `prompt?`, `time?` |
| `forward` | `id`, `content?` |
| `image` | FileBase + `summary?`, `sub_type?` |
| `record` / `video` / `file` / `music` | FileBase（`music` 只在词汇表里有段名，未见字段定义）|

**FileBase**（`FileBaseDataSchema`）：`file`（必填，路径/URL/`file://`）、`path?`、`url?`、`name?`、`thumb?`

## 3. 合并转发与 JSON 卡片：NapCat 的真实做法 [CODE]

`packages/napcat-onebot/action/msg/SendMsg.ts`（514 行）的三条关键证据：

### 3.1 合并转发 = 上传 protobuf + 发一个 ARK 段

```ts
// 发送 L324-346
const resid = await this.core.apis.PacketApi.pkt.operation.UploadForwardMsgV2(uploadMsgData, ...);
return { finallySendElements: { elementType: ElementType.ARK,
  arkElement: { bytesData: JSON.stringify(ForwardMsgBuilder.fromPacketMsg(resid, packetMsg, ...)) } }, res_id: resid };
```

→ **合并转发在线上就是一个 `arkElement`**，内容里带 `resid`；内层消息体早已上传到服务器 `[CODE]`。

### 3.2 接收侧靠 ARK JSON 的 `app` 字段识别合并转发

```ts
// SendMsg.ts L289-297（处理转发节点时反向识别）
} else if (element.arkElement?.bytesData) {
  const json = JSON.parse(element.arkElement.bytesData);
  if (json.app === com.tencent.multimsg) { resId = json.meta?.detail?.resid; uuid = json.meta?.detail?.uniseq || json.extra?.filename; }
}
```

→ **`{"type":"json"}` 不是一种东西**：`app === com.tencent.multimsg` 的才是合并转发卡片，要从 `meta.detail.resid` 取内层；其他 app（小程序、联系人卡片、markdown…）语义不同 `[CODE]`。

### 3.3 发送时的元素分组规则（⚠️ 已更正）

`SendMsg.ts` L411-431 的 `MixElement` / `SingleElement` 拆分（FILE/VIDEO/ARK/PTT 被拆成「单独一条消息」）**只在
`handleForwardedNodes`（合并转发节点路径）内部**：全文**仅 L417 一处** `elementType ===` 比较，普通发送路径（`normalize()`
L53-60 → `createSendElements`）**没有**任何拆分 `[CODE]`。Flowerie 因此**不做**发送侧拆分（详见 `protocol-reverse-engineering.md` §9 C1）。
→ **真正有意义的约束**：合并转发 `node.content` 里**只能放 `node` 段** —— 混入其他段时 NapCat 记 error 并 `continue`，**整个节点被丢弃**（L392-397）`[CODE]`。

## 4. 能力矩阵（第一版）

> ⚠️ 本表是**各客户端混合的首轮快照**（含 MVP 对照列）；权威矩阵见 §4.2 / §4.3。

| 能力 | OneBot 11 规范 | NapCat | Lagrange | Milky | SnowLuma | LLBot | Flowerie 现状 | MVP |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 文本收发 | [DOC] 段 `text` | [CODE] `text` | [UNKNOWN] | [DOC] `text` | [UNKNOWN] | [UNKNOWN] | [CODE] 已支持 | [MVP] 已支持 |
| 图片接收 | [DOC] `image`(file/url) | [CODE] FileBase+summary/sub_type | [UNKNOWN] | [DOC] `image`(temp_url/resource_id) | [UNKNOWN] | [UNKNOWN] | [CODE] url/file 提取 | [MVP] **未实现** |
| 图片发送 | [DOC] `image` | [CODE] SendPicElement | [UNKNOWN] | [DOC] `image` 段 | [UNKNOWN] | [UNKNOWN] | [CODE] 走 sender 段数组/图片路径 | [UNKNOWN] |
| QQ 表情 face | [DOC] `face` | [CODE] `{id,resultId?,chainCount?}` | [UNKNOWN] | [DOC] `face{face_id}` | [UNKNOWN] | [UNKNOWN] | [CODE] **已建模** `faces`（连击/大表情渲染进上下文，上限 3 条）| [MVP] 未处理 |
| 商城表情 mface | [DOC] 非标准 | [CODE] `{emoji_package_id,emoji_id,key,summary}` | [UNKNOWN] | [DOC] `market_face`（实现只有 `url`）| [UNKNOWN] | [UNKNOWN] | [CODE] **已建模**（`faces` kind=market_face，无描述时不退化渲染）| [MVP] 未处理 |
| 文件接收（消息段 / notice）| [DOC] `file` / `group_upload` | [CODE] FileBase / `OB11GroupUploadNoticeEvent` | [UNKNOWN] | [DOC] `file` / 文件事件 | [UNKNOWN] | [UNKNOWN] | [CODE] **已分类** `files`（`file_id/name/size/url/path`；NapCat 无 file_id 与 LLBot 有 file_id 均兜底）+ `notice_file` 走 `/get_file` 下载解码 | [MVP] url+base64 信封 / 同左 |
| 文件发送 | [DOC] `upload_group_file` | [CODE] 独占一条消息（§3.3） | [UNKNOWN] | [DOC] 上传 API | [UNKNOWN] | [UNKNOWN] | [CODE] **未接线**（`capabilities.py` FILE_SEND=PARTIAL；原标「待核对」）| [UNKNOWN] |
| 合并转发接收 | [DOC] `forward`/`node` | [CODE] ARK+resid 或 MULTIFORWARD | [UNKNOWN] | [DOC] `get_forwarded_messages` | [UNKNOWN] | [UNKNOWN] | [CODE] 递归展开+预算控制 + **ARK multimsg 卡片按 `resid` 拉内层**（强于 MVP）| [MVP] 递归收 text |
| JSON 卡片 | [DOC] `json` | [CODE] `{data,config?}`，靠 `app` 区分 | [UNKNOWN] | [DOC] 无 | [UNKNOWN] | [UNKNOWN] | [CODE] **已区分 `app`**：`json_cards` 保留 `app/is_forward_card`，`com.tencent.multimsg` 走转发拉内层 | [MVP] 黑名单过滤收集 |
| poke（notice） | [DOC] `notice/notify/poke` | [CODE] `OB11PokeEvent` | [UNKNOWN] | [DOC] `send_group_nudge` | [UNKNOWN] | [UNKNOWN] | [CODE] 已支持（target 回退链齐全） | [MVP] 同左 |
| poke（消息段） | [DOC] 非标准 | [CODE] `poke{type,id}` + GreyTip(8) | [UNKNOWN] | [DOC] 无（Milky 是 `group_nudge` 事件）| [UNKNOWN] | [CODE] `shake{}`（face type=Poke，无目标）| [CODE] **已建模** `pokes`（含 shake，target 可为 None）| [MVP] 未处理 |
| 在线文件 | — | [CODE] `onlinefile{msgId,elementId,fileName,fileSize,isDir}` | [UNKNOWN] | [DOC] 无 | [UNKNOWN] | [UNKNOWN] | [CODE] **已建模** `files.sub_type=onlinefile`（`onebot_parser.py:377`，另有 `flashtransfer`）| [UNKNOWN] |
| markdown | — | [CODE] `markdown{content}` | [UNKNOWN] | [DOC] `markdown{content}`（since 1.3，两份实现都无）| [UNKNOWN] | [UNKNOWN] | [CODE] **内容并入** `text` | [UNKNOWN] |

### 4.1 Milky 列的证据（Lagrange.Milky / LLBot 实现 `[CODE]` + 规范 `[DOC]`）

> Milky 列以 **LLBot 的 Milky 实现**（`~/proto_src/LLBot/src/milky/transform/message/incoming.ts`，252 行）+ 规范 `SaltifyDev/milky` 互证；
> **更权威的第二来源**是协议作者本人的实现 —— 内嵌在 `Lagrange.Core` / `LagrangeV2` 的 `Lagrange.Milky/`（119 个 .cs；两份副本**布局不同**：
> V2 `Entity/Segment/` 15 文件 / 13 种段，Core `Models/Segments/` 11 文件 / 10 种段），见 [protocol-reverse-engineering.md](protocol-reverse-engineering.md) §6（早期曾误判「Lagrange.Milky 实现仓库不可得」，实为内嵌 —— 见 source-acquisition.md「状态更正」）。

| 能力 | Milky 段与字段 [CODE] |
| :--- | :--- |
| 文本 / @ | `text{text}`；**@ 不是独立元素**，而是 Text 元素的 `atType`：`One`→`mention{user_id,name}`、`All`→`mention_all{}` |
| 图片 | `image{resource_id(fileUuid), temp_url, width, height, summary, sub_type(sticker/normal)}`（`picSubType===1` → `sticker`） |
| QQ 表情 / 商城表情 | `face{face_id: faceIndex.toString(), is_large: faceType===3}` / `market_face{emoji_package_id, emoji_id, key, summary, url}`（url 由 emoji_id 拼 `gxh.vip.qq.com` 路径） |
| 语音 / 视频 | `record{resource_id,temp_url,duration}` / `video{resource_id,temp_url,width,height,duration}` |
| 文件（消息段） | `file{file_id(fileUuid), file_name, file_size}`（**无 url**，需另走下载接口） |
| 合并转发 | `forward{forward_id, title, preview[], summary}`；来源二选一：`MultiForward` 元素的 **XML `xmlContent`**（`resId`），或 **Ark**（`app=com.tencent.multimsg` → `meta.detail.resid`） |
| JSON/Ark 卡片 | **按 `app` 分流**：`com.tencent.multimsg` → `forward`；其它 → `light_app{app_name, json_payload}` |
| 引用 | `reply{message_seq, sender_id, time, segments[]}` —— **内联携带被引消息的完整段数组**（与 OneBot 只给 `id` 完全不同） |
| markdown | `markdown{content}`，且**短路**：只要消息里有 markdown 元素，其余元素一律不产出 |
| 临时会话 | `message_scene = temp`（OneBot 侧叫 `group_temp`；Flowerie 归一成 `scene=temp` + `scope=private` + `context_group_id`） |

**对 Flowerie 的直接影响（已落地见 [milky-protocol.md](milky-protocol.md)）**：① `reply` 段自带被引内容 → 归一化层把内联段也归一
（`reply_segments`/`reply_text`），不丢弃；② `mention`/`mention_all` 是 Text 元素属性 → 不能只按「段类型」判断 @；
③ `image.sub_type=sticker` 是**图片形式的表情包**，与 `face`/`market_face` 是三回事；④ `temp` 场景归一成私聊 + `context_group_id`（不新增第三类会话）。

### 4.2 客户端档案矩阵（**由代码生成**，勿手改）

> 数据源：`src/adapters/client_profile.py::PROFILES`；生成：`python3 -c "from src.adapters.client_profile import render_matrix; print(render_matrix())"`；
> 漂移保护：`tests/test_client_contract_matrix.py::test_doc_matrix_matches_code` 逐字比对下表。四态：`SUPPORTED` 有源码/规范证据；`PARTIAL` 只支持一部分
> （如 forward 只能按 id 下载）；`UNSUPPORTED` 证据表明**不存在**；`UNKNOWN` 没查到 —— 空格是信息，不是待办勾。

<!-- BEGIN GENERATED: client-matrix -->
| 能力 | go-cqhttp | lagrange | llbot | napcat | spec |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `text` | SUPPORTED | UNKNOWN | SUPPORTED | SUPPORTED | SUPPORTED |
| `face` | SUPPORTED | UNKNOWN | SUPPORTED | SUPPORTED | SUPPORTED |
| `image` | SUPPORTED | UNKNOWN | SUPPORTED | SUPPORTED | SUPPORTED |
| `record` | SUPPORTED | UNKNOWN | UNKNOWN | SUPPORTED | SUPPORTED |
| `video` | SUPPORTED | UNKNOWN | UNKNOWN | SUPPORTED | SUPPORTED |
| `at` | SUPPORTED | UNKNOWN | SUPPORTED | SUPPORTED | SUPPORTED |
| `reply` | SUPPORTED | UNKNOWN | SUPPORTED | SUPPORTED | SUPPORTED |
| `json` | SUPPORTED | UNKNOWN | SUPPORTED | SUPPORTED | SUPPORTED |
| `xml` | SUPPORTED | UNKNOWN | UNKNOWN | SUPPORTED | SUPPORTED |
| `share` | SUPPORTED | UNKNOWN | UNKNOWN | UNSUPPORTED | SUPPORTED |
| `music` | SUPPORTED | UNKNOWN | UNKNOWN | SUPPORTED | SUPPORTED |
| `poke` | SUPPORTED | UNKNOWN | SUPPORTED | SUPPORTED | SUPPORTED |
| `dice` | SUPPORTED | UNKNOWN | UNKNOWN | SUPPORTED | SUPPORTED |
| `rps` | SUPPORTED | UNKNOWN | UNKNOWN | SUPPORTED | SUPPORTED |
| `mface` | UNSUPPORTED | UNKNOWN | UNKNOWN | SUPPORTED | UNSUPPORTED |
| `file` | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | UNSUPPORTED |
| `markdown` | UNSUPPORTED | UNKNOWN | UNKNOWN | SUPPORTED | UNSUPPORTED |
| `forward_segment` | PARTIAL | SUPPORTED | UNKNOWN | SUPPORTED | PARTIAL |
<!-- END GENERATED: client-matrix -->

Lagrange 列只有 `[DOC]`（实现源码 **SOURCE_UNAVAILABLE**）：文档只写了 File/Node 两类段，其余保持 UNKNOWN，**没有**因为"它参考了规范"就填 SUPPORTED。

### 4.3 Milky 客户端档案矩阵（同样由代码生成）

> 数据源：`render_matrix("milky")`；漂移测试同上（`test_doc_matrix_matches_code` 逐字比对两块表）。
> 与 §4 的 Milky 列互为补充：§4 讲**入站段**，这里讲**档案登记的能力**（含出站）。

<!-- BEGIN GENERATED: milky-matrix -->
| 能力 | lagrange | llbot | spec |
| :--- | :--- | :--- | :--- |
| `text` | SUPPORTED | SUPPORTED | SUPPORTED |
| `face` | SUPPORTED | SUPPORTED | SUPPORTED |
| `image` | SUPPORTED | SUPPORTED | SUPPORTED |
| `record` | SUPPORTED | UNKNOWN | SUPPORTED |
| `video` | SUPPORTED | UNKNOWN | SUPPORTED |
| `at` | UNKNOWN | UNKNOWN | UNKNOWN |
| `reply` | SUPPORTED | SUPPORTED | SUPPORTED |
| `json` | UNKNOWN | UNKNOWN | UNKNOWN |
| `xml` | UNKNOWN | UNKNOWN | UNSUPPORTED |
| `share` | UNKNOWN | UNKNOWN | UNKNOWN |
| `music` | UNKNOWN | UNKNOWN | UNKNOWN |
| `poke` | UNKNOWN | UNKNOWN | UNKNOWN |
| `dice` | UNKNOWN | UNKNOWN | UNKNOWN |
| `rps` | UNKNOWN | UNKNOWN | UNKNOWN |
| `mface` | UNKNOWN | UNKNOWN | UNKNOWN |
| `file` | UNKNOWN | UNKNOWN | UNSUPPORTED |
| `markdown` | UNKNOWN | UNKNOWN | UNSUPPORTED |
| `forward_segment` | UNKNOWN | UNKNOWN | UNKNOWN |
<!-- END GENERATED: milky-matrix -->

Lagrange 的 Milky 实现是**协议作者本人的实现**（内嵌 Lagrange.Core/V2，两份副本段集合不同），LLBot 的是第三方实现 —— 两者在 `mention` 私聊行为与段集合上有差异
（见 [reverse-engineering/milky/](reverse-engineering/milky/)）。**未调查**的 Milky 客户端不登记，查询得到 UNKNOWN。注意 `at`/`json`/`xml` 等格子是**段名**维度：Milky 的 @ 是 Text 元素属性、JSON 卡片走 `light_app`（§4.1），所以显示 UNKNOWN 而非 SUPPORTED。

## 6. 生态覆盖清单（Ecosystem Coverage）

> 由用户提供的 OneBot11 / Milky 生态清单整理而成。**分层判定价值**：协议端（实现端）决定**线上 JSON 形态** → 必须逐个核对 `[CODE]`；SDK / 框架绝大多数只是
> **消费**同一套形态，不新增 wire 信息（只有 imhelper 这类「统一客户端 SDK」与 adapter-onebot 这类兼容层会暴露字段兼容策略，按需抽查）；工具 / 中间件与协议形态无关。
> 状态词表与逐仓库明细见 [source-acquisition.md](source-acquisition.md)；**未取得源码的一律标 `NOT_INVESTIGATED`，不假装看过**。

### 6.0 一览（截至 2026-08-09）
**源码获取**：**15 个仓库 / 369M 已取得**，1 个 `SOURCE_UNAVAILABLE`（OpenShamrock）。**能力覆盖的证据密度**（按 message-model.md §3 的 14 行能力表**逐格统计标注** —— 报告的是标注密度，不是重新审计）：

| 客户端 | [CODE] | [DOC] | [UNKNOWN] | 说明 |
| :--- | ---: | ---: | ---: | :--- |
| NapCat | **14** | 0 | 0 | 唯一逐格全 [CODE] 的协议端（§1–§3）|
| SnowLuma | **14** | 0 | 0 | 段编解码层逐格有据 |
| Milky | 11 | 3 | 2 | 实现内嵌 LagrangeV2/Core（两份副本）+ 规范互证（§4.1、§4.3）|
| LLBot（OneBot）| 10 | 0 | 3 | OneBot 实现侧；Milky 侧计入 Milky 列 |
| OneBot 11 规范 | 1 | 9 | 2 | 规范文档级参照（`[DOC]` 为主）|

**生态分层**（"已取得并核对" = 字段定义被逐行读过且结论以 `[CODE]` 落进文档；"已取得未逐行核对" = 仓库在本地但**不声称支持**）：

| 层 | 已取得并核对 | 已取得未逐行核对 | 未调查 | 不可得 |
| :--- | :--- | :--- | :--- | :--- |
| 协议端（决定 wire 形态）| NapCatQQ、LLBot、Lagrange.Milky（内嵌）| Lagrange.OneBot、go-cqhttp | onebots、Yogurt、onebot-kotlin | OpenShamrock |
| SDK / 框架（消费侧）| NoneBot2 + adapter-onebot、SnowLuma | Koishi、Kovi、ROneBot、milky-python-sdk | imhelper 及 40+ 项（见 §6.2）| — |
| 规范 / 文档 | OneBot11-spec、Milky-spec | Lagrange.Milky.Document（仅文档）| — | — |
| 工具 / 中间件 | — | — | matcha、nonebot-plugin-all4one | — |

**行动结论**：① 必须逐个核对 wire 形态的协议端里，只剩 **onebots / Yogurt**（仓库地址未确认）与 **OpenShamrock**（不可得 → 不声称支持）；② 消费侧 SDK 的差异靠**宽容解析 + unknown 保留**覆盖，不为每个 SDK 写分支；③ 未调查项不影响归一化层的正确性 —— 它们消费的是同一套形态；④ onebots 与 ROneBot 提到 OneBot **v12** —— 本仓库只支持 v11（v12 骨架**未接线**，见 [onebot12-research.md](onebot12-research.md)）。

### 6.1 协议端（OneBot 11）
| 项目 | 语言 | 状态 | 说明 |
| :--- | :--- | :--- | :--- |
| NapCatQQ / LLBot / Lagrange.Milky | TS / TS / C# | **SOURCE_OBTAINED**（均已逆向） | 分别见 §1–§3 / §4 / §4.1+§4.3；LLBot 同时实现 OneBot 11 与 Milky |
| Lagrange.OneBot | C# | **SOURCE_UNAVAILABLE** | 2026-09-25 复核：LagrangeDev/Lagrange.OneBot HTTP 404；本地 Lagrange.Core/V2 无 OneBot 代码（source-acquisition.md C4）→ 只能靠 [DOC]（Lagrange.Doc，页面自称过时）|
| OpenShamrock | Kotlin/Java | **SOURCE_UNAVAILABLE** | 原仓库（whitechi73/OpenShamrock）不可得：clone 报 could not read Username，仓库搜索只剩第三方分支；**未逆向，不声称支持** |
| go-cqhttp | Go | **SOURCE_OBTAINED** a5923f1（121 文件） | 已归档，但**是事实基线**（很多实现模仿它的字段） |
| onebots / Yogurt / onebot-kotlin | ? | `NOT_INVESTIGATED` | 前两个是 OneBot v11/v12 + Satori + Milky 的多协议服务端 / Milky 协议端，**仓库地址未确认**；onebot-kotlin 未查 |
| oicq / OneBot-YaYa / coolq-http-api / PicqBotX / Gensokyo / KookOneBot | — | `ARCHIVED` / `NOT_INVESTIGATED` | 历史实现仅在解释遗留字段时参考；Gensokyo / KookOneBot 非 QQ 平台（开黑啦/Discord），与本任务无关 |

### 6.2 SDK / 框架
| 项目 | 语言 | 状态 | 价值判定 |
| :--- | :--- | :--- | :--- |
| NoneBot2 + adapter-onebot | Python | **SOURCE_OBTAINED** | **高**：规范级参照（`poke{type,id}` 有工厂方法），兼容策略在 `v11/compat.py` |
| Koishi / Kovi / ROneBot / milky-python-sdk | TS / Rust / Kotlin / Python | **SOURCE_OBTAINED**（5525cfd·186 文件 / 9decea5·114 / b39550f·368 / 805b194·182） | 中-中高：OneBot 适配器字段处理；Kovi 同时支持 Milky/OneBot（可交叉验证）；ROneBot 覆盖 OneBot11/12 + Milky；milky-python-sdk 提供 Milky 字段视角 |
| imhelper | TS | `NOT_INVESTIGATED` | **高**（若取到）：统一客户端 SDK，覆盖 OneBot v11/v12 + Satori + Milky —— 与 Flowerie 同类问题 |
| AstrBot / LangBot / Graia / ZeroBot / NsxBot / Shiro / makabaka / OlivOS / 炸毛 / Simbot / Adachi-BOT / PepperBot / melobot / AlemonJS / MuRainBot2 / NcatBot / napcat-sdk / OneBotConnecter / eridanus-dep / qcrbot-sdk / yiri-onebot / AliceBot / Overflow / kira_framework / walle-core / oxidebot / onebotv11_rs / runbot / onebot-client-next / shirosaki-onebot / @zhinjs/adapter-onebot-11 / Zhin.js / Karin / nagisa / satori-python-adapter-milky / @imhelper/milky-v1 / @onebots/protocol-milky-v1 / @zhin.js/adapter-milky / karin-plugin-adapter-milky / Saltify core / Vivian / nagisa-milky / Milky.Net.Model / milky-types / @saltify/milky-protocol / milkygen | 多语言 | `NOT_INVESTIGATED` | 低-中：**消费同一套 wire 形态**，除非发现某实现有独特字段，否则不逐个逆向；`@saltify/milky-protocol`（= `SaltifyDev/milky` 的 IR）**已取得** |

### 6.3 工具 / 中间件
| 项目 | 状态 | 说明 |
| :--- | :--- | :--- |
| matcha（模拟聊天交互）/ nonebot-plugin-all4one（NoneBot 2 → OneBot 12） | `NOT_INVESTIGATED` | 前者是开发辅助工具，不改变协议形态；后者是协议转换插件，**若 Flowerie 未来支持 v12 可作为参考** |

> 原 §5「待办（下一轮）」6 项已全部完成（SnowLuma / Lagrange.Core+V2 / LLBot 双协议 / NoneBot2 adapter-onebot / OneBot 11 规范逐段 / Milky 实现内嵌），Milky 段与 21 种事件类型的归一化见 [milky-protocol.md](milky-protocol.md)。
> 说明（2026-08-09 更新）：§4 的**客户端列**是第一版快照 —— Lagrange / SnowLuma / LLBot 的多数格子仍标 `[UNKNOWN]`，其实际证据写在 protocol-reverse-engineering.md §4（LLBot 双协议）与 §6（Lagrange.Milky）；**未逐格回填**是为了不把「某一处已核对」扩写成「整列已核对」（任务书 §22）。
