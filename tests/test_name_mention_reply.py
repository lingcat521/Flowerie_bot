"""名字唤起必回（不带 @）：默认昵称/群特色昵称命中 → 必回；无命中走概率。"""
from src.core.message_router import MessageRouter
from src.models import GroupMessage


class _Cfg:
    BOT_NICKNAME = "花璃"
    ONLY_REPLY_WHEN_AT = False


class _Store:
    def __init__(self, name): self._n = name
    def get(self, gid): return self._n


def _msg(text, mentioned=False):
    return GroupMessage(group_id=1, user_id=2, message_id=3, raw_message=text,
                        message_array=[], time=0, clean_text=text,
                        is_mentioned=mentioned)


def _router(store=None):
    r = MessageRouter.__new__(MessageRouter)
    r.config = _Cfg()
    r.group_nicknames = store
    r.policy_engine = type("P", (), {"should_reply_by_context": lambda self, g: False})()
    return r


def test_default_name_triggers():
    r = _router()
    assert r._should_reply(_msg("花璃在吗")) is True


def test_group_nickname_does_NOT_trigger():
    # 群特色昵称不参与唤起（仅与 BOT_NICKNAME 绑定）
    r = _router(_Store("小彩"))
    r.policy_engine = type("P", (), {"should_reply_by_context": lambda self, g: False})()
    assert r._should_reply(_msg("小彩你好")) is False


def test_no_name_falls_to_probability():
    # 无名字 → 由 should_reply_by_context 概率决定（桩 False = 不会必回）
    assert _router()._should_reply(_msg("今天天气怎么样")) is False


def test_empty_text_safe():
    r = _router()
    assert r._should_reply(_msg("")) is False
