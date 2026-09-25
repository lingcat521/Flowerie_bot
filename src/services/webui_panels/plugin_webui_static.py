"""插件 WebUI 静态资源处理器（任务书第 1 份 §12）。

单独成 mixin 的原因：任务书要求"不要把逻辑全部堆到 PluginPanelMixin"，
而且静态资源与页面/上传是三条不同的安全通道。

边界：
- 只服务**该插件自己**的 webui/static（路径校验/符号链接检查在 plugins/webui_loader，单一实现）
- 需要与页面相同的 `web_ui` 权限（未批准一律 404，不泄露插件是否存在）
- 扩展名白名单里**没有 .js** —— 主 WebUI 与插件 WebUI 都是 No-JS 架构（审计 §2）
- `.css` 额外过 `sanitize_plugin_css`（禁 @import / 外链 url / expression 等）
- 响应头：nosniff + no-store（插件状态类资源不适合缓存）
"""
import re

from aiohttp import web

from src.plugins.webui_loader import PluginWebuiPathError

_PID_RE = re.compile(r"[a-z][a-z0-9_-]{0,31}")


class PluginWebUIStaticMixin:
    """GET /panel/plugins/webui/{pid}/static/{path}"""

    async def _handle_panel_plugin_webui_static(self, request: web.Request) -> web.Response:
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        pid = str(request.match_info.get("pid", ""))[:64]
        rel = str(request.match_info.get("path", ""))[:200]
        if not _PID_RE.fullmatch(pid):
            return web.Response(status=404, text="not found")
        if self._plugin_manager is None:
            return web.Response(status=404, text="not found")
        row = self._plugin_manager.get_plugin(pid) or {}
        approved = set(row.get("approved_permissions") or [])
        if not row.get("enabled") or "web_ui" not in approved:
            return web.Response(status=404, text="not found")   # 不泄露存在性
        try:
            blob, mime = self._plugin_manager.plugin_webui_static_file(pid, rel)
        except PluginWebuiPathError:
            return web.Response(status=404, text="not found")
        except OSError:
            return web.Response(status=404, text="not found")
        # CSS 净化收口在 PluginManager.plugin_webui_static_file（单一实现，此处不重复）
        return web.Response(body=blob, content_type=mime.split(";")[0], charset="utf-8",
                            headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
