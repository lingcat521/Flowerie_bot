"""Phase 3-4 Web UI 高级记忆门控渲染测试（零 JS；本地可跑，不依赖 pydantic）。"""
from src.services.webui_render.config_panel import (
    _living_on,
    _sub_switch_on,
    render_config_sections,
)


def _cfg(key, current="false", ctype="bool"):
    return {"key": key, "current": current, "type": ctype, "category": "LivingMemory",
            "description": key, "secret": False, "hot_reload": True}


def _living_cfgs(total="false", embed="false", rerank="false", extract="false", retriev="false"):
    return [
        _cfg("LIVING_MEMORY_ENABLED", total),
        _cfg("LIVING_MEMORY_EMBEDDING_ENABLED", embed),
        _cfg("LIVING_MEMORY_RERANKER_ENABLED", rerank),
        _cfg("LIVING_MEMORY_EXTRACT_ENABLED", extract),
        _cfg("LIVING_MEMORY_RETRIEVAL_ENABLED", retriev),
        _cfg("LIVING_MEMORY_EMBEDDING_MODEL", "", "str"),
        _cfg("LIVING_MEMORY_RERANKER_MODEL", "", "str"),
        _cfg("LIVING_MEMORY_VECTOR_DIMENSION", "1024", "int"),
    ]


_ORDER = ["LivingMemory"]
_LABELS = {"LivingMemory": "高级记忆（默认关闭）"}


def test_living_default_off_hides_all():
    html = render_config_sections([_cfg("LIVING_MEMORY_ENABLED", "false")
                                   | {"category": "LivingMemory"}]
                                  + [_cfg(k, "false") | {"category": "LivingMemory"}
                                     for k in ("LIVING_MEMORY_EMBEDDING_ENABLED",
                                               "LIVING_MEMORY_EMBEDDING_MODEL")],
                                  category_order=_ORDER, category_labels=_LABELS)
    # 总开关显示；子开关与模型配置不渲染
    assert "LIVING_MEMORY_ENABLED" in html
    assert "LIVING_MEMORY_EMBEDDING_ENABLED" not in html
    assert "LIVING_MEMORY_EMBEDDING_MODEL" not in html
    assert "<details" in html and "<summary" in html  # 原生折叠
    assert "script" not in html.lower()                # 零 JS


def test_living_on_shows_sub_switches_but_hides_off_sub_config():
    cfgs = _living_cfgs(total="true", embed="false", rerank="true")
    for c in cfgs:
        c["category"] = "LivingMemory"
        c["description"] = c["key"]
    html = render_config_sections(cfgs, category_order=_ORDER, category_labels=_LABELS)
    assert "LIVING_MEMORY_EMBEDDING_ENABLED" in html      # 子开关显示
    assert "LIVING_MEMORY_RERANKER_ENABLED" in html
    assert "LIVING_MEMORY_EMBEDDING_MODEL" not in html    # embedding 关 → 模型键隐藏
    assert "LIVING_MEMORY_RERANKER_MODEL" in html         # rerank 开 → 模型键显示
    assert "LIVING_MEMORY_VECTOR_DIMENSION" in html       # 参数键：总开关 ON 时显示


def test_gate_helpers():
    cfgs = _living_cfgs(total="true", embed="true")
    assert _living_on(cfgs) is True
    assert _sub_switch_on(cfgs, "LIVING_MEMORY_EMBEDDING_MODEL") is True
    assert _sub_switch_on(cfgs, "LIVING_MEMORY_RERANKER_MODEL") is False
    assert _sub_switch_on(cfgs, "LIVING_MEMORY_VECTOR_DIMENSION") is True  # 未归属键仅受总开关
