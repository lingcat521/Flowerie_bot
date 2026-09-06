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

## 已知边界（真机联调时请反馈）
- **发送图片/语音段**：Milky 发送段 data（resource_id 需先上传）——Flowerie 当前 text 发送完整可用；多媒体发送待联调
- notice 的 event_type 完整命名（目前按 notice_receive 匹配）
- 响应 retcode 语义（200 + retcode 0/None = 成功）

> 使用问题可提 Issue（不保证修复——项目停更中）。
