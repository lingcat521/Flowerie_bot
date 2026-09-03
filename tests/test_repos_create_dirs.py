"""防回归：所有 sqlite 仓库在「不存在的父目录」下构造——自动建目录（logs 同类坑）。"""
import os
import tempfile

from src.repositories.blossom_memory_repository import BlossomMemoryRepository
from src.repositories.meme_knowledge_repository import MemeKnowledgeRepository
from src.repositories.settings_repository import SettingsRepository
from src.repositories.sticker_repository import StickerRepository


def _fresh_path(tmp):
    return os.path.join(tmp, "not_exist_dir", "sub", "x.db")


def test_settings_repo_creates_dirs(tmp_path):
    p = _fresh_path(str(tmp_path))
    with SettingsRepository(p):
        assert os.path.exists(p)


def test_meme_repo_creates_dirs(tmp_path):
    p = _fresh_path(str(tmp_path))
    with MemeKnowledgeRepository(p):
        assert os.path.exists(p)


def test_blossom_repo_creates_dirs(tmp_path):
    p = _fresh_path(str(tmp_path))
    with BlossomMemoryRepository(p):
        assert os.path.exists(p)


def test_sticker_repo_creates_dirs(tmp_path):
    p = _fresh_path(str(tmp_path))
    with StickerRepository(p):
        assert os.path.exists(p)
