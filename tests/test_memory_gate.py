"""MEMORY_ENABLED gate 回归：关闭时不读/写长期记忆（参数曾丢失——CI 黑盒抓出）。"""
import asyncio
import tempfile

from src.services.memory_manager import MemoryManager


class StubRepo:
    """最小 repository 桩（record 交互）。"""

    def __init__(self):
        self.notes = []
        self.calls = []

    def list_notes(self, user_id, group_id, limit=None):
        self.calls.append(("list", user_id, group_id))
        return self.notes

    def list_all_notes(self):
        return []

    def iter_user_groups(self):
        return []

    def trim_notes(self, user_id, group_id, keep):
        return 0

    def commit(self):
        pass

    def insert_note(self, note):
        self.calls.append(("insert", note.user_id, note.group_id, note.text))
        return 1

    def close(self):
        pass


def make_mgr(enabled):
    db = tempfile.mktemp(suffix=".db")
    repo = StubRepo()
    return MemoryManager(db, 0, None, 30, repository=repo, memory_enabled=enabled), repo


def test_disabled_skips_reads_and_writes():
    mm, repo = make_mgr(False)
    assert mm.get_memory_context(1, 2) == ""
    assert repo.calls == []                      # 未读
    asyncio.run(mm.append_memory_text(1, 2, "我喜欢奶茶"))
    assert repo.calls == []                      # 未写
    mm.close()


def test_enabled_reads_and_writes():
    mm, repo = make_mgr(True)
    from src.repositories.base import MemoryNote
    mm.repository.notes = [MemoryNote(text="奶茶", user_id=1, group_id=2)]
    mm.get_memory_context(1, 2)
    assert ("list", 1, 2) in repo.calls
    asyncio.run(mm.append_memory_text(1, 2, "我喜欢奶茶"))
    assert any(c[0] == "insert" for c in repo.calls)
    mm.close()


def test_main_passes_memory_enabled():
    src = open("main.py", encoding="utf-8").read()
    assert "memory_enabled=config.MEMORY_ENABLED" in src
    mm_src = open("src/services/memory_manager.py", encoding="utf-8").read()
    assert "memory_enabled: bool = True" in mm_src
