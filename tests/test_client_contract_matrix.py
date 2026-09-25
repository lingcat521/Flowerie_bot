"""客户端 × 能力 × 方向 契约矩阵 + Unknown Data 安全（任务书 §十五/§十六/§十七）。

三层断言，全部驱动**生产代码**（解析器 / 序列化器 / 响应解析）：

1. `Client × Capability`：每个客户端的语料都要 Parse + Normalize 成功；
2. `Client × Direction`：OneBot 11 客户端语料要能**反向序列化**（Parse → Serialize），
   且类型序列保持、丢失字段必须出现在 notes；
3. `Unknown × 3`：未知字段 / 未知段 / 未知事件 / 未知响应**都不能炸**，且已知字段必须完好
   （Unknown Data Safety Rate 的度量口径就是本文件这几条）。

语料来自 `tests/fixtures/<client>/`（每个文件带 _provenance）；没有语料的客户端不在这里假装跑过。
"""
import glob
import json
import os

import pytest

from src.adapters.client_profile import PROFILES, profile_for
from src.adapters.milky_parser import MilkyEventParser
from src.adapters.onebot12_parser import OneBot12EventParser
from src.adapters.onebot_parser import OneBotEventParser
from src.adapters.onebot_serializer import serialize_segments
from src.transport.onebot_response import parse_onebot_response

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
BOT_QQ = 10001

#: 目录名 → (协议, 解析器, 该协议是否有出站序列化)
CLIENTS = {
    "napcat": ("onebot11", OneBotEventParser),
    "go-cqhttp": ("onebot11", OneBotEventParser),
    "llbot": ("onebot11", OneBotEventParser),
    "onebot11": ("onebot11", OneBotEventParser),
    "milky": ("milky", MilkyEventParser),
    "onebot12": ("onebot12", OneBot12EventParser),
}

#: 档案里的客户端名与语料目录名不同时在这里映射
PROFILE_CLIENT = {"onebot11": "spec"}


def _fixtures(client: str):
    return sorted(glob.glob(os.path.join(FIXTURES, client, "*.json")))


def _cases():
    out = []
    for client in sorted(CLIENTS):
        for path in _fixtures(client):
            out.append((client, path))
    return out


CASES = _cases()


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _parse(client: str, raw: dict):
    protocol, parser_cls = CLIENTS[client]
    return parser_cls(bot_qq=BOT_QQ).parse(raw)


# ---------------------------------------------------------------- 1. Parse/Normalize

@pytest.mark.parametrize("client,path", CASES, ids=[("%s/%s" % (c, os.path.basename(p)))
                                                     for c, p in CASES])
def test_parse_and_normalize_per_client(client, path):
    ev = _parse(client, _load(path))
    assert ev.kind and ev.kind != "unknown", ev.kind
    assert ev.raw_data, "归一化后必须保留原始数据（unknown 安全的前提）"


# ---------------------------------------------------------------- 2. Serialize（方向二）

@pytest.mark.parametrize("client,path", [(c, p) for c, p in CASES if c in
                                         ("napcat", "go-cqhttp", "llbot", "onebot11")],
                         ids=[("%s/%s" % (c, os.path.basename(p)))
                              for c, p in CASES if c in ("napcat", "go-cqhttp", "llbot", "onebot11")])
def test_serialize_roundtrip_per_client(client, path):
    """Parse → Serialize：段类型序列保持；每个丢失字段都要有 note（不许静默丢）。"""
    raw = _load(path)
    ev = _parse(client, raw)
    profile = profile_for("onebot11", PROFILE_CLIENT.get(client, client))
    wire, notes = serialize_segments(ev.message_segments, profile=profile)
    inbound = [s.get("type") for s in (raw.get("message") or []) if isinstance(s, dict)]
    assert sorted(s["type"] for s in wire) == sorted(inbound), (inbound, wire)
    for note in notes:
        assert note.get("reason"), note


# ---------------------------------------------------------------- 3. Unknown 安全

def test_unknown_field_safety():
    """未知字段：不炸、进 raw_data、已知字段完好。"""
    raw = _load(os.path.join(FIXTURES, "napcat", "group_message_text_at_image.json"))
    raw["future_client_field"] = {"nested": [1, 2, 3]}
    ev = _parse("napcat", raw)
    assert ev.kind == "message" and ev.text == "看这个图"
    assert ev.raw_data["future_client_field"] == {"nested": [1, 2, 3]}


def test_unknown_segment_safety():
    """未知段：不炸、原样保留、其它段不受影响。"""
    raw = _load(os.path.join(FIXTURES, "napcat", "group_message_text_at_image.json"))
    raw["message"] = list(raw["message"]) + [{"type": "future_segment",
                                              "data": {"whatever": "值"}}]
    ev = _parse("napcat", raw)
    types = [s.get("type") for s in ev.message_segments]
    assert "future_segment" in types
    assert ev.text == "看这个图"          # 已知段仍被正确解析
    assert ev.images, ev.images          # 图片段没被未知段带崩


def test_unknown_event_safety():
    """未知事件类型：kind 原样保留（不是笼统 unknown），且不抛异常。"""
    ev = _parse("napcat", {"post_type": "future_event", "time": 1, "self_id": BOT_QQ,
                           "weird": True})
    assert ev.kind == "future_event"
    milky = _parse("milky", {"event_type": "future_milky_event", "time": 1,
                             "self_id": BOT_QQ})
    assert milky.kind == "future_milky_event"


