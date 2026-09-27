"""上下文崩溃备份的存储层（从 ContextManager 拆出）。

ContextManager 里约 189 行（60%）是「建库 / WAL / 旧 JSON 迁移 / 行级读写」，
与「上下文读写、接话概率、重复回复过滤」异质，而且是全项目唯一的同步阻塞 IO。
本模块只负责存储：库路径、连接与建表、旧 JSON 迁移、行的读回与全量重写；
把行灌进 GroupState / 从 state 取快照仍由 ContextManager 决定。
"""
import json
import os
import sqlite3
import time
from typing import Dict, List, Optional, Tuple

from src.utils.logging_setup import get_logger

logger = get_logger(__name__)


class ContextBackupStore:
    """按群持久化上下文（每群最近 50 条）与已处理消息 id（最近 200 个）。"""

    def __init__(self, config):
        self.config = config


    def db_path(self) -> Optional[str]:
        """备份库路径：旧 .json 配置自动映射到同目录 .db（兼容旧 .env）。"""
        path = self.config.CONTEXT_BACKUP_PATH
        if not path:
            return None
        if str(path).lower().endswith(".json"):
            return str(path)[:-5] + ".db"
        return path

    def _open(self, path: str, row_factory: bool = False) -> sqlite3.Connection:
        conn = sqlite3.connect(path)
        if row_factory:
            conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
        except sqlite3.Error:
            pass  # 只读介质时静默降级
        return conn

    def _init_db(self, conn) -> None:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS group_context (
            group_id INTEGER NOT NULL,
            seq INTEGER NOT NULL,
            user_id INTEGER,
            message TEXT,
            is_bot INTEGER NOT NULL DEFAULT 0,
            time REAL,
            PRIMARY KEY (group_id, seq)
        );
        CREATE TABLE IF NOT EXISTS processed_ids (
            group_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            PRIMARY KEY (group_id, message_id)
        );
        """)
        conn.commit()

    def migrate_from_json(self, legacy_path: str) -> None:
        """把旧 context_backup.json 导入 SQLite（兼容纯数组与 {"messages":..., "processed_ids":...} 两种格式）。"""
        try:
            with open(legacy_path, "r", encoding="utf-8") as f:
                backup = json.load(f)
        except Exception as e:
            logger.error(f"上下文备份迁移失败：读取旧 JSON 出错: {e}")
            return
        if not isinstance(backup, dict):
            return
        db_path = self.db_path()
        conn = sqlite3.connect(db_path)
        try:
            self._init_db(conn)
            restored = 0
            restored_ids = 0
            for group_id_str, value in backup.items():
                if isinstance(value, dict):
                    messages = value.get("messages", [])
                    processed_ids = value.get("processed_ids", [])
                elif isinstance(value, list):
                    messages = value
                    processed_ids = []
                else:
                    continue
                try:
                    group_id = int(group_id_str)
                except (TypeError, ValueError):
                    continue
                for seq, msg in enumerate(messages[-50:]):
                    if isinstance(msg, dict) and "message" in msg:
                        conn.execute(
                            "INSERT OR REPLACE INTO group_context (group_id, seq, user_id, message, is_bot, time)"
                            " VALUES (?,?,?,?,?,?)",
                            (group_id, seq,
                             msg.get("user_id", 0),
                             str(msg.get("message", "")),
                             1 if msg.get("is_bot", False) else 0,
                             msg.get("time", 0.0)),
                        )
                        restored += 1
                for mid in processed_ids[-200:]:
                    try:
                        conn.execute("INSERT OR IGNORE INTO processed_ids (group_id, message_id) VALUES (?,?)",
                                     (group_id, int(mid)))
                        restored_ids += 1
                    except (ValueError, TypeError):
                        continue
            conn.commit()
            try:
                os.replace(legacy_path, legacy_path + ".migrated")
                logger.info(f"旧上下文备份 JSON 已备份为: {legacy_path}.migrated")
            except OSError as e:
                logger.warning(f"旧上下文备份 JSON 备份改名失败（可手动删除）: {e}")
            logger.info(f"上下文备份已从 JSON 迁移到 SQLite: {restored} 条消息, {restored_ids} 条消息 id -> {db_path}")
        except Exception as e:
            logger.error(f"上下文备份迁移失败: {e}")
        finally:
            conn.close()


    def load(self) -> Tuple[List[tuple], List[tuple]]:
        """读回 (上下文行, 已处理消息 id 行)；出错时抛异常，由调用方记日志。

        上下文行 = (group_id, user_id, message, is_bot, time)，
        id 行 = (group_id, message_id)。
        """
        db_path = self.db_path()
        if not db_path:
            return [], []
        dirname = os.path.dirname(db_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        conn = self._open(db_path)
        try:
            self._init_db(conn)
            cnt = conn.execute("SELECT COUNT(*) FROM group_context").fetchone()[0]
        finally:
            conn.close()
        # 旧 JSON 迁移：db 为空且旧 json 存在时导入一次
        legacy = self.config.CONTEXT_BACKUP_PATH
        if cnt == 0 and legacy and str(legacy).lower().endswith(".json") and os.path.exists(legacy):
            self.migrate_from_json(legacy)

        conn = self._open(db_path, row_factory=True)
        try:
            rows = [(r["group_id"], r["user_id"], r["message"], r["is_bot"], r["time"])
                    for r in conn.execute("SELECT group_id, user_id, message, is_bot, time"
                                          " FROM group_context ORDER BY group_id, seq")]
            id_rows = [(r["group_id"], r["message_id"])
                       for r in conn.execute("SELECT group_id, message_id FROM processed_ids")]
        finally:
            conn.close()
        return rows, id_rows

    def save(self, groups: Dict[int, Tuple[List[dict], List[int]]]) -> bool:
        """单事务全量重写；groups = {group_id: (上下文快照, 已处理 id 快照)}。

        返回是否真的写了（CONTEXT_BACKUP_PATH 为空时不写、也不算错误）。
        """
        db_path = self.db_path()
        if not db_path:
            return False
        dirname = os.path.dirname(db_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        conn = self._open(db_path)
        try:
            self._init_db(conn)
            conn.execute("BEGIN")
            conn.execute("DELETE FROM group_context")
            conn.execute("DELETE FROM processed_ids")
            for group_id, (msgs, processed_ids) in groups.items():
                if not msgs and not processed_ids:
                    continue
                for seq, msg in enumerate(msgs):
                    conn.execute(
                        "INSERT INTO group_context (group_id, seq, user_id, message, is_bot, time)"
                        " VALUES (?,?,?,?,?,?)",
                        (group_id, seq,
                         msg.get("user_id", 0),
                         str(msg.get("message", "")),
                         1 if msg.get("is_bot", False) else 0,
                         msg.get("time", time.time())),
                    )
                for mid in processed_ids:
                    conn.execute("INSERT OR IGNORE INTO processed_ids (group_id, message_id) VALUES (?,?)",
                                 (group_id, mid))
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

