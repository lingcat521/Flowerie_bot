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

    def __init__(self, *args):
        super().__init__(*args)
        # 结构化控制指令：表情包文件名列表（由 extract_stickers 从文本剥离）
        self.stickers: List[str] = []


# 句尾标点（强边界）：句号/问号/感叹号（中英全角）+ 分号
_SENTENCE_PUNCT = "。！？!?；;"
# 弱边界：逗号（中英）与顿号
_COMMA_PUNCT = "，,、"
# 切点保护：切点之后至少保留这么多字符，避免切出「一句话 + 一个标点」式碎片段
_MIN_TAIL = 2

_TRAILING_PUNCT = re.compile(r"[\s。！？!?；;，,、…~～]+$")


def fragment_split(text: str) -> List[str]:
    """Split a short reply into fragments by spaces and punctuation.

    Only used when SPLIT_REPLY_ENABLED and the reply is under the lower threshold.
    Punctuation stays attached to the preceding fragment. Empty frags dropped.
    """
    if not text or not str(text).strip():
        return []
    parts = re.split(r"[ 	]+", str(text).strip())
    out: List[str] = []
    for part in parts:
        if not part:
            continue
        # further split after sentence-ending punctuation only: keep the punct with the preceding piece
        # 逗号/顿号/小数点不拆（它们是句内成分，拆了反而碎）
        pieces = re.split(r"(?<=[。！？!?；;])", part)
        out.extend(p for p in pieces if p)
    return out

# 控制标记：[STICKER:文件名] —— 不是聊天文本，属框架内部指令
_STICKER_TAG_RE = re.compile(r"\[STICKER:\s*([^\]]+?)\s*\]")


def extract_stickers(text):
    """把 [STICKER:文件名] 控制标记从文本中剥离。

    返回 (纯聊天文本, 表情包文件名列表)；标记绝不进入发给用户的文本。
    """
    raw = str(text or "")
    names = [m.strip() for m in _STICKER_TAG_RE.findall(raw) if m and m.strip()]
    clean = _STICKER_TAG_RE.sub("", raw)
    # 剥离标记后清理多余空白/空行（标记常独占一行）
    clean = re.sub(r"[ \t]+\n", "\n", clean)
    clean = re.sub(r"\n{2,}", "\n", clean).strip()
    return clean, names
