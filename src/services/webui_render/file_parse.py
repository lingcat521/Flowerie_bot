"""The zero-JavaScript file preview form and escaped extraction output."""

from html import escape


def render_file_preview(status, result=None):
    formats = []
    for name, info in status["formats"].items():
        label = "已启用" if info["enabled"] and status["enabled"] else "已关闭"
        if not info["available"]:
            label = "缺少依赖"
        formats.append(f'<li><strong>{escape(name.upper())}</strong> {label}</li>')
    preview = ""
    if result and result["ok"]:
        preview = (
            f'<h3>提取结果 · {escape(result["filename"])}</h3>'
            + ('<p class="hint">文本超过上限，已截断。</p>' if result["truncated"] else "")
            + (f'<pre class="file-parse-result" tabindex="0">{escape(result["text"])}</pre>'
               if result["text"] else '<p class="hint">文件中没有可提取的文本。</p>')
        )
    disabled = "" if status["enabled"] else " disabled"
    return (
        '<section class="group"><h2>上传试解析</h2>'
        '<ul class="file-parse-formats" aria-label="格式状态">' + "".join(formats) + '</ul>'
        f'<p class="hint">使用已保存的设置。最多 {status["max_bytes"]:,} 字节。'
        '试解析只提取文本，不会发送给模型。</p>'
        '<form action="/panel/files/preview" method="post" enctype="multipart/form-data">'
        '<label for="parse-file">选择文件</label>'
        f'<input id="parse-file" name="file" type="file" required{disabled}>'
        f'<div class="group-actions"><button class="btn" type="submit"{disabled}>提取文本</button></div>'
        '</form>' + preview + '</section>'
    )
