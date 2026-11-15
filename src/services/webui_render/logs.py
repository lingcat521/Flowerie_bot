"""Render a selectable card for each record in the in-memory log buffer."""

from collections.abc import Sequence
from html import escape

from src.services.webui_render.graphics import empty_state


def render_logs(records: Sequence[str], limit: int, panel_opacity: int = 100) -> str:
    if records:
        items = "".join(
            f'<li><pre class="log-entry"><span>{escape(record)}</span></pre></li>'
            for record in records
        )
        body = (
            '<div class="log-scroll" role="region" aria-labelledby="runtime-log-title" tabindex="0">'
            f'<ul class="log-entries" role="list">{items}</ul></div>'
        )
    else:
        body = empty_state("logs", "暂无运行日志。")
    return (
        f'<div class="log-toolbar"><span>最近 {limit} 条</span>'
        '<div class="log-actions">'
        '<form class="log-opacity" method="post" action="/panel/appearance/log-opacity">'
        '<label for="log-opacity">面板不透明度</label>'
        '<span class="log-opacity-value">'
        f'<input type="number" id="log-opacity" name="panel_opacity" min="0" max="100"'
        f' value="{panel_opacity:d}" required><span aria-hidden="true">%</span></span>'
        '<button class="btn secondary" type="submit">应用</button></form>'
        '<a href="/panel?tab=logs" class="btn secondary">刷新</a></div></div>'
        '<section class="log-frame"><h2 id="runtime-log-title">运行日志</h2>'
        f'{body}</section>'
    )
