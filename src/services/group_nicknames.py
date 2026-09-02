"""群特色昵称（Group Nickname）：每群可设专属称呼，全局默认 BOT_NICKNAME。

- 存储：{data}/nicknames.json（{str(group_id): nickname}），线程锁 + 原子写（tmp+replace）
- 语义：群有配置 → 覆盖默认；配置为空字符串 → 视为"恢复默认"（删除条目）
- 干净：任何按钮写入前清洗（≤20 字、trim、禁控制字符）；读取时再兜底清洗
"""
import json
import logging
import os
import re
import threading
from typing import Dict

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"[\x00-\x1f\x7f]")
_MAX_LEN = 20


def _clean(nickname: str) -> str:
    name = _NAME_RE.sub("", str(nickname or "")).strip()
    return name[:_MAX_LEN]


class GroupNicknameStore:
    """JSON 原子存储（轻量、单进程；写时加锁）。"""

    def __init__(self, path: str, default_nickname: str = "花璃"):
        self._path = path
        self._default = default_nickname or "花璃"
        self._lock = threading.Lock()
        self._data: Dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as f:  # noqa: PTH123
                raw = json.load(f)
        except (OSError, ValueError):
            raw = {}
        data: Dict[str, str] = {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                if isinstance(k, str) and k.isdigit() and isinstance(v, str):
                    clean = _clean(v)
                    if clean:
                        data[k] = clean
        self._data = data

    def _persist(self) -> None:
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:  # noqa: PTH123
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path)

    # ---------- 读写 ----------
    def get(self, group_id) -> str:
        """群特色昵称（无配置 → 全局默认）。"""
        key = str(int(group_id))
        with self._lock:
            name = self._data.get(key, "")
        return _clean(name) or self._default

    def set(self, group_id, nickname: str) -> str:
        """设置群昵称；空/纯空白 → 恢复默认。返回生效昵称。"""
        key = str(int(group_id))
        clean = _clean(nickname)
        with self._lock:
            if clean:
                self._data[key] = clean
            else:
                self._data.pop(key, None)
            self._persist()
        return clean or self._default

    def delete(self, group_id) -> None:
        self.set(group_id, "")

    def all(self) -> Dict[str, str]:
        """全部配置（面板展示）。"""
        with self._lock:
            return dict(self._data)

    def list_groups(self) -> list:
        """已配置群 id 列表（升序）。"""
        with self._lock:
            return sorted((int(k) for k in self._data), key=lambda x: x)

    @property
    def default(self) -> str:
        return self._default

    def set_default(self, default: str) -> None:
        """全局默认随 BOT_NICKNAME 热更新（已配置群不受影响）。"""
        self._default = _clean(default) or "花璃"
