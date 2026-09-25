"""表情进业务层测试：Adapter 归一化字段 → AI 可见的一句话。

证据（见 docs/message-model.md §3）：NapCat face/mface schema、Milky FaceSegment、LLBot market_face。
"""
import pytest

from src.core.message_assembler import MessageAssembler


class _FileParser:
    async def extract_forward_messages(self, arr):
        return ("", [], False)

    def extract_json_card_content(self, arr):
        return ("", False)


class _AI:
    async def describe_image(self, url):
        return ""

    async def describe_image_file(self, path):
        return ""


class _Cfg:
    VISION_ENABLED = False
    MAX_IMAGES_PER_MESSAGE = 1
    VISION_FORWARD_IMAGES = False


class _Event:
    def __init__(self, faces):
        self.faces = faces
        self.message_segments = []
        self.text = "hi"
        self.images = []
        self.image_files = []
        self.is_reply_to_bot = False
        self.has_reply_to_other = False
        self.has_at_others = False


class _GS:
    pending_files = {}


def _asm():
    return MessageAssembler(_Cfg(), _AI(), _FileParser(), _GS())


def test_qq_face_becomes_text():
    out = _asm()._assemble_faces(_Event([{"kind": "face", "face_id": "14"}]))
    assert "用户发送了表情" in out and "id=14" in out


def test_market_face_uses_summary():
    out = _asm()._assemble_faces(_Event([{"kind": "market_face", "emoji_id": "abc", "summary": "猫猫头"}]))
    assert "商城表情" in out and "猫猫头" in out


def test_market_face_without_summary_falls_back_to_emoji_id():
    out = _asm()._assemble_faces(_Event([{"kind": "market_face", "emoji_id": "xyz", "summary": ""}]))
    assert "xyz" in out


def test_face_extras_rendered():
    out = _asm()._assemble_faces(_Event([{"kind": "face", "face_id": "5", "chain_count": 3, "is_large": True}]))
    assert "连击 x3" in out and "大表情" in out


def test_empty_faces_no_output():
    assert _asm()._assemble_faces(_Event([])) == ""


def test_faces_capped_at_three():
    faces = [{"kind": "face", "face_id": str(i)} for i in range(6)]
    out = _asm()._assemble_faces(_Event(faces))
    assert out.count("[QQ 表情") == 3


def test_non_dict_faces_ignored():
    out = _asm()._assemble_faces(_Event(["x", 1, {"kind": "face", "face_id": "7"}]))
    assert "id=7" in out and out.count("[QQ 表情") == 1


@pytest.mark.asyncio
async def test_assemble_includes_faces():
    """端到端：assemble() 的输出里带表情提示。"""
    ev = _Event([{"kind": "face", "face_id": "9"}])
    full_text, _imgs, _a, _b, _c = await _asm().assemble(ev, user_id=1, group_id=2, raw_time=0)
    assert "用户发送了表情" in full_text
