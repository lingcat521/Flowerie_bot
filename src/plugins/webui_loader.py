"""插件 WebUI 文件加载与路径安全（任务书第 1 份 §4 / §5 / §6 / §12）。

核心原则（任务书 §6 明令）：
    URL page id → manifest 声明 → 解析出相对路径 → **校验** → 确认在插件 webui 根内 → 读文件
而不是：
    URL 里的文件名 → open(filename)

因此本模块**只接受 manifest 里声明过的相对路径**，并且：
- 禁止绝对路径、`..` 段、反斜杠、NUL、隐藏段（以 . 开头）
- `realpath` 必须仍在插件 webui 根内（防 symlink 逃逸）
- 扩展名白名单（页面只允许 .html；静态只允许 css/图片/文本类，**不允许 .js** —— No-JS 政策）
- 单文件大小上限；必须是普通文件
"""
import os
import re
from typing import Dict, Optional, Tuple

PAGE_EXTS = (".html",)
STATIC_EXTS = (".css", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".txt", ".json", ".md", ".csv", ".ico")
MIME_TYPES: Dict[str, str] = {
    ".css": "text/css; charset=utf-8",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".webp": "image/webp", ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8", ".json": "application/json; charset=utf-8",
    ".md": "text/plain; charset=utf-8", ".csv": "text/csv; charset=utf-8",
    ".html": "text/html; charset=utf-8",
}
PAGE_MAX_BYTES = 512 * 1024
STATIC_MAX_BYTES = 4 * 1024 * 1024
_REL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")


class PluginWebuiPathError(ValueError):
    """路径非法（穿越 / 绝对路径 / 扩展名不允许 / 越界）。"""


def validate_relative(raw: object, allowed_exts: Tuple[str, ...], *, field: str = "path") -> str:
    """校验一个**相对路径**（manifest 声明或静态资源请求）；不通过直接抛错。"""
    s = str(raw or "").strip()
    if not s:
        raise PluginWebuiPathError("%s 不能为空" % field)
    if len(s) > 200:
        raise PluginWebuiPathError("%s 过长" % field)
    if s.startswith(("/", "\\")) or "\\" in s or "\x00" in s:
        raise PluginWebuiPathError("%s 不能是绝对路径或含反斜杠" % field)
    if not _REL_RE.match(s):
        raise PluginWebuiPathError("%s 含非法字符（只允许字母数字 . _ - /）" % field)
    parts = s.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise PluginWebuiPathError("%s 含非法路径段（不允许 .. / 空段）" % field)
    if any(p.startswith(".") for p in parts):
        raise PluginWebuiPathError("%s 不允许隐藏文件/目录" % field)
    ext = os.path.splitext(s)[1].lower()
    if ext not in allowed_exts:
        raise PluginWebuiPathError("%s 扩展名不允许：%s（允许 %s）" % (field, ext or "(无)", ", ".join(allowed_exts)))
    return s


def resolve_within(root: str, rel: str, *, max_bytes: int, allowed_exts: Tuple[str, ...],
                   field: str = "path") -> str:
    """把相对路径解析成绝对路径，并确保它**真实落在** root 内（含 symlink 检查）。"""
    rel = validate_relative(rel, allowed_exts, field=field)
    base = os.path.realpath(root)
    target = os.path.realpath(os.path.join(base, rel))
    if target != base and not target.startswith(base + os.sep):
        raise PluginWebuiPathError("%s 越出插件 WebUI 根目录" % field)
    if not os.path.isfile(target):
        raise PluginWebuiPathError("%s 文件不存在" % field)
    size = os.path.getsize(target)
    if size > max_bytes:
        raise PluginWebuiPathError("%s 超过大小上限（%d > %d 字节）" % (field, size, max_bytes))
    return target


def read_page(root: str, rel: str, *, max_bytes: int = PAGE_MAX_BYTES) -> Tuple[str, str]:
    """读取页面 HTML（只允许 .html）；返回 (文本, 绝对路径)。解码失败按 utf-8 容错。"""
    target = resolve_within(root, rel, max_bytes=max_bytes, allowed_exts=PAGE_EXTS, field="页面文件")
    with open(target, "rb") as fh:
        raw = fh.read(max_bytes)
    return raw.decode("utf-8", errors="replace"), target


def read_static(root: str, rel: str, *, max_bytes: int = STATIC_MAX_BYTES) -> Tuple[bytes, str, str]:
    """读取静态资源；返回 (bytes, mime, 绝对路径)。"""
    target = resolve_within(root, rel, max_bytes=max_bytes, allowed_exts=STATIC_EXTS, field="静态资源")
    with open(target, "rb") as fh:
        blob = fh.read(max_bytes)
    return blob, guess_mime(target), target


def guess_mime(path: str) -> str:
    return MIME_TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


def static_root(webui_root: str, declared: Optional[str]) -> str:
    """静态资源根目录：manifest 的 `web_ui.static`（默认 "static"），同样要过路径校验。"""
    rel = str(declared or "static").strip() or "static"
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts) or rel.startswith("/") or "\\" in rel:
        raise PluginWebuiPathError("web_ui.static 非法：%r" % declared)
    return os.path.join(webui_root, rel)
