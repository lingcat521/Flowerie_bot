"""文档黑盒：docs §0「60 秒上手」插件（tests/plugins/doc_example）真实加载+路由。"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath("tests/plugins/doc_example"))


@pytest.mark.asyncio
async def test_doc_example_loads_and_routes():
    """验证文档代码可直接运行：加载插件 → 注册 matcher → 路由执行。"""
    import importlib.util

    # 加载（模拟 python_runner -I 加载）
    spec = importlib.util.spec_from_file_location(
        "doc_example_plugin", "tests/plugins/doc_example/plugin.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class FakeApi:
        def __init__(self):
            self.sent = []
            self.registered = None

        def matcher_register(self, matchers):
            self.registered = matchers
            return {"ok": True}

        def send_message(self, payload):
            self.sent.append(payload)
            return {"ok": True}

    api = FakeApi()
    mod.on_startup({}, api=api)
    assert api.registered is not None and len(api.registered) == 3
    # hi 路由
    ev = type("E", (), {"text": "!hi", "args": [], "is_group": True, "group_id": 777,
                        "user_id": 123, "message_id": 1, "reply": lambda self, m=None, **k: api.send_message({
                            "group_id": 777, "message": m})})
    event = ev()
    mod.on_message(event, api)
    assert api.sent and api.sent[-1]["message"] == "你好呀"
    # add 路由：event.args 存在
    ev2 = type("E2", (), {"text": "!add 1 2", "args": ["1", "2"], "is_group": True,
                          "group_id": 777, "user_id": 123, "message_id": 2,
                          "reply": lambda self, m=None, **k: api.send_message({
                              "group_id": 777, "message": m})})
    mod.on_message(ev2(), api)
    assert api.sent[-1]["message"] == "3"
    # 权限规则（ban）：requirement 已随 matcher 上报
    assert any("is_group_admin" in (m.get("rule") or {}) for m in api.registered)