def test_unknown_response_safety():
    """未知响应形态：不抛异常，失败要带原因。"""
    assert parse_onebot_response({"status": "future_status", "retcode": 0})["ok"] is False
    assert parse_onebot_response({"status": "ok", "retcode": 0,
                                  "future_field": 1})["ok"] is True
    assert parse_onebot_response(None)["ok"] is False


def test_unknown_segment_serialization_is_passthrough():
    """序列化未知段：原样传递 + note（不伪造支持、不丢内容）。"""
    wire, notes = serialize_segments([{"type": "future_segment", "data": {"a": 1}}],
                                     profile=profile_for("onebot11", "go-cqhttp"))
    assert wire == [{"type": "future_segment", "data": {"a": 1}}]
    assert notes and notes[0]["reason"]


# ---------------------------------------------------------------- 4. 档案自身的诚实性

def test_every_profile_has_evidence_and_source():
    """档案不允许"空口"条目：每个档案都要写清证据等级与出处。"""
    for (protocol, client), profile in PROFILES.items():
        assert profile.evidence in ("[CODE]", "[DOC]", "[MVP]", "[INFERENCE]", "[UNKNOWN]"), \
            (protocol, client, profile.evidence)
        assert profile.source, (protocol, client)
        assert profile.evidence != "[INFERENCE]" or client == "spec", \
            "推断不能作为客户端档案的依据"


def test_capability_matrix_is_reported(capsys):
    """打印 客户端 × 能力 矩阵（最终报告 §二十四 的数字来源）。"""
    caps = ("text", "at", "image", "reply", "face", "mface", "record", "video", "file",
            "json", "xml", "poke", "dice", "rps", "forward_segment")
    lines = ["客户端能力矩阵（档案登记值，未登记=UNKNOWN）：",
             "  %-18s %s" % ("client", " ".join("%-9s" % c for c in caps))]
    for (protocol, client), profile in sorted(PROFILES.items()):
        if protocol != "onebot11":
            continue
        lines.append("  %-18s %s" % (client, " ".join("%-9s" % profile.state(c) for c in caps)))
    print("\n".join(lines))
    assert len(PROFILES) >= 4

@pytest.mark.parametrize("protocol,marker", [
    ("onebot11", "client-matrix"),
    ("milky", "milky-matrix"),
])
def test_doc_matrix_matches_code(protocol, marker):
    """文档里的生成矩阵必须与 PROFILES 逐字一致（防文档漂移）。"""
    import re

    from src.adapters.client_profile import render_matrix

    doc = open(os.path.join(ROOT, "docs", "client-compatibility.md"), encoding="utf-8").read()
    pattern = ("<!-- BEGIN GENERATED: %s -->\n(.*?)\n<!-- END GENERATED: %s -->"
               % (marker, marker))
    block = re.search(pattern, doc, re.S)
    assert block, "文档里缺少生成矩阵标记：%s" % marker
    assert block.group(1).strip() == render_matrix(protocol).strip(), \
        "%s 矩阵与 client_profile.PROFILES 不一致：请重跑生成命令" % protocol


# ---------------------------------------------------------------- 自发送消息（跨客户端）

def test_self_sent_message_content_is_parsed_for_both_clients():
    """`message_sent` = 机器人自己发的消息：NapCat 与 go-cqhttp 都用它 [CODE]。

    kind 必须原样保留（上层按 kind 分派：`message_router` 只把 `"message"` 送进回复链路，
    所以不会造成自问自答），但**内容要照常解析** —— 否则机器人自己说的话在归一化层消失。
    """
    napcat = _parse("napcat", _load(os.path.join(FIXTURES, "napcat", "message_sent_self.json")))
    assert napcat.kind == "message_sent" and napcat.scope == "group"
    assert napcat.text == "我发的", napcat.text

    gocq = _parse("go-cqhttp", {
        "post_type": "message_sent", "message_type": "group", "sub_type": "normal",
        "time": 1, "self_id": BOT_QQ, "message_id": 1, "group_id": 2, "user_id": BOT_QQ,
        "message": [{"type": "text", "data": {"text": "我说"}}],
        "sender": {"user_id": BOT_QQ, "nickname": "bot"}})
    assert gocq.kind == "message_sent" and gocq.text == "我说", gocq.text


def test_napcat_temp_session_uses_top_level_group_id():
    """NapCat 把临时会话来源群放**顶层 group_id**（api/msg.ts L1163-1176）[CODE]，

    与 go-cqhttp 的 `sender.group_id` 形态归一化结果必须一致。
    """
    napcat = _parse("napcat", _load(os.path.join(FIXTURES, "napcat", "private_temp_message.json")))
    gocq = _parse("go-cqhttp", _load(os.path.join(FIXTURES, "go-cqhttp", "private_temp_message.json")))
    assert (napcat.scope, napcat.scene, napcat.context_group_id) == ("private", "temp", 123456)
    assert (napcat.scope, napcat.scene, napcat.context_group_id) == \
           (gocq.scope, gocq.scene, gocq.context_group_id)


def test_napcat_dice_rps_use_result_field():
    """同一段不同客户端不同字段名：NapCat `dice/rps{result}` vs go-cqhttp `{value}`。

    归一化层不做字段重命名（原样保留 segments），但**必须两种都收下、都不丢**。
    """
    ev = _parse("napcat", _load(os.path.join(FIXTURES, "napcat",
                                             "group_message_dice_rps_mface.json")))
    data = [s["data"] for s in ev.message_segments if s.get("type") in ("dice", "rps")]
    assert data and all("result" in d for d in data), data
    assert [f["kind"] for f in ev.faces] == ["face", "market_face"]
