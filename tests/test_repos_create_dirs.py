"""防回归：所有 sqlite 仓库在「不存在的父目录」下构造——自动建目录（logs 同类坑）。"""
import os

from src.repositories.blossom_memory_repository import BlossomMemoryRepository
from src.repositories.meme_knowledge_repository import MemeKnowledgeRepository
from src.repositories.settings_repository import SettingsRepository
from src.repositories.sticker_repository import StickerRepository


def _fresh_path(tmp):
    return os.path.join(tmp, "not_exist_dir", "sub", "x.db")


def test_settings_repo_creates_dirs(tmp_path):
    p = _fresh_path(str(tmp_path))
    r = SettingsRepository(p)
    r._conn.close()
    assert os.path.exists(p)


def test_meme_repo_creates_dirs(tmp_path):
    p = _fresh_path(str(tmp_path))
    r = MemeKnowledgeRepository(p)
    r._conn.close()
    assert os.path.exists(p)


def test_blossom_repo_creates_dirs(tmp_path):
    p = _fresh_path(str(tmp_path))
    r = BlossomMemoryRepository("sqlite://" + p)
    r._conn.close()
    assert os.path.exists(p)


def test_sticker_repo_creates_dirs(tmp_path):
    p = _fresh_path(str(tmp_path))
    r = StickerRepository(p)
    r._conn.close()
    assert os.path.exists(p)
