"""出站段路由（任务书 §十/§十一/§十四）：配置 → 档案 → 序列化器的接线 + 默认关闭行为。

两层断言：

1. **纯函数**（本机可跑，不依赖 aiohttp）：配置解析、默认关闭、未调查客户端不收敛、两个协议各走自己的序列化器；
2. **静态接线守卫**（ast，同样不需要 aiohttp）：`Sender` 必须**接收**注入的适配器并在发送路径上调用它，
   组合根（`main.py`）必须构造并传入 —— 客户端的名字与逻辑不允许出现在 services 里（ADR-001 冻结层规则）。
"""
import ast
import os

import pytest

from src.adapters.outgoing import (
    KNOWN_CLIENTS,
    NOTE_UNKNOWN_CLIENT,
    channel_protocol,
    make_outgoing_adapter,
    parse_profile_setting,
    prepare_outgoing,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------- 1. 纯函数

@pytest.mark.parametrize("value,expected", [
    ("", ("", "")),
    (None, ("", "")),
    ("go-cqhttp", ("", "go-cqhttp")),
    ("NapCat", ("", "napcat")),
    ("onebot11:llbot", ("onebot11", "llbot")),
    ("milky:llbot", ("milky", "llbot")),
    ("satori:foo", ("", "")),          # 未知协议 → 关闭
    ("  milky:lagrange  ", ("milky", "lagrange")),
])
def test_parse_profile_setting(value, expected):
    assert parse_profile_setting(value) == expected


def test_default_is_off():
    """默认（空配置）→ 不注入适配器 = 发送行为与历史完全一致。"""
    assert make_outgoing_adapter("") is None
    assert make_outgoing_adapter("satori:foo") is None
    segments = [{"type": "text", "data": {"text": "hi"}},
                {"type": "mface", "data": {"emoji_id": "1"}}]
    out, notes = prepare_outgoing(segments, client="")
    assert out == segments and notes == []


def test_unknown_client_is_not_silently_adapted():
    """未调查的客户端：原样发送 + 一条说明（**不伪装**成已适配）。"""
    segments = [{"type": "text", "data": {"text": "hi"}}]
    out, notes = prepare_outgoing(segments, client="some-future-client")
    assert out == segments
    assert [n["reason"] for n in notes] == [NOTE_UNKNOWN_CLIENT]
    assert "some-future-client" in notes[0]["client"]
    assert "some-future-client" not in KNOWN_CLIENTS


def test_onebot_profile_is_applied():
    """配置了已调查的客户端 → 走 OneBot 序列化器（字段收敛 + note）。"""
    adapter = make_outgoing_adapter("go-cqhttp")
    assert adapter is not None and adapter.client == "go-cqhttp"
    out, notes = adapter([{"type": "mface", "data": {"emoji_id": "1"}}],
                         is_group=True, protocol="onebot11")
    assert out == [{"type": "mface", "data": {"emoji_id": "1"}}]     # 原样传递
    assert notes and notes[0]["reason"] == "segment_unsupported_by_profile"


def test_milky_profile_is_applied():
    """同名客户端在 Milky 下走 Milky 序列化器（段名/字段完全不同）。"""
    adapter = make_outgoing_adapter("milky:llbot")
    out, notes = adapter([{"type": "mention", "data": {"user_id": 1}}],
                         is_group=False, protocol="milky")
    assert out == [] and notes[0]["reason"] == "segment_dropped_by_client_rule"


def test_channel_protocol_mapping():
    assert channel_protocol("milky-http") == "milky"
    assert channel_protocol("onebot-ws") == "onebot11"
    assert channel_protocol("") == "onebot11"


# ---------------------------------------------------------------- 2. 静态接线守卫

def test_sender_accepts_injected_adapter_and_uses_it():
    """Sender 必须接收注入的适配器，并在发送路径上调用它（默认 None = 行为不变）。"""
    tree = ast.parse(_read("src/services/sender.py"))
    init_args = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "__init__":
            init_args = [a.arg for a in node.args.args]
    assert "outgoing_adapter" in init_args, "Sender.__init__ 少了 outgoing_adapter 注入点"

    body = _read("src/services/sender.py")
    assert "self._outgoing_adapter" in body, "注入的适配器没有被保存"
    # 两处段数组发送路径：send_msg_raw（通用）与 send_group_message_with_image（图片）\
    assert body.count("self._prepare_outgoing(") >= 2, \
        "段数组发送路径（send_msg_raw / 图片消息）必须调用出站收敛"


def test_sender_does_not_import_adapters():
    """冻结层规则：services 不得 import adapters（客户端差异靠组合根注入）。"""
    body = _read("src/services/sender.py")
    assert "src.adapters" not in body, "services 反向依赖 adapters（ADR-001 冻结层规则）"


def test_composition_root_injects_adapter():
    """组合根（main.py）必须构造并把适配器传给 Sender。"""
    body = _read("main.py")
    assert "make_outgoing_adapter" in body, "组合根没有构造出站适配器"
    assert "outgoing_adapter=" in body, "组合根没有把适配器注入 Sender"


def test_adapter_module_does_not_import_services():
    """反向：Adapter 层不得依赖 services（否则又是环形依赖）。"""
    body = _read("src/adapters/outgoing.py")
    assert "src.services" not in body
