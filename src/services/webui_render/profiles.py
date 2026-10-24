"""webui_render 群友画像页：按群查看 / 手工编辑 / 删除（严格按群隔离）。

画像数据来自 MemberProfileService（每日摘要后提炼的性格/喜好/个人生活/特点）。
纯服务端渲染（零 JS）：所有操作都是表单 POST，与既有面板同一套 CSS。
"""
import time

from src.services.webui_render.config_panel import _render_config_row
from src.services.webui_render.util import _esc


def _fmt_ts(ts) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))
    except (TypeError, ValueError):
        return ""


def _member_card(group_id: int, member: dict) -> str:
    """单个群友画像卡片：昵称 + 各字段（含上次更新时间）+ 编辑/删除表单。"""
    uid = member.get("user_id", 0)
    nick = _esc(member.get("nickname") or "")
    head = '<fieldset class="group"><legend>用户 %d' % uid
    if nick:
        head += '（%s）' % nick
    head += '</legend>'
    parts = [head]
    for sec in member.get("sections") or []:
        label = _esc(sec.get("label") or "")
        name = _esc(sec.get("name") or label)
        text = _esc(sec.get("text") or "")
        ts = _fmt_ts(sec.get("ts"))
        parts.append(
            '<div class="row"><label class="row-info"><span class="row-title">%s</span>'
            '<span class="row-key">%s</span></label>'
            '<form class="row-control" method="post" action="/panel/profile/save">'
            '<input type="hidden" name="group_id" value="%d">'
            '<input type="hidden" name="user_id" value="%d">'
            '<input type="hidden" name="label" value="%s">'
            '<input type="hidden" name="nickname" value="%s">'
            '<div style="display:flex;gap:8px;flex-wrap:wrap">'
            '<input class="w-lg" type="text" name="text" value="%s" maxlength="120">'
            '<button type="submit" class="btn small">保存</button>'
            '</div><span class="hint">上次更新 %s</span></form></div>'
            % (name, label, group_id, uid, label, nick, text, ts))
    if not (member.get("sections") or []):
        parts.append('<div class="msg">该群友暂无画像字段</div>')
    parts.append(
        '<div class="group-actions">'
        '<form method="post" action="/panel/profile/delete" style="display:inline">'
        '<input type="hidden" name="group_id" value="%d">'
        '<input type="hidden" name="user_id" value="%d">'
        '<button type="submit" class="btn small">删除该群友画像</button></form>'
        '</div></fieldset>' % (group_id, uid))
    return "".join(parts)


def render_profile_tab(group_id, members, enabled=True, count=0, groups=None,
                       profile_configs=None) -> str:
    """群友画像管理页（零 JS）：输入群号查看，手工修正/删除画像（按群隔离）。"""
    if not enabled:
        return '<div class="msg err">群友画像未开启（PROFILE_ENABLED=false）；开启后每日摘要会自动提炼画像</div>'
    view_block = (
        '<fieldset class="group"><legend>群友画像（Member Profile：性格/喜好/个人生活/特点）</legend>'
        '<form method="post" action="/panel/profile/view">'
        '<div class="row"><label class="row-info"><span class="row-title">查看指定群的画像</span>'
        '<span class="row-key">group_id</span></label>'
        '<div class="row-control" style="flex-direction:row;gap:10px;flex-wrap:wrap">'
        '<input class="w-gid" type="text" name="group_id" placeholder="群号" required'
        + (f' value="{_esc(group_id)}"' if group_id else '') + '>'
        '<button type="submit" class="btn small">查看</button></div>'
        '<span class="hint">画像按群隔离，由每日摘要自动提炼，也可在此手工修正</span>'
        '</div></form>'
        + (
            '<div class="mcp-card-meta">有画像的群：'
            + " ".join(
                '<a href="/panel?tab=profiles&gid=%d">%d</a>' % (g, g) for g in (groups or [])
            ) + '</div>' if groups else ""
        )
        + '</fieldset>'
    )
    if not group_id:
        return view_block
    members_html = "".join(_member_card(int(group_id), m) for m in (members or []))
    clear_block = (
        '<fieldset class="group"><legend>清空本群画像</legend>'
        '<form method="post" action="/panel/profile/clear">'
        f'<input type="hidden" name="group_id" value="{_esc(group_id)}">'
        '<span class="hint">删除本群全部画像（不可恢复）；单人删除请用卡片内的按钮</span>'
        '<div class="group-actions"><button type="submit" class="btn small">清空本群画像</button></div>'
        '</form></fieldset>'
    )
    config_block = ""
    if profile_configs:
        rows = "".join(_render_config_row(c) for c in profile_configs)
        config_block = (
            '<fieldset class="group"><legend>画像配置</legend>'
            '<form method="post" action="/panel/save">'
            + rows
            + '<div class="group-actions"><button type="submit" class="btn">保存配置</button></div>'
            '</form></fieldset>'
        )
    header = (
        f'<div class="mcp-card-meta">当前群 {_esc(group_id)}：已建档 {count} 位群友'
        '（注入对话的活跃成员上限见 PROFILE_MAX_MEMBERS）</div>'
    )
    return view_block + header + members_html + clear_block + config_block
