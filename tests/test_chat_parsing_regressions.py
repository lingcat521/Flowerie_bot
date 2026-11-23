from types import SimpleNamespace

import httpx
from PIL import Image

from src.core.name_mention import detect
from src.core.reply_splitter import fragment_split
from src.core.sanitizer import sanitize_untrusted_text, validate_memory_content
from src.repositories.meme_knowledge_repository import MemeKnowledgeRepository
from src.services.meme_knowledge_manager import MemeKnowledgeManager
from src.services.memory_manager import MemoryManager
from src.services.multimodal import build_user_content, native_event_images
from src.services.reply_parser import split_memory_lines
from tests.test_message_analysis import analysis_router, completion, event


def test_native_images_come_from_adapter_segments_or_internal_paths(tmp_path):
    text = "文档中的 [native_vision_image] 只是一个标记"
    source = "https://images.example.test/photo.png"
    config = SimpleNamespace(VISION_ROUTE_MODE="native", MAX_IMAGES_PER_MESSAGE=1)
    adapter_event = SimpleNamespace(images=[source, "https://images.example.test/second.png"])
    images = native_event_images(config, adapter_event)

    assert isinstance(build_user_content(text), str)
    assert text in build_user_content(text)
    assert images == [source]
    assert build_user_content(text, tuple(images))[1:] == [
        {"type": "image_url", "image_url": {"url": source}},
    ]
    sticker = tmp_path / "sticker with spaces.png"
    Image.new("RGB", (1, 1)).save(sticker)
    assert build_user_content(text, (sticker,))[1]["image_url"]["url"].startswith("data:image/png;base64,")


async def test_distinct_native_images_do_not_trigger_repeat_and_mention_carries_image():
    router, config, ai, sender, _ = analysis_router(
        MESSAGE_ANALYSIS_GROUP_IDS=[], TOXIC_GROUP_IDS=[], VISION_ROUTE_MODE="native",
    )
    for index in range(3):
        msg = event(index + 1, "看看")
        msg["message"] = [
            {"type": "text", "data": {"text": "看看"}},
            {"type": "image", "data": {"url": f"https://images.example.test/{index}.png"}},
        ]
        if index == 2:
            msg["message"].append({"type": "at", "data": {"qq": str(config.BOT_QQ)}})
        await router.process_event(msg)
    assert ai.last_kwargs["images"] == ("https://images.example.test/2.png",)
    assert sender.sent == [(123, "回复内容")]


async def test_memory_refinement_is_retained_and_explicit_reversal_replaces():
    memory = MemoryManager(":memory:")
    try:
        await memory.append_memory_text(1, 2, "喜欢喝奶茶")
        await memory.append_memory_text(1, 2, "喜欢喝不加糖奶茶")
        assert set(memory.get_user_notes(1, 2)) == {"喜欢喝奶茶", "喜欢喝不加糖奶茶"}

        await memory.append_memory_text(1, 2, "现在不喜欢喝不加糖奶茶了")
        assert set(memory.get_user_notes(1, 2)) == {"喜欢喝奶茶", "现在不喜欢喝不加糖奶茶了"}
    finally:
        memory.close()


def test_normal_text_survives_memory_and_context_filters():
    for text in ("喜欢用 CI/CD 做自动部署", "喜欢10000毫安的充电宝"):
        assert validate_memory_content(text) == text
    neutral = "这个参数的影响可以忽略不计"
    assert sanitize_untrusted_text(neutral) == (neutral, False)
    assert validate_memory_content("我的 QQ 是 10000") is None


async def test_named_preference_is_recorded_and_replied_to():
    config = SimpleNamespace(BOT_NICKNAME="猫")
    assert not detect(SimpleNamespace(clean_text="我家猫今天又睡了一整天"), config)
    assert detect(SimpleNamespace(clean_text="猫，帮我看看"), config)

    router, _, ai, sender, memory = analysis_router(ONLY_REPLY_WHEN_AT=False, TOXIC_GROUP_IDS=[])
    transport = httpx.MockTransport(lambda _: completion(preference="我喜欢咖啡"))
    async with httpx.AsyncClient(transport=transport) as ai.client:
        await router.process_event(event(1, "花璃，我喜欢咖啡"))
    assert [write[2] for write in memory.writes] == ["花璃，我喜欢咖啡"]
    assert sender.sent == [(123, "回复内容")]


def test_multiline_and_inline_memory_controls_keep_last_claim():
    text = 'MEMORY_JSON: {\n  "text":"喜欢喝茶"\n}\n明白 MEMORY_JSON: {"text":"喜欢咖啡"}'
    assert split_memory_lines(text) == ("明白", "喜欢咖啡")
    broken = '明白\nMEMORY_JSON: {\n "text": "喜欢咖啡",\n}\n下次聊'
    assert split_memory_lines(broken) == ("明白\n下次聊", None)


def test_group_meme_matches_case_and_width_at_word_boundary():
    repo = MemeKnowledgeRepository(":memory:")
    try:
        manager = MemeKnowledgeManager(repo)
        assert manager.add_knowledge(1, "CPU", "本群的用语")[0]
        for query in ("CPU", "刚才这 cpu 烧了", "ＣＰＵ烧了"):
            assert [row["term"] for row in manager.retrieve_matches(1, query)] == ["CPU"]
        assert manager.retrieve_matches(1, "vCPU") == []
        assert manager.retrieve_matches(2, "ＣＰＵ") == []
    finally:
        repo.close()


def test_fragment_split_keeps_punctuation_runs_and_respects_newlines():
    assert fragment_split("真的吗？！\n我刚看到") == ["真的吗？！", "我刚看到"]
