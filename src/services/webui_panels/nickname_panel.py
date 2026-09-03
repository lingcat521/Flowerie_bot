"""Web UI 群特色昵称面板（GET 展示 / POST 保存，零 JS 重渲染）。"""
from html import escape as _e

from aiohttp import web

from src.services.group_nicknames import GroupNicknameStore
from src.services.webui_render.nicknames import render_nicknames_tab


def apply_nicknames_form(store, form) -> int:
    """解析表单（修改 nick_<gid>__<pid> + 新增 group_id/persona_id/nickname），返回操作数。

    键格式：无 persona → nick_<gid>；有 persona → nick_<gid>__<pid>（persona_id 可含非法字符，
    用 __ 双下划线分隔；pid 原样传递）。
    """
    saved = 0
    for key in form:
        if key.startswith("nick_"):
            rest = key[5:]
            gid_s, sep, pid = rest.partition("__")
            if gid_s.isdigit() and int(gid_s) > 0:
                store.set(int(gid_s), pid if sep else None, str(form.get(key) or ""))
                saved += 1
    gid = str((form.get("group_id") or "")).strip()
    if gid.isdigit() and int(gid) > 0:
        pid = str(form.get("persona_id") or "").strip()
        store.set(int(gid), pid or None, str(form.get("nickname") or ""))
        saved += 1
    return saved


class NicknamePanelMixin:

    @property
    def _nickname_store(self) -> GroupNicknameStore:
        return getattr(self, "group_nicknames", None)

    @property
    def _style_rule_store(self):
        return getattr(self, "group_style_rules", None)

    async def _handle_panel_nicknames(self, request: web.Request) -> web.Response:
        return web.Response(text=self._render_nicknames_page(),
                            content_type="text/html", charset="utf-8")

    def _render_nicknames_page(self, msg: str = "") -> str:
        store = self._nickname_store
        nicknames = store.all() if store else {}
        default = store.default if store else getattr(self.config, "BOT_NICKNAME", "花璃")
        # 群聊列表（选择器）：status_provider 提供 group_ids（已进过消息的群）
        group_ids = []
        try:
            status = getattr(self, "_status_provider", None)
            if callable(status):
                group_ids = (status() or {}).get("group_ids") or []
        except Exception:  # noqa: BLE001
            group_ids = []
        # 人设列表（隔离维度）：persona_manager 提供
        personas = []
        try:
            pm = self._persona_manager
            if pm is not None:
                personas = [(str(p.get("id") or ""), str(p.get("name") or p.get("id") or ""))
                            for p in (pm.list_personas() or [])]
        except Exception:  # noqa: BLE001
            personas = []
        rules_html = ""
        sr = self._style_rule_store
        if sr is not None:
            rules = sr.all()
            rule_rows = "".join(
                f'<tr><td>{_e(gid)}</td><td><textarea name="rule_{gid}" rows="3">'
                f'{_e(r)}</textarea></td></tr>'
                for gid, r in sorted(rules.items(), key=lambda kv: int(kv[0])))
            rules_html = (
                '<fieldset class="group"><legend>群专属发言规则（覆盖全局 GLOBAL_STYLE_RULES）</legend>'
                '<form method="post" action="/panel/grouprules">'
                '<table><tr><th>群号</th><th>规则（多行；留空＝回退全局）</th></tr>'
                + rule_rows +
                '</table>'
                '<p>新增/修改：<input list="gidlist" name="group_id" placeholder="群号" pattern="[0-9]+">'
                '<textarea name="rules" rows="4" placeholder="该群专属发言规则"></textarea>'
                '<button type="submit">保存</button></p>'
                '</form></fieldset>'
            )
        return render_nicknames_tab(nicknames, default, msg, group_ids=list(group_ids),
                                    personas=personas) + rules_html

    async def _handle_panel_grouprules_save(self, request: web.Request) -> web.Response:
        form = await request.post()
        sr = self._style_rule_store
        if sr is None:
            return web.Response(text=self._render_nicknames_page(msg="未初始化（重启后重试）"),
                                content_type="text/html", charset="utf-8")
        saved = 0
        for key in form:
            if key.startswith("rule_") and key[5:].isdigit():
                sr.set(int(key[5:]), str(form.get(key) or ""))
                saved += 1
        gid = str((form.get("group_id") or "")).strip()
        if gid.isdigit() and int(gid) > 0:
            sr.set(int(gid), str(form.get("rules") or ""))
            saved += 1
        msg = f"已保存 {saved} 个群的发言规则" if saved else "无变更"
        return web.Response(text=self._render_nicknames_page(msg=msg),
                            content_type="text/html", charset="utf-8")

    async def _handle_panel_nicknames_save(self, request: web.Request) -> web.Response:
        form = await request.post()
        store = self._nickname_store
        if store is None:
            return web.Response(text=self._render_nicknames_page(msg="未初始化（重启后重试）"),
                                content_type="text/html", charset="utf-8")
        saved = apply_nicknames_form(store, form)
        msg = f"已保存 {saved} 个群的昵称" if saved else "无变更"
        return web.Response(text=self._render_nicknames_page(msg=msg),
                            content_type="text/html", charset="utf-8")
