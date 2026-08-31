"""PostgreSQL 后端真跑（CI service 提供 TEST_POSTGRES_URL；本地无 PG 时跳过——环境依赖）。

覆盖：PG MemoryRepository 与 PG BlossomRepository 的 CRUD/TTL/隔离语义。
"""
import os

import pytest

PG_URL = os.environ.get("TEST_POSTGRES_URL", "")


@pytest.mark.skipif(not PG_URL, reason="需要 TEST_POSTGRES_URL（CI postgres service）")
def test_postgres_memory_repository_crud():
    from src.repositories.base import MemoryNote
    from src.repositories.postgres_memory_repository import PostgresMemoryRepository

    try:
        repo = PostgresMemoryRepository(PG_URL)
    except Exception as e:  # noqa: BLE001 - 连接失败明确报错（不是静默）
        pytest.fail(f"PG 连接失败: {e}")
    try:
        note = MemoryNote(text="我喜欢奶茶", user_id=7001, group_id=701, confidence="model")
        nid = repo.insert_note(note)
        assert nid > 0
        notes = repo.list_notes(7001, 701)
        assert len(notes) == 1 and notes[0].text == "我喜欢奶茶"
        assert repo.count_notes(7001, 701) == 1
        assert repo.search_notes(7001, 701, "奶茶")
        repo.kv_set(7001, 701, "fav", "奶茶")
        assert ("fav", "奶茶") in repo.kv_list(7001, 701)
        assert repo.trim_notes(7001, 701, 0) >= 0
        assert repo.delete_user_notes(7001, 701) == 1
        repo.commit()
    finally:
        repo.close()


@pytest.mark.skipif(not PG_URL, reason="需要 TEST_POSTGRES_URL（CI postgres service）")
def test_postgres_blossom_repository_isolated():
    from src.repositories.blossom_memory_repository import BlossomMemoryRecord
    from src.repositories.postgres_blossom_repository import PostgresBlossomMemoryRepository

    repo = PostgresBlossomMemoryRepository(PG_URL)
    try:
        mid = repo.add(BlossomMemoryRecord(memory_id=0, group_id=801, kind="group",
                                           text="奶茶好喝", vector=[0.1, 0.2, 0.3, 0.4],
                                           created_at=100.0))
        assert mid > 0
        hit = repo.list_by_group(801, "group")
        assert len(hit) == 1 and hit[0]["text"] == "奶茶好喝"
        assert repo.list_by_group(802, "group") == []  # 群隔离
        assert repo.count(801) == 1
        repo.touch(mid)
        assert repo.recent(801, 1)[0]["used_count"] >= 1
        repo.delete_missing_before(801, 0, 99999)  # ttl 清理
        assert repo.count(801) == 0
    finally:
        repo.close()
