"""动作表 ↔ Sender 方法 / NS 声明 ↔ 端点 一致性（防“poke 类”断链回归）。

攻击面：声称支持但 Sender 无方法（→恒失败）；声称不支持但端点存在（→能力被埋）。
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _sender_methods() -> set:
    tree = ast.parse((ROOT / "src/services/sender.py").read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == "Sender":
            return {f.name for f in n.body if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return set()


def _action_table() -> tuple:
    tree = ast.parse((ROOT / "src/plugins/manager.py").read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == "_SENDER_ACTIONS":
            keys, methods = set(), set()
            for k, v in zip(n.value.keys, n.value.values):
                keys.add(k.value)
                first = v.elts[0] if hasattr(v, "elts") and v.elts else None
                if isinstance(first, ast.Constant):
                    methods.add(first.value)
                elif isinstance(first, ast.List):
                    for el in first.elts:
                        if isinstance(el, ast.Constant):
                            methods.add(el.value)
            return keys, methods
    return set(), set()


def _ns_actions() -> set:
    tree = ast.parse((ROOT / "src/plugins/manager.py").read_text(encoding="utf-8"))
    ns = set()
    for n in ast.walk(tree):
        target = None
        if isinstance(n, ast.Assign):
            target = n.targets[0].id if len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) else None
        elif isinstance(n, ast.AnnAssign):
            target = n.target.id if isinstance(n.target, ast.Name) else None
        if target == "_EXT_NS" or target == "NS":
            if hasattr(n.value, "elts"):
                ns |= {el.value for el in n.value.elts if isinstance(el, ast.Constant)}
    return ns


def test_table_methods_exist_in_sender():
    keys, methods = _action_table()
    assert keys and methods, "动作表为空"
    missing = methods - _sender_methods()
    assert not missing, f"表引用但 Sender 无方法（恒失败）: {sorted(missing)}"


# 纯工具/日志动作：不经权限 gate（本地实现），无需映射
_LOCAL_UTILS = {"now", "format_time", "log", "random_choice", "random_int"}


def _action_names_from_api():
    tree = ast.parse((ROOT / "src/plugins/runner/python_runner.py").read_text(encoding="utf-8"))
    calls = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "_send_action":
            if n.args and isinstance(n.args[0], ast.Constant):
                calls.add(n.args[0].value)
    return calls


def test_all_actions_have_permissions():
    import re as _re
    perm = (ROOT / "src/plugins/permissions.py").read_text(encoding="utf-8")
    perm_keys = set(_re.findall(r'^    "([a-z_0-9]+)": "[a-z_0-9_.]+",', perm, _re.M))
    tree = ast.parse((ROOT / "src/plugins/manager.py").read_text(encoding="utf-8"))
    ext_actions = set()
    for n in ast.walk(tree):
        target = None
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            target = n.targets[0].id
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            target = n.target.id
        if target and target.endswith("_EXT") and target != "_EXT_NS" and not target.startswith("_WEBUI"):
            v = n.value
            while isinstance(v, ast.Call):
                v = v.args[0] if v.args else None
            if v is not None and hasattr(v, "elts"):
                ext_actions |= {el.value for el in v.elts if isinstance(el, ast.Constant)}
    actions = _action_names_from_api() | ext_actions
    missing = sorted((actions - _LOCAL_UTILS) - perm_keys)
    assert not missing, f"动作无权限映射（gate 会被绕过）: {missing}"
    keys, _ = _action_table()
    ns = _ns_actions()
    overlap = ns & keys
    assert not overlap, f"声明 NS 却已有端点（能力被埋）: {sorted(overlap)}"
