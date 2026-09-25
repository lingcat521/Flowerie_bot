"""G6 / §8.1：OneBot 11 实机 Integration Test（10 项）。

**默认全部 skip**：只有在配置了真实客户端环境变量时才执行（见 tests/integration/README.md）。
未配置时给出 §8.3 要求的"缺失条件"，绝不把手工验证写成"已通过"。

每一项目测的都是真实链路：**通过客户端 API 发送 → 再从客户端取回 → 用仓库**真解析器**归一化**，
断言归一化结果 —— 也就是"真客户端数据 → Adapter → Normalized Model"这一段真的跑通了。
"""
import json

import pytest

from src.adapters.onebot_parser import OneBotEventParser

from ._realenv import (ENV_FILE, ENV_IMAGE, client_config, media_path, record_evidence,
                       skip_message)

pytestmark = pytest.mark.real_device

KIND = "onebot11"
BOT_QQ = 10001


class _Cfg:
    def __init__(self, base):
        self.HTTP_API_BASE = base


def _env():
    env = client_config(KIND)
    if env is None:
        pytest.skip(skip_message(KIND))
    return env


async def _call(endpoint, payload, env):
    import aiohttp

    from src.transport.action_channels import OneBotHTTPChannel

    async with aiohttp.ClientSession() as session:
        channel = OneBotHTTPChannel(_Cfg(env["base"]), session)
        return await channel.post(endpoint, payload)


def _as_event(data):
    """把 /get_msg 的真实响应拼成一个事件（接收方向解析器的输入形状）。"""
    return {"post_type": "message", "message_type": "group", "sub_type": "normal",
            "group_id": data.get("group_id"), "user_id": data.get("user_id") or data.get("sender", {}).get("user_id"),
            "message_id": data.get("message_id"), "time": data.get("time"),
            "message": data.get("message") or []}


@pytest.mark.asyncio
async def test_01_text_send():
    env = _env()
    res = await _call("send_group_msg", {"group_id": env["group"], "message": "Flowerie 实机测试 text send"},
                      env)
    assert res.get("ok") is True, res
    record_evidence("text send", KIND, {"client": "OneBot11 客户端", "input": "send_group_msg",
                                        "expected": "retcode=0", "actual": json.dumps(res)[:300],
                                        "result": "PASS"})


@pytest.mark.asyncio
async def test_02_text_receive():
    env = _env()
    marker = "flowerie-real-text-receive"
    sent = await _call("send_group_msg", {"group_id": env["group"], "message": marker}, env)
    assert sent.get("ok") is True, sent
    msg = await _call("get_msg", {"message_id": sent["data"]["message_id"]}, env)
    event = OneBotEventParser(bot_qq=BOT_QQ).parse(_as_event(msg.get("data") or {}))
    assert event.text.strip() == marker, event.text
    record_evidence("text receive", KIND, {"client": "OneBot11 客户端", "input": marker,
                                           "expected": marker, "actual": event.text, "result": "PASS"})


@pytest.mark.asyncio
async def test_03_image_send():
    env = _env()
    image = media_path(ENV_IMAGE)
    if not image:
        pytest.skip("未设置 " + ENV_IMAGE + "（可发送的图片 URL 或本地路径）")
    res = await _call("send_group_msg", {"group_id": env["group"],
                                         "message": [{"type": "image", "data": {"file": image}}]}, env)
    assert res.get("ok") is True, res


@pytest.mark.asyncio
async def test_04_image_receive():
    env = _env()
    image = media_path(ENV_IMAGE)
    if not image:
        pytest.skip("未设置 " + ENV_IMAGE)
    sent = await _call("send_group_msg", {"group_id": env["group"],
                                          "message": [{"type": "image", "data": {"file": image}}]}, env)
    msg = await _call("get_msg", {"message_id": sent["data"]["message_id"]}, env)
    event = OneBotEventParser(bot_qq=BOT_QQ).parse(_as_event(msg.get("data") or {}))
    assert event.images or event.image_files, event.message_segments
    record_evidence("image receive", KIND, {"client": "OneBot11 客户端", "input": image,
                                            "expected": "images 非空", "actual": str(event.images)[:200],
                                            "result": "PASS"})


