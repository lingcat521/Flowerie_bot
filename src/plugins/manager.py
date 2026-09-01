"""PluginManager：插件注册表 + 生命周期 + 事件分发 + Action 执行（受控运行时入口）。

职责边界（与 Flowerie 现有架构对齐）：
- 注册表：settings.db `plugins` 表（manifest 镜像 / enabled / 批准的权限 / 保护级别 / 状态）
- 自动发现：扫描 PLUGIN_DIR 下的 */manifest.json → 校验 → 注册（**发现 ≠ 自动执行**，
  新插件一律 enabled=0，由管理员明确启用并批准权限）
- 运行时：enabled 插件启动独立子进程（PluginRuntime）；崩溃/超时标记 unhealthy，
  Flowerie 继续运行（不影响其他插件与主流程）
- 事件分发：message/notice 等事件按 read_message 权限投递（声明式 JSON 插件在进程内
  匹配规则，不落地执行代码）
- Action 执行：**唯一副作用出口**，一切 action 先过 PermissionManager，拒绝即记日志
  （plugin_permission_denied），绝不静默放行；token/secret 不写日志

安全不变式（任何保护级别都不豁免）：管理员权限（Web UI 认证）、安装完整性检查、
manifest 校验、进程隔离、日志、崩溃保护、资源限制、权限强制。
"""
import json
import os
import random
import re
import shutil
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.core.sanitizer import validate_memory_content
from src.plugins.http_action import plugin_http_request, redact_url
from src.plugins.installer import PluginInstaller, PluginInstallError
from src.plugins.manifest import PluginManifest, PluginManifestError
from src.plugins.permissions import PermissionManager
from src.plugins.runtime import PluginRuntime
from src.repositories.settings_repository import SettingsRepository
from src.sdk.bot import Bot
from src.sdk.event import BotEvent
from src.sdk.matcher import Matcher
from src.sdk.onebot.adapter import OneBotAdapter
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)

# 事件类型 → 需要权限（未批准则事件不投递）
_EVENT_PERMISSION = {"message": "read_message", "group_message": "read_message",
                     "notice": "read_message", "command": "read_message"}
# 声明式插件支持的模板字段（值只能来自事件 payload，绝不执行代码）
_TEMPLATE_FIELDS = ("group_id", "user_id", "text", "message_name", "message")


