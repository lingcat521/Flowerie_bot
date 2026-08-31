"""文档黑盒：docs/plugin-developer-guide.md §0「60 秒上手」示例（原样插件）真实加载+路由。

事件形态与真实 runner 一致（dict），SDK 路由 → BotEvent → handler → reply 走 api。
"""
import importlib.util
import sys

import pytest


@pytest.mark.asyncio
async def test_doc_example_loads_and_routes():
    # 加载（模拟 python_runner 加载形态：模块名 flowerie_plugin_* + sys.modules 注册）
    plugin_dir = "tests/plugins/doc_example"
    if plugin_dir not in sys.path:
        sys.path.insert(0, plugin_dir)   # 与 python_runner 一致（插件可 import 自带的 flowerie_sdk）
    spec = importlib.util.spec_from_file_location(
        "flowerie_plugin_doc_example", "tests/plugins/doc_example/plugin.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["flowerie_plugin_doc_example"] = mod
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
            return {"ok": True, "message_id": 100 + len(self.sent)}

        def send_reply(self, payload):
            self.sent.append(payload)
            return {"ok": True, "message_id": 200 + len(self.sent)}

    api = FakeApi()
    mod.on_startup({}, api=api)
    assert api.registered is not None and len(api.registered) == 3

    # !hi → 回复"你好呀"
    await mod.on_message({"kind": "message", "scope": "group", "text": "!hi",
                          "group_id": 777, "user_id": 123, "message_id": 1,
                          "matched": {"name": "hello", "args": ""}}, api)
    assert api.sent and api.sent[-1]["message"] == "你好呀"

    # !add 1 2 → 3
    await mod.on_message({"kind": "message", "scope": "group", "text": "!add 1 2",
                          "group_id": 777, "user_id": 123, "message_id": 2,
                          "matched": {"name": "add", "args": "1 2"}}, api)
    assert api.sent[-1]["message"] == "3"

    # 权限规则随 matcher 上报（require_permission 生效）
    assert any("is_group_admin" in (m.get("rule") or {}) for m in api.registered)
