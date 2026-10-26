"""webui_render 管理员页（Bot 群管理：管理员/禁言/踢人/名片/群名/头衔/全员禁言/退群）。

零 JavaScript：单表单 + select 选择操作，服务端渲染结果。
操作清单由 GroupAdminService.OPERATIONS 提供（单一事实来源）。
"""
from src.services.webui_render.util import _esc


def render_admin_tab(enabled: bool = True, operations=None, group_id: str = "",
                     result_html: str = "", msg: str = "", err: bool = False) -> str:
    """管理员操作页：选操作 + 填群号/成员号 → 提交执行，结果就地显示。"""
    if not enabled:
        return '<div class="msg err">群管理控制台未开启（ADMIN_CONSOLE_ENABLED=false）</div>'
    ops = operations or []
    if not ops:
        return '<div class="msg err">当前网关未提供群管理能力（Adapter 未实现）</div>'
    opts = "".join(
        '<option value="%s" data-extra="%s" data-user="%s">%s</option>'
        % (_esc(o.get("op", "")), _esc(o.get("extra", "none")),
           "1" if o.get("need_user") else "0", _esc(o.get("label", o.get("op", ""))))
        for o in ops
    )
    msg_html = ""
    if msg:
        msg_html = '<div class="msg %s">%s</div>' % ("err" if err else "ok", _esc(msg))
    form_block = (
        '<fieldset class="group"><legend>群管理操作（Bot 管理员）</legend>'
        '<form method="post" action="/panel/admin/run">'
        '<div class="row"><label class="row-info"><span class="row-title">选择操作</span>'
        '<span class="row-key">op</span></label>'
        '<div class="row-control"><select class="w-gid" name="op" required>'
        + opts +
        '</select><span class="hint">操作清单与 NapCat OneBot11 群管动作一一对应</span></div></div>'
        '<div class="row"><label class="row-info"><span class="row-title">群号</span>'
        '<span class="row-key">group_id</span></label>'
        '<div class="row-control"><input class="w-gid" type="text" name="group_id" '
        'placeholder="群号" required value="%s"></div></div>'
        '<div class="row"><label class="row-info"><span class="row-title">成员 QQ 号</span>'
        '<span class="row-key">user_id</span></label>'
        '<div class="row-control"><input class="w-gid" type="text" name="user_id" '
        'placeholder="成员 QQ 号（需要时填）"></div></div>'
        '<div class="row"><label class="row-info"><span class="row-title">额外参数</span>'
        '<span class="row-key">extra</span></label>'
        '<div class="row-control" style="flex-direction:row;gap:10px;flex-wrap:wrap">'
        '<input class="w-md" type="number" name="duration" min="0" placeholder="禁言秒数（0=解除）">'
        '<input class="w-lg" type="text" name="card" maxlength="20" placeholder="群名片（空=清除）">'
        '<input class="w-lg" type="text" name="group_name" maxlength="30" placeholder="新群名称">'
        '<input class="w-lg" type="text" name="title" maxlength="12" placeholder="头衔（空=清除）">'
        '</div><span class="hint">禁言填秒数；名片/群名/头衔按需填写；其余操作留空即可</span></div>'
        '<div class="row"><label class="row-info"><span class="row-title">附加选项</span>'
        '<span class="row-key">options</span></label>'
        '<div class="row-control" style="flex-direction:row;gap:16px;flex-wrap:wrap">'
        '<label class="hint" style="display:flex;align-items:center;gap:6px">'
        '<input type="checkbox" name="reject" value="1">踢人时拒绝再次加群</label>'
        '<label class="hint" style="display:flex;align-items:center;gap:6px">'
        '<input type="checkbox" name="dismiss" value="1">群主身份时解散群</label>'
        '</div></div>'
        '<div class="group-actions"><button type="submit" class="btn">执行操作</button></div>'
        '</form></fieldset>' % _esc(str(group_id or ""))
    )
    op_table = (
        '<fieldset class="group"><legend>操作清单</legend><div class="mcp-card-meta">'
        + "".join(
            '<div class="row"><label class="row-info"><span class="row-title">%s</span>'
            '<span class="row-key">%s</span></label><div class="row-control">'
            '<span class="hint">%s%s</span></div></div>'
            % (_esc(o.get("label", "")), _esc(o.get("op", "")), _esc(o.get("desc", "")),
               "（需要成员 QQ 号）" if o.get("need_user") else "")
            for o in ops
        )
        + "</div></fieldset>"
    )
    return msg_html + form_block + (result_html or "") + op_table
