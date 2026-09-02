"""群特色昵称面板渲染（零 JS：表单 POST 重渲染）。

免责语义：昵称会注入 system prompt 的【本群专属称呼】段（写入前已清洗/截断
≤20 字 + 控制字符剥离），此处再转义展示。
"""
from html import escape


def render_nicknames_tab(nicknames: dict, default: str, msg: str = "") -> str:
    """nicknames: {group_id_str: nickname}；default：全局默认（BOT_NICKNAME）。"""
    rows = []
    for gid in sorted(nicknames, key=lambda x: int(x)):
        rows.append(
            '<tr><td>%s</td><td><input type="text" name="nick_%s" value="%s" '
            'maxlength="20" placeholder="留空恢复默认"></td></tr>'
            % (escape(gid), int(gid), escape(nicknames[gid])))

    hint = ""
    if msg:
        hint = '<p style="color:#2ea043"><b>%s</b></p>' % escape(msg)
    empty = ""
    if not rows:
        empty = '<p>还没有配置任何群的专属昵称——填入群号即可生效。</p>'

    return (
        '<h2>群特色昵称</h2>'
        f'<p>全局默认：<b>{escape(default)}</b>（每个群可覆盖；留空＝恢复默认）</p>'
        f"{hint}{empty}"
        '<form method="post" action="/panel/nicknames">'
        '<table><tr><th>群号</th><th>专属昵称</th></tr>'
        + "".join(rows) +
        '<tr><td><input type="text" name="group_id" placeholder="新群号" '
        'pattern="[0-9]+"></td><td><input type="text" name="nickname" '
        'maxlength="20" placeholder="新昵称"></td></tr>'
        '</table>'
        '<p><button type="submit">保存 / 添加</button>'
        ' <a href="/panel/nicknames">刷新</a></p>'
        '</form>'
        '<p><small>昵称将注入该群 AI 提示词的【本群专属称呼】段；≤20 字，自动剥离控制字符。</small></p>'
    )
