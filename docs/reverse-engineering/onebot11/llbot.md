# LLBot 逆向（OneBot 11 + Milky 双实现客户端档案）

> 任务书 ~/storage/emulated/0/协议.txt §三/§七/§八/§二十三。矩阵见 [../../client-compatibility.md](../../client-compatibility.md)；
> Milky 侧的段映射见 [../milky/](../../protocol-reverse-engineering.md) §4.1/§4.3（本轮只补 OneBot 11 列）。

## Source

| 项 | 值 |
| :--- | :--- |
| 仓库 | `LLOneBot/LuckyLilliaBot`（本地 `~/proto_src/LLBot`）|
| 版本 | `9f374f6`（浅克隆 HEAD，2026-09-25 取）|
| 语言 / 规模 | TypeScript / 1086 文件（129M）|
| 关键源码 | `src/onebot11/transform/message/incoming.ts`（**入站段映射，327 行**）、
`src/onebot11/transform/message/outgoing.ts`（出站，341 行）、`src/onebot11/action/OB11Response.ts`（响应包封）、
`src/milky/transform/message/{incoming,outgoing}.ts`（Milky 侧，见既有文档）|
| 实机抓包 | **无** → 全部 `[CODE]`，fixture 标 `captured: false` |

## Version

- `9f374f6`：同时实现 OneBot 11 与 Milky（两套 transform 目录），本文件只覆盖 OneBot 11。

## Evidence

`[CODE]` 源码逐行（附行号）；`[MVP]` 本仓库实现；无 `[INFERENCE]` 结论。

## Observed Behavior（入站段映射，incoming.ts）

| 内部元素 | 段 type | data 字段 [CODE] | 行号 |
| :--- | :--- | :--- | :--- |
| at | `at` | `{qq, name}`（name 由 content 去掉 @ 得到；支持 all）| L20-33 |
| text | `text` | `{text}`（空文本**跳过**）| L34-45 |
| reply | `reply` | `{id}` = **LLBot 自建短 id**（`store.createMsgShortId`）；原消息找不到 → **整段丢弃** + warning | L57-80 |
| pic | `image` | `{file: fileName, subType: picSubType, url, file_size}` | L81-107 |
| video | `video` | `{file, url, path, file_size}` | L108-130 |
| file | `file` | `{file: fileName, url: file://…, file_id: fileUuid, path, file_size}` | L131-154 |
| record | `record` | 见 L155-176 | |
| ark | `json` | `{data: bytesData}` | L177-181 |
| face | `shake` / `dice` / `rps` / `face` | poke → `shake{data:{}}`（**空对象、无目标**）；骰子/猜拳 → `{result}`；其它 → `{id, sub_type: faceType}` | L182-222 |
| market face | `mface` | `{summary, url, emoji_id, emoji_package_id, key}`（url 由 emoji_id 拼）| L223-248 |
| markdown | `flash_file` / `markdown` | 以 `[闪传](` 开头且 `busId==='FlashTransfer'` → `flash_file{title, file_set_id, scene_type}`；否则 `markdown{content}` | L249-292 |
| multiForward | `forward` | `{id: resId}` | L285-291 |
| inlineKeyboard | `keyboard` | `{rows:[{buttons:[{id, render_data{...}}]}]}` | L292+ |

## Normalized Behavior（Flowerie 现状 [MVP]）

| fixture（本轮新增 3 个）| 归一化结果 |
| :--- | :--- |
| `message_shake_dice_face.json` | `pokes` 命中 shake；dice/rps 原样保留（`result`）；face 归一化 |
| `message_reply_short_id_and_file.json` | `files` 命中（含 `file_id`/`file_size`）；reply id 原样保留在段里（**不做跨客户端 id 翻译**）|
| `message_flashfile_and_keyboard.json` | 两段原样保留在段数组（未建语义字段 —— 见 Unknowns）|

## Known Differences（跨客户端）

| 维度 | LLBot [CODE] | NapCat [CODE] | go-cqhttp [CODE] |
| :--- | :--- | :--- | :--- |
| 戳一戳（段）| `shake{data:{}}`（无目标）| `poke{type,id}` | `poke{qq}` |
| dice/rps 取值字段 | `result` | `result` | **`value`**（三家里的少数派）|
| reply id 命名空间 | LLBot **短 id**（自建映射）| `{id?,seq?}`（seq 优先）| 客户端 **DB global id** |
| reply 解析失败行为 | **丢段 + warning** | —— | 需 DB 里有原消息，否则报错 |
| image 子类型字段 | `subType`（驼峰）| `sub_type`（下划线）| `subType` |
| file 段 | `{file, url, file_id, path, file_size}` | FileBase `{file, path?, url?, name?, thumb?}` | `{path, name, size, busid}` |
| mface | 带 `url` | 无 url | **无 mface 段**（降级 text）|
| 独有段 | `flash_file` / `keyboard` | `markdown/miniapp/contact/location/onlinefile/flashtransfer` | `cardimage/redbag` |

> 结论：**同一个语义（戳一戳、骰子、回复、文件）在三个客户端里有三种字段形状** ——
> 这正是任务书 §八「同名不同义 / 同义不同名」要求逐格核实的原因。

## Unknowns

1. `record`（L155-176）的完整字段未逐行抄录（本轮只核对了类型名与位置）→ 未登记进档案 quirks；
2. `file_size` 的类型约定（源码里是字符串化 int）在发送侧是否同样接受，未验证；
3. `keyboard` / `flash_file` 的语义与消费方式（Flowerie 目前只在段数组里保留原文）；
4. `reply` 短 id 与 Flowerie `reply_id` 的映射（跨客户端引用回复需要翻译层，**本轮不做**）；
5. 实机抓包：**BLOCKED BY EXTERNAL DEPENDENCY**（需要运行中的 LLBot 实例）。

## Tests

| 文件 | 覆盖 |
| :--- | :--- |
| `tests/fixtures/llbot/`（4 个）| shake/dice/face、reply 短 id + file 段、flash_file + keyboard、既有的 file+shake 用例 |
| `tests/test_fixtures_corpus.py` | 溯源契约 + 归一化断言（既有 LLBot 用例）|
| `tests/test_client_contract_matrix.py` | 该客户端语料的 Parse / Serialize（方向二）与 Unknown 安全 |
