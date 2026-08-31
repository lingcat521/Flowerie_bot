"""API/SDK/源码一致性 白盒校验（v1.7 常跑）：

- _SENDER_ACTIONS 动作表 ↔ permissions 权限表 ↔ Sender 方法 ↔ PluginApi/Adapter 引用
  四向一致性（发现不一致 = 白名单死动作/未授权动作/缺失端点，必须修复）
- 语义层（src/sdk/**/bot.py/message.py/listener.py + plugin_sdk 非适配文件）不含
  OneBot 端点字符串（低耦合红线）
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _sender_actions() -> dict:
    tree = ast.parse((ROOT / "src/plugins/manager.py").read_text(encoding="utf-8"))
    actions = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for t in targets:
            if isinstance(t, ast.Name) and t.id == "_SENDER_ACTIONS" and isinstance(node.value, ast.Dict):
                for k, v in zip(node.value.keys, node.value.values):
                    if isinstance(k, ast.Constant):
                        entry = v.elts[0]
                        names = ([entry.value] if isinstance(entry, ast.Constant)
                                 else [e.value for e in entry.elts])
                        actions[k.value] = names
    return actions


def _permissions() -> dict:
    return dict(re.findall(
        r'    "(\w+)": ("[^"]+"|None),',
        (ROOT / "src/plugins/permissions.py").read_text(encoding="utf-8")))


def _sender_methods() -> set:
    return set(re.findall(
        r"    async def (\w+)",
        (ROOT / "src/services/sender.py").read_text(encoding="utf-8")))


def test_sender_actions_consistent():
    actions = _sender_actions()
    assert actions, "动作表为空（解析失败）"
    perms = _permissions()
    senders = _sender_methods()
    problems = []
    for action, names in sorted(actions.items()):
        if action not in perms:
            problems.append(f"动作 {action} 缺权限映射")
        for n in names:
            if n not in senders:
                problems.append(f"动作 {action} → Sender.{n}() 不存在")
    assert not problems, "白名单死动作/缺权限: " + "; ".join(problems)


def test_adapter_refs_exist():
    """OneBotAdapter 引用的 sender 方法必须存在。"""
    src = (ROOT / "src/sdk/onebot/adapter.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    senders = _sender_methods()
    attrs = set()
    for n in ast.walk(tree):
        if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute)
                and isinstance(n.value.value, ast.Name)
                and n.value.value.id == "self" and n.value.attr == "_sender"):
            attrs.add(n.attr)
    missing = attrs - senders
    assert not missing, f"adapter 引用不存在的 sender 方法: {sorted(missing)}"


def test_semantics_layers_free_of_endpoints():
    """语义/插件侧非适配文件不得出现 /send_ /get_ /set_ 端点串（低耦合红线）。"""
    bad = []
    for p in list((ROOT / "src/sdk").glob("*.py")) + list((ROOT / "plugin_sdk/flowerie_sdk").glob("*.py")):
        if p.name == "adapter.py":
            continue
        body = p.read_text(encoding="utf-8")
        hits = [h for h in re.findall(r'"(/[a-z_]+)"', body)
                if h.startswith(("/send_", "/get_", "/set_"))]
        if hits:
            bad.append((p.name, hits))
    assert not bad, f"端点泄漏: {bad}"


def test_docs_api_matches_implementation():
    """api.md 权威速查表方法集 ⊆ PluginApi 方法集（文档不承诺不存在的能力）。"""
    api_doc = (ROOT / "docs/api.md").read_text(encoding="utf-8")
    doc_methods = set(re.findall(r"^\| `(\w+)\(`", api_doc, re.M)) | set(
        re.findall(r"^\| `(\w+)\(", api_doc, re.M))
    tree = ast.parse((ROOT / "src/plugins/runner/python_runner.py").read_text(encoding="utf-8"))
    impl = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == "PluginApi":
            impl = {f.name for f in n.body if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}
    missing = doc_methods - impl
    assert not missing, f"api.md 提及但实现缺失: {sorted(missing)}"
