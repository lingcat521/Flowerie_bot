"""协议选择：make_adapters 按 protocol 构造对应解析器（Milky 入站事件链路）。"""
import src.adapters.container as container
from src.adapters.container import make_adapters
from src.adapters.milky_parser import MilkyEventParser
from src.adapters.onebot_parser import OneBotEventParser


class _Sender:
    async def send_group_message(self, *a, **k): return True
    async def send_private_message(self, *a, **k): return True
    async def get_login_info(self, *a, **k): return {"ok": True}
    async def close(self): pass


def _mk(monkeypatch, protocol):
    # 桩只测协议选择：绕过完整契约校验（真实 Sender 由 CI/启动期覆盖）
    monkeypatch.setattr(container, "_missing_sender_methods", lambda sender: [])
    return make_adapters(123, _Sender(), protocol=protocol)


def test_milky_protocol_selects_milky_parser(monkeypatch):
    ad = _mk(monkeypatch, "milky")
    assert ad.transport == "milky"
    assert isinstance(ad.parser, MilkyEventParser)


def test_onebot_default_unchanged(monkeypatch):
    ad = _mk(monkeypatch, "onebot")
    assert ad.transport == "onebot"
    assert isinstance(ad.parser, OneBotEventParser)


def test_milky_parser_parses_segments(monkeypatch):
    ad = _mk(monkeypatch, "milky")
    ev = ad.parser.parse({"time": 1, "event_type": "message_receive",
                          "data": {"message_scene": "group", "peer_id": 5, "sender_id": 6,
                                   "segments": [{"type": "text", "data": {"text": "hi"}}]}})
    assert ev.scope == "group" and ev.text == "hi"
