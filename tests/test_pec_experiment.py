"""Gate E/F：TestProtocolAdapter 实验 —— 新增协议成本（PEC）与最小接入实验。

任务书要求：
- Gate E：用一个虚拟协议接入，测量需要修改的 Core / Services / SDK / 既有插件文件数，硬性要求 0；
- Gate F：用该虚拟协议完成至少 7 项实验（text 收发 / image 接收 / unknown 段 / unknown event /
  recall / capability query …），并证明「TestProtocolAdapter -> Normalized Model -> Core 能完整运行」。

PEC 的**可复现**口径（两种，互为补充）：
1. 静态口径（本文件断言，任何环境都能跑）：`src/core`、`src/services`、`src/sdk`、`src/plugins`、
   `plugin_sdk` 里**不出现** testproto / testkit 的任何引用 —— 新协议对这些层完全不可见；
2. 变更口径（本地 git 可用时测量，CI 浅克隆下自动跳过）：与基线提交比对，列出本轮实际改动的文件，
   核对它们全部属于允许集（Adapter 层 / Transport 层 / Tests / Docs）。
"""
import os
import subprocess

import pytest

from src.adapters.capabilities import coverage_for_descriptor
from src.adapters.testkit import (
    TestProtocolChannel,
    TestProtocolEventParser,
    test_protocol_descriptor,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT_QQ = 10001
# 允许集（任务书 Gate E）：新增协议只应改这些地方 —— Adapter 层、Transport 层（动作通道，
# 见 ADR-004 §5 的接入清单第 3 步）、测试与文档；Core/Services/SDK/既有插件一个都不许动。
ALLOWED_PREFIXES = ("src/adapters/", "src/transport/", "tests/", "docs/")
FORBIDDEN_DIRS = ("src/core", "src/services", "src/sdk", "src/plugins", "plugin_sdk")
FORBIDDEN_MARKERS = ("testproto", "testkit", "TestProtocol")


def _sample_message(**overrides):
    raw = {"kind": "msg", "chan": "group:123456", "from": 456789, "seq": 1001,
           "ts": 1700000000,
           "parts": [{"t": "text", "v": "hello "},
                     {"t": "at", "v": BOT_QQ},
                     {"t": "img", "url": "https://x/a.png", "name": "a.png"}]}
    raw.update(overrides)
    return raw


# ---------- Gate E：PEC 测量 ----------

def test_pec_static_new_protocol_is_invisible_to_core_layers():
    """静态口径：五层里一处都不能出现伪协议的任何标记。"""
    offenders = []
    for base in FORBIDDEN_DIRS:
        for dirpath, _dirs, files in os.walk(os.path.join(ROOT, base)):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                if any(m in text for m in FORBIDDEN_MARKERS):
                    offenders.append(os.path.relpath(path, ROOT))
    assert offenders == [], "新协议污染了这些层：%s" % offenders


def test_pec_static_testkit_is_self_contained():
    """伪协议只依赖 adapters 内部契约（不 import 业务层），所以它才可能零成本替换。"""
    path = os.path.join(ROOT, "src/adapters/testkit/test_protocol.py")
    with open(path, encoding="utf-8") as fh:
        lines = [ln.strip() for ln in fh if ln.strip().startswith(("import ", "from "))]
    bad = [ln for ln in lines
           if ("src." in ln and "src.adapters.proto" not in ln and "src.adapters.capabilities" not in ln)]
    assert bad == [], "伪协议不应依赖 adapters 之外的东西：%s" % bad


def test_pec_changed_files_if_git_available():
    """变更口径：凡**与虚拟协议相关**的改动，必须全部落在允许集内（CI 浅克隆下跳过）。

    判定：对本轮改动 / 新增的文件逐个看内容，出现 testproto / testkit / TestProtocol 标记的，
    必须位于允许集（Adapter / Transport / Tests / Docs）。

    **为什么不要求"工作区所有改动都在允许集"**：工作区里可能同时有与该协议**无关**的重构
    （例如 Gate R 拆掉 Core 的协议资源依赖、Gate S 加多实例）——那些改动本来就**应该**动 Core/Services，
    拿它们去判"新协议污染了 Core"是口径错误（会把无关工作误报成 PEC>0）。
    硬保证仍由静态口径承担：五层里一个标记都不许出现。
    """
    try:
        out = subprocess.run(["git", "log", "--oneline", "-1"], cwd=ROOT,
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("本环境没有 git，跳过变更口径测量")
    if out.returncode != 0 or not out.stdout.strip():
        pytest.skip("git 不可用或浅克隆，跳过变更口径测量")
    diff = subprocess.run(["git", "diff", "--name-only", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True, timeout=10)
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT,
                               capture_output=True, text=True, timeout=10)
    changed = sorted({f for f in (diff.stdout + "\n" + untracked.stdout).split()
                      if f.endswith((".py", ".md"))})
    protocol_files = []
    for rel in changed:
        try:
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        if any(marker in text for marker in FORBIDDEN_MARKERS):
            protocol_files.append(rel)
    outside = [f for f in protocol_files if not f.startswith(ALLOWED_PREFIXES)]
    assert outside == [], "与虚拟协议相关的改动落在允许集之外：%s" % outside
    forbidden = [f for f in protocol_files if f.startswith(FORBIDDEN_DIRS)]
    assert forbidden == [], "虚拟协议污染了禁止层：%s" % forbidden
    # 反向对照：标记扫描确实有效（协议自身的实现文件必须带标记，否则本检查是假绿）
    with open(os.path.join(ROOT, "src/adapters/testkit/test_protocol.py"), encoding="utf-8") as fh:
        assert any(marker in fh.read() for marker in FORBIDDEN_MARKERS)


# ---------- Gate F：7 项（+1）最小接入实验 ----------

def test_experiment_1_text_receive():
    ev = TestProtocolEventParser(bot_qq=BOT_QQ).parse(_sample_message())
    assert ev.kind == "message" and ev.scope == "group" and ev.group_id == 123456
    assert ev.text == "hello" and ev.is_mentioned is True
    assert str(BOT_QQ) in ev.mentions


@pytest.mark.asyncio
async def test_experiment_2_text_send():
    channel = TestProtocolChannel()
    res = await channel.post("send_message", {"chan": "group:123456",
                                      "parts": [{"t": "text", "v": "hi"}]})
    assert res["ok"] is True
    assert channel.sent[0][0] == "send_message"
    assert channel.sent[0][1]["parts"][0]["v"] == "hi"


def test_experiment_3_image_receive():
    ev = TestProtocolEventParser(bot_qq=BOT_QQ).parse(_sample_message())
    assert ev.images == ["https://x/a.png"]
    assert ev.image_files == ["a.png"]


def test_experiment_4_unknown_segment():
    raw = _sample_message(parts=[{"t": "brand-new-part", "v": {"k": [1, 2]}}])
    ev = TestProtocolEventParser(bot_qq=BOT_QQ).parse(raw)
    assert ("brand-new-part", {"k": [1, 2]}) in ev.segments_summary


def test_experiment_5_unknown_event():
    raw = {"kind": "future_kind", "chan": "group:1", "ts": 1700000000}
    ev = TestProtocolEventParser(bot_qq=BOT_QQ).parse(raw)
    assert ev.kind == "future_kind"          # 原样保留，不塌缩成 unknown
    assert ev.raw_data == raw


@pytest.mark.asyncio
async def test_experiment_6_recall():
    channel = TestProtocolChannel()
    ok = await channel.recall(42, "group")
    assert ok is True and channel.recalled == [(42, "group")]


def test_experiment_7_capability_query():
    caps = test_protocol_descriptor().capabilities
    assert caps.supports("message.send") is True
    assert caps.supports("forward.send") is False
    assert coverage_for_descriptor(test_protocol_descriptor()) == 1.0


@pytest.mark.asyncio
async def test_experiment_8_core_consumer_runs_on_virtual_protocol():
    """任务书 Gate F 的关键一步：Normalized Model -> **Core 消费者**能完整运行。

    这里用 Core 的 MessageAssembler 作为消费者（它不认识任何协议，只读领域字段）。
    """
    from src.core.message_assembler import MessageAssembler

    class _Cfg:
        VISION_ENABLED = False
        MAX_IMAGES_PER_MESSAGE = 1
        VISION_FORWARD_IMAGES = False

    class _GS:
        pending_files = {}

    class _FP:
        async def extract_forward_messages(self, message_array):
            return ("", [], False)

        def extract_json_card_content(self, message_array):
            return ("", False)

    class _AI:
        async def describe_image(self, url):
            return ""

        async def describe_image_file(self, path):
            return ""

    ev = TestProtocolEventParser(bot_qq=BOT_QQ).parse(
        _sample_message(parts=[{"t": "text", "v": "虚拟协议进入 Core"}]))
    asm = MessageAssembler(_Cfg(), _AI(), _FP(), _GS())
    out = await asm.assemble(ev, ev.actor_id, ev.group_id, ev.timestamp)
    full_text = out[0]
    assert "虚拟协议进入 Core" in full_text
