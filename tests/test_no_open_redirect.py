"""Code Scanning py/url-redirection 的证明性测试：所有重定向目标必须是站内 /panel 路径。

审计结论（17 条全部为 False Positive）：
- 全部 web.HTTPFound(...) 的目标都是硬编码 "/panel" 前缀 + 查询串；
- 插入查询串的用户输入要么经 urllib.parse.quote 转义，要么先过 isdigit()（群号）；
- 插件 WebUI 的 {pid}/{page} 来自 aiohttp 路由段（不含 "/"），无法凑出 scheme://host。
  → Location 永远是站内相对路径，不构成开放重定向。
CodeQL 看不到「常量前缀 + 转义」这层保证，本测试把它固定下来。

不变量（硬性）：
    每个 HTTPFound 的目标要么是 "/panel" 开头的常量，
    要么是 f-string 且其第一个字面量片段以 "/panel" 开头。
    出现任何「整串来自变量」的重定向，本测试立即失败。
"""
import ast
import io
import os

PANELS_DIR = "src/services/webui_panels"
PREFIX = "/panel"


def _panel_sources():
    for name in sorted(os.listdir(PANELS_DIR)):
        if name.endswith(".py"):
            path = os.path.join(PANELS_DIR, name)
            yield path, io.open(path, encoding="utf-8").read()


def _httpfound_targets(src: str):
    """产出所有 HTTPFound(...) 调用的第一个参数 AST 节点。"""
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "HTTPFound" and node.args:
            yield node.args[0]


def _first_literal(node):
    """取出目标里的第一个字面量片段。

    支持三种写法（都很常见）：
        web.HTTPFound("/panel")                   常量
        web.HTTPFound(f"/panel?msg={x}")          f-string
        web.HTTPFound("/panel?msg=" + quote(x))   字符串拼接（左结合，递归左侧）
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and node.values:
        head = node.values[0]
        if isinstance(head, ast.Constant) and isinstance(head.value, str):
            return head.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _first_literal(node.left)
    return None


def test_every_redirect_stays_within_panel():
    bad = []
    total = 0
    for path, src in _panel_sources():
        for target in _httpfound_targets(src):
            total += 1
            head = _first_literal(target)
            if head is None or not head.startswith(PREFIX):
                bad.append((path, ast.dump(target)[:120]))
    assert total > 0, "没找到任何 HTTPFound（测试失效？）"
    assert bad == [], "存在非 /panel 前缀的重定向目标：%s" % bad


def test_no_redirect_target_comes_from_a_bare_variable():
    """整串来自变量的重定向（开放重定向的典型形态）必须为 0。"""
    bad = []
    for path, src in _panel_sources():
        for target in _httpfound_targets(src):
            if isinstance(target, ast.Name) or (
                    isinstance(target, ast.Call) and not isinstance(target, ast.JoinedStr)):
                bad.append((path, ast.dump(target)[:100]))
    assert bad == [], bad


# 说明（任务书 §10：区分「误报」与「暂时无法证明」）：
# 第三项「插入查询串的片段是否已转义」**不做静态断言** —— 静态看 AST 无法知道
# 上游是否已经过 isdigit()/白名单门禁（例如 knowledge_panel 先判 gid_raw.isdigit()，
# config_panel 先判 cat in ConfigService.CATEGORY_ORDER），强行断言只会产生误报。
# 该结论由人工审计给出（见提交说明）：17 处重定向的插入片段全部是
# quote(...) 转义 / isdigit() 门禁 / 上游已 quote 的成品串（gid_q、_catq）/
# 已过白名单的分类名（cat），因此不构成开放重定向。
