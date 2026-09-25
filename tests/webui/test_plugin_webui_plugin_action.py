# -*- coding: utf-8 -*-
"""§10 WebUI → 插件动作 / §11 配置 round-trip / §15 RPC 五种结果 / §16 结构化错误 / §17 权限。

全部真链路：POST /panel/plugins/webui/{pid}/{page} → webui.action → 插件子进程 →（必要时）
Core Router → 另一个插件 → 回到页面。断言的是**页面里出现的东西**（黑盒），不是内部对象。

错误码来源（任务书 §16/§32 Gate J）：插件间调用由 Core 的 PluginCommError 给出结构化
code（PLUGIN_NOT_FOUND / METHOD_NOT_FOUND / TIMEOUT / PLUGIN_ERROR / PERMISSION_DENIED），
参考插件把 code 渲染进页面。**引擎自身**的失败（例如未批 webui.action）目前仍是页面级
中文文案、没有 code —— 这是本轮如实记录的限制（见 test_page_level_permission_is_text_only）。
"""
import json

import pytest

NOT_ECHOED = "（对端未回传）"


async def _call_sync(web, func, *args):
    """把引擎的同步 API（disable 等）放到服务器事件循环线程里执行，避免跨线程改状态。"""
    return func(*args)


def _disable(web, plugin_id):
    return web.call(_call_sync(web, web.manager.disable, plugin_id))


def _post(web, page, action, **fields):
    data = {"plugin_action": action}
    data.update(fields)
    return web.post(web.page_url(web.plugin_a, page), data=data)


def _json_of(web, text, elem_id):
    raw = web.element_text(text, elem_id)
    try:
        return json.loads(raw)
    except ValueError:
        return None


@pytest.fixture
def restore_settings(web):
    yield
    _post(web, "settings", "save", name="Flowerie", number="123", enabled="1", mode="auto")


# ---------------------------------------------------------------- §10 WebUI → 插件动作

def test_action_get_info(web):
    resp = _post(web, "index", "get_info")
    assert resp.status == 200, resp.status
    payload = _json_of(web, resp.text, "self-test-result")
    assert isinstance(payload, dict) and payload.get("plugin_id") == web.plugin_a, payload
    assert payload.get("runtime") == "python", payload
    assert payload.get("sdk_version"), payload
    assert "get_info" in resp.text


def test_action_echo(web):
    resp = _post(web, "index", "echo", echo_text="hello-webui-action")
    assert resp.status == 200, resp.status
    payload = _json_of(web, resp.text, "self-test-result")
    assert isinstance(payload, dict), payload
    assert "hello-webui-action" in json.dumps(payload, ensure_ascii=False), payload


def test_action_set_config(web):
    resp = _post(web, "index", "set_config", echo_text="set-config-probe")
    assert resp.status == 200, resp.status
    payload = _json_of(web, resp.text, "self-test-result")
    assert isinstance(payload, dict), payload
    assert payload.get("ok") is True, payload
    assert "self_test" in (payload.get("keys") or []), payload


def test_settings_config_round_trip(web, restore_settings):
    """§11：WebUI 写 → 插件落盘 → 重新打开页面读回**同样的值**。"""
    resp = _post(web, "settings", "save", name="RoundTrip-A", number="4242",
                 enabled="1", mode="manual")
    assert resp.status == 200, resp.status
    assert "设置已保存" in resp.text, resp.text[:300]
    assert web.element_text(resp.text, "setting-name") == "RoundTrip-A"
    assert web.element_text(resp.text, "setting-number") == "4242"
    assert web.element_text(resp.text, "setting-mode") == "manual"

    readback = web.get(web.page_url(web.plugin_a, "settings")).text
    assert web.element_text(readback, "setting-name") == "RoundTrip-A", "重新打开后 name 不一致"
    assert web.element_text(readback, "setting-number") == "4242", "重新打开后 number 不一致"
    assert web.element_text(readback, "setting-mode") == "manual", "重新打开后 mode 不一致"
    stored = _json_of(web, readback, "storage-json")
    assert isinstance(stored, dict), stored
    assert (stored.get("values") or {}).get("name") == "RoundTrip-A", stored


def test_settings_round_trip_negative_and_checkbox(web, restore_settings):
    resp = _post(web, "settings", "save", name="Neg", number="-17", enabled="0", mode="debug")
    assert resp.status == 200
    readback = web.get(web.page_url(web.plugin_a, "settings")).text
    assert web.element_text(readback, "setting-number") == "-17"
    assert web.element_text(readback, "setting-enabled") in ("关闭", "false", "False", "off")


