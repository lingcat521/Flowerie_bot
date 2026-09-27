"""隐私存档（从 MessageAssembler 拆出）：按群/按天的明文存档 + 保留策略。

ARCHIVE_ENABLED 默认关（隐私优先）；开启后写
<ARCHIVE_BASE_DIR>/<group_id>/YYYY-MM-DD.txt，并按 ARCHIVE_RETENTION_DAYS
（保留天数）与 ARCHIVE_MAX_SIZE_MB（每群目录上限）清理。
纯文件操作：只读 config，不持有组装状态。
"""
import os
import time
from datetime import datetime

from src.utils.logging_setup import get_logger

logger = get_logger(__name__)


# ---------- 存档（ARCHIVE_ENABLED 开关，默认关——隐私优先） ----------
def archive_message(config, group_id: int, user_id: int, text: str, raw_time: int) -> None:
    if not getattr(config, "ARCHIVE_ENABLED", False):
        return
    if not text:
        return
    try:
        base = config.ARCHIVE_BASE_DIR
        if not os.path.exists(base):
            os.makedirs(base, exist_ok=True)
        group_dir = os.path.join(base, str(group_id))
        if not os.path.exists(group_dir):
            os.makedirs(group_dir, exist_ok=True)
        filename = os.path.join(group_dir, f"{datetime.now().strftime('%Y-%m-%d')}.txt")
        time_str = datetime.fromtimestamp(raw_time).strftime("%H:%M:%S")
        line = f"[{time_str}] 用户{user_id}：{text}\n"
        with open(filename, "a", encoding="utf-8") as f:
            f.write(line)
        # 存档治理：保留天数 + 每群目录大小上限（隐私数据不是无限堆积）
        cleanup_group_dir(config, group_dir)
    except Exception as e:
        logger.error(f"Archive error: {e}")

def cleanup_group_dir(config, group_dir: str) -> None:
    """按 ARCHIVE_RETENTION_DAYS（保留天数）与 ARCHIVE_MAX_SIZE_MB（每群大小上限）清理存档。"""
    try:
        retention_days = getattr(config, "ARCHIVE_RETENTION_DAYS", 0)
        max_size_mb = getattr(config, "ARCHIVE_MAX_SIZE_MB", 0)
        if not retention_days and not max_size_mb:
            return
        files = [os.path.join(group_dir, f) for f in os.listdir(group_dir)
                 if os.path.isfile(os.path.join(group_dir, f))]
        # 1) 按保留天数清理过期文件
        if retention_days and retention_days > 0:
            cutoff = time.time() - retention_days * 86400
            for fp in files:
                try:
                    if os.path.getmtime(fp) < cutoff:
                        os.remove(fp)
                except OSError:
                    pass
        # 2) 按目录大小上限删最旧（从旧到新删到不超限）
        if max_size_mb and max_size_mb > 0:
            limit = max_size_mb * 1024 * 1024
            files = [os.path.join(group_dir, f) for f in os.listdir(group_dir)
                     if os.path.isfile(os.path.join(group_dir, f))]
            files.sort(key=os.path.getmtime)
            total = sum(os.path.getsize(fp) for fp in files)
            for fp in files:
                if total <= limit:
                    break
                try:
                    total -= os.path.getsize(fp)
                    os.remove(fp)
                    logger.debug(f"Archive pruned (size cap): {os.path.basename(fp)}")
                except OSError:
                    pass
    except Exception as e:
        logger.error(f"Archive cleanup error: {e}")
