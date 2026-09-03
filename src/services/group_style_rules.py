"""群专属发言规则（Group Style Rule）：每群可覆盖全局 GLOBAL_STYLE_RULES。

- 存储：{data}/style_rules.json（{str(group_id): rules}），线程锁 + 原子写（tmp+replace）
- 语义：群有规则 → 注入时以群规则替换全局规则段；无 → 用全局规则
- 容错：非字符串/超长（>2000 字）丢弃；空字符串 = 删除（回退全局）
"""
import json
import logging
import os
import threading
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_MAX_LEN = 2000


class GroupStyleRuleStore:
    """JSON 原子存储（单进程；写时加锁）。"""

    def __init__(self, path: str):
        self._path = path
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
                    rule = v.strip()[: _MAX_LEN]
                    if rule:
                        data[k] = rule
        self._data = data

    def _persist(self) -> None:
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:  # noqa: PTH123
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path)

    def get(self, group_id) -> Optional[str]:
        """群专属发言规则；无 → None（回退全局）。"""
        gid = str(int(group_id))
        with self._lock:
            return self._data.get(gid)

    def set(self, group_id, rules: str) -> Optional[str]:
        """设置群规则；空/纯空白 → 删除（回退全局）。返回生效规则或 None。"""
        gid = str(int(group_id))
        clean = str(rules or "").strip()[: _MAX_LEN]
        with self._lock:
            if clean:
                self._data[gid] = clean
            else:
                self._data.pop(gid, None)
            self._persist()
        return clean or None

    def delete(self, group_id) -> None:
        self.set(group_id, "")

    def all(self) -> Dict[str, str]:
        with self._lock:
            return dict(self._data)
