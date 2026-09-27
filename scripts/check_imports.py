"""import 顺序兜底检查（近似 ruff I001：stdlib → third-party → first-party，组间空行）。

用法：python3 work/check_imports.py [文件或目录...]（缺省扫仓库 src/ + tests/ + main.py）
退出码 1 = 有违规。本机装不上 ruff（Android aarch64 无 wheel），故用这个兜底。
"""
import ast
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STDLIB = set(getattr(sys, "stdlib_module_names", ()))


def kind(name: str) -> str:
    top = (name or "").split(".")[0]
    if top in ("src", "tests", "flowerie_sdk", "plugin_sdk"):
        return "first"
    if top in STDLIB:
        return "std"
    return "third"


def check(path: str):
    text = io.open(path, encoding="utf-8").read()
    tree = ast.parse(text)
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
    problems = []
    order = {"std": 0, "third": 1, "first": 2}
    prev_kind = None
    prev_end = None
    for lineno, end_lineno, k, name in entries:
        if prev_kind is not None:
            if order[k] < order[prev_kind]:
                problems.append("L%d: %s 组出现在 %s 组之后（%s）" % (lineno, k, prev_kind, name))
            elif k != prev_kind and (lineno - prev_end) < 2:
                problems.append("L%d: %s 组与 %s 组之间缺空行（%s）" % (lineno, k, prev_kind, name))
        prev_kind, prev_end = k, end_lineno
    return problems


def main():
    args = sys.argv[1:] or [os.path.join(ROOT, "src"), os.path.join(ROOT, "tests"),
                            os.path.join(ROOT, "main.py")]
    files = []
    for a in args:
        if os.path.isdir(a):
            files += [os.path.join(dp, f) for dp, _dn, fn in os.walk(a)
                      for f in fn if f.endswith(".py")]
        else:
            files.append(a)
    nested = os.path.join(ROOT, "Flowerie_bot") + os.sep
    files = [f for f in files
             if not f.startswith(nested) and "/.git/" not in f and "__pycache__" not in f]
    bad = 0
    for f in sorted(files):
        try:
            problems = check(f)
        except SyntaxError as exc:
            print("%s: 语法错误 %s" % (f, exc))
            bad += 1
            continue
        for p in problems:
            print("%s: %s" % (os.path.relpath(f, ROOT), p))
            bad += 1
    print("检查 %d 个文件；import 顺序问题 %d 处" % (len(files), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

