# Milky 协议支持（Milky 特供版）

> 📦 **维护状态：停更（v2.2.2-milky 为 Milky 适配最终版）**——Flowerie 停更，本版为 Milky 协议适配的收官版本；OneBot 版 v2.2.2 资产继续保留在 [v2.2.2 Release](https://github.com/lingcat521/Flowerie_bot/releases/tag/v2.2.2)。

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
| `set_friend_add_request` / `set_group_add_request` | Milky 只提供 `get_friend_requests` / `get_group_notifications` **读取**，无批准动作 |
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

## 已知边界（真机联调时请反馈）
- **发送图片/语音段**：Milky 发送段 data（resource_id 需先上传）——Flowerie 当前 text 发送完整可用；多媒体发送待联调
- notice 的 event_type 完整命名（目前按 notice_receive 匹配）
- 响应 retcode 语义（200 + retcode 0/None = 成功）

> 使用问题可提 Issue（不保证修复——项目停更中）。
