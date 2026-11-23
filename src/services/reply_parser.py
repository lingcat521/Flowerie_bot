"""回复解析（从 AIClient 拆出）：多消息结构提取 + 记忆指令剥离 + 长度截断。

从 ai_client.py 原样搬出（那个文件有 430 行硬上限，且「解析回复」与「发一次 HTTP
请求」本就是两件事）。纯函数：只读传入的 config，不持有 client / 记忆 / 连接，
因此可以独立测试。
"""
import json
import re
from typing import Any, List, Optional, Tuple

from src.core.reply_splitter import SplitSegments, extract_stickers, fragment_split
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)
_MEMORY_MARKER = re.compile(r"MEMORY_JSON:|^[ \t]*(?:【记忆】|记忆[:：])", re.MULTILINE)
_JSON_DECODER = json.JSONDecoder()


def extract_multi_messages(text: str) -> Optional[List[str]]:
    """从模型输出提取「多条消息」结构；不合法一律 None（调用方降级单条）。

    只认完整 JSON 对象（形如 {"messages": [...]}，允许外层带 json 代码围栏）。
    换行/标点切分见 reply_splitter（v2.6.0 Layer A）；多条结构只认完整 JSON。
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

def _line_end(text: str, position: int) -> int:
    end = text.find("\n", position)
    return len(text) if end < 0 else end


def _invalid_json_end(text: str, start: int) -> int:
    """Skip a broken control object without showing its body in chat."""
    depth, quoted, escaped = 0, False, False
    for index in range(start, len(text)):
        char = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if not depth:
                return index + 1
    return len(text)


def split_memory_lines(text: str) -> Tuple[str, Optional[str]]:
    """剥离记忆指令和完整 JSON 对象，按原文顺序采用最后一条有效更新。"""
    text = text or ""
    clean, update, cursor, search = [], None, 0, 0
    while marker := _MEMORY_MARKER.search(text, search):
        start = marker.start()
        line_start = text.rfind("\n", 0, start) + 1
        standalone = not text[line_start:start].strip()
        end = _line_end(text, marker.end())
        if marker.group() == "MEMORY_JSON:":
            body = marker.end()
            while body < len(text) and text[body].isspace():
                body += 1
            if text[body:body + 1] == "{":
                try:
                    value, end = _JSON_DECODER.raw_decode(text, body)
                    claim = value.get("text") if isinstance(value, dict) else None
                    if isinstance(claim, str) and (claim := claim.strip()):
                        update = claim
                except (ValueError, RecursionError):
                    logger.warning("Memory JSON parse failed")
                    end = _invalid_json_end(text, body)
            elif not standalone:
                search = marker.end()
                continue
        else:
            update = text[start:end].strip()
        rest_of_line = _line_end(text, end)
        if standalone and not text[end:rest_of_line].strip():
            start, end = line_start, min(len(text), rest_of_line + 1)
        clean.append(text[cursor:start])
        cursor = search = end
    clean.append(text[cursor:])
    return "".join(clean).strip(), update


def parse_reply_content(content: str, config) -> Tuple[Optional[Any], Optional[str]]:
    """parse model reply: 剥离记忆行与控制标记，再按规则分句。

    控制标记（[STICKER:文件名]）**无条件**剥离：它属于框架内部指令，
    与 SPLIT_REPLY_ENABLED 无关——分句器关掉时也不能把标记发给用户。

    Split rules (only these; nothing else):
    - total length > SPLIT_REPLY_DISABLE_AT (100): send whole, no fragmentation
    - total length < SPLIT_REPLY_LOWER (40): fragment by spaces and punctuation
    - between: send whole
    """
    content = (content or "").strip()
    if not content:
        return None, None
    reply_content, memory_update = split_memory_lines(content)

    # 1) 控制标记剥离（与分句开关解耦，任何情况下都不外发）
    reply_content, sticker_names = extract_stickers(reply_content)
    if sticker_names and not getattr(config, "STICKER_MARKER_ENABLED", True):
        # 开关关闭：丢弃图片指令（标记已剥离，绝不泄漏给用户）
        sticker_names = []
    # 注意：空文本不在这里判 None（原语义：只有整条为空才返回 None，
    # 记忆行剥离后的空串仍返回 ''，避免把「只发记忆指令」误判成「没有回复」）

    # 2) 文本分句（可选的表达增强，与标记无关）
    frags = None
    if getattr(config, "SPLIT_REPLY_ENABLED", False):
        lower = int(getattr(config, "SPLIT_REPLY_LOWER", 40) or 40)
        n = len(reply_content)
        if n < lower:
            _f = fragment_split(reply_content)
            if len(_f) > 1:
                frags = _f
                logger.debug("fragment_reply count=%d", len(_f))
    if frags is None:
        # >=lower: keep the legacy cap (MAX_REPLY_LENGTH + ellipsis)
        max_len = int(getattr(config, "MAX_REPLY_LENGTH", 40) or 40)
        if len(reply_content) > max_len:
            reply_content = reply_content[:max_len] + "..."

    # 3) 有表情包指令时用 SplitSegments 承载（结构化，便于发送层单独发图）
    if sticker_names:
        segs = SplitSegments(frags if frags else ([reply_content] if reply_content.strip() else []))
        segs.stickers = sticker_names
        return segs, memory_update
    if frags:
        return SplitSegments(frags), memory_update
    return reply_content, memory_update
