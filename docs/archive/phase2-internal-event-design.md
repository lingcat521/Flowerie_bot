# Phase 2 设计：InternalEvent / EventParser / MessageSender（只设计，不改业务代码）

> 依据：解耦.txt Phase 2 要求 + 实际源码审计（Phase 1 报告 + 本轮消费方逐点核实）。
> 方案基调：**新增抽象 + Compatibility Adapter 的渐进式路线**，不替换现有模型。

## 0. 源码事实（零点核实，决定设计）

| 事实 | 证据 | 含义 |
| --- | --- | --- |
| `GroupMessage.message_array` **仅解析期使用** | 全仓 `\.message_array` 属性访问 = 0；全部消费（assembler 4 私有方法 + file_parser extract_*）都发生在 router:309 构造 **之前** | 模型字段是"保留区"，对业务不构成运行时耦合——兼容策略可零成本 |
| `GroupMessage` 其余字段均为领域语义 | clean_text/full_text/is_mentioned/is_reply_to_bot/has_reply_to_other/has_at_others/time/group_id/user_id/message_id → context/AI/记忆消费方 | 无需改动模型字段 |
| sender 业务调用面 | command_handler 26（send_group_message 为主）/ sdk adapter 23 / manager 13 / router 7 / budget 1 | MessageSender 以现有签名声明（鸭子契约），零实现变更 |
| 主流程 OneBot 字段访问 | router:167(post_type 分支)/180(sub_type poke)/235(message_type)/254(data["message"]) + time/user_id/message_id/notice_type | 唯一需要"替换"的读取点（约 10 行） |
| plugin 通道已有领域事件 | `src/sdk/event.BotEvent`（kind/scope/text/at_list/images/reply_id/notice_kind 等，零 OneBot） | InternalEvent 与 BotEvent **同构**，推荐合并为单一事件模型 |

## 1. InternalEvent 字段设计（按真实消费方设计，不复制 OneBot）

```python
@dataclass
class InternalEvent:
    # 标识与审计
    event_id: str                 # f"{kind}:{group_id}:{actor_id}:{message_id}:{timestamp}" 或 trace_id
    kind: str                     # "message" | "notice" | "request" | "lifecycle"（替代 post_type）
    scope: str                    # "group" | "private" | ""（替代 message_type 判定）
    # 主体
    group_id: Optional[int]
    actor_id: Optional[int]       # 触发者（替代 user_id）
    message_id: Optional[int]
    timestamp: Optional[int]      # 替代 time
    # 内容（解析后结构化，替代段数组扫描）
    text: str                     # 纯文本（clean_text 同源）
    mentions: List[str]           # at 的 QQ（替代 segment["at"] 扫描）
    images: List[str]             # 图片 URL/path（替代 segment["image"] 扫描）
    reply_id: Optional[int]       # 引用消息（替代 segment["reply"] 扫描）
    notice_kind: str              # poke/group_increase/...（替代 sub_type+notice_type 组合）
    # 派生语义（现有消费方直接使用）
    is_mentioned: bool
    is_reply_to_bot: bool
    has_reply_to_other: bool
    has_at_others: bool
    # 高级段摘要（forward/card）——(kind, data) 对；data 为平台释义 dict（保留必要字段）
    segments_summary: List[Tuple[str, dict]] = field(default_factory=list)
    # 隔离保留（合规文档：仅 EventParser 内部可读取，业务禁止）
    raw_data: dict = field(default_factory=dict, repr=False)
```

**明确不包含**：`post_type/sub_type/message_type/self_id/raw_message`；**不再有**段数组裸结构（segments_summary 为语义化 (kind, data)）。

> 与 `BotEvent(src/sdk/event.py)` 的关系——推荐方案 A：
> - **方案 A（推荐）**：`InternalEvent = BotEvent 演进`——将 `src/sdk/event.py` 的 BotEvent 增补 `actor_id 别名/segments_summary/event_id` 后即为主进程通用事件；插件 SDK 与主流程**共享一套事件模型**（插件侧已零 OneBot，主流程复用，避免双模型漂移）。
> - 方案 B：另建 InternalEvent（字段 95% 重叠，后续合并成本高）。

## 2. EventParser Protocol

```python
class EventParser(Protocol):
    """OneBot raw dict → InternalEvent（机械转换，唯一读取 raw 的位置）。"""
    def parse(self, raw: dict) -> InternalEvent: ...
    def mentions_bot_qq(self, event: InternalEvent, bot_qq: str) -> bool:
        """bot 是否被 @（替代手写 min(sender)==BOT_QQ 判断）。"""
```

- **实现位置**：`src/adapters/onebot_parser.py`（**新建**；组合现有 `src/sdk/onebot/transformer` 的机械转换函数 + `src/services/file_parser` 的 mention 提取与 forward/card 摘要，**不改动二者**）
- **OneBot → InternalEvent 映射表**（现成转换全部已在 transformer，此处只做字段命名映射）

