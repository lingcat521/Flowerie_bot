# -*- coding: utf-8 -*-
"""§18 路径穿越 / §20 Secret 泄漏 / §21 XSS + 模板注入 —— 全部打在真服务器上。

路径用例用 http.client **原样发送** Request-URI（不经任何客户端的路径归一化），
所以 %2e%2e%2f、双重编码、反斜杠这些形态是真正到达引擎的原始字节。
"""
import os
import re

import pytest

from tests.webui.conftest import SECRETS, TRAVERSAL_PATHS  # 绝对导入：避免与 tests/e2e/conftest.py 撞名（整套 pytest 同跑时）

MANIFEST_MARKERS = ('"id"', '"runtime"', '"web_ui"', "plugin_webui_test")
PASSWD_MARKERS = ("root:x:0:0", "root:*)", "/bin/sh")

XSS_PAYLOADS = (
    "<script>alert(1)</script>",
    '<img src=x onerror=alert(1)>',
)


def _leaked(text):
    """响应里是否出现被测文件的内容特征（说明穿越成功）。"""
    return [m for m in MANIFEST_MARKERS + PASSWD_MARKERS if m in text]


@pytest.mark.parametrize("probe", TRAVERSAL_PATHS + ("../manifest.json", "../../main.py"))
def test_static_path_traversal_rejected(web, probe):
    resp = web.get(web.static_url(web.plugin_a, probe))
    assert resp.status != 200 or not _leaked(resp.text), \
        "路径穿越成功（%s）：HTTP %s %s" % (probe, resp.status, resp.text[:200])
    assert not _leaked(resp.text), "响应泄露了插件目录外的文件内容：%s" % probe


@pytest.mark.parametrize("probe", TRAVERSAL_PATHS + ("../plugin.py",))
def test_asset_path_traversal_rejected(web, probe):
    resp = web.get(web.asset_url(web.plugin_a, probe))
    assert resp.status != 200 or not _leaked(resp.text), \
        "asset 通道穿越成功（%s）：HTTP %s" % (probe, resp.status)


@pytest.mark.parametrize("probe", TRAVERSAL_PATHS + ("../manifest.json",))
def test_files_download_traversal_rejected(web, probe):
    resp = web.get(web.file_url(web.plugin_a, probe))
    assert resp.status != 200 or not _leaked(resp.text), \
        "下载通道穿越成功（%s）：HTTP %s" % (probe, resp.status)


def test_absolute_path_rejected(web):
    for probe in ("/etc/passwd", "/etc/hostname", "//etc/passwd"):
        resp = web.get("/panel/plugins/webui/%s/static%s" % (web.plugin_a, probe))
        assert not _leaked(resp.text), "绝对路径被读出：%s → %s" % (probe, resp.text[:120])


