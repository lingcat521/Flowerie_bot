"""webui_render QQ空间页（发说说 / 查看历史 / 删除），零 JavaScript。

权限枚举与 QzoneService.UGC_RIGHTS 同源；历史来自本地 data/qzone_history.json。
图片输入支持 file:// / http(s):// / base64:// / 本地绝对路径，每行一个。
"""
import time

from src.services.webui_render.util import _esc


def _fmt_ts(ts) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))
    except (TypeError, ValueError):
        return ""


def _history_card(item: dict) -> str:
    tid = _esc(str(item.get("tid") or ""))
    content = _esc(str(item.get("content") or ""))
    right = int(item.get("ugc_right") or 1)
    images = int(item.get("images") or 0)
    ts = _fmt_ts(item.get("ts"))
    return (
        '<div class="row"><label class="row-info"><span class="row-title">%s</span>'
        '<span class="row-key">%s · 权限 %d · %d 图</span></label>'
        '<div class="row-control">'
        '<form method="post" action="/panel/qzone/delete" style="display:inline">'
        '<input type="hidden" name="tid" value="%s">'
        '<button type="submit" class="btn small">删除</button></form>'
        '<span class="hint">%s</span></div></div>'
        % (content or "（无正文）", ts, right, images, tid, tid)
    )


def render_qzone_tab(enabled: bool = True, rights=None, default_right: int = 1,
                     history=None, msg: str = "", err: bool = False,
                     last_tid: str = "") -> str:
    """QQ空间管理页：发布表单 + 本地历史（可删除）。"""
    if not enabled:
        return '<div class="msg err">QQ空间功能未开启（QZONE_ENABLED=false）</div>'
    msg_html = ""
    if msg:
        msg_html = '<div class="msg %s">%s</div>' % ("err" if err else "ok", _esc(msg))
    last = ""
    if last_tid:
        last = ('<div class="msg ok">上一条说说 tid：<code>%s</code></div>'
                % _esc(last_tid))
    opts = "".join(
        '<option value="%d"%s>%d %s</option>'
        % (int(r.get("value", 1)), " selected" if int(r.get("value", 1)) == int(default_right) else "",
           int(r.get("value", 1)), _esc(str(r.get("label", ""))))
        for r in (rights or [])
    )
    publish_block = (
        '<fieldset class="group"><legend>发表说说（QQ空间）</legend>'
        '<form method="post" action="/panel/qzone/publish">'
        '<div class="row"><label class="row-info"><span class="row-title">说说正文</span>'
        '<span class="row-key">content</span></label>'
        '<div class="row-control"><textarea name="content" rows="4" maxlength="2000" required '
        'placeholder="想说点什么…（最多 2000 字）"></textarea></div></div>'
        '<div class="row"><label class="row-info"><span class="row-title">图片（每行一个）</span>'
        '<span class="row-key">images</span></label>'
        '<div class="row-control"><textarea name="images" rows="3" '
        'placeholder="file:///sdcard/a.jpg&#10;https://example.com/b.png&#10;base64://..."></textarea>'
        '<span class="hint">支持 file:// 本地路径 / http(s):// 链接 / base64:// 数据；最多 9 张</span>'
        '</div></div>'
        '<div class="row"><label class="row-info"><span class="row-title">查看权限</span>'
        '<span class="row-key">ugc_right</span></label>'
        '<div class="row-control"><select class="w-md" name="ugc_right">%s</select>'
        '<span class="hint">16/128 需在下方填写权限对象 QQ 号</span></div></div>'
        '<div class="row"><label class="row-info"><span class="row-title">权限对象</span>'
        '<span class="row-key">target_uins</span></label>'
        '<div class="row-control"><input class="w-lg" type="text" name="target_uins" '
        'placeholder="QQ号，逗号分隔（权限 16/128 时必填）"></div></div>'
        '<div class="group-actions"><button type="submit" class="btn">发表说说</button></div>'
        '</form></fieldset>' % opts
    )
    items = list(history or [])
    if items:
        history_block = (
            '<fieldset class="group"><legend>本机发布历史（%d 条）</legend>%s</fieldset>'
            % (len(items), "".join(_history_card(it) for it in items))
        )
    else:
        history_block = ('<fieldset class="group"><legend>本机发布历史</legend>'
                         '<div class="msg">暂无记录（历史只记录通过本机面板发布的说说）</div></fieldset>')
    return msg_html + last + publish_block + history_block
