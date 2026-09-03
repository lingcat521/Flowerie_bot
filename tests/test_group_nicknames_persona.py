"""群特色昵称 × 人设隔离：同群按人设联动的唤名/注入。"""

from src.services.group_nicknames import GroupNicknameStore


def _store(tmp_path):
    return GroupNicknameStore(str(tmp_path / "n.json"), "花璃")


def test_persona_dim_get_set(tmp_path):
    st = _store(tmp_path)
    st.set(111, "zhui", "琉璃")          # 人设维度
    st.set_group(111, "小彩")            # 群级
    assert st.get(111, "zhui") == "琉璃"   # 人设命中
    assert st.get(111) == "小彩"            # 无 persona → 群级
    assert st.get(111, "other") == "小彩"   # 未配置 personaid → 群级回退
    assert st.get(222, "zhui") == "花璃"    # 无配置 → 默认


def test_persona_delete_cascades(tmp_path):
    st = _store(tmp_path)
    st.set(111, "zhui", "琉璃")
    st.set_group(111, "小彩")
    st.set(111, "zhui", "")               # 删人设条目
    assert st.get(111, "zhui") == "小彩"   # 级联到群级


def test_old_format_compatible(tmp_path):
    path = str(tmp_path / "n.json")
    with open(path, "w", encoding="utf-8") as f:  # noqa: PTH123
        f.write('{"786368680": "小彩"}')
    st = GroupNicknameStore(path, "花璃")
    assert st.get(786368680) == "小彩"
    assert st.get(786368680, "zhui") == "小彩"   # 旧键作为群级回退


def test_entries_for(tmp_path):
    st = _store(tmp_path)
    st.set_group(111, "小彩")
    st.set(111, "zhui", "琉璃")
    st.set(111, "b", "阿璃")
    entries = dict(st.entries_for(111))
    assert entries == {None: "小彩", "zhui": "琉璃", "b": "阿璃"}


def test_apply_form_persona_dim(tmp_path):
    import sys
    sys.path.insert(0, ".")
    from src.services.webui_panels.nickname_panel import apply_nicknames_form

    class _F:
        def __init__(self, d): self._d = d
        def __getitem__(self, k): return self._d[k]
        def get(self, k, default=None): return self._d.get(k, default)
        def __iter__(self): return iter(self._d)

    st = _store(tmp_path)
    n = apply_nicknames_form(st, _F({"nick_111__zhui": "琉璃", "group_id": "222",
                                     "persona_id": "zhui", "nickname": "小莹"}))
    assert n == 2
    assert st.get(111, "zhui") == "琉璃"
    assert st.get(222, "zhui") == "小莹"