## 3. MessageSender Protocol（基于现有真实签名声明，零行为变更）

```python
class MessageSender(Protocol):
    # 已定义于 Sender 的方法，名称、签名完全一致（鸭子类型，Sender 隐式满足）
    async def send_group_message(self, group_id: int, message: str, ...): ...
    async def send_private_message(self, user_id: int, message: str): ...
    async def send_msg_raw(self, target: str, target_id: int, message, reply_id=None): ...
    async def delete_msg / get_msg / get_group_msg_history(...)
    async def get_group_member_info / get_group_member_list(...)
    async def set_group_ban / set_group_kick / set_group_admin / set_group_whole_ban /
        set_group_name / set_group_card / set_group_special_title(...)
    async def set_react / set_essence_msg / send_poke / set_friend_profile_like(
        ) / set_friend_add_request / set_group_add_request / set_qq_profile(...)
```

- 业务侧（command_handler 等）**不改调用**；仅在被注入处标注 `sender: MessageSender`（类型契约）
- 新增发送语义（图片/段/引用）维持 `send_msg_raw`（业务化 `{ok, message_id}` 返回）——**不**预设计 `send(group_id, content: dict)`

## 4. 兼容策略（旧模型不删）

1. `GroupMessage` 原样保留：`message_array` 字段改为内部注释标注「解析期使用；构造后无消费者」；`raw_message` 保留
2. `CompatibilityAdapter`（新文件 `src/adapters/compat.py`）：
   - `build_group_message(event: InternalEvent, raw: dict) -> GroupMessage`——Phase 5/6 期间 router 仍产 GroupMessage，但数据源改为 InternalEvent（**输出模型不变**，中断风险≈0）
   - 提供 `LegacyEventBridge`：任何依赖旧形态的调用方可包一层拿回 dict（理论上不需要——已核实无消费者）
3. 迁移顺序：**先加边界（Phase 3-4）→ 再改 router 读取点（Phase 5）→ 最后化简 assembler/模型（Phase 6）**；每步测试全绿再进下一步；Phase 6 后若风险出现，回退路径 = 保持 CompatibilityAdapter 常驻（GroupMessage 不删除）

## 5. 受影响文件清单与风险评级（Phase 3-6 预期）

| 文件 | 预期改动 | 风险 | 说明 |
| --- | --- | --- | --- |
| `src/adapters/__init__.py` / `proto.py`（新） | 新增（Protocol + InternalEvent） | 无 | 纯新增 |
| `src/adapters/onebot_parser.py`（新） | 新增（组合 transformer + file_parser extract_*） | 低 | 无 import 变更 |
| `src/adapters/compat.py`（新） | 新增（build_group_message） | 无 | 纯新增 |
| `src/core/message_router.py` | ~10-15 行（process_event 读取点替换） | **中** | ≤50 行红线内；替换时保持 GroupMessage 输出不变 |
| `src/core/message_assembler.py` | 内部 4 私有方法改消费 segments_summary（输入 event 而非 message_array） | **中** | 行为需等价（图片描述/转发/卡片/at/reply 输出同旧） |
| `src/services/file_parser.py` | 0 行（**保留原位**，由 parser 组合调用） | 无 | 冻结执行 |
| `src/core/command_handler.py` | 仅注入类型标注（可选）或 0 | 低 | 调用不变 |
| `src/services/sender.py` | 0（行为已满足 Protocol） | 无 | 冻结执行 |
| `src/core/napcat_forward_client.py` / `websocket_server.py` | 0（WS 层透传，仅日志） | 无 | 本轮不动 |
| `main.py` | Phase 4：构建 parser/sender 注入（运行时仍 OneBot） | 低 | 手工验证启动 |

**冻结区（零改动）**：persona / prompt / ai_client / ai_gateway / memory / meme_* / mcp_* / sticker / session / policy / cooldown / budget / repositories / plugins 全部。

## 6. 设计红线自查

- 不解耦字段：无 post_type/sub_type/message_type/self_id 进入业务（映射到 kind/scope/notice_kind/event_id）
- 不预造 Worker/哈希（无此需求）
- Python 3.9 兼容（不用 asyncio.timeout 等；Protocol 用 typing.Protocol）
- SSRF/权限/Token/沙盒：零改动，新增 parser 不引入任何新网络调用（forward 提取已有行为原样）
- 测试红线：Phase 3-6 结束后 `pytest` + `ruff`，断言不变

## 7. 停止条件预判

若 Phase 5/6 期间发现：assembler 行为等价性无法在单 Phase 内验证（图片描述/转发解析依赖网络 API 时序），或 300+ 测试中出现业务行为差异 → **立即停止**，退回 CompatibilityAdapter 常驻方案，报告耦合点与最小安全方案。
