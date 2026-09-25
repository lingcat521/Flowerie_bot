# 客户端兼容矩阵（Client Compatibility Matrix）

> 任务书 §五/§八/§十四 要求：逐客户端逐能力填表，**不为了填表而编造**。
> 证据等级：`[CODE]` 源码 / `[DOC]` 文档 / `[FIXTURE]` 真实事件 / `[MVP]` 本地 MVP / `[INFERENCE]` 推断 / `[UNKNOWN]` 无证据。
>
> **当前进度**：NapCat 已完成源码级调查（本轮）；其余客户端源码已就位（见 source-acquisition.md），
> 逐列调查进行中 —— 未调查完的格子一律写 `[UNKNOWN]`，不猜。

## 0. 证据来源（可复核）

| 项目 | 本地路径 | HEAD |
| :--- | :--- | :--- |
| NapCatQQ | `~/proto_src/NapCatQQ` | `0b4cfe6` |
| Flowerie | 本仓库 | 见 git log |
| MVP | `/storage/emulated/0/bot.py` | 2026-08-07 版本（1797 行） |

## 1. NapCat 的内部元素模型 [CODE]

`packages/napcat-core/types/msg.ts` 的 `ElementType` 枚举（30+ 项，节选关键项）：

| 值 | 名称 | 说明（源码注释） |
| ---: | :--- | :--- |
| 1 | `TEXT` | 文本 |
| 2 | `PIC` | 图片 |
| 3 | `FILE` | 文件 |
| 4 | `PTT` | 语音 |
| 5 | `VIDEO` | 视频 |
| 6 | `FACE` | QQ 表情 |
| 7 | `REPLY` | 引用 |
| **8** | **`GreyTip`** | **「小灰条」，包括拍一拍（Poke）、撤回提示等** |
| **10** | **`ARK`** | Ark 卡片（JSON 卡片走这里） |
| **11** | **`MFACE`** | 商城表情 |
| 13 | `STRUCTLONGMSG` | 结构化长消息 |
| 14 | `MARKDOWN` | Markdown |
| 15 | `GIPHY` | Giphy 动图 |
| **16** | **`MULTIFORWARD`** | 合并转发 |
| 17 | `INLINEKEYBOARD` | 内联键盘 |
| 23 | `TOFURECORD` | 在线文件 id 所在元素 |
| 30 | `ONLINEFOLDER` | 在线文件夹 |
| 43/44 | `RECOMMENDEDMSG` / `ACTIONBAR` | 推荐消息 / 操作栏 |

**关键结论**：poke、撤回提示这类「小灰条」在 NapCat 内部是**同一种元素**（GreyTip=8）——
所以「收到 poke」既可能出现在 notice，也可能藏在消息元素里，不能只按 OneBot 标准猜 `[CODE]`。

## 2. NapCat 的 OneBot 段词汇表 [CODE]

`packages/napcat-onebot/types/message.ts`（482 行，typebox schema）定义 `OB11MessageDataType`：

`text` `image` `music` `video` `record` `file` `at` `reply` `json` `face` `mface` `markdown`
`node` `forward` `xml` `poke` `dice` `rps` `miniapp` `contact` `location` `onlinefile` `flashtransfer`

### 字段级 schema（节选，逐字取自源码）

| 段 | 字段 |
| :--- | :--- |
| `text` | `text` |
| `face` | `id`, `resultId?`, `chainCount?`（连击数） |
| **`mface`** | `emoji_package_id`(Number), `emoji_id`(String), `key`(String), `summary`(String) |
| `at` | `qq`, `name?` |
| `reply` | `id?`, `seq?` |
| `poke` | `type`, `id` |
| `dice` / `rps` | `result` |
| `contact` | `type`, `id` |
| `location` | `lat`, `lon`, `title?`, `content?` |
| `json` | `data`(Union), `config?` |
| `xml` | `data` |
| `markdown` | `content` |
| `miniapp` | `data` |
| **`onlinefile`** | `msgId`, `elementId`, `fileName`, `fileSize`, `isDir` |
| `flashtransfer` | `fileSetId` |
| `node` | `id?`, `user_id?`, `uin?`, `nickname`, `name?`, `content`, `source?`, `news?`, `summary?`, `prompt?`, `time?` |
| `forward` | `id`, `content?` |
| `image` | FileBase + `summary?`, `sub_type?` |
| `record` / `video` / `file` | FileBase |

