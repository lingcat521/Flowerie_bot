"""群特色昵称 Prompt 注入（默认不注入/空不注入/换行清洗）。"""
from src.services.prompt_builder import build_system_prompt


class _Cfg:
    MAX_AI_INPUT_CHARS = 2000


class _Mem:
    def get_memory_context(self, *a, **k):
        return ""


def _prompt(**kw):
    base = dict(config=_Cfg(), memory_manager=_Mem(), user_message="hi", context="",
                user_id=1, group_id=100, custom_prompt="", is_mentioned=False)
    base.update(kw)
    _, sp = build_system_prompt(**base)
    return sp


def test_nickname_injected_when_differs():
    sp = _prompt(persona_text="你是花璃", bot_nickname="小彩", default_nickname="花璃")
    assert "本群专属称呼" in sp and "小彩" in sp


def test_nickname_not_injected_when_default():
    assert "本群专属称呼" not in _prompt(persona_text="你是花璃",
                                        bot_nickname="花璃", default_nickname="花璃")


def test_nickname_not_injected_when_empty():
    assert "本群专属称呼" not in _prompt(persona_text="你是花璃", bot_nickname="",
                                        default_nickname="花璃")


def test_nickname_newline_sanitized():
    head = _prompt(persona_text="p", bot_nickname="小\n彩", default_nickname="花璃")
    seg = head.split("本群专属称呼")[1][:14]
    assert "\n" not in seg