class PluginManager:
    """受控插件运行时管理器。"""

    def __init__(self, config, repository: SettingsRepository,
                 sender: Optional[Any] = None, memory_manager: Optional[Any] = None,
                 state_provider: Optional[Callable[[str, Any], Optional[dict]]] = None,
                 installer: Optional[PluginInstaller] = None, context_manager: Optional[Any] = None,
                 ai_client: Optional[Any] = None):
        self.config = config
        self.repository = repository
        self.sender = sender
        self.memory_manager = memory_manager
        # state_provider: (kind, id) -> dict | None（get_group/get_user 的数据源，由 main 注入）
        self.state_provider = state_provider
        self.installer = installer or PluginInstaller(self._plugin_dir())
        self._runtimes: Dict[str, PluginRuntime] = {}
        self._manifest_cache: Dict[str, Optional[PluginManifest]] = {}
        self._started = False
        # 本实例（bot）已发送的 message_id 记录：插件只能撤回这些消息（防删他人消息）
        self._sent_message_ids: list = []
        self._context_manager = context_manager   # SDK get_context 复用 ContextManager
        self._ai_client = ai_client               # ai_chat 调用注入
        self._matchers: Dict[str, list] = {}      # plugin_id -> [Matcher]（SDK 注册）
        self._bot = None                          # SDK 匹配用 Bot（惰性构建）
        self._schedules: Dict[str, dict] = {}     # schedule_id -> {plugin_id,name,kind,...}
        self._schedule_tasks: Dict[str, Any] = {} # schedule_id -> asyncio.Task

    @property
    def plugin_dir(self) -> str:
        return os.path.abspath(self._plugin_dir())

    def _plugin_dir(self) -> str:
        return str(getattr(self.config, "PLUGIN_DIR", "./plugins") or "./plugins")

    # ================= Plugin WebUI 文件空间（web_ui.files 权限；仅插件自己目录） =================
    _WEBUI_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".txt", ".json",
                          ".md", ".log", ".csv"}
    _WEBUI_MAX_UPLOAD = 10 * 1024 * 1024  # 10MB
    _WEBUI_ALLOWED_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

    def plugin_webui_dir(self, plugin_id: str) -> str:
        """插件 WebUI 专属空间（不影响插件常规文件系统路径）。"""
        import os
        base = os.path.abspath(self._plugin_dir())
        d = os.path.join(base, plugin_id, "webui")
        # 防穿越：必须位于插件目录内
        if not os.path.abspath(d).startswith(base + os.sep):
            raise ValueError("非法插件目录")
        os.makedirs(d, exist_ok=True)
        return d

    def webui_save_upload(self, plugin_id: str, filename: str, data: bytes):
        """带权限/扩展名/名称/大小/魔数校验的保存（web_ui.files 由调用方 gate）。"""
        import os
        raw_name = str(filename or "")
        if "/" in raw_name or "\\" in raw_name:
            raise ValueError("文件名含路径分隔符（拒绝）")
        name = os.path.basename(raw_name)
        if not self._WEBUI_ALLOWED_NAME.fullmatch(name):
            raise ValueError("文件名非法（仅字母/数字/下划线/点/短横线，≤64）")
        ext = os.path.splitext(name)[1].lower()
        if ext not in self._WEBUI_ALLOWED_EXT:
            raise ValueError(f"不支持的扩展名（允许: {', '.join(sorted(self._WEBUI_ALLOWED_EXT))}）")
        if len(data) > self._WEBUI_MAX_UPLOAD:
            raise ValueError("文件超过 10MB 上限")
        # 魔数核验（图片类必须命中；文本类不校验内容）
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            sigs = {".png": b"\x89PNG", ".jpg": b"\xff\xd8", ".jpeg": b"\xff\xd8",
                    ".gif": (b"GIF87a", b"GIF89a"), ".webp": b"RIFF"}
            sig = sigs[ext]
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

    def webui_read_file(self, plugin_id: str, name: str, max_bytes: int = 50 * 1024 * 1024):
        """带穿越防护的读取（下载）；返回 (bytes, safe_name, ext)。"""
        import os
        if not self._WEBUI_ALLOWED_NAME.fullmatch(name or ""):
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

    # ================= Plugin WebUI（控制面；不进入消息高频路径） =================
    async def plugin_webui_page(self, plugin_id: str, page_id: str, action: str = "get",
                                params: Optional[dict] = None, values: Optional[dict] = None):
        """插件 WebUI 页面渲染/提交的统一入口。

        权限：插件须启用且管理员批准过 web_ui（web_ui.files 控制文件能力——本方法不含文件）。
        返回 (dsl, error_str)：dsl 可直接交给 render_plugin_dsl；error 非空时渲染错误页。
        任何异常都降级为错误页，绝不把异常/原始 HTML 交给浏览器。
        """
        row = self.get_plugin(plugin_id)
        if row is None or not row.get("enabled"):
            return None, "插件未启用或不存在"
        approved = set(row.get("approved_permissions") or [])
        if "web_ui" not in approved:
            return None, "插件未批准 web_ui 权限（管理员批准后才能访问）"
        try:
            manifest = self._manifest_of(row)
        except Exception:  # noqa: BLE001
            return None, "插件 manifest 不可解析"
        if not manifest or not manifest.web_ui:
            return None, "插件未声明 web_ui"
        page = next((p for p in manifest.web_ui["pages"] if p["id"] == page_id), None)
        if page is None:
            return None, f"页面不存在: {page_id}"
        rt = self._runtimes.get(plugin_id)
        if rt is None:
            return None, "插件运行中未加载（重启后重试）"
        hook_name = str(manifest.web_ui.get("entry") or "webui_page")
        try:
            import asyncio
            result = await asyncio.wait_for(
                asyncio.to_thread(rt._call_hook, hook_name, page_id, action,
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

    # ================= 注册表 =================
    def _manifest_of(self, record: dict) -> Optional[PluginManifest]:
        """从注册行解析 manifest（带进程内缓存，manifest 变更时失效）。"""
        m = self._manifest_cache.get(record["id"], "missing")
        if m == "missing" or (isinstance(m, PluginManifest) and m.to_json() != record.get("manifest_json")):
            try:
                m = PluginManifest.from_dict(json.loads(record["manifest_json"]))
            except (PluginManifestError, ValueError):
                m = None
            self._manifest_cache[record["id"]] = m
        return m

    def list_plugins(self) -> List[dict]:
        """注册表视图（含解析后的 manifest 摘要与运行时状态）。"""
        rows = self.repository.list_plugins()
        result = []
        for row in rows:
            manifest = self._manifest_of(row)
            rt = self._runtimes.get(row["id"])
            status = row["status"]
            if rt is not None:
                status = rt.status
            result.append({
                "id": row["id"],
                "enabled": bool(row["enabled"]),
                "status": status,
                "protection": row.get("protection", "normal") or "normal",
                "approved_permissions": [p for p in (row.get("approved_permissions") or "").split(",") if p],
                "install_source": row.get("install_source", ""),
                "version": manifest.version if manifest else "?",
                "name": manifest.name if manifest else row["id"],
                "runtime": manifest.runtime if manifest else "?",
                "declared_permissions": manifest.permissions if manifest else [],
                "description": manifest.description if manifest else "",
                "manifest_valid": manifest is not None,
            })
        return result

    def get_plugin(self, plugin_id: str) -> Optional[dict]:
        for item in self.list_plugins():
            if item["id"] == plugin_id:
                return item
        return None

    # ================= 自动发现（发现 ≠ 自动执行） =================
    def discover(self) -> List[str]:
        """扫描插件目录：新插件注册为 disabled（启用需管理员明确操作）。返回新发现 id 列表。"""
        os.makedirs(self.plugin_dir, exist_ok=True)
        known = {row["id"] for row in self.repository.list_plugins()}
        discovered: List[str] = []
        for entry in sorted(os.listdir(self.plugin_dir)):
            dir_path = os.path.join(self.plugin_dir, entry)
            if not os.path.isdir(dir_path):
                continue
            manifest_path = os.path.join(dir_path, "manifest.json")
            if not os.path.isfile(manifest_path):
                continue
            try:
                manifest = PluginManifest.load(manifest_path)
            except (PluginManifestError, OSError, ValueError) as e:
                logger.warning("plugin_discover_invalid dir=%s reason=%s", entry, e,
                               extra={"event": "plugin_invalid"})
                if entry in known:
                    self._mark_status(entry, "invalid")
                continue
            if manifest.id in known or manifest.id in discovered:
                continue
            self.repository.upsert_plugin({
                "id": manifest.id,
                "manifest_json": manifest.to_json(),
                "enabled": False,           # 发现 ≠ 自动执行
                "approved_permissions": [],
                "protection": self._protection_level(),
                "status": "discovered",
                "install_source": "local",
            })
            discovered.append(manifest.id)
            logger.info("plugin_discovered id=%s version=%s", manifest.id, manifest.version,
                        extra={"event": "plugin_discovered"})
        return discovered

    def refresh(self) -> Tuple[List[str], List[str]]:
        """重新扫描（新发现的插件 disabled；manifest 变更的注册行同步 + 停掉旧运行时）。"""
        discovered = self.discover()
        changed: List[str] = []
        for row in self.repository.list_plugins():
            dir_path = os.path.join(self.plugin_dir, row["id"])
            manifest_path = os.path.join(dir_path, "manifest.json")
            if not os.path.isfile(manifest_path):
                continue
            try:
                manifest = PluginManifest.load(manifest_path)
            except (PluginManifestError, OSError, ValueError):
                continue
            if manifest.to_json() != row.get("manifest_json"):
                self._stop_runtime(row["id"])
                self.repository.upsert_plugin({
                    "id": row["id"], "manifest_json": manifest.to_json(),
                    "enabled": bool(row["enabled"]),
                    "approved_permissions": (row.get("approved_permissions") or "").split(","),
                    "protection": row.get("protection", "normal") or "normal",
                    "status": "discovered", "install_source": row.get("install_source", ""),
                })
                changed.append(row["id"])
                logger.info("plugin_manifest_updated id=%s", row["id"], extra={"event": "plugin_updated"})
        return discovered, changed

    # ================= 安装 / 卸载 =================
    def install_upload(self, data: bytes, filename: str = "") -> Tuple[bool, str]:
        """文件上传安装（校验通过才落盘 + 注册；安装后一律 disabled）。"""
        try:
            manifest = self.installer.install_from_bytes(data, source="upload", filename=filename)
        except PluginInstallError as e:
            logger.warning("plugin_install_rejected source=upload reason=%s", e,
                           extra={"event": "plugin_install_rejected"})
            return False, str(e)
        return self._register_installed(manifest, "upload")

    def install_url(self, url: str) -> Tuple[bool, str]:
        """URL 下载安装（同步占位：必须走 install_url_async，见 Web UI 处理器）。"""
        raise RuntimeError("URL 安装必须使用 install_url_async（async 环境）")

    async def install_url_async(self, url: str) -> Tuple[bool, str]:
        try:
            manifest = await self.installer.install_from_url(url)
        except PluginInstallError as e:
            logger.warning("plugin_install_rejected source=url url=%s reason=%s",
                           redact_url(url), e, extra={"event": "plugin_install_rejected"})
            return False, str(e)
        return self._register_installed(manifest, "url")

    def _register_installed(self, manifest: PluginManifest, source: str) -> Tuple[bool, str]:
        existing = self.repository.get_plugin(manifest.id)
        if existing:
            return False, f"插件 {manifest.id} 已存在于注册表（请先卸载）"
        self.repository.upsert_plugin({
            "id": manifest.id, "manifest_json": manifest.to_json(),
            "enabled": False, "approved_permissions": [],
            "protection": self._protection_level(), "status": "discovered",
            "install_source": source,
        })
        logger.info("plugin_installed id=%s version=%s source=%s", manifest.id, manifest.version, source,
                    extra={"event": "plugin_installed"})
        return True, f"插件「{manifest.name}」已安装（默认禁用，请手动启用并批准权限）"

    def uninstall(self, plugin_id: str) -> Tuple[bool, str]:
        self._matchers.pop(plugin_id, None)  # SDK matcher 残留清理
        row = self.repository.get_plugin(plugin_id)
        if row is None:
            return False, "插件不存在"
        self._stop_runtime(plugin_id)
        self._manifest_cache.pop(plugin_id, None)
        self.repository.delete_plugin(plugin_id)
        dir_path = os.path.join(self.plugin_dir, plugin_id)
        if os.path.isdir(dir_path):
            shutil.rmtree(dir_path, ignore_errors=True)
        logger.info("plugin_uninstalled id=%s", plugin_id, extra={"event": "plugin_uninstalled"})
        return True, f"插件 {plugin_id} 已卸载"

    # ================= 启用 / 禁用（管理员操作） =================
    async def enable(self, plugin_id: str, approved_permissions: Optional[List[str]] = None,
                     protection: Optional[str] = None) -> Tuple[bool, str]:
        """启用插件并批准权限（权限子集 = manifest 声明 ∩ 管理员选择）。"""
        row = self.repository.get_plugin(plugin_id)
        if row is None:
            return False, "插件不存在（请先扫描/安装）"
        manifest = self._manifest_of(row)
        if manifest is None:
            return False, "manifest 校验失败，无法启用"
        if manifest.runtime == "node":
            import shutil as _shutil
            if _shutil.which("node") is None:
                return False, "Node.js 插件需要 node 可执行文件（环境未安装）"
        protection = (protection or row.get("protection") or "normal")
        if protection not in PermissionManager.PROTECTION_LEVELS:
            return False, f"保护级别非法: {protection}"
        declared = set(manifest.permissions)
        chosen = [p for p in (approved_permissions or []) if p and p in declared]
        if manifest.permissions and approved_permissions is not None and set(approved_permissions) - declared:
            return False, "批准了 manifest 未声明的权限（拒绝）"
        if manifest.permissions and not chosen:
            return False, "该插件声明了权限，请至少批准一项后再启用（0 权限不建议启用）"
        # 已运行则先停（更新权限/保护级别后重启）
        self._stop_runtime(plugin_id)
        self.repository.upsert_plugin({
            "id": plugin_id, "manifest_json": manifest.to_json(),
            "enabled": True, "approved_permissions": chosen,
            "protection": protection, "status": "starting",
            "install_source": row.get("install_source", ""),
        })
        try:
            rt = self._start_runtime(plugin_id, manifest, chosen, protection)
            if manifest.runtime != "json":
                await rt.start()  # json 声明式插件无需子进程
            else:
                rt.status = "running"
                self._mark_status(plugin_id, "running")
        except Exception as e:  # noqa: BLE001 - 启用失败：回滚 enabled
            self.repository.upsert_plugin({
                "id": plugin_id, "manifest_json": manifest.to_json(),
                "enabled": False, "approved_permissions": chosen,
                "protection": protection, "status": "error", "install_source": row.get("install_source", ""),
            })
            logger.error("plugin_enable_failed id=%s reason=%s", plugin_id, e,
                         extra={"event": "plugin_enable_failed"})
            return False, f"启用失败: {type(e).__name__}: {e}"
        logger.info("plugin_enabled id=%s perms=%s protection=%s", plugin_id, chosen, protection,
                    extra={"event": "plugin_enabled"})
        return True, f"插件「{manifest.name}」已启用（权限: {', '.join(chosen) or '无'}；保护: {protection}）"

    def disable(self, plugin_id: str) -> Tuple[bool, str]:
        self._matchers.pop(plugin_id, None)  # 禁用即撤销 matcher 注册
        row = self.repository.get_plugin(plugin_id)
        if row is None:
            return False, "插件不存在"
        self._stop_runtime(plugin_id)
        self.repository.upsert_plugin({
            "id": plugin_id, "manifest_json": row["manifest_json"],
            "enabled": False, "approved_permissions": (row.get("approved_permissions") or "").split(","),
            "protection": row.get("protection", "normal") or "normal",
            "status": "disabled", "install_source": row.get("install_source", ""),
        })
        self._manifest_cache.pop(plugin_id, None)
        logger.info("plugin_disabled id=%s", plugin_id, extra={"event": "plugin_disabled"})
        return True, f"插件 {plugin_id} 已禁用"

    def set_protection(self, level: str) -> Tuple[bool, str]:
        """全局插件保护级别（Web UI 开关；影响后续启动的运行时限制）。"""
        if level not in PermissionManager.PROTECTION_LEVELS:
            return False, "保护级别非法（normal/relaxed/unsafe）"
        setattr(self.config, "PLUGIN_PROTECTION", level)
        return True, f"插件保护级别已设为 {level}（运行中插件需重启生效）"

    def _protection_level(self) -> str:
        level = str(getattr(self.config, "PLUGIN_PROTECTION", "normal") or "normal").lower()
        return level if level in PermissionManager.PROTECTION_LEVELS else "normal"

    # ================= 运行时生命周期 =================
    def _start_runtime(self, plugin_id: str, manifest: Optional[PluginManifest],
                       approved: List[str], protection: str) -> PluginRuntime:
        if manifest is None:
            manifest = self._manifest_of(self.repository.get_plugin(plugin_id))
            if manifest is None:
                raise RuntimeError("manifest 非法")
        rt = PluginRuntime(
            plugin_id, manifest, os.path.join(self.plugin_dir, plugin_id),
            protection=protection, on_exit=self._on_runtime_exit,
        )
        rt.permissions = PermissionManager(approved, protection)
        rt.set_action_handler(self._handle_action)
        self._runtimes[plugin_id] = rt
        return rt

    async def start_all(self) -> None:
        """启动所有 enabled 插件（发现新插件；失败记状态不影响启动）。"""
        self._started = True
        try:
            self.discover()
        except Exception as e:  # noqa: BLE001
            logger.error("plugin_discover_failed reason=%s", e)
        for row in self.repository.list_plugins():
            if not row.get("enabled"):
                continue
            manifest = self._manifest_of(row)
            if manifest is None:
                self._mark_status(row["id"], "invalid")
                continue
            if manifest.runtime == "json":
                # 声明式：进程内（无代码执行），无需子进程
                rt = PluginRuntime(row["id"], manifest, os.path.join(self.plugin_dir, row["id"]),
                                   protection=row.get("protection") or "normal",
                                   on_exit=self._on_runtime_exit)
                rt.permissions = PermissionManager(
                    (row.get("approved_permissions") or "").split(","),
                    row.get("protection") or "normal")
                self._runtimes[row["id"]] = rt
                self._mark_status(row["id"], "running")
                continue
            try:
                rt = self._start_runtime(row["id"], manifest,
                                         (row.get("approved_permissions") or "").split(","),
                                         row.get("protection") or "normal")
                await rt.start()
            except Exception as e:  # noqa: BLE001 - 单插件失败不阻塞
                self._mark_status(row["id"], "error")
                logger.error("plugin_start_failed id=%s reason=%s", row["id"], e,
                             extra={"event": "plugin_failed"})

    async def shutdown(self) -> None:
        self._started = False
        self.cancel_all_schedules()  # 清理全部定时任务（防 task 泄漏）
        for plugin_id in list(self._runtimes.keys()):
            rt = self._runtimes.pop(plugin_id, None)
            if rt is not None:
                try:
                    await rt.shutdown()
                except Exception:  # noqa: BLE001
                    pass
        self._runtimes.clear()

    def _stop_runtime(self, plugin_id: str) -> None:
        rt = self._runtimes.pop(plugin_id, None)
        if rt is not None:
            asyncio_create_task(rt.shutdown())

    def _mark_status(self, plugin_id: str, status: str) -> None:
        row = self.repository.get_plugin(plugin_id)
        if row is None:
            return
        self.repository.upsert_plugin({
            "id": plugin_id, "manifest_json": row["manifest_json"],
            "enabled": bool(row["enabled"]), "approved_permissions": (row.get("approved_permissions") or "").split(","),
            "protection": row.get("protection", "normal") or "normal",
            "status": status, "install_source": row.get("install_source", ""),
        })

    def _on_runtime_exit(self, plugin_id: str, reason: str, code: int) -> None:
        """插件进程异常退出：标记 unhealthy（Flowerie 继续运行；管理员可重新启用）。"""
        self._mark_status(plugin_id, "crashed")
        logger.error("plugin_crashed id=%s reason=%s code=%s", plugin_id, reason, code,
                     extra={"event": "plugin_crash"})

    # ================= 事件分发 =================
    async def dispatch_event(self, event_type: str, payload: Dict[str, Any]) -> List[dict]:
        """向所有 enabled 且有 read_message 权限的插件投递事件；返回执行摘要（测试可断言）。"""
        if not self._started:
            self._started = True  # 幂等：未显式 start_all 时自动发现一次（测试友好）
            try:
                self.discover()
            except Exception:  # noqa: BLE001
                pass
        summary: List[dict] = []
        required = _EVENT_PERMISSION.get(event_type, "read_message")
        for row in self.repository.list_plugins():
            if not row.get("enabled"):
                continue
            record_id = row["id"]
            approved = set((row.get("approved_permissions") or "").split(","))
            if required not in approved:
                continue  # 事件权限未批准：不投递（权限不是提示文字）
            manifest = self._manifest_of(row)
            # SDK 模式：插件注册过 matcher → 只投递命中事件（payload 附带 matched 列表）
            matchers = self._matchers.get(record_id)
            if matchers:
                hits = await self._match_plugin_payload(record_id, matchers, event_type, payload)
                if not hits:
                    continue
                payload = {**payload, "matched": hits}
            if manifest is None:
                continue
            try:
                if manifest.runtime == "json":
                    actions = self._declarative_match(manifest, event_type, payload)
                    for action in actions:
                        summary.extend(await self._execute_action(record_id, action))
                else:
                    rt = self._runtimes.get(record_id)
                    if rt is None or not rt.healthy:
                        continue
                    actions = await rt.dispatch_event(event_type, payload)
                    for action in actions:
                        summary.extend(await self._execute_action(record_id, action))
            except Exception as e:  # noqa: BLE001 - 插件异常被隔离
                logger.error("plugin_event_error id=%s event=%s reason=%s", record_id, event_type, e,
                             extra={"event": "plugin_error"})
        return summary

    async def _match_plugin_payload(self, plugin_id, matchers, event_type, payload):
        """SDK Matcher 匹配：返回命中的 [{name, kind, args, block}]（priority 降序）。"""
        try:
            if self._bot is None and self.sender is not None:
                self._bot = Bot(OneBotAdapter(self.sender, self._context_manager))
            if self._bot is None:
                return []  # 无 sender：匹配不可用 → 不投递（保守）
            event = BotEvent.from_dict(payload)
            hits = []
            for m in sorted(matchers, key=lambda x: x.priority, reverse=True):
                try:
                    if await m.amatches(event, self._bot):
                        hits.append({"name": m.name or "", "kind": m.kind,
                                     "args": getattr(event, "matcher_args", ""),
                                     "block": m.block})
                except Exception:  # noqa: BLE001 - 匹配失败按不命中处理
                    continue
            return hits
        except Exception:  # noqa: BLE001 - 匹配框架异常 → 不投递（保守）
            return []

    # ================= 声明式 JSON 插件（进程内规则匹配，无代码执行） =================
    def _declarative_match(self, manifest: PluginManifest, event_type: str, payload: Dict[str, Any]) -> List[dict]:
        if event_type not in ("message", "group_message", "notice"):
            return []
        wants = "message" if event_type in ("message", "group_message") else "notice"
        actions: List[dict] = []
        # 优先级大者先执行；stop=true 的规则命中后，本插件剩余规则不再匹配（Matcher 阻断）
        rules = sorted(manifest.declarations, key=lambda r: int(r.get("priority") or 0), reverse=True)
        for rule in rules:
            if rule["event"] != wants:
                continue
            match = rule["match"]
            if not self._rule_matches(match, payload):
                continue
            for a in rule["actions"]:
                actions.append({
                    "type": str(a.get("type") or ""),
                    "payload": self._substitute(a.get("payload") or {}, payload),
                })
            if rule.get("stop"):  # Matcher 阻断：插件内后续规则不再匹配（跨插件不阻断，保隔离）
                break
        return actions

    @staticmethod
    def _rule_matches(match: dict, payload: Dict[str, Any]) -> bool:
        for key, value in match.items():
            if key == "text_contains":
                if str(value) not in str(payload.get("text", "")):
                    return False
            elif key == "text_prefix":
                if not str(payload.get("text", "")).startswith(str(value)):
                    return False
            elif key == "text_exact":
                if str(payload.get("text", "")) != str(value):
                    return False
            elif key == "text_suffix":
                if not str(payload.get("text", "")).endswith(str(value)):
                    return False
            elif key == "text_regex":
                try:
                    if re.search(str(value)[:200], str(payload.get("text", ""))) is None:
                        return False
                except re.error:
                    return False
            elif key == "command":
                # 命令匹配：与消息开头（可选前缀）解析的命令名及参数
                import shlex
                text = str(payload.get("text", "")).strip()
                parts = shlex.split(text) if text else []
                if not parts:
                    return False
                cmd_name, cmd_args = parts[0].lstrip("/!."), parts[1:]
                wanted = str(value)
                okay = cmd_name in {wanted, wanted.lstrip("/!.")}
                if not okay:
                    return False
                if isinstance(match.get("args"), (list, tuple)) and match.get("args"):
                    if len(cmd_args) < len(match["args"]):
                        return False
                return True
            elif key == "user_id":
                try:
                    if int(payload.get("user_id", -1)) != int(value):
                        return False
                except (TypeError, ValueError):
                    return False
            elif key == "group_id":
                try:
                    if int(payload.get("group_id", -1)) != int(value):
                        return False
                except (TypeError, ValueError):
                    return False
        return True

    @classmethod
    def _substitute(cls, value: Any, payload: Dict[str, Any]) -> Any:
        """模板替换：${group_id} 等只从事件 payload 取值（纯文本替换，绝无代码路径）。"""
        if isinstance(value, str):
            out = value
            for field in _TEMPLATE_FIELDS:
                out = out.replace("${" + field + "}", str(payload.get(field, "")))
            return out
        if isinstance(value, dict):
            return {k: cls._substitute(v, payload) for k, v in value.items()}
        if isinstance(value, list):
            return [cls._substitute(v, payload) for v in value]
        return value

    # ================= Action 执行（唯一副作用出口） =================
    async def _handle_action(self, plugin_id: str, action: str, payload: Dict[str, Any]) -> dict:
        """PluginRuntime 的回调：执行单个 action（含权限检查与结果回传插件）。"""
        results = await self._execute_action(plugin_id, {"type": action, "payload": payload})
        if not results:
            return {"ok": False, "error": "permission denied or unknown action"}
        first = results[0]
        # 权限拒绝/错误的内层响应直接是 {ok:False, denied:True, ...}（无嵌套 result）——
        # 必须原样回传，否则插件会把「拒绝」当成功
        return first.get("result", first)

    async def _execute_action(self, plugin_id: str, action: dict) -> List[dict]:
        action_type = str(action.get("type") or "")
        payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
        row = self.repository.get_plugin(plugin_id)
        if row is None:
            return [{"plugin": plugin_id, "action": action_type, "ok": False, "denied": True,
                     "error": "plugin not in registry"}]
        rt = self._runtimes.get(plugin_id)
        pm = rt.permissions if rt is not None else PermissionManager(
            (row.get("approved_permissions") or "").split(","), row.get("protection") or "normal")
        if not pm.check(action_type):
            reason = pm.denied_reason(action_type)
            logger.warning("plugin_permission_denied id=%s action=%s reason=%s",
                           plugin_id, action_type, reason, extra={"event": "plugin_permission_denied"})
            return [{"plugin": plugin_id, "action": action_type, "ok": False, "denied": True,
                     "error": reason}]
        try:
            result = await self._run_action(plugin_id, action_type, payload)
            return [{"plugin": plugin_id, "action": action_type, "ok": bool(result.get("ok", False)),
                     "denied": False, "result": result}]
        except Exception as e:  # noqa: BLE001 - action 异常不扩散
            logger.error("plugin_action_error id=%s action=%s reason=%s", plugin_id, action_type, e,
                         extra={"event": "plugin_error"})
            return [{"plugin": plugin_id, "action": action_type, "ok": False, "denied": False,
                     "error": f"{type(e).__name__}: {e}"}]


    # ---------- v2.1 缺口池：消息/好友语义（本地实现 + 受控 not supported） ----------
    _MSG_FRIEND_EXT = frozenset({"edit_message", "forward_message", "split_message",
                                        "merge_message", "favorite_message", "mark_message",
                                        "read_status", "search_message", "quote_chain",
                                        "friend_detail", "friend_remark", "friend_delete",
                                        "friend_group", "friend_category", "friend_online"})

    _GROUP_EXT = frozenset({"group_member_search", "group_member_update", "group_mute_status",
                            "group_title", "group_notice_create", "group_notice_update",
                            "group_file_upload", "group_file_rename", "group_essence",
                            "group_invite", "group_apply", "group_admins", "group_honor"})
    _EXT_NS = {"edit_message", "favorite_message", "mark_message", "read_status",
               "friend_remark", "friend_delete", "friend_group", "friend_category",
               "friend_online"}

    async def _ext_group(self, plugin_id: str, action: str, payload: dict) -> dict:
        """群语义：本地实现/等价别名/组合/明确 not supported。"""
        sender = getattr(self, "sender", None)
        # 等价别名（复用现有动作）
        alias = {"group_title": "group_title", "group_notice_create": "group_notice_send",
                 "group_essence": "essence_list", "group_honor": "group_honor",
                 "group_apply": "handle_group_request"}
        if action in alias:
            return await self._sender_forward(plugin_id, alias[action], payload)
        if action == "group_member_update":
            return await self._sender_forward(plugin_id, "group_card", payload)
        if action == "group_notice_update":
            # 组合语义：删除旧公告（如有 notice_id）+ 发送新公告
            if payload.get("notice_id"):
                await self._sender_forward(plugin_id, "group_notice_delete", payload)
            return await self._sender_forward(plugin_id, "group_notice_send", payload)
        if action == "group_member_search":
            try:
                rows = await sender.get_group_member_list(group_id=payload.get("group_id"))
                members = rows.get("data") or rows.get("members") or []
                q = str(payload.get("query") or "").lower()
                out = []
                for m in members:
                    if not q:
                        out.append(m)
                        continue
                    hay = " ".join(str(m.get(k, "")) for k in ("user_id", "nickname", "card"))
                    if q in hay.lower():
                        out.append(m)
                return {"ok": True, "results": out, "count": len(out)}
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": f"group_member_search: {type(e).__name__}: {e}"}
        if action == "group_admins":
            try:
                rows = await sender.get_group_member_list(group_id=payload.get("group_id"))
                members = rows.get("data") or rows.get("members") or []
                admins = [m for m in members if str(m.get("role", "")).lower() in ("admin", "owner")]
                return {"ok": True, "admins": admins, "count": len(admins)}
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": f"group_admins: {type(e).__name__}: {e}"}
        return {"ok": False, "error": f"{action}: 网关 v1 无对应端点（not supported）"}

    async def _ext_msg_friend(self, plugin_id: str, action: str, payload: dict) -> dict:
        """消息/好友缺口：可用=本地语义真实现；无端点=显式 not supported（绝不静默）。"""
        if action in self._EXT_NS:
            return {"ok": False, "error": f"{action}: 网关 v1 无对应端点（not supported）"}
        sender = getattr(self, "sender", None)
        if sender is None:
            return {"ok": False, "error": "sender 不可用"}
        if action == "forward_message":
            gid = payload.get("group_id")
            if not (gid or payload.get("user_id")):
                return {"ok": False, "error": "forward_message 需要 group_id 或 user_id"}
            p2 = dict(payload)
            if "messages" not in p2 and p2.get("text"):
                p2["messages"] = p2["text"]
            if "messages" not in p2:
                return {"ok": False, "error": "forward_message 需要 messages（或 text）"}
            if gid:
                return await self._sender_forward(plugin_id, "group_forward", p2)
            return await self._sender_forward(plugin_id, "user_forward", p2)
        if action == "split_message":
            text = str(payload.get("text") or "")
            limit = max(1, min(200, int(payload.get("limit", 2000) or 2000)))
            segs = []
            for i in range(0, len(text), limit):
                segs.append(text[i:i + limit])
            return {"ok": True, "segments": segs, "count": len(segs)}
        if action == "merge_message":
            segs = payload.get("segments") or payload.get("messages") or []
            if not isinstance(segs, list):
                return {"ok": False, "error": "merge_message 需要 segments 数组"}
            return {"ok": True, "text": "".join(str(x) for x in segs)}
        if action == "search_message":
            query = str(payload.get("query") or "")
            count = max(1, min(50, int(payload.get("count", 20) or 20)))
            gid, uid = payload.get("group_id"), payload.get("user_id")
            try:
                if gid:
                    rows = await sender.get_group_msg_history(group_id=gid, count=count)
                elif uid:
                    rows = await sender.get_friend_msg_history(user_id=uid, count=count)
                else:
                    return {"ok": False, "error": "search_message 需要 group_id 或 user_id"}
                messages = rows.get("messages") or rows.get("data") or []
                if query:
                    messages = [m for m in messages if query in str(m.get("message", "") or str(m))]
                return {"ok": True, "results": messages, "count": len(messages)}
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": f"search_message: {type(e).__name__}: {e}"}
        if action == "quote_chain":
            chain, mid = [], payload.get("message_id")
            for _ in range(3):
                if not mid:
                    break
                try:
                    got = await sender.get_msg(message_id=int(mid))
                    data = got.get("message") if isinstance(got, dict) else got
                    if not data:
                        break
                    chain.append({"message_id": mid, "message": data})
                    mid = data.get("quote_id") if isinstance(data, dict) else None
                except Exception:  # noqa: BLE001
                    break
            return {"ok": True, "chain": chain, "depth": len(chain)}
        if action == "friend_detail":
            uid = payload.get("user_id")
            try:
                rows = await sender.get_friend_list()
                friends = rows.get("data") or rows.get("friends") or []
                for f in friends:
                    if str(f.get("user_id")) == str(uid):
                        return {"ok": True, "friend": f}
                return {"ok": False, "error": "未找到该好友"}
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "error": f"friend_detail: {type(e).__name__}: {e}"}
        return {"ok": False, "error": f"{action}: 未知语义"}

    async def _run_action(self, plugin_id: str, action_type: str, payload: Dict[str, Any]) -> dict:
        """action 具体实现（按类型；全部结果回传插件，不执行任何未实现动作）。"""
        if action_type in _SENDER_ACTIONS:
            return await self._sender_forward(plugin_id, action_type, payload)
        if action_type in self._MSG_FRIEND_EXT:
            return await self._ext_msg_friend(plugin_id, action_type, payload)
        if action_type in self._GROUP_EXT:
            return await self._ext_group(plugin_id, action_type, payload)
        if action_type == "test":
            return {"ok": True, "plugin": plugin_id}
        if action_type == "log":
            level = str(payload.get("level") or "info")[:16]
            message = str(payload.get("message") or "")[:500]
            logger.info("plugin_log id=%s level=%s message=%s", plugin_id, level, message,
                        extra={"event": "plugin_log"})
            return {"ok": True}
        if action_type in ("send_message", "send_private_message", "send_reply"):
            # 消息发送三者共用：message 支持 str（含 [CQ:...]）或 OneBot 段数组 list
            group_id = payload.get("group_id")
            user_id = payload.get("user_id")
            message = payload.get("message")
            reply_id = payload.get("reply_id")
            if action_type == "send_private_message":
                target, target_id = "private", user_id
            else:
                target, target_id = "group", group_id
            if not target_id or not message:
                return {"ok": False, "error": f"{action_type} 需要目标与 message"}
            if self.sender is None:
                return {"ok": False, "error": "sender 未注入（不可用）"}
            result = await self.sender.send_msg_raw(target, int(target_id), message, reply_id=reply_id)
            if isinstance(message, str):
                result.setdefault("raw_text", str(message)[:2000])
            if result.get("ok") and result.get("message_id"):
                self._sent_message_ids.append(int(result["message_id"]))
                if len(self._sent_message_ids) > 200:  # 只保留最近 200 条（撤回窗口）
                    self._sent_message_ids = self._sent_message_ids[-200:]
            return {"ok": bool(result.get("ok")), "target": target, "target_id": int(target_id),
                    "message_id": result.get("message_id"),
                    "raw_text": result.get("raw_text", str(message)[:2000] if isinstance(message, str) else "")}
        if action_type == "delete_message":
            # 撤回：只允许撤回本 bot 发送过（且由本实例记录）的消息
            message_id = payload.get("message_id")
            if message_id is None:
                return {"ok": False, "error": "delete_message 需要 message_id"}
            if int(message_id) not in self._sent_message_ids:
                return {"ok": False, "denied": True,
                        "error": "只能撤回本 bot 发送的消息（message_id 未被记录）"}
            if self.sender is None:
                return {"ok": False, "error": "sender 未注入（不可用）"}
            ok = await self.sender.delete_msg(int(message_id))
            if ok:
                try:
                    self._sent_message_ids.remove(int(message_id))
                except ValueError:
                    pass
            return {"ok": ok, "message_id": int(message_id)}
        if action_type == "get_message":
            message_id = payload.get("message_id")
            if message_id is None or self.sender is None:
                return {"ok": False, "error": "get_message 需要 message_id（或 sender 不可用）"}
            return await self.sender.get_msg(int(message_id))
        if action_type == "get_group_history":
            group_id = payload.get("group_id")
            count = int(payload.get("count") or 15)
            if not group_id or self.sender is None:
                return {"ok": False, "error": "get_group_history 需要 group_id（或 sender 不可用）"}
            return await self.sender.get_group_msg_history(int(group_id), count)
        if action_type == "get_context":
            # 群上下文：最近 10 条（与主进程上下文同理的轻量版）
            group_id = payload.get("group_id")
            if not group_id or self.sender is None:
                return {"ok": False, "error": "get_context 需要 group_id（或 sender 不可用）"}
            return await self.sender.get_group_msg_history(int(group_id), 10)
        if action_type == "get_group":
            group_id = payload.get("group_id")
            if not group_id:
                return {"ok": False, "error": "get_group 需要 group_id"}
            info = self._state_lookup("group", int(group_id)) or {}
            return {"ok": True, "group_id": int(group_id), "info": info}
        if action_type == "get_user":
            user_id = payload.get("user_id")
            if not user_id:
                return {"ok": False, "error": "get_user 需要 user_id"}
            info = self._state_lookup("user", int(user_id)) or {}
            return {"ok": True, "user_id": int(user_id), "info": info}
        if action_type == "get_group_member":
            group_id, user_id = payload.get("group_id"), payload.get("user_id")
            if not group_id or not user_id or self.sender is None:
                return {"ok": False, "error": "get_group_member 需要 group_id 与 user_id（或 sender 不可用）"}
            return await self.sender.get_group_member_info(int(group_id), int(user_id))
        if action_type == "get_group_members":
            group_id = payload.get("group_id")
            if not group_id or self.sender is None:
                return {"ok": False, "error": "get_group_members 需要 group_id（或 sender 不可用）"}
            return await self.sender.get_group_member_list(int(group_id))
        if action_type == "group_ban":
            group_id, user_id = payload.get("group_id"), payload.get("user_id")
            duration = int(payload.get("duration") or 0)
            if not group_id or not user_id or self.sender is None:
                return {"ok": False, "error": "group_ban 需要 group_id 与 user_id（或 sender 不可用）"}
            if duration < 0 or duration > 30 * 24 * 3600:
                return {"ok": False, "error": "group_ban duration 0~2592000 秒"}
            ok = await self.sender.set_group_ban(int(group_id), int(user_id), duration)
            return {"ok": ok, "group_id": int(group_id), "user_id": int(user_id), "duration": duration}
        if action_type == "group_kick":
            group_id, user_id = payload.get("group_id"), payload.get("user_id")
            reject_add = bool(payload.get("reject_add", False))
            if not group_id or not user_id or self.sender is None:
                return {"ok": False, "error": "group_kick 需要 group_id 与 user_id（或 sender 不可用）"}
            ok = await self.sender.set_group_kick(int(group_id), int(user_id), reject_add)
            return {"ok": ok, "group_id": int(group_id), "user_id": int(user_id)}
        if action_type == "group_admin":
            group_id, user_id = payload.get("group_id"), payload.get("user_id")
            enable = bool(payload.get("enable", False))
            if not group_id or not user_id or self.sender is None:
                return {"ok": False, "error": "group_admin 需要 group_id 与 user_id（或 sender 不可用）"}
            ok = await self.sender.set_group_admin(int(group_id), int(user_id), enable)
            return {"ok": ok, "group_id": int(group_id), "user_id": int(user_id), "enable": enable}
        if action_type == "matcher_register":
            # SDK matcher 注册（幂等）：插件上报匹配规则，主进程匹配后只投递命中事件
            raw = payload.get("matchers") or []
            if not isinstance(raw, list):
                return {"ok": False, "error": "matcher_register 需要 matchers 数组"}
            compiled, errors = [], []
            for i, m in enumerate(raw):
                try:
                    compiled.append(Matcher(
                        str(m.get("kind") or "keyword"), m.get("pattern"),
                        priority=int(m.get("priority") or 0),
                        block=bool(m.get("block", False)),
                        name=str(m.get("name") or f"m{i}"),
                        rule=_rule_from(m.get("rule") or {}),
                    ))
                except Exception as e:  # noqa: BLE001
                    errors.append(f"matcher[{i}]: {e}")
            if compiled:
                self._matchers[plugin_id] = compiled
            return {"ok": True, "count": len(compiled), "errors": errors}
        if action_type in ("is_group_admin", "is_group_owner"):
            group_id, user_id = payload.get("group_id"), payload.get("user_id")
            if not group_id or not user_id or self.sender is None:
                return {"ok": False, "error": f"{action_type} 需要 group_id 与 user_id（或 sender 不可用）"}
            info = await self.sender.get_group_member_info(int(group_id), int(user_id))
            role = str((info or {}).get("role") or "member")
            wanted = "owner" if action_type == "is_group_owner" else ("owner", "admin")
            return {"ok": True, "result": role in wanted}
        if action_type == "handle_friend_request":
            flag = str(payload.get("flag") or "")
            approve = bool(payload.get("approve", False))
            if not flag or self.sender is None:
                return {"ok": False, "error": "handle_friend_request 需要 flag（或 sender 不可用）"}
            ok = await self.sender.set_friend_add_request(flag, approve, str(payload.get("remark") or ""))
            return {"ok": ok, "flag": flag, "approve": approve}
        if action_type == "handle_group_request":
            flag = str(payload.get("flag") or "")
            approve = bool(payload.get("approve", False))
            if not flag or self.sender is None:
                return {"ok": False, "error": "handle_group_request 需要 flag（或 sender 不可用）"}
            ok = await self.sender.set_group_add_request(flag, approve, str(payload.get("reason") or ""))
            return {"ok": ok, "flag": flag, "approve": approve}
        if action_type == "schedule_register":
            # 轻量调度：interval（秒循环）/ delay（一次性延时）/ daily（HH:MM 每日）
            name = str(payload.get("name") or f"task{len(self._schedules) + 1}")[:50]
            kind = str(payload.get("kind") or "interval")
            when = payload.get("when")
            if kind == "interval":
                seconds = float(when or 60)
                if not (1 <= seconds <= 86400):
                    return {"ok": False, "error": "interval 必须 1~86400 秒"}
            elif kind == "delay":
                seconds = float(when or 0)
                if not (0 < seconds <= 86400 * 7):
                    return {"ok": False, "error": "delay 必须 0~604800 秒"}
            elif kind == "daily":
                if not re.match(r"^\d{2}:\d{2}$", str(when or "")):
                    return {"ok": False, "error": "daily 需要 HH:MM（如 09:30）"}
            else:
                return {"ok": False, "error": f"未知 schedule kind: {kind}"}
            # 同插件同名覆盖（幂等）
            for sid, sched in list(self._schedules.items()):
                if sched.get("plugin_id") == plugin_id and sched.get("name") == name:
                    await self._cancel_schedule(sid)
            sid = f"{plugin_id}:{name}"
            self._schedules[sid] = {"plugin_id": plugin_id, "name": name, "kind": kind,
                                    "when": when, "created": time.time()}
            task = asyncio_create_task(self._schedule_loop(sid, kind, when))
            self._schedule_tasks[sid] = task
            return {"ok": True, "schedule_id": sid, "name": name, "kind": kind}
        if action_type == "schedule_cancel":
            sid = str(payload.get("schedule_id") or "")
            sched = self._schedules.get(sid)
            if sched is None or sched.get("plugin_id") != plugin_id:
                return {"ok": False, "error": "schedule 不存在（或不属于本插件）"}
            await self._cancel_schedule(sid)
            return {"ok": True, "schedule_id": sid}
        if action_type == "schedule_list":
            mine = [{**s, "schedule_id": sid} for sid, s in self._schedules.items()
                    if s.get("plugin_id") == plugin_id]
            return {"ok": True, "schedules": mine}
        if action_type == "kv_get":
            key = str(payload.get("key") or "")
            if not key or len(key) > 128:
                return {"ok": False, "error": "kv_get 需要 key（≤128 字符）"}
            value = self.repository.get_plugin_kv(plugin_id, key)
            if value is None:
                return {"ok": True, "exists": False, "value": None}
            return {"ok": True, "exists": True, "value": value}
        if action_type in ("kv_set", "kv_delete"):
            key = str(payload.get("key") or "")
            if not key or len(key) > 128:
                return {"ok": False, "error": f"{action_type} 需要 key（≤128 字符）"}
            if action_type == "kv_set":
                value = payload.get("value")
                serialized = _json_dumps(value) if not isinstance(value, str) else value
                if len(serialized) > 64 * 1024:
                    return {"ok": False, "error": "kv 值过大（>64KB）"}
                self.repository.set_plugin_kv(plugin_id, key, serialized)
                return {"ok": True, "key": key}
            self.repository.delete_plugin_kv(plugin_id, key)
            return {"ok": True, "key": key}
        if action_type == "kv_list":
            items = self.repository.list_plugin_kv(plugin_id)
            return {"ok": True, "items": [{"key": k, "value": _json_loads(v)} for k, v in items]}
        if action_type == "ai_chat":
            user_message = str(payload.get("message") or "")[:2000]
            if not user_message:
                return {"ok": False, "error": "ai_chat 需要 message"}
            if self._ai_client is None:
                return {"ok": False, "error": "ai_chat 不可用（未注入 ai_client）"}
            try:
                reply = await self._ai_client.chat_once(
                    user_message=user_message, context="", custom_prompt=(
                        str(payload.get("system") or "")[:1000] or ""))
                return {"ok": True, "reply": str(reply or "")[:3000]}
            except Exception as e:  # noqa: BLE001 - AI 失败按错误回传
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        if action_type == "mem_update":
            user_id, group_id = payload.get("user_id"), payload.get("group_id")
            key = str(payload.get("key") or "")
            if not user_id or not group_id or not key or self.memory_manager is None:
                return {"ok": False, "error": "mem_update 需要 user_id/group_id/key（或 memory 不可用）"}
            await self.memory_manager.update_memory(int(user_id), int(group_id), key,
                                                    str(payload.get("value") or "")[:2000])
            return {"ok": True, "key": key}
        if action_type == "mem_clear":
            user_id, group_id = payload.get("user_id"), payload.get("group_id")
            if not user_id or not group_id or self.memory_manager is None:
                return {"ok": False, "error": "mem_clear 需要 user_id/group_id（或 memory 不可用）"}
            count = await self.memory_manager.clear_user_memory(int(user_id), int(group_id))
            return {"ok": True, "cleared": count}
        if action_type == "random_choice":
            choices = payload.get("choices") or []
            if not isinstance(choices, list) or not choices:
                return {"ok": False, "error": "random_choice 需要非空 choices 数组"}
            return {"ok": True, "choice": str(random.choice([str(c)[:200] for c in choices]))}
        if action_type == "random_int":
            low, high = int(payload.get("low") or 0), int(payload.get("high") or 100)
            if low > high:
                return {"ok": False, "error": "random_int 需要 low<=high"}
            return {"ok": True, "value": random.randint(low, min(high, low + 10_000_000))}
        if action_type == "now":
            return {"ok": True, "timestamp": time.time(),
                    "iso": datetime.now(timezone.utc).isoformat()}
        if action_type == "format_time":
            raw_ts = payload.get("timestamp")
            ts = float(raw_ts) if raw_ts is not None else time.time()
            fmt = str(payload.get("format") or "%Y-%m-%d %H:%M:%S")[:64]
            try:
                return {"ok": True, "text": datetime.fromtimestamp(ts).strftime(fmt)}
            except (ValueError, OverflowError):
                return {"ok": False, "error": "format_time 非法 timestamp/format"}
        if action_type in ("http_put", "http_delete", "http_head", "http_download"):
            return await self._http_ext(plugin_id, action_type, payload)
        if action_type == "get_group_info":
            group_id = payload.get("group_id")
            if not group_id:
                return {"ok": False, "error": "get_group_info 需要 group_id"}
            info = self._state_lookup("group", int(group_id)) or {}
            return {"ok": True, "group_id": int(group_id), "info": info}
        if action_type == "get_memory":
            user_id = payload.get("user_id")
            group_id = payload.get("group_id")
            if not user_id or not group_id or self.memory_manager is None:
                return {"ok": False, "error": "get_memory 需要 user_id 与 group_id（或 memory 不可用）"}
            mem = self.memory_manager.get_user_memory(int(user_id), int(group_id))
            if not isinstance(mem, dict):
                return {"ok": False, "error": "memory 不可用"}
            return {"ok": True, "memory": mem}
        if action_type == "write_memory":
            user_id = payload.get("user_id")
            group_id = payload.get("group_id")
            content = str(payload.get("content") or "")[:500]
            if not user_id or not group_id or not content or self.memory_manager is None:
                return {"ok": False, "error": "write_memory 需要 user_id/group_id/content"}
            safe = validate_memory_content(content)
            if safe is None:
                return {"ok": False, "error": "记忆内容被安全策略拒绝（防注入）"}
            await self.memory_manager.append_memory_text(
                int(user_id), int(group_id), safe, source_user=int(user_id),
                source_group=int(group_id), source_message_id=0, confidence="plugin")
            return {"ok": True}
        if action_type == "http_request":
            return await plugin_http_request(payload)
        if action_type == "file_read":
            rel = str(payload.get("path") or "").strip()
            return self._file_read(plugin_id, rel)
        if action_type == "file_write":
            rel = str(payload.get("path") or "").strip()
            data = str(payload.get("data") or "")[:256 * 1024]
            return self._file_write(plugin_id, rel, data)
        if action_type in ("execute_process", "webhook"):
            return {"ok": False, "error": f"action {action_type!r} 在 Plugin API v1 未实现（保留权限）"}
        return {"ok": False, "error": f"未知 action: {action_type!r}"}

    def _state_lookup(self, kind: str, ident: int) -> Optional[dict]:
        if self.state_provider is None:
            return None
        try:
            return self.state_provider(kind, ident) or None
        except Exception:  # noqa: BLE001
            return None

    async def _schedule_loop(self, sid: str, kind: str, when) -> None:
        """轻量调度执行：interval/delay/daily（asyncio Task；无第三方依赖）。"""
        import asyncio as _asyncio
        try:
            if kind == "delay":
                await _asyncio.sleep(float(when or 0))
                await self._dispatch_schedule(sid)
                # delay 一次性任务：触发即清理（interval/daily 保留）
                self._schedule_tasks.pop(sid, None)
                self._schedules.pop(sid, None)
            elif kind == "interval":
                seconds = float(when or 60)
                while sid in self._schedule_tasks:
                    await _asyncio.sleep(seconds)
                    if sid not in self._schedule_tasks:
                        break
                    await self._dispatch_schedule(sid)
            elif kind == "daily":
                hh, mm = str(when or "00:00").split(":")
                while sid in self._schedule_tasks:
                    now = datetime.now()
                    nxt = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
                    if nxt <= now:
                        nxt = nxt + timedelta(days=1)
                    await _asyncio.sleep(max(1.0, (nxt - now).total_seconds()))
                    if sid not in self._schedule_tasks:
                        break
                    await self._dispatch_schedule(sid)
        except _asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001 - 调度器异常不拖垮管理器
            return

    async def _dispatch_schedule(self, sid: str) -> None:
        sched = self._schedules.get(sid)
        if sched is None:
            return
        payload = {"kind": "schedule", "schedule_id": sid, "name": sched["name"],
                   "trigger": sched["kind"], "plugin_id": sched["plugin_id"],
                   "trace_id": ""}
        try:
            await self.dispatch_event("schedule", payload)
        except Exception:  # noqa: BLE001
            pass

    async def _cancel_schedule(self, sid: str) -> None:
        task = self._schedule_tasks.pop(sid, None)
        self._schedules.pop(sid, None)
        if task is not None:
            try:
                task.cancel()
            except Exception:  # noqa: BLE001
                pass

    def cancel_all_schedules(self) -> None:
        """shutdown 时清理全部调度器。"""
        for sid in list(self._schedule_tasks.keys()):
            task = self._schedule_tasks.pop(sid, None)
            if task is not None:
                task.cancel()
        self._schedules.clear()

    async def _http_ext(self, plugin_id: str, action_type: str, payload: dict) -> dict:
        """HTTP 扩展：PUT/DELETE/HEAD 与下载到插件目录（全部复用 http_action 防线）。

        - PUT/DELETE/HEAD：走 plugin_http_request（SSRF/DNS/头清理/大小上限/不重定向）
        - http_download：SSRF 校验后读取（≤10MB）写入插件目录（save_to 相对路径）
        """
        url = str(payload.get("url") or "")[:800]
        if not url or not (url.startswith("http://") or url.startswith("https://")):
            return {"ok": False, "error": "http 扩展需要 http(s) url"}
        from src.plugins.http_action import plugin_http_request
        if action_type in ("http_put", "http_delete", "http_head"):
            req_payload = {"url": url,
                           "method": {"http_put": "PUT", "http_delete": "DELETE",
                                      "http_head": "HEAD"}[action_type]}
            if payload.get("headers") is not None:
                req_payload["headers"] = payload["headers"]
            if payload.get("body") is not None:
                req_payload["body"] = str(payload["body"])[:200_000]
            if payload.get("json") is not None:
                req_payload["json"] = payload["json"]
            return await plugin_http_request(req_payload)
        # http_download：SSRF 双闸复用（字面量 + DNS 结果校验）
        import httpx

        from src.plugins.http_action import assert_ssrf_ok
        try:
            await assert_ssrf_ok(url)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"SSRF 防护拒绝: {e}"}
        rel = str(payload.get("save_to") or "download.bin")[:120]
        if not rel or ".." in rel.split("/") or rel.startswith("/") or "\\" in rel:
            return {"ok": False, "error": "save_to 必须是插件目录内相对路径"}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=5.0),
                                         follow_redirects=False) as client:
                async with client.get(url) as resp:
                    if resp.status_code != 200:
                        return {"ok": False, "error": f"HTTP {resp.status_code}"}
                    data = await resp.aread()
        except httpx.HTTPError as e:
            return {"ok": False, "error": f"下载失败: {type(e).__name__}"}
        if len(data) > 10 * 1024 * 1024:
            return {"ok": False, "error": "下载超过 10MB 上限"}
        base = os.path.realpath(os.path.join(self.plugin_dir, plugin_id))
        target = os.path.realpath(os.path.join(base, rel))
        if os.path.commonpath([base, target]) != base:
            return {"ok": False, "error": "save_to 路径越界"}
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            f.write(data)
        return {"ok": True, "bytes": len(data), "saved_to": rel}

    async def _sender_forward(self, plugin_id: str, action_type: str, payload: dict) -> dict:
        """语义化动作 → Sender 端点（参数白名单清洗；未实现端点返回明确错误）。"""
        entry, spec = _SENDER_ACTIONS[action_type]
        sender = getattr(self, "sender", None)
        if sender is None:
            return {"ok": False, "error": "sender 不可用"}
        # 网关回退：entry 可为 str（单一端点）或 list（按序尝试，支持度自动激活）
        names = [entry] if isinstance(entry, str) else list(entry)
        method = None
        for name in names:
            cand = getattr(sender, name, None)
            if cand is not None:
                method = cand
                break
        if method is None:
            return {"ok": False, "error": f"当前网关不支持该能力（{'/'.join(names)}）"}
        kw = {}
        for key, typ, backend_key in spec:
            val = payload.get(key)
            if key == "group_config_set" and backend_key == "group_id":
                val = payload.get("group_id")
            if val is None:
                continue
            if typ == "int":
                val = int(val)
            elif typ == "bool":
                val = bool(val)
            else:
                val = str(val)
            kw[backend_key] = val
        # group_config_set：payload 其余键透传（网关允许的配置键）
        if action_type == "group_config_set":
            for k, v in payload.items():
                if k not in ("group_id",) and not k.startswith("_"):
                    kw[k] = v
        try:
            result = await method(**kw)
        except TypeError as e:
            return {"ok": False, "error": f"参数错误: {e}"}
        if isinstance(result, dict):
            return result
        return {"ok": bool(result)}

    def _file_read(self, plugin_id: str, rel: str) -> dict:
        """filesystem_read：仅允许读取插件自身目录内的文件（真实路径校验）。"""
        base = os.path.realpath(os.path.join(self.plugin_dir, plugin_id))
        target = os.path.realpath(os.path.join(base, rel))
        if os.path.commonpath([base, target]) != base or not os.path.isfile(target):
            return {"ok": False, "error": "路径越界（仅允许插件目录内文件）"}
        if os.path.getsize(target) > 256 * 1024:
            return {"ok": False, "error": "文件过大（>256KB）"}
        try:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                return {"ok": True, "content": f.read()[:256 * 1024]}
        except OSError as e:
            return {"ok": False, "error": f"读取失败: {e}"}

    def _file_write(self, plugin_id: str, rel: str, data: str) -> dict:
        """filesystem_write：仅允许写入插件自身目录（真实路径校验 + 大小上限）。"""
        if not rel or ".." in rel.split("/") or rel.startswith("/") or "\\" in rel:
            return {"ok": False, "error": "路径越界（仅允许插件目录内相对路径）"}
        base = os.path.realpath(os.path.join(self.plugin_dir, plugin_id))
        target = os.path.realpath(os.path.join(base, rel))
        if os.path.commonpath([base, target]) != base:
            return {"ok": False, "error": "路径越界"}
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(data)
        return {"ok": True, "bytes": len(data.encode("utf-8"))}