def test_symlink_escape_rejected(web):
    """符号链接逃逸：插件 static 目录里放一个指向 /etc/passwd 的软链，必须 404。"""
    static_dir = os.path.join(web.deployed[web.plugin_a], "webui", "static")
    link = os.path.join(static_dir, "escape.css")
    if os.path.lexists(link):
        os.remove(link)
    try:
        os.symlink("/etc/passwd", link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip("BLOCKED BY FILESYSTEM：本机文件系统不支持符号链接（%s）" % exc)
    try:
        resp = web.get(web.static_url(web.plugin_a, "escape.css"))
        assert resp.status == 404, "符号链接逃逸成功：HTTP %s" % resp.status
        assert not _leaked(resp.text)
    finally:
        os.remove(link)


def test_secret_values_never_leak(web):
    """§20：HTML / CSS / JSON / 错误响应里都不得出现 TEST_SECRET / TEST_API_KEY / TEST_TOKEN。"""
    probes = [
        web.page_url(web.plugin_a, "index"),
        web.page_url(web.plugin_a, "settings"),
        web.page_url(web.plugin_a, "communication"),
        web.static_url(web.plugin_a, "style.css"),
        web.asset_url(web.plugin_a, "theme.css"),
        web.asset_url(web.plugin_a, "info.json"),
        web.asset_url(web.plugin_a, "logo.txt"),
        web.page_url(web.plugin_a, "missing_page_for_error"),
        "/panel?tab=plugins",
        web.static_url(web.plugin_a, "..%2fmanifest.json"),
    ]
    leaks = []
    for path in probes:
        resp = web.get(path)
        for name, value in SECRETS.items():
            if value in resp.text:
                leaks.append("%s @ %s" % (name, path))
    assert not leaks, "Secret 泄漏到 WebUI 响应：%s" % leaks


@pytest.fixture
def restore_settings(web):
    yield
    web.post(web.page_url(web.plugin_a, "settings"),
             data={"plugin_action": "save", "name": "Flowerie", "number": "123",
                   "enabled": "1", "mode": "auto"})


@pytest.mark.parametrize("payload", XSS_PAYLOADS)
def test_xss_payload_is_escaped_on_render(web, restore_settings, payload):
    resp = web.post(web.page_url(web.plugin_a, "settings"),
                    data={"plugin_action": "save", "name": payload, "number": "1",
                          "enabled": "1", "mode": "auto"})
    assert resp.status == 200, resp.status
    text = resp.text
    assert "<script" not in text.lower(), "XSS 负载原样回显（可执行 <script）"
    handlers = web.live_event_handlers(text)
    assert not handlers, "响应里存在存活的内联事件属性：%s" % handlers[:2]
    assert "&lt;script&gt;" in text or "&lt;img" in text, "负载没有被转义显示"
    raw = web.element_html(text, "setting-name")      # 原始（未反转义）元素内容
    assert "<script>" not in raw and "<img" not in raw, "读回值未转义：%r" % raw
    assert "&lt;" in raw, "读回值不是转义后的形态：%r" % raw


@pytest.mark.parametrize("payload", XSS_PAYLOADS)
def test_xss_payload_is_escaped_on_readback(web, restore_settings, payload):
    web.post(web.page_url(web.plugin_a, "settings"),
             data={"plugin_action": "save", "name": payload, "number": "1",
                   "enabled": "1", "mode": "auto"})
    text = web.get(web.page_url(web.plugin_a, "settings")).text
    assert "<script" not in text.lower(), "重新打开页面时负载变成真 <script 标签"
    handlers = web.live_event_handlers(text)
    assert not handlers, "重新打开页面时负载变成真事件属性：%s" % handlers[:2]
    assert "&lt;" in text, "转义后的负载没有出现在读回页面"


def test_html_injection_in_communication_params(web):
    """把注入负载放进 plugin.call 的 params：只允许出现在转义后的 JSON 里。"""
    payload = '<script>alert(1)</script><img src=x onerror=alert(1)>'
    resp = web.post(web.page_url(web.plugin_a, "communication"),
                    data={"plugin_action": "call", "target": web.plugin_a, "method": "echo",
                          "params": '{"text": "%s"}' % payload.replace('"', '\\"'),
                          "route": "core", "timeout_ms": "5000"})
    assert resp.status == 200, resp.status
    text = resp.text
    assert "<script" not in text.lower(), "communication 页出现可执行脚本"
    handlers = web.live_event_handlers(text)
    assert not handlers, "communication 页出现存活的事件属性：%s" % handlers[:2]
    assert "&lt;img" in text or "&lt;script" in text, "注入负载没有以转义形态出现"


def test_template_injection_is_not_evaluated(web, restore_settings):
    """模板注入：{{ ... }} 只能作为**字面量**出现在页面上，绝不被二次求值。"""
    marker = "{{ 6*7 }}"
    web.post(web.page_url(web.plugin_a, "settings"),
             data={"plugin_action": "save", "name": marker, "number": "1",
                   "enabled": "1", "mode": "auto"})
    text = web.get(web.page_url(web.plugin_a, "settings")).text
    shown = web.element_text(text, "setting-name")
    assert marker in shown, "字面量没有原样显示：%r" % shown
    assert "42" not in shown, "模板表达式被求值了：%r" % shown


def test_error_response_has_no_stack_or_path(web):
    payloads = (
        {"plugin_action": "call", "target": "no_such_plugin_xyz", "method": "ping",
         "params": "{}", "timeout_ms": "1000"},
        {"plugin_action": "call", "target": web.plugin_a, "method": "no_such_method",
         "params": "{}", "timeout_ms": "1000"},
        {"plugin_action": "call", "target": web.plugin_a, "method": "boom", "params": "{}",
         "timeout_ms": "1000"},
        {"plugin_action": "call", "target": web.plugin_a, "method": "echo", "params": "not-json",
         "timeout_ms": "1000"},
    )
    for data in payloads:
        resp = web.post(web.page_url(web.plugin_a, "communication"), data=data)
        assert resp.status == 200, "插件错误不该变成 HTTP %s" % resp.status
        text = resp.text
        assert "Traceback" not in text, "错误响应里出现堆栈：%s" % text[:200]
        assert web.plugin_dir not in text and "/storage/emulated/0" not in text, "错误响应泄露路径"
        assert not re.search(r'File "[^"]+", line \d+', text), "错误响应里出现调用栈帧"
