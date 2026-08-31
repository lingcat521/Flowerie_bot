# Phase 6 审计：message_assembler 的 OneBot 字段消费（只审计）

## 1. 4 方法消费的 OneBot 段字段

| 方法 | 消费的 OneBot 内容 | 对应 InternalEvent 语义字段 | 行为风险 |
| --- | --- | --- | --- |
| `assemble`（入口） | `message_array: List[Dict]`（段数组） | event.message_segments（保留段列表） | 低：组装器仍可读段（boundary 已提供） |
| `_describe_images` | `seg["type"]=="image"` + `data["url"]` | event.images | **中：旧行为只认 url（file 路径不描述）；event.images 为 url-or-file（SDK 语义）→ 迁移须 http 过滤，行为等价** |
| `_scan_reply_and_at` | reply 段 `data.qq` / at 段 `data.qq` | event.is_reply_to_bot / has_reply_to_other / has_at_others（parser 同规则实现） | 低：同规则，等价可直接替换并删除本方法 |
| `_assemble_forward` | **委托 file_parser.extract_forward_messages(message_array)**（冻结） | 无（保留 message_segments 传参） | **无**：file_parser 冻结，调用形态不变 |
| `_assemble_card` | **委托 file_parser.extract_json_card_content(message_array)**（冻结） | 无（保留 message_segments 传参） | **无**：同上 |

## 2. 迁移设计（预计 ±30 行，≤50 红线）

```diff
- async def assemble(self, message_array, user_id, group_id, raw_time):
+ async def assemble(self, event, *, user_id, group_id, raw_time):
+     message_array = event.message_segments or []     # 组装器保留段（boundary 已规范化）
-     clean_text, is_mentioned = self.file_parser.extract_mention_and_text(message_array, ...)
+     clean_text = event.text                          # 等价格（parser 同规则）
+     is_mentioned = event.is_mentioned
-     image_descriptions = await self._describe_images(message_array)
+     image_descriptions = await self._describe_images(event)   # 内部：http 过滤后的 event.images
-     is_reply_to_bot, ... = self._scan_reply_and_at(message_array)
+     is_reply_to_bot = event.is_reply_to_bot; ...（直取，删除 _scan_reply_and_at）
     full_text += await self._assemble_forward(message_array)   # 不变（file_parser 冻结）
     full_text += self._assemble_card(message_array)            # 不变
```

## 3. 行为等价红线确认
- `_describe_images`：迁移后 `[i for i in event.images if i.startswith("http")]`——与旧（只 data.url）**等价**（file 路径图仍不描述）
- `_scan_reply_and_at`：parser 与该方法**同规则实现**（已由 tests/test_adapters 快照断言）→ 直取安全
- clean_text：parser.text（at/text 段拼合 strip）与 extract_mention_and_text **同规则**（快照断言）
- forward/card：零改动（file_parser 冻结）

## 4. 不改清单（冻结）
- file_parser（冻结执行）｜pending_file（global_state，领域）｜_archive（领域）｜sanitize（领域）
