"""Milky 消息号字段回归（P4）：Milky **只有 message_seq**，没有 message_id。

证据（均 [CODE]）：
- `Lagrange.Milky/Models/Messages/IncomingMessageBase.cs` L13：`message_seq`
- `LLBot/src/milky/transform/event.ts` L80/L99/L118：friend/group/temp 三种场景都用 `message_seq`
- `Api/Handlers/Message/SendGroupMessageHandler.cs` L41：Result 字段是 `message_seq`
- `RecallGroupMessageHandler.cs` L36 / `RecallPrivateMessageHandler.cs` L36：Request 只有 `message_seq`

修复前的真实后果：Milky 模式下 `message_id` 恒为 None —— 事件去重键（event_id）缺消息号、
撤回/删除拿不到可用的号。本文件锁住三处修复（解析器 / 发送响应 / 撤回路由）。
"""
import ast
import io

from src.adapters.milky_parser import MilkyEventParser

SENDER = "src/services/sender.py"


CHANNELS = "src/transport/action_channels.py"


def _sender_src() -> str:
    return io.open(SENDER, encoding="utf-8").read()


def _channels_src() -> str:
    return io.open(CHANNELS, encoding="utf-8").read()


def _func_src(name: str) -> str:
    src = _sender_src()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError("sender.py 里找不到 %s" % name)


def test_parser_maps_message_seq_to_message_id():
    raw = {"time": 1, "self_id": 10001, "event_type": "message_receive",
           "data": {"message_scene": "group", "peer_id": 123, "sender_id": 456,
                    "message_seq": 998877,
                    "segments": [{"type": "text", "data": {"text": "hi"}}]}}
    ev = MilkyEventParser(bot_qq=10001).parse(raw)
    assert ev.message_id == 998877
    assert "998877" in ev.event_id


def test_friend_scene_message_seq_also_works():
    raw = {"time": 1, "self_id": 10001, "event_type": "message_receive",
           "data": {"message_scene": "friend", "peer_id": 456, "sender_id": 456,
                    "message_seq": 5, "segments": []}}
    ev = MilkyEventParser(bot_qq=10001).parse(raw)
    assert ev.message_id == 5 and ev.scope == "private"


def test_send_response_reads_message_seq():
    assert "message_seq" in _func_src("send_msg_raw")


def test_delete_msg_routes_milky_recall_actions():
    # Gate B/O：协议分支已下沉到 Adapter 通道 —— sender 只委托，Milky 撤回路由在通道里
    body = _func_src("delete_msg")
    assert "self._ensure_channel().recall" in body
    ch = _channels_src()
    assert "recall_group_message" in ch and "recall_private_message" in ch
    assert "message_seq" in ch


def test_delete_msg_default_scope_is_group():
    body = _func_src("delete_msg")
    assert 'scope: str = "group"' in body
