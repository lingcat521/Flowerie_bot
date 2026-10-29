"""v2.16.0 自动化 tab 测试：键迁移 / 渲染 / 过滤。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.config_schema import SCHEMA  # noqa: E402
from src.services.webui_panels.automation_panel import (  # noqa: E402
    AUTOMATION_KEYS,
    AutomationPanelMixin,
)
from src.services.webui_render.category_constants import (  # noqa: E402
    CATEGORY_LABELS,
    CATEGORY_ORDER,
)


_EXPECTED = (
    "AI_QZONE_ENABLED", "AI_QZONE_MAX_PER_DAY",
    "AI_QZONE_AUTO_ENABLED", "AI_QZONE_AUTO_INTERVAL_HOURS",
    "AI_ADMIN_ENABLED", "AI_MEMORY_ENABLED", "AI_TOOL_PROMPT",
    "QZONE_IMAGE_DIR", "QZONE_IMAGE_INDEX_PATH",
    "QZONE_IMAGE_MAX", "QZONE_IMAGE_DESCRIBE_LIMIT",
    "QZONE_ENABLED", "QZONE_DEFAULT_UGC_RIGHT",
    "QZONE_HISTORY_PATH", "QZONE_MAX_HISTORY",
)


def test_automation_keys_match_expected():
    """SCHEMA 中 Automation 分类恰好是这 15 键（防漂移）。"""
    in_schema = sorted(k for k, v in SCHEMA.items() if v[0] == "Automation")
    assert in_schema == sorted(_EXPECTED)
    assert set(AUTOMATION_KEYS) == set(_EXPECTED)


def test_automation_not_in_config_page_order():
    """Automation 不在配置页展示（专属 tab，同 Plugin/Persona 模式）。"""
    assert "Automation" not in CATEGORY_ORDER
    assert CATEGORY_LABELS["Automation"] == "自动化"


def test_moved_keys_left_old_categories():
    """Qzone 分类应清空；Admin 只剩群管三键。"""
    assert not [k for k, v in SCHEMA.items() if v[0] == "Qzone"]
    remaining = sorted(k for k, v in SCHEMA.items() if v[0] == "Admin")
    assert remaining == ["ADMIN_COMMANDS_ENABLED", "ADMIN_CONSOLE_ENABLED", "ADMIN_ROLE_CACHE_SECONDS"]


def test_automation_render_and_filter():
    """渲染本页键 + 过滤非本页键。"""
    class FakeSvc:
        def list_configs(self):
            return [
                {"key": "AI_QZONE_ENABLED", "type": "bool", "current": "true",
                 "description": "AI 可自主发表", "hot_reload": True},
                {"key": "QZONE_IMAGE_DIR", "type": "str", "current": "./data/qzone_images",
                 "description": "配图池目录", "hot_reload": True},
                {"key": "AI_SEARCH_ENABLED", "type": "bool", "current": "false",
                 "description": "搜索开关", "hot_reload": True},
            ]

    class FakeServer(AutomationPanelMixin):
        def __init__(self):
            self.config_service = FakeSvc()
    html = FakeServer()._render_automation_page()
    assert "自动化" in html and "AI_QZONE_ENABLED" in html
    assert "checked" in html
    assert "./data/qzone_images" in html
    assert "/panel/automation/save" in html
    assert "AI_SEARCH_ENABLED" not in html


def test_automation_keys_in_schema():
    """自动化键全部在 SCHEMA（保存路径依赖 update_many 校验）。"""
    for k in AUTOMATION_KEYS:
        assert SCHEMA.get(k) is not None, k
