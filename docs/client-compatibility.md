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

### 3.3 发送时的元素分组规则（重要）

```ts
// SendMsg.ts L413-420
element.elementType !== ElementType.FILE && element.elementType !== ElementType.VIDEO
  && element.elementType !== ElementType.ARK && element.elementType !== ElementType.PTT
// → 这几类元素被拆成「单独一条消息」发送（不能与其他段混在同一条里）
```

→ **文件 / 视频 / ARK / 语音必须独占一条消息**；给 Flowerie 的启示：多条回复里混这类段时要拆消息 `[CODE]`。

## 4. 能力矩阵（第一版）

| 能力 | OneBot 11 规范 | NapCat | Lagrange | Milky | SnowLuma | LLBot | Flowerie 现状 | MVP |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 文本收发 | [DOC] 段 `text` | [CODE] `text` | [UNKNOWN] | [DOC] `text` | [UNKNOWN] | [UNKNOWN] | [CODE] 已支持 | [MVP] 已支持 |
| 图片接收 | [DOC] `image`(file/url) | [CODE] FileBase+summary/sub_type | [UNKNOWN] | [DOC] `image`(temp_url/resource_id) | [UNKNOWN] | [UNKNOWN] | [CODE] url/file 提取 | [MVP] **未实现** |
| 图片发送 | [DOC] `image` | [CODE] SendPicElement | [UNKNOWN] | [DOC] `image` 段 | [UNKNOWN] | [UNKNOWN] | [CODE] 走 sender 段数组/图片路径 | [UNKNOWN] |
| QQ 表情 face | [DOC] `face` | [CODE] `{id,resultId?,chainCount?}` | [UNKNOWN] | [DOC] `face{face_id}` | [UNKNOWN] | [UNKNOWN] | **未建模** | [MVP] 未处理 |
| 商城表情 mface | [DOC] 非标准 | [CODE] `{emoji_package_id,emoji_id,key,summary}` | [UNKNOWN] | [DOC] 无对应 | [UNKNOWN] | [UNKNOWN] | **未建模** | [MVP] 未处理 |
| 文件接收（消息段） | [DOC] `file` | [CODE] FileBase | [UNKNOWN] | [DOC] `file` | [UNKNOWN] | [UNKNOWN] | [CODE] 段 `file` **未分类**（仅在通用 summary） | [MVP] url+base64 信封 |
| 文件接收（notice） | [DOC] `group_upload` | [CODE] `OB11GroupUploadNoticeEvent` | [UNKNOWN] | [DOC] 文件事件 | [UNKNOWN] | [UNKNOWN] | [CODE] `notice_file` + `/get_file` 下载解码 | [MVP] 同左 |
| 文件发送 | [DOC] `upload_group_file` | [CODE] 独占一条消息（§3.3） | [UNKNOWN] | [DOC] 上传 API | [UNKNOWN] | [UNKNOWN] | [UNKNOWN] 待核对 | [UNKNOWN] |
| 合并转发接收 | [DOC] `forward`/`node` | [CODE] ARK+resid 或 MULTIFORWARD | [UNKNOWN] | [DOC] `get_forwarded_messages` | [UNKNOWN] | [UNKNOWN] | [CODE] 递归展开+预算控制（强于 MVP） | [MVP] 递归收 text |
| JSON 卡片 | [DOC] `json` | [CODE] `{data,config?}`，靠 `app` 区分 | [UNKNOWN] | [DOC] 无 | [UNKNOWN] | [UNKNOWN] | [CODE] 有 `extract_json_card_content`，但**不区分 app** | [MVP] 黑名单过滤收集 |
| poke（notice） | [DOC] `notice/notify/poke` | [CODE] `OB11PokeEvent` | [UNKNOWN] | [DOC] `send_group_nudge` | [UNKNOWN] | [UNKNOWN] | [CODE] 已支持（target 回退链齐全） | [MVP] 同左 |
| poke（消息段） | [DOC] 非标准 | [CODE] `poke{type,id}` + GreyTip(8) | [UNKNOWN] | [DOC] 无 | [UNKNOWN] | [UNKNOWN] | **未建模** | [MVP] 未处理 |
| 在线文件 | — | [CODE] `onlinefile{msgId,elementId,fileName,fileSize,isDir}` | [UNKNOWN] | [DOC] 无 | [UNKNOWN] | [UNKNOWN] | **未建模** | [UNKNOWN] |
| markdown | — | [CODE] `markdown{content}` | [UNKNOWN] | [DOC] 无 | [UNKNOWN] | [UNKNOWN] | **未建模** | [UNKNOWN] |

## 5. 待办（下一轮）

1. SnowLuma：定位它的 OneBot/Milky 实现与事件模型；
2. Lagrange.Core / LagrangeV2：定位 message element 定义与 OneBot/Milky 转换；
3. LLBot：定位 OneBot 11 + Milky 双实现（它两个协议都支持）；
4. NoneBot2 + adapter-onebot：定位它对非标准字段的兼容策略（任务书 §二点名）；
5. OneBot 11 规范：逐段核对 `[DOC]` 列；
6. Milky：实现仓库不可得 → 只能 [DOC]（SaltifyDev/milky protocol 定义 + Lagrange.Milky.Document）。

> 说明：本文件当前只有 NapCat 一列是 `[CODE]` 完成态，其余列显式标 `[UNKNOWN]`。
> 按任务书 §22，绝不用别的客户端的实现去填某列的空白。
