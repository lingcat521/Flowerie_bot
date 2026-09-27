"""指标注册表：同名不同 schema 不得静默吞标签（Phase 0 审计报告 §5 第 2 条）。

历史问题：`received_messages_total` 在 `message_router`（无标签）与两个 transport 客户端
（带 `post_type`）各注册一次，而 `registry.counter()` 是"先到先得" → 后注册者拿到旧实例，
它的 `inc({"post_type": ...})` 被 `_label_key` 静默丢弃（label_names 为空 → 返回空元组）。
"""
import importlib
import logging

from src.utils.metrics import registry


def _load_registrars():
    """按副作用导入：让 transport / core 的模块级计数器都注册进来。"""
    for name in ("src.core.message_router", "src.transport.ws_server", "src.transport.ws_forward_client"):
        importlib.import_module(name)


def test_no_metric_name_has_conflicting_schemas():
    """全量自省：注册表里不允许出现「同名不同标签 schema」的计数器。"""
    _load_registrars()
    schemas = {}
    for name, counter in registry._counters.items():
        schemas.setdefault(name, set()).add(tuple(counter.label_names))
    conflicts = {k: v for k, v in schemas.items() if len(v) > 1}
    assert not conflicts, "同名不同 schema 的计数器: %s" % conflicts


def test_ws_events_counter_is_separate_from_messages_counter():
    """transport 侧事件计数器改名为 `ws_events_total`（带 post_type），与消息计数器不再相撞。"""
    _load_registrars()
    ws = registry._counters["ws_events_total"]
    assert tuple(ws.label_names) == ("post_type",)
    recv = registry._counters["received_messages_total"]
    assert tuple(recv.label_names) == ()
    # 两条计数互不影响：给 ws 计数不会污染消息计数
    before = recv.snapshot()
    ws.inc({"post_type": "message"})
    assert recv.snapshot() == before
    # 标签确实生效（不是被吞掉）
    ws.inc({"post_type": "message"})
    assert any(k == ("message",) for k, _v in ws.series())


def test_schema_conflict_logs_warning(caplog):
    """同名不同 schema 必须告警（此前静默返回旧实例，标签静默丢失）。"""
    local = type(registry)()
    local.counter("dup_total", "第一次注册")
    with caplog.at_level(logging.WARNING):
        local.counter("dup_total", "第二次注册（带标签）", ["k"])
    messages = [r.getMessage() for r in caplog.records]
    assert any("metric_schema_conflict" in m for m in messages), messages
    assert tuple(local._counters["dup_total"].label_names) == ()
