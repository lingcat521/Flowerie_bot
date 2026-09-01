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
             "> 语义方法若网关无对应端点，运行时返回 `not supported in v1`（绝不静默）。", "", ""]
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
            doc = api[m].splitlines()[0] if api[m] else ""
            lines.append(f"| `{m}(payload)` | {doc} | `{perms.get(m, '—')}` |")
        lines.append("")
    rest = [m for m in sorted(api) if m not in used]
    if rest:
        lines.append("**其他**")
        lines.append("| 方法 | 作用 | 权限 |")
        lines.append("| --- | --- | --- |")
        for m in rest:
            doc = api[m].splitlines()[0] if api[m] else ""
            lines.append(f"| `{m}(payload)` | {doc} | `{perms.get(m, '—')}` |")
        lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"api.md 生成：{len(api)} 方法 → {OUT}")


if __name__ == "__main__":
    main()
