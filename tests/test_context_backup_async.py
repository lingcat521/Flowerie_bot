
"""上下文备份线程池化（fix.txt ⑤ IO-1）：不阻塞事件循环 + 保存串行 + 数据一致。

含 micro-benchmark（-s 时打印实测耗时），断言只覆盖可重复的部分。
"""
import asyncio
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.context_backup import ContextBackupStore
from src.core.context_manager import ContextManager
from src.models import GlobalState


def _build(tmp_path, groups=200, msgs=50):
    cfg = SimpleNamespace(CONTEXT_BACKUP_PATH=os.path.join(str(tmp_path), "ctx.db"),
                          CONTEXT_SIZE=300)
    cm = ContextManager(cfg, {}, GlobalState())
    for gid in range(groups):
        st = cm.get_group_state(gid)
        for i in range(msgs):
            st.context.append({"user_id": 1, "message": "m%d" % i, "is_bot": False,
                               "time": 1.0 + i})
        st.processed_msg_ids.extend(range(200))
    return cm, cfg


def test_backup_save_does_not_block_event_loop(tmp_path):
    """旧实现：同步全表重写会把事件循环按住；新实现里 ticker 必须持续推进。"""
    cm, cfg = _build(tmp_path)
    snapshot = {gid: (list(st.context)[-50:], list(st.processed_msg_ids)[-200:])
                for gid, st in cm.groups.items()}
    t0 = time.perf_counter()
    ContextBackupStore(cfg).save(snapshot)
    sync_ms = (time.perf_counter() - t0) * 1000
    assert sync_ms > 0

    ticks = {"n": 0, "stop": False}

    async def measure():
        async def ticker():
            while not ticks["stop"]:
                ticks["n"] += 1
                await asyncio.sleep(0.001)

        task = asyncio.create_task(ticker())
        await cm.save_context_backup()
        ticks["stop"] = True
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(measure())
    print("同步存储层 %.1f ms；to_thread 期间 ticker 推进 %d 次" % (sync_ms, ticks["n"]))
    assert ticks["n"] > 0

    cm2 = ContextManager(cfg, {}, GlobalState())
    cm2.load_context_backup()
    assert len(cm2.groups) == 200
    assert len(cm2.get_group_state(0).context) == 50


def test_concurrent_saves_are_serialized(tmp_path):
    """两次并发保存仍走同一把锁，结果与串行执行一致。"""
    cm, cfg = _build(tmp_path, groups=50, msgs=20)

    async def run_two():
        await asyncio.gather(cm.save_context_backup(), cm.save_context_backup())

    asyncio.run(run_two())
    cm2 = ContextManager(cfg, {}, GlobalState())
    cm2.load_context_backup()
    assert len(cm2.groups) == 50
    assert len(cm2.get_group_state(0).context) == 20

