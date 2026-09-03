"""OneBot 全平台兼容：图片 file 字段优先识别（绕开 CDN/UA/过期——标准段属性）。"""
import asyncio


def test_event_image_files_preferred_over_url():
    """parser：file 优先收集（file:// 剥离）→ assembler 先描述 file/URL 兜底。"""
    import sys
    sys.path.insert(0, ".")
    from src.adapters.onebot_parser import OneBotEventParser

    parser = OneBotEventParser(bot_qq=10001)
    arr = [{"type": "text", "data": {"text": "看图"}},
           {"type": "image", "data": {"file": "/tmp/img.png", "url": "https://cdn.example.com/a.png"}}]
    ev = parser.parse({"sender": {"user_id": 1}, "group_id": 9,
                       "user_id": 1, "message_id": 2, "message": arr,
                       "message_type": "group", "post_type": "message",
                       "time": 0})
    assert getattr(ev, "image_files", []) == ["/tmp/img.png"]
    assert ev.images[0].startswith("https://") or "/tmp/img.png" in ev.images[0]


def test_image_files_roundtrip_no_double():
    """file 同时出现在 images（兼容视图）与 image_files 时：assembler 不重复描述。"""
    import sys
    sys.path.insert(0, ".")
    from src.core.message_assembler import MessageAssembler

    class _Event:
        images = ["/tmp/a.png"]
        image_files = ["/tmp/a.png"]
        config = type("C", (), {"MAX_IMAGES_PER_MESSAGE": 3})()

    class _AIClient:
        def __init__(self):
            self.called = []

        async def describe_image_file(self, p):
            self.called.append(("file", p))
            return "一张图"

        async def describe_image(self, u):
            self.called.append(("url", u))
            return "url图"

    ma = MessageAssembler.__new__(MessageAssembler)
    ma.config = _Event.config
    ma.ai_client = _AIClient()
    ma._file_parser = None
    ma._logger = None
    out = asyncio.run(ma._describe_images(_Event()))
    assert out == ["一张图"]
    assert ma.ai_client.called == [("file", "/tmp/a.png")]