**FileBase**（`FileBaseDataSchema`）：`file`（必填，路径/URL/`file://`）、`path?`、`url?`、`name?`、`thumb?`

## 3. 合并转发与 JSON 卡片：NapCat 的真实做法 [CODE]

`packages/napcat-onebot/action/msg/SendMsg.ts`（514 行）里的两条关键证据：

### 3.1 合并转发 = 上传 protobuf + 发一个 ARK 段

```ts
// SendMsg.ts L324-346（发送合并转发）
const uploadMsgData: UploadForwardMsgParams[] = [{ actionCommand: MultiMsg, actionMsg: packetMsg }];
const resid = await this.core.apis.PacketApi.pkt.operation.UploadForwardMsgV2(uploadMsgData, ...);
const forwardJson = ForwardMsgBuilder.fromPacketMsg(resid, packetMsg, source, news, summary, prompt, uuid);
return { finallySendElements: { elementType: ElementType.ARK,
  arkElement: { bytesData: JSON.stringify(forwardJson) } } as SendArkElement, res_id: resid, ... };
```

→ **合并转发在线上就是一个 `arkElement`**，内容里带 `resid`；内层消息体早已上传到服务器 `[CODE]`。

### 3.2 接收侧靠 ARK JSON 的 app 字段识别合并转发

```ts
// SendMsg.ts L289-297（处理转发节点时反向识别）
} else if (element.arkElement?.bytesData) {
  const json = JSON.parse(element.arkElement.bytesData);
  if (json.app === com.tencent.multimsg) {
    resId = json.meta?.detail?.resid;
    uuid  = json.meta?.detail?.uniseq || json.extra?.filename;
  }
}
```

→ **`{"type":"json"}` 不是一种东西**：`app === com.tencent.multimsg` 的才是合并转发卡片，
  要从 `meta.detail.resid` 取内层；其他 app（小程序、联系人卡片、markdown…）语义不同 `[CODE]`。

### 3.3 发送时的元素分组规则（⚠️ 已更正）

```ts
// SendMsg.ts L411-431 —— 关键：这段代码在 handleForwardedNodes（合并转发节点路径）内部
const MixElement = sendElements.filter(e => e.elementType !== ElementType.FILE && e.elementType !== ElementType.VIDEO
  && e.elementType !== ElementType.ARK && e.elementType !== ElementType.PTT);
const SingleElement = sendElements.filter(/* FILE / VIDEO / ARK / PTT */).map(e => [e]);
// → 这些元素被 NapCat 拆成「单独一条消息」，发送后收集 msgId，再组装成一张转发卡片
```

→ **更正**：这不是对发送方的约束，而是 NapCat 在**合并转发节点路径**内的自身行为 ——
全文**仅 L417 一处** `elementType ===` 比较，普通发送路径（`normalize()` L53-60 → `createSendElements`）**没有**任何拆分 `[CODE]`。
Flowerie 因此**不做**发送侧拆分；详见 `protocol-reverse-engineering.md` §9 C1。

→ **对 Flowerie 真正有意义的约束**：合并转发 `node.content` 里**只能放 `node` 段** ——
混入其他段时 NapCat 记 error 并 `continue`，**整个节点被丢弃**（L392-397）`[CODE]`。

## 4. 能力矩阵（第一版）

