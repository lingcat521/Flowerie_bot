"""名字唤起检测（不带 @ 的点名）→ 必回。

参与名字：BOT_NICKNAME（环境变量/配置）+ 群特色昵称（Group Nickname 配置）
——两个都触发 100% 回复（改 BOT_NICKNAME 即生效；群特色昵称亦可唤起）。
"""
from typing import Any
from unicodedata import normalize

_ADDRESS_FOLLOWERS = ("在吗", "在不在", "你好", "早安", "晚安", "帮", "请", "能不能", "可以", "给我",
                      "你在", "你能", "你觉得", "你知道", "你说", "你看", "怎么", "为什么", "要不要")
_ADDRESS_SEPARATORS = "，,。！？!?；;：:、"


def detect(msg: Any, config: Any, store: Any = None) -> bool:
    """msg: GroupMessage；config: Settings（BOT_NICKNAME）；store: GroupNicknameStore（可 None）。"""
    try:
        text = normalize("NFKC", msg.clean_text).strip().casefold()
        if not text:
            return False
        names = {str(getattr(config, "BOT_NICKNAME", "花璃")).strip() or "花璃"}
        if store is not None:
            try:
                if hasattr(store, "entries_for"):
                    for _pid, _name in store.entries_for(msg.group_id):
                        if _name:
                            names.add(_name)
                else:
                    names.add(store.get(msg.group_id))
            except Exception:  # noqa: BLE001
                pass
        for name in names:
            if not name:
                continue
            name = normalize("NFKC", name).strip().casefold()
            if not name or not text.startswith(name):
                continue
            tail = text[len(name):]
            if (not tail or tail[0].isspace() or tail[0] in _ADDRESS_SEPARATORS
                    or tail.startswith(_ADDRESS_FOLLOWERS)):
                return True
        return False
    except Exception:  # noqa: BLE001
        return False
