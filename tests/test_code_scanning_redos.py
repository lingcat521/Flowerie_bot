r"""Code Scanning 回归：ReDoS（CQ 码正则）+ 不安全临时文件。

审计结论（详见 docs/archive/code-scanning-report.md）：
- py/redos #84（True Positive）：_CQ 最初是 (?:,[^\[\]]*)* —— 内层 star 能吃掉逗号，
  同一串逗号因此存在多种划分方式 → 指数回溯。实测 '[CQ:0' + N 个逗号：
  N=10/14/18 → 0.2 / 3.7 / 60.4 ms（每 +4 个逗号 ×16），40 个逗号直接把进程卡死。
- 第一版修复 (?:,[^\[\],][^\[\]]*)* 只堵住「纯逗号」这一条路径：实测已无指数行为
  （N 到 100 仍 < 0.01 ms），但「量词套量词」的形状还在，静态分析照旧报（下次分析 #84 复现）。
  只靠引擎优化（REPEAT_ONE）才不炸，不算修好。
- 最终修复：单一字符集重复 r"\[CQ:([^\[\]]+)\]"，动作名/参数在 _cq_parts 里切分。
  整个模式只有一个量词 → 划分点唯一 → 线性（不依赖任何引擎优化）。
  等价性由本文件对「历史正则」的差分用例逐条比对。
- py/insecure-temporary-file（True Positive）：测试里的 tempfile.mktemp 有竞态，改 mkstemp。
"""
import io
import os
import re
import sys
import time

TRANSFORMER = os.path.join("src", "sdk", "onebot", "transformer.py")
# 历史实现（含 ReDoS 的版本），只作差分基准，不参与运行
REFERENCE_PATTERN = r"\[CQ:([a-zA-Z0-9_]+)((?:,[^\[\],][^\[\]]*)*)\]"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.sdk.onebot.transformer import _CQ, _cq_parts, _parse_params, extract_at_list, extract_images  # noqa: E402


def _cq_pattern() -> str:
    """从源码 AST 取真实的 _CQ 模式（不另写一份）。"""
    import ast
    tree = ast.parse(io.open(TRANSFORMER, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "_CQ" for t in node.targets):
            return node.value.args[0].value
    raise AssertionError("找不到 _CQ 正则")


def test_cq_regex_has_exactly_one_quantifier():
    """形状不变量：整个模式只允许一个量词 —— 没有第二个量词就没有可歧义的划分点。"""
    pat = _cq_pattern()
    quantifiers = sum(pat.count(c) for c in "*+?")
    assert quantifiers == 1, "CQ 正则必须只有一个量词（否则回溯有歧义）: %s" % pat
    assert "(?:" not in pat, "不得使用分组量词（嵌套量词正是 ReDoS 根源）: %s" % pat


def test_cq_regex_handles_pathological_inputs_quickly():
    """病态输入必须在毫秒级返回（修复前 18 个逗号就要 60ms、40 个直接卡死）。"""
    rx = re.compile(_cq_pattern())
    bad_inputs = [
        "[CQ:0," + "," * 4000,          # CodeQL 给出的攻击串：,,,,
        "[CQ:0" + ",a" * 4000,          # 多段参数、无收尾 ]
        "[CQ:" + "a" * 20000,           # 动作名超长、无收尾 ]
        "[CQ:0" + ",aaaa" * 4000,       # 每参数多字符
    ]
    for bad in bad_inputs:
        t0 = time.time()
        rx.search(bad)
        elapsed = time.time() - t0
        assert elapsed < 1.0, "病态输入(长度 %d)耗时 %.3fs，疑似仍有回溯" % (len(bad), elapsed)


def test_cq_parsing_matches_historical_reference():
    """差分：新实现（源码 _CQ + _cq_parts）对合法输入与历史正则结果逐条一致。"""
    ref = re.compile(REFERENCE_PATTERN)
    cases = [
        "[CQ:at,qq=123]",
        "[CQ:at,qq=123,name=x]",
        "[CQ:at,qq=all]",
        "[CQ:image,file=a,b,c]",          # 值里带逗号（真实用法）
        "[CQ:image,url=http://x/i.png]",
        "[CQ:reply,id=777]",
        "[CQ:face,id=1]",
        "前[CQ:at,qq=1]后",
        "Hi [CQ:at,qq=10001] 世界 [CQ:image,url=http://x/i.png]",
    ]
    for text in cases:
        new = _CQ.search(text)
        old = ref.search(text)
        assert (new is None) == (old is None), text
        assert new is not None, text
        assert _cq_parts(new) == (old.group(1), old.group(2)), (text, _cq_parts(new), old.groups())


def test_cq_parser_tolerates_malformed_input_the_same_way():
    """已知且刻意的差异：空参数（,,）历史正则整段不认，新实现认下但解析结果仍为空。

    真实协议不会产生 ,,；认下来只会多剥掉一段畸形 CQ 文本，不会多出 at/image。
    """
    ref = re.compile(REFERENCE_PATTERN)
    text = "[CQ:at,,qq=1]"
    assert ref.search(text) is None, "历史基准应当拒绝空参数"
    new = _CQ.search(text)
    assert new is not None
    action, params = _cq_parts(new)
    assert action == "at"
    assert dict(_parse_params(params)) == {"qq": "1"}
    assert extract_at_list(text) == ["1"]


def test_extractors_still_work_end_to_end():
    """真实事件文本抽取不回退。"""
    raw = "[CQ:at,qq=10001] 来图 [CQ:image,url=http://x/i.png] [CQ:reply,id=777]"
    assert extract_at_list(raw) == ["10001"]
    assert extract_images(raw) == ["http://x/i.png"]


def test_no_mktemp_in_tests():
    """测试里不得再出现 tempfile.mktemp（竞态 + CodeQL high）。"""
    for rel in ("tests/test_memory_gate.py", "tests/test_storage_backend.py"):
        src = io.open(os.path.join(ROOT, rel), encoding="utf-8").read()
        assert "tempfile.mktemp(" not in src, rel
        assert "tempfile.mkstemp(" in src, rel
