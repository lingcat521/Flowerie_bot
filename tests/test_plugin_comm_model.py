"""Plugin-to-Plugin 通信模型测试（任务书《通信》§四–§二十三）。

这一层只验**模型**（不投递）：消息五分类、请求/响应/错误模型、语言无关数据类型、
Normalized DTO、循环保护、权限串、超时归一，以及"五种语言用的是同一套常量"。
真实跨进程投递在 tests/test_plugin_comm_bus.py 与 tests/test_plugin_comm_paths.py。
"""
import ast
import json
import math
import os

import pytest

from src.plugins import comm
from src.plugins.comm import PluginCommError
from src.plugins.permissions import (
    call_permission_granted,
    emit_permission_granted,
    is_call_permission,
)
from src.plugins.protocol import OPTIONAL_METHODS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(ROOT, "src/plugins/runner/python_runner.py")


def _runner_constants():
    tree = ast.parse(open(RUNNER, encoding="utf-8").read())
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    found[target.id] = ast.literal_eval(node.value)
                except ValueError:
                    found[target.id] = ast.unparse(node.value)
    return found


# ---------------------------------------------------------------- §十 五类消息

def test_message_kinds_are_five_and_distinct():
    assert comm.MESSAGE_KINDS == ("CALL", "RESPONSE", "EVENT", "ERROR", "CANCEL")


@pytest.mark.parametrize("msg,kind", [
    ({"id": 1, "method": "plugin.call", "params": {}}, "CALL"),
    ({"id": 1, "result": {"ok": True, "result": {}}}, "RESPONSE"),
    ({"id": 1, "method": "plugin.event", "params": {}}, "EVENT"),
    ({"id": 1, "result": {"ok": False, "error": {"code": "TIMEOUT"}}}, "ERROR"),
    ({"id": 1, "error": "未知方法"}, "ERROR"),
    ({"id": 1, "method": "plugin.cancel", "params": {}}, "CANCEL"),
    ({"id": 1, "method": "initialize", "params": {}}, "UNKNOWN"),
    ("not-a-dict", "UNKNOWN"),
])
def test_classify_message_maps_wire_lines(msg, kind):
    assert comm.classify_message(msg) == kind


def test_rpc_and_event_are_not_the_same_method():
    """§十：RPC 与 Event 必须是两种方法，不能一个方法兼两用。"""
    assert "plugin.call" in comm.PLUGIN_METHODS
    assert "plugin.event" in comm.PLUGIN_METHODS
    assert "plugin.call" != "plugin.event"


# ---------------------------------------------------------------- §六/§七 请求与响应

def test_request_model_has_every_required_field():
    req = comm.make_request("b.go", "get_status", {"x": 1},
                            source={"plugin_id": "a.py", "runtime": "python"},
                            timeout_ms=2500, trace_id="trace-1", hop_count=2)
    assert comm.validate_request(req) is None
    for key in ("request_id", "source", "target", "method", "params", "timeout", "metadata"):
        assert key in req, key
    assert req["target"]["plugin_id"] == "b.go"
    assert req["source"] == {"plugin_id": "a.py", "runtime": "python"}
    assert req["timeout"] == 2500 and req["trace_id"] == "trace-1" and req["hop_count"] == 2


@pytest.mark.parametrize("bad", [
    {}, {"request_id": "x"}, "not-a-dict",
])
def test_invalid_requests_are_rejected_with_structured_error(bad):
    err = comm.validate_request(bad)
    assert err is not None and err.code in comm.ERROR_CODES


def test_response_and_error_models():
    ok = comm.make_response("r1", {"n": 1})
    assert ok == {"request_id": "r1", "ok": True, "result": {"n": 1}}
    bad = comm.make_error_response("r2", PluginCommError.timeout("b.go", "get_status", 5000))
    assert bad["request_id"] == "r2" and bad["ok"] is False
    assert set(bad["error"]) == {"code", "message", "data"}
    assert bad["error"]["code"] == "TIMEOUT"


# ---------------------------------------------------------------- §二十一 错误模型

def test_error_codes_cover_task_book_verbatim():
    assert comm.CORE_ERROR_CODES == (
        "PLUGIN_NOT_FOUND", "PLUGIN_NOT_READY", "METHOD_NOT_FOUND", "PERMISSION_DENIED",
        "INVALID_ARGUMENT", "TIMEOUT", "CANCELLED", "SERIALIZATION_ERROR", "PLUGIN_ERROR",
        "INTERNAL_ERROR",
    )
    # §十七 生命周期要 PLUGIN_UNAVAILABLE，§二十二 环保护要 PLUGIN_CALL_LOOP
    assert comm.LIFECYCLE_ERROR_CODE in comm.ERROR_CODES
    assert comm.LOOP_ERROR_CODE in comm.ERROR_CODES
    assert len(comm.ERROR_CODES) == 12


