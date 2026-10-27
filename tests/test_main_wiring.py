"""组合根静态检查：main.py 里「先引用后赋值」的变量必须被拦住（v2.12.1 回归）。

背景：v2.11.0 曾把 message_router.commands/ai_tools 的注入写在 MessageRouter 构造之前，
CI 的 acceptance 直接报 NameError 且 Web UI 起不来；这里用 AST 做一次快速静态守卫。
"""
import ast
import os


def _load_main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "main.py"), encoding="utf-8") as f:
        return ast.parse(f.read())


def _first_load_before_store(tree, name):
    """返回 (首个 Load 行号, 首个 Store 行号)；任一不存在返回 None。"""
    loads, stores = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == name:
            if isinstance(node.ctx, ast.Load):
                loads.append(node.lineno)
            elif isinstance(node.ctx, ast.Store):
                stores.append(node.lineno)
    first_load = min(loads) if loads else None
    first_store = min(stores) if stores else None
    return first_load, first_store


def test_message_router_used_after_assignment():
    tree = _load_main()
    first_load, first_store = _first_load_before_store(tree, "message_router")
    assert first_store is not None, "main.py 里找不到 message_router 的赋值"
    # 允许 1 处例外：闭包（函数体内引用）在调用时才求值，行号可能靠前；
    # 这里只要求「模块级/函数级顺序语句」里没有先引用——用最保守的判定：
    # 引用出现在赋值之前时，引用必须位于嵌套函数内部（closure 延迟求值）。
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for stmt in node.body:
            if not isinstance(stmt, (ast.Assign, ast.Expr, ast.AnnAssign)):
                continue
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Name) and sub.id == "message_router" \
                        and isinstance(sub.ctx, ast.Load) \
                        and sub.lineno < first_store:
                    # 只有当该语句不在 def/lambda 里才违规
                    inner = any(isinstance(x, (ast.FunctionDef, ast.Lambda))
                                for x in ast.walk(stmt) if x is not stmt)
                    assert inner, (
                        "main.py:%d 引用了 message_router，但它直到第 %d 行才赋值"
                        % (sub.lineno, first_store))
