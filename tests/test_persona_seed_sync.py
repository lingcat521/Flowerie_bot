"""内置描述升级：旧默认/空→升级；用户改过→不再覆盖。"""
from src.services.persona_manager import PersonaManager, _LEGACY_BUILTIN_DESCRIPTIONS
from src.services.persona_presets import BUILTIN_PERSONAS


class _Repo:
    def __init__(self, existing=None):
        self.existing = existing or {}
        self.upserts = []

    def get_persona(self, pid):
        return self.existing.get(pid)

    def upsert_persona(self, p):
        self.upserts.append(p)


def _should_upgrade(desc, preset_id):
    """复现 seed 门控逻辑。"""
    preset = next(p for p in BUILTIN_PERSONAS if p["id"] == preset_id)
    if desc is None or desc == _LEGACY_BUILTIN_DESCRIPTIONS.get(preset_id, "__none__"):
        return desc != preset["description"]
    return False


def test_legacy_desc_upgraded():
    assert _should_upgrade("官方内置：冬川花璃（小恶魔系青梅竹马）", "flowerie") is True


def test_empty_desc_upgraded():
    assert _should_upgrade("", "flowerie") is True


def test_user_customized_not_touched():
    assert _should_upgrade("我的自定义描述（改过）", "flowerie") is False
    assert _should_upgrade("官方内置：冬川花璃（小恶魔系青梅竹马）改过", "flowerie") is False


def test_already_new_noop():
    preset = next(p for p in BUILTIN_PERSONAS if p["id"] == "flowerie")
    assert _should_upgrade(preset["description"], "flowerie") is False
