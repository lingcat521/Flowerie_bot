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
    sys.modules["pydantic"] = pyd
    sys.modules["pydantic_settings"] = ps
    sys.path.insert(0, ".")
    from src.services.prompt_builder import build_system_prompt

    class C:
        GLOBAL_STYLE_RULES = "【全局】"
        BOT_NICKNAME = "花璃"
        MAX_AI_INPUT_CHARS = 99999
        MAX_CONTEXT_CHARS = 99999
        PERSONA_ENABLED = True

    out = build_system_prompt(C(), None, "hi", "", None, 1, "", False,
                              group_style_rules="【群专属】")
    p = out[1] if isinstance(out, tuple) else out
    assert "【群专属】" in p
    assert "【全局】" not in p
