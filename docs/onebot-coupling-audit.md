# OneBot 耦合点审计报告（Phase 1）

> 依据 /storage/emulated/0/解耦.txt「第一阶段」要求：只审计、不改代码。
> 结论先行：**无 P0 级深耦合**；主流程有一处 P1 入口解析与一个 P1 业务消息模型；
> 其余为 P2/P3。此前 SDK 轮次已将插件通道与中层完全领域化，本次审计是主流程剩余面。

## 0. 审计方法与范围

- 源码树：`src/core`（19 文件）/ `src/services`（28）/ `src/repositories`（8）/ `src/plugins`（9）/ `src/sdk`（含 onebot 适配层）/ `main.py`
- 扫描：OneBot 特有字段 `post_type / sub_type / message_type / raw_message / self_id / sender / HTTP_API_BASE / onebot|OneBot / CQ:`（精确匹配，排除 `src/sdk/`（边界内）与注释）
- 区分：`user_id / group_id / message_id / time / text` 为**业务通用语义**（记忆/人格/AI 大量使用，不构成 OneBot 耦合）
- Python 3.9 兼容（pyproject requires-python >= 3.9）；冻结区模块零修改

## 1. OneBot 入口（WS / 解析 / Event / 字段访问）

| # | 文件:行 | 内容 | 等级 |
| --- | --- | --- | --- |
| 1 | `src/core/websocket_server.py:178-182` | `data.get("post_type")` **仅用于日志与指标 label**（`_M_RECEIVED.inc({"post_type": ...})`）；事件数据透传 router | P3 |
| 2 | `src/core/napcat_forward_client.py:164-168` | 同上（正向 WS 客户端，日志/指标 label） | P3 |
| 3 | `src/core/message_router.py:167-180` | **主流程入口分派**：`post_type == "message" / "notice"` 分支 + `sub_type == "poke"` 识别 | P1 |
| 4 | `src/core/message_router.py:235` | **主流程群/私聊判定**：`data.get("message_type") != "group"` → 直接 return | P1 |
| 5 | `src/core/message_router.py:204` | `_plugin_payload` 兜底分支回退 `post_type`（正常路径已领域化，仅异常兜底） | P2 |
| 6 | `src/core/message_assembler.py:71-99` | **OneBot 段数组解析**：`seg.get("type") == "image"/"reply"/"at"` + `seg.get("data").get("qq")` | P2 |
| 7 | `src/services/file_parser.py:396-402` | `bot_qq`（自 ID 对比，参数化字段，非 raw） | P3 |

## 2. OneBot 出口（Sender / HTTP API）

| # | 文件:行 | 内容 | 等级 |
| --- | --- | --- | --- |
| 8 | `src/services/sender.py`（全文件，32 处） | 全部 OneBot HTTP 端点（`/send_*` `/set_*` `/get_*` + `HTTP_API_BASE` + token）。**本就是出口边界**；`send_msg_raw` 返回值已业务化（`{ok, message_id}`） | P2 |
| 9 | `src/services/sender.py` get_* 系列 | `get_msg/get_group_*_info` 等**直接透传 OneBot 响应 dict**（`{ok, data}` 形态）——业务消费其 data 结构 | P2 |
| 10 | `src/config.py:60` / `src/services/config_schema.py:34` | `HTTP_API_BASE` 挂载在全局 Settings（适配器连接参数） | P3 |

## 3. 核心业务污染情况（好消息）

精确扫描（post_type/sub_type/message_type/self_id/raw_message/CQ）**零命中**：

- `context_manager` / `cooldown_manager` / `policy_engine` / `budget_manager` / `command_handler`（其 57 处计数全部为 `group_id/user_id` 业务字段）
- `memory_manager` / `meme_knowledge_manager` / `persona_manager` / `prompt_manager` / `prompt_builder` / `ai_gateway` / `ai_client` / `active_chat_manager` / `repeat_detector` / `toxic_detector` / `sticker_manager` / `vision` / `mcp_client` / `mcp_tool_manager` / `shutdown`
- `repositories/*`（数据库层，只有业务列）

