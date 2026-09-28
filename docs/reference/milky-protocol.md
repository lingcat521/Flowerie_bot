# Milky 协议支持（Milky 特供版）

> Milky 是新一代 QQ 机器人协议标准（Lagrange.Core V2 已放弃 OneBot 转向 Milky）。同一 Flowerie 实例改 `QQ_PROTOCOL=milky`
> 即直连 Milky 协议端（Lagrange.Milky / Yogurt 等），AI/人设/记忆/群规则零改动。协议事实以 Milky **1.3** 为准；
> OneBot 版历史资产仍保留在 [v2.2.2 Release](https://github.com/lingcat521/Flowerie_bot/releases/tag/v2.2.2)。

## 配置（`.env`，默认值取自 `src/config.py`）
| 键 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `QQ_PROTOCOL` | `onebot` | 设为 `milky` 才走 Milky 分支（`main.py:242`）|
| `MILKY_API_BASE` | `http://127.0.0.1:8080` | 协议端 HTTP 根，调用 `POST /api/<action>` |
| `MILKY_EVENT_URL` | `ws://127.0.0.1:8080/event` | 事件推送 WebSocket（应用端主动连接）|
| `MILKY_ACCESS_TOKEN` | 空 | Bearer 鉴权；同时作为 `?access_token=` 拼进事件 URL |

也可在 Web UI 配置页（Bot 分类，键表见 `src/services/config_schema.py`）修改。**协议端侧**需：HTTP 服务开（`/api` 入口）、事件推送走 WebSocket（`/event`）、`access_token` 与上表一致；启动 `python main.py`，日志出现 `Milky event connected` 即连接成功。

## 事件格式（EventEnvelope）
```json
{"time": 1234567890, "event_type": "message_receive",
 "data": {"message_scene": "group", "peer_id": 786368680, "sender_id": 297205104, "segments": []}}
```

### 消息段（`src/adapters/milky_parser.py`，已按官方 SDK + 两份作者实现对齐）
| 段 `type` | `data` 字段 | 归一化去向（Adapter）|
| :--- | :--- | :--- |
| `text` | `text` | `text` |
| `mention` | `user_id`（+name）| `mentions`（与 OneBot `at/qq` 不同）|
| `mention_all` | — | `mentions`（"all"）|
| `image` | `temp_url` + `resource_id`（+width/height/summary/sub_type）| `images` / `image_files`（识图用 temp_url）|
| `reply` | `message_seq`（+ 内联 `segments`）| `reply_id` + `reply_ref`/`reply_segments`/`reply_text`（内联内容已消费）|
| `face` | `face_id`（规范另有 `is_large`）| `faces` |
| `market_face` | **实现只有** `url`；规范另有 emoji_id/summary 等 | `faces` |
| `light_app` | `app_name` + `json_payload` | `json_cards`（payload 内 `app=com.tencent.multimsg` 时按合并转发拉内层）|
| `forward` | `forward_id` + title/preview/summary | `forwards` |
| `file` | `file_id` + `file_name` + `file_size`（+`file_hash`?）| `files` |
| `record` | `resource_id` + `temp_url` + `duration` | `records`（未知字段进 `extra`）|
| `video` | `resource_id` + `temp_url`（+宽高/时长）| `videos` |
| `xml` | `service_id` + `xml_payload` | `xmls`（只保真保存 `raw_xml`，**不解析**）|
| `markdown` | `content` | `text`（规范 since 1.3；两份实现都未定义该段）|

**与 OneBot 的差异**：段容器字段是 `segments`（OneBot 是 `message`）；@ 用 `mention`/`user_id`（OneBot `at`/`qq`）；
图片用 `temp_url`（OneBot `file/url`）；回复用 `message_seq`（OneBot `id`）；消息号是 `message_seq`（OneBot `message_id`）
—— 事件、**发送响应**、撤回入参三处都用它。

> 段清单以**两份内嵌实现 + 规范三方互证**（均为 `[CODE]`/`[DOC]`，见 protocol-reverse-engineering.md §6.1 / §9 C2）：
> `LagrangeV2/Lagrange.Milky/Entity/Segment/`（15 文件 / 13 种 incoming）与 `Lagrange.Core/Lagrange.Milky/Models/Segments/`
> （11 文件 / 10 种 incoming）布局不同，且**实现字段比规范窄**（如 `market_face` 只有 `url`）—— 解析一律逐字段兜底。

## API 调用（发送）
```
POST {MILKY_API_BASE}/api/send_group_message      # 私聊为 send_private_message
Authorization: Bearer <access_token>
{"group_id": 123, "message": [{"type": "text", "data": {"text": "hi"}}]}
```
- 消息必须是 **OutgoingSegment 数组**（字符串自动转 text 段）
- action 名映射：`send_group_msg→send_group_message`、`send_private_msg→send_private_message`

## 消息场景（`message_scene`）
| 场景 | 归一化 | 说明 |
| :--- | :--- | :--- |
| `friend` | `scope=private`, `scene=friend` | 好友私聊 |
| `group` | `scope=group`, `scene=group` | 群消息（`group_id = peer_id`）|
| `temp` | `scope=private`, `scene=temp`, `context_group_id = group.group_id` | **临时会话**（QQ 群内发起）：规范 L284-291 的 `group` 是**可选实体**，来源群只做上下文，不冒充群会话 |
| `stranger` | `scope=private`, `scene=stranger` | 陌生人（LLBot 侧实现）|
| ~~`group_temp`~~ | 别名归一成 `temp`（旧样例名）| 规范枚举只有 `friend/group/temp`（L266-291）|

> ⚠️ **Core 边界**：`src/core/message_router.py:238` 首行是 `if event.scope != "group": return` ——
> 私聊/临时会话**不进入群业务**（插件事件投递在此之前，仍可收到）。

## 事件类型（当前映射，`milky_parser.py::_event_kind`）
> ⚠️ **更正（2026-08-09）**：规范（`common.ts` 的 Event 联合，实测 **21 种**）里**没有 `notice_receive`** —— 通知类事件各有独立 `event_type`。
> 旧实现按 `notice_receive` 匹配，导致除消息外的事件全部落到 `kind=<event_type>`，连 notice 分支都进不去（**Milky 模式下戳一戳/文件上传等于失效**）。
> 现按事件类型归一化成领域 kind，业务分支（`_handle_poke` / `_handle_group_upload`）不变；`notice_receive` 仅为兼容旧样例保留。

| event_type | 归一化 kind | 处理 |
| --- | --- | --- |
| `message_receive` | `message` | 消息（`friend`/`stranger`/`temp` → 私聊；`group` → 群）|
| `group_nudge` | `notice`（kind=`poke`）| **戳一戳**：`sender_id`→actor、`receiver_id`→target、`group_id`→群 → 走 `_handle_poke` |
| `friend_nudge` | `notice`（kind=`poke`）| 好友戳一戳：`user_id` → 私聊 poke |
| `group_file_upload` | `notice`（kind=`group_upload`）| 群文件上传 → `notice_file{id,name,size}` → 走 `_handle_group_upload` |
| `message_recall` 等其余 11 种群/好友通知 | `notice` | `notice_kind` 取具体 event_type；业务侧暂未消费，插件可见 |
| `friend_request` / `group_join_request` / `group_invited_join_request` / `group_invitation` | `request` | `request_kind` = friend/group；字段级映射**已完成**（`request_scene`/`request_id`/`request_uid`/`request_filtered`/`comment`）|
| `bot_offline` | `lifecycle` | 生命周期 |
| 未识别的 | 原样保留 | 按 unknown 忽略（不阻塞主流程）|

## 适配层（实现说明）
| 文件 | 职责 |
| --- | --- |
| `src/adapters/milky_parser.py` | EventEnvelope → InternalEvent（event_type / message_scene / peer_id；段扫描 segments / mention / temp_url / message_seq）|
| `src/transport/action_channels.py` | **MilkyHTTPChannel**：`POST {MILKY_API_BASE}/api/<action>` + Bearer；`_MILKY_ACTIONS`（36 条）做动作名映射，字符串消息自动转 OutgoingSegment 数组；`_MILKY_UNSUPPORTED` 不发请求、直接返回明确错误。Milky 撤回走 `recall()`（群/私聊分流，入参 `message_seq`）|
| `src/transport/milky_ws_client.py` | `MilkyClient`：WS 客户端连 `/event`（`access_token` 参数；断线重连退避 5→10→20→40→60s；事件并发）|
| `src/services/sender.py` | 统一出口 `_post` → 通道；**不含协议分支**（协议开关只在 action_channels 读取，Gate B/O）|
| `main.py:242-244` | `QQ_PROTOCOL=milky` → `MilkyClient`（替代 NapCat 反向/正向 WS）|

## 能力对照（Milky vs OneBot）
> 数据源：官方 Milky API 文档（`milky.ntqqrev.org/api/` 的 system / message / friend / group / file 五组）与
> `src/transport/action_channels.py::_MILKY_ACTIONS` 逐一核对。**新增端点若忘记登记，CI 会失败**（`tests/test_milky_mapping.py`）。

| 能力 | Flowerie | OneBot | Milky 协议 | 说明 |
| :--- | :---: | :---: | :---: | :--- |
| 发送/回复消息 | ✓ | ✓ | ✓ | `send_group_message` / `send_private_message` |
| **多条回复（Multi-Reply）** | ✓ | ✓ | ✓ | 走同一条 sender 调用路径，自动共用 |
| 撤回消息 | ✓ | ✓ | ⚠️ | Milky 分 `recall_group_message` / `recall_private_message` 两个动作 |
| 群信息 / 群列表 | ✓ | ✓ | ✓ | `get_group_info` / `get_group_list` |
| 群成员信息 / 列表 | ✓ | ✓ | ✓ | `get_group_member_info` / `get_group_member_list` |
| 群名片 / 管理员 / 禁言 / 改名 / 头衔 | ✓ | ✓ | ✓ | `set_group_member_card` 等 |
| 全体禁言 | ✓ | ✓ | ✓ | `set_group_whole_mute` |
| 群公告 收发删 | ✓ | ✓ | ✓ | `send_group_announcement` / `get_group_announcements` / `delete_group_announcement` |
| 精华消息 设/查 | ✓ | ✓ | ✓ | `set_group_essence_message` / `get_group_essence_messages` |
| 表情回应 / 戳一戳 | ✓ | ✓ | ✓ | `send_group_message_reaction` / `send_group_nudge`（好友戳 `send_friend_nudge`）|
| 群文件 列/删/移/改名/建目录 + 下载地址 | ✓ | ✓ | ✓ | `get_group_files` / `delete_group_file` / `move_group_file` / `rename_group_folder` / `create_group_folder` / `get_group_file_download_url` |
| 好友列表 / 点赞 | ✓ | ✓ | ✓ | `get_friend_list` / `send_profile_like` |
| 历史消息 | ✓ | ✓ | ✓ | `get_history_messages` |
| 登录信息 / 实现信息 | ✓ | ✓ | ✓ | `get_login_info` / `get_impl_info` |
| 群荣誉 | ✓ | ✓ | ✗ | Milky 无对应接口（调用返回明确错误）|
| 在线客户端 | ✓ | ✓ | ✗ | 同上 |
| 删除精华 | ✓ | ✓ | ✗ | Milky 只有开关式 `set_group_essence_message` |
| 转发消息（发送） | ✓ | ✓ | ✗ | Milky 只提供读取 `get_forwarded_messages` |
| 群配置写入 | ✓ | ✓ | ✗ | Milky 未提供群配置写接口 |
| 修改自身资料 | ✓ | ✓ | ✗ | Milky 拆成 `set_nickname` / `set_bio` / `set_avatar`，语义不唯一 |

> 「Milky 协议」列读作**协议是否提供该能力**（✗ = 协议端没有此接口）；协议提供了但本仓库仍可能调不到的端点，见下面 §B 绕过点与全量对照表的「未接线」列。

**不支持的调用会怎样**：`_MILKY_UNSUPPORTED` 里的端点**不发请求**，直接返回「Milky 协议不支持该能力：xxx」——
不会把请求丢给协议端换回一个 404，便于上游如实降级。

### 明确不支持 / 尚未接线（两回事，别混）
**A. 协议层不支持（9 项，`_MILKY_UNSUPPORTED`）**：`get_group_honor_info`、`get_online_clients`、`delete_essence_msg`、
`send_group_forward_msg`、`send_private_forward_msg`、`set_group_config`、`set_self_profile`、`set_friend_add_request`、`set_group_add_request`。
最后两个 ⚠️ **已过时（文档同步 2026-09-25）**：Milky 1.3 已提供 `accept_friend_request`/`reject_friend_request`、
`accept_group_request`/`reject_group_request`（及 `accept_group_invitation`/`reject_group_invitation`）—— 不再是「协议不支持」，而是**本仓库尚未接线**。

**B. 仍绕过统一入口的端点（已知缺口）**：`tests/test_milky_mapping.py::test_direct_post_sites_only_shrink` 把"绕过 `_post` 的端点集合"锁成**只许减少**。
守卫扫描 `src/services/sender.py` + `src/transport/action_channels.py`，实测 5 个：`delete_msg`（OneBot 通道 `recall()` 直连；Milky 通道已覆写）、`get_msg`、
`get_group_msg_history`、`get_group_member_info`、`get_group_member_list`（后四个返回体是 OneBot 结构，如 `raw_message`，需按 Milky 响应逐字段对齐后再转）。
`send_group_msg` / `send_private_msg` 现已**全部走 `_post`**（`src/services/sender.py:109/136/175`）；`KNOWN_BYPASS` 里的 `send_group_msg` 属历史遗留（测试只断言"不许新增"，留着不影响）。
⚠️ **守卫未覆盖**：`src/services/file_parser.py:272` 的 `/get_forward_msg` 仍是直连 —— **Milky 模式下合并转发拉取会打到 OneBot 地址**。

### 官方 API 全量对照（同步 2026-09-25）
> 数据源：官方协议定义 [`protocol/src/ir/api/*.ts`](https://github.com/SaltifyDev/milky/tree/main/protocol/src/ir/api)（Milky **1.3**），
> 同步页 `milky.ntqqrev.org/api/{system,message,friend,group,file}`。共 **65 个动作**：system 17 · message 9 · friend 6 · group 21 · file 12。
> 「本仓库」= 是否接线（`_MILKY_ACTIONS` 映射，或 `MilkyHTTPChannel.recall()` 直接调用）：**35 已接线 / 30 未接线**。
> 原来按组拆的五张表合并如下（动作名一个不丢；每条动作的中文释义是动作名的直译，已随表合并略去）。

| 组（总数）| 已接线：官方动作 ← 本仓库端点 | 未接线（官方有、本仓库未用）|
| :--- | :--- | :--- |
| system（17）| `get_friend_list`←`get_friend_list`；`get_group_info`←`get_group_config`/`get_group_info`；`get_group_list`←`get_group_list`；`get_impl_info`←`get_status`；`get_login_info`←`get_login_info` | `get_cookies` `get_csrf_token` `get_custom_face_url_list` `get_friend_info` `get_group_member_info` `get_group_member_list` `get_peer_pins` `get_user_profile` `set_avatar` `set_bio` `set_nickname` `set_peer_pin`（12）|
| message（9）| `send_group_message`←`send_group_msg`；`send_private_message`←`send_private_msg`；`get_history_messages`←`get_friend_msg_history`；`get_resource_temp_url`←`get_group_res`；`recall_group_message`/`recall_private_message`←`delete_msg`（`recall()` 分流，**不在** `_MILKY_ACTIONS` 里）| `get_forwarded_messages` `get_message` `mark_message_as_read`（3）|
| friend（6）| `send_friend_nudge`←`friend_poke`；`send_profile_like`←`set_friend_profile_like` | `accept_friend_request` `delete_friend` `get_friend_requests` `reject_friend_request`（4）|
| group（21）| `delete_group_announcement`←`_del_group_notice`；`get_group_announcements`←`get_group_notice`；`get_group_essence_messages`←`get_essence_msg_list`；`kick_group_member`←`set_group_kick`；`send_group_announcement`←`send_group_notice`；`send_group_message_reaction`←`set_group_reaction`/`set_react`；`send_group_nudge`←`send_poke`；`set_group_avatar`←`set_group_portrait`；`set_group_essence_message`←`set_essence_msg`；`set_group_member_admin`←`set_group_admin`；`set_group_member_card`←`set_group_card`；`set_group_member_mute`←`set_group_ban`；`set_group_member_special_title`←`set_group_special_title`；`set_group_name`←`set_group_name`；`set_group_whole_mute`←`set_group_whole_ban` | `accept_group_invitation` `accept_group_request` `get_group_notifications` `quit_group` `reject_group_invitation` `reject_group_request`（6）|
| file（12）| `create_group_folder`←`create_group_file_folder`；`delete_group_file`←`delete_group_file`；`delete_group_folder`←`delete_group_folder`；`get_group_file_download_url`←`get_group_file_url`；`get_group_files`←`get_group_files_by_folder`/`get_group_root_files`；`move_group_file`←`move_group_file`；`rename_group_folder`←`rename_group_file_folder` | `get_private_file_download_url` `persist_group_file` `rename_group_file` `upload_group_file` `upload_private_file`（5）|

> ⚠️ 未接线清单里的 6 个「好友/群请求与邀请的同意-拒绝」动作是**可接线缺口**（协议已支持，仓库尚未接）；
> 接线需改 `src/transport/action_channels.py::_MILKY_ACTIONS`，本次只同步文档。

## 已知边界（真机联调时请反馈）
- **发送图片/语音段**：Milky 发送段的 `data`（`resource_id` 需先上传）—— Flowerie 当前 **text 发送完整可用**，多媒体发送待联调
  （`src/adapters/capabilities.py`：Milky `image.send` / `file.send` = `unsupported`，`face.send` / `market_face.send` = `partial`）
- **消息号（已修）**：Milky 只有 `message_seq`（事件 / 发送响应 / 撤回入参都是它）—— 现已映射到 `message_id`，撤回按群/私聊分流；OneBot 行为不变
- **段字段宽度**：规范与两份实现不完全一致（`market_face` 实现只有 `url`、`face` 无 `is_large`）—— 按可选字段解析，缺失时不报错只降级描述
- ~~notice 的 event_type 完整命名~~ **已修（2026-08-09）**：21 种事件类型已按 kind 归一化（见上表）；请求类事件字段级映射**已完成**：四类（含 `group_invitation`）字段与标识（`notification_seq`）均已归一化
- **响应 retcode 语义**：`status=ok`，或（无 `status` 且 `retcode ∈ {0, None}`）= 成功；实现见 `src/transport/milky_response.py`

> 使用问题可提 Issue。
