"""Web UI QQ空间域处理器（发说说 / 删除 / 本地历史）。

零 JavaScript：表单 POST → 服务端调用 QzoneService → 重定向回显。
数据源为 main.py 注入的 QzoneService；未注入时页面提示不可用。
"""
from urllib.parse import quote

from aiohttp import web

from src.services.web_ui_assets import render_qzone_tab


class QzonePanelMixin:
    """QQ空间面板：发布说说 + 按 tid 删除 + 本机历史。"""

    def _render_qzone_page(self, msg: str = "", err: bool = False) -> str:
        service = getattr(self, "_qzone_service", None)
        if service is None:
            return render_qzone_tab(enabled=False)
        return render_qzone_tab(enabled=service.enabled(), rights=service.rights(),
                                default_right=service.default_ugc_right(),
                                history=service.history(), msg=msg, err=err)

    @staticmethod
    def _split_lines(raw: str) -> list:
        """多行文本 → 去空行后的列表（图片/权限对象共用）。"""
        return [line.strip() for line in str(raw or "").replace(",", "\n").splitlines() if line.strip()]

    async def _handle_panel_qzone_publish(self, request: web.Request) -> web.Response:
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        service = getattr(self, "_qzone_service", None)
        if service is None:
            return web.HTTPFound("/panel?tab=qzone&msg=" + quote("QQ空间服务未接入") + "&err=1")
        form = await request.post()
        content = str(form.get("content", "") or "")
        images = self._split_lines(str(form.get("images", "") or ""))
        try:
            ugc_right = int(str(form.get("ugc_right", "1") or "1"))
        except ValueError:
            ugc_right = 1
        targets = []
        for raw in self._split_lines(str(form.get("target_uins", "") or "")):
            try:
                targets.append(int(raw))
            except ValueError:
                return web.HTTPFound("/panel?tab=qzone&msg=" + quote("权限对象里存在非法 QQ 号") + "&err=1")
        result = await service.publish(content, images, ugc_right, targets)
        if not result.get("ok"):
            return web.HTTPFound("/panel?tab=qzone&msg=" + quote(str(result.get("error") or "发表失败"))
                                 + "&err=1")
        return web.HTTPFound("/panel?tab=qzone&msg=" + quote("已发表说说 tid=" + str(result.get("tid") or "")))

    async def _handle_panel_qzone_delete(self, request: web.Request) -> web.Response:
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        service = getattr(self, "_qzone_service", None)
        if service is None:
            return web.HTTPFound("/panel?tab=qzone&msg=" + quote("QQ空间服务未接入") + "&err=1")
        form = await request.post()
        tid = str(form.get("tid", "") or "").strip()
        result = await service.delete(tid)
        if not result.get("ok"):
            return web.HTTPFound("/panel?tab=qzone&msg=" + quote(str(result.get("error") or "删除失败"))
                                 + "&err=1")
        return web.HTTPFound("/panel?tab=qzone&msg=" + quote("已删除说说 tid=" + tid))
