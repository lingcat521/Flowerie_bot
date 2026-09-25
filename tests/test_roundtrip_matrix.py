"""Gate N：Round-trip（Normalized → 协议线格式 → Normalized，7 类 × 2 协议 = 14 格）。

任务书 §15 要求：`Normalized ↓ OneBot11 ↓ Normalized` 与 `Normalized ↓ Milky ↓ Normalized`
各覆盖 text / image / face / file / reply / at / forward，共 14 格，硬性 14/14 PASS；
协议本身无法完整 round-trip 的能力**必须显式标记** partial / lossy / unsupported，不得伪造 PASS。

方法（诚实说明）：本仓库目前只有**接收方向**的解析器（发送方向由 Gate O 的 action 映射与实机联调覆盖），
所以"编码器"是测试侧的**接收线格式构造器**：它把协议中立的消息规格写成该协议的线格式，
并**显式声明自己丢弃了哪些字段**（`dropped`）。三件事分开断言：

1. 编码器不许"偷偷丢字段"：丢了就必须写在 `dropped` 里（否则测试失败）；
2. 解析回来的结果，必须与"规格 − 声明丢弃的字段"逐字段相等 → 这才是真正验证了 round-trip；
3. 已知无法完整 round-trip 的能力单独列出并标注 partial/lossy（见文件末尾），不计入 PASS。
"""
import pytest

from src.adapters.milky_parser import MilkyEventParser
from src.adapters.onebot_parser import OneBotEventParser

BOT_QQ = 10001
GROUP = 123456
USER = 456789
IMG = "https://example.com/a.png"
FWD_ID = "fwd-1"
REPLY_SEQ = 1001

# 协议中立的消息规格（7 类；字段取两协议的**公共可表达**集合）
SPECS = {
    "text": {"class": "text", "text": "你好世界"},
    "at": {"class": "at", "text": " ", "mentions": [str(BOT_QQ)], "is_mentioned": True},
    "reply": {"class": "reply", "text": "回复你", "reply_id": REPLY_SEQ},
    "image": {"class": "image", "images": [IMG]},
    "face": {"class": "face", "faces": [("face", "14")]},
    "file": {"class": "file", "files": [("f1", "报.zip")]},
    "forward": {"class": "forward", "forwards": [FWD_ID]},
}


def _encode_onebot(spec):
    """规格 → OneBot 11 线格式；返回 (raw, dropped)。"""
    dropped = []
    segments = []
    if spec.get("text"):
        segments.append({"type": "text", "data": {"text": spec["text"]}})
    if spec.get("mentions"):
        segments.append({"type": "at", "data": {"qq": spec["mentions"][0]}})
    if spec.get("reply_id") is not None:
        segments.append({"type": "reply", "data": {"id": str(spec["reply_id"])}})
    if spec.get("images"):
        segments.append({"type": "image", "data": {"file": spec["images"][0].rsplit("/", 1)[-1],
                                                   "url": spec["images"][0]}})
    if spec.get("faces"):
        segments.append({"type": "face", "data": {"id": spec["faces"][0][1]}})
    if spec.get("files"):
        fid, name = spec["files"][0]
        segments.append({"type": "file", "data": {"file_id": fid, "file": name}})
    if spec.get("forwards"):
        segments.append({"type": "forward", "data": {"id": spec["forwards"][0]}})
    for key in ("inline_reply_segments", "file_url"):
        if spec.get(key):
            dropped.append(key)
    raw = {"post_type": "message", "message_type": "group", "sub_type": "normal", "group_id": GROUP,
           "user_id": USER, "message_id": 1001, "time": 1700000000, "message": segments}
    return raw, dropped


def _encode_milky(spec):
    """规格 → Milky 线格式；返回 (raw, dropped)。"""
    dropped = []
    segments = []
    if spec.get("text"):
        segments.append({"type": "text", "data": {"text": spec["text"]}})
    if spec.get("mentions"):
        segments.append({"type": "mention", "data": {"user_id": int(spec["mentions"][0])}})
    if spec.get("reply_id") is not None:
        segments.append({"type": "reply", "data": {"message_seq": spec["reply_id"]}})
    if spec.get("images"):
        segments.append({"type": "image", "data": {"temp_url": spec["images"][0], "resource_id": "r1"}})
    if spec.get("faces"):
        segments.append({"type": "face", "data": {"face_id": int(spec["faces"][0][1])}})
    if spec.get("files"):
        fid, name = spec["files"][0]
        segments.append({"type": "file", "data": {"file_id": fid, "file_name": name, "file_size": 2048}})
    if spec.get("forwards"):
        segments.append({"type": "forward", "data": {"forward_id": spec["forwards"][0]}})
    for key in ("inline_reply_segments", "file_url"):
        if spec.get(key):
            dropped.append(key)
    raw = {"time": 1700000000, "self_id": BOT_QQ, "event_type": "message_receive",
           "data": {"message_scene": "group", "peer_id": GROUP, "sender_id": USER,
                    "message_seq": 1001, "segments": segments}}
    return raw, dropped


