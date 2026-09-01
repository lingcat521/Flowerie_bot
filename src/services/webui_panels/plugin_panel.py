"""Web UI 插件域处理器（Plugin Panel）。

从 WebUIServer 拆分（防上帝类）：数据源为注入的 plugin_manager。
全部处理器先过 _check_token（管理员认证）；未认证一律重定向回 /panel。
"""
import re
from urllib.parse import quote

from aiohttp import web

from src.services.web_ui_assets import render_plugin_tab
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)

_MAX_UPLOAD_READ = 6 * 1024 * 1024  # 上传读取兜底上限（安装器内另有 ZIP 大小校验）


class PluginPanelMixin:

    def _render_plugin_page(self) -> str:
        if self._plugin_manager is None:
            return render_plugin_tab([], protection="normal", plugin_configs=[])
        try:
            plugins = self._plugin_manager.list_plugins()
        except Exception as e:  # noqa: BLE001 - 页面不因插件系统异常崩溃
            logger.error("plugin_page_list_failed reason=%s", e)
            plugins = []
        protection = self._plugin_manager._protection_level() if hasattr(
            self._plugin_manager, "_protection_level") else "normal"
        plugin_configs = [c for c in self.config_service.list_configs()
                          if c["key"].startswith("PLUGIN_")]
        webui_links = []
        try:
            for prow in self._plugin_manager.list_plugins():
                if not prow.get("enabled"):
                    continue
                if "web_ui" not in (prow.get("approved_permissions") or []):
                    continue
                try:
                    pm = self._plugin_manager._manifest_of(prow)
                except Exception:  # noqa: BLE001
                    pm = None
                if pm and pm.web_ui and pm.web_ui.get("pages"):
                    first = pm.web_ui["pages"][0]["id"]
                    webui_links.append(
                        (prow.get("name") or prow["id"],
                         f"/panel/plugins/webui/{prow['id']}/{first}"))
        except Exception:  # noqa: BLE001
            webui_links = []
        return render_plugin_tab(plugins, protection=protection,
                                 plugin_configs=plugin_configs, protection_warning=protection == "unsafe",
                                 webui_links=webui_links)

    async def _handle_panel_plugin_webui(self, request: web.Request) -> web.Response:
        """Plugin WebUI 页面：GET=渲染（params 从 query），POST=form 提交（动态重渲染）。

        零 JS：所有交互都是表单 POST/GET → 插件（webui_page hook）→ DSL → 重渲染。
        """
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        pid = str(request.match_info.get("pid", ""))[:64]
        page = str(request.match_info.get("page", ""))[:64]
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", pid) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", page):
            return web.HTTPFound("/panel?tab=plugins&err=1&msg=" + quote("非法页面参数"))
        if self._plugin_manager is None:
            return web.HTTPFound("/panel?tab=plugins&err=1&msg="
                                 + quote("插件系统未启用（未注入 PluginManager）"))
        if request.method == "POST":
            form = await request.post()
            action = str(form.get("plugin_action", "") or "")[:64] or "submit"
            values = {str(k): str(v) for k, v in form.items() if not str(k).startswith("plugin_")}
        else:
            action, values = "get", {}
        params = {str(k): str(v) for k, v in request.query.items()}
        result, err = await self._plugin_manager.plugin_webui_page(pid, page, action, params, values)
        plugin_row = self._plugin_manager.get_plugin(pid) or {}
        pname = str(plugin_row.get("name") or pid)
        page_meta = result.get("page", {"title": page, "description": ""}) if isinstance(result, dict) else {}
        dsl_html = ""
        if err:
            dsl_html = ""
        elif isinstance(result, dict):
            from src.services.webui_render.plugin_dsl import render_plugin_dsl
            dsl_html = render_plugin_dsl(result.get("dsl"))
        tabs = []
        try:
            manifest = self._plugin_manager._manifest_of(plugin_row)
            if manifest and manifest.web_ui:
                tabs = [{"id": p["id"], "title": p["title"], "active": p["id"] == page}
                        for p in manifest.web_ui["pages"]]
        except Exception:  # noqa: BLE001
            tabs = []
        from src.services.webui_render.plugin_webui import render_plugin_webui_page
        html = render_plugin_webui_page(
            pname, str(page_meta.get("title") or page),
            str(page_meta.get("description") or ""), dsl_html,
            error=err, plugin_id=pid, plugin_tabs=tabs)
        return web.Response(text=html, content_type="text/html", charset="utf-8")

    async def _handle_panel_plugins_refresh(self, request: web.Request) -> web.Response:
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        if self._plugin_manager is None:
            return web.HTTPFound("/panel?tab=plugins&err=1&msg="
                                 + quote("插件系统未启用（未注入 PluginManager）"))
        discovered, changed = self._plugin_manager.refresh()
        msg = f"扫描完成：新发现 {len(discovered)} 个插件，更新 {len(changed)} 个" \
              if (discovered or changed) else "扫描完成：无变化（新插件默认禁用，需手动启用）"
        return web.HTTPFound(f"/panel?tab=plugins&msg={quote(msg)}")

    async def _handle_panel_plugins_upload(self, request: web.Request) -> web.Response:
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        if self._plugin_manager is None:
            return web.HTTPFound("/panel?tab=plugins&err=1&msg=" + quote("插件系统未启用"))
        form = await request.post()
        upload = form.get("plugin_file")
        if upload is None or not getattr(upload, "file", None):
            return web.HTTPFound("/panel?tab=plugins&err=1&msg=" + quote("未选择文件"))
        filename = str(getattr(upload, "filename", "") or "upload.zip")
        data = upload.file.read(_MAX_UPLOAD_READ + 1)
        if len(data) > _MAX_UPLOAD_READ:
            return web.HTTPFound("/panel?tab=plugins&err=1&msg="
                                 + quote(f"文件超过大小上限（{_MAX_UPLOAD_READ} 字节）"))
        ok, message = self._plugin_manager.install_upload(data, filename=filename)
        return web.HTTPFound(f"/panel?tab=plugins&msg={quote(message)}&err={'1' if not ok else ''}")

    async def _handle_panel_plugins_install_url(self, request: web.Request) -> web.Response:
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        if self._plugin_manager is None:
            return web.HTTPFound("/panel?tab=plugins&err=1&msg=" + quote("插件系统未启用"))
        form = await request.post()
        url = str(form.get("url", ""))
        if not url:
            return web.HTTPFound("/panel?tab=plugins&err=1&msg=" + quote("URL 为空"))
        ok, message = await self._plugin_manager.install_url_async(url)
        return web.HTTPFound(f"/panel?tab=plugins&msg={quote(message)}&err={'1' if not ok else ''}")

    async def _handle_panel_plugins_enable(self, request: web.Request) -> web.Response:
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        if self._plugin_manager is None:
            return web.HTTPFound("/panel?tab=plugins&err=1&msg=" + quote("插件系统未启用"))
        form = await request.post()
        plugin_id = str(form.get("id", ""))
        # MultiDict（真 aiohttp）用 getall；简易 dict（测试桩）兼容取单值/列表
        if hasattr(form, "getall"):
            perms = [str(p) for p in form.getall("perm")]
        else:
            raw = form.get("perm")
            perms = [str(p) for p in (raw if isinstance(raw, (list, tuple)) else [raw]) if p]
        ok, message = await self._plugin_manager.enable(plugin_id, approved_permissions=perms)
        return web.HTTPFound(f"/panel?tab=plugins&msg={quote(message)}&err={'1' if not ok else ''}")

    async def _handle_panel_plugins_disable(self, request: web.Request) -> web.Response:
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        if self._plugin_manager is None:
            return web.HTTPFound("/panel?tab=plugins&err=1&msg=" + quote("插件系统未启用"))
        form = await request.post()
        ok, message = self._plugin_manager.disable(str(form.get("id", "")))
        return web.HTTPFound(f"/panel?tab=plugins&msg={quote(message)}&err={'1' if not ok else ''}")

    async def _handle_panel_plugins_uninstall(self, request: web.Request) -> web.Response:
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        if self._plugin_manager is None:
            return web.HTTPFound("/panel?tab=plugins&err=1&msg=" + quote("插件系统未启用"))
        form = await request.post()
        ok, message = self._plugin_manager.uninstall(str(form.get("id", "")))
        return web.HTTPFound(f"/panel?tab=plugins&msg={quote(message)}&err={'1' if not ok else ''}")

    async def _handle_panel_plugins_protection(self, request: web.Request) -> web.Response:
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        form = await request.post()
        level = str(form.get("protection", "")).lower()
        # 双写：ConfigService（.env + settings.db + 热更新）→ Manager 运行态
        ok, message = self.config_service.update("PLUGIN_PROTECTION", level)
        if ok and self._plugin_manager is not None:
            _ok2, msg2 = self._plugin_manager.set_protection(level)
            message = (message + "；" + msg2) if _ok2 else (msg2 or message)
        return web.HTTPFound(f"/panel?tab=plugins&msg={quote(message)}&err={'1' if not ok else ''}")

    async def _handle_panel_plugins_config(self, request: web.Request) -> web.Response:
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        form = await request.post()
        updates = {k: str(v) for k, v in form.items()
                   if k in ("PLUGIN_MAX_COUNT", "PLUGIN_URL_MAX_BYTES", "PLUGIN_URL_TIMEOUT",
                            "PLUGIN_ZIP_MAX_UNZIPPED_BYTES", "PLUGIN_ZIP_MAX_FILES")}
        ok, message = self.config_service.update_many(updates)
        return web.HTTPFound(f"/panel?tab=plugins&msg={quote(message)}&err={'1' if not ok else ''}")
