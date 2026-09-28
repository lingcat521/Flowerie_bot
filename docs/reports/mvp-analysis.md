# MVP 对照报告（/storage/emulated/0/bot.py）

> 任务书 §四/§22.5：先把本地 MVP 逆向清楚，再与 Flowerie 逐项比较，说明「做了什么 / 为什么能工作 /
> Flowerie 缺什么 / 哪些逻辑值得迁移 / 哪些不能直接迁移」。
>
> MVP 文件：`/storage/emulated/0/bot.py`（1797 行，UTF-8，2026-08-07 版本）。行号均为实测。

## 1. MVP 做了什么 [MVP]

| 主题 | 事实 | 行号 |
| :--- | :--- | :--- |
| 连接 | **反向 WS 服务端**（`websockets.serve`），无鉴权、无 ack、无 echo 配对 | L1747-1786 |
| 发送 | HTTP `POST {HTTP_API_BASE}/send_group_msg`，`message` 是**纯字符串**；成功 = HTTP 200 且 `retcode==0` | L691-740 |
| 事件分发 | `post_type=message` → `_handle_message`；`notice/group_upload` → 缓存待取文件；`notice/notify/poke` → `_handle_poke` | L1258-1278 |
| 消息模型 | `data.message` 为**段数组**；text→文本、at→`data.qq`、reply→`data.qq` 判是否回机器人；`raw_message` 未使用 | L787-813 |
| **poke** | 字段回退链 `target_id → target → to_user_id → user_id`；仅 `target == bot` 才回复 | L1213-1256 |
| **文件（notice）** | `group_upload` → `data.file{name,id,size,busid}`，随后 `GET /get_file?file_id=` → **`{retcode:0,data:{base64}}`** | L815-829 / L931-969 |
| **文件（消息段）** | 段 `type=file`，`data.url` + `data.file`（名）；`/` 开头拼 `HTTP_API_BASE`；同一 base64 信封 | L971-1014 |
| **合并转发** | 段 `type=forward`：优先 `data.messages` 内联，否则 `data.id` → `GET /get_forward_msg?message_id=`；文本用**递归**遍历任意 `{text:str}`，sender 取 `sender.user_id` | L1016-1075 |
| **JSON 卡片** | 段 `type=json`，原始串在 `data.data`（回退 `content`/`text`）；**递归收集字符串**并用黑名单跳过技术字段 | L1078-1128 |
| 识图 | **完全没有**（grep `image`/`vision` 零命中） | — |
| 其他 | 复读/引战/主动聊天/记忆/存档等业务逻辑与协议无关，不在此报告范围 | — |

## 2. 为什么它能工作 [MVP] [INFERENCE]

1. **只服务一个客户端**：所有字段形态按 NapCat 实测写死（`data.data` 里塞 JSON、`/get_file` 返回 base64、
   `target_id` 这类 NapCat 字段）—— 没有跨客户端抽象的需求，所以不需要归一化层；
2. **对未知一律"尽力而为"**：JSON 卡片用"递归收集 + 黑名单"而不是结构解析；转发用"递归找 text"而不是节点模型。
   这种做法在**单一客户端**下鲁棒性意外地高（字段变了也不会崩，只是内容少一点）；
3. **不区分卡片种类**：把所有 `type=json` 一视同仁 —— 在它支持的场景下够用，但会**丢掉合并转发内层**
   （见 §3 的证据缺口）。

## 3. 与 Flowerie 的逐项比较

| 能力 | MVP | Flowerie 现状 | 结论 |
| :--- | :--- | :--- | :--- |
| 图片接收 | 无 | 段 `image` → `images`/`image_files`，本地 file 优先、URL 兜底，走 Vision 识图 | **Flowerie 强**（MVP 无识图）|
| 文件接收 | notice + 段两条路径，base64 信封 | 同左（`file_parser.fetch_and_parse_file` + `decode_napcat_file_response`） | 持平（Flowerie 有流式上限与更多格式）|
| 合并转发 | 递归收 text；**无嵌套展开、无预算** | `extract_forward_messages`：嵌套展开 + 深度/节点/条数/拉取预算 + 同 id 缓存 + 转发内图片识图 | **Flowerie 强** |
| JSON 卡片 | 递归收集 + 黑名单 | `extract_json_card_content`（同类做法） | 持平，但**两者都不区分 `app`**（见下）|
| poke | notice + 回退链 | 同左（`_handle_poke`，语义一致） | 持平 |
| 消息段建模 | 只认 text/at/reply/image/face(skip)/forward/json/file | **本轮新增**：`faces`/`pokes`/`files`/`json_cards`/`forwards` 归一化载体 | **Flowerie 强（本轮）** |
| 发送 | 纯字符串 | 段数组 / 图片路径 / 多协议统一入口 `Sender._post` | **Flowerie 强** |

### 3.1 MVP 里"看着能用其实丢信息"的地方（重要）

- **合并转发卡片（ARK `app=com.tencent.multimsg`）被当普通卡片**：MVP 的 `_extract_json_card_content` 会把
  `meta.detail.news[].text` 等字段收成"卡片内容"，但**不会去拉内层消息** ✓
  （对比证据：NapCat `SendMsg.ts` L289-297 用 `resid` 拉内层 —— 见 client-compatibility.md §3.3）；
- 因此 MVP 在"有人转发聊天记录"时只能看到标题/摘要，看不到内容。

## 4. 值得迁移的逻辑（已迁移 / 建议迁移）

| MVP 逻辑 | 状态 |
| :--- | :--- |
| `target_id → target → to_user_id → user_id` 回退链 | **已有**（Flowerie `_handle_poke` 同语义）|
| `/get_file` → base64 信封解码 | **已有**（`decode_napcat_file_response`）|
| 转发递归收 text + `sender.user_id` | **已有且更强** |
| JSON 卡片"递归收集 + 黑名单" | **已有**；本轮补上 `app` 判定（MVP 缺）|
| poke 的 `user_id/target_id/group_id` 字段用法 | **已有** |

## 5. 不能直接迁移的部分 [MVP] [INFERENCE]

1. **纯字符串发送**：MVP `{"message": "文本"}`；Flowerie 需要段数组/图片路径（多协议统一入口），迁移会退化能力；
2. **无鉴权反连 WS**：MVP 不校验 token；Flowerie 的 WS 通道有 token 策略（见 security.md）；
3. **硬编码**：MVP 里写死 `http://127.0.0.1:3000/get_file`、存档路径 `/storage/emulated/0/lingcat521`、
   测试群号 `123456789` —— 属于个人环境，不能进库；
4. **忽略私聊**：MVP `_handle_message` 直接 `if message_type != "group": return`；Flowerie 支持私聊；
5. **无嵌套/预算控制**：直接把客户端 JSON 递归展开在真实场景会被套娃转发打爆（Flowerie 已加预算）；
6. **把客户端字段直接用进业务**：MVP 到处读 `data.xxx`；Flowerie 的分层要求 Adapter 归一化后再进 Core（任务书 §十六）。

## 6. 结论

- MVP 的价值在于**证明 NapCat 的真实字段形态**（文件 base64 信封、`data.data` 里的卡片 JSON、poke 回退链），
  这些事实已被逐条吸收进 Flowerie 的 Adapter 层 `[MVP]`；
- MVP 的**架构**不可迁移（单客户端、无分层、无预算）；
- 本轮新发现的差距（**JSON 卡片必须按 `app` 分流**）是 MVP 与 Flowerie **共有**的缺陷，
  已按 NapCat/LLBot 的 `[CODE]` 证据在 Flowerie 侧修复（`4a6a157`）。
