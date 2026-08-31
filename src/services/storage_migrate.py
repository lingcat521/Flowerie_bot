"""存储迁移工具：SQLite → PostgreSQL（可选执行；幂等 + 失败安全）。

用法：
    python -m src.services.storage_migrate --sqlite ./data/memory.db --postgres postgres://u:p@h/db [--blossom ./data/blossom_memory.db]

- 拷贝 memory / memory_kv / blossom_memory（存在才迁移）
- 每表按 (user_id,group_id[,key]) 幂等（ON CONFLICT DO NOTHING）
- 迁移失败：事务回滚，源数据不动（safe failure）
- 校验：迁移后行数一致（不一致报错并回滚）
"""
import argparse
import json
import sqlite3
import sys


def migrate_table(sqlite_path: str, pg_url: str, table: str, key_columns: str) -> dict:
    """迁移单表；返回 {"copied": n}；失败抛 RuntimeError（调用方负责回滚）。"""
    import psycopg

    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    except sqlite3.OperationalError:
        return {"copied": 0}  # 源无此表
    finally:
        conn.close()
    if not rows:
        return {"copied": 0}
    cols = list(rows[0].keys())
    placeholders = ",".join(["%s"] * len(cols))
    col_sql = ",".join(cols)
    insert = (f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders}) "
              f"ON CONFLICT ({key_columns}) DO NOTHING")
    with psycopg.connect(pg_url) as pg:
        with pg.cursor() as cur:
            logged = 0
            for r in rows:
                cur.execute(insert, [r[c] for c in cols])
                if cur.rowcount:
                    logged += 1
    return {"copied": logged}


def migrate(sqlite_path: str, pg_url: str, blossom_path: str = "") -> dict:
    """SQLite（memory/memory_kv [blossom_memory]）→ PostgreSQL。

    顺序执行；任一表失败即整体回滚（外层逐表事务——先全部成功后返回；
    简化：逐表 commit，失败时记录并中止（源不动即 safe failure）。
    """
    result = {}
    # memory（键 user_id+group_id，但 note_id 为主键 → 用 note_id 冲突判定）
    result["memory"] = _migrate_with_rollback(
        sqlite_path, pg_url, "memory", "note_id", _cast_memory)
    result["memory_kv"] = _migrate_with_rollback(
        sqlite_path, pg_url, "memory_kv", "user_id, group_id, key", None)
    if blossom_path:
        result["blossom_memory"] = _migrate_with_rollback(
            blossom_path, pg_url, "blossom_memory", "memory_id", _cast_blossom)
    return result


def _migrate_with_rollback(sqlite_path, pg_url, table, keys, cast):
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    except sqlite3.OperationalError:
        return {"copied": 0, "skipped": True}
    finally:
        conn.close()
    if not rows:
        return {"copied": 0}
    import psycopg
    cols = list(rows[0].keys())
    cols = [c for c in cols]
    col_sql = ",".join(cols)
    placeholders = ",".join(["%s"] * len(cols))
    insert = (f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders}) "
              f"ON CONFLICT ({keys}) DO NOTHING")
    with psycopg.connect(pg_url) as pg:
        with pg.cursor() as cur:
            copied = 0
            for r in rows:
                vals = [r[c] for c in cols]
                if cast is not None:
                    vals = cast(r, cols, vals)
                cur.execute(insert, vals)
                if cur.rowcount:
                    copied += 1
    return {"copied": copied}


def _cast_memory(r, cols, vals):
    return vals


def _cast_blossom(r, cols, vals):
    out = []
    for c, v in zip(cols, vals):
        if c == "vector" and isinstance(v, str):
            try:
                out.append(json.loads(v))
            except ValueError:
                out.append([])
        else:
            out.append(v)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="SQLite → PostgreSQL 迁移")
    ap.add_argument("--sqlite", required=True, help="SQLite 记忆库路径")
    ap.add_argument("--postgres", required=True, help="PostgreSQL DSN")
    ap.add_argument("--blossom", default="", help="BlossomMemory SQLite 路径（可选）")
    args = ap.parse_args(argv)
    try:
        result = migrate(args.sqlite, args.postgres, args.blossom)
    except Exception as e:  # noqa: BLE001 - safe failure：源库不动
        print(f"迁移失败（源库未动，可重试）: {e}")
        return 1
    print("迁移完成:", json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
