# 表情包（Sticker）

默认关闭。开启后启动扫描目录、为每张图生成**详细描述**（80–150 字），聊天时模型可
通过三种通道之一发出表情包。**文本与图片永远分开成两条消息**。

| 配置项 | 默认 | 说明 |
| :--- | :--- | :--- |
| `STICKER_ENABLED` | `false` | 总开关（与 `STICKER_DIR` 同时非空才生效） |
| `STICKER_DIR` | 空（=禁用） | 图片目录（jpg/png/gif/webp/bmp），**需重启**；只允许该目录内文件 |
| `STICKER_DB_PATH` | `./data/stickers.db` | 描述索引库（SQLite，需重启） |
| `STICKER_MAX_LIST` | `30` | 每次注入给模型的描述条数上限（防 token 膨胀） |
| `STICKER_COOLDOWN` | `60` | 每群两次发图的最小间隔（秒） |
| `STICKER_MARKER_ENABLED` | `true` | 允许模型用 `[STICKER:文件名]` 标记选图（**标记永远剥离，不与分句开关耦合**） |
| `STICKER_REPLY_PROBABILITY` | `0.10` | 被 @／叫名字回复后附带随机图的概率 |
| `STICKER_INDEX_LIMIT` | `30` | 单次扫描新索引上限（`0`=不限；主模型直看时每张要一次模型调用） |
| `STICKER_INDEX_WORKERS` | `4` | 索引并发数（`0`/空=不限） |
| `STICKER_NATIVE_MAX_IMAGES` | `4` | 主模型原生识图时，选图上下文里内联的候选图张数（其余只给文字描述） |
| `AI_STICKER_ENABLED` | `false` | 开启 AI 工具通道（`sticker_search` / `sticker_send`），Web UI「自动化」抽屉 |

## 三种发送通道

三者互不冲突，可分别开关：

1. **文本标记**（`STICKER_MARKER_ENABLED`）
   模型在回复里写 `[STICKER:文件名]`。**解析层第一步就剥离**该标记
   （`reply_parser.parse_reply_content` → `SplitSegments.stickers`），
   文本按分句规则发出后，图片作为**独立消息**发送。
   与 `SPLIT_REPLY_ENABLED` **完全解耦**——关掉分句也不会把标记泄漏给用户。

2. **概率附图**（`STICKER_REPLY_PROBABILITY`）
   被 @／直接回复／叫名字时，正文发完后按概率附带一张随机表情包。受群级冷却约束。

3. **AI 工具调用**（`AI_STICKER_ENABLED`）
   `sticker_search(keyword)` 按情绪/动作/文件名检索候选，`sticker_send(filename)` 发图。
   模型自己决定何时用，冷却中调用返回 `{"ok":false,"error":"cooldown"}`。

## 工作机制

1. **索引**：启动扫描 `STICKER_DIR`，新图片交**识图路由**生成描述，缓存到 SQLite。
   - 主模型原生识图（`VISION_ROUTE_MODE`）→ 主模型自己看图写描述
   - 否则 → 外部视觉模型（`VISION_MODEL`）描述
   - 受 `STICKER_INDEX_LIMIT` / `STICKER_INDEX_WORKERS` 控制批量与并发
2. **去重**：以文件 **SHA-256** 为内容身份——重启复用缓存，**不重复调用模型**；
   同名不同内容才重新分析。
3. **选择与防刷屏**：注入描述列表 + `STICKER_COOLDOWN` 群级冷却。

## 图片格式

- **GIF 保留动图**：本地文件以原字节上传（官方富媒体接口的 `file_data` 通道支持 GIF）。
- 若平台拒收 GIF，桥接器会自动降级为首帧 PNG（日志事件 `gif_rejected_fallback_png`），保证「至少图能到」。
- 描述生成阶段 GIF 取**首帧**降采样（避免 base64 体积过大）。

## 容错与安全

- **识图失败**：记录 failed 状态，不阻塞启动、不每条消息重试；**超过 24h 才允许重试**。
- **路径安全**：只允许 `STICKER_DIR` 目录内的文件，目录不匹配或非文件一律拒绝。
- **冷却**：工具通道与概率附图共用 `STICKER_COOLDOWN`，避免刷屏。
- **测试**：`pytest tests/test_sticker_manager.py -q`

## 部署提示

- 官方桥接部署下，桥接器需支持本地文件发送（`file://` → 官方 `files` 接口的 `file_data`）；
  纯 URL 通道（`post_group_file url=`）无法发送本地图片。
- NapCat 等 OneBot11 实现原生支持 `image` 段的 `file://` 绝对路径，无需额外处理。