| 能力 | OneBot 11 规范 | NapCat | Lagrange | Milky | SnowLuma | LLBot | Flowerie 现状 | MVP |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 文本收发 | [DOC] 段 `text` | [CODE] `text` | [UNKNOWN] | [DOC] `text` | [UNKNOWN] | [UNKNOWN] | [CODE] 已支持 | [MVP] 已支持 |
| 图片接收 | [DOC] `image`(file/url) | [CODE] FileBase+summary/sub_type | [UNKNOWN] | [DOC] `image`(temp_url/resource_id) | [UNKNOWN] | [UNKNOWN] | [CODE] url/file 提取 | [MVP] **未实现** |
| 图片发送 | [DOC] `image` | [CODE] SendPicElement | [UNKNOWN] | [DOC] `image` 段 | [UNKNOWN] | [UNKNOWN] | [CODE] 走 sender 段数组/图片路径 | [UNKNOWN] |
| QQ 表情 face | [DOC] `face` | [CODE] `{id,resultId?,chainCount?}` | [UNKNOWN] | [DOC] `face{face_id}` | [UNKNOWN] | [UNKNOWN] | [CODE] **已建模** `faces`（连击/大表情渲染进上下文，上限 3 条）| [MVP] 未处理 |
| 商城表情 mface | [DOC] 非标准 | [CODE] `{emoji_package_id,emoji_id,key,summary}` | [UNKNOWN] | [DOC] `market_face`（实现只有 `url`）| [UNKNOWN] | [UNKNOWN] | [CODE] **已建模**（`faces` kind=market_face，无描述时不退化渲染）| [MVP] 未处理 |
| 文件接收（消息段） | [DOC] `file` | [CODE] FileBase | [UNKNOWN] | [DOC] `file` | [UNKNOWN] | [UNKNOWN] | [CODE] **已分类** `files`（`file_id/name/size/url/path`；NapCat 无 file_id 与 LLBot 有 file_id 均兜底）| [MVP] url+base64 信封 |
| 文件接收（notice） | [DOC] `group_upload` | [CODE] `OB11GroupUploadNoticeEvent` | [UNKNOWN] | [DOC] 文件事件 | [UNKNOWN] | [UNKNOWN] | [CODE] `notice_file` + `/get_file` 下载解码 | [MVP] 同左 |
| 文件发送 | [DOC] `upload_group_file` | [CODE] 独占一条消息（§3.3） | [UNKNOWN] | [DOC] 上传 API | [UNKNOWN] | [UNKNOWN] | [UNKNOWN] 待核对 | [UNKNOWN] |
| 合并转发接收 | [DOC] `forward`/`node` | [CODE] ARK+resid 或 MULTIFORWARD | [UNKNOWN] | [DOC] `get_forwarded_messages` | [UNKNOWN] | [UNKNOWN] | [CODE] 递归展开+预算控制 + **ARK multimsg 卡片按 `resid` 拉内层**（强于 MVP）| [MVP] 递归收 text |
| JSON 卡片 | [DOC] `json` | [CODE] `{data,config?}`，靠 `app` 区分 | [UNKNOWN] | [DOC] 无 | [UNKNOWN] | [UNKNOWN] | [CODE] **已区分 `app`**：`json_cards` 保留 `app/is_forward_card`，`com.tencent.multimsg` 走转发拉内层 | [MVP] 黑名单过滤收集 |
| poke（notice） | [DOC] `notice/notify/poke` | [CODE] `OB11PokeEvent` | [UNKNOWN] | [DOC] `send_group_nudge` | [UNKNOWN] | [UNKNOWN] | [CODE] 已支持（target 回退链齐全） | [MVP] 同左 |
| poke（消息段） | [DOC] 非标准 | [CODE] `poke{type,id}` + GreyTip(8) | [UNKNOWN] | [DOC] 无（Milky 是 `group_nudge` 事件）| [UNKNOWN] | [CODE] `shake{}`（face type=Poke，无目标）| [CODE] **已建模** `pokes`（含 shake，target 可为 None）| [MVP] 未处理 |
| 在线文件 | — | [CODE] `onlinefile{msgId,elementId,fileName,fileSize,isDir}` | [UNKNOWN] | [DOC] 无 | [UNKNOWN] | [UNKNOWN] | **未建模** | [UNKNOWN] |
| markdown | — | [CODE] `markdown{content}` | [UNKNOWN] | [DOC] `markdown{content}`（since 1.3，两份实现都无）| [UNKNOWN] | [UNKNOWN] | [CODE] **内容并入** `text` | [UNKNOWN] |

### 4.1 Milky 列的证据（来自 LLBot 实现 [CODE]）

> Milky 列以 **LLBot 的 Milky 实现**为 `[CODE]` 证据 + `SaltifyDev/milky` 规范为 `[DOC]` 证据，两者互证
> （早期曾误判「Lagrange.Milky 实现仓库不可得」，实为内嵌在 LagrangeV2/Core —— 见 source-acquisition.md「状态更正」）。
> 源码：`~/proto_src/LLBot/src/milky/transform/message/incoming.ts`（252 行）。
>
> **更权威的第二来源已补**：Milky 协议作者本人的实现内嵌在 `Lagrange.Core` / `LagrangeV2` 的
> `Lagrange.Milky/` 目录（119 个 .cs；**两份副本布局不同**：V2 `Entity/Segment/` 15 个文件 / 13 种段，
> Core `Models/Segments/` 11 个文件 / 10 种段），见
> [protocol-reverse-engineering.md](protocol-reverse-engineering.md) §6 —— 与 LLBot 逐字段互证。

