# OneBot v11 全平台兼容（v2.2.2 起）

> 目标：同一 Flowerie 实例**不区分** NapCat / Lagrange / LLOneBot / Koishi 等 OneBot v11 实现 —— 收发与动作尽力而为；
> 支持则用，**不支持显式报错**（绝不静默）。逐客户端差异见 [client-compatibility.md](client-compatibility.md)。

## 连接层（三模式；默认值以 `src/config.py` 为准）
| 模式 | 说明 | 配置 |
| :--- | :--- | :--- |
| 反向 WS（默认）| 实现主动连入 bot | `NAPCAT_WS_MODE=reverse`；监听 `WS_HOST:WS_PORT` = `127.0.0.1:3001` |
| 正向 WS | bot 连实现的 WS server | `NAPCAT_WS_MODE=forward` + `NAPCAT_WS_URL`（必填，ws/wss）|
| HTTP 发送 | 经典 OneBot HTTP API | 无 WS 发送器时自动走 HTTP；`HTTP_API_BASE` 默认 `127.0.0.1:3000` |

发送通道 `SEND_VIA_WS`（默认 `auto`；判据 `src/transport/action_channels.py::_ws_enabled`）：
`auto` = 有 WS 发送器走 WS、没有走 HTTP（**WS 发送失败不静默换通道**）；`true` = 有 WS 只走 WS、没有则 HTTP；`false` = 仅 HTTP。

## 图片识图：`image.file` 优先（核心兼容点）
- **优先** `image.file`（OneBot 标准段属性，任何实现都下发本地路径）→ 本地读文件识图，**绕开** NT CDN 的 302/UA/Referer/链接过期；
  兜底 `image.url`（file 缺失或不可读）。路径容错：剥 `file://` 前缀、相对路径试 CWD/Android data
- 证据：`src/core/message_assembler.py::_describe_images`（file 先入队列，url 仅补齐）

## 动作能力
- **37 个**语义动作走标准端点（`send_group_msg` 等），全实现一致：`_SENDER_ACTIONS` 表（`src/plugins/manager.py:2674`）；实现特有点（如 Lagrange `get_group_res`）标注在表内，不支持的端点返回**明确错误**
- ⚠️ **能力是静态声明，不是运行时探测**：`src/adapters/capabilities.py` 按协议登记 18 项能力（`AdapterDescriptor`），只由组合根（`src/adapters/container.py`、`instance.py`）与测试消费，**服务层不查询** —— 不存在"连接后自动探测能力 / NS 降级"
- **Multi-Reply / Native Reply Tool 协议无关**：只产出 `ReplyPlan`（`src/core/reply_plan.py`），经同一 `Sender` 逐条发送，OneBot 与 Milky 同链路（Milky 映射见 [milky-protocol.md](milky-protocol.md)）

## 名字唤起与验证（都与协议无关）
`BOT_NICKNAME`（默认 `花璃`）+ 群特色昵称**同时参与**，任一命中必回（不带 @ 也回）—— `src/core/name_mention.py`
验证：`curl "http://127.0.0.1:3000/get_status"`（`HTTP_API_BASE` 默认端口）；或任一实现启动后聊天/发图，看日志 `message_send_finished` + Vision 无警告。
