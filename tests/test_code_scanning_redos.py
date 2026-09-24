r"""Code Scanning 回归：ReDoS（CQ 码正则）+ 不安全临时文件。

审计结论（详见 docs/archive/code-scanning-report.md）：
- py/redos #84（True Positive）：_CQ 最初是 (?:,[^\[\]]*)* —— 内层 star 能吃掉逗号，
  同一串逗号因此存在多种划分方式 → 指数回溯。实测 [CQ:0 + N 个逗号：
  N=10/14/18 → 0.2 / 3.7 / 60.4 ms（每 +4 个逗号 ×16），40 个逗号直接把进程卡死。
- 第一版修复 (?:,[^\[\],][^\[\]]*)* 只堵住「纯逗号」这一条路径：实测已无指数行为
  （N 到 100 仍 < 0.01 ms），但「量词套量词」的形状还在，静态分析照旧报（下一次分析 #84 复现）。
  只靠引擎优化（REPEAT_ONE）才不炸，不算修好。
- 最终修复：单一字符集重复 r"\[CQ:([^\[\]]+)\]"，动作名/参数在 _cq_parts 里切分。
  整个模式只有一个量词 → 划分点唯一 → 线性（不依赖任何引擎优化）。
  等价性用「期望结果表」锁住（见 EXPECTED），不再把可被利用的历史模式留在仓库里 ——
  第一版正是把它当差分基准留在测试中，CodeQL 立刻（且正确地）报了它（#85）。
- py/insecure-temporary-file（True Positive）：测试里的 tempfile.mktemp 有竞态，改 mkstemp。
"""
import ast
import io
import os
import sys
import time

try:  # Python >= 3.11
    from re import _constants as sre_constants
    from re import _parser as sre_parse
except ImportError:  # Python 3.9 / 3.10
    import sre_constants
    import sre_parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.sdk.onebot.transformer import _CQ, _cq_parts, _parse_params, extract_at_list, extract_images  # noqa: E402

TRANSFORMER = os.path.join("src", "sdk", "onebot", "transformer.py")

# 历史实现的解析结果（人工固化，替代「跑一遍旧正则」的差分基准）。
# 键 = 输入文本，值 = (动作名, 参数串)；参数串保留前导逗号，与 _parse_params 的输入格式一致。
EXPECTED = {
    "[CQ:at,qq=123]": ("at", ",qq=123"),
    "[CQ:at,qq=123,name=x]": ("at", ",qq=123,name=x"),
    "[CQ:at,qq=all]": ("at", ",qq=all"),
    "[CQ:image,file=a,b,c]": ("image", ",file=a,b,c"),
    "[CQ:image,url=http://x/i.png]": ("image", ",url=http://x/i.png"),
    "[CQ:reply,id=777]": ("reply", ",id=777"),
    "[CQ:face,id=1]": ("face", ",id=1"),
    "前[CQ:at,qq=1]后": ("at", ",qq=1"),
}

# 已人工复核、确认无歧义的嵌套量词：分隔符是字面量，字符无法在两层量词之间搬运。
# 新增条目必须写清理由 —— 这个白名单就是「新引入回溯形状」的闸门。
NESTED_QUANTIFIER_ALLOWLIST = {
    "src/services/webui_render/plugin_dsl.py": "\\| 是字面量分隔符，(?:\\|(.+))? 里的 (.+) 吃不到分隔符",
    "src/repositories/env_store.py": "分组外的 [ \\t] 与组内 [ \\t]+ 被字面量 = 隔开",
}


def _cq_pattern() -> str:
    """从源码 AST 取真实的 _CQ 模式（不另写一份）。"""
    tree = ast.parse(io.open(TRANSFORMER, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "_CQ" for t in node.targets):
            return node.value.args[0].value
    raise AssertionError("找不到 _CQ 正则")


def _has_nested_quantifier(pattern: str):
    """模式里是否存在「量词套量词」（ReDoS 的形状根源）；解析失败返回 None。"""
    try:
        tree = sre_parse.parse(pattern, 0)
    except Exception:
        return None
    repeated = (sre_constants.MAX_REPEAT, sre_constants.MIN_REPEAT)
    if hasattr(sre_constants, "POSSESSIVE_REPEAT"):
        repeated = repeated + (sre_constants.POSSESSIVE_REPEAT,)

    def walk(seq, depth):
        for op, av in seq:
            if op in repeated:
                if depth > 0:
                    return True
                if isinstance(av, tuple) and len(av) == 3 and walk(av[2], depth + 1):
                    return True
            elif op is sre_constants.SUBPATTERN:
                if walk(av[3], depth):
                    return True
            elif op is sre_constants.BRANCH:
                for branch in av[1]:
                    if walk(branch, depth):
                        return True
        return False

    return walk(tree, 0)


def _regex_literals():
    """遍历仓库里所有 re.<fn>("字面量") 调用 → (相对路径, 行号, 模式)。"""
    skip = (".git", "__pycache__", "node_modules", ".venv", "build", "dist")
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in skip]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(base, name)
            try:
                tree = ast.parse(io.open(path, encoding="utf-8").read())
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if getattr(func, "attr", "") not in ("compile", "match", "search", "fullmatch", "findall", "sub", "split"):
                    continue
                if getattr(getattr(func, "value", None), "id", "") != "re":
                    continue
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    yield os.path.relpath(path, ROOT), node.lineno, node.args[0].value