| 能力 | Milky 段与字段 [CODE] |
| :--- | :--- |
| 文本 / @ | `text{text}`；**@ 不是独立元素**，而是 Text 元素的 `atType`：`One`→`mention{user_id,name}`、`All`→`mention_all{}` |
| 图片 | `image{resource_id(fileUuid), temp_url, width, height, summary, sub_type(sticker/normal)}`（`picSubType===1` → `sticker`） |
| QQ 表情 | `face{face_id: faceIndex.toString(), is_large: faceType===3}` |
| 商城表情 | `market_face{emoji_package_id, emoji_id, key, summary, url}`（url 由 emoji_id 拼 `gxh.vip.qq.com` 路径） |
| 语音 / 视频 | `record{resource_id,temp_url,duration}` / `video{resource_id,temp_url,width,height,duration}` |
| 文件（消息段） | `file{file_id(fileUuid), file_name, file_size}`（**无 url**，需另走下载接口） |
| 合并转发 | `forward{forward_id, title, preview[], summary}`；来源二选一：`MultiForward` 元素的 **XML `xmlContent`**（`resId`），或 **Ark**（`app=com.tencent.multimsg` → `meta.detail.resid`） |
| JSON/Ark 卡片 | **按 `app` 分流**：`com.tencent.multimsg` → `forward`；其它 → `light_app{app_name, json_payload}` |
| 引用 | `reply{message_seq, sender_id, time, segments[]}` —— **内联携带被引消息的完整段数组**（与 OneBot 只给 `id` 完全不同） |
| markdown | `markdown{content}`，且**短路**：只要消息里有 markdown 元素，其余元素一律不产出 |
| 临时会话 | `message_scene = temp`（OneBot 侧叫 `group_temp`；Flowerie 当前按 group/private 二分） |

**对 Flowerie 的直接影响（待 P3/P4 落地）**：

1. `reply` 段在 Milky 里**自带被引内容** → 归一化层要么把内联段也归一（信息更全），要么明确丢弃（不能假装它没出现）；
2. `mention`/`mention_all` 属于 Text 元素属性 → 归一化层不能只按「段类型」判断 @；
3. `image.sub_type=sticker` 是**图片形式的表情包** → 与 `face`/`market_face` 是三种不同的东西；
4. `temp` 场景需要归一化层新增一类会话（当前 Flowerie 只有 group/private）。
## 6. 生态覆盖清单（Ecosystem Coverage）

> 由用户提供的 OneBot11 / Milky 生态清单整理而成。**分层判定价值**：
>
> - **协议端（实现端）**：决定**线上 JSON 形态** → 归一化层必须逐个核对 `[CODE]`；
> - **SDK / 框架**：绝大多数只是**消费**同一套形态，不新增 wire 信息；只有少数「统一客户端 SDK」
>   （如 imhelper）或兼容层（如 adapter-onebot）会暴露**字段兼容策略**，按需抽查；
> - **工具 / 中间件**：与协议形态无关，本任务不涉及。
>
> 状态用 `source-acquisition.md` 的词表；**未取得源码的一律标 `NOT_INVESTIGATED`，不假装看过**。

### 6.0 一览（截至 2026-08-09）

**源码获取**（明细见 source-acquisition.md）：**15 个仓库 / 369M 已取得**，1 个 `SOURCE_UNAVAILABLE`（OpenShamrock）。

**能力覆盖的证据密度**（按 message-model.md §3 的 14 行能力表**逐格统计标注** —— 报告的是标注密度，不是重新审计）：

| 客户端 | [CODE] | [DOC] | [UNKNOWN] | 说明 |
| :--- | ---: | ---: | ---: | :--- |
| NapCat | **14** | 0 | 0 | 唯一逐格全 [CODE] 的协议端（§1–§3）|
| SnowLuma | **14** | 0 | 0 | 段编解码层逐格有据 |
| Milky | 11 | 3 | 2 | 实现内嵌 LagrangeV2/Core（两份副本）+ 规范互证（§4.1、§6）|
| LLBot（OneBot）| 10 | 0 | 3 | OneBot 实现侧；Milky 侧计入 Milky 列 |
| OneBot 11 规范 | 1 | 9 | 2 | 规范文档级参照（`[DOC]` 为主）|

