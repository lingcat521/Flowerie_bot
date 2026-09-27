"""插件 WebUI 宿主（Phase 1 / M2：从 PluginManager 拆出的 WebUI 职责域）。

M2a（本次）先搬「文件空间」三件事：
- 拥有：插件 WebUI 专属目录推导、上传保存、下载读取（名称/扩展名/大小/魔数/穿越防护）
- 注入：只有一个 `plugin_root` 回调（manager 传 `self._plugin_dir`）
- 不拥有：权限判定（`web_ui.files` 由调用方 gate）、页面渲染、静态资源（后续步骤搬入）

行为与拆分前**逐字一致**（错误文案、校验顺序、上限都不变）。
"""
import os
import re
from typing import Callable, Tuple

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

    def __init__(self, plugin_root: Callable[[], str]):
        self._plugin_root = plugin_root

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

