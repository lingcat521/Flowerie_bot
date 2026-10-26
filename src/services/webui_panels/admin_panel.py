"""Web UI 群管理员域处理器（Bot 群管理：管理员/禁言/踢人/名片/群名/头衔/全员禁言/退群）。

零 JavaScript：单表单提交，服务端执行并回显结果。
数据源为 main.py 注入的 GroupAdminService；未注入时页面提示不可用。
"""
from urllib.parse import quote

from aiohttp import web

from src.services.web_ui_assets import render_admin_tab


class AdminPanelMixin:
    """Admin 面板：渲染操作页 + 执行单个群管操作。"""

    def _render_admin_page(self, msg: str = "", err: bool = False) -> str:
        service = getattr(self, "_admin_service", None)
        if service is None:
            return render_admin_tab(enabled=False, operations=[])
        return render_admin_tab(enabled=service.enabled(), operations=service.operations(),
                                msg=msg, err=err)

    @staticmethod
    def _admin_kwargs(form) -> dict:
        """把表单归一化成 GroupAdminService.execute 的参数（全部是字符串输入）。"""
        def _int(name: str, default: int = 0) -> int:
            raw = str(form.get(name, "") or "").strip()
            try:
                return int(raw) if raw else default
            except ValueError:
                return default

        def _str(name: str) -> str:
            return str(form.get(name, "") or "")

        def _flag(name: str) -> bool:
            return str(form.get(name, "") or "").strip() in ("1", "true", "on", "yes")

        return {
            "group_id": _int("group_id"),
            "user_id": _int("user_id"),
            "duration": _int("duration", 0),
            "card": _str("card").strip(),
            "group_name": _str("group_name").strip(),
            "title": _str("title").strip(),
            "reject": _flag("reject"),
            "dismiss": _flag("dismiss"),
        }

    async def _handle_panel_admin_run(self, request: web.Request) -> web.Response:
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        service = getattr(self, "_admin_service", None)
        if service is None:
            return web.HTTPFound("/panel?tab=admin&msg=" + quote("群管理服务未接入") + "&err=1")
        form = await request.post()
        op = str(form.get("op", "") or "").strip()
        kwargs = self._admin_kwargs(form)
        result = await service.execute(op, **kwargs)
        if not result.get("ok"):
            return web.HTTPFound("/panel?tab=admin&msg=" + quote(str(result.get("error") or "操作失败"))
                                 + "&err=1")
        payload = result.get("result")
        detail = ""
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, list) and data:
                detail = "，%d 人" % len(data)
            elif isinstance(data, dict) and data.get("data"):
                inner = data["data"]
                if isinstance(inner, list):
                    detail = "，%d 人" % len(inner)
        return web.HTTPFound("/panel?tab=admin&msg=" + quote("操作成功" + detail))
