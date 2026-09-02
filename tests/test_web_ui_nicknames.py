"""群特色昵称：核心逻辑（store / 渲染 / 表单解析）——避 pydantic 链（面板集成归 CI Web UI 套件）。"""
import importlib.util
import sys
from pathlib import Path

from src.services.group_nicknames import GroupNicknameStore
from src.services.webui_render.nicknames import render_nicknames_tab

# webui_panels 包 __init__ 会拉 pydantic 链——直载模块（本地无 pydantic-core）
_spec = importlib.util.spec_from_file_location(
    "_np", Path(__file__).resolve().parents[1] / "src/services/webui_panels/nickname_panel.py")
_np = importlib.util.module_from_spec(_spec)
sys.modules["_np"] = _np
_spec.loader.exec_module(_np)
apply_nicknames_form = _np.apply_nicknames_form


def test_render_shows_default_and_rows(tmp_path):
    store = GroupNicknameStore(str(tmp_path / "n.json"))
    store.set(111, "小彩")
    html = render_nicknames_tab(store.all(), "花璃")
    assert "花璃" in html and "111" in html and "小彩" in html
    # XSS 转义：昵称 HTML 不破坏结构
    store.set(222, "<script>x</script>")
    html2 = render_nicknames_tab(store.all(), "花璃")
    assert "<script>x</script>" not in html2  # 已转义
    assert "&lt;script&gt;" in html2


def test_save_updates_and_clears(tmp_path):
    store = GroupNicknameStore(str(tmp_path / "n.json"))
    store.set(111, "小彩")
    store.set(333, "旧")
    form = {"nick_111": "小彩2", "group_id": "222", "nickname": "阿蓝", "nick_333": ""}
    n = apply_nicknames_form(store, form)
    assert n == 3
    assert store.get(111) == "小彩2"
    assert store.get(222) == "阿蓝"
    assert store.get(333) == "花璃"   # 留空恢复默认


def test_add_invalid_group_ignored(tmp_path):
    store = GroupNicknameStore(str(tmp_path / "n.json"))
    n = apply_nicknames_form(store, {"group_id": "abc", "nickname": "x"})
    assert n == 0 and store.all() == {}