def _json_dumps(value) -> str:
    import json as _j
    return _j.dumps(value, ensure_ascii=False)


def _json_loads(value: str):
    import json as _j
    try:
        return _j.loads(value)
    except Exception:  # noqa: BLE001
        return value


# ---------- v1.5：语义化动作 → Sender 端点方法 转发表（端点实现只在 Sender/下层） ----------
_SENDER_ACTIONS: Dict[str, tuple] = {
    # 动作名: (sender 方法, 参数白名单 [(payload键, 类型: "int"/"str"/"bool"/"any", 后端键)])
    "tap": ("send_poke", [("group_id", "int", "group_id"), ("user_id", "int", "user_id")]),
    "react": (["set_react", "set_group_reaction"],  # 网关回退：NapCat=set_react，Lagrange=set_group_reaction
              [("message_id", "int", "message_id"), ("react_type", "int", "react_type")]),
    # v1.7.0 拉格朗日补齐
    "user_history": ("get_friend_msg_history", [("user_id", "int", "user_id"), ("count", "int", "count")]),
    "user_forward": ("send_private_forward_msg", [("user_id", "int", "user_id"), ("messages", "any", "messages")]),
    "user_poke": ("friend_poke", [("user_id", "int", "user_id")]),
    "essence_list": ("get_essence_msg_list", [("group_id", "int", "group_id")]),
    "group_honor": ("get_group_honor_info", [("group_id", "int", "group_id"), ("honor_type", "str", "honor_type")]),
    "group_notice_delete": ("delete_group_notice", [("group_id", "int", "group_id"), ("notice_id", "str", "notice_id")]),
    "group_portrait": ("set_group_portrait", [("group_id", "int", "group_id"), ("file", "str", "file")]),
    "group_info": ("get_group_info", [("group_id", "int", "group_id"), ("no_cache", "bool", "no_cache")]),
    "group_list": ("get_group_list", [("no_cache", "bool", "no_cache")]),
    "group_forward": ("send_group_forward_msg", [("group_id", "int", "group_id"), ("messages", "any", "messages")]),
    "group_folder_create": ("create_group_file_folder", [("group_id", "int", "group_id"), ("name", "str", "name")]),
    "group_file_delete": ("delete_group_file", [("group_id", "int", "group_id"), ("file_id", "str", "file_id"), ("busid", "int", "busid")]),
    "group_folder_delete": ("delete_group_folder", [("group_id", "int", "group_id"), ("folder_id", "str", "folder_id")]),
    "group_file_move": ("move_group_file", [("group_id", "int", "group_id"), ("file_id", "str", "file_id"), ("busid", "int", "busid"), ("target_folder_id", "str", "target_folder_id")]),
    "group_folder_rename": ("rename_group_file_folder", [("group_id", "int", "group_id"), ("folder_id", "str", "folder_id"), ("name", "str", "name")]),
    "pin": ("set_essence_msg", [("message_id", "int", "message_id")]),
    "unpin": ("delete_essence_msg", [("message_id", "int", "message_id")]),
    "like": ("set_friend_profile_like", [("user_id", "int", "user_id")]),
    "friends": ("get_friend_list", []),
    "login_info": ("get_login_info", []),
    "devices": ("get_online_clients", []),
    "status": ("get_status", []),
    "profile_set": ("set_qq_profile", [("nickname", "str", "nickname"), ("signature", "str", "signature")]),
    "group_whole_ban": ("set_group_whole_ban", [("group_id", "int", "group_id"), ("enable", "bool", "enable")]),
    "group_rename": ("set_group_name", [("group_id", "int", "group_id"), ("name", "str", "name")]),
    "group_card": ("set_group_card", [("group_id", "int", "group_id"), ("user_id", "int", "user_id"), ("card", "str", "card")]),
    "group_title": ("set_group_special_title", [("group_id", "int", "group_id"), ("user_id", "int", "user_id"), ("title", "str", "title")]),
    "group_notice_send": ("send_group_notice", [("group_id", "int", "group_id"), ("content", "str", "content"), ("image", "str", "image")]),
    "group_notice_get": ("get_group_notice", [("group_id", "int", "group_id")]),
    "group_files": ("get_group_root_files", [("group_id", "int", "group_id")]),
    "group_files_in": ("get_group_files_by_folder", [("group_id", "int", "group_id"), ("folder_id", "str", "folder_id")]),
    "group_file_url": ("get_group_file_url", [("group_id", "int", "group_id"), ("file_id", "str", "file_id"), ("busid", "int", "busid")]),
    "group_config": ("get_group_config", [("group_id", "int", "group_id")]),
    "group_config_set": ("set_group_config", [("group_id", "int", "group_id")]),  # 其余键透传
    "group_res": ("get_group_res", [("group_id", "int", "group_id"), ("res_type", "str", "group_res")]),
}


def _rule_from(conditions: dict):
    """SDK rule 条件 dict → Rule 对象（用户/群/机器人角色条件）。"""
    from src.sdk.matcher import Rule
    return Rule(**dict(conditions or {}))


def asyncio_create_task(coro) -> None:
    """兼容无事件循环上下文（_stop_runtime 可能被同步调用）。"""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # 无运行中的循环：直接丢弃（进程即将退出场景）
    loop.create_task(coro)
