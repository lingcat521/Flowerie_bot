"""群特色昵称（Group Nickname）× 人设隔离：每群可设专属称呼，且按人设维度隔离。

- 存储：{data}/nicknames.json（JSON dict），线程锁 + 原子写（tmp+replace）
- 键：无 persona → "gid"；有 persona → "gid:persona_id"（旧数据 "gid" 天然兼容）
- 解析链：persona 精确命中 → 群级（无 persona 条目）→ 全局默认 BOT_NICKNAME
- 干净：写入前清洗（≤20 字、trim、禁控制字符）；读取时再兜底清洗
- 空字符串 → 删除条目（恢复"无配置"状态，级联到下一层）
"""
import json
import logging
import os
import re
import threading
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"[\x00-\x1f\x7f]")
_MAX_LEN = 20


def _clean(nickname: str) -> str:
    name = _NAME_RE.sub("", str(nickname or "")).strip()
    return name[:_MAX_LEN]


def _key(group_id, persona_id: Optional[str]) -> str:
    gid = str(int(group_id))
    pid = str(persona_id or "").strip()
    return f"{gid}:{pid}" if pid else gid


class GroupNicknameStore:
    """JSON 原子存储（轻量、单进程；写时加锁）。键含 persona 维度。"""

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
                if isinstance(k, str) and isinstance(v, str):
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
    def get(self, group_id, persona_id: Optional[str] = None) -> str:
        """解析昵称：persona 命中 → 群级 → 默认。persona_id 空/None = 群级。"""
        gid = str(int(group_id))
        pid = str(persona_id or "").strip()
        with self._lock:
            # 1) persona 精确（若有 persona）
            name = self._data.get(f"{gid}:{pid}", "") if pid else ""
            # 2) 群级回退
            if not name:
                name = self._data.get(gid, "")
        return _clean(name) or self._default

    def set(self, group_id, persona_id: Optional[str], nickname: str) -> str:
        """设置 (群 × 人设) 昵称；空 → 删除该键（级联回退）。返回生效昵称。"""
        key = _key(group_id, persona_id)
        clean = _clean(nickname)
        with self._lock:
            if clean:
                self._data[key] = clean
            else:
                self._data.pop(key, None)
            self._persist()
        return clean or self._default

    def set_group(self, group_id, nickname: str) -> str:
        """群级（无 persona）昵称；兼容旧调用。"""
        return self.set(group_id, None, nickname)

    def delete(self, group_id, persona_id: Optional[str] = None) -> None:
        self.set(group_id, persona_id, "")

    def all(self) -> Dict[str, str]:
        """全部配置（键含 persona 维度；面板展示用）。"""
        with self._lock:
            return dict(self._data)

    def list_groups(self) -> list:
        """出现过配置的群号（唯一）。"""
        with self._lock:
            gids = set()
            for k in self._data:
                gids.add(int(k.split(":", 1)[0]))
            return sorted(gids)

    def entries_for(self, group_id) -> List[Tuple[Optional[str], str]]:
        """某群全部条目：[(persona_id or None, nickname)]（面板行）。"""
        gid = str(int(group_id))
        out: List[Tuple[Optional[str], str]] = []
        with self._lock:
            for k, v in self._data.items():
                if k == gid:
                    out.append((None, v))
                elif k.startswith(gid + ":"):
                    out.append((k.split(":", 1)[1], v))
        return out

    def set_default(self, nickname: str) -> str:
        """更新全局默认名（BOT_NICKNAME 热更新）。"""
        self._default = _clean(nickname) or self._default
        return self._default

    @property
    def default(self) -> str:
        return self._default
