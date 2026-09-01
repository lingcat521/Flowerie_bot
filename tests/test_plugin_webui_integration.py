"""Plugin WebUI 集成：真插件加载 → hook 调用 → DSL → 渲染（零 JS 红线 + 注入负载）。"""
import importlib.util
import re
import sys
from pathlib import Path

import pytest

from src.services.webui_render.plugin_dsl import render_plugin_dsl

PLUGIN_DIR = Path(__file__).resolve().parent / "plugins/webui_example"


@pytest.fixture
def module():
    sys.path.insert(0, str(PLUGIN_DIR))
    spec = importlib.util.spec_from_file_location(
        "flowerie_plugin_webui_example", str(PLUGIN_DIR / "plugin.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["flowerie_plugin_webui_example"] = mod
    spec.loader.exec_module(mod)
    return mod


def _assert_no_js(html):
    for m in re.finditer(r"<[^>]{0,200}>", html):
        tag = m.group(0).lstrip("<").lstrip("/").split()[0].rstrip(">").lower()
        assert re.fullmatch(r"(p|h\d|div|span|pre|code|table|thead|tbody|tr|td|th|form|input|"
                            r"select|option|label|button|a|img|details|summary|section|article|"
                            r"ul|ol|li|strong|b|i|em|br|hr|blockquote|nav|fieldset|legend|"
                            r"textarea|small|sub|sup|ins|del)", tag), tag
    assert "<script" not in html.lower()
    assert re.search(r'\son\w+\s*=\s*"', html.lower(), re.S) is None or "<" not in html.lower()


def test_hook_returns_dsl_and_renders(module):
    dsl = module.webui_page("home", "get", {}, {})
    assert isinstance(dsl, dict) and dsl["type"] == "container"
    html = render_plugin_dsl(dsl)
    assert "示例插件总览" in html and "开始任务" in html
    _assert_no_js(html)


def test_hook_pages(module):
    dsl = module.webui_page("tasks", "get", {}, {})
    html = render_plugin_dsl(dsl)
    assert "同步歌单" in html
    _assert_no_js(html)


def test_action_flow(module):
    """动作：button action -> webui_page(action=...) 返回新状态 DSL。"""
    dsl = module.webui_page("home", "start", {}, {})
    html = render_plugin_dsl(dsl)
    _assert_no_js(html)


def test_malicious_dsl_from_plugin_rendered_safe(module):
    """插件恶意返回注入负载 → 渲染器必须全部吸收（零 JS 证明）。"""
    evil = {"type": "container", "children": [
        {"type": "text", "text": "<script>alert(1)</script>"},
        {"type": "form", "fields": [
            {"field": "text", "name": "x", "value": '"><img src=x onerror=alert(1)>'}],
         "buttons": [{"type": "submit", "text": '<b onclick="alert(1)">go</b>'}]},
        {"type": "link", "text": "x", "href": "javascript:alert(1)"},
        {"type": "link", "text": "y", "href": "data:text/html,<script>alert(1)</script>"},
    ]}
    html = render_plugin_dsl(evil)
    assert "<script" not in html
    assert "javascript:" not in html or '<a' not in html
    _assert_no_js(html)