**生态分层**（"已取得并核对" = 字段定义被逐行读过且结论以 `[CODE]` 落进文档；"已取得未逐行核对" = 仓库在本地但**不声称支持**）：

| 层 | 已取得并核对 | 已取得未逐行核对 | 未调查 | 不可得 |
| :--- | :--- | :--- | :--- | :--- |
| 协议端（决定 wire 形态）| NapCatQQ、LLBot、Lagrange.Milky（内嵌）| Lagrange.OneBot、go-cqhttp | onebots、Yogurt、onebot-kotlin | OpenShamrock |
| SDK / 框架（消费侧）| NoneBot2 + adapter-onebot、SnowLuma | Koishi、Kovi、ROneBot、milky-python-sdk | imhelper 及 40+ 项（见 6.2）| — |
| 规范 / 文档 | OneBot11-spec、Milky-spec | Lagrange.Milky.Document（仅文档）| — | — |
| 工具 / 中间件 | — | — | matcha、nonebot-plugin-all4one | — |

**行动结论**：① 必须逐个核对 wire 形态的协议端里，只剩 **onebots / Yogurt**（仓库地址未确认）与 **OpenShamrock**（不可得）；
② 消费侧 SDK 的差异靠**宽容解析 + unknown 保留**覆盖，不为每个 SDK 写分支；
③ 未调查项不影响当前归一化层的正确性 —— 它们消费的是同一套形态。
### 6.1 协议端（OneBot 11）

| 项目 | 语言 | 状态 | 说明 |
| :--- | :--- | :--- | :--- |
| NapCatQQ | TS | **SOURCE_OBTAINED**（已逆向） | 见 protocol-reverse-engineering.md §3 |
| LLOneBot / LLBot | TS | **SOURCE_OBTAINED**（已逆向） | 同时实现 OneBot 11 与 Milky，见 §4 |
| Lagrange.OneBot | C# | **SOURCE_UNAVAILABLE**（2026-09-25 复核：LagrangeDev/Lagrange.OneBot HTTP 404；本地 Lagrange.Core/V2 无 OneBot 代码 —— 见 source-acquisition.md C4）| OneBot 11 列只能靠 [DOC]（Lagrange.Doc，且页面自称过时）|
| Lagrange.Milky | C# | **SOURCE_OBTAINED**（内嵌 Lagrange.Core/V2） | 见 §6 |
| OpenShamrock | Kotlin/Java | **SOURCE_UNAVAILABLE** | 原仓库（whitechi73/OpenShamrock）不可得：clone 报 could not read Username，仓库搜索只剩第三方分支/适配；**未逆向，不声称支持** |
| go-cqhttp | Go | **SOURCE_OBTAINED** a5923f1（121 文件） | 已归档，但**是事实基线**（很多实现模仿它的字段） |
| onebots | ? | `NOT_INVESTIGATED` | 多协议服务端（OneBot v11/v12 + Satori + Milky），仓库地址未确认 |
| Yogurt | ? | `NOT_INVESTIGATED` | Milky 协议端，仓库地址未确认 |
| onebot-kotlin | Kotlin | `NOT_INVESTIGATED` | |
| oicq | JS | `ARCHIVED` | 已归档，优先级低 |
| OneBot-YaYa / coolq-http-api / PicqBotX | — | `ARCHIVED` | 历史实现，仅在需要解释遗留字段时参考 |
| Gensokyo / KookOneBot | — | `NOT_INVESTIGATED` | 非 QQ 平台（开黑啦/Discord），与本任务无关 |

### 6.2 SDK / 框架