**即：人格/记忆/AI/MCP/知识库/Session/限流/熔断/权限（插件侧+主进程侧）均不读取 OneBot JSON。** 冻结合规。

## 4. 核心业务消息模型（唯一 P1 数据载体）

`src/models.py:68-77` `GroupMessage`：

```python
@dataclass
class GroupMessage:
    group_id: int
    user_id: int
    message_id: int
    raw_message: str          # 原始文本（CQ 或纯文本）
    message_array: List[Dict[str, Any]]   # ★ OneBot 段数组（image/reply/at/json/forward 结构）
    time: int
    clean_text / full_text / is_mentioned / is_reply_to_bot / ...
```

- 消费方：message_router（构造）→ context_manager / memory / AI / poke / repeat / active_chat / meme_summary / file_parser
- **耦合点**：`message_array` 是 OneBot 段结构；业务借 `message_array` 拿图片/at/引用等信息（image 提取在 assembler）
- 等级：**P1**（核心数据流载体，但改造需全链路验证——`message_array` 的消费点均为"取图/取 at/取引用"，可收敛到 `images/at_list/reply_id` 结构化字段）

## 5. 严重程度汇总

| 等级 | 数量 | 内容 |
| --- | --- | --- |
| P0 极高 | 0 | — |
| P1 高 | 2 | #3/#4（router 入口分派与范围判定）；#GroupMessage.message_array（数据载体） |
| P2 中 | 3 | #5 兜底、#6 assembler 段解析、#8/#9 sender 出口契约 |
| P3 低 | 3 | #1/#2 WS 日志 label、#7 file_parser、#10 config 参数 |

## 6. 建议的隔离方向（Phase 2 设计输入，本轮不实施）

1. **InternalEvent**（按实际业务需求，不复制 OneBot）：
   字段建议（均有现成消费方）：`event_id / scope_type(group|private) / group_id / actor_id / message_id / text / mentions(at_list) / images / reply_id / timestamp / sender_summary(user_id, card, nickname?)` + `raw_data`（隔离保留，禁止外部读取）。Poke/转发/卡片：`notice_kind / extra`。
   废弃字段：`post_type/sub_type/message_type` → `kind/scope`。
2. **EventParser Protocol**：`parse(raw: dict) -> InternalEvent`；OneBot 实现复用 `src/sdk/onebot/transformer` 的模式（机械转换），核心 `parse` 逻辑下沉到 `src/sdk/onebot/`（已有 to_bot_event 可扩展，但**新增 InternalEvent 与现有 BotEvent 的关系**须 Phase 2 设计确认——是否以 BotEvent 演进为 InternalEvent，避免两套事件）。
3. **MessageSender Protocol**：基于现有 Sender 的真实签名抽象（`send_group/text+段`、`reply`、`recall`、`get`、`context`）；**不**预设计成 `send(group_id, content: dict)`；返回值统一业务 dict。
4. **迁移路径**（Phase 3+ 顺序）：
   - Phase 3：新增 Facade（`src/adapters/onebot/`？与 `src/sdk/onebot/` 合并）包装现有 sender + EventParser——**不移动旧文件**；
   - Phase 4：main.py 注入（运行时仍用原 OneBot）；
   - Phase 5：router `process_event` 改从 parser 拿 event（只替换 3-4 处字段访问，≤50 行）；
   - Phase 6：GroupMessage.message_array → 结构化字段（image/at/reply 收敛；assembler 只产结构化元组）；保留 raw_message；
   - Phase 7/8：最终扫描 + 验收。
5. **风险提示**：GroupMessage 消费方 >10 处（context/AI/记忆链），message_array 迁移需逐点验证；若出现风险，按停止条件回退为 Compatibility Adapter（消息数组保留为 `raw_message_array` 字段，业务渐进消费结构化字段）。

## 7. 测试与验证基线

- 现有测试（本地可跑 152 + CI 全量 300+）在 Phase 1 **零改动**；ruff 0；
- 每 Phase 完成：`pytest` + `ruff check .` + 启动冒烟 + git diff 控制（现有文件 >50 行修改须先说明）。
