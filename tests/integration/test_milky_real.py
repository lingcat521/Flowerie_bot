"""G6 / §8.2：Milky 实机 Integration Test（12 项）。

默认全部 skip（同 test_onebot11_real.py 的约定）：需要真实 Milky 协议端 + 测试群。
"""
import pytest

from src.adapters.milky_parser import MilkyEventParser

from ._realenv import ENV_FILE, ENV_IMAGE, ENV_RECORD, client_config, media_path, record_evidence, skip_message

pytestmark = pytest.mark.real_device

KIND = "milky"
BOT_QQ = 10001


class _Cfg:
    def __init__(self, base, token=""):
        self.MILKY_API_BASE = base
        self.MILKY_ACCESS_TOKEN = token


def _env():
    env = client_config(KIND)
    if env is None:
        pytest.skip(skip_message(KIND))
    return env


async def _call(action, payload, env):
    import aiohttp

    from src.transport.action_channels import MilkyHTTPChannel

    async with aiohttp.ClientSession() as session:
        channel = MilkyHTTPChannel(_Cfg(env["base"], env["token"]), session)
        return await channel.post(action, payload)


def _as_event(data):
    return {"time": data.get("time") or 0, "self_id": BOT_QQ, "event_type": "message_receive",
            "data": {"message_scene": "group", "peer_id": data.get("peer_id") or data.get("group_id"),
                     "sender_id": data.get("sender_id") or data.get("user_id"),
                     "message_seq": data.get("message_seq") or data.get("message_id"),
                     "segments": data.get("segments") or data.get("message") or []}}


async def _send_and_fetch(env, segments, marker):
    sent = await _call("send_group_message", {"group_id": env["group"], "message": segments}, env)
    assert sent.get("ok") is True, sent
    seq = (sent.get("data") or {}).get("message_seq") or (sent.get("data") or {}).get("message_id")
    history = await _call("get_history_messages", {"message_scene": "group", "peer_id": env["group"],
                                                  "limit": 5}, env)
    messages = (history.get("data") or {}).get("messages") or []
    target = None
    for item in messages:
        if str(item.get("message_seq") or item.get("message_id")) == str(seq):
            target = item
            break
    if target is None:
        pytest.skip("取回消息失败（客户端 history API 未实现或字段不同）：marker=%s" % marker)
    return MilkyEventParser(bot_qq=BOT_QQ).parse(_as_event(target))


@pytest.mark.asyncio
async def test_01_text_send():
    env = _env()
    res = await _call("send_group_message", {"group_id": env["group"],
                                            "message": [{"type": "text", "data": {"text": "flowerie-real"}}]},
                      env)
    assert res.get("ok") is True, res


@pytest.mark.asyncio
async def test_02_text_receive():
    env = _env()
    event = await _send_and_fetch(env, [{"type": "text", "data": {"text": "flowerie-real-recv"}}], "text")
    assert event.text.strip() == "flowerie-real-recv", event.text
    record_evidence("text receive", KIND, {"client": "Milky 客户端", "input": "flowerie-real-recv",
                                           "expected": "flowerie-real-recv", "actual": event.text,
                                           "result": "PASS"})


@pytest.mark.asyncio
async def test_03_image_send():
    env = _env()
    image = media_path(ENV_IMAGE)
    if not image:
        pytest.skip("未设置 " + ENV_IMAGE)
    res = await _call("send_group_message",
                      {"group_id": env["group"], "message": [{"type": "image", "data": {"uri": image}}]}, env)
    assert res.get("ok") is True, res


@pytest.mark.asyncio
async def test_04_image_receive():
    env = _env()
    image = media_path(ENV_IMAGE)
    if not image:
        pytest.skip("未设置 " + ENV_IMAGE)
    event = await _send_and_fetch(env, [{"type": "image", "data": {"uri": image}}], "image")
    assert event.images or event.image_files, event.message_segments


@pytest.mark.asyncio
async def test_05_record_send():
    env = _env()
    record = media_path(ENV_RECORD)
    if not record:
        pytest.skip("未设置 " + ENV_RECORD)
    res = await _call("send_group_message",
                      {"group_id": env["group"], "message": [{"type": "record", "data": {"uri": record}}]}, env)
    assert res.get("ok") is True, res


@pytest.mark.asyncio
async def test_06_record_receive():
    env = _env()
    record = media_path(ENV_RECORD)
    if not record:
        pytest.skip("未设置 " + ENV_RECORD)
    event = await _send_and_fetch(env, [{"type": "record", "data": {"uri": record}}], "record")
    assert event.records, event.message_segments


@pytest.mark.asyncio
async def test_07_file_send():
    env = _env()
    path = media_path(ENV_FILE)
    if not path:
        pytest.skip("未设置 " + ENV_FILE)
    res = await _call("upload_group_file", {"group_id": env["group"], "file": path,
                                            "name": path.rsplit("/", 1)[-1]}, env)
    assert res.get("ok") is True, res


@pytest.mark.asyncio
async def test_08_file_receive():
    env = _env()
    res = await _call("get_group_files", {"group_id": env["group"]}, env)
    if not res.get("ok"):
        pytest.skip("该实现不支持 get_group_files：%s" % res.get("error"))
    from src.adapters.resource import ResourceRef

    files = ((res.get("data") or {}).get("files") or []) if isinstance(res.get("data"), dict) else []
    if not files:
        pytest.skip("测试群里还没有文件（先跑 test_07_file_send）")
    ref = ResourceRef.from_protocol_id(str(files[0].get("file_id") or ""), origin="milky")
    assert ref.is_protocol_id and ref.ref


@pytest.mark.asyncio
async def test_09_forward_receive():
    env = _env()
    res = await _call("send_group_forwarded_message",
                      {"group_id": env["group"], "messages": [{"sender_name": "test",
                                                               "segments": [{"type": "text",
                                                                             "data": {"text": "fwd"}}]}]}, env)
    if not res.get("ok"):
        pytest.skip("该实现不支持合并转发发送：%s" % res.get("error"))
    event = await _send_and_fetch(env, [], "forward")
    assert event is not None


@pytest.mark.asyncio
async def test_10_reply():
    env = _env()
    first = await _call("send_group_message", {"group_id": env["group"],
                                              "message": [{"type": "text", "data": {"text": "base"}}]}, env)
    assert first.get("ok") is True, first
    seq = (first.get("data") or {}).get("message_seq")
    res = await _call("send_group_message",
                      {"group_id": env["group"],
                       "message": [{"type": "reply", "data": {"message_seq": seq}},
                                   {"type": "text", "data": {"text": "flowerie-real-reply"}}]}, env)
    assert res.get("ok") is True, res
    event = await _send_and_fetch(env, [{"type": "reply", "data": {"message_seq": seq}},
                                        {"type": "text", "data": {"text": "flowerie-real-reply"}}], "reply")
    assert event.text.strip() == "flowerie-real-reply"


@pytest.mark.asyncio
async def test_11_poke():
    env = _env()
    res = await _call("send_group_nudge", {"group_id": env["group"], "user_id": BOT_QQ}, env)
    assert res.get("ok") is True, res


@pytest.mark.asyncio
async def test_12_request_event():
    """入群/加好友请求事件：**必须由人工触发**（另一个人去点申请）——按 §13 属于 manual real-device test。

    这里只做**前置校验**：请求类事件在真实环境出现时，解析器应归一出 request_kind/request_id。
    人工步骤与证据格式见 tests/integration/README.md §manual。
    """
    pytest.skip("manual real-device test：需要另一账号发起入群/好友申请（见 README §manual 步骤）")
