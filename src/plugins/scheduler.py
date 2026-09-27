"""插件定时任务调度器（Phase 1 / M1：从 PluginManager 拆出的独立职责域）。

职责边界（Phase 0 审计报告 §4.3）：
- **拥有**：定时任务的注册 / 校验 / 同名去重 / 取消 / 派发，以及两个状态容器
  （`_schedules` / `_tasks`）——调度器是它们的唯一 owner。
- **依赖**：注入的 `dispatch` 回调（manager 传 `self.dispatch_event`）+ 模块 logger。
- **不管**：插件生命周期、权限、action 执行 —— 那些仍在 PluginManager。

行为与拆分前**逐字一致**（interval 1~86400 / delay 0~604800 / daily HH:MM 的校验与
三条循环语义、同插件同名覆盖、`schedule_id = "<plugin_id>:<name>"` 的格式都不变）。
"""
import asyncio
import re
import time
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List

from src.utils.logging_setup import get_logger

logger = get_logger(__name__)

DispatchFn = Callable[[str, Dict[str, Any]], Awaitable[Any]]


class PluginScheduler:
    """轻量调度：interval（秒循环）/ delay（一次性）/ daily（HH:MM 每日）。"""

    def __init__(self, dispatch: DispatchFn):
        self._dispatch = dispatch
        #: schedule_id -> {plugin_id, name, kind, when, created}
        self._schedules: Dict[str, dict] = {}
        #: schedule_id -> asyncio.Task（取消/清理都靠它）
        self._tasks: Dict[str, asyncio.Task] = {}

    # ---------------------------------------------------------------- 对外 API
    async def register(self, plugin_id: str, name: str, kind: str, when: Any) -> dict:
        """注册（同插件同名 → 覆盖，幂等）。返回与拆分前 action 分支逐字一致的 dict。"""
        if kind == "interval":
            seconds = float(when or 60)
            if not (1 <= seconds <= 86400):
                return {"ok": False, "error": "interval 必须 1~86400 秒"}
        elif kind == "delay":
            seconds = float(when or 0)
            if not (0 < seconds <= 86400 * 7):
                return {"ok": False, "error": "delay 必须 0~604800 秒"}
        elif kind == "daily":
            if not re.match(r"^\d{2}:\d{2}$", str(when or "")):
                return {"ok": False, "error": "daily 需要 HH:MM（如 09:30）"}
        else:
            return {"ok": False, "error": "未知 schedule kind: %s" % kind}
        # 同插件同名覆盖（幂等）
        for sid, sched in list(self._schedules.items()):
            if sched.get("plugin_id") == plugin_id and sched.get("name") == name:
                await self._cancel_one(sid)
        sid = "%s:%s" % (plugin_id, name)
        self._schedules[sid] = {"plugin_id": plugin_id, "name": name, "kind": kind,
                                "when": when, "created": time.time()}
        self._tasks[sid] = asyncio.get_running_loop().create_task(self._loop(sid, kind, when))
        return {"ok": True, "schedule_id": sid, "name": name, "kind": kind}

    async def cancel(self, plugin_id: str, schedule_id: str) -> dict:
        """取消本插件自己的任务（**越权拒绝**：别人的 schedule_id 一律不认）。"""
        sched = self._schedules.get(schedule_id)
        if sched is None or sched.get("plugin_id") != plugin_id:
            return {"ok": False, "error": "schedule 不存在（或不属于本插件）"}
        await self._cancel_one(schedule_id)
        return {"ok": True, "schedule_id": schedule_id}

    def list_for(self, plugin_id: str) -> List[dict]:
        """列出本插件的任务（带 schedule_id 字段）。"""
        return [{**s, "schedule_id": sid} for sid, s in self._schedules.items()
                if s.get("plugin_id") == plugin_id]

    def cancel_all(self) -> None:
        """shutdown 时清理全部调度（同步；manager.cancel_all_schedules() 委托到这里）。"""
        for sid in list(self._tasks.keys()):
            task = self._tasks.pop(sid, None)
            if task is not None:
                task.cancel()
        self._schedules.clear()

    def default_name(self, prefix: str = "task") -> str:
        """未显式命名时的默认名（与拆分前 f"task{len(self._schedules) + 1}" 等价）。"""
        return "%s%d" % (prefix, len(self._schedules) + 1)

    # ---------------------------------------------------------------- 内部
    async def _loop(self, sid: str, kind: str, when: Any) -> None:
        """interval/delay/daily 三条循环（与拆分前逐字一致）。"""
        try:
            if kind == "delay":
                await asyncio.sleep(float(when or 0))
                await self._dispatch_one(sid)
                # delay 一次性任务：触发即清理（interval/daily 保留）
                self._tasks.pop(sid, None)
                self._schedules.pop(sid, None)
            elif kind == "interval":
                seconds = float(when or 60)
                while sid in self._tasks:
                    await asyncio.sleep(seconds)
                    if sid not in self._tasks:
                        break
                    await self._dispatch_one(sid)
            elif kind == "daily":
                hh, mm = str(when or "00:00").split(":")
                while sid in self._tasks:
                    now = datetime.now()
                    nxt = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
                    if nxt <= now:
                        nxt = nxt + timedelta(days=1)
                    await asyncio.sleep(max(1.0, (nxt - now).total_seconds()))
                    if sid not in self._tasks:
                        break
                    await self._dispatch_one(sid)
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001 - 调度器异常不拖垮管理器
            return

    async def _dispatch_one(self, sid: str) -> None:
        sched = self._schedules.get(sid)
        if sched is None:
            return
        payload = {"kind": "schedule", "schedule_id": sid, "name": sched["name"],
                   "trigger": sched["kind"], "plugin_id": sched["plugin_id"],
                   "trace_id": ""}
        try:
            await self._dispatch("schedule", payload)
        except Exception:  # noqa: BLE001
            pass

    async def _cancel_one(self, sid: str) -> None:
        task = self._tasks.pop(sid, None)
        self._schedules.pop(sid, None)
        if task is not None:
            try:
                task.cancel()
            except Exception:  # noqa: BLE001
                pass

