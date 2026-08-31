"""迷你 Markdown → HTML 渲染（零依赖；先转义后结构化，杜绝 XSS）。

仅用于渲染 docs 内受控文档（quick-start 等）。表格/图片不渲染——需要时扩展。
"""
import html
import re
from typing import List


def render_md(text: str) -> str:
    """把受控 markdown 渲染到 <article> 内 HTML。"""
    lines = text.splitlines()
    out: List[str] = []
    i = 0
    in_code = False
    buf: List[str] = []
    in_list: str = ""   # "ul" | "ol"

    def flush_para():
        if buf:
            out.append(f"<p>{_inline(' '.join(buf))}</p>")
            buf.clear()

    def close_list():
        nonlocal in_list
        if in_list:
            out.append(f"</{in_list}>")
            in_list = ""

    while i < len(lines):
        ln = lines[i]
        if ln.strip().startswith("```"):
            if in_code:
                out.append("<pre><code>" + html.escape("\n".join(buf)) + "</code></pre>")
                buf.clear()
                in_code = False
            else:
                flush_para()
                close_list()
                in_code = True
            i += 1
            continue
        if in_code:
            buf.append(ln)
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            flush_para()
            close_list()
            lvl = min(len(m.group(1)) + 2, 6)
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            i += 1
            continue
        m = re.match(r"^\s*[-*]\s+(.*)$", ln)
        if m:
            flush_para()
            if in_list != "ul":
                close_list()
                in_list = "ul"
                out.append("<ul>")
            out.append(f"<li>{_inline(m.group(1))}</li>")
            i += 1
            continue
        m = re.match(r"^\s*\d+[.)]\s+(.*)$", ln)
        if m:
            flush_para()
            if in_list != "ol":
                close_list()
                in_list = "ol"
                out.append("<ol>")
            out.append(f"<li>{_inline(m.group(1))}</li>")
            i += 1
            continue
        if re.match(r"^\s*---+\s*$", ln):
            flush_para()
            close_list()
            out.append("<hr>")
            i += 1
            continue
        if ln.strip().startswith(">"):
            flush_para()
            out.append(f"<blockquote>{_inline(ln.strip().lstrip('>').strip())}</blockquote>")
            i += 1
            continue
        if not ln.strip():
            flush_para()
            close_list()
            i += 1
            continue
        buf.append(ln)
        i += 1
    flush_para()
    close_list()
    return "<article class=\"doc\">" + "\n".join(out) + "</article>"


def _inline(s: str) -> str:
    """转义 + 行内标记（代码/粗体/链接——链接协议白名单，堵 javascript:/data:）。"""
    s = html.escape(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)

    def link(m):
        text, href = m.group(1), m.group(2)
        if re.match(r"^(https?://|mailto:|/|docs/|\.\./|#)", href):
            return f'<a class="doc-link" href="{href}">{text}</a>'
        return m.group(0)  # 危险协议：保留纯文本，不成链接

    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, s)
    return s


def render_doc(rel_md: str) -> str:
    """读 docs 内 markdown 文件并渲染（受控：仅 docs 目录 basename）。"""
    import os
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    path = os.path.join(root, "docs", os.path.basename(rel_md))
    if not os.path.isfile(path):
        return "<p>文档不存在</p>"
    return render_md(open(path, encoding="utf-8").read())
