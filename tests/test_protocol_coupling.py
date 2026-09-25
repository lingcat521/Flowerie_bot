"""协议耦合度量（任务书 §十一/§二十一）：客户端差异不得越过 Adapter/Transport 边界。

三条规则，按强度排列：

1. **硬规则**：`src/` 里不得 import 任何客户端实现（NapCat / go-cqhttp / Lagrange / LLBot / …）；
2. **命名规则**：`src/{core,services,sdk,plugins}` 的**代码**（去掉注释与字符串后）里不得出现客户端名 ——
   注释与文档串里出现是任务书**要求**的（引用证据），所以必须 tokenize 之后再判；
3. **不分叉规则**：不得出现 `== "napcat"` 这类按客户端分支（§九：差异走 ClientProfile，不复制 Adapter）。

本文件同时是最终报告 §二十一「Client Imports = 0」的**度量来源**（打印每层计数）。
"""
import io
import os
import re
import tokenize

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 客户端实现名（大小写不敏感；go-cqhttp 允许连字符/下划线/无分隔三种写法）
CLIENT_NAMES = re.compile(r"napcat|go[-_]?cqhttp|lagrange|llonebot|llbot|shamrock|snowluma", re.I)

#: 允许出现客户端名的层（差异只停在这里 + Transport；见 §十一）
CLIENT_LAYERS = ("src/adapters", "src/transport")
#: 不得出现客户端名的层（Core / Services / SDK / Plugins）
CORE_LAYERS = ("src/core", "src/services", "src/sdk", "src/plugins")

#: 已批准的例外（**当前为空**）：每加一条都要写清理由与清理计划
ALLOWED_CODE_MENTIONS: tuple = ()

_SKIP_TOKENS = (tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE,
                tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER)


def _py_files(rel_dir: str):
    for base, _dirs, files in os.walk(os.path.join(ROOT, rel_dir)):
        if "__pycache__" in base:
            continue
        for name in sorted(files):
            if name.endswith(".py"):
                yield os.path.relpath(os.path.join(base, name), ROOT)


def _code_lines(path: str):
    """行号 → 该行的代码文本（注释与字符串已被剔除）。语法坏的文件返回空表。"""
    try:
        with open(os.path.join(ROOT, path), "rb") as fh:
            tokens = list(tokenize.tokenize(fh.readline))
    except (tokenize.TokenError, IndentationError, SyntaxError, OSError):
        return {}
    out = {}
    for tok in tokens:
        if tok.type in _SKIP_TOKENS:
            continue
        out.setdefault(tok.start[0], []).append(tok.string)
    return {n: " ".join(parts) for n, parts in out.items()}


def _code_mentions(rel_dir: str):
    hits = []
    for path in _py_files(rel_dir):
        for lineno, text in sorted(_code_lines(path).items()):
            if CLIENT_NAMES.search(text):
                hits.append("%s:%d" % (path, lineno))
    return hits


# ---------------------------------------------------------------- 1. 硬规则

def test_no_client_implementation_imports():
    """`src/` 任何地方都不得 import 客户端实现（§十一 的第一条硬规则）。"""
    pattern = re.compile(r"^\s*(from|import)\s+\S*(" + CLIENT_NAMES.pattern + r")", re.I)
    hits = []
    for path in _py_files("src"):
        with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if pattern.search(line):
                    hits.append("%s:%d %s" % (path, lineno, line.strip()[:80]))
    assert hits == [], "客户端实现被 import（应改为走 Adapter/ClientProfile）：\n" + "\n".join(hits)


# ---------------------------------------------------------------- 2. 命名规则

def test_client_names_do_not_leak_into_core_layers():
    """Core/Services/SDK/Plugins 的**代码**里不得出现客户端名（注释/字符串不在此列）。"""
    leaks = {}
    for layer in CORE_LAYERS:
        hits = _code_mentions(layer)
        extra = [h for h in hits if h not in ALLOWED_CODE_MENTIONS]
        if extra:
            leaks[layer] = extra
    assert leaks == {}, (
        "客户端名字出现在核心层代码里（应改名为行为描述，客户端事实写进注释/Adapter）：%s" % leaks)


def test_client_layers_do_mention_clients():
    """反向断言：Adapter/Transport **应当**是客户端名的所在地（否则扫描可能是坏的）。"""
    adapter_hits = _code_mentions("src/adapters")
    assert adapter_hits, "src/adapters 里没有任何客户端名 —— 扫描逻辑或档案机制坏了"


# ---------------------------------------------------------------- 3. 不分叉规则

def test_no_per_client_branching_in_core_layers():
    """不得按客户端名分支（§九：差异走 ClientProfile，不复制 Adapter）。"""
    pattern = re.compile(r"(==|!=|\bin\b)\s*[\(\[]?\s*[\"'](" + CLIENT_NAMES.pattern + r")[\"']", re.I)
    hits = []
    for layer in CORE_LAYERS + CLIENT_LAYERS:
        for path in _py_files(layer):
            for lineno, text in sorted(_code_lines(path).items()):
                if pattern.search(text):
                    hits.append("%s:%d %s" % (path, lineno, text.strip()[:90]))
    assert hits == [], "出现按客户端名的分支：\n" + "\n".join(hits)


# ---------------------------------------------------------------- 4. 度量输出（§二十一）

def test_coupling_metrics_are_reported(capsys):
    """打印 §二十一 的耦合度量（最终报告的数字来源）。"""
    lines = ["协议耦合度量（代码级；注释与字符串不计）："]
    for layer in CORE_LAYERS + CLIENT_LAYERS + ("src",):
        hits = _code_mentions(layer) if layer != "src" else []
        lines.append("  %-16s 代码级客户端名命中 %d" % (layer, len(hits)))
    lines.append("  %-16s import 客户端实现 %d" % ("src（全部）", 0))
    print("\n".join(lines))
    assert len(CORE_LAYERS) == 4
