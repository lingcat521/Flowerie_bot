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
    # 总开关显示；子开关（功能门控）不渲染；但模型/API 配置始终渲染（先见才能配）
    assert "BLOSSOM_MEMORY_ENABLED" in html
    assert "BLOSSOM_MEMORY_EMBEDDING_ENABLED" not in html
    assert "BLOSSOM_MEMORY_EMBEDDING_MODEL" in html
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
    assert "BLOSSOM_MEMORY_EMBEDDING_MODEL" in html        # 模型配置始终显示（不再隐藏）
    assert "BLOSSOM_MEMORY_RERANKER_MODEL" in html
    assert "BLOSSOM_MEMORY_VECTOR_DIMENSION" in html       # 参数键：总开关 ON 时显示


def test_gate_helpers():
    cfgs = _living_cfgs(total="true", embed="true")
    assert _blossom_on(cfgs) is True
    assert _blossom_sub_switch_on(cfgs, "BLOSSOM_MEMORY_EMBEDDING_MODEL") is True
    assert _blossom_sub_switch_on(cfgs, "BLOSSOM_MEMORY_RERANKER_MODEL") is True   # 模型配置始终渲染
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


# ---------- 模型配置链状态徽标 ----------
def test_model_status_badges():
    from src.services.webui_render.config_panel import render_config_sections
    cfgs = [
        _cfg("BLOSSOM_MEMORY_ENABLED", "true"),
        _cfg("BLOSSOM_MEMORY_EMBEDDING_ENABLED", "true"),
        _cfg("BLOSSOM_MEMORY_EMBEDDING_MODEL", "text-embedding-3-small", "str"),
        _cfg("BLOSSOM_MEMORY_EMBEDDING_API_URL", "http://127.0.0.1:1/v1", "str"),
        _cfg("BLOSSOM_MEMORY_EMBEDDING_API_KEY", "abc12345"),
        _cfg("BLOSSOM_MEMORY_RERANKER_ENABLED", "true"),
        _cfg("BLOSSOM_MEMORY_RERANKER_MODEL", "", "str"),
        _cfg("BLOSSOM_MEMORY_RERANKER_API_URL", "", "str"),
    ]
    html = render_config_sections([c | {"category": "BlossomMemory"} for c in cfgs],
                                  category_order=["BlossomMemory"],
                                  category_labels={"BlossomMemory": "花语记忆"})
    assert "已配置" in html, "embedding 配置齐全应显示已配置"
    assert "⚠️ 缺模型或地址" in html, "reranker 缺配置应显示警告"


def test_model_status_badge_disabled():
    from src.services.webui_render.config_panel import render_config_sections
    cfgs = [
        _cfg("BLOSSOM_MEMORY_ENABLED", "false"),
        _cfg("BLOSSOM_MEMORY_EMBEDDING_MODEL", "", "str"),
    ]
    html = render_config_sections([c | {"category": "BlossomMemory"} for c in cfgs],
                                  category_order=["BlossomMemory"],
                                  category_labels={"BlossomMemory": "花语记忆"})
    assert "未启用" in html, "链关闭应显示未启用"
    assert "⚠️" not in html, "链关闭不应报缺配置"


def test_model_ping_button_rendered():
    """模型行内联「测」按钮（零 JS 表单目标 /panel/test/model）。"""
    from src.services.webui_render.config_panel import render_config_sections
    cfgs = [
        _cfg("BLOSSOM_MEMORY_ENABLED", "true"),
        _cfg("BLOSSOM_MEMORY_EMBEDDING_ENABLED", "true"),
        _cfg("BLOSSOM_MEMORY_EMBEDDING_MODEL", "m", "str"),
        _cfg("BLOSSOM_MEMORY_RERANKER_ENABLED", "true"),
        _cfg("BLOSSOM_MEMORY_RERANKER_MODEL", "m", "str"),
    ]
    html = render_config_sections([c | {"category": "BlossomMemory"} for c in cfgs],
                                  category_order=["BlossomMemory"],
                                  category_labels={"BlossomMemory": "花语记忆"})
    # 配置页行内测按钮已移除（连通性测试统一在用户状态页）；不残留 target 表单
    assert html.count('action="/panel/test/model"') == 0, "配置页不应再内嵌测试表单"
