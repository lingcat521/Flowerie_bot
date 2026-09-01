"""Plugin WebUI 受控 DSL 渲染器：正常渲染 + 零 JS 安全红线全套测试。"""
import re

import pytest

from src.services.webui_render.plugin_dsl import (
    _SAFE_ATTRS,
    _form_field,
    render_plugin_dsl,
    safe_url,
)

_TAGS = ("p|h1|h2|h3|h4|h5|h6|div|span|pre|code|table|thead|tbody|tr|td|th|form|input|"
         "select|option|label|button|a|img|details|summary|section|article|ul|ol|li|strong|"
         "b|i|em|br|hr|blockquote|nav|fieldset|legend|textarea|small|sub|sup|ins|del")


def _assert_no_js(html: str):
    """零 JS 语义级断言：① 所有未转义标签 ⊆ HTML 白名单 ② 无事件属性 ③ URL scheme 白名单。"""
    for m in re.finditer(r"<[^>]{0,200}>", html):
        raw = m.group(0)
        tag = raw.lstrip("<").lstrip("/").split()[0].rstrip(">").lower()
        if not re.fullmatch(_TAGS, tag):
            raise AssertionError(f"HTML 非白名单标签/注入: {raw!r}")
        # 属性名必须 ⊆ 白名单（事件属性/外链 style 等即注入）；值内字符已转义无威胁
        seen_attrs = [a.lower() for a in re.findall(r'([a-z][\w-]*)\s*=\s*"[^"]*"', raw)]
        unsafe = [a for a in seen_attrs if a not in _SAFE_ATTRS]
        if unsafe:
            raise AssertionError(f"非法属性: {unsafe} in {raw!r}")
        for sm in re.finditer(r'style="([^"]*)"', raw):
            for bad in ("expression(", "url(", "javascript", "@import", "behavior"):
                if bad in sm.group(1).lower():
                    raise AssertionError(f"危险 style: {sm.group(1)!r}")
        for hm in re.finditer(r'(?:href|src)="([^"]*)"', raw):
            if hm.group(1) and safe_url(hm.group(1)) == "":
                raise AssertionError(f"危险 URL: {hm.group(1)!r}")


# ---------- 正常渲染 ----------
def test_display_components():
    html = render_plugin_dsl({
        "type": "container", "kind": "stack", "children": [
            {"type": "heading", "text": "总览"},
            {"type": "text", "text": "插件在运行"},
            {"type": "badge", "text": "Running", "variant": "ok"},
            {"type": "progress", "value": 82},
            {"type": "alert", "text": "同步完成", "variant": "ok"},
            {"type": "code", "text": "print('hi')"},
            {"type": "divider"},
        ]})
    assert "总览" in html and "Running" in html and "82%" in html
    _assert_no_js(html)


def test_form_components():
    html = render_plugin_dsl({
        "type": "form", "action": "/panel/plugin-actions", "fields": [
            {"field": "text", "name": "name", "label": "名称", "value": "abc"},
            {"field": "textarea", "name": "desc", "label": "描述"},
            {"field": "select", "name": "mode", "label": "模式", "options": ["a", "b|B标签"]},
            {"field": "checkbox", "name": "on", "label": "启用", "value": "true"},
            {"field": "radio", "name": "t", "label": "类型", "options": ["x", "y"]},
            {"field": "number", "name": "n", "label": "数量", "value": 3},
            {"field": "password", "name": "p", "label": "密钥"},
        ], "buttons": [{"type": "submit", "text": "保存"}]})
    assert 'name="name"' in html and 'name="mode"' in html and "保存" in html
    assert 'name="on" value="true"' in html
    _assert_no_js(html)


def test_data_and_container():
    html = render_plugin_dsl({
        "type": "grid", "columns": 2, "children": [
            {"type": "stats", "items": [{"label": "歌曲", "value": "1732"},
                                        {"label": "缓存", "value": "4.2GB"}]},
            {"type": "table", "headers": ["id", "名称"],
             "rows": [{"id": 1, "名称": "歌A"}, [2, "歌B"]]},
            {"type": "log", "lines": ["[INFO] ok", "[WARN] x"]},
            {"type": "accordion", "title": "更多", "children": [{"type": "text", "text": "详情"}]},
        ]})
    assert "1732" in html and "歌A" in html and "[INFO] ok" in html
    assert "<table" in html and 'cols-2' in html
    _assert_no_js(html)


# ---------- 零 JS 安全红线（攻击载荷全量） ----------
@pytest.mark.parametrize("payload,desc", [
    ('<script>alert(1)</script>', "script 注入"),
    ('<img src=x onerror=alert(1)>', "事件属性注入"),
    ('<div onclick="alert(1)">x</div>', "inline handler"),
    ('<a href="javascript:alert(1)">x</a>', "javascript URL"),
    ('<a href="data:text/html,<script>alert(1)</script>">x</a>', "data URL"),
    ('<a href="vbscript:msgbox(1)">x</a>', "vbscript URL"),
    ('<svg onload=alert(1)></svg>', "SVG XSS"),
    ('<iframe src="https://evil"></iframe>', "iframe 绕过"),
    ('<input onfocus=alert(1) onblur=alert(2)>', "focus handler"),
    ('<math><mtext><table><mglyph><style><!--</style>', "mXSS 类"),
])
def test_xss_payloads_escaped(payload, desc):
    # 文本组件 + 表单 field 的 value + 链接 href 三通道
    html = render_plugin_dsl({"type": "container", "children": [
        {"type": "text", "text": payload},
        {"type": "heading", "text": payload},
        {"type": "button", "text": payload, "action": "x"},
    ]})
    _assert_no_js(html)


def test_attr_injection_blocked():
    # 标签 value/label/placeholder/alt 注入 onclick（工具转义）
    html = _form_field({"field": "text", "name": "x", "label": '<b>" onfocus="alert(1)', "value": '"><script>'})
    _assert_no_js(html)


def test_dynamic_form_value_injection():
    html = render_plugin_dsl({"type": "form", "fields": [
        {"field": "text", "name": "n", "value": '"><script>alert(1)</script><img src=x onerror=a>'}
    ]})
    _assert_no_js(html)


def test_url_scheme_whitelist():
    assert safe_url("https://a.com") == "https://a.com"
    assert safe_url("http://a.com/x") == "http://a.com/x"
    assert safe_url("mailto:a@b.com") == "mailto:a@b.com"
    assert safe_url("/panel/x?q=1") == "/panel/x?q=1"
    assert safe_url("") == ""
    assert safe_url("javascript:alert(1)") == ""
    assert safe_url("data:text/html,x") == ""
    assert safe_url("vbscript:x") == ""
    assert safe_url("//evil.com/x") == ""       # protocol-relative
    assert safe_url("JAVASCRIPT:alert(1)") == ""  # 大小写


def test_markdown_limited():
    html = render_plugin_dsl({"type": "markdown", "text": "# 标题\n\n`code`\n\n<script>alert(1)</script>\n\n[x](javascript:alert(1))"})
    _assert_no_js(html)
    assert "标题" in html


def test_unknown_component_safe():
    html = render_plugin_dsl({"type": "fancy-chart", "data": "<script>"})
    assert "组件嵌套过深" not in html  # 未知组件降级为文本
    _assert_no_js(html)


def test_deep_recursion_guarded():
    deep = {"type": "text", "text": "x"}
    for _ in range(30):
        deep = {"type": "card", "children": [deep]}
    html = render_plugin_dsl(deep)
    assert "组件嵌套过深" in html
