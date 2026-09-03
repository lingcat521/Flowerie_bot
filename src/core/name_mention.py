"""名字唤起检测（不带 @ 的点名）：消息文本含默认昵称或群特色昵称 → 必回。"""
from typing import Any, Optional, Set


def detect(msg: Any, config: Any, store: Optional[Any] = None) -> bool:
    """msg: GroupMessage；store: GroupNicknameStore（可 None）。"""
    try:
        text = str(getattr(msg, "clean_text", "") or "") or \
               str(getattr(msg, "full_text", "") or "") or \
               str(getattr(msg, "raw_message", "") or "")
        if not text:
            return False
        names: Set[str] = {str(getattr(config, "BOT_NICKNAME", "花璃")).strip() or "花璃"}
        if store is not None:
            try:
                names.add(store.get(msg.group_id))
            except Exception:  # noqa: BLE001
                pass
        return any(n and n in text for n in names)
    except Exception:  # noqa: BLE001
        return False
