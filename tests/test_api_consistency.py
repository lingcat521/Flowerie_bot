"""API/SDK/源码一致性 白盒校验（v1.7 常跑）：

- _SENDER_ACTIONS 动作表 ↔ permissions 权限表 ↔ Sender 方法 ↔ PluginApi/Adapter 引用
  四向一致性（发现不一致 = 白名单死动作/未授权动作/缺失端点，必须修复）
- _LOCAL_ACTIONS 本地动作表 ↔ permissions 对账（W6：不经 Sender 的动作也受门禁约束）
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
    src = (ROOT / "src/adapters/onebot/adapter.py").read_text(encoding="utf-8")
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


def _local_actions() -> dict:
    """manager._LOCAL_ACTIONS：本地动作 → 权限名（W6 对账门禁）。"""
    tree = ast.parse((ROOT / "src/plugins/manager.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Dict):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == "_LOCAL_ACTIONS" for t in targets):
                out = {}
                for k, v in zip(node.value.keys, node.value.values):
                    if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                        out[k.value] = v.value
                return out
    return {}


def _bot_public_methods(path) -> set:
    """FlowerieBot 的公开方法集合（AST 提取，不导入模块）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    methods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == "FlowerieBot":
            for f in n.body:
                if (isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and not f.name.startswith("_")):
                    methods.add(f.name)
    return methods


def test_plugin_fixture_sdk_methods_subset():
    """插件夹具自带的 SDK 副本：公开方法必须是本体子集（W8）。

    副本由插件作者随插件分发，无法保证与本体同步（新方法缺失是副本作者责任）；
    但副本不得声明本体没有的方法（幻影 API：插件调用必然失败）。
    """
    main = _bot_public_methods(ROOT / "plugin_sdk" / "flowerie_sdk" / "bot.py")
    assert main, "本体 FlowerieBot 解析失败"
    fixtures = sorted((ROOT / "tests" / "plugins").glob("*/flowerie_sdk/bot.py"))
    assert fixtures, "未找到插件夹具 SDK 副本（测试失效）"
    for fixture in fixtures:
        phantom = _bot_public_methods(fixture) - main
        assert not phantom, f"{fixture.parent.parent.name} 副本含本体没有的方法: {sorted(phantom)}"


def test_local_actions_have_permissions():
    """本地动作（不经 Sender）也必须登记权限映射（W6：补齐 _SENDER_ACTIONS 之外的门禁盲区）。

    本地动作不经 Sender，四向一致性鞭长莫及；这里要求它与 permissions 表逐条对账，
    避免「删映射/加动作忘了登记」导致未授权能力悄悄上线。
    """
    actions = _local_actions()
    assert actions, "本地动作表为空（_LOCAL_ACTIONS 解析失败）"
    perms = _permissions()
    problems = []
    for action, declared in sorted(actions.items()):
        if declared is None:
            problems.append(f"本地动作 {action} 未登记权限")
            continue
        mapped = perms.get(action)
        if mapped is None:
            problems.append(f"本地动作 {action} 缺 permissions 映射")
        elif mapped.strip('"') != declared:
            problems.append(f"本地动作 {action} 声明权限 {declared} 与 permissions 映射 {mapped} 不一致")
    assert not problems, "本地动作权限对账失败: " + "; ".join(problems)


def test_docs_api_matches_implementation():
    """api.md 权威速查表方法集 ⊆ PluginApi 方法集（文档不承诺不存在的能力）。"""
    api_doc = (ROOT / "docs/reference/api.md").read_text(encoding="utf-8")
    doc_methods = set(re.findall(r"^\| `(\w+)\(`", api_doc, re.M)) | set(
        re.findall(r"^\| `(\w+)\(", api_doc, re.M))
    tree = ast.parse((ROOT / "src/plugins/runner/python_runner.py").read_text(encoding="utf-8"))
    impl = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == "PluginApi":
            impl = {f.name for f in n.body if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}
    missing = doc_methods - impl
    assert not missing, f"api.md 提及但实现缺失: {sorted(missing)}"
