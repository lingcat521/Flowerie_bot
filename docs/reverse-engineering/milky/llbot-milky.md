# LLBot 的 Milky 实现逆向

> 任务书 ~/storage/emulated/0/协议.txt §四/§十/§二十三。同一仓库的 OneBot 11 侧见
> [../onebot11/llbot.md](../onebot11/llbot.md)；Milky 入站映射的既有详细记录见
> [../../protocol-reverse-engineering.md](../../protocol-reverse-engineering.md) §4.1/§4.3。

## Source

| 项 | 值 |
| :--- | :--- |
| 仓库 | `LLOneBot/LuckyLilliaBot` `9f374f6`（本地 `~/proto_src/LLBot`）|
| 关键源码 | `src/milky/transform/message/incoming.ts`（252 行）、`src/milky/transform/message/outgoing.ts`（131 行）、
`src/milky/common/api.ts`（响应包封）、`src/milky/network/http.ts`（HTTP 面）、`src/milky/api/*.ts` |
| 实机抓包 | **无** → `[CODE]` |

## Version

- `9f374f6`；与 OneBot 11 侧同一提交（一个进程同时提供两套协议面）。

## Evidence

`[CODE]` 源码逐行；与 Milky 规范（`SaltifyDev/milky 151dd90`）互证。

## Observed Behavior

### 1. 出站（outgoing.ts）

| Milky 段 | 客户端行为 [CODE] |
| :--- | :--- |
| `text` | 直接转文本元素 |
| `mention` | **仅群聊**（`&& isGroup`）；先按 uin 查群成员拿昵称再 @ |
| `mention_all` | **仅群聊**；@全体 |
| `face` | `face_id` 转 int，`is_large` → faceType 3 |
| `reply` | 用 `message_seq` 查本地/服务端消息；**查不到直接 throw「被回复的消息未找到」**；转发内还会取 `rawPb` |
| `image` | `uri` 先下载（`resolveMilkyUri`）到临时文件再上传 |
| （其余）| 见文件后半段（本轮未逐行抄录 → 未登记能力）|

### 2. 响应包封（`src/milky/common/api.ts L4-40`）

```ts
interface MilkyApiOkResponse<T> { status: 'ok'; retcode: 0; data: T }
interface MilkyApiFailedResponse { status: 'failed'; retcode: number; message: string }
export function Ok<OT>(data: OT) { return { status: 'ok', retcode: 0, data } }
export function Failed(retcode: number, message: string) { return { status: 'failed', retcode, message } }
```

**没有** OneBot 11 的 `msg`/`wording` 字段 → Flowerie 用**两个独立解析器**
（`src/transport/onebot_response.py` 与 `milky_response.py`），不共用字段假设。

### 3. HTTP 面

`src/milky/network/http.ts` 记录每个请求的 `retcode`（日志行里 `retcode === 0 ? 'OK' : retcode`）——
与包封一致：**retcode 是判定的主字段**，status 是它的冗余表达。

## Normalized Behavior（Flowerie 现状 [MVP]）

- 入站：`src/adapters/milky_parser.py`（G1-G4 CLOSED，本轮未改动）；
- 出站：`src/adapters/milky_serializer.py` 按档案 `LLBOT_MILKY` 处理 ——
  `mention_group_only`（私聊丢段 + note）、`reply_requires_resolvable_seq`（保留 `message_seq`）、`image_uri_download_first`；
- 响应：`src/transport/milky_response.py`。

## Known Differences

- 与 Lagrange.Milky 的对照见 [lagrange-milky.md](lagrange-milky.md) 的 Known Differences 表（段集合 / mention 私聊 / 发送响应字段）；
- 与 OneBot 11 侧（同一客户端）的差异：段名与字段完全不同（`mention` vs `at`、`face_id` vs `id`、`uri` vs `file`、`message_seq` vs `id`）——
  所以两套序列化器分开实现，但共用"未知段原样传递 + 每次改动记 note"的规则。

## Unknowns

1. `record` / `video` / `forward` / `light_app` 的出站实现细节（本轮只读到 `image` 为止）；
2. `markdown` 出站是否支持（入站有，出站联合体未列 → 档案标 UNSUPPORTED 是**规范口径**，不是客户端实测）；
3. 实机抓包：**BLOCKED BY EXTERNAL DEPENDENCY**。

## Tests

| 文件 | 覆盖 |
| :--- | :--- |
| `tests/test_milky_serializer.py` | 客户端规则用例（私聊 mention 丢弃 + note；reply 字段改名 + note；往返不许静默消失）|
| `tests/fixtures/milky/actions/`（2 个）| OK / Failed 包封语料（走生产解析器）|
