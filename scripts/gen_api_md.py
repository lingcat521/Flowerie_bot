"""api.md 生成器：AST 提取 PluginApi 方法 + permissions 动作映射 → 权威索引（可重复运行）。"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/api.md"

GROUPS = {
    "消息": ("send_", "delete_message", "get_message", "get_group_history", "get_context"),
    "群": ("group_", "is_group", "group"),
    "关系/用户": ("user_", "friend", "friends", "get_user", "login_info", "devices", "status"),
    "社交互动": ("react", "tap", "poke", "like", "pin", "unpin", "emoji", "essence"),
    "记忆/存储": ("memory", "mem_", "kv_"),
    "插件运行时": ("matcher_", "schedule_", "plugin", "kv_"),
    "AI/MCP": ("ai_", "http_", "http_request", "mcp_"),
}


def _describe(method: str, doc: str) -> str:
    """方法说明：优先 docstring 首行；没有 docstring 时从实现里推导，保证表格不出现空说明。

    - self._send_action("x", ...) -> 引擎动作 x 的语义封装
    - self._runner._y(...)        -> runner 本地实现 y
    """
    if doc:
        return doc.splitlines()[0].strip()
    path = ROOT / "src/plugins/runner/python_runner.py"
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
    except (OSError, SyntaxError):
        return "-"
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name != method:
            continue
        seg = ast.get_source_segment(text, node) or ""
        m = re.search(r'self\._send_action\("([^"]+)"', seg)
        if m:
            return "引擎动作 %s 的语义封装。" % m.group(1)
        m = re.search(r"self\._runner\.(\w+)\(", seg)
        if m:
            return "runner 本地实现 %s。" % m.group(1).lstrip("_")
    return "-"


def main():
    tree = ast.parse((ROOT / "src/plugins/runner/python_runner.py").read_text(encoding="utf-8"))
    api = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == "PluginApi":
            for f in n.body:
                if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    api[f.name] = ast.get_docstring(f) or ""
    perms = dict(re.findall(r'    "(\w+)": "(\w+)",',
                            (ROOT / "src/plugins/permissions.py").read_text(encoding="utf-8")))
    lines = ["# Flowerie API 总索引（自动生成·唯一事实来源）", "",
             "> 由 scripts/gen_api_md.py 生成（AST from PluginApi）；端点名（OneBot）不出现在此。",
             "> 语义方法若网关无对应端点，运行时返回 `not supported in v1`（绝不静默）。",
             "> 插件间通信（PluginCommApi：`plugin.call/emit/on/expose/cancel`）不在本索引，见 [plugin-developer-guide.md](plugin-developer-guide.md) §8。", "", ""]
    used = set()
    for group, prefixes in GROUPS.items():
        members = [m for m in sorted(api) if m not in used and m.startswith(prefixes)]
        if not members:
            continue
        used.update(members)
        lines.append(f"**{group}**")
        lines.append("| 方法 | 作用 | 权限 |")
        lines.append("| --- | --- | --- |")
        for m in members:
            doc = _describe(m, api[m])
            lines.append(f"| `{m}(payload)` | {doc} | `{perms.get(m, '—')}` |")
        lines.append("")
    rest = [m for m in sorted(api) if m not in used]
    if rest:
        lines.append("**其他**")
        lines.append("| 方法 | 作用 | 权限 |")
        lines.append("| --- | --- | --- |")
        for m in rest:
            doc = _describe(m, api[m])
            lines.append(f"| `{m}(payload)` | {doc} | `{perms.get(m, '—')}` |")
        lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"api.md 生成：{len(api)} 方法 → {OUT}")


if __name__ == "__main__":
    main()
