"""名字唤起检测（不带 @ 的点名）：消息文本含 BOT_NICKNAME（环境变量/配置）→ 必回。

语义：只与 BOT_NICKNAME 绑定——改这个变量，叫这个名字即 100% 回复；
群特色昵称（Group Nickname）是展示/描述用，不参与唤起（避免它误触发）。
"""
from typing import Any


def detect(msg: Any, config: Any, store: Any = None) -> bool:
    """msg: GroupMessage；config: Settings（读 BOT_NICKNAME）。store 保留兼容签名（不再使用）。"""
    try:
        text = str(getattr(msg, "clean_text", "") or "") or \
               str(getattr(msg, "full_text", "") or "") or \
               str(getattr(msg, "raw_message", "") or "")
        if not text:
            return False
        name = str(getattr(config, "BOT_NICKNAME", "花璃")).strip() or "花璃"
        return name in text
    except Exception:  # noqa: BLE001
        return False