def test_unknown_error_shapes_never_leak_raw_strings():
    assert PluginCommError.from_error("boom").code == "PLUGIN_ERROR"
    assert PluginCommError.from_error({"code": "NOT_A_CODE", "message": "x"}).code == "INTERNAL_ERROR"
    assert PluginCommError.from_error(None).code == "PLUGIN_ERROR"
    assert PluginCommError.from_error({"code": "TIMEOUT", "message": "慢"}).to_error() == {
        "code": "TIMEOUT", "message": "慢", "data": {}}


# ---------------------------------------------------------------- §十九 数据类型

def test_bytes_become_language_agnostic_reference():
    ref = comm.bytes_ref(b"\x00\x01hello", "application/octet-stream")
    assert comm.is_bytes_ref(ref) and ref["size"] == 7
    assert comm.decode_bytes_ref(ref) == b"\x00\x01hello"
    assert comm.sanitize_value({"data": b"abc"})["data"]["$bytes"] == "YWJj"


def test_language_internal_objects_are_refused_not_stringified():
    class PythonOnly:
        def __str__(self):
            return "看起来无害"

    err = comm.validate_value({"obj": PythonOnly()})
    assert err is not None and err.code == "SERIALIZATION_ERROR"
    with pytest.raises(PluginCommError) as ei:
        comm.sanitize_value(PythonOnly())
    assert ei.value.code == "SERIALIZATION_ERROR"
    assert "PythonOnly" in ei.value.message


def test_only_language_agnostic_types_survive():
    payload = {"n": None, "b": True, "i": 7, "f": 1.5, "s": "x", "a": [1, 2], "o": {"k": "v"},
               "t": (1, 2)}
    clean = comm.json_roundtrip(payload)
    assert clean == {"n": None, "b": True, "i": 7, "f": 1.5, "s": "x", "a": [1, 2],
                     "o": {"k": "v"}, "t": [1, 2]}


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_json_numbers_are_refused(bad):
    assert comm.validate_value(bad).code == "SERIALIZATION_ERROR"


def test_non_string_object_keys_are_refused():
    """Python 允许 {1: 'x'}，Java/Go 不允许 —— 边界处就要拦下，不能靠对面语言猜。"""
    assert comm.validate_value({1: "x"}).code == "SERIALIZATION_ERROR"


def test_value_type_names():
    assert comm.value_type(None) == "null" and comm.value_type(True) == "boolean"
    assert comm.value_type(3) == "integer" and comm.value_type(3.0) == "number"
    assert comm.value_type("s") == "string" and comm.value_type([]) == "array"
    assert comm.value_type({}) == "object" and comm.value_type(b"") == "bytes"
    assert comm.value_type(object()) == "object"   # 自定义类 -> 类型名，不属于 DATA_TYPES


# ---------------------------------------------------------------- §二十 Normalized DTO

def test_dto_shape_is_shared_across_languages():
    msg = comm.dto("message", message_id="m1", text="hi", segments=[{"type": "text"}])
    assert msg["type"] == "message" and msg["message_id"] == "m1"
    assert comm.is_dto(msg, "message") and not comm.is_dto(msg, "user")


def test_dto_refuses_unknown_fields():
    with pytest.raises(PluginCommError) as ei:
        comm.dto("user", user_id=1, nickname="n", 不存在的字段="x")
    assert ei.value.code == "INVALID_ARGUMENT"


def test_to_dto_converts_internal_objects_via_field_table():
    class Message:
        message_id = "m9"
        text = "hello"
        group_id = 42
        internal_cache = {"不该出现": True}

    out = comm.to_dto("message", Message())
    assert out == {"type": "message", "message_id": "m9", "group_id": 42, "text": "hello"}
    assert "internal_cache" not in out


def test_to_dto_refuses_objects_without_known_fields():
    with pytest.raises(PluginCommError) as ei:
        comm.to_dto("message", object())
    assert ei.value.code == "SERIALIZATION_ERROR"


# ---------------------------------------------------------------- §二十二/§二十三 trace 与 hop

def test_hop_count_protection():
    assert comm.next_hop(0) == 1 and comm.next_hop("3") == 4 and comm.next_hop(None) == 1
    assert not comm.hop_exceeded(comm.MAX_HOP_COUNT - 1)
    assert comm.hop_exceeded(comm.MAX_HOP_COUNT)
    err = PluginCommError.loop(comm.MAX_HOP_COUNT, "t1")
    assert err.code == "PLUGIN_CALL_LOOP" and err.data["max_hop"] == comm.MAX_HOP_COUNT


def test_trace_id_falls_back_to_fresh_id_without_engine_context():
    tid = comm.new_trace_id()
    assert isinstance(tid, str) and len(tid) == 32
    assert comm.new_call_id() != tid


