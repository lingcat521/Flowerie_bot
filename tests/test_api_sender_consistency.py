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


def test_ns_actions_have_no_endpoint():
    keys, _ = _action_table()
    ns = _ns_actions()
    overlap = ns & keys
    assert not overlap, f"声明 NS 却已有端点（能力被埋）: {sorted(overlap)}"
