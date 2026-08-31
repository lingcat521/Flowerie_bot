"""BlossomMemory PostgreSQL 存储后端（可选；默认 SQLite）。

与 PostgresMemoryRepository 相同约束：STORAGE_BACKEND=postgres 时启用，
psycopg 软依赖；向量统一走"存储 + 内存 cosine"策略（pgvector 列可选，未来）。
"""
import json
import time
from typing import Any, List

from src.repositories.blossom_memory_repository import (
    BlossomMemoryRecord,
    BlossomMemoryRepository,
)


class PostgresBlossomMemoryRepository(BlossomMemoryRepository):
    def __init__(self, database_url: str):
        try:
            import psycopg  # noqa: F401
            import psycopg_pool
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "STORAGE_BACKEND=postgres 需要安装 psycopg 与 psycopg-pool") from e
        self._pool = psycopg_pool.ConnectionPool(
            database_url, min_size=1, max_size=2, open=False,
            kwargs={"autocommit": True})
        self._pool.open(wait=True, timeout=10)
        self._init_schema()

    def _conn(self):
        return self._pool.connection()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS blossom_memory (
                        memory_id BIGSERIAL PRIMARY KEY,
                        group_id BIGINT NOT NULL,
                        kind TEXT NOT NULL DEFAULT 'group',
                        target_id BIGINT NOT NULL DEFAULT 0,
                        text TEXT NOT NULL,
                        vector JSONB DEFAULT '[]',
                        source_message_id BIGINT,
                        created_at DOUBLE PRECISION NOT NULL DEFAULT 0,
                        last_used_at DOUBLE PRECISION NOT NULL DEFAULT 0,
                        used_count BIGINT NOT NULL DEFAULT 0
                    )""")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_pg_blossom_ugk "
                            "ON blossom_memory(group_id, kind, target_id)")
            conn.commit()

    def add(self, rec: BlossomMemoryRecord) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO blossom_memory (group_id, kind, target_id, text, vector, "
                    "source_message_id, created_at, last_used_at, used_count) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING memory_id",
                    (rec.group_id, rec.kind, rec.target_id, rec.text,
                     json.dumps(rec.vector or []), rec.source_message_id,
                     rec.created_at, rec.last_used_at, rec.used_count))
                mid = int(cur.fetchone()[0])
            conn.commit()
            return mid

    def list_by_group(self, group_id: int, kind: str = "group") -> List[dict]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM blossom_memory WHERE group_id=%s AND kind=%s "
                    "ORDER BY created_at DESC", (group_id, kind))
                return [self._row(r) for r in cur.fetchall()]

    def touch(self, memory_id: int) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE blossom_memory SET last_used_at=%s, used_count=used_count+1 "
                    "WHERE memory_id=%s", (time.time(), memory_id))
            conn.commit()

    def delete_missing_before(self, group_id: int, keep_count: int, ttl_ts: float) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM blossom_memory WHERE group_id=%s AND created_at<%s",
                            (group_id, ttl_ts))
                cur.execute("SELECT COUNT(*) FROM blossom_memory WHERE group_id=%s", (group_id,))
                total = int(cur.fetchone()[0])
                if total > keep_count:
                    cur.execute(
                        "DELETE FROM blossom_memory WHERE group_id=%s AND memory_id IN ("
                        "SELECT memory_id FROM blossom_memory WHERE group_id=%s "
                        "ORDER BY created_at ASC LIMIT %s)",
                        (group_id, group_id, total - keep_count))
                cur.execute("SELECT COUNT(*) FROM blossom_memory WHERE group_id=%s", (group_id,))
                n = int(cur.fetchone()[0])
                # 兼容：无 RETURNING 时用 count 差集校验（总行数 = 删除后行数）
            conn.commit()
            return n

    def count(self, group_id: int) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM blossom_memory WHERE group_id=%s", (group_id,))
                return int(cur.fetchone()[0])

    def recent(self, group_id: int, limit: int) -> List[dict]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM blossom_memory WHERE group_id=%s "
                    "ORDER BY created_at DESC LIMIT %s", (group_id, limit))
                return [self._row(r) for r in cur.fetchall()]

    def close(self) -> None:
        self._pool.close()

    @staticmethod
    def _row(r: Any) -> dict:
        cols = ("memory_id", "group_id", "kind", "target_id", "text", "vector",
                "source_message_id", "created_at", "last_used_at", "used_count")
        d = dict(zip(cols, r))
        vec = d.get("vector")
        if isinstance(vec, str):
            try:
                d["vector"] = json.loads(vec)
            except ValueError:
                d["vector"] = []
        elif not isinstance(vec, list):
            d["vector"] = []
        return d
