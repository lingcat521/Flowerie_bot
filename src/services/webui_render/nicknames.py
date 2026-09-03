"""群特色昵称面板渲染（零 JS：表单 POST 重渲染）。

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


def render_nicknames_tab(nicknames: dict, default: str, msg: str = "",
                         group_ids: list = None, personas: list = None) -> str:
    """nicknames: {key: nickname}（key = "gid" 或 "gid:persona_id"）。

    group_ids：最近消息过的群（选择器提示）；personas：[(id, name)]（人设列）。
    """
    group_ids = list(group_ids or [])
    personas = list(personas or [])
    rows = []

    def _key_parts(key: str):
        gid, _, pid = key.partition(":")
        return int(gid) if gid.isdigit() else 0, pid

    for key in sorted(nicknames, key=lambda k: (int(k.split(":")[0]) if k.split(":")[0].isdigit() else 0, k.split(":", 1)[-1])):
        gid, pid = _key_parts(key)
        gid_s = str(gid)
        input_name = f"nick_{gid_s}__{pid}" if pid else f"nick_{gid_s}"
        pid_cell = f'<td>{escape(_pid_label(personas, pid))}</td>' if pid else '<td>—</td>'
        rows.append(
            f'<tr><td>{escape(gid_s)}</td>{pid_cell}'
            f'<td><input type="text" name="{input_name}" value="{escape(nicknames[key])}" '
            f'maxlength="20" placeholder="留空恢复默认"></td></tr>')

    hint = f'<p style="color:#2ea043"><b>{escape(msg)}</b></p>' if msg else ""
    empty = '<p>还没有配置——选群（或填群号）即可生效。</p>' if not rows else ""

    # 群选择器（datalist 零 JS 输入提示）+ 人设选择器（select 下拉）
    gopts = "".join(f'<option value="{g}">' for g in group_ids)
    popts = '<option value="">（群级）</option>' + "".join(
        f'<option value="{escape(pid)}">{escape(name)}</option>' for pid, name in personas)
    picker = (
        '<p><b>新增 / 覆盖：</b>'
        '<input list="gidlist" name="group_id" placeholder="群号" pattern="[0-9]+">'
        f'<datalist id="gidlist">{gopts}</datalist>'
        f'<select name="persona_id">{popts}</select>'
        '<input type="text" name="nickname" maxlength="20" placeholder="昵称（留空删除）"></p>'
    )

    return (
        '<h2>群特色昵称（× 人设隔离）</h2>'
        f'<p>全局默认：<b>{escape(default)}</b>　'
        '群绑定人设后，唤名随当前人设联动（人设命中 → 群级 → 默认）</p>'
        f"{hint}{empty}"
        '<form method="post" action="/panel/nicknames">'
        '<table><tr><th>群号</th><th>人设</th><th>专属昵称</th></tr>'
        + "".join(rows) +
        '</table>'
        f'{picker}'
        '<p><button type="submit">保存 / 添加</button>'
        ' <a href="/panel/nicknames">刷新</a></p>'
        '</form>'
        '<p><small>昵称注入该群 AI 提示词的【本群专属称呼】段；≤20 字，自动剥离控制字符；'
        '留空＝恢复默认（删除该条目）。</small></p>'
    )
