"""插件 WebUI 宿主（Phase 1 / M2：从 PluginManager 拆出的 WebUI 职责域）。

M2a（本次）先搬「文件空间」三件事：
- 拥有：插件 WebUI 专属目录推导、上传保存、下载读取（名称/扩展名/大小/魔数/穿越防护）
- 注入：只有一个 `plugin_root` 回调（manager 传 `self._plugin_dir`）
- 不拥有：权限判定（`web_ui.files` 由调用方 gate）、页面渲染、静态资源（后续步骤搬入）

行为与拆分前**逐字一致**（错误文案、校验顺序、上限都不变）。
"""
import asyncio
import base64
import os
import re
from typing import Any, Callable, Dict, Optional, Tuple

from src.plugins.webui_loader import (PluginWebuiPathError, STATIC_EXTS, read_page,
                                    read_static, static_root, validate_relative)

#: 允许的上传扩展名（与拆分前 PluginManager._WEBUI_ALLOWED_EXT 相同）
WEBUI_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".txt", ".json",
                     ".md", ".log", ".csv"}
#: 上传大小上限（10MB）
WEBUI_MAX_UPLOAD = 10 * 1024 * 1024
#: 文件名规则：字母数字开头，≤64，允许 . _ -
WEBUI_ALLOWED_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

#: 图片类扩展名的魔数（上传时必须命中）
_IMAGE_SIGS = {".png": b"\x89PNG", ".jpg": b"\xff\xd8", ".jpeg": b"\xff\xd8",
               ".gif": (b"GIF87a", b"GIF89a"), ".webp": b"RIFF"}


