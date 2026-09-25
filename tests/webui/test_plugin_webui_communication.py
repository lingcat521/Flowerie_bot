# -*- coding: utf-8 -*-
"""§12 Plugin WebUI → Plugin-to-Plugin / §14 WebUI 与 Event / §15 WebUI → RPC → WebUI。

这是本轮最重要的链路（任务书 §12）：Browser → 插件 A WebUI → A 进程 → Core Router →
插件 B 进程 → 回 A 页面 → Browser。全程真进程、真 HTTP、真路由器，没有 Fake 任何东西。

页面（examples/plugin-webui-test/webui/pages/communication.html）显示的字段：
source / target / method / route / request_id / trace_id / kind / delivered / response，
对端不回传 id 时如实显示「（对端未回传）」——测试同时断言**不编造**。
"""
import json
import uuid

import pytest

NOT_ECHOED = "（对端未回传）"

#: 给「事件被另一个插件进程收到」加订阅的附加源码（真 SDK API：api.plugin.on / expose）。
#: 只用于测试部署的对端变体，不改仓库里的示例插件。
BUS_SUBSCRIBER = '''

# ---- tests/webui：订阅事件总线（真 SDK API plugin.on / expose），并提供一个「让对端广播」的方法 ----
_BUS_EVENTS = []


def _bus_probe(event, api=None):
    _BUS_EVENTS.append(event if isinstance(event, dict) else {})
    del _BUS_EVENTS[:-10]
    return {"ok": True}


def _bus_emit_back(request=None, api=None):
    params = (request or {}).get("params") if isinstance(request, dict) else {}
    message = params.get("message") if isinstance(params, dict) else ""
    return api.plugin.emit("test.event", {"message": message or "emit-back"})


_ORIGINAL_ON_STARTUP = on_startup


def on_startup(context, api=None):        # noqa: F811 - 覆盖以追加订阅
    result = _ORIGINAL_ON_STARTUP(context, api)
    if api is not None:
        api.plugin.on("*", _bus_probe)
        api.plugin.expose("bus_seen", lambda request=None: {"events": list(_BUS_EVENTS)})
        api.plugin.expose("emit_back", lambda request=None: _bus_emit_back(request, api))
    return result
'''



@pytest.fixture(scope="module")
def subscriber(web):
    """对端变体：真插件进程 + 只追加了 plugin.on("*") 订阅与 bus_seen/emit_back 两个方法。"""
    plugin_id = web.plugin_b + "_sub"
    web.deploy_variant(web.src_b, plugin_id,
                       permissions=["web_ui", "read_message", "plugin.call.*", "plugin.emit"],
                       extra_entry=BUS_SUBSCRIBER)
    return plugin_id


def _comm(web, action="call", **fields):
    data = {"plugin_action": action}
    data.update(fields)
    return web.post(web.page_url(web.plugin_a, "communication"), data=data)


def _fields(web, text):
    return {
        "status": web.element_text(text, "call-status").replace("Status:", "").strip(),
        "code": web.element_text(text, "call-code").replace("Code:", "").strip(),
        "source": web.element_text(text, "call-source"),
        "target": web.element_text(text, "call-target"),
        "method": web.element_text(text, "call-method"),
        "route": web.element_text(text, "call-route"),
        "request_id": web.element_text(text, "call-request-id"),
        "trace_id": web.element_text(text, "call-trace-id"),
        "kind": web.element_text(text, "call-kind"),
        "delivery": web.element_text(text, "call-delivery"),
        "response": web.element_text(text, "call-response"),
        "request": web.element_text(text, "call-request"),
        "message": web.element_text(text, "call-message"),
    }


def test_self_call_echo_shows_engine_ids_and_result(web):
    """WebUI → RPC → WebUI 闭环：引擎给的 request_id / trace_id / route 原样回到页面。"""
    resp = _comm(web, target=web.plugin_a, method="echo", params='{"text": "hello-self-call"}',
                 timeout_ms="5000", route="core")
    assert resp.status == 200, resp.status
    got = _fields(web, resp.text)
    assert got["status"] == "OK", got
    assert got["source"] == web.plugin_a and got["target"] == web.plugin_a, got
    assert got["method"] == "echo", got
    assert got["route"] == "core", got
    assert got["request_id"] not in ("", NOT_ECHOED) and len(got["request_id"]) >= 8, got
    assert got["trace_id"] not in ("", NOT_ECHOED) and len(got["trace_id"]) >= 8, got
    assert got["request_id"] in got["response"], "request_id 没有随响应回到页面"
    assert got["trace_id"] in got["response"], "trace_id 没有随响应回到页面"
    assert "hello-self-call" in got["response"], got


def test_cross_plugin_call_returns_peer_result(web):
    """A 的 WebUI → Core → B 进程 → 结果回到 A 的页面（§12 的核心断言）。"""
    marker = "hello-peer-%s" % uuid.uuid4().hex[:8]
    resp = _comm(web, target=web.plugin_b, method="echo",
                 params=json.dumps({"text": marker}), timeout_ms="5000", route="core")
    assert resp.status == 200, resp.status
    got = _fields(web, resp.text)
    assert got["status"] == "OK", got
    assert got["source"] == web.plugin_a, got
    assert got["target"] == web.plugin_b, got
    assert got["method"] == "echo", got
    assert got["route"] == "core", got
    assert marker in got["response"], "对端结果没有回到页面：%s" % got["response"][:300]
    assert marker in got["request"], "请求 JSON 里没有本次调用的参数"


