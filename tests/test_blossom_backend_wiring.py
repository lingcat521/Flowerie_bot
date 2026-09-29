"""Blossom Memory 存储后端接线（road.txt §二）：默认 SQLite 不变 / postgres 真注入 / 失败要响。

不需要真 PostgreSQL：这里验证的是**组合根的选择逻辑与生命周期**（用替身类记录构造参数），
真库的 CRUD 语义由 tests/test_postgres_backend.py（CI 的 postgres service）覆盖。
"""
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main as app_main  # noqa: E402 - 组合根模块：本文件测的就是它的装配决策
from src.repositories.blossom_memory_repository import SQLiteBlossomMemoryRepository  # noqa: E402
from src.services.blossom_memory import BlossomMemoryManager  # noqa: E402

PG_MODULE = "src.repositories.postgres_blossom_repository.PostgresBlossomMemoryRepository"
PG_URL = "postgresql://flowerie:secret@db:5432/flowerie"


class _Cfg:
    """最小配置替身：只带组合根选择逻辑真正读的字段（其余字段管理器用 getattr 默认值取）。"""

    def __init__(self, **kw):
        self.STORAGE_BACKEND = kw.pop("STORAGE_BACKEND", "sqlite")
        self.DATABASE_URL = kw.pop("DATABASE_URL", "")
        self.BLOSSOM_MEMORY_ENABLED = kw.pop("BLOSSOM_MEMORY_ENABLED", True)
        self.BLOSSOM_MEMORY_DB_PATH = kw.pop("BLOSSOM_MEMORY_DB_PATH", "")
        # validate_config 用到的必填项（默认给合法值）
        self.DEEPSEEK_API_KEY = kw.pop("DEEPSEEK_API_KEY", "sk-real-looking-key")
        self.BOT_QQ = kw.pop("BOT_QQ", 10001)
        self.WS_PORT = kw.pop("WS_PORT", 3001)
        for key, value in kw.items():
            setattr(self, key, value)


def test_sqlite_backend_keeps_sqlite_repository(tmp_path):
    """默认后端：组合根不注入任何仓库，管理器自建 SQLite（行为与升级前完全一致）。"""
    cfg = _Cfg(STORAGE_BACKEND="sqlite", BLOSSOM_MEMORY_DB_PATH=str(tmp_path / "blossom.db"))
    assert app_main._build_blossom_repository(cfg) is None
    mgr = BlossomMemoryManager(cfg)
    assert isinstance(mgr.repository, SQLiteBlossomMemoryRepository)
    asyncio.run(mgr.close())


def test_postgres_backend_injects_postgres_repository(monkeypatch):
    """STORAGE_BACKEND=postgres：构造 PG 仓库并用 DATABASE_URL，管理器必须用它。"""
    made = {}

    class _FakePg:
        def __init__(self, url):
            made["url"] = url
            self.closed = False

        def close(self):
            self.closed = True

    monkeypatch.setattr(PG_MODULE, _FakePg)
    cfg = _Cfg(STORAGE_BACKEND="postgres", DATABASE_URL=PG_URL)
    repo = app_main._build_blossom_repository(cfg)
    assert isinstance(repo, _FakePg), repo
    assert made["url"] == PG_URL

    mgr = BlossomMemoryManager(cfg, repository=repo)
    assert mgr.repository is repo, "管理器没有使用注入的 PG 仓库"
    assert not isinstance(mgr.repository, SQLiteBlossomMemoryRepository)
    asyncio.run(mgr.close())
    assert repo.closed is True, "仓库/连接池必须由管理器按生命周期关闭"


def test_postgres_without_database_url_fails_loudly():
    """缺 DATABASE_URL：明确报错，绝不静默给一个 SQLite 仓库。"""
    cfg = _Cfg(STORAGE_BACKEND="postgres", DATABASE_URL="")
    with pytest.raises(RuntimeError) as excinfo:
        app_main._build_blossom_repository(cfg)
    message = str(excinfo.value)
    assert "DATABASE_URL" in message and "不回退 SQLite" in message, message


def test_postgres_connection_failure_is_wrapped(monkeypatch):
    """PG 构造失败（缺 psycopg / 连不上）：包装成带原因与非回退声明的启动错误。"""

    class _Boom:
        def __init__(self, url):
            raise RuntimeError("could not connect to server: Connection refused")

    monkeypatch.setattr(PG_MODULE, _Boom)
    cfg = _Cfg(STORAGE_BACKEND="postgres", DATABASE_URL=PG_URL)
    with pytest.raises(RuntimeError) as excinfo:
        app_main._build_blossom_repository(cfg)
    message = str(excinfo.value)
    assert "不回退 SQLite" in message, message
    assert "Connection refused" in message, message


def test_validate_config_requires_database_url_for_postgres():
    """既有 fail-fast 不回归：postgres 必须有 DATABASE_URL。"""
    from src.config import validate_config

    with pytest.raises(ValueError) as excinfo:
        validate_config(_Cfg(STORAGE_BACKEND="postgres", DATABASE_URL=""))
    assert "DATABASE_URL" in str(excinfo.value)


def test_composition_root_really_injects_the_repository():
    """静态护栏：组合根必须把 repository 传给 BlossomMemoryManager（防止将来又被摘掉）。"""
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "BlossomMemoryManager(config, repository=_build_blossom_repository(config)" in source
