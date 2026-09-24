"""Code Scanning path-injection 回归：#plugin_id 必须先过 id 校验再拼路径。

审计结论（任务书 §2）：
- True Positive：manager.uninstall() 曾直接用表单传入的 id 拼路径做 shutil.rmtree
  （plugin_panel 的 "id" 表单字段 → uninstall(str(form.get("id", "")))），
  id 里带 ../ 即可删除 plugin_dir 之外的目录。
- 同类风险：_file_read/_file_write/_file_list 的 commonpath 检查是拿
  "由 id 推导出的 base" 去比，base 本身就可能已在 plugin_dir 之外。

修复：新增 _PLUGIN_ID_RE（与 manifest 同源）+ _plugin_base()（先校验 id，
再对 plugin_dir 做包含性检查），uninstall 与三处 file 操作全部改用它。
本文件把这两条不变量固定下来（零依赖，本地可跑）。
"""
import ast
import io
import re

MANAGER = "src/plugins/manager.py"


def _source() -> str:
    return io.open(MANAGER, encoding="utf-8").read()


def _plugin_id_pattern() -> str:
    """从源码 AST 里取出真实的 _PLUGIN_ID_RE 模式（而不是测试里另写一份）。"""
    tree = ast.parse(_source())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "_PLUGIN_ID_RE" for t in node.targets):
            call = node.value
            return call.args[0].value
    raise AssertionError("manager.py 里找不到 _PLUGIN_ID_RE")


def test_plugin_id_regex_rejects_traversal_ids():
    """拼路径用的 id 绝不能出现 ../、绝对路径、分隔符等越界形态。"""
    rx = re.compile(_plugin_id_pattern())
    for bad in ("../../etc", "..", "../x", "/etc/passwd", "a/b", "a\\b", "..%2f..",
                "A", "1abc", "", "-x", "a" * 40, "plugin.id"):
        assert not rx.fullmatch(bad), "应拒绝 id：%r" % bad


def test_plugin_id_regex_accepts_legal_ids():
    """合法 id（与 manifest 同源规则）必须放行，避免为过扫描破坏业务（§13）。"""
    rx = re.compile(_plugin_id_pattern())
    for good in ("ml_go", "echo", "flowerie-plugin", "a", "p" + "x" * 30):
        assert rx.fullmatch(good), "应接受 id：%r" % good


def test_uninstall_validates_id_before_building_path():
    """uninstall 必须在校验通过之后才拼路径/删除（顺序错了防线就失效）。"""
    src = _source()
    i_def = src.find("def uninstall(self, plugin_id")
    i_guard = src.find("_PLUGIN_ID_RE.fullmatch", i_def)
    i_join = src.find("os.path.join(self.plugin_dir, plugin_id)", i_def)
    assert i_def > 0 and i_guard > 0, "uninstall 缺少 id 校验"
    assert i_join > 0, "uninstall 仍在直接拼路径"
    assert i_guard < i_join, "id 校验必须在拼路径之前"


def test_plugin_base_checks_containment_against_plugin_dir():
    """_plugin_base 必须同时做两件事：id 合法 + 越过 plugin_dir 即拒。"""
    src = _source()
    i = src.find("def _plugin_base")
    assert i > 0
    body = src[i:i + 900]
    assert "_PLUGIN_ID_RE.fullmatch" in body, "缺少 id 校验"
    assert "commonpath([root, base]) != root" in body, "缺少对 plugin_dir 的包含性检查"


def test_file_helpers_sanitize_inline_then_use_plugin_base():
    """三处 file 操作必须在**同一函数内**先 basename 净化 + 正则校验，再用 _plugin_base。

    为什么要内联：CodeQL 的局部数据流看不到跨函数的自定义校验，
    把净化放在 sink 同函数内既更安全（纵深防御），也让静态分析能看出污染被切断。
    """
    src = _source()
    assert src.count("_safe_id = os.path.basename(str(plugin_id or ""))") == 4,         "uninstall + 三处 file 操作都应内联 basename 净化"
    assert src.count("base = self._plugin_base(_safe_id)") == 3
    # 旧的「直接用未净化 id 拼 base」写法必须消失
    assert "base = self._plugin_base(plugin_id)" not in src
    # uninstall 的路径必须由净化后的变量拼出
    assert "dir_path = os.path.join(self.plugin_dir, _safe_id)" in src
    assert "dir_path = os.path.join(self.plugin_dir, plugin_id)" not in src
