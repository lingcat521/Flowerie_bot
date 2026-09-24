r"""Code Scanning 回归：日志不得输出密钥（py/clear-text-logging-sensitive-data，True Positive）。

审计：验收脚本曾用 _masked_key(value) 把「长度 + 前 3 位」写进 CI 日志。
CodeQL 不认这种自定义脱敏函数（返回值仍是从密钥派生的字符串）→ 判为明文日志。
修复：日志实参只用「比较得到的布尔结论」挑选常量文案，密钥值本身根本不进日志参数。

本文件用两条源码级不变量把修复钉住（不需要跑起整个验收脚本）：
1. rec()/print() 的实参里不得出现「由敏感来源派生的表达式」（纯比较除外 —— 比较只产生布尔值）；
2. 敏感来源不得进入字符串格式化构造（f-string / % / str.format）。
"""
import ast
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCEPTANCE = os.path.join(ROOT, "tests", "acceptance_check.py")
LOG_CALLS = ("rec", "print")
SENSITIVE_HINTS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "CREDENTIAL")


def _tree():
    return ast.parse(io.open(ACCEPTANCE, encoding="utf-8").read())


def _is_sensitive_source(node):
    """是否是「敏感来源」表达式：xxx.get("...KEY...") / os.getenv("...") / os.environ["..."]。"""
    if isinstance(node, ast.Call):
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None) or ""
        if name == "getenv":
            return True
        if name in ("get", "getvalue"):
            for a in list(node.args) + [k.value for k in node.keywords]:
                if _is_sensitive_name(a):
                    return True
    if isinstance(node, ast.Subscript):
        return _is_sensitive_name(node.slice) or _is_sensitive_source(node.value)
    return False


def _is_sensitive_name(node):
    return (isinstance(node, ast.Constant) and isinstance(node.value, str)
            and any(h in node.value.upper() for h in SENSITIVE_HINTS))


def _contains_sensitive(node):
    return any(_is_sensitive_source(n) for n in ast.walk(node))


def _calls():
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in LOG_CALLS:
                yield node


def test_no_secret_expression_in_log_arguments():
    """禁用形状：rec(..., _masked_key(ev.get("DEEPSEEK_API_KEY"))) —— 密钥派生值进了日志实参。"""
    for node in _calls():
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        for arg in list(node.args) + [k.value for k in node.keywords]:
            if isinstance(arg, ast.Compare):
                continue  # 纯比较 → 只有布尔结论进日志，安全
            assert not _contains_sensitive(arg), (
                "acceptance_check.py:%d %s() 实参里出现敏感来源派生表达式（会明文进日志）"
                % (getattr(node, "lineno", 0), name))


def test_secret_never_enters_string_formatting():
    """禁用形状：f"{key}" / "%s" % key / "...".format(key) —— 格式化即泄漏。"""
    for node in ast.walk(_tree()):
        bad = False
        if isinstance(node, ast.JoinedStr):
            bad = _contains_sensitive(node)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            bad = _contains_sensitive(node.right)
        elif isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "format":
            bad = _contains_sensitive(node)
        assert not bad, (
            "acceptance_check.py:%d 敏感来源被塞进字符串格式化" % getattr(node, "lineno", 0))


def test_masking_helper_is_gone():
    """脱敏函数必须删掉：留着就会诱导「回显密钥片段」，而 CodeQL 不认它。"""
    src = io.open(ACCEPTANCE, encoding="utf-8").read()
    assert "_masked_key" not in src
