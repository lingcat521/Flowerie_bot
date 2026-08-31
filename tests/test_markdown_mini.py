"""迷你 markdown 渲染器（受控文档用；先转义后结构化=无 XSS）。"""

from src.services.webui_render.markdown_mini import render_doc, render_md


def test_headings_code_lists_bold():
    html = render_md("""# 标题

```python
x = '<script>'
```

- **粗体**项目
- `代码`

1. 第一
2. 第二
""")
    assert "<h3>标题</h3>" in html          # # → h3（在 article 内避免与页面标题冲突）
    assert "<pre><code>" in html
    assert "&lt;script&gt;" in html          # 代码内 HTML 已转义
    assert "<strong>" in html
    assert "<ul>" in html and "<ol>" in html


def test_markdown_injection_escaped():
    html = render_md("""# hi<script>alert(1)</script>

[a](javascript:alert(1))
""")
    assert "<script>" not in html
    assert 'href="javascript:' not in html       # 危险协议不得成为链接（可保留纯文本）


def test_render_doc_quickstart_exists():
    html = render_doc("quick-start.md")
    assert "10 分钟" in html or "快速开始" in html