# ---------------------------------------------------------------- §15/§16/§17 结构化错误

def _comm(web, **fields):
    return _post(web, "communication", "call", **fields)


def _code_status(web, text):
    return (web.element_text(text, "call-code").replace("Code:", "").strip(),
            web.element_text(text, "call-status").replace("Status:", "").strip())


@pytest.mark.parametrize("case,expected", (
    ("plugin_not_found", "PLUGIN_NOT_FOUND"),
    ("method_not_found", "METHOD_NOT_FOUND"),
    ("timeout", "TIMEOUT"),
    ("plugin_error", "PLUGIN_ERROR"),
))
def test_structured_error_codes(web, case, expected):
    """§16：插件侧失败必须是结构化 code（不是 500、不是裸堆栈）。"""
    if case == "plugin_not_found":
        resp = _comm(web, target="no_such_plugin_xyz", method="ping", params="{}",
                     timeout_ms="2000", route="core")
    elif case == "method_not_found":
        resp = _comm(web, target=web.plugin_b, method="no_such_method", params="{}",
                     timeout_ms="2000", route="core")
    elif case == "timeout":
        resp = _comm(web, target=web.plugin_b, method="slow", params="{}",
                     timeout_ms="200", route="core")
    else:
        resp = _comm(web, target=web.plugin_b, method="boom", params="{}",
                     timeout_ms="2000", route="core")
    assert resp.status == 200, "插件错误变成了 HTTP %s" % resp.status
    code, status = _code_status(web, resp.text)
    assert status == "Failed", "页面没有显示 Failed：%r" % status
    assert code == expected, "期望 %s，页面显示 %r（响应：%s）" % (expected, code, resp.text[:300])
    assert "Traceback" not in resp.text


def test_permission_denied_is_structured(web):
    """§17：撤销 plugin.call.* 权限后，页面必须显示 PERMISSION_DENIED（不能绕过权限门）。"""
    plugin_id = "plugin_webui_denied"
    web.deploy_variant(web.src_a, plugin_id, permissions=["web_ui", "read_message"])
    try:
        resp = web.post(web.page_url(plugin_id, "communication"),
                        data={"plugin_action": "call", "target": web.plugin_b, "method": "ping",
                              "params": "{}", "timeout_ms": "2000", "route": "core"})
        assert resp.status == 200, resp.status
        code, status = _code_status(web, resp.text)
        assert status == "Failed", status
        assert code == "PERMISSION_DENIED", "期望 PERMISSION_DENIED，实际 %r" % code
    finally:
        ok, why = _disable(web, plugin_id)
        assert ok, why


def test_allowed_call_passes_with_permission(web):
    """§17 的另一半：权限在 → 同一个调用 PASS（对照 PERMISSION_DENIED）。"""
    resp = _comm(web, target=web.plugin_b, method="ping", params="{}",
                 timeout_ms="2000", route="core")
    code, status = _code_status(web, resp.text)
    assert status == "OK" and code in ("", "—"), (status, code)


def test_unknown_action_is_reported_without_500(web):
    """已知限制（如实记录）：引擎**页面级**的失败目前只有中文文案，没有结构化 code。"""
    resp = _post(web, "communication", "definitely_not_an_action")
    assert resp.status == 200, resp.status
    assert "未知动作" in resp.text or "Failed" in resp.text, resp.text[:300]
    assert "Traceback" not in resp.text


def test_page_level_permission_is_text_only(web):
    """已知限制：未批 webui.action 时引擎回的是页面级中文文案（无 code）——本轮不改引擎，只记录。"""
    plugin_id = "plugin_webui_viewonly"
    web.deploy_variant(web.src_a, plugin_id, permissions=["web_ui", "webui.view", "webui.action"])
    try:
        ok, why = web.call(web.manager.enable(plugin_id, approved_permissions=["webui.view"]))
        assert ok, why
        resp = web.post(web.page_url(plugin_id, "settings"),
                        data={"plugin_action": "save", "name": "x"})
        assert resp.status == 200, resp.status
        assert "权限" in resp.text, "未批准 webui.action 时没有给出权限提示：%s" % resp.text[:300]
        assert "Traceback" not in resp.text
    finally:
        _disable(web, plugin_id)
