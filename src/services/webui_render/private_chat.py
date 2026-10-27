"""私聊面板渲染（v2.14.0）：开关状态 / 允许名单 / 每人记忆清空。零 JavaScript。"""
from typing import Any, Dict, List

from src.services.webui_render.util import _esc


def render_private_tab(*, enabled: bool, allowed: List[int], admins: List[int],
                       cooldown: int, context_size: int, memory_enabled: bool,
                       users: List[Dict[str, Any]], msg: str = "", err: bool = False) -> str:
    msg_html = ""
    if msg:
        msg_html = '<div class="msg %s">%s</div>' % ("err" if err else "ok", _esc(msg))
    state = "已开启" if enabled else "未开启"
    allow_text = ", ".join(str(x) for x in allowed) if allowed else "（空：仅 ADMIN_QQ_IDS 可私聊）"
    admin_text = ", ".join(str(x) for x in admins) if admins else "（未配置管理员）"
    rows = ""
    for item in users:
        qq = int(item.get("qq") or 0)
        notes = int(item.get("notes") or 0)
        rows += (
            '<tr><td>%s</td><td>%d</td>'
            '<td><form method="post" action="/panel/private/clear">'
            '<input type="hidden" name="qq" value="%d">'
            '<button class="btn small danger" type="submit">清空私聊记忆</button>'
            '</form></td></tr>' % (qq, notes, qq)
        )
    if not rows:
        rows = '<tr><td colspan="3">还没有私聊记录（只统计有记忆的用户）</td></tr>'
    return (
        msg_html +
        '<div class="group"><h2>私聊状态</h2>'
        '<p>开关：<b>%s</b>　冷却：<b>%d 秒</b>　上下文：<b>%d 条</b>　记忆：<b>%s</b></p>'
        '<p>允许私聊 QQ：%s</p><p>管理员（自动允许）：%s</p>'
        '<p class="hint">私聊与群聊完全隔离：每位 QQ 用独立的虚拟会话 key（负数）存上下文/记忆/预算，'
        '互不可见。开关与冷却等配置在 <a href="/panel?cat=PrivateChat">配置 · 私聊</a>。</p></div>' % (
            _esc(state), int(cooldown), int(context_size), _esc("开" if memory_enabled else "关"),
            _esc(allow_text), _esc(admin_text)) +
        '<div class="group"><h2>允许名单</h2>'
        '<p class="hint">每行一个 QQ，或用逗号分隔；留空表示只允许 ADMIN_QQ_IDS。</p>'
        '<form method="post" action="/panel/private/allowlist">'
        '<textarea name="qqs" rows="5" placeholder="123456&#10;234567">%s</textarea>'
        '<button class="btn" type="submit">保存允许名单</button></form></div>' % _esc(", ".join(str(x) for x in allowed)) +
        '<div class="group"><h2>私聊用户</h2>'
        '<table><thead><tr><th>QQ</th><th>记忆条数</th><th>操作</th></tr></thead>'
        '<tbody>%s</tbody></table></div>' % rows
    )
