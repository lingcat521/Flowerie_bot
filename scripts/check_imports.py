"""import 顺序 + 未使用 import 的本地兜底检查（本机装不上 ruff）。

规则：
1) 组顺序 stdlib → third-party → first-party（flowerie_sdk / plugin_sdk 归 first-party）；
2) 组与组之间必须有空行；
3) 模块级 import 的本地名在文件其它位置一次都没出现 → 报「可能未使用（F401）」；
   `__init__.py` 与含 `__all__` 的文件跳过（再导出不算未使用）；
4) 函数内 import 的名字在模块级也被 import、且模块级那个名字任何作用域都没用到
   → 报「F811 风险」（ruff 同时报模块级 F401 + 函数内 F811；2026-09-27 CI 实际踩到）；
5) 函数内 import 的名字在所属函数里没被用到（symtable 判定 + 函数体内文本计数双重确认，
   避开 PEP 649 惰性注解作用域造成的假阴性）→ 报「未使用（F401）」。

规则 4/5 用 symtable 做作用域判定：纯文本计数会把「被函数内同名 import 遮蔽的模块级 import」
误判成使用过（这正是 4 号规则要抓的形态）。规则 3 保持文本计数（保守、零误报）。

用法：python3 scripts/check_imports.py [文件或目录...]（缺省扫 src/ + tests/ + main.py）
退出码 1 = 有违规。刻意不检查「同组多余空行」与「import 是否排序」（与 ruff 判定不一致、
误报率高）；本脚本只挡已知会红的四类。
"""
import ast
import io
import os
import re
import symtable
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


def local_names(node):
    """一个 import 语句绑定的本地名。"""
    if isinstance(node, ast.Import):
        return [a.asname or a.name.split(".")[0] for a in node.names]
    if isinstance(node, ast.ImportFrom):
        return [a.asname or a.name for a in node.names if a.name != "*"]
    return []


def module_level_names(tree):
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(local_names(node))
    return names


def unused_imports(path: str, tree, text: str):
    """F401 启发：模块级 import 的本地名在文件其它地方一次都没出现 → 报可能未使用。"""
    if os.path.basename(path) == "__init__.py" or "__all__" in text:
        return []
    problems = []
    lines = text.split(chr(10))
    for node in tree.body:
        if "noqa" in lines[node.lineno - 1]:      # 显式声明的再导出（如 web_ui.py 的 MAX_UPLOAD_BYTES）
            continue
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        for local in local_names(node):
            if len(re.findall(r"\b" + re.escape(local) + r"\b", text)) <= 1:
                problems.append("L%d: %s 可能未使用（F401）" % (node.lineno, local))
    return problems


def _own_imports(func):
    """func 内、且最近的外层函数就是 func 的 import 语句（嵌套函数留给它自己）。"""
    found = []

    def walk(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                found.append(child)
            walk(child)

    walk(func)
    return found


def _scope_index(top):
    tables = {}

    def visit(table):
        tables.setdefault((table.get_name(), table.get_lineno()), table)
        for child in table.get_children():
            visit(child)

    visit(top)
    return tables


def _globally_used_names(top):
    """任何作用域里被当作全局名引用过的名字（= 模块级绑定确实被用到）。"""
    used = set()
    for sym in top.get_symbols():
        if sym.is_referenced():
            used.add(sym.get_name())

    def visit(table):
        for sym in table.get_symbols():
            if sym.is_global() and sym.is_referenced():
                used.add(sym.get_name())
        for child in table.get_children():
            if child.get_type() != "annotation":
                visit(child)

    for child in top.get_children():
        if child.get_type() != "annotation":
            visit(child)
    return used


def _symbol_referenced(table, name):
    for sym in table.get_symbols():
        if sym.get_name() == name:
            return sym.is_referenced()
    return True


def scoped_import_problems(path: str, tree, text: str):
    """规则 4/5：函数内 import 的 F811 / F401（symtable 作用域判定）。"""
    if os.path.basename(path) == "__init__.py" or "__all__" in text:
        return []
    try:
        top = symtable.symtable(text, path, "exec")
    except (SyntaxError, ValueError):
        return []
    tables = _scope_index(top)
    used_globally = _globally_used_names(top)
    mod_names = module_level_names(tree)
    lines = text.split(chr(10))
    problems = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        table = tables.get((func.name, func.lineno))
        segment = ast.get_source_segment(text, func) or ""
        for node in _own_imports(func):
            if "noqa" in lines[node.lineno - 1]:
                continue
            for local in local_names(node):
                if local in mod_names and local not in used_globally:
                    problems.append("L%d: 函数 %s 内的 %s 与模块级同名，且模块级那个没被任何作用域用到"
                                    "（ruff 报模块级 F401 + 这里 F811）" % (node.lineno, func.name, local))
                elif table is not None and not _symbol_referenced(table, local):
                    # 叠加文本证据：PEP 649 惰性注解把「只用在注解里的名字」放进 __annotate__ 作用域，
                    # symtable 会看不到那次引用（测试里常见），故要求函数体内除本行外再无出现才报。
                    if len(re.findall(r"\b" + re.escape(local) + r"\b", segment)) <= 1:
                        problems.append("L%d: 函数 %s 内的 %s 未使用（F401）" % (node.lineno, func.name, local))
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
        for p in (order_problems(tree) + unused_imports(f, tree, text)
                  + scoped_import_problems(f, tree, text)):
            print("%s: %s" % (os.path.relpath(f, ROOT), p))
            bad += 1
    print("检查 %d 个文件；问题 %d 处" % (len(files), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

