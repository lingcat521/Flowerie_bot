"""Phase 3-4 Web UI 高级记忆门控渲染测试（零 JS；本地可跑，不依赖 pydantic）。"""
from src.services.webui_render.config_panel import (
    _blossom_on,
    _blossom_sub_switch_on,
    render_config_sections,
)


def _cfg(key, current="false", ctype="bool"):
    return {"key": key, "current": current, "type": ctype, "category": "BlossomMemory",
            "description": key, "secret": False, "hot_reload": True}


def _living_cfgs(total="false", embed="false", rerank="false", extract="false", retriev="false"):
    return [
        _cfg("BLOSSOM_MEMORY_ENABLED", total),
        _cfg("BLOSSOM_MEMORY_EMBEDDING_ENABLED", embed),
        _cfg("BLOSSOM_MEMORY_RERANKER_ENABLED", rerank),
        _cfg("BLOSSOM_MEMORY_EXTRACT_ENABLED", extract),
        _cfg("BLOSSOM_MEMORY_RETRIEVAL_ENABLED", retriev),
        _cfg("BLOSSOM_MEMORY_EMBEDDING_MODEL", "", "str"),
        _cfg("BLOSSOM_MEMORY_RERANKER_MODEL", "", "str"),
        _cfg("BLOSSOM_MEMORY_VECTOR_DIMENSION", "1024", "int"),
    ]


_ORDER = ["BlossomMemory"]
_LABELS = {"BlossomMemory": "高级记忆（默认关闭）"}


def test_blossom_default_off_hides_all():
    html = render_config_sections([_cfg("BLOSSOM_MEMORY_ENABLED", "false")
                                   | {"category": "BlossomMemory"}]
                                  + [_cfg(k, "false") | {"category": "BlossomMemory"}
                                     for k in ("BLOSSOM_MEMORY_EMBEDDING_ENABLED",
                                               "BLOSSOM_MEMORY_EMBEDDING_MODEL")],
                                  category_order=_ORDER, category_labels=_LABELS)
    # 总开关显示；子开关与模型配置不渲染
    assert "BLOSSOM_MEMORY_ENABLED" in html
    assert "BLOSSOM_MEMORY_EMBEDDING_ENABLED" not in html
    assert "BLOSSOM_MEMORY_EMBEDDING_MODEL" not in html
    assert "<details" in html and "<summary" in html  # 原生折叠
    assert "script" not in html.lower()                # 零 JS


def test_blossom_on_shows_sub_switches_but_hides_off_sub_config():
    cfgs = _living_cfgs(total="true", embed="false", rerank="true")
    for c in cfgs:
        c["category"] = "BlossomMemory"
        c["description"] = c["key"]
    html = render_config_sections(cfgs, category_order=_ORDER, category_labels=_LABELS)
    assert "BLOSSOM_MEMORY_EMBEDDING_ENABLED" in html      # 子开关显示
    assert "BLOSSOM_MEMORY_RERANKER_ENABLED" in html
    assert "BLOSSOM_MEMORY_EMBEDDING_MODEL" not in html    # embedding 关 → 模型键隐藏
    assert "BLOSSOM_MEMORY_RERANKER_MODEL" in html         # rerank 开 → 模型键显示
    assert "BLOSSOM_MEMORY_VECTOR_DIMENSION" in html       # 参数键：总开关 ON 时显示


def test_gate_helpers():
    cfgs = _living_cfgs(total="true", embed="true")
    assert _blossom_on(cfgs) is True
    assert _blossom_sub_switch_on(cfgs, "BLOSSOM_MEMORY_EMBEDDING_MODEL") is True
    assert _blossom_sub_switch_on(cfgs, "BLOSSOM_MEMORY_RERANKER_MODEL") is False
    assert _blossom_sub_switch_on(cfgs, "BLOSSOM_MEMORY_VECTOR_DIMENSION") is True  # 未归属键仅受总开关


# ---------- 折叠规则：全部视图平铺；特定分类折叠 ----------
def test_all_view_flat_all_categories_open():
    from src.services.webui_render.config_panel import render_config_sections
    cfgs = [
        _cfg("AI_ENABLED", "true") | {"category": "AI"},
        _cfg("BLOSSOM_MEMORY_ENABLED", "false"),
    ]
    html = render_config_sections(cfgs, active_cat="all",
                                  category_order=["AI", "BlossomMemory"],
                                  category_labels={"AI": "AI 配置", "BlossomMemory": "花语记忆"})
    # 全部视图：每个分类 details 都带 open（平铺，不折叠）
    assert html.count('<details class="cfg-group" open>') == 2, "全部视图应平铺"


def test_specific_view_also_open():
    from src.services.webui_render.config_panel import render_config_sections
    cfgs = [
        _cfg("AI_ENABLED", "true") | {"category": "AI"},
        _cfg("BLOSSOM_MEMORY_ENABLED", "false"),
    ]
    html = render_config_sections(cfgs, active_cat="AI",
                                  category_order=["AI", "BlossomMemory"],
                                  category_labels={"AI": "AI 配置", "BlossomMemory": "花语记忆"})
    # 特定分类视图同样默认展开（用户要求所有分类不折叠）；分类本身只显示选中项
    assert html.count('<details class="cfg-group" open>') == 1, "特定分类默认展开"
