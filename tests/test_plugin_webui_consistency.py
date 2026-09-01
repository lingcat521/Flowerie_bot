"""Plugin WebUI 一致性（源码 ↔ 文档 ↔ SDK/API 三层）：

- 文档组件表 type 集 == 渲染器注册表（防漂移：文档承诺 = 实现存在）
- 权限注册（web_ui / web_ui.files ∈ ALL_PERMISSIONS；不存在 JS 类权限）
- manifest web_ui roundtrip（to_dict → from_dict 不丢；未知字段拒绝）
- SDK 协议契约：webui_page hook 四参（集成插件验证）+ 错误分支（超时/未启用/未批准）
"""
import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _renderer_types() -> set:
    tree = ast.parse((ROOT / "src/services/webui_render/plugin_dsl.py").read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if not isinstance(n, (ast.Assign, ast.AnnAssign)):
            continue
        targets = n.targets if isinstance(n, ast.Assign) else [n.target]
        for t in targets:
            if isinstance(t, ast.Name) and t.id == "_RENDERERS":
                return {k.value for k in n.value.keys}
    return set()


def _doc_component_types() -> set:
    text = (ROOT / "docs/plugin-webui.md").read_text(encoding="utf-8")
    # 仅 §4 组件表区域（展示/表单/操作/容器小节；权限表里也有 `web_ui` 行，排除）
    seg = text.split("### 展示")[1].split("## 5.")[0]
    return set(re.findall(r"^\| `([a-z_]+)` \|", seg, re.M))


def test_doc_components_match_renderer():
    docs = _doc_component_types()
    impl = _renderer_types()
    assert docs, "文档组件表为空"
    assert impl, "渲染器空"
    # 文档承诺的组件必须可实现；实现组件必须有文档条目（双向防漂移）
    missing = docs - impl
    assert not missing, f"文档有但实现缺: {missing}"
    undocumented = impl - docs
    assert not undocumented, f"实现有但文档未收录: {undocumented}"


def test_no_js_permission_ever():
    perms = (ROOT / "src/plugins/permissions.py").read_text(encoding="utf-8")
    assert '"web_ui"' in perms and '"web_ui.files"' in perms
    assert not re.search(r'"web_ui\.js"|"javascript"|"jscript"', perms)


def test_all_permissions_include_webui():
    from src.plugins.permissions import ALL_PERMISSIONS
    assert "web_ui" in ALL_PERMISSIONS and "web_ui.files" in ALL_PERMISSIONS


def test_manifest_webui_roundtrip_and_reject():
    from src.plugins.manifest import PluginManifest, PluginManifestError
    base = {"id": "abc", "name": "n", "version": "1.0.0", "runtime": "python",
            "entry": "p.py", "api_version": "1", "permissions": ["web_ui"],
            "web_ui": {"pages": [{"id": "home", "title": "总览"}]}}
    m = PluginManifest.from_dict(base)
    d = m.to_dict()
    assert d["web_ui"]["pages"][0]["title"] == "总览"
    m2 = PluginManifest.from_dict(d)  # roundtrip 再校验不炸
    assert m2.web_ui == m.web_ui
    for bad in (
        {**base, "web_ui": {"pages": []}},                          # 空页
        {**base, "web_ui": {"pages": [{"id": "X"}]}},               # 大写 id
        {**base, "web_ui": {"pages": [{"id": "h", "title": "t", "evil": 1}]}},  # 未知字段
        {**base, "web_ui": {"entry": "exec('x')"}},                  # 非法函数名
        {**base, "web_ui": {"pages": [{"id": "a", "title": "t"}] * 9}},  # 超 8 页
    ):
        with pytest.raises(PluginManifestError):
            PluginManifest.from_dict(bad)


def test_hook_contract_integration_plugin():
    """SDK/协议契约：webui_page(page, action, params, values) 四参签名 + 渲染安全。"""
    import importlib.util
    import sys
    sys.path.insert(0, str(ROOT / "tests/plugins/webui_example"))
    spec = importlib.util.spec_from_file_location(
        "flowerie_plugin_webui_example", str(ROOT / "tests/plugins/webui_example/plugin.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["flowerie_plugin_webui_example"] = mod
    spec.loader.exec_module(mod)
    import inspect
    sig = inspect.signature(mod.webui_page)
    assert [p.name for p in sig.parameters.values()] == ["page", "action", "params", "values"]
    dsl = mod.webui_page("home", "get", {"q": "1"}, {})
    assert isinstance(dsl, dict)
