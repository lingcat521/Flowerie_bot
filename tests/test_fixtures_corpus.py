"""P5 夹具语料回归：`tests/fixtures/<client>/*.json` → 归一化字段。

语料是**按客户端源码逐字段构造**的（非实机抓包），每个文件带 `_provenance` 写明证据；
本测试做两件事：① 强制溯源字段完整；② 按目录选解析器并断言归一化结果。
详见 tests/fixtures/README.md。
"""
import glob
import json
import os

import pytest

from src.adapters.milky_parser import MilkyEventParser
from src.adapters.onebot_parser import OneBotEventParser

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
BOT_QQ = 10001
ALL_FIXTURES = sorted(glob.glob(os.path.join(FIXTURES, "*", "*.json")))


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _parse(path: str):
    """按目录选解析器（目录名即客户端名）。"""
    raw = _load(path)
    client = os.path.basename(os.path.dirname(path))
    if client == "milky":
        return MilkyEventParser(bot_qq=BOT_QQ).parse(raw)
    return OneBotEventParser(bot_qq=BOT_QQ).parse(raw)


def _by_name(name: str):
    for path in ALL_FIXTURES:
        if os.path.basename(path) == name:
            return path
    pytest.skip("语料缺失：%s" % name)


def test_corpus_is_not_empty():
    assert len(ALL_FIXTURES) >= 7, ALL_FIXTURES


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=[os.path.basename(p) for p in ALL_FIXTURES])
def test_every_fixture_declares_provenance(path):
    prov = _load(path).get("_provenance") or {}
    for key in ("client", "status", "captured", "evidence", "note"):
        assert prov.get(key) not in (None, ""), "缺少 _provenance.%s：%s" % (key, path)
    assert prov["client"] == os.path.basename(os.path.dirname(path))


@pytest.mark.parametrize("path", ALL_FIXTURES, ids=[os.path.basename(p) for p in ALL_FIXTURES])
def test_every_fixture_parses_without_error(path):
    ev = _parse(path)
    assert ev.kind and ev.kind != "unknown", ev.kind


# ---------- NapCat ----------

def test_napcat_text_at_image():
    ev = _parse(_by_name("group_message_text_at_image.json"))
    assert ev.kind == "message" and ev.scope == "group"
    assert ev.is_mentioned is True and "10001" in ev.mentions
    assert ev.text == "看这个图"
    assert ev.images and ev.image_files == ["abc.jpg"]


def test_napcat_ark_multimsg_is_forward_card():
    ev = _parse(_by_name("group_message_ark_multimsg.json"))
    card = ev.json_cards[0]
    assert card["app"] == "com.tencent.multimsg" and card["is_forward_card"] is True
    assert card["payload"]["meta"]["detail"]["resid"] == "ResId_ABC123"


def test_napcat_group_upload_notice():
    ev = _parse(_by_name("notice_group_upload.json"))
    assert ev.kind == "notice" and ev.notice_kind == "group_upload"
    assert ev.notice_file["name"] == "报告.pdf" and ev.notice_file["busid"] == 102


def test_napcat_poke_notice():
    ev = _parse(_by_name("notice_poke.json"))
    assert ev.kind == "notice" and ev.notice_kind == "poke"
    assert ev.actor_id == 456789 and ev.target_id == BOT_QQ


# ---------- LLBot ----------

def test_llbot_file_and_shake():
    ev = _parse(_by_name("onebot_message_file_and_shake.json"))
    assert ev.files[0]["file_id"] == "fid-9" and ev.files[0]["name"] == "资料.zip"
    assert ev.pokes and ev.pokes[0]["poke_type"] == "shake"
    assert ev.json_cards == []


# ---------- Milky ----------

def test_milky_mixed_segments_all_normalized():
    ev = _parse(_by_name("group_message_segments.json"))
    assert ev.message_id == 998878                      # message_seq → message_id
    assert ev.is_mentioned is True
    assert [f["kind"] for f in ev.faces] == ["face", "market_face"]
    assert ev.json_cards[0]["is_forward_card"] is True   # light_app 内 app=multimsg
    assert ev.forwards[0]["id"] == "fwd-1" and ev.forwards[0]["title"] == "聊天记录"
    assert ev.files[0]["file_id"] == "mfid-1" and ev.files[0]["size"] == 2048
    assert "混合段测试" in ev.text and "**公告**" in ev.text


def test_milky_group_nudge_becomes_poke_notice():
    ev = _parse(_by_name("group_nudge_event.json"))
    assert ev.kind == "notice" and ev.notice_kind == "poke"
    assert ev.actor_id == 456789 and ev.target_id == BOT_QQ
    assert ev.group_id == 123456 and ev.scope == "group"
