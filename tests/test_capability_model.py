"""Gate G/H：能力模型（Capability Model）验收。

任务书要求：
- Gate G：当前已明确存在的能力 100% 能映射到 Capability Model，覆盖率 ≥95%；
- Gate H：每项能力的**状态必须显式**（supported / partial / emulated / unsupported / unknown），
  且 `unknown` 不得被自动当作 `unsupported`。

本测试同时钉住"诚实性"：任何非 supported 的状态都必须写明理由（note），
避免出现"标了 partial 却不知道 partial 在哪"的情况。
"""
import pytest

from src.adapters.capabilities import (
    CANONICAL_CAPABILITIES,
    AdapterDescriptor,
    Capability,
    CapabilitySet,
    CapState,
    capability_coverage,
    descriptors,
    get_descriptor,
)

REGISTERED = ("onebot11", "milky", "onebot12")

# 任务书 Gate G 明列的 18 项能力（写成字面量，防止实现里悄悄改名/漏项）
GATE_G_LIST = (
    "message.send", "message.receive", "message.recall",
    "image.receive", "image.send",
    "face.receive", "face.send",
    "market_face.receive", "market_face.send",
    "file.receive", "file.send",
    "forward.receive", "forward.send",
    "card.receive", "poke.receive", "group_upload.receive",
    "markdown.receive", "light_app.receive",
)


def test_capability_list_matches_task_book():
    assert tuple(CANONICAL_CAPABILITIES) == GATE_G_LIST


@pytest.mark.parametrize("pid", REGISTERED)
def test_gate_h_every_capability_has_explicit_state(pid):
    caps = get_descriptor(pid).capabilities
    missing = [c for c in CANONICAL_CAPABILITIES if not caps.declared(c)]
    assert missing == [], "%s 未显式声明状态的能力：%s" % (pid, missing)
    for c in CANONICAL_CAPABILITIES:
        assert caps.state(c) in CapState.VALID


@pytest.mark.parametrize("pid", REGISTERED)
def test_gate_g_coverage_at_least_95_percent(pid):
    assert capability_coverage(pid) >= 0.95


@pytest.mark.parametrize("pid", REGISTERED)
def test_non_supported_states_must_explain_why(pid):
    """诚实性规则（本文件自定）：
    - partial / emulated 必须**逐条**写明理由（它们最容易含糊）；
    - unsupported / unknown 允许由描述符级 note 统一说明（例如"骨架未接线发送路径"），
      但描述符级 note 必须存在 —— 不允许整片状态没有解释。
    """
    d = get_descriptor(pid)
    caps = d.capabilities
    need_note = (CapState.PARTIAL, CapState.EMULATED)
    unexplained = [c for c in CANONICAL_CAPABILITIES
                   if caps.state(c) in need_note and not caps.note(c)]
    assert unexplained == [], "%s 这些 partial/emulated 能力没写理由：%s" % (pid, unexplained)
    vague = [c for c in CANONICAL_CAPABILITIES
             if caps.state(c) in (CapState.UNSUPPORTED, CapState.UNKNOWN) and not caps.note(c)]
    if vague:
        assert d.note, "%s 有 %d 项 unsupported/unknown 且描述符级也没说明" % (pid, len(vague))


def test_unknown_is_not_treated_as_unsupported():
    # 未声明的能力必须返回 unknown，而不是被悄悄当成 unsupported
    caps = CapabilitySet(states={Capability.MESSAGE_SEND: CapState.SUPPORTED})
    assert caps.state("future.capability") == CapState.UNKNOWN
    assert caps.supports("future.capability") is False
    assert CapState.UNKNOWN != CapState.UNSUPPORTED


def test_invalid_state_is_rejected():
    with pytest.raises(ValueError):
        CapabilitySet(states={Capability.MESSAGE_SEND: "probably-works"})


def test_descriptor_sanity():
    seen = set()
    for pid, d in descriptors().items():
        assert isinstance(d, AdapterDescriptor)
        assert d.protocol_id == pid and pid not in seen
        seen.add(pid)
        assert d.version and d.transports, pid
        assert d.capabilities.as_dict(), pid


def test_registry_reports_unknown_protocol_clearly():
    with pytest.raises(KeyError) as e:
        get_descriptor("telepathy")
    assert "未登记的协议" in str(e.value)


def test_milky_image_send_documented_as_unsupported_gap():
    # 缺口台账 G5（多媒体上传管道）在能力模型里必须可见，不能悄悄标成 supported
    caps = get_descriptor("milky").capabilities
    assert caps.state(Capability.IMAGE_SEND) == CapState.UNSUPPORTED
    assert "G5" in caps.note(Capability.IMAGE_SEND)


def test_onebot11_supported_receive_side_matches_docs():
    # 与 client-compatibility.md 的能力矩阵对齐（接收侧已建模的项）
    caps = get_descriptor("onebot11").capabilities
    for c in (Capability.MESSAGE_RECEIVE, Capability.IMAGE_RECEIVE, Capability.FACE_RECEIVE,
              Capability.MARKET_FACE_RECEIVE, Capability.FILE_RECEIVE, Capability.FORWARD_RECEIVE,
              Capability.CARD_RECEIVE, Capability.POKE_RECEIVE, Capability.GROUP_UPLOAD_RECEIVE,
              Capability.MARKDOWN_RECEIVE, Capability.LIGHT_APP_RECEIVE):
        assert caps.supports(c), c


def test_onebot12_uses_unknown_not_unsupported_where_evidence_missing():
    caps = get_descriptor("onebot12").capabilities
    assert caps.state(Capability.FORWARD_RECEIVE) == CapState.UNKNOWN
    assert caps.state(Capability.FACE_RECEIVE) == CapState.UNKNOWN


def test_capability_set_reports_notes():
    caps = get_descriptor("milky").capabilities
    assert "group_nudge" in caps.note(Capability.POKE_RECEIVE)
