"""Web UI 私聊域处理器（v2.14.0）：允许名单 / 每人记忆清空 / 状态页。

零 JavaScript：表单 POST → 服务端改配置或清记忆 → 重定向回显。
数据源为 main.py 注入的 config_service + memory_manager；未注入时提示不可用。
"""
from urllib.parse import quote

from aiohttp import web

from src.services.web_ui_assets import render_private_tab


class PrivateChatPanelMixin:
    """私聊面板：状态 + 允许名单 + 每人记忆清空。"""

    def _private_users(self):
        """列出有私聊记忆的用户（虚拟 key 为负数；-gid 就是 QQ）。"""
        memory = getattr(self, "_memory_manager", None)
        if memory is None:
            return []
        users = []
        try:
            for uid, gid in memory.iter_user_groups():
                if int(gid) >= 0:
                    continue
                notes = memory.get_user_notes(int(uid), int(gid)) or []
                if notes:
                    users.append({"qq": int(uid), "notes": len(notes)})
        except Exception:  # noqa: BLE001 —— 统计失败不影响页面
            return []
        users.sort(key=lambda x: -x["notes"])
        return users[:200]

    def _render_private_page(self, msg: str = "", err: bool = False) -> str:
        cfg = self.config
        return render_private_tab(
            enabled=bool(getattr(cfg, "PRIVATE_CHAT_ENABLED", False)),
            allowed=[int(x) for x in (getattr(cfg, "PRIVATE_CHAT_ALLOWED_QQS", None) or [])],
            admins=[int(x) for x in (getattr(cfg, "ADMIN_QQ_IDS", None) or [])],
            cooldown=int(getattr(cfg, "PRIVATE_CHAT_COOLDOWN_SECONDS", 3) or 0),
            context_size=int(getattr(cfg, "PRIVATE_CHAT_CONTEXT_SIZE", 40) or 40),
            memory_enabled=bool(getattr(cfg, "PRIVATE_CHAT_MEMORY_ENABLED", True)),
            users=self._private_users(), msg=msg, err=err,
        )

    async def _handle_panel_private_allowlist(self, request: web.Request) -> web.Response:
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        form = await request.post()
        raw = str(form.get("qqs", "") or "").replace("，", ",").replace("\n", ",")
        qqs = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            if not part.isdigit() or int(part) <= 0:
                return web.HTTPFound("/panel?tab=private&msg=" + quote("允许名单里有非法 QQ 号") + "&err=1")
            qqs.append(str(int(part)))
        value = ",".join(qqs)
        ok, err = self.config_service.update("PRIVATE_CHAT_ALLOWED_QQS", value)
        if not ok:
            return web.HTTPFound("/panel?tab=private&msg=" + quote("保存失败：" + str(err)) + "&err=1")
        return web.HTTPFound("/panel?tab=private&msg=" + quote("允许名单已更新（%d 个 QQ）" % len(qqs)))

    async def _handle_panel_private_clear(self, request: web.Request) -> web.Response:
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        form = await request.post()
        try:
            qq = int(str(form.get("qq", "") or "0"))
        except (TypeError, ValueError):
            qq = 0
        memory = getattr(self, "_memory_manager", None)
        if qq <= 0 or memory is None:
            return web.HTTPFound("/panel?tab=private&msg=" + quote("参数不合法或记忆服务未接入") + "&err=1")
        removed = await memory.clear_user_memory(qq, -qq)
        return web.HTTPFound("/panel?tab=private&msg=" + quote("已清空 %d 的记忆（%d 条）" % (qq, removed)))
