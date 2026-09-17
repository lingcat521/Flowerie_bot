"""群特色昵称面板渲染（零 JS：表单 POST 重渲染；列表用卡片而非表格）。

隔离语义：昵称按「群 × 人设」存储——群绑定人设后，唤名/注入随当前人设联动；
未绑定人设时用群级昵称；都无 → BOT_NICKNAME 默认。
"""
from html import escape


def _pid_label(personas, pid):
    """人设 id → 展示名（找不到则原样 id）。"""
    for _pid, name in personas:
        if _pid == pid:
            return name
    return pid


def _sort_key(key: str):
    gid, _, pid = key.partition(":")
    return (int(gid) if gid.isdigit() else 0, pid)


def render_nicknames_tab(nicknames: dict, default: str, msg: str = "",
                         group_ids: list = None, personas: list = None) -> str:
    """nicknames: {key: nickname}（key = "gid" 或 "gid:persona_id"）。

    group_ids：最近消息过的群（选择器提示）；personas：[(id, name)]（人设徽标）。
    """
    group_ids = list(group_ids or [])
    personas = list(personas or [])
    cards = []

    for key in sorted(nicknames, key=_sort_key):
        gid, _, pid = key.partition(":")
        gid_s = gid if gid else "—"
        input_name = f"nick_{gid}__{pid}" if pid else f"nick_{gid}"
        if pid:
            badge = f'<span class="nick-persona">{escape(_pid_label(personas, pid))}</span>'
        else:
            badge = '<span class="nick-persona group">群级</span>'
        cards.append(
            '<div class="mcp-card nick-card">'
            f'<div class="nick-head"><span class="nick-gid">群 {escape(gid_s)}</span>{badge}</div>'
            f'<input type="text" name="{input_name}" value="{escape(nicknames[key])}"'
            ' maxlength="20" placeholder="留空恢复默认">'
            '</div>')

    hint = f'<p class="alert ok">{escape(msg)}</p>' if msg else ""
    empty = ('<p class="hint">还没有配置——在下面选群（或填群号）新增一条即可。</p>'
             if not cards else "")
    save_row = ('<div class="group-actions"><button type="submit" class="btn">保存全部修改</button>'
                '</div>' if cards else "")

    gopts = "".join(f'<option value="{g}">' for g in group_ids)
    popts = '<option value="">（群级）</option>' + "".join(
        f'<option value="{escape(pid)}">{escape(name)}</option>' for pid, name in personas)
    picker = (
        '<div class="mcp-card">'
        '<div class="nick-head"><b>新增 / 覆盖</b>'
        '<span class="hint">昵称留空＝删除该条目</span></div>'
        '<div class="nick-add">'
        '<input list="gidlist" name="group_id" placeholder="群号" pattern="[0-9]+">'
        f'<datalist id="gidlist">{gopts}</datalist>'
        f'<select name="persona_id">{popts}</select>'
        '<input type="text" name="nickname" maxlength="20" placeholder="昵称（留空删除）">'
        '<button type="submit" class="btn small">添加 / 覆盖</button>'
        '</div></div>'
    )

    return (
        '<h2>群特色昵称（× 人设隔离）</h2>'
        f'<p>全局默认：<b>{escape(default)}</b>　'
        '群绑定人设后，唤名随当前人设联动（人设命中 → 群级 → 默认）</p>'
        f"{hint}{empty}"
        '<form method="post" action="/panel/nicknames">'
        f'<div class="nick-grid">{"".join(cards)}</div>'
        f'{save_row}{picker}'
        '<p class="hint">昵称注入该群 AI 提示词的【本群专属称呼】段；≤20 字，自动剥离控制字符；'
        '留空＝恢复默认（删除该条目）。 <a href="/panel/nicknames">刷新</a></p>'
        '</form>'
    )
