"""Web UI 群特色昵称面板（GET 展示 / POST 保存，零 JS 重渲染）。"""
from aiohttp import web

from src.services.group_nicknames import GroupNicknameStore
from src.services.webui_render.nicknames import render_nicknames_tab


def apply_nicknames_form(store, form) -> int:
    """解析表单（修改 nick_<gid> + 新增 group_id/nickname），返回操作数。"""
    saved = 0
    for key in form:
        if key.startswith("nick_") and key[5:].isdigit():
            store.set(int(key[5:]), str(form.get(key) or ""))
            saved += 1
    gid = str((form.get("group_id") or "")).strip()
    if gid.isdigit() and int(gid) > 0:
        store.set(int(gid), str(form.get("nickname") or ""))
        saved += 1
    return saved


class NicknamePanelMixin:

    @property
    def _nickname_store(self) -> GroupNicknameStore:
        return getattr(self, "group_nicknames", None)

    async def _handle_panel_nicknames(self, request: web.Request) -> web.Response:
        return web.Response(text=self._render_nicknames_page(),
                            content_type="text/html", charset="utf-8")

    def _render_nicknames_page(self, msg: str = "") -> str:
        store = self._nickname_store
        nicknames = store.all() if store else {}
        default = store.default if store else getattr(self.config, "BOT_NICKNAME", "花璃")
        return render_nicknames_tab(nicknames, default, msg)

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