def test_cq_regex_has_exactly_one_quantifier():
    """形状不变量：整个模式只允许一个量词 —— 没有第二个量词就没有可歧义的划分点。"""
    pat = _cq_pattern()
    assert sum(pat.count(c) for c in "*+?") == 1, "CQ 正则必须只有一个量词: %s" % pat
    assert "(?:" not in pat, "不得使用分组量词（嵌套量词正是 ReDoS 根源）: %s" % pat


def test_cq_pattern_has_no_nested_quantifier():
    """独立复核：用正则解析树确认没有「量词套量词」。"""
    assert _has_nested_quantifier(_cq_pattern()) is False


def test_cq_regex_handles_pathological_inputs_quickly():
    """病态输入必须在毫秒级返回（修复前 18 个逗号就要 60ms、40 个直接卡死）。"""
    import re as _re
    rx = _re.compile(_cq_pattern())
    bad_inputs = [
        "[CQ:0," + "," * 4000,          # CodeQL 给出的攻击串
        "[CQ:0" + ",a" * 4000,          # 多段参数、无收尾 ]
        "[CQ:" + "a" * 20000,           # 动作名超长、无收尾 ]
        "[CQ:0" + ",aaaa" * 4000,       # 每参数多字符
    ]
    for bad in bad_inputs:
        t0 = time.time()
        rx.search(bad)
        elapsed = time.time() - t0
        assert elapsed < 1.0, "病态输入(长度 %d)耗时 %.3fs，疑似仍有回溯" % (len(bad), elapsed)


def test_cq_parsing_matches_expected_results():
    """等价性：对历史实现的期望结果逐条比对（不跑旧正则，避免把危险模式留在仓库）。"""
    for text, expect in EXPECTED.items():
        m = _CQ.search(text)
        assert m is not None, text
        assert _cq_parts(m) == expect, (text, _cq_parts(m), expect)


def test_cq_parser_tolerates_empty_params():
    """已知且刻意的差异：空参数（,,）历史实现整段不认，现在认下但解析结果仍为空。

    真实协议不会产生 ,,；认下来只会多剥掉一段畸形 CQ 文本，不会多出 at/image。
    """
    text = "[CQ:at,,qq=1]"
    m = _CQ.search(text)
    assert m is not None
    action, params = _cq_parts(m)
    assert action == "at"
    assert dict(_parse_params(params)) == {"qq": "1"}
    assert extract_at_list(text) == ["1"]


def test_extractors_still_work_end_to_end():
    """真实事件文本抽取不回退。"""
    raw = "[CQ:at,qq=10001] 来图 [CQ:image,url=http://x/i.png] [CQ:reply,id=777]"
    assert extract_at_list(raw) == ["10001"]
    assert extract_images(raw) == ["http://x/i.png"]


def test_no_new_nested_quantifier_regex_in_repo():
    """闸门：仓库里任何 re.<fn>("字面量") 都不得新出现「量词套量词」形状。

    白名单里的两条已人工复核（字面量分隔符隔开了两层量词，字符搬不过去）。
    """
    offenders = []
    seen = set()
    for rel, lineno, pattern in _regex_literals():
        if _has_nested_quantifier(pattern) is not True:
            continue
        if rel in NESTED_QUANTIFIER_ALLOWLIST:
            seen.add(rel)
            continue
        offenders.append("%s:%d %s" % (rel, lineno, pattern))
    assert not offenders, "新出现回溯歧义形状的正则（请改写或补白名单理由）：\n" + "\n".join(offenders)
    stale = set(NESTED_QUANTIFIER_ALLOWLIST) - seen
    assert not stale, "白名单条目已失效，请删除：%s" % sorted(stale)


def test_no_mktemp_in_tests():
    """测试里不得再出现 tempfile.mktemp（竞态 + CodeQL high）。"""
    for rel in ("tests/test_memory_gate.py", "tests/test_storage_backend.py"):
        src = io.open(os.path.join(ROOT, rel), encoding="utf-8").read()
        assert "tempfile.mktemp(" not in src, rel
        assert "tempfile.mkstemp(" in src, rel
