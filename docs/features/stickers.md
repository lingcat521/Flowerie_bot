# 表情包（Sticker）

默认关闭。开启后启动扫描目录、用视觉模型为每张图生成一句话描述；聊天时**只把描述列表**给模型（不传图片本体）。

| 配置项 | 默认 | 说明 |
| :--- | :--- | :--- |
| `STICKER_ENABLED` | `false` | 总开关（与 `STICKER_DIR` 同时非空才生效，`src/services/sticker_manager.py:40`） |
| `STICKER_DIR` | 空（=禁用） | 图片目录（jpg/png/gif/webp/bmp），**需重启**；只允许该目录内文件 |
| `STICKER_DB_PATH` | `./data/stickers.db` | 视觉描述索引库（SQLite，需重启） |
| `STICKER_MAX_LIST` | `30` | 每次注入给模型的描述条数上限（防 token 膨胀） |
| `STICKER_COOLDOWN` | `60` | 每群两次发图的最小间隔（秒） |

## 工作机制

1. **索引**：启动扫描 `STICKER_DIR`，新图片交视觉模型生成一句话描述，缓存到 SQLite。
2. **去重**：以文件 **SHA-256** 为内容身份——重启复用缓存，**不重复调用 Vision**；同名不同内容才重新分析（`sticker_manager.py:80`）。
3. **选择与防刷屏**：注入的描述列表即提示"如语境合适可附加 `[STICKER:文件名]`，最多一张"；发送时自动剥离标记（`strip_sticker_marker`），每群受 `STICKER_COOLDOWN` 冷却约束（`can_send`）。

## 容错与安全

- **Vision 失败**：记录 failed 状态，不阻塞启动、不每条消息重试；**超过 24h 才允许重试**（`_FAILED_RETRY_AFTER=86400`）。
- **路径安全**：只允许 `STICKER_DIR` 目录内的文件，目录不匹配或非文件一律拒绝（`sticker_manager.py:116-129`）；**测试**：`pytest tests/test_sticker_manager.py -q`。

