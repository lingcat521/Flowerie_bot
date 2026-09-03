"""名字唤起检测（不带 @ 的点名）→ 必回。

参与名字：BOT_NICKNAME（环境变量/配置）+ 群特色昵称（Group Nickname 配置）
——两个都触发 100% 回复（改 BOT_NICKNAME 即生效；群特色昵称亦可唤起）。
"""
from typing import Any


def detect(msg: Any, config: Any, store: Any = None) -> bool:
    """msg: GroupMessage；config: Settings（BOT_NICKNAME）；store: GroupNicknameStore（可 None）。"""
    try:
        text = str(getattr(msg, "clean_text", "") or "") or \
               str(getattr(msg, "full_text", "") or "") or \
               str(getattr(msg, "raw_message", "") or "")
        if not text:
            return False
        names = {str(getattr(config, "BOT_NICKNAME", "花璃")).strip() or "花璃"}
        if store is not None:
            try:
                # 该群全部有效昵称（人设维度 + 群级）都参与唤起
                for _pid, _name in store.entries_for(msg.group_id):
                    if _name:
                        names.add(_name)
            except Exception:  # noqa: BLE001
                pass
        return any(n and n in text for n in names)
    except Exception:  # noqa: BLE001
        return False
