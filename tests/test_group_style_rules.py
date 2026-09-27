"""群专属发言规则：按群覆盖全局规则 + 存储容错。"""
import pytest
from src.services.group_style_rules import GroupStyleRuleStore


def _store(tmp_path):
    return GroupStyleRuleStore(str(tmp_path / "rules.json"))


def test_set_get(tmp_path):
    st = _store(tmp_path)
    assert st.get(1) is None                    # 无配置回退全局
    st.set(786368680, "本群规则（每句≤8字）")
    assert st.get(786368680) == "本群规则（每句≤8字）"


def test_empty_removes(tmp_path):
    st = _store(tmp_path)
    st.set(1, "x")
    st.set(1, "   ")                            # 空白 → 删除（全局回退）
    assert st.get(1) is None


def test_truncate_oversize(tmp_path):
    st = _store(tmp_path)
    st.set(1, "a" * 5000)
    assert len(st.get(1)) == 2000


def test_prompt_priority():
    """群规则覆盖全局（注入链在 prompt_builder 层验证）。"""
    import sys
    import types
    pyd = types.ModuleType("pydantic")
    pyd.Field = lambda *a, **k: None
    pyd.field_validator = lambda *a, **k: (lambda f: f)
    pyd.BaseModel = type("BaseModel", (), {})
    ps = types.ModuleType("pydantic_settings")
    ps.BaseSettings = type("BaseSettings", (), {})
    ps.SettingsConfigDict = dict
    # 这两个替身必须在用例结束时**还原**：整套 pytest 同进程跑时，它们会污染后面所有
    # 真需要 pydantic 的用例（实测 CI Acceptance：tests/webui 全部 102 条 setup 阶段就
    # ImportError: cannot import name 'AliasChoices' from 'pydantic'）。
    _saved = {key: sys.modules.get(key) for key in ("pydantic", "pydantic_settings")}
    sys.modules["pydantic"] = pyd
    sys.modules["pydantic_settings"] = ps
    sys.path.insert(0, ".")
    try:
        _prompt_priority_body()
    finally:
        for _key, _value in _saved.items():
            if _value is None:
                sys.modules.pop(_key, None)
            else:
                sys.modules[_key] = _value


def _prompt_priority_body():
    from src.services.prompt_builder import build_system_prompt

    class C:
        BOT_NICKNAME = "花璃"
        MAX_AI_INPUT_CHARS = 99999
        MAX_CONTEXT_CHARS = 99999
        PERSONA_ENABLED = True

    out = build_system_prompt(C(), None, "hi", "", None, 1, "", False,
                              group_style_rules="【群专属】")
    p = out[1] if isinstance(out, tuple) else out
    assert "【群专属】" in p
    from src.services.prompt_builder import GLOBAL_STYLE_RULES
    assert GLOBAL_STYLE_RULES[:4] not in p  # 群规则覆盖内置默认


# ---------- 回归：群昵称 / 群风格注入（Phase 0 审计报告 §5 第 1 条） ----------
class _RecordingAI:
    """最小 AI 客户端桩：记录 chat_once 收到的 kwargs。"""

    _retryable = True
    _api_backoff = 0.0

    def __init__(self):
        self.kwargs = None

    async def chat_once(self, **kwargs):
        self.kwargs = kwargs
        return "回复", None


class _FakeBudget:
    def check(self, *a, **k):
        return True, "ok"


class _FakeNicknames:
    default = "花璃"

    def get(self, group_id, persona_id=None):
        return "小铃" if int(group_id) == 123 else self.default


class _FakeStyleRules:
    def get(self, group_id):
        return "（群规则：只聊猫）" if int(group_id) == 123 else None


class _FakePersona:
    """最小 persona provider：gateway 会调 resolve_persona_id 解析人设。"""

    def resolve_persona_id(self, group_id=None):
        return None


@pytest.mark.asyncio
async def test_guarded_chat_injects_group_identity_for_positional_call():
    """回归：群特色昵称 / 群专属发言规则注入曾判 `kwargs.get("group_id")`，而 group_id 是
    `guarded_chat` 的**位置参数** —— 于是生产链路（位置参数调用）里两个 if 恒假、功能从未生效。

    修复后：注入改用已回退到位置参数的 `_gid`；本用例用**位置参数**调用并断言
    `bot_nickname` / `default_nickname` / `group_style_rules` 真的传到了 AI 客户端。
    """
    from src.core.ai_gateway import AiGateway
    from tests.test_native_reply_tool import FakeConfig

    client = _RecordingAI()
    gateway = AiGateway(FakeConfig(), client, _FakeBudget(), prompt_manager=None,
                        tool_manager=None, persona_manager=lambda: None, meme_manager=None,
                        nicknames=lambda: _FakeNicknames(), style_rules=lambda: _FakeStyleRules())
    _reply, _mem, denied = await gateway.guarded_chat(123, 456, user_message="hi", context="ctx", persona_id="atri")
    assert denied is False
    assert client.kwargs["bot_nickname"] == "小铃"
    assert client.kwargs["default_nickname"] == "花璃"
    assert client.kwargs["group_style_rules"] == "（群规则：只聊猫）"
