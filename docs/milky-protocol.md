# Milky 协议支持（Milky 特供版）

> **维护状态：停更一年（2026-09-04 起）** —— 仓库不归档，停更期间的兼容性维护以 2.2.2xx 递增发布；
> Milky 支持随维护版继续补齐（本文已同步至 Milky 协议 1.3）；OneBot 版 v2.2.2 资产仍保留在 [v2.2.2 Release](https://github.com/lingcat521/Flowerie_bot/releases/tag/v2.2.2)。

## 背景
Milky 是新一代 QQ 机器人协议标准（Lagrange.Core V2 已放弃 OneBot 转向 Milky）；
本适配让 Flowerie 直连 Milky 协议端（Lagrange.Milky / Yogurt 等），同一套 AI/人设/记忆/群规则零改动。

## 配置（.env）
```ini
# 协议切换（默认 onebot 不变）
QQ_PROTOCOL=milky
# Milky 协议端 HTTP（/api/<action> 调用）
MILKY_API_BASE=http://127.0.0.1:8080
# Milky 事件推送 WebSocket（应用端主动连接）
MILKY_EVENT_URL=ws://127.0.0.1:8080/event
# Bearer 鉴权（协议端配置的 access_token）
MILKY_ACCESS_TOKEN=
```
也可在 Web UI 配置页（Bot 分类）修改。

## 启动
```bash
python main.py
# 日志出现 "Milky event connected" 即连接成功
```

## 协议端（Milky）配置
| 项 | 值 |
| --- | --- |
| HTTP 服务 | 开（`/api` 入口）|
| 事件推送 | WebSocket（`/event`）|
| access_token | 与 `MILKY_ACCESS_TOKEN` 一致 |

## 事件格式（EventEnvelope）
```json
{
  "time": 1234567890,
  "event_type": "message_receive",
  "data": {
    "message_scene": "group",
    "peer_id": 786368680,
    "sender_id": 297205104,
    "segments": [ ... ]
  }
}
```

### 消息段（已按官方 SDK 对齐）
| 语义 | 段 `type` | `data` 字段 | 说明 |
| --- | --- | --- | --- |
| 文本 | `text` | `text` | |
| @某人 | `mention` | `user_id` | 与 OneBot `at/qq` 不同 |
| @全体 | `mention_all` | — | |
| 图片 | `image` | `temp_url` + `resource_id`（+width/height/summary/sub_type）| 识图用 temp_url |
| 回复 | `reply` | `message_seq` | 引用消息序列号 |
| 表情 | `face` | `face_id` | |
| 语音 | `record` | `resource_id` + `temp_url` + `duration` | |
| 视频 | `video` | `resource_id` + `temp_url` | |
| 转发 | `forward` | — | |

⚠️ **与 OneBot 的差异**：
- 段容器字段是 **`segments`**（OneBot 是 `message`）
- @ 用 **`mention`/`user_id`**（OneBot `at`/`qq`）
- 图片用 **`temp_url`**（临时 URL；OneBot `file/url`）
- 回复用 **`message_seq`**（OneBot `id`）

## API 调用（发送）
```
POST {MILKY_API_BASE}/api/send_group_message
POST {MILKY_API_BASE}/api/send_private_message
Authorization: Bearer <access_token>
{"group_id": 123, "message": [{"type": "text", "data": {"text": "hi"}}]}
```
- 消息必须是 **OutgoingSegment 数组**（字符串自动转 text 段）
- action 名与 OneBot 的映射：`send_group_msg→send_group_message`、`send_private_msg→send_private_message`

## 事件类型（当前映射）
| event_type | 处理 |
| --- | --- |
| `message_receive` | 消息（message_scene: friend/stranger→私聊；group/group_temp→群）|
| `notice_receive` | 通知（notice_kind 取 data.notice_type）|
| `lifecycle` | 生命周期 |
| 其他 | 按 unknown 忽略（不阻塞主流程）|

## 适配层（实现说明）
| 文件 | 职责 |
| --- | --- |
| `src/adapters/milky_parser.py` | EventEnvelope → InternalEvent（event_type/message_scene/peer_id；段扫描 segments/mention/temp_url/message_seq）|
| `src/services/sender.py` | Milky 模式：`/api/<action>` + Bearer（action 映射；消息自动转 OutgoingSegment 数组）|
| `src/core/milky_client.py` | WS 客户端连 `/event`（access_token 参数；断线重连 5→60s 退避；事件并发）|
| `main.py` | `QQ_PROTOCOL=milky` → MilkyClient（替代 NapCat 反向/正向）|

## API 能力表（Milky vs OneBot）

> 数据来源：官方 Milky API 文档（`milky.ntqqrev.org/api/` 的 system / message / friend / group / file 五组）
> 与仓库内 `src/services/sender.py` 的 `_MILKY_ACTIONS` 映射表逐一核对。
> **新增端点若忘记登记，CI 会失败**（`tests/test_milky_mapping.py`）。

| 能力 | Flowerie | OneBot | Milky | 说明 |
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
| 表情回应 / 戳一戳 | ✓ | ✓ | ✓ | `send_group_message_reaction` / `send_group_nudge`（好友戳 `send_friend_nudge`） |
| 群文件 列/删/移/改名/建目录 | ✓ | ✓ | ✓ | `get_group_files` / `delete_group_file` / `move_group_file` / `rename_group_folder` / `create_group_folder` |
| 群文件下载地址 | ✓ | ✓ | ✓ | `get_group_file_download_url` |
| 好友列表 / 点赞 | ✓ | ✓ | ✓ | `get_friend_list` / `send_profile_like` |
| 历史消息 | ✓ | ✓ | ✓ | `get_history_messages` |
| 登录信息 / 实现信息 | ✓ | ✓ | ✓ | `get_login_info` / `get_impl_info` |
| 群荣誉 | ✓ | ✓ | ✗ | Milky 无对应接口（调用返回明确错误） |
| 在线客户端 | ✓ | ✓ | ✗ | 同上 |
| 删除精华 | ✓ | ✓ | ✗ | Milky 只有开关式 `set_group_essence_message` |
| 转发消息（发送） | ✓ | ✓ | ✗ | Milky 只提供读取 `get_forwarded_messages` |
| 群配置写入 | ✓ | ✓ | ✗ | Milky 未提供群配置写接口 |
| 修改自身资料 | ✓ | ✓ | ✗ | Milky 拆成 `set_nickname` / `set_bio` / `set_avatar`，语义不唯一 |

**不支持的调用会怎样**：`Sender` 在 Milky 模式下遇到这些端点会**直接返回明确错误**
（`Milky 协议不支持该能力：xxx`），不会把请求丢给协议端换回一个 404 —— 便于上游如实降级。
## 统一入口与已知缺口（实现约束）

**所有出站调用必须经过 `Sender._post`** —— 它统一处理三件事：

1. **动作名映射**：`_MILKY_ACTIONS`（Milky 模式把 OneBot 端点名换成 Milky 官方动作名）
2. **鉴权与协议差异**：Milky 模式补 `Authorization: Bearer <MILKY_ACCESS_TOKEN>`，
   并把字符串消息自动转成 Milky 要求的段数组 `[{"type":"text","data":{"text":...}}]`
3. **能力缺失的明确处理**：`_MILKY_UNSUPPORTED` 里的端点**不发请求**，直接返回
   「Milky 协议不支持该能力：xxx」，便于上游如实降级

### 明确不支持的能力（9 项）

| 端点 | 原因 |
| :--- | :--- |
| `get_group_honor_info` | Milky 未提供群荣誉接口 |
| `get_online_clients` | Milky 未提供在线客户端列表 |
| `delete_essence_msg` | Milky 只有开关式 `set_group_essence_message` |
| `send_group_forward_msg` / `send_private_forward_msg` | Milky 只提供读取 `get_forwarded_messages` |
| `set_friend_add_request` / `set_group_add_request` | Milky ⚠️ **已过时（文档同步 2026-09-25）**：官方协议 1.3 已提供 `accept_friend_request` / `reject_friend_request`、`accept_group_request` / `reject_group_request`（及 `accept_group_invitation` / `reject_group_invitation`）——不再是「协议不支持」，而是**本仓库尚未接线**（见下方全量对照表） |
| `set_group_config` | Milky 未提供群配置写接口 |
| `set_self_profile` | Milky 拆成 `set_nickname` / `set_bio` / `set_avatar`，语义不唯一 |

### 仍绕过统一入口的端点（6 处，已知缺口）

这些方法目前仍直接 `session.post`，**Milky 模式下会打到 OneBot 地址**；
`tests/test_milky_mapping.py::test_direct_post_sites_only_shrink` 把它锁成"只许减少"：

| 端点 | 为什么还没转 |
| :--- | :--- |
| `send_group_msg` / `send_private_msg`（带图发送、其余直连处） | 需逐处核对调用方对返回值的用法 |
| `delete_msg` | Milky 分 `recall_group_message` / `recall_private_message`，当前签名只有 message_id（缺场景） |
| `get_msg` / `get_group_msg_history` / `get_group_member_info` / `get_group_member_list` | 返回体是 OneBot 结构（如 `raw_message`），需按 Milky 响应逐字段对齐后再转 |

### 官方 API 全量对照（同步 2026-09-25）

> 数据源：官方协议定义 [`protocol/src/ir/api/*.ts`](https://github.com/SaltifyDev/milky/tree/main/protocol/src/ir/api)（Milky 协议 **1.3**），同步页 `milky.ntqqrev.org/api/{system,message,friend,group,file}`。
> 共 **65 个动作**：system 17 · message 9 · friend 6 · group 21 · file 12。
> 「本仓库」列 = `src/services/sender.py::_MILKY_ACTIONS` 是否接线（`—` = 尚未使用）；未登记的新端点会让 `tests/test_milky_mapping.py` 失败。

#### 系统 API（17）

| 动作 | 说明 | 本仓库 |
| :--- | :--- | :--- |
| `get_cookies` | 获取 Cookies | — |
| `get_csrf_token` | 获取 CSRF Token | — |
| `get_custom_face_url_list` | 获取自定义表情 URL 列表 | — |
| `get_friend_info` | 获取好友信息 | — |
| `get_friend_list` | 获取好友列表 | ✓ `get_friend_list` |
| `get_group_info` | 获取群信息 | ✓ `get_group_config` / `get_group_info` |
| `get_group_list` | 获取群列表 | ✓ `get_group_list` |
| `get_group_member_info` | 获取群成员信息 | — |
| `get_group_member_list` | 获取群成员列表 | — |
| `get_impl_info` | 获取协议端信息 | ✓ `get_status` |
| `get_login_info` | 获取登录信息 | ✓ `get_login_info` |
| `get_peer_pins` | 获取置顶的好友和群列表 | — |
| `get_user_profile` | 获取用户个人信息 | — |
| `set_avatar` | 设置 QQ 账号头像 | — |
| `set_bio` | 设置 QQ 账号个性签名 | — |
| `set_nickname` | 设置 QQ 账号昵称 | — |
| `set_peer_pin` | 设置好友或群的置顶状态 | — |

#### 消息 API（9）

| 动作 | 说明 | 本仓库 |
| :--- | :--- | :--- |
| `get_forwarded_messages` | 获取合并转发消息内容 | — |
| `get_history_messages` | 获取历史消息列表 | ✓ `get_friend_msg_history` |
| `get_message` | 获取消息 | — |
| `get_resource_temp_url` | 获取临时资源链接 | ✓ `get_group_res` |
| `mark_message_as_read` | 标记消息为已读 | — |
| `recall_group_message` | 撤回群聊消息 | — |
| `recall_private_message` | 撤回私聊消息 | — |
| `send_group_message` | 发送群聊消息 | ✓ `send_group_msg` |
| `send_private_message` | 发送私聊消息 | ✓ `send_private_msg` |

#### 好友 API（6）

| 动作 | 说明 | 本仓库 |
| :--- | :--- | :--- |
| `accept_friend_request` | 同意好友请求 | — |
| `delete_friend` | 删除好友 | — |
| `get_friend_requests` | 获取好友请求列表 | — |
| `reject_friend_request` | 拒绝好友请求 | — |
| `send_friend_nudge` | 发送好友戳一戳 | ✓ `friend_poke` |
| `send_profile_like` | 发送名片点赞 | ✓ `set_friend_profile_like` |

#### 群组 API（21）

| 动作 | 说明 | 本仓库 |
| :--- | :--- | :--- |
| `accept_group_invitation` | 同意他人邀请自身入群 | — |
| `accept_group_request` | 同意入群/邀请他人入群请求 | — |
| `delete_group_announcement` | 删除群公告 | ✓ `_del_group_notice` |
| `get_group_announcements` | 获取群公告列表 | ✓ `get_group_notice` |
| `get_group_essence_messages` | 获取群精华消息列表 | ✓ `get_essence_msg_list` |
| `get_group_notifications` | 获取群通知列表 | — |
| `kick_group_member` | 踢出群成员 | ✓ `set_group_kick` |
| `quit_group` | 退出群 | — |
| `reject_group_invitation` | 拒绝他人邀请自身入群 | — |
| `reject_group_request` | 拒绝入群/邀请他人入群请求 | — |
| `send_group_announcement` | 发送群公告 | ✓ `send_group_notice` |
| `send_group_message_reaction` | 发送群消息表情回应 | ✓ `set_group_reaction` / `set_react` |
| `send_group_nudge` | 发送群戳一戳 | ✓ `send_poke` |
| `set_group_avatar` | 设置群头像 | ✓ `set_group_portrait` |
| `set_group_essence_message` | 设置群精华消息 | ✓ `set_essence_msg` |
| `set_group_member_admin` | 设置群管理员 | ✓ `set_group_admin` |
| `set_group_member_card` | 设置群名片 | ✓ `set_group_card` |
| `set_group_member_mute` | 设置群成员禁言 | ✓ `set_group_ban` |
| `set_group_member_special_title` | 设置群成员专属头衔 | ✓ `set_group_special_title` |
| `set_group_name` | 设置群名称 | ✓ `set_group_name` |
| `set_group_whole_mute` | 设置群全员禁言 | ✓ `set_group_whole_ban` |

#### 文件 API（12）

| 动作 | 说明 | 本仓库 |
| :--- | :--- | :--- |
| `create_group_folder` | 创建群文件夹 | ✓ `create_group_file_folder` |
| `delete_group_file` | 删除群文件 | ✓ `delete_group_file` |
| `delete_group_folder` | 删除群文件夹 | ✓ `delete_group_folder` |
| `get_group_file_download_url` | 获取群文件下载链接 | ✓ `get_group_file_url` |
| `get_group_files` | 获取群文件列表 | ✓ `get_group_files_by_folder` / `get_group_root_files` |
| `get_private_file_download_url` | 获取私聊文件下载链接 | — |
| `move_group_file` | 移动群文件 | ✓ `move_group_file` |
| `persist_group_file` | 转存群文件为永久文件 | — |
| `rename_group_file` | 重命名群文件 | — |
| `rename_group_folder` | 重命名群文件夹 | ✓ `rename_group_file_folder` |
| `upload_group_file` | 上传群文件 | — |
| `upload_private_file` | 上传私聊文件 | — |

### 尚未接线的官方动作（32 个）

- **系统**：`get_cookies` `get_csrf_token` `get_custom_face_url_list` `get_friend_info` `get_group_member_info` `get_group_member_list` `get_peer_pins` `get_user_profile` `set_avatar` `set_bio` `set_nickname` `set_peer_pin`
- **消息**：`get_forwarded_messages` `get_message` `mark_message_as_read` `recall_group_message` `recall_private_message`
- **好友**：`accept_friend_request` `delete_friend` `get_friend_requests` `reject_friend_request`
- **群组**：`accept_group_invitation` `accept_group_request` `get_group_notifications` `quit_group` `reject_group_invitation` `reject_group_request`
- **文件**：`get_private_file_download_url` `persist_group_file` `rename_group_file` `upload_group_file` `upload_private_file`

> ⚠️ 上面未接线清单里的 6 个「好友/群请求与邀请的同意-拒绝」动作是**可接线缺口**（协议已支持，仓库尚未接）；接线需改 `src/services/sender.py`，本次只同步文档。

## 已知边界（真机联调时请反馈）
- **发送图片/语音段**：Milky 发送段 data（resource_id 需先上传）——Flowerie 当前 text 发送完整可用；多媒体发送待联调
- notice 的 event_type 完整命名（目前按 notice_receive 匹配）
- 响应 retcode 语义（200 + retcode 0/None = 成功）

> 使用问题可提 Issue（不保证修复——项目停更中）。
