"""Web UI 群特色昵称面板（GET 展示 / POST 保存，零 JS 重渲染）。"""

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
        return render_nicknames_tab(nicknames, default, msg, group_ids=list(group_ids),
                                    personas=personas)

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