| 项目 | 语言 | 状态 | 价值判定 |
| :--- | :--- | :--- | :--- |
| NoneBot2 + adapter-onebot | Python | **SOURCE_OBTAINED** | **高**：规范级参照（`poke{type,id}` 有工厂方法），兼容策略在 `v11/compat.py` |
| Koishi | TS | **SOURCE_OBTAINED** 5525cfd（186 文件） | 中：OneBot 适配器的字段处理 |
| Kovi | Rust | **SOURCE_OBTAINED** 9decea5（114 文件） | 中高：同时支持 Milky/OneBot 的框架，可交叉验证 |
| ROneBot | Kotlin | **SOURCE_OBTAINED** b39550f（368 文件） | 中：OneBot11/12 + Milky 多平台库 |
| milky-python-sdk | Python | **SOURCE_OBTAINED** 805b194（182 文件） | 中：Milky 客户端 SDK 的字段视角 |
| imhelper | TS | `NOT_INVESTIGATED` | **高**（若取到）：统一客户端 SDK，覆盖 OneBot v11/v12 + Satori + Milky —— 与 Flowerie 同类问题 |
| AstrBot / LangBot / Graia / ZeroBot / NsxBot / Shiro / makabaka / OlivOS / 炸毛 / Simbot / Adachi-BOT / PepperBot / melobot / AlemonJS / MuRainBot2 / NcatBot / napcat-sdk / OneBotConnecter / eridanus-dep / qcrbot-sdk / yiri-onebot / AliceBot / Overflow / kira_framework / walle-core / oxidebot / onebotv11_rs / runbot / onebot-client-next / shirosaki-onebot / @zhinjs/adapter-onebot-11 / Zhin.js / Karin / nagisa / satori-python-adapter-milky / @imhelper/milky-v1 / @onebots/protocol-milky-v1 / @zhin.js/adapter-milky / karin-plugin-adapter-milky / Saltify core / Vivian / nagisa-milky / Milky.Net.Model / milky-types / @saltify/milky-protocol / milkygen | 多语言 | `NOT_INVESTIGATED` | 低-中：**消费同一套 wire 形态**，除非发现某实现有独特字段，否则不逐个逆向；`@saltify/milky-protocol`（= `SaltifyDev/milky` 的 IR）**已取得** |

### 6.3 工具 / 中间件

| 项目 | 状态 | 说明 |
| :--- | :--- | :--- |
| matcha（模拟聊天交互） | `NOT_INVESTIGATED` | 开发辅助工具，不改变协议形态 |
| nonebot-plugin-all4one（NoneBot 2 → OneBot 12） | `NOT_INVESTIGATED` | 协议转换插件；**若 Flowerie 未来支持 v12，可作为参考** |

### 6.4 由此清单得出的行动项

1. **必须逐个核对 wire 形态的**：协议端（OpenShamrock / go-cqhttp 本轮补齐；onebots / Yogurt 待确认仓库）；
2. **值得抽查兼容策略的**：Koishi / Kovi / ROneBot / imhelper（统一 SDK）；
3. **不逐个逆向的**：其余 SDK/框架 —— 它们的差异通常在**消费侧**（字段缺失容忍度），
   而归一化层的健壮性应该通过**宽容解析 + unknown 保留**来覆盖，而不是给每个 SDK 写分支；
4. **协议版本维度**：onebots 与 ROneBot 提到 OneBot **v12** —— Flowerie 目前只支持 v11，
   这条记为 `[UNKNOWN]`（不在本任务范围内，但清单里保留）。
## 5. 待办（下一轮）

1. SnowLuma：定位它的 OneBot/Milky 实现与事件模型；
2. Lagrange.Core / LagrangeV2：定位 message element 定义与 OneBot/Milky 转换；
3. LLBot：定位 OneBot 11 + Milky 双实现（它两个协议都支持）；
4. NoneBot2 + adapter-onebot：定位它对非标准字段的兼容策略（任务书 §二点名）；
5. OneBot 11 规范：逐段核对 `[DOC]` 列；
6. ~~Milky：实现仓库不可得 → 只能 [DOC]~~ **已完成**：实现内嵌于 LagrangeV2/Core
   （`Entity/Segment/` 与 `Models/Segments/` 两份副本），现已具 `[CODE]` 证据；
   Milky 段归一化与 21 种事件类型归一化均已落地（见 milky-protocol.md、message-model.md）。

> 说明（2026-08-09 更新）：§4 矩阵的**客户端列**是**第一版**快照 —— Lagrange / SnowLuma / LLBot 的多数格子仍标 `[UNKNOWN]`，
> 这些客户端的实际证据写在 protocol-reverse-engineering.md §4（LLBot 双协议）与 §6（Lagrange.Milky）中；**未逐格回填**是为了不把
> 「某一处已核对」扩写成「整列已核对」（任务书 §22）。**「Flowerie 现状」列已按本会话落地情况更新**
> （face / mface / file 段 / poke 段 / json 卡片 app 分流 / 合并转发 multimsg / markdown）。
