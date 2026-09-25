"""群专属发言规则：按群覆盖全局规则 + 存储容错。"""
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