def test_timeout_is_always_bounded():
    assert comm.normalize_timeout_ms(None) == comm.DEFAULT_TIMEOUT_MS
    assert comm.normalize_timeout_ms(0) == comm.DEFAULT_TIMEOUT_MS
    assert comm.normalize_timeout_ms(-5) == comm.DEFAULT_TIMEOUT_MS
    assert comm.normalize_timeout_ms("abc") == comm.DEFAULT_TIMEOUT_MS
    assert comm.normalize_timeout_ms(1234) == 1234
    assert comm.normalize_timeout_ms(10 ** 9) == comm.MAX_TIMEOUT_MS


# ---------------------------------------------------------------- §十四/§十六 权限与目标

@pytest.mark.parametrize("approved,target,method,ok", [
    ([], "weather", "get_status", False),
    (["plugin.call.weather"], "weather", "get_status", True),
    (["plugin.call.weather.refresh"], "weather", "refresh", True),
    (["plugin.call.weather.refresh"], "weather", "get_status", False),
    (["plugin.call.*"], "anything", "m", True),
    (["plugin.call"], "anything", "m", True),
    (["plugin.emit"], "anything", "m", False),
    (["plugin_admin"], "anything", "m", False),   # 旧粗粒度权限不能冒充细粒度调用权
])
def test_call_permission_matrix(approved, target, method, ok):
    assert call_permission_granted(approved, target, method) is ok


def test_emit_permission_matrix():
    assert emit_permission_granted(["plugin.emit"]) is True
    assert emit_permission_granted(["plugin.call.*"]) is True
    assert emit_permission_granted(["send_message"]) is False
    assert emit_permission_granted([]) is False


@pytest.mark.parametrize("perm,ok", [
    ("plugin.call.weather", True),
    ("plugin.call.weather.get_status", True),
    ("plugin.call.weather_2.refresh_now", True),
    ("plugin.call", False),
    ("plugin.call.*", False),
    ("plugin.call.", False),
    ("plugin.call.中文", False),
    ("plugin.emit", False),
])
def test_dynamic_call_permission_shape(perm, ok):
    assert is_call_permission(perm) is ok


def test_call_permission_candidates_are_ordered_fine_to_coarse():
    assert comm.call_permissions("weather", "get_status") == [
        "plugin.call.weather.get_status", "plugin.call.weather",
        "plugin.call.*", "plugin.call"]


@pytest.mark.parametrize("spec,plugin_id,instance", [
    ("a", "a", ""),
    ("a#instance1", "a", "instance1"),
    ("a#", "a", ""),
    ({"plugin_id": "a", "instance_id": "i2"}, "a", "i2"),
    ({"plugin_id": "a#i3"}, "a", "i3"),
    ("", "", ""),
])
def test_target_parsing(spec, plugin_id, instance):
    assert comm.parse_target(spec) == (plugin_id, instance)


def test_instance_full_id_format():
    assert comm.format_instance_id("a", "i1") == "a#i1"
    assert comm.format_instance_id("a", "") == "a"


# ---------------------------------------------------------------- 五种语言同源

def test_runner_and_engine_constants_are_the_same_object_model():
    """runner 以 python -I 启动、导入不了仓库代码，协议常量是内联副本 —— 这里逐项比对。"""
    consts = _runner_constants()
    assert tuple(consts["OPTIONAL_METHODS"]) == tuple(OPTIONAL_METHODS)
    assert set(comm.PLUGIN_METHODS) <= set(consts["OPTIONAL_METHODS"])
    assert tuple(consts["CAPABILITY_GROUPS"]["plugin"]) == tuple(comm.PLUGIN_METHODS)
    assert tuple(consts["ERROR_CODES"]) == tuple(comm.ERROR_CODES)
    assert tuple(consts["MESSAGE_KINDS"]) == tuple(comm.MESSAGE_KINDS)
    assert {k: tuple(v) for k, v in consts["DTO_FIELDS"].items()} == comm.DTO_FIELDS
    assert tuple(consts["ROUTE_POLICIES"]) == tuple(comm.ROUTE_POLICIES)
    assert consts["MAX_HOP_COUNT"] == comm.MAX_HOP_COUNT


def test_event_model_roundtrip():
    ev = comm.make_event("weather.updated", {"city": "上海"},
                         source={"plugin_id": "a.py", "runtime": "python"}, trace_id="t9")
    assert comm.validate_event(ev) is None
    assert ev["name"] == "weather.updated" and ev["trace_id"] == "t9"
    assert "request_id" not in ev, "事件不是 RPC：不能带 request_id（§十）"


def test_cancel_message_shape():
    msg = comm.make_cancel("r1", "caller timeout", source={"plugin_id": "a.py"})
    assert msg["kind"] == "CANCEL" and msg["request_id"] == "r1"
    assert comm.classify_message({"id": 1, "method": "plugin.cancel", "params": msg}) == "CANCEL"


def test_json_roundtrip_of_bytes_is_stable():
    ref = comm.sanitize_value({"blob": b"\xff\xfe"})
    assert json.loads(json.dumps(ref))["blob"]["$bytes"] == comm.bytes_ref(b"\xff\xfe")["$bytes"]
    assert not math.isnan(0.0)

