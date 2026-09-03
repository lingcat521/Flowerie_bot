"""VISION_ENABLED 开关：关闭后不调用视觉模型（省 token/隐私）。"""
import asyncio

from src.core.message_assembler import MessageAssembler


class _Cfg:
    VISION_ENABLED = False
    VISION_FORWARD_IMAGES = True
    MAX_IMAGES_PER_MESSAGE = 3


class _Event:
    images = ["https://cdn.example.com/a.png"]
    image_files = []
    config = _Cfg()


class _AI:
    def __init__(self):
        self.calls = []

    async def describe_image(self, u):
        self.calls.append(u)
        return "一张图"

    async def describe_image_file(self, p):
        self.calls.append(("file", p))
        return "本地图"


def test_disabled_no_vision_call():
    ma = MessageAssembler.__new__(MessageAssembler)
    ma.config = _Cfg()
    ma.ai_client = _AI()
    out = asyncio.run(ma._describe_images(_Event()))
    assert out == []
    assert ma.ai_client.calls == []      # 完全没有调用视觉模型


def test_enabled_calls_vision():
    class _CfgOn:
        VISION_ENABLED = True
        VISION_FORWARD_IMAGES = True
        MAX_IMAGES_PER_MESSAGE = 3

    class _Ev2:
        images = ["https://cdn.example.com/a.png"]
        image_files = []

    ma = MessageAssembler.__new__(MessageAssembler)
    ma.config = _CfgOn()
    ma.ai_client = _AI()
    ev = _Ev2()
    ev.config = _CfgOn()
    out = asyncio.run(ma._describe_images(ev))
    assert out == ["一张图"] and ma.ai_client.calls == ["https://cdn.example.com/a.png"]
