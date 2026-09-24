"""Milky 能力矩阵回归：Sender 的每个端点都必须"要么有映射、要么明确不支持"。

刻意用 AST 解析 sender.py 而不是 import —— 这样不依赖 aiohttp，本地也能跑。
"""
import ast
import io
import re

SENDER = "src/services/sender.py"


def _sender_module():
    return ast.parse(io.open(SENDER, encoding="utf-8").read())


def _milky_actions() -> dict:
    for node in ast.walk(_sender_module()):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "_MILKY_ACTIONS" for t in node.targets):
            return {k.value: v.value for k, v in zip(node.value.keys, node.value.values)}
    raise AssertionError("sender.py 里找不到 _MILKY_ACTIONS")


def _milky_unsupported() -> set:
    for node in ast.walk(_sender_module()):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "_MILKY_UNSUPPORTED" for t in node.targets):
            call = node.value
            elts = call.args[0].elts if call.args else []
            return {e.value for e in elts}
    raise AssertionError("sender.py 里找不到 _MILKY_UNSUPPORTED")


def _literal_endpoints() -> set:
    src = io.open(SENDER, encoding="utf-8").read()
    return set(re.findall(r'''["']/([a-z_]+)["']''', src))


def test_every_endpoint_is_mapped_or_explicitly_unsupported():
    """新增端点却忘了登记 → 这里报警（Milky 下会静默透传成 404）。"""
    eps = _literal_endpoints()
    covered = set(_milky_actions()) | _milky_unsupported()
    missing = sorted(eps - covered)
    assert missing == [], missing


def test_unsupported_and_mapped_do_not_overlap():
    both = set(_milky_actions()) & _milky_unsupported()
    assert both == set(), both


def test_unsupported_endpoints_are_the_known_gaps():
    """这 7 个是逐一核对官方 Milky API（system/message/friend/group/file 五组）后
    确认没有对应能力的 —— 将来 Milky 补了，删掉对应项并加映射即可。"""
    assert _milky_unsupported() == {
        "get_group_honor_info", "get_online_clients", "delete_essence_msg",
        "send_group_forward_msg", "send_private_forward_msg",
        "set_group_config", "set_self_profile",
    }


def test_core_mappings_are_milky_native_names():
    """核心发送必须映射到 Milky 官方动作名（下划线式，区别于 OneBot 的 send_group_msg）。"""
    m = _milky_actions()
    assert m["send_group_msg"] == "send_group_message"
    assert m["send_private_msg"] == "send_private_message"
    assert m["set_group_card"] == "set_group_member_card"
    assert m["send_poke"] == "send_group_nudge"
    assert m["set_react"] == "send_group_message_reaction"


def test_multi_reply_shares_the_same_send_path():
    """Multi-Reply 复用 sender 的单条发送 → Milky 下自动共用 send_group_message。"""
    src = io.open("src/core/reply_dispatch.py", encoding="utf-8").read()
    assert "send_group_message" in src, "多条发送必须复用 sender 的单条方法（协议无关）"
    assert _milky_actions()["send_group_msg"] == "send_group_message"


def test_unsupported_returns_clear_error_not_silent_404():
    src = io.open(SENDER, encoding="utf-8").read()
    assert "_MILKY_UNSUPPORTED" in src
    assert "Milky 协议不支持该能力" in src
