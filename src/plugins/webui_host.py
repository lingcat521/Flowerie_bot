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

from src.plugins.webui_loader import (PluginWebuiPathError, STATIC_EXTS, read_static,
                                    static_root, validate_relative)

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
                 manifest_of: Callable[[dict], Any], runtime_of: Callable[[str], Any]):
        self._plugin_root = plugin_root
        self._plugin_of = plugin_of
        self._manifest_of_cb = manifest_of
        self._runtime_of = runtime_of

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
