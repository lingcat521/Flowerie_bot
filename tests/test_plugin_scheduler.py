"""PluginScheduler（Phase 1 / M1：从 PluginManager 拆出的定时任务域）单元测试。

拆分前这层逻辑没有专属用例（Phase 0 审计报告 §4.3 记录的测试缺口）。这里补上：
kind 校验边界、同插件同名幂等覆盖、越权取消拒绝、cancel_all 清理、
delay 一次性触发后自动清理、以及 manager 侧公开面保持（委托而非自己持有状态）。
"""
import asyncio
import inspect

import pytest

from src.plugins.scheduler import PluginScheduler


class _Recorder:
    def __init__(self):
        self.events = []

    async def __call__(self, event, payload):
        self.events.append((event, payload))


def _sched():
    rec = _Recorder()
    return PluginScheduler(rec), rec


@pytest.mark.asyncio
async def test_register_validates_kind_and_bounds():
    """四种 kind 的边界：interval 1~86400 / delay (0, 604800] / daily HH:MM / 未知 kind。"""
    s, _rec = _sched()
    assert (await s.register("p", "a", "interval", 0.5))["ok"] is False   # <1 秒
    # when 为 0/None 时按默认 60 秒（拆分前 float(when or 60) 的语义，逐字保留）
    assert (await s.register("p", "a0", "interval", 0))["ok"] is True
    assert (await s.register("p", "a", "interval", 86401))["ok"] is False
    assert (await s.register("p", "a", "interval", 1))["ok"] is True
    assert (await s.register("p", "b", "delay", 0))["ok"] is False
    assert (await s.register("p", "c", "delay", 604801))["ok"] is False
    assert (await s.register("p", "d", "daily", "9:30"))["ok"] is False
    assert (await s.register("p", "e", "daily", "09:30"))["ok"] is True
    assert (await s.register("p", "f", "cron", "x"))["ok"] is False
    listed = s.list_for("p")
    assert {x["name"] for x in listed} == {"a", "a0", "e"}
    assert all("schedule_id" in x for x in listed)
    s.cancel_all()


@pytest.mark.asyncio
async def test_same_plugin_same_name_is_idempotent():
    """同插件同名 → 覆盖（幂等）：只保留一份，旧 task 被取消。"""
    s, _rec = _sched()
    r1 = await s.register("p", "job", "interval", 3600)
    r2 = await s.register("p", "job", "interval", 3600)
    assert r1["schedule_id"] == r2["schedule_id"] == "p:job"
    assert len(s._schedules) == 1
    assert len(s._tasks) == 1
    s.cancel_all()


@pytest.mark.asyncio
async def test_cancel_rejects_other_plugins_schedule():
    """越权取消必须拒绝（别人的 schedule_id 一律不认）。"""
    s, _rec = _sched()
    await s.register("owner", "job", "interval", 3600)
    denied = await s.cancel("intruder", "owner:job")
    assert denied["ok"] is False and "不属于本插件" in denied["error"]
    assert "owner:job" in s._schedules
    assert (await s.cancel("owner", "owner:job"))["ok"] is True
    assert s._schedules == {} and s._tasks == {}


@pytest.mark.asyncio
async def test_delay_fires_once_then_cleans_up():
    """delay 一次性：到点派发一次（payload 形状与拆分前一致），随后自动清理。"""
    s, rec = _sched()
    assert (await s.register("p", "once", "delay", 0.05))["ok"] is True
    await asyncio.sleep(0.3)
    assert len(rec.events) == 1
    event, payload = rec.events[0]
    assert event == "schedule"
    assert payload == {"kind": "schedule", "schedule_id": "p:once", "name": "once",
                       "trigger": "delay", "plugin_id": "p", "trace_id": ""}
    assert s._schedules == {} and s._tasks == {}


@pytest.mark.asyncio
async def test_cancel_all_clears_everything():
    s, _rec = _sched()
    await s.register("a", "x", "interval", 3600)
    await s.register("b", "y", "interval", 3600)
    assert len(s._tasks) == 2
    tasks = list(s._tasks.values())
    s.cancel_all()
    assert s._schedules == {} and s._tasks == {}
    await asyncio.sleep(0)          # 让取消生效，确认任务确实被 cancel
    assert all(t.cancelled() or t.done() for t in tasks)


def test_manager_delegates_and_no_longer_holds_scheduler_state():
    """manager 侧公开面保持：cancel_all_schedules 仍在，且不再自己持有调度状态。"""
    from src.plugins import manager as manager_mod
    src = inspect.getsource(manager_mod.PluginManager)
    assert "PluginScheduler(" in src
    assert "_schedule_tasks" not in src
    assert "self._schedules" not in src
    assert "def cancel_all_schedules" in src