def test_cross_plugin_ping_and_get_info(web):
    resp = _comm(web, target=web.plugin_b, method="ping", params="{}",
                 timeout_ms="5000", route="core")
    got = _fields(web, resp.text)
    assert got["status"] == "OK", got
    assert "minimal-py" in got["response"], got["response"][:300]

    resp = _comm(web, target=web.plugin_b, method="get_info", params="{}",
                 timeout_ms="5000", route="core")
    got = _fields(web, resp.text)
    assert got["status"] == "OK", got
    assert web.plugin_b in got["response"], got["response"][:300]
    assert "python" in got["response"], got["response"][:300]


def test_missing_target_is_structured_and_not_fabricated(web):
    """失败时：结构化 PLUGIN_NOT_FOUND + 不编造 request_id/trace_id。"""
    resp = _comm(web, target="no_such_plugin_xyz", method="ping", params="{}",
                 timeout_ms="2000", route="core")
    got = _fields(web, resp.text)
    assert got["status"] == "Failed", got
    assert got["code"] == "PLUGIN_NOT_FOUND", got
    assert got["request_id"] == NOT_ECHOED, "对端没回传却编造了 request_id：%r" % got["request_id"]
    assert got["trace_id"] == NOT_ECHOED, "对端没回传却编造了 trace_id：%r" % got["trace_id"]


def test_emit_event_is_delivered_to_other_plugin(web, subscriber):
    """§14 去程：WebUI 表单 → A.emit → Core 广播 → 对端**进程**收到（用它自己的收件记录证明）。"""
    marker = "hello-event-%s" % uuid.uuid4().hex[:8]
    resp = _comm(web, action="emit", target=subscriber, method="test.event",
                 params=json.dumps({"message": marker}), timeout_ms="5000")
    assert resp.status == 200, resp.status
    got = _fields(web, resp.text)
    assert got["status"] == "OK", got
    assert got["kind"] == "emit", got
    delivered = 0
    for part in got["delivery"].split():
        if part.startswith("delivered="):
            delivered = int(part.split("=", 1)[1] or 0)
    assert delivered >= 1, "广播没有投递给任何插件：%r" % got["delivery"]

    seen = _fields(web, _comm(web, target=subscriber, method="bus_seen", params="{}",
                              timeout_ms="5000", route="core").text)
    assert seen["status"] == "OK", seen
    assert marker in seen["response"], "对端进程没有收到广播事件：%s" % seen["response"][:400]


def test_event_received_is_shown_on_webui(web, subscriber):
    """§14 回程：对端 emit → Core → A 订阅收到 → A 的页面显示事件（source/event/payload/时间戳）。"""
    marker = "event-back-%s" % uuid.uuid4().hex[:8]
    resp = _comm(web, target=subscriber, method="emit_back",
                 params=json.dumps({"message": marker}), timeout_ms="5000", route="core")
    got = _fields(web, resp.text)
    assert got["status"] == "OK", got

    page = web.get(web.page_url(web.plugin_a, "communication")).text
    events = web.element_text(page, "event-log")
    assert marker in events, "A 的页面事件日志里没有收到的事件：%s" % events[:300]
    assert "test.event" in events, events[:300]
    assert subscriber in events, "事件日志里没有 source（应为对端插件 id）：%s" % events[:300]
    assert "received_at" in events, "事件日志里没有时间戳：%s" % events[:300]
    assert web.element_text(page, "event-count") not in ("", "0"), "event-count 没有增长"


def test_emit_and_call_keep_kind_and_delivery(web):
    resp = _comm(web, target=web.plugin_b, method="ping", params="{}", timeout_ms="5000")
    assert _fields(web, resp.text)["kind"] == "call"
    resp = _comm(web, action="emit", target=web.plugin_b, method="test.event", params="{}",
                 timeout_ms="5000")
    assert _fields(web, resp.text)["kind"] == "emit"


def test_route_policy_core_is_reported(web):
    resp = _comm(web, target=web.plugin_b, method="ping", params="{}",
                 timeout_ms="5000", route="core")
    got = _fields(web, resp.text)
    assert got["status"] == "OK", got
    assert got["route"] == "core", got


def test_route_auto_resolves_to_core_engine_side(web):
    """route=auto 时引擎实际走 core（一个插件一个进程，跨插件只能经 Core）。

    证据来自对端**回传的引擎字段**：自调用 echo 会把引擎 request 里的 route 原样回传。
    """
    resp = _comm(web, target=web.plugin_a, method="echo", params='{"text": "route-probe"}',
                 timeout_ms="5000", route="auto")
    got = _fields(web, resp.text)
    assert got["status"] == "OK", got
    assert got["route"] == "core", "引擎把 auto 解析成了 %r（跨进程应回落 core）" % got["route"]
