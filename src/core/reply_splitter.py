"""长文本边界感知切分（Layer A）：替代「超过 MAX_REPLY_LENGTH 就截断 + ...」。

对齐 dsh-qq-bridge 的 splitText：按「换行 → 句尾标点 → 逗号 → 空格 → 硬切」优先级
在 limit 内寻找最近切点，保证段长 <= limit 且尽量不切断语义单元。
Flowerie 人设「用空格代替逗号、不用句号问号感叹号」，因此空格是主要可用边界之一。

核心层、协议无关、纯函数：只依赖文本与上限，不读配置副作用。
"""
import re
from typing import List


class SplitSegments(list):
    """标记类：来自「边界切分 / 流式分句」的段列表（v2.6.0 Layer A/B）。

    用来与 AI 自主多条（MULTI_REPLY 的 messages[]）区分来源，plan_from_config
    据此施加各自的上限与发送策略（v2.7.0 C3：切分段不再接管 AI 多条的 clamped；
    C1：整轮分段记一次连续回复；C5：零段间隔）。
    是 list 子类：所有 isinstance(reply, list) 的既有消费者无需改动。
    """

# 句尾标点（强边界）：句号/问号/感叹号（中英全角）+ 分号
_SENTENCE_PUNCT = "。！？!?；;"
# 弱边界：逗号（中英）与顿号
_COMMA_PUNCT = "，,、"
# 切点保护：切点之后至少保留这么多字符，避免切出「一句话 + 一个标点」式碎片段
_MIN_TAIL = 2

_TRAILING_PUNCT = re.compile(r"[\s。！？!?；;，,、…~～]+$")


def split_by_boundary(text: str, limit: int) -> List[str]:
    """把 text 切成若干段，每段长度 <= limit。

    切点优先级（在 limit 范围内从右往左找最近者）：
    1. 换行（段落边界，最优先）
    2. 句尾标点（。！？!?；;）
    3. 逗号（，,、）
    4. 空格（人设下的主要边界）
    5. 都没有 → 硬切（保证不超 limit）

    段首段尾空白被去掉，空段被丢弃。limit<=0 时按「不切」处理（调用方自证）。
    """
    if limit <= 0:
        return [text] if text else []
    text = text or ""
    if len(text) <= limit:
        return [text] if text.strip() else []

    parts: List[str] = []
    rest = text
    while len(rest) > limit:
        cut = _find_cut(rest, limit)
        parts.append(rest[:cut].strip())
        rest = _TRAILING_PUNCT.sub("", rest[cut:]) if cut < len(rest) else ""
    if rest.strip():
        parts.append(rest.strip())
    return [p for p in parts if p]


def _find_cut(rest: str, limit: int) -> int:
    """在 rest 的 [limit*0.4, limit] 区间内找最佳切点；返回切点下标（切点字符含在前段）。"""
    lo = max(1, int(limit * 0.4))
    hi = min(limit, len(rest))
    for chars in ("\n", _SENTENCE_PUNCT, _COMMA_PUNCT, " "):
        idx = _last_index_of_any(rest, chars, lo, hi)
        if idx > 0 and (len(rest) - idx >= _MIN_TAIL or chars == "\n"):
            return idx + 1
    return hi  # 无候选 → 硬切


def _last_index_of_any(text: str, chars: str, lo: int, hi: int) -> int:
    """在 text[lo:hi] 范围内找任一 chars 字符的最后出现位置（-1 表示未找到）。"""
    best = -1
    for ch in chars:
        idx = text.rfind(ch, lo, hi)
        if idx > best:
            best = idx
    return best



def needs_split(text: str, limit: int) -> bool:
    """是否需要切分（供调用方决定走旧截断还是新切分）。"""
    return bool(text) and len(text) > limit

