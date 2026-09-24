r"""Code Scanning 回归：ReDoS（CQ 码正则）+ 不安全临时文件。

审计结论：
- py/redos (True Positive)：transformer.py 的 _CQ 正则里 (?:,[^\[\]]*)* 允许
  [^\[\]]* 吃掉逗号 → 内层 star 与外层 star 对同一串逗号存在多种划分 → 指数回溯。
  实测（[CQ:0, + N 个逗号）：10/14/18 个逗号 = 0.2/3.7/60.4 ms（×16 递增），
  40 个逗号直接卡死进程。
  修复：每个参数必须以「非逗号」起头 → (?:,[^\[\],][^\[\]]*)*，划分唯一、线性。
  实测修复后 2000 个逗号仅 0.008 ms，且 5 组样例解析结果与原正则完全一致。
- py/insecure-temporary-file (True Positive)：测试里的 tempfile.mktemp 存在竞态，
  改为 mkstemp + close。
"""
import io
import re
import time

TRANSFORMER = "src/sdk/onebot/transformer.py"


def _cq_pattern() -> str:
    """从源码 AST 取真实的 _CQ 模式（不另写一份）。"""
    import ast
    tree = ast.parse(io.open(TRANSFORMER, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "_CQ" for t in node.targets):
            return node.value.args[0].value
    raise AssertionError("找不到 _CQ 正则")


def test_cq_regex_is_unambiguous_for_commas():
    """每个参数必须以非逗号起头 —— 否则内层 star 与外层 star 会产生多种划分（ReDoS 根源）。"""
    pat = _cq_pattern()
    assert "[^\\[\\],]" in pat, "参数起始字符集必须排除逗号：%s" % pat


def test_cq_regex_handles_long_comma_runs_quickly():
    """病态输入必须在毫秒级返回（修复前 18 个逗号就要 60ms、40 个直接卡死）。"""
    rx = re.compile(_cq_pattern())
    bad = "[CQ:0," + "," * 2000
    t0 = time.time()
    rx.search(bad)
    elapsed = time.time() - t0
    assert elapsed < 1.0, "病态输入耗时 %.3fs，疑似仍有回溯" % elapsed


def test_cq_regex_semantics_preserved():
    """修复不能改变解析结果（含「值里带逗号」这种真实用法）。"""
    rx = re.compile(_cq_pattern())
    cases = {
        "[CQ:at,qq=123]": ("at", ",qq=123"),
        "[CQ:at,qq=123,name=x]": ("at", ",qq=123,name=x"),
        "[CQ:at,qq=all]": ("at", ",qq=all"),
        "[CQ:image,file=a,b,c]": ("image", ",file=a,b,c"),
    }
    for text, expect in cases.items():
        m = rx.search(text)
        assert m is not None, text
        assert (m.group(1), m.group(2)) == expect, (text, m.groups())


def test_no_mktemp_in_tests():
    """测试里不得再出现 tempfile.mktemp（竞态 + CodeQL high）。"""
    for rel in ("tests/test_memory_gate.py", "tests/test_storage_backend.py"):
        src = io.open(rel, encoding="utf-8").read()
        assert "tempfile.mktemp(" not in src, rel
        assert "tempfile.mkstemp(" in src, rel