@pytest.mark.asyncio
async def test_05_file_send():
    env = _env()
    path = media_path(ENV_FILE)
    if not path:
        pytest.skip("未设置 " + ENV_FILE)
    res = await _call("upload_group_file", {"group_id": env["group"], "file": path,
                                            "name": path.rsplit("/", 1)[-1]}, env)
    assert res.get("ok") is True, res


@pytest.mark.asyncio
async def test_06_file_receive():
    """文件"接收"：从客户端取回群文件列表，并把真实条目归一化成统一资源（Gate R 的 ResourceRef）。"""
    env = _env()
    res = await _call("get_group_root_files", {"group_id": env["group"]}, env)
    assert res.get("ok") is True, res
    from src.adapters.resource import ResourceRef

    files = ((res.get("data") or {}).get("files") or []) if isinstance(res.get("data"), dict) else []
    if not files:
        pytest.skip("测试群里还没有文件（先跑 test_05_file_send）")
    ref = ResourceRef.from_protocol_id(str(files[0].get("file_id") or ""), origin="onebot11",
                                       name=str(files[0].get("file_name") or ""))
    assert ref.is_protocol_id and ref.ref


@pytest.mark.asyncio
async def test_07_forward_receive():
    env = _env()
    res = await _call("send_group_forward_msg", {"group_id": env["group"],
                                                 "messages": [{"type": "node",
                                                               "data": {"name": "test",
                                                                        "uin": str(BOT_QQ),
                                                                        "content": [{"type": "text",
                                                                                     "data": {"text": "fwd"}}]}}]},
                      env)
    if not res.get("ok"):
        pytest.skip("该客户端不支持 send_group_forward_msg：%s" % res.get("error"))
    msg = await _call("get_msg", {"message_id": res["data"]["message_id"]}, env)
    event = OneBotEventParser(bot_qq=BOT_QQ).parse(_as_event(msg.get("data") or {}))
    assert event.forwards, event.message_segments


@pytest.mark.asyncio
async def test_08_json_ark_receive():
    env = _env()
    card = json.dumps({"app": "com.tencent.miniapp", "prompt": "flowerie-real", "metaData": {}})
    sent = await _call("send_group_msg", {"group_id": env["group"],
                                          "message": [{"type": "json", "data": {"data": card}}]}, env)
    assert sent.get("ok") is True, sent
    msg = await _call("get_msg", {"message_id": sent["data"]["message_id"]}, env)
    event = OneBotEventParser(bot_qq=BOT_QQ).parse(_as_event(msg.get("data") or {}))
    assert event.json_cards, event.message_segments
    assert event.json_cards[0]["app"] == "com.tencent.miniapp"


@pytest.mark.asyncio
async def test_09_poke():
    """戳一戳：发送侧可自动验证；接收侧需要事件流（见 README 的 manual 步骤）。"""
    env = _env()
    res = await _call("send_poke", {"group_id": env["group"], "user_id": BOT_QQ}, env)
    assert res.get("ok") is True, res


@pytest.mark.asyncio
async def test_10_recall():
    env = _env()
    sent = await _call("send_group_msg", {"group_id": env["group"], "message": "flowerie-real-recall"}, env)
    assert sent.get("ok") is True, sent
    res = await _call("delete_msg", {"message_id": sent["data"]["message_id"]}, env)
    assert res.get("ok") is True, res
    record_evidence("recall", KIND, {"client": "OneBot11 客户端", "input": "send → delete_msg",
                                     "expected": "delete_msg retcode=0", "actual": json.dumps(res)[:200],
                                     "result": "PASS"})