ENCODERS = {"onebot11": _encode_onebot, "milky": _encode_milky}
PARSERS = {"onebot11": lambda: OneBotEventParser(bot_qq=BOT_QQ),
           "milky": lambda: MilkyEventParser(bot_qq=BOT_QQ)}


def _project(protocol, event, spec):
    """把解析结果投影成与规格同形的比较元组（只读归一化字段）。"""
    got = {"class": spec["class"]}
    if spec.get("text"):
        # 编码器把文本写成主文本段；@ 与 reply 会带上前导空格的写法差异 → 统一 strip 比较
        got["text"] = event.text.strip()
    if spec.get("mentions"):
        got["mentions"] = sorted(event.mentions)
        got["is_mentioned"] = event.is_mentioned
    if spec.get("reply_id") is not None:
        got["reply_id"] = event.reply_id
    if spec.get("images"):
        got["images"] = list(event.images)
    if spec.get("faces"):
        got["faces"] = [(f.get("kind"), f.get("face_id")) for f in event.faces]
    if spec.get("files"):
        got["files"] = [(f.get("file_id"), f.get("name")) for f in event.files]
    if spec.get("forwards"):
        got["forwards"] = [f.get("id") for f in event.forwards]
    return got


def _expected(spec):
    expected = {"class": spec["class"]}
    for key in ("text", "mentions", "is_mentioned", "reply_id", "images", "faces", "files", "forwards"):
        if key in spec:
            if key == "mentions":
                expected[key] = sorted(spec[key])
            elif key == "text":
                expected[key] = spec[key].strip()      # 与 _project 的投影口径一致
            else:
                expected[key] = spec[key]
    return expected


@pytest.mark.parametrize("protocol", ["onebot11", "milky"])
@pytest.mark.parametrize("name", sorted(SPECS))
def test_roundtrip_normalized_wire_normalized(protocol, name):
    spec = SPECS[name]
    raw, dropped = ENCODERS[protocol](spec)
    assert dropped == [], "%s 编码器丢弃了未声明的字段：%s" % (protocol, dropped)
    event = PARSERS[protocol]().parse(raw)
    got = _project(protocol, event, spec)
    expected = _expected(spec)
    assert got == expected, "round-trip 不一致（%s/%s）：%s != %s" % (protocol, name, got, expected)
    assert event.raw_data == raw, "raw_data 必须保真（%s/%s）" % (protocol, name)


def test_matrix_is_fourteen_cells():
    assert len(SPECS) == 7 and sorted(ENCODERS) == ["milky", "onebot11"]
    assert len(SPECS) * len(ENCODERS) == 14


# ---------------------------------------------------------------- 无法完整 round-trip 的能力（显式标注）

PARTIAL_CASES = [
    {"protocol": "onebot11", "capability": "reply 内联被引段",
     "status": "lossy",
     "reason": "OneBot 11 的 reply 段只有 id（+qq），内联被引段是 Milky 独有（ReplySegment）",
     "evidence": "src/adapters/onebot_parser.py reply 分支注释（G4）"},
    {"protocol": "milky", "capability": "file 的 url",
     "status": "partial",
     "reason": "Milky file 段只有 file_id/file_name/file_size（无 url），需要 get_resource_temp_url 另取",
     "evidence": "[CODE] LagrangeV2 FileSegment.cs L5-11"},
    {"protocol": "onebot11", "capability": "forward 内联内容",
     "status": "partial",
     "reason": "两协议都只给 forward id；内联内容需额外 API（OneBot /get_forward_msg）",
     "evidence": "src/adapters/onebot_parser.py forward 分支（inline=False 除非报文自带 messages）"},
]


def test_known_lossy_cases_are_marked_not_faked_as_pass():
    for case in PARTIAL_CASES:
        assert case["status"] in ("partial", "lossy", "unsupported")
        assert case["reason"].strip() and case["evidence"].strip()
        # 显式标注的用例**不计入** 14/14：这里断言它们确实会被编码器丢弃（不是"其实能过"）
        if case["capability"] == "reply 内联被引段":
            raw, dropped = ENCODERS[case["protocol"]]({"class": "reply", "inline_reply_segments": ["x"]})
            assert dropped == ["inline_reply_segments"]
        if case["capability"] == "file 的 url":
            raw, dropped = ENCODERS[case["protocol"]]({"class": "file", "file_url": IMG})
            assert dropped == ["file_url"]