class PluginWebUIHost:
    """插件 WebUI 的文件空间（只碰该插件自己的 webui/ 目录）。"""

    def __init__(self, plugin_root: Callable[[], str], plugin_of: Callable[[str], Optional[dict]],
                 manifest_of: Callable[[dict], Any], runtime_of: Callable[[str], Any],
                 hook_call: Callable[..., Any]):
        self._plugin_root = plugin_root
        self._plugin_of = plugin_of
        self._manifest_of_cb = manifest_of
        self._runtime_of = runtime_of
        self._hook_call = hook_call

    def plugin_webui_dir(self, plugin_id: str) -> str:
        """插件 WebUI 专属空间（不影响插件常规文件系统路径）。"""
        base = os.path.abspath(self._plugin_root())
        d = os.path.join(base, plugin_id, "webui")
        # 防穿越：必须位于插件目录内
        if not os.path.abspath(d).startswith(base + os.sep):
            raise ValueError("非法插件目录")
        os.makedirs(d, exist_ok=True)
        return d

    def webui_save_upload(self, plugin_id: str, filename: str, data: bytes):
        """带权限/扩展名/名称/大小/魔数校验的保存（web_ui.files 由调用方 gate）。"""
        raw_name = str(filename or "")
        if "/" in raw_name or "\\" in raw_name:
            raise ValueError("文件名含路径分隔符（拒绝）")
        name = os.path.basename(raw_name)
        if not WEBUI_ALLOWED_NAME.fullmatch(name):
            raise ValueError("文件名非法（仅字母/数字/下划线/点/短横线，≤64）")
        ext = os.path.splitext(name)[1].lower()
        if ext not in WEBUI_ALLOWED_EXT:
            raise ValueError(f"不支持的扩展名（允许: {', '.join(sorted(WEBUI_ALLOWED_EXT))}）")
        if len(data) > WEBUI_MAX_UPLOAD:
            raise ValueError("文件超过 10MB 上限")
        # 魔数核验（图片类必须命中；文本类不校验内容）
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            sig = _IMAGE_SIGS[ext]
            ok = data[:8].startswith(sig) if isinstance(sig, bytes) else data[:6] in sig
            if not ok:
                raise ValueError("文件内容与扩展名不匹配（魔数校验失败）")
        # 固定名前缀：防覆盖/路径穿越（保存为 <safe 名>）
        root = self.plugin_webui_dir(plugin_id)
        target = os.path.join(root, name)
        if os.path.exists(target):
            raise ValueError("同名文件已存在（请换一个文件名）")
        with open(target, "wb") as f:
            f.write(data)
        return name, len(data)

    def webui_read_file(self, plugin_id: str, name: str,
                        max_bytes: int = 50 * 1024 * 1024) -> Tuple[bytes, str, str]:
        """带穿越防护的读取（下载）；返回 (bytes, safe_name, ext)。"""
        if not WEBUI_ALLOWED_NAME.fullmatch(name or ""):
            raise ValueError("文件名非法")
        root = self.plugin_webui_dir(plugin_id)
        target = os.path.abspath(os.path.join(root, name))
        if not target.startswith(os.path.abspath(root) + os.sep):
            raise ValueError("路径穿越拒绝")
        if not os.path.isfile(target):
            raise ValueError("文件不存在")
        if os.path.getsize(target) > max_bytes:
            raise ValueError("文件超过下载上限")
        with open(target, "rb") as f:
            return f.read(), name, os.path.splitext(name)[1].lower()
    #: 插件资源 MIME 白名单（No-JS：没有 javascript，也没有可执行 SVG / text/html）
    WEBUI_ASSET_MIME = {
        ".css": "text/css; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".csv": "text/csv; charset=utf-8",
        ".md": "text/plain; charset=utf-8",
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".ico": "image/x-icon",
    }
    #: 插件资源大小上限（比静态文件更严：内容是插件临时生成的）
    WEBUI_ASSET_MAX_BYTES = 256 * 1024

    @staticmethod
    def _webui_supports(rt, method: str) -> bool:
        """插件是否声明了某 WebUI 能力（未声明的运行时/测试桩一律不调用）。"""
        supports = getattr(rt, "supports", None)
        return bool(callable(supports) and supports(method))

    def _webui_approved(self, plugin_id: str) -> set:
        """该插件已批准的权限集合（唯一入口：WebUI 各处都从这里取，避免口径不一）。"""
        row = self._plugin_of(plugin_id) or {}
        return {str(p) for p in (row.get("approved_permissions") or []) if p}

    @staticmethod
    def _webui_granted(approved, permission: str) -> bool:
        from src.plugins.permissions import webui_permission_granted
        return webui_permission_granted(approved, permission)

    async def _webui_call(self, plugin_id: str, method: str, params: Dict[str, Any],
                          timeout: float = 4.0):
        """调插件的 WebUI 协议方法（真子进程 + 真管道）。返回 (payload, error)。"""
        rt = self._runtime_of(plugin_id)
        if rt is None:
            return None, "插件运行中未加载（重启后重试）"
        if not self._webui_supports(rt, method):
            return None, "插件未声明能力 %s" % method
        try:
            payload = await asyncio.wait_for(rt.request(method, params), timeout=timeout)
        except asyncio.TimeoutError:
            return None, "插件响应超时（%ss 上限）" % timeout
        except Exception as e:  # noqa: BLE001
            return None, "插件调用失败: %s: %s" % (type(e).__name__, e)
        if not isinstance(payload, dict):
            return None, "插件返回了非法响应（应为对象）"
        if payload.get("ok") is False:
            return None, str(payload.get("error") or "插件返回 ok=false")
        return payload, ""

    def plugin_webui_static_root(self, plugin_id: str) -> str:
        """该插件的静态资源根目录（manifest `web_ui.static`，默认 "static"）。"""
        row = self._plugin_of(plugin_id)
        declared = None
        if row is not None:
            manifest = self._manifest_of_cb(row)
            if manifest and manifest.web_ui:
                declared = manifest.web_ui.get("static")
        return static_root(self.plugin_webui_dir(plugin_id), declared)

    def plugin_webui_static_file(self, plugin_id: str, rel_path: str):
        """读取插件静态资源：返回 (bytes, mime)；越界/非法一律抛 PluginWebuiPathError。

        `.css` 在这里就过 `sanitize_plugin_css`（**单一收口**）：任何调用方拿到的都是净化后的
        样式，不依赖上层 HTTP 处理器再补一次。
        """
        root = self.plugin_webui_static_root(plugin_id)
        blob, mime, _path = read_static(root, rel_path)
        if mime.startswith("text/css"):
            from src.plugins.webui_security import sanitize_plugin_css

            css, _report = sanitize_plugin_css(blob.decode("utf-8", errors="replace"))
            blob = css.encode("utf-8")
        return blob, mime

    async def plugin_webui_asset(self, plugin_id: str, rel_path: str) -> Tuple[bytes, str]:
        """插件提供的 WebUI 资源（`webui.asset`）：返回 (bytes, mime)。

        越界 / 未批准 / 未声明能力 / MIME 不在白名单 / 超限一律抛 PluginWebuiPathError
        （HTTP 层统一转 404，不泄露插件是否存在）。No-JS 政策落在三处：
        路径扩展名白名单没有 .js；MIME 白名单没有 javascript / text/html / svg；
        `.css` 过 sanitize_plugin_css（与静态文件同一收口）。
        """
        from src.plugins.webui_loader import STATIC_EXTS, validate_relative

        rel = validate_relative(rel_path, STATIC_EXTS, field="插件资源")
        row = self._plugin_of(plugin_id)
        if row is None or not row.get("enabled"):
            raise PluginWebuiPathError("插件未启用或不存在")
        approved = self._webui_approved(plugin_id)
        if not self._webui_granted(approved, "webui.view"):
            raise PluginWebuiPathError("插件未批准 webui.view 权限")
        rt = self._runtime_of(plugin_id)
        if not self._webui_supports(rt, "webui.asset"):
            raise PluginWebuiPathError("插件未声明 webui.asset 能力")
        payload, err = await self._webui_call(plugin_id, "webui.asset", {"path": rel})
        if err:
            raise PluginWebuiPathError(err)
        ext = os.path.splitext(rel)[1].lower()
        expect = self.WEBUI_ASSET_MIME.get(ext)
        if not expect:
            raise PluginWebuiPathError("插件资源类型不允许：%s" % (ext or "(无)"))
        declared = str(payload.get("content_type") or "").split(";")[0].strip().lower()
        if declared and declared != expect.split(";")[0].strip().lower():
            raise PluginWebuiPathError("content_type 与扩展名不符：%s" % declared)
        if expect.startswith("text/"):
            body = payload.get("body")
            if not isinstance(body, str):
                raise PluginWebuiPathError("文本资源需要 body 字符串字段")
            blob = body.encode("utf-8")
        else:
            encoded = payload.get("base64")
            if not isinstance(encoded, str):
                raise PluginWebuiPathError("二进制资源需要 base64 字段")
            try:
                blob = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError):
                raise PluginWebuiPathError("base64 解码失败") from None
        if len(blob) > self.WEBUI_ASSET_MAX_BYTES:
            raise PluginWebuiPathError("插件资源超过大小上限")
        if expect.startswith("text/css"):
            from src.plugins.webui_security import sanitize_plugin_css
            css, _report = sanitize_plugin_css(blob.decode("utf-8", errors="replace"))
            blob = css.encode("utf-8")
        return blob, expect

    #: 传给 WebUI 页面的上下文里**永远**只有这些顶层键（新增键必须同步进安全测试）
    WEBUI_CONTEXT_KEYS = ("plugin", "page", "request", "user", "config", "data")

    async def plugin_webui_page(self, plugin_id: str, page_id: str, action: str = "get",
                                params: Optional[dict] = None, values: Optional[dict] = None):
        """插件 WebUI 页面渲染/提交的统一入口。

        权限：插件须启用且管理员批准过 web_ui（web_ui.files 控制文件能力——本方法不含文件）。
        返回 (dsl, error_str)：dsl 可直接交给 render_plugin_dsl；error 非空时渲染错误页。
        任何异常都降级为错误页，绝不把异常/原始 HTML 交给浏览器。
        """
        row = self._plugin_of(plugin_id)
        if row is None or not row.get("enabled"):
            return None, "插件未启用或不存在"
        approved = set(row.get("approved_permissions") or [])
        if not self._webui_granted(approved, "webui.view"):
            return None, "插件未批准 webui.view 权限（旧权限名 web_ui；管理员批准后才能访问）"
        try:
            manifest = self._manifest_of_cb(row)
        except Exception:  # noqa: BLE001
            return None, "插件 manifest 不可解析"
        if not manifest or not manifest.web_ui:
            return None, "插件未声明 web_ui"
        page = next((p for p in manifest.web_ui["pages"] if p["id"] == page_id), None)
        if page is None:
            return None, f"页面不存在: {page_id}"
        rt = self._runtime_of(plugin_id)
        if rt is None:
            return None, "插件运行中未加载（重启后重试）"
        hook_name = str(manifest.web_ui.get("entry") or "webui_page")
        try:
            import asyncio
            result = await asyncio.wait_for(
                self._hook_call(rt, hook_name, page_id, action,
                                        dict(params or {}), dict(values or {})),
                timeout=4.0)
        except asyncio.TimeoutError:
            return None, "插件响应超时（4s 上限）"
        except Exception as e:  # noqa: BLE001
            return None, f"插件调用失败: {type(e).__name__}: {e}"
        if isinstance(result, dict) and result.get("__error__"):
            return None, str(result["__error__"])
        if result is None:
            return None, "插件未返回页面内容"
        if not isinstance(result, dict):
            return None, "插件返回了非法响应（必须是 DSL 对象）"
        # 附加页面元数据（供 shell 展示）
        return {"dsl": result, "page": page}, ""

    async def plugin_webui_render(self, plugin_id: str, page_id: str, action: str = "get",
                                  params: Optional[dict] = None, values: Optional[dict] = None):
        """Plugin WebUI 渲染入口：返回 (result, error)。

        三种页面形态（任务书第 1 份 §4-§8 + 第 3 份 §三）：
        - **文件页面**（manifest `pages[].file`）：引擎读文件 → 净化 → 受控变量替换；
        - **插件页面**（manifest `pages[].render = "plugin"`）：引擎经 `webui.page` 取 HTML，
          同样先净化再替换变量；
        - **DSL 页面**（无 file / render，旧 compat）：走 `web_ui.entry` hook 返回组件树。

        顺序是**先净化、后替换变量**：变量值由模板渲染器 escape，无法借替换注入标记。
        POST（action != "get"）必须先过 `webui.action` 权限再交给插件 `webui.action`；
        老插件未声明该能力时回退到数据钩子（与 Phase 1 行为一致）。
        """
        row, manifest, page, err = self._plugin_webui_page_context(plugin_id, page_id)
        if err:
            return None, err
        approved = self._webui_approved(plugin_id)
        if not self._webui_granted(approved, "webui.view"):
            return None, "插件未批准 webui.view 权限（旧权限名 web_ui；管理员批准后才能访问）"
        action_name = str(action or "get")
        is_action = action_name != "get"
        if is_action and not self._webui_granted(approved, "webui.action"):
            return None, "插件未批准 webui.action 权限（无法提交表单）"
        render_kind = ("plugin" if page.get("render") == "plugin"
                       else ("file" if page.get("file") else "dsl"))
        if render_kind == "dsl":
            legacy, legacy_err = await self.plugin_webui_page(plugin_id, page_id, action,
                                                              params, values)
            if legacy_err:
                return None, legacy_err
            return {"mode": "dsl", "render": "dsl", "dsl": legacy.get("dsl"),
                    "page": legacy.get("page")}, ""

        rt = self._runtime_of(plugin_id)
        page_meta = {"id": str(page.get("id") or ""), "title": str(page.get("title") or ""),
                     "description": str(page.get("description") or "")}
        context = await self._webui_engine_context(plugin_id, row, page, approved,
                                                   method=("POST" if is_action else "GET"),
                                                   action=action_name)
        extra_vars: Dict[str, Any] = {}
        warnings: List[str] = []
        hook_error = ""
        raw_html: Optional[str] = None
        if render_kind == "plugin":
            if not self._webui_supports(rt, "webui.page"):
                return None, "该页面由插件渲染，但插件未声明 webui.page 能力"
            payload, perr = await self._webui_call(plugin_id, "webui.page",
                                                   {"page": page_meta, "context": context})
            if perr:
                return None, perr
            raw_html, extra_vars, hook_error = self._webui_read_payload(payload)
            if raw_html is None:
                return None, "插件未返回页面内容（webui.page 需要 html 字段）"
        if is_action:
            if self._webui_supports(rt, "webui.action"):
                payload, perr = await self._webui_call(plugin_id, "webui.action", {
                    "page": page_meta, "action": action_name,
                    "form": {str(k): str(v) for k, v in dict(values or {}).items()},
                    "context": context})
                if perr:
                    return None, perr
                html2, vars2, note = self._webui_read_payload(payload)
                if html2 is not None:
                    raw_html = html2
                extra_vars.update(vars2)
                if note:
                    hook_error = note
                warnings.extend(await self._webui_apply_writes(plugin_id, payload, approved))
            elif render_kind == "plugin":
                return None, "插件未声明 webui.action 能力（无法提交表单）"
            else:
                hook_vars, herr = await self._webui_html_hook_vars(plugin_id, manifest, page_id,
                                                                   action, params, values)
                extra_vars.update(hook_vars)
                if herr:
                    hook_error = herr
        elif render_kind == "file":
            hook_vars, herr = await self._webui_html_hook_vars(plugin_id, manifest, page_id,
                                                               action, params, values)
            extra_vars.update(hook_vars)
            if herr:
                hook_error = herr
        if raw_html is None:
            root = self.plugin_webui_dir(plugin_id)
            try:
                raw_html, _path = read_page(root, page.get("file"))
            except PluginWebuiPathError as e:
                return None, "页面不可用：%s" % e
        context_vars = self._webui_template_context(plugin_id, row, page)
        context_vars.update(extra_vars)
        from src.plugins.webui_security import render_plugin_template, sanitize_plugin_html

        style_prefix = "/panel/plugins/webui/%s/static/" % plugin_id
        safe_html, dropped = sanitize_plugin_html(raw_html, style_prefix=style_prefix)
        html, unresolved = render_plugin_template(safe_html, context_vars)
        return {"mode": "html", "render": render_kind, "html": html, "page": page,
                "vars": context_vars, "dropped": dropped, "unresolved": unresolved,
                "hook_error": hook_error, "warnings": warnings}, ""

    def plugin_webui_page_file(self, plugin_id: str, page_id: str) -> Optional[str]:
        """页面声明的相对路径（没有 = DSL 页面）。给面板/测试做模式判定用。"""
        _row, _manifest, page, err = self._plugin_webui_page_context(plugin_id, page_id)
        if err:
            return None
        return page.get("file")

    def _plugin_webui_page_context(self, plugin_id: str, page_id: str):
        """权限 + manifest + 页面定位（HTML / DSL 两条路径共用的前置检查）。"""
        row = self._plugin_of(plugin_id)
        if row is None or not row.get("enabled"):
            return None, None, None, "插件未启用或不存在"
        approved = set(row.get("approved_permissions") or [])
        if not self._webui_granted(approved, "webui.view"):
            return None, None, None, "插件未批准 webui.view 权限（旧权限名 web_ui；管理员批准后才能访问）"
        try:
            manifest = self._manifest_of_cb(row)
        except Exception:  # noqa: BLE001
            return None, None, None, "插件 manifest 不可解析"
        if not manifest or not manifest.web_ui:
            return None, None, None, "插件未声明 web_ui"
        page = next((p for p in manifest.web_ui["pages"] if p["id"] == page_id), None)
        if page is None:
            return None, None, None, f"页面不存在: {page_id}"
        return row, manifest, page, ""

    def _webui_template_context(self, plugin_id: str, row: dict, page: dict) -> Dict[str, Any]:
        """受控模板变量（任务书第 1 份 §7）：只有这些键，插件不能注入任意对象。"""
        return {
            "plugin_id": str(plugin_id),
            "plugin_name": str(row.get("name") or plugin_id),
            "page_id": str(page.get("id") or ""),
            "page_title": str(page.get("title") or ""),
            "page_description": str(page.get("description") or ""),
            "message": "",
        }

    async def _webui_html_hook_vars(self, plugin_id: str, manifest: Any, page_id: str, action: str,
                                    params: Optional[dict], values: Optional[dict]):
        """HTML 页面的可选数据钩子：插件可返回 `{"vars": {...}}` / `{"message": "..."}`。

        与 DSL 的区别：**没有 hook 也能渲染 HTML 页面**（静态页面是合法用法）。
        hook 报错/超时不影响页面本身，但会如实返回给调用方（面板会显示警示，不静默吞掉）。
        """
        rt = self._runtime_of(plugin_id)
        if rt is None:
            return {}, ""
        hook_name = str(manifest.web_ui.get("entry") or "webui_page")
        try:
            result = await asyncio.wait_for(
                self._hook_call(rt, hook_name, page_id, action,
                                        dict(params or {}), dict(values or {})),
                timeout=4.0)
        except asyncio.TimeoutError:
            return {}, "插件数据钩子超时（4s 上限）"
        except Exception as e:  # noqa: BLE001
            return {}, f"插件数据钩子失败: {type(e).__name__}: {e}"
        if result is None:
            return {}, ""
        if not isinstance(result, dict):
            return {}, "插件数据钩子返回了非法类型（应为对象）"
        if result.get("__error__"):
            return {}, str(result["__error__"])
        if "type" in result:
            # 这是 DSL 组件树，不是 HTML 变量：明确拒绝，避免"HTML 页面里塞 DSL"的隐性回退
            return {}, "HTML 页面不应返回 DSL 组件树（请返回 {'vars': {...}}）"
        out: Dict[str, Any] = {}
        for key in ("vars", "context"):
            extra = result.get(key)
            if isinstance(extra, dict):
                out.update({str(k): extra[k] for k in extra})
        if result.get("message") is not None:
            out["message"] = str(result.get("message"))
        return out, ""

    def _webui_operator_config(self, plugin_id: str) -> Dict[str, Any]:
        """操作员配置（manifest 的 config 段，只读）——与 engine op 的 config.get 同一来源。"""
        row = self._plugin_of(plugin_id)
        try:
            manifest = self._manifest_of_cb(row) if row else None
        except Exception:  # noqa: BLE001
            manifest = None
        cfg = (manifest.config if manifest else None) or {}
        if isinstance(cfg, dict) and isinstance(cfg.get("values"), dict):
            cfg = cfg["values"]
        return dict(cfg) if isinstance(cfg, dict) else {}

    async def _webui_storage_snapshot(self, plugin_id: str) -> Dict[str, Any]:
        """插件存储快照：经协议 storage.list + storage.get 取（插件未声明能力则为空）。"""
        rt = self._runtime_of(plugin_id)
        if not self._webui_supports(rt, "storage.list"):
            return {}
        listed, err = await self._webui_call(plugin_id, "storage.list", {"prefix": ""}, timeout=2.0)
        if err or not isinstance(listed, dict):
            return {}
        keys = listed.get("keys")
        out: Dict[str, Any] = {}
        for key in list(keys or [])[:200]:
            got, gerr = await self._webui_call(plugin_id, "storage.get", {"key": str(key)},
                                               timeout=2.0)
            if gerr or not isinstance(got, dict):
                continue
            out[str(key)] = got.get("value")
        return out

    async def _webui_engine_context(self, plugin_id: str, row: dict, page: dict, approved,
                                    *, method: str, action: str) -> Dict[str, Any]:
        """受控 WebUI Context（任务书第 3 份 §七）——只有这 6 个顶层键。

        - `config` / `data` 分别需要 webui.config.read / webui.storage.read，未批准就是空对象；
        - **绝不**放入面板令牌、会话、环境变量、宿主路径（安全用例逐项断言：Context 泄露 / Token 泄露）；
        - 页面模板变量是另一条通道（`_webui_template_context` + 插件显式返回的 vars），同样会被 escape。
        """
        ctx: Dict[str, Any] = {
            "plugin": {"id": str(plugin_id), "name": str(row.get("name") or plugin_id)},
            "page": {"id": str(page.get("id") or ""), "title": str(page.get("title") or "")},
            "request": {"method": str(method), "action": str(action or "get")},
            "user": {"authenticated": True, "role": "admin"},
            "config": {},
            "data": {},
        }
        if self._webui_granted(approved, "webui.config.read"):
            ctx["config"] = self._webui_operator_config(plugin_id)
        if self._webui_granted(approved, "webui.storage.read"):
            ctx["data"] = await self._webui_storage_snapshot(plugin_id)
        return ctx

    @staticmethod
    def _webui_read_payload(payload: Dict[str, Any]):
        """解析插件 WebUI 应答：返回 (html|None, vars, error)。

        `vars` / `context` 是插件**显式**给模板的变量（其余上下文不外泄）；
        `message` 归一成模板变量（面板壳会显示）。
        """
        html = payload.get("html")
        html = str(html) if isinstance(html, str) else None
        out: Dict[str, Any] = {}
        for key in ("vars", "context"):
            extra = payload.get(key)
            if isinstance(extra, dict):
                out.update({str(k): extra[k] for k in extra})
        if payload.get("message") is not None:
            out["message"] = str(payload.get("message"))
        return html, out, str(payload.get("error") or "")

    async def _webui_apply_writes(self, plugin_id: str, payload: Dict[str, Any],
                                  approved) -> List[str]:
        """动作返回的 `config_set` / `storage_set`：**先过权限**，再经协议写回。

        拒绝或失败都如实返回告警（不静默吞掉），页面壳会把告警显示给管理员。
        """
        warnings: List[str] = []
        cfg_set = payload.get("config_set")
        if isinstance(cfg_set, dict) and cfg_set:
            if not self._webui_granted(approved, "webui.config.write"):
                warnings.append("配置写入被拒绝：未批准 webui.config.write")
            else:
                _res, err = await self._webui_call(plugin_id, "config.set", {"values": cfg_set})
                if err:
                    warnings.append("配置写入失败：%s" % err)
        store_set = payload.get("storage_set")
        if isinstance(store_set, dict) and store_set:
            if not self._webui_granted(approved, "webui.storage.write"):
                warnings.append("存储写入被拒绝：未批准 webui.storage.write")
            else:
                for key, value in list(store_set.items())[:64]:
                    _res, err = await self._webui_call(plugin_id, "storage.set",
                                                       {"key": str(key), "value": value})
                    if err:
                        warnings.append("存储写入失败(%s)：%s" % (key, err))
        return warnings
