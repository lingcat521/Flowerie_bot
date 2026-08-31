"""LivingMemory 存储仓库接口 + SQLite 实现（群隔离；默认存储后端）。

表：blossom_memory
  group_id      INTEger 群隔离边界（==0 表示全局，暂不启用）
  kind          'user' | 'group' | 'global'（语义层保留；当前实现 user/group）
  target_id     INTEGER（kind=user 时为 user_id；group 时为 0）
  text          TEXT 记忆原文
  vector        TEXT（JSON 数组浮点；SQLite 后端用内存 cosine 检索）
  source_message_id INTEger
  created_at / last_used_at REAL
  used_count    INTEger
"""
import json
import os
import sqlite3
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class BlossomMemoryRecord:
    memory_id: int
    group_id: int
    kind: str = "group"                  # user | group | global
    target_id: int = 0
    text: str = ""
    vector: List[float] = field(default_factory=list)
    created_at: float = 0.0
    last_used_at: float = 0.0
    used_count: int = 0
    source_message_id: Optional[int] = None


class BlossomMemoryRepository(ABC):
    """存储无关接口（业务不感知 SQL）。"""

    @abstractmethod
    def add(self, rec: BlossomMemoryRecord) -> int: ...

    @abstractmethod
    def list_by_group(self, group_id: int, kind: str = "group") -> List[dict]: ...

    @abstractmethod
    def touch(self, memory_id: int) -> None: ...

    @abstractmethod
    def delete_missing_before(self, group_id: int, keep_count: int, ttl_ts: float) -> int:
        """清理（返回删除数）：超 TTL 与超上限的最旧条目。"""

    @abstractmethod
    def count(self, group_id: int) -> int: ...

    @abstractmethod
    def recent(self, group_id: int, limit: int) -> List[dict]: ...

    @abstractmethod
    def close(self) -> None: ...


class SQLiteBlossomMemoryRepository(BlossomMemoryRepository):
    def __init__(self, db_path: str):
        dirname = os.path.dirname(db_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self._pragma()

    def _pragma(self) -> None:
        with self._lock:
            try:
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA busy_timeout=5000")
            except sqlite3.Error:
                pass

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS blossom_memory (
                memory_id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                kind TEXT NOT NULL DEFAULT 'group',
                target_id INTEGER NOT NULL DEFAULT 0,
                text TEXT NOT NULL,
                vector TEXT DEFAULT '[]',
                source_message_id INTEGER,
                created_at REAL NOT NULL DEFAULT 0,
                last_used_at REAL NOT NULL DEFAULT 0,
                used_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_living_ugk ON blossom_memory(group_id, kind, target_id);
            """)

    def add(self, rec: BlossomMemoryRecord) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO blossom_memory (group_id, kind, target_id, text, vector, "
                "source_message_id, created_at, last_used_at, used_count) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (rec.group_id, rec.kind, rec.target_id, rec.text,
                 json.dumps(rec.vector or []), rec.source_message_id,
                 rec.created_at or 0.0, rec.last_used_at or 0.0, rec.used_count or 0))
            self._conn.commit()
            return int(cur.lastrowid)

    def list_by_group(self, group_id: int, kind: str = "group") -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM blossom_memory WHERE group_id=? AND kind=? "
                "ORDER BY created_at DESC", (group_id, kind)).fetchall()
        return [self._row(r) for r in rows]

    def touch(self, memory_id: int) -> None:
        now = __import__("time").time()
        with self._lock:
            self._conn.execute(
                "UPDATE blossom_memory SET last_used_at=?, used_count=used_count+1 "
                "WHERE memory_id=?", (now, memory_id))
            self._conn.commit()

    def delete_missing_before(self, group_id: int, keep_count: int, ttl_ts: float) -> int:
        with self._lock:
            # 超 TTL
            self._conn.execute(
                "DELETE FROM blossom_memory WHERE group_id=? AND created_at<?",
                (group_id, ttl_ts))
            # 超上限（保留 keep_count 条最新）
            count = self._conn.execute(
                "SELECT COUNT(*) FROM blossom_memory WHERE group_id=?",
                (group_id,)).fetchone()[0]
            if count > keep_count:
                self._conn.execute(
                    "DELETE FROM blossom_memory WHERE group_id=? AND memory_id IN ("
                    "SELECT memory_id FROM blossom_memory WHERE group_id=? "
                    "ORDER BY created_at ASC LIMIT ?)",
                    (group_id, group_id, count - keep_count))
            total = self._conn.execute(
                "SELECT COUNT(*) FROM blossom_memory WHERE group_id=?",
                (group_id,)).fetchone()[0]
            self._conn.commit()
            return total

    def count(self, group_id: int) -> int:
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) FROM blossom_memory WHERE group_id=?",
                (group_id,)).fetchone()[0]

    def recent(self, group_id: int, limit: int) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM blossom_memory WHERE group_id=? ORDER BY created_at DESC LIMIT ?",
                (group_id, limit)).fetchall()
        return [self._row(r) for r in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _row(r) -> dict:
        d = dict(r)
        try:
            d["vector"] = json.loads(d.get("vector") or "[]")
        except (ValueError, TypeError):
            d["vector"] = []
        return d
