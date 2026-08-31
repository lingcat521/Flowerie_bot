"""PostgreSQL 后端（可选；默认仍为 SQLite）。

- 通过 STORAGE_BACKEND=postgres + DATABASE_URL 启用（配置见 config.py）
- 依赖 psycopg>=3：import 时软加载（未安装/未启用时不会触发）
- 语义与 SQLiteMemoryRepository 完全一致（同一 MemoryRepository 接口）
- 向量列说明：BlossomMemory 的向量统一走"存储 + 内存 cosine"策略（与后端无关）；
  pgvector 列为未来可选优化（见 docs/technical-storage.md）
"""
from typing import Any, List, Optional, Tuple

from src.repositories.base import MemoryNote, MemoryRepository


class PostgresMemoryRepository(MemoryRepository):
    """memory/memory_kv 的 PG 实现（接口平行；业务零改动）。"""

    def __init__(self, database_url: str, pool_size: int = 4):
        try:
            import psycopg  # noqa: F401
            import psycopg_pool
        except ImportError as e:  # pragma: no cover - 依赖缺失提示
            raise RuntimeError(
                "STORAGE_BACKEND=postgres 需要安装 psycopg 与 psycopg-pool "
                "（pip install psycopg psycopg_pool）") from e
        self.url = database_url
        self._pool = psycopg_pool.ConnectionPool(
            database_url, min_size=1, max_size=pool_size, open=False,
            kwargs={"autocommit": True})
        self._pool.open(wait=True, timeout=10)
        self._init_schema()

    def _conn(self):
        return self._pool.connection()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS memory (
                        user_id BIGINT NOT NULL,
                        group_id BIGINT NOT NULL,
                        note_id BIGSERIAL PRIMARY KEY,
                        text TEXT NOT NULL,
                        source_user BIGINT,
                        source_group BIGINT,
                        source_message_id BIGINT,
                        created_at DOUBLE PRECISION,
                        confidence TEXT NOT NULL DEFAULT 'model'
                    )""")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_pg_memory_ug ON memory(user_id, group_id)")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS memory_kv (
                        user_id BIGINT NOT NULL,
                        group_id BIGINT NOT NULL,
                        key TEXT NOT NULL,
                        value TEXT,
                        PRIMARY KEY (user_id, group_id, key)
                    )""")
            conn.commit()

    # ---------- 读 ----------
    def list_notes(self, user_id: int, group_id: int, limit: Optional[int] = None) -> List[MemoryNote]:
        sql = "SELECT * FROM memory WHERE user_id=%s AND group_id=%s ORDER BY created_at DESC"
        params: list = [user_id, group_id]
        if limit:
            sql += " LIMIT %s"
            params.append(limit)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [self._row(r) for r in cur.fetchall()]

    def search_notes(self, user_id: int, group_id: int, keyword: str) -> List[MemoryNote]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM memory WHERE user_id=%s AND group_id=%s AND text LIKE %s "
                    "ORDER BY created_at DESC",
                    (user_id, group_id, f"%{keyword}%"))
                return [self._row(r) for r in cur.fetchall()]

    def list_all_notes(self) -> List[MemoryNote]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM memory ORDER BY created_at DESC")
                return [self._row(r) for r in cur.fetchall()]

    def iter_user_groups(self) -> List[Tuple[int, int]]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT user_id, group_id FROM memory")
                return [(int(r[0]), int(r[1])) for r in cur.fetchall()]

    # ---------- 写 ----------
    def insert_note(self, note: MemoryNote) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO memory (user_id, group_id, text, source_user, source_group, "
                    "source_message_id, created_at, confidence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                    "RETURNING note_id",
                    (note.user_id, note.group_id, note.text, note.source_user, note.source_group,
                     note.source_message_id, note.created_at, note.confidence))
                note_id = int(cur.fetchone()[0])
            conn.commit()
            return note_id

    def delete_note(self, note_id: int) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM memory WHERE note_id=%s", (note_id,))
            conn.commit()

    def delete_user_notes(self, user_id: int, group_id: int) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM memory WHERE user_id=%s AND group_id=%s RETURNING note_id",
                            (user_id, group_id))
                deleted = len(cur.fetchall())
            conn.commit()
            return deleted

    def count_notes(self, user_id: int, group_id: int) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM memory WHERE user_id=%s AND group_id=%s",
                            (user_id, group_id))
                return int(cur.fetchone()[0])

    def trim_notes(self, user_id: int, group_id: int, keep: int) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM memory WHERE user_id=%s AND group_id=%s AND note_id IN ("
                    "SELECT note_id FROM memory WHERE user_id=%s AND group_id=%s "
                    "ORDER BY created_at DESC OFFSET %s) RETURNING note_id",
                    (user_id, group_id, user_id, group_id, keep))
                deleted = len(cur.fetchall())
            conn.commit()
            return deleted

    def kv_set(self, user_id: int, group_id: int, key: str, value: str) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO memory_kv (user_id, group_id, key, value) VALUES (%s,%s,%s,%s) "
                    "ON CONFLICT (user_id, group_id, key) DO UPDATE SET value=EXCLUDED.value",
                    (user_id, group_id, key, value))
            conn.commit()

    def kv_list(self, user_id: int, group_id: int) -> List[Tuple[str, str]]:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT key, value FROM memory_kv WHERE user_id=%s AND group_id=%s",
                            (user_id, group_id))
                return [(r[0], r[1]) for r in cur.fetchall()]

    def commit(self) -> None:
        pass  # 每语句自动提交（与 SQLite 实现的事务语义对齐）

    def close(self) -> None:
        self._pool.close()

    @staticmethod
    def _row(r: Any) -> MemoryNote:
        d = dict(zip(("user_id", "group_id", "note_id", "text", "source_user",
                      "source_group", "source_message_id", "created_at", "confidence"),
                     r))
        return MemoryNote(
            text=d["text"], user_id=int(d["user_id"]), group_id=int(d["group_id"]),
            note_id=int(d["note_id"]), source_user=d["source_user"],
            source_group=d["source_group"], source_message_id=d["source_message_id"],
            created_at=d["created_at"], confidence=d["confidence"])
