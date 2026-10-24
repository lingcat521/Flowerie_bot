"""Web UI 群友画像域处理器（按群查看/手工修正/删除，严格隔离）。

从 WebUIServer 拆分（防上帝类）：数据源为注入的 profile_service；
所有操作按 group_id 作用域，防跨群访问。
"""
from typing import Optional
from urllib.parse import quote

from aiohttp import web

from src.services.web_ui_assets import render_profile_tab


class ProfilePanelMixin:
    """群友画像面板：查看 / 手工编辑字段 / 删除单人 / 清空本群。"""

    def _render_profile_page(self, gid: Optional[int]) -> str:
        service = getattr(self, "_profile_service", None)
        if service is None:
            return render_profile_tab(None, [], enabled=False)
        if gid is None:
            return render_profile_tab(None, [], enabled=True, groups=service.store.list_groups())
        members = service.list_group_profiles(gid)
        profile_configs = [c for c in self.config_service.list_configs()
                           if c["key"].startswith("PROFILE_")]
        return render_profile_tab(gid, members, enabled=service.enabled(),
                                  count=service.store.count_group(gid),
                                  groups=service.store.list_groups(),
                                  profile_configs=profile_configs)

    async def _handle_panel_profile_view(self, request: web.Request) -> web.Response:
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        form = await request.post()
        gid_raw = str(form.get("group_id", "") or "").strip()
        if not gid_raw.isdigit():
            return web.HTTPFound("/panel?tab=profiles&msg=" + quote("群号必须是数字") + "&err=1")
        return web.HTTPFound("/panel?tab=profiles&gid=" + gid_raw)

    async def _handle_panel_profile_save(self, request: web.Request) -> web.Response:
        """手工修正某位群友的一个画像字段（管理员手动）。"""
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        service = getattr(self, "_profile_service", None)
        if service is None:
            return web.HTTPFound("/panel?tab=profiles&msg=" + quote("群友画像未启用") + "&err=1")
        form = await request.post()
        gid_raw = str(form.get("group_id", "") or "").strip()
        uid_raw = str(form.get("user_id", "") or "").strip()
        label = str(form.get("label", "") or "").strip()
        text = str(form.get("text", "") or "")
        nickname = str(form.get("nickname", "") or "")
        if not gid_raw.isdigit() or not uid_raw.isdigit():
            return web.HTTPFound("/panel?tab=profiles&msg=" + quote("参数非法") + "&err=1")
        ok, msg = service.set_section(int(gid_raw), int(uid_raw), label, text, nickname=nickname)
        return web.HTTPFound(
            f"/panel?tab=profiles&gid={gid_raw}&msg={quote(msg)}&err={'1' if not ok else ''}")

    async def _handle_panel_profile_delete(self, request: web.Request) -> web.Response:
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        service = getattr(self, "_profile_service", None)
        if service is None:
            return web.HTTPFound("/panel?tab=profiles&msg=" + quote("群友画像未启用") + "&err=1")
        form = await request.post()
        gid_raw = str(form.get("group_id", "") or "").strip()
        uid_raw = str(form.get("user_id", "") or "").strip()
        if not gid_raw.isdigit() or not uid_raw.isdigit():
            return web.HTTPFound("/panel?tab=profiles&msg=" + quote("参数非法") + "&err=1")
        service.delete_profile(int(gid_raw), int(uid_raw))
        return web.HTTPFound("/panel?tab=profiles&gid=" + gid_raw + "&msg=" + quote("已删除该群友画像"))

    async def _handle_panel_profile_clear(self, request: web.Request) -> web.Response:
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        service = getattr(self, "_profile_service", None)
        if service is None:
            return web.HTTPFound("/panel?tab=profiles&msg=" + quote("群友画像未启用") + "&err=1")
        form = await request.post()
        gid_raw = str(form.get("group_id", "") or "").strip()
        if not gid_raw.isdigit():
            return web.HTTPFound("/panel?tab=profiles&msg=" + quote("参数非法") + "&err=1")
        removed = service.clear_group(int(gid_raw))
        return web.HTTPFound(
            f"/panel?tab=profiles&gid={gid_raw}&msg=" + quote(f"已清空本群 {removed} 位群友画像"))
