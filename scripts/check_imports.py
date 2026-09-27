"""import 顺序 + 未使用 import 的本地兜底检查（本机装不上 ruff）。

规则：
1) 组顺序 stdlib → third-party → first-party（flowerie_sdk / plugin_sdk 归 first-party）；
2) 组与组之间必须有空行；
3) 模块级 import 的本地名在文件其它位置一次都没出现 → 报「可能未使用（F401）」；
   `__init__.py` 与含 `__all__` 的文件跳过（再导出不算未使用）。

用法：python3 scripts/check_imports.py [文件或目录...]（缺省扫 src/ + tests/ + main.py）
退出码 1 = 有违规。刻意不检查「同组多余空行」（与 ruff 判定不一致、误报率高）。
"""
import ast
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STDLIB = set(getattr(sys, "stdlib_module_names", ()))
#: 与 pyproject.toml 的 ruff extend-exclude 保持一致
RUFF_EXCLUDED = {"tests/acceptance_check.py"}


def kind(name: str) -> str:
    top = (name or "").split(".")[0]
    if top in ("src", "tests", "flowerie_sdk", "plugin_sdk"):
        return "first"
    if top in STDLIB:
        return "std"
    return "third"


def import_entries(tree):
    entries = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                entries.append((node.lineno, node.end_lineno, kind(a.name), a.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                entries.append((node.lineno, node.end_lineno, "first", node.module or "."))
            else:
                entries.append((node.lineno, node.end_lineno, kind(node.module or ""), node.module or ""))
    return entries


def order_problems(tree):
    problems = []
    order = {"std": 0, "third": 1, "first": 2}
    prev_kind = None
    prev_end = None
    for lineno, end_lineno, k, name in import_entries(tree):
        if prev_kind is not None:
            if order[k] < order[prev_kind]:
                problems.append("L%d: %s 组出现在 %s 组之后（%s）" % (lineno, k, prev_kind, name))
            elif k != prev_kind and (lineno - prev_end) < 2:
                problems.append("L%d: %s 组与 %s 组之间缺空行（%s）" % (lineno, k, prev_kind, name))
        prev_kind, prev_end = k, end_lineno
    return problems


def unused_imports(path: str, tree, text: str):
    """F401 启发：模块级 import 的本地名在文件其它地方一次都没出现 → 报可能未使用。"""
    if os.path.basename(path) == "__init__.py" or "__all__" in text:
        return []
    problems = []
    lines = text.split(chr(10))
    for node in tree.body:
        if "noqa" in lines[node.lineno - 1]:      # 显式声明的再导出（如 web_ui.py 的 MAX_UPLOAD_BYTES）
            continue
        pairs = []
        if isinstance(node, ast.Import):
            pairs = [(a.asname or a.name.split(".")[0]) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            pairs = [(a.asname or a.name) for a in node.names if a.name != "*"]
        for local in pairs:
            if len(re.findall(r"\b" + re.escape(local) + r"\b", text)) <= 1:
                problems.append("L%d: %s 可能未使用（F401）" % (node.lineno, local))
    return problems


def main():
    args = sys.argv[1:] or [os.path.join(ROOT, "src"), os.path.join(ROOT, "tests"),
                            os.path.join(ROOT, "main.py"), os.path.join(ROOT, "scripts")]
    files = []
    for a in args:
        if os.path.isdir(a):
            files += [os.path.join(dp, f) for dp, _dn, fn in os.walk(a)
                      for f in fn if f.endswith(".py")]
        else:
            files.append(a)
    nested = os.path.join(ROOT, "Flowerie_bot") + os.sep
    files = [f for f in files
             if not f.startswith(nested) and "/.git/" not in f and "__pycache__" not in f
             and os.path.relpath(f, ROOT) not in RUFF_EXCLUDED]
    bad = 0
    for f in sorted(files):
        try:
            text = io.open(f, encoding="utf-8").read()
            tree = ast.parse(text)
        except SyntaxError as exc:
            print("%s: 语法错误 %s" % (f, exc))
            bad += 1
            continue
        for p in order_problems(tree) + unused_imports(f, tree, text):
            print("%s: %s" % (os.path.relpath(f, ROOT), p))
            bad += 1
    print("检查 %d 个文件；问题 %d 处" % (len(files), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
