"""Native Reply Tool：AI 自主决定「是否拆成多条、每条说什么」（内部工具，协议无关）。

设计（对齐任务书 Phase 2-9 / 12 / 13）：
- 只**捕获**模型给出的 messages[]，绝不发送消息、绝不 import OneBot/Milky/NapCat；
- 捕获结果以 List[str] 形式回到既有回复链路（与旧式 JSON Multi-Reply 完全同型），
  于是 100% 复用 plan_from_config（开关门控 + clamped 上限）→ ReplySender → 协议适配；
- 工具仅在 MULTI_REPLY_ENABLED 时注入（不新增开关，Phase 12）；
- 每个 logical request 只认**第一次**成功捕获：模型重复调用不会重发第一条（Phase 8）。
"""
from typing import Any, Dict, List, Optional

REPLY_TOOL_NAME = "reply"

REPLY_TOOL_DESCRIPTION = (
    "发送本轮回复。可以发一条或多条独立消息，消息边界由你根据上下文自行决定。"
    "只有在拆开更符合自然聊天节奏时才传多条；一句完整自然的话就只传一条，"
    "不要为了用这个工具而强行拆分。条数上限、间隔与发送频率由系统控制，你无法通过本工具绕过。"
)

# OpenAI 风格 tool schema（与 MCP 工具 payload 同一形状）。
REPLY_TOOL_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": REPLY_TOOL_NAME,
        "description": REPLY_TOOL_DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "description": "要发送的独立消息列表；不需要拆分时只放一条。",
                    "items": {"type": "string"},
                    "minItems": 1,
                }
            },
            "required": ["messages"],
            "additionalProperties": False,
        },
    },
}

# 防元数据洪泛：超出部分直接丢弃；真正的上限仍由 Core 配置（MULTI_REPLY_MAX_MESSAGES）决定。
MAX_CAPTURE_MESSAGES = 20


def parse_reply_args(args: Any) -> Optional[List[str]]:
    """校验工具实参 → 消息列表；任何不合法一律 None（调用方按「未调用」处理）。"""
    if not isinstance(args, dict):
        return None
    msgs = args.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return None
    out: List[str] = []
    for m in msgs:
        if not isinstance(m, str):  # 非字符串（数字/对象）一律拒绝整次调用，不猜测
            return None
        text = m.strip()
        if text:
            out.append(text)
    if not out:
        return None
    return out[:MAX_CAPTURE_MESSAGES]


class ReplyToolCapture:
    """一次 logical request 的捕获器（幂等：只认第一次调用）。"""

    def __init__(self) -> None:
        self.messages: Optional[List[str]] = None
        self.calls = 0

    @property
    def captured(self) -> bool:
        return self.messages is not None

    def capture(self, args: Any) -> str:
        """执行一次 reply 调用：返回给模型的工具结果（短文本）。"""
        self.calls += 1
        msgs = parse_reply_args(args)
        if msgs is None:
            return "调用无效：messages 必须是非空字符串数组；本次未记录，请重新调用。"
        if self.captured:
            # Phase 8：已捕获就不再接受，避免重复发送第一条
            return "本轮回复已记录，请勿重复调用。"
        self.messages = msgs
        return "已记录本轮回复（%d 条），请勿重复调用。" % len(msgs)


def make_tool_caller(capture: ReplyToolCapture, fallback=None):
    """包装 caller：reply → 捕获；其余工具 → 原样委托（MCP）。

    fallback 为 None 时（未配置 MCP）：未知工具名返回明确错误，绝不静默失败。
    """

    async def _call(name: str, args: Any) -> str:
        if name == REPLY_TOOL_NAME:
            return capture.capture(args)
        if fallback is None:
            return "工具不可用：%s" % name
        return await fallback(name, args)

    return _call
