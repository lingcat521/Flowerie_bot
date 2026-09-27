"""回复解析（从 AIClient 拆出）：多消息结构提取 + 记忆指令剥离 + 长度截断。

从 ai_client.py 原样搬出（那个文件有 430 行硬上限，且「解析回复」与「发一次 HTTP
请求」本就是两件事）。纯函数：只读传入的 config，不持有 client / 记忆 / 连接，
因此可以独立测试。
"""
import json
from typing import Any, List, Optional, Tuple

from src.utils.logging_setup import get_logger

logger = get_logger(__name__)


def extract_multi_messages(text: str) -> Optional[List[str]]:
    """从模型输出提取「多条消息」结构；不合法一律 None（调用方降级单条）。

    只认完整 JSON 对象（形如 {"messages": [...]}，允许外层带 json 代码围栏），
    不做换行/标点猜测 —— 任务书 §6 明确要求。
    """
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith('```'):
        first_nl = raw.find(chr(10))
        last_fence = raw.rfind('```')
        if first_nl > 0 and last_fence > first_nl:
            raw = raw[first_nl + 1:last_fence].strip()
    if not raw.startswith("{"):
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    msgs = data.get("messages")
    if not isinstance(msgs, list):
        return None
    out = [str(m).strip() for m in msgs if str(m).strip()]
    return out or None

def parse_reply_content(content: str, config) -> Tuple[Optional[Any], Optional[str]]:
    """解析模型回复：剥离记忆指令，返回 (reply_text, memory_update)。"""
    content = (content or "").strip()
    if not content:
        return None, None
    memory_update = None
    lines = content.split('\n')
    clean_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("MEMORY_JSON:"):
            try:
                json_body = stripped[len("MEMORY_JSON:"):].strip()
                parsed = json.loads(json_body)
                if isinstance(parsed, dict) and parsed.get("text"):
                    memory_update = str(parsed["text"]).strip()
            except (json.JSONDecodeError, TypeError):
                logger.warning("Memory JSON parse failed: %s", stripped[:80])
            continue
        if (stripped.startswith("【记忆】") or
                stripped.startswith("记忆:") or
                stripped.startswith("记忆：")):
            memory_update = stripped
            continue
        clean_lines.append(line)
    reply_content = "\n".join(clean_lines).strip()
    if getattr(config, "MULTI_REPLY_ENABLED", False):
        multi = extract_multi_messages(reply_content)
        if multi:
            limit = int(getattr(config, "MAX_REPLY_LENGTH", 40) or 40)
            capped = [m if len(m) <= limit else m[:limit] + "..." for m in multi]
            logger.debug("multi_reply_detected count=%d", len(capped))
            return capped, memory_update
    if len(reply_content) > config.MAX_REPLY_LENGTH:
        reply_content = reply_content[:config.MAX_REPLY_LENGTH] + "..."
    logger.debug("api_reply len=%d", len(reply_content))
    if memory_update:
        logger.debug("memory_update_detected len=%d", len(memory_update))
    return reply_content, memory_update
