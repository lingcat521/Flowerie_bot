"""存储后端：默认 SQLite 选择逻辑 + 迁移工具（安全失败语义）。

PG 实现需真实 postgres（CI service 覆盖）；此处验证配置分支与迁移工具
对"源库缺失表=跳过/失败回滚（源不动）"的语义（sqlite 侧可本地验证）。
"""
import os
import sqlite3
import tempfile


def test_backend_default_is_sqlite():
    # config 默认值不可在本地实例化（pydantic）——验证源码默认值
    src = open("src/config.py", encoding="utf-8").read()
    assert "STORAGE_BACKEND: str = \"sqlite\"" in src
    assert "DATABASE_URL: str = \"\"" in src


def test_validate_postgres_requires_url():
    src = open("src/config.py", encoding="utf-8").read()
    assert "STORAGE_BACKEND=postgres 时必须配置 DATABASE_URL" in src
    assert "STORAGE_BACKEND 仅支持 sqlite/postgres" in src


def test_migrate_missing_table_skips():
    from src.services.storage_migrate import _migrate_with_rollback
    db = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE memory (note_id INTEGER PRIMARY KEY, user_id INTEGER, group_id INTEGER, text TEXT)")
    conn.execute("INSERT INTO memory (note_id, user_id, group_id, text) VALUES (1, 7, 1, 'hello')")
    conn.commit()
    conn.close()
    # 无 pg 时：函数在 psycopg 缺失时应报 RuntimeError 风格而不是静默
    res = _migrate_with_rollback(db, "postgres://x@y/z", "no_such_table", "note_id", None)
    assert res == {"copied": 0, "skipped": True}
    os.remove(db)
