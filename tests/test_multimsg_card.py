"""合并转发卡片（multimsg）组装测试：证据驱动的行为变更。

证据：NapCat SendMsg.ts L289-297 —— arkElement JSON 的 app == com.tencent.multimsg 时，
取 meta.detail.resid 拉取内层消息；LLBot milky/transform/message/incoming.ts L210-235 同样判定。
因此 Flowerie 的卡片组装必须把这种卡片当**合并转发**处理，而不是当普通卡片收字符串。
"""
import json

import pytest

from src.core.message_assembler import MessageAssembler


class _FileParser:
    """假 file_parser：记录是否被要求拉取转发，并按脚本返回。"""

    def __init__(self, forward_text = "", forward_ok = True, card_text = "卡片文本"):
        self.forward_text = forward_text
        self.forward_ok = forward_ok
        self.card_text = card_text
        self.forward_calls = []
        self.card_calls = 0

    async def extract_forward_messages(self, message_array):
        self.forward_calls.append(message_array)
        return (self.forward_text, [], self.forward_ok)

    def extract_json_card_content(self, message_array):
        # 与真实实现一致的契约：没有 json 段就没有卡片内容（否则 stub 比真实实现更宽松）
        if not any(isinstance(x, dict) and x.get("type") == "json" for x in (message_array or [])):
            return ("", False)
        self.card_calls += 1
        return (self.card_text, True)


class _AIClient:
    async def describe_image(self, url):
        return ""

    async def describe_image_file(self, path):
        return ""


class _Cfg:
    VISION_ENABLED = False
    MAX_IMAGES_PER_MESSAGE = 1
    VISION_FORWARD_IMAGES = False


def _multimsg_segment(resid = "resid-1", app = "com.tencent.multimsg"):
    payload = {"app": app, "meta": {"detail": {"resid": resid, "source": "群聊的聊天记录",
                                      "summary": "查看 3 条转发消息", "news": [{"text": "a"}, {"text": "b"}]}}}
    return {"type": "json", "data": {"data": json.dumps(payload, ensure_ascii=False)}}


def _assembler(fp):
    return MessageAssembler(_Cfg(), _AIClient(), fp, None)


@pytest.mark.asyncio
async def test_multimsg_card_is_fetched_as_forward():
    """multimsg 卡片：必须走转发拉取（把 resid 当 forward id）。"""
    fp = _FileParser(forward_text="[用户1]：你好", forward_ok=True)
    out = await _assembler(fp)._assemble_card([_multimsg_segment()])
    assert len(fp.forward_calls) == 1
    assert fp.forward_calls[0] == [{"type": "forward", "data": {"id": "resid-1"}}]
    assert "转发" in out and "你好" in out
    assert fp.card_calls == 0            # 不再走卡片文本路径


@pytest.mark.asyncio
async def test_multimsg_card_falls_back_to_card_text_when_fetch_fails():
    """拉取失败时退回卡片文本路径，绝不丢内容（任务书 §十八.9）。"""
    fp = _FileParser(forward_text="", forward_ok=False, card_text="群聊的聊天记录 3 条")
    out = await _assembler(fp)._assemble_card([_multimsg_segment()])
    assert len(fp.forward_calls) == 1
    assert fp.card_calls == 1
    assert "卡片" in out and "3 条" in out


@pytest.mark.asyncio
async def test_other_app_card_keeps_old_path():
    """其它 app（小程序等）不受影响：走原有卡片文本路径。"""
    fp = _FileParser(card_text="小程序标题")
    out = await _assembler(fp)._assemble_card([_multimsg_segment(app="com.tencent.miniapp_01")])
    assert fp.forward_calls == []
    assert fp.card_calls == 1 and "小程序标题" in out


@pytest.mark.asyncio
async def test_multimsg_without_resid_keeps_old_path():
    """有 app 但没有 resid：无法拉取 → 退回卡片文本路径。"""
    seg = {"type": "json", "data": {"data": json.dumps({"app": "com.tencent.multimsg", "meta": {"detail": {}}})}}
    fp = _FileParser(card_text="无 resid")
    out = await _assembler(fp)._assemble_card([seg])
    assert fp.forward_calls == [] and fp.card_calls == 1
    assert "无 resid" in out


@pytest.mark.asyncio
async def test_multimsg_card_with_dict_payload():
    """负载是 dict（不是字符串）时同样识别（各家实现两种形态都有）。"""
    seg = {"type": "json", "data": {"data": {"app": "com.tencent.multimsg",
                                          "meta": {"detail": {"resid": "r9"}}}}}
    fp = _FileParser(forward_text="内层文本", forward_ok=True)
    out = await _assembler(fp)._assemble_card([seg])
    assert fp.forward_calls[0][0]["data"]["id"] == "r9"
    assert "内层文本" in out


@pytest.mark.asyncio
async def test_non_json_segments_ignored():
    """非 json 段不受影响（回归）。"""
    fp = _FileParser()
    out = await _assembler(fp)._assemble_card([{"type": "text", "data": {"text": "hi"}}])
    assert fp.forward_calls == []
    assert out == ""


# ---------- 多卡片同条消息：优先级明确化（P4 项 3 的决策）----------
# 背景：一条消息里出现多个 json 段在实践中很少（各客户端源码未见构造多处卡片的代码），
# 但行为必须**写清并锁定**，避免以后有人以为"所有卡片都会被渲染"。

@pytest.mark.asyncio
async def test_multimsg_wins_over_other_cards_in_same_message():
    fp = _FileParser(forward_text="转发内容")
    out = await _assembler(fp)._assemble_card([
        _multimsg_segment(resid="r-first"),
        _multimsg_segment(resid="r-second", app="com.tencent.miniapp_01"),
    ])
    assert len(fp.forward_calls) == 1
    assert fp.forward_calls[0][0]["data"]["id"] == "r-first"   # 只取第一个 multimsg
    assert fp.card_calls == 0                                   # 其余卡片不再走文本路径
    assert "转发内容" in out


@pytest.mark.asyncio
async def test_two_multimsg_cards_only_first_resid_used():
    fp = _FileParser(forward_text="内层")
    await _assembler(fp)._assemble_card([_multimsg_segment(resid="r1"), _multimsg_segment(resid="r2")])
    assert [c[0]["data"]["id"] for c in fp.forward_calls] == ["r1"]


@pytest.mark.asyncio
async def test_multiple_normal_cards_use_parser_merged_text():
    # 普通卡片（非 multimsg）：文本合并发生在 file_parser.extract_json_card_content 内部
    # （它对所有 json 段收集字符串到一个 set），组装层只调用一次、原样使用其返回。
    fp = _FileParser(card_text="卡片A 卡片B")
    out = await _assembler(fp)._assemble_card([
        {"type": "json", "data": {"data": '{"app":"a","title":"卡片A"}'}},
        {"type": "json", "data": {"data": '{"app":"b","title":"卡片B"}'}},
    ])
    assert fp.card_calls == 1 and fp.forward_calls == []
    assert "卡片A 卡片B" in out
