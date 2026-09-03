# OneBot v11 全平台兼容（v2.2.2 封版）

> 目标：同一 Flowerie 实例，**不区分** NapCat / Lagrange / LLOneBot / Koishi 等
> OneBot v11 实现——收发、识图、动作尽力而为：支持则该用，不支持显式报错（绝不静默）。

## 连接层（三模式自动/可配）
| 模式 | 说明 | 配置 |
| --- | --- | --- |
| 反向 WS | NapCat 等主动连入 bot（1145）| 默认 |
| 正向 WS | bot 连接实现的 WS server | `NAPCAT_WS_MODE=forward` |
| HTTP 发送 | 经典 OneBot HTTP API | `SEND_VIA_WS=false` 或 auto 回退 |

## 发送通道：`SEND_VIA_WS`（三值）
| 值 | 行为 |
| --- | --- |
| `auto`（默认）| WS 优先（实现如只开 WS）→ 失败/未连回退 HTTP |
| `true` | 仅 WS |
| `false` | 仅 HTTP |

## 图片识图：file 字段优先（核心兼容点）
- **优先** `image.file`（OneBot 标准段属性；任何实现都下发本地路径）→ 本地读文件识图
  ——**彻底绕开** NT CDN 302/UA/Referer/链接过期问题
- 兜底 `image.url`（file 缺失或不可读时）
- 路径容错：`file://` 前缀剥离；相对路径尝试 CWD/Android data

## 动作能力矩阵（_SENDER_ACTIONS 表驱动）
- 37 个语义动作走标准端点（`send_group_msg` 等）——全实现一致
- 实现特有点（如 Lagrange `get_group_res`）标注在表内；不支持返回明确错误
- 连接后自动探测能力（`capabilities`）——未探测到走 NS 降级（现有语义已设计）

## 验证方法
```bash
curl "http://127.0.0.1:3000/get_status"   # HTTP 连通性
# 或用任一实现启动后直接聊天/发图，看 message_send_finished + Vision 无警告
```


## 名字唤起（100% 回复）
- 消息文本含 `BOT_NICKNAME`（环境变量/配置）→ 必回（不带 @ 也回）
- **参与名字**：`BOT_NICKNAME` + 群特色昵称**同时参与**（改 BOT_NICKNAME 即生效；群昵称也触发）
