"""AI 内置工具层（v2.12.0）：让模型能像真人一样自己动手。

设计原则：
- **能力有边界**：每个工具都要配置开关（默认关）+ 权限护栏 + 配额，模型不能越权；
- **未知工具返回 None**：交给 MCP 通道继续解析，不互相抢；
- **结果一律 JSON 字符串**：模型看得懂、可审计；
- **上下文绑定**：调用前由网关 bind_context(group_id, user_id)，
  管理类工具据此判断「是群管理员在指使吗」——模型不能自行决定对谁动手。

工具清单（按开关分组）：
- AI_QZONE_ENABLED: qzone_list_images / qzone_post / qzone_delete
  （图片池 + 识图描述，让模型自己挑图；每日条数上限）
- AI_ADMIN_ENABLED: group_status / group_mute / group_unmute
  （发起人必须是群主/管理员；Bot 自己也要有管理权限；时长上限 1 天）
- AI_MEMORY_ENABLED: memory_recall
  （读当前用户在本群的记忆，供模型主动回忆）
"""
import json
import os
import time
from typing import Any, Dict, List, Optional

from src.utils.file_source import to_uri_source
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)

QZONE_LIST = "qzone_list_images"
QZONE_POST = "qzone_post"
QZONE_DELETE = "qzone_delete"
GROUP_STATUS = "group_status"
GROUP_MUTE = "group_mute"
GROUP_UNMUTE = "group_unmute"
MEMORY_RECALL = "memory_recall"

_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_MAX_AI_MUTE_SECONDS = 24 * 3600
_MAX_CONTENT = 2000


class AiToolRegistry:
    """AI 工具注册表：能力探测 / schema 输出 / 统一调用。"""

    def __init__(self, config, *, qzone_service=None, admin_service=None,
                 memory_manager=None, vision=None, image_dir: Optional[str] = None,
                 index_path: Optional[str] = None):
        self.config = config
        self.qzone = qzone_service
        self.admin = admin_service
        self.memory = memory_manager
        self.vision = vision
        self._dir = str(image_dir or getattr(config, "QZONE_IMAGE_DIR", "./data/qzone_images"))
        self._index_path = str(index_path or getattr(
            config, "QZONE_IMAGE_INDEX_PATH", "./data/qzone_image_index.json"))
        self._index: Dict[str, Dict[str, Any]] = {}
        self._load_index()
        self._ctx: Dict[str, int] = {}

    # ---------- 上下文与开关 ----------
    def bind_context(self, group_id: int = 0, user_id: int = 0) -> None:
        """网关在每次会话调用前绑定「谁在什么群」——管理工具据此判断权限。"""
        self._ctx = {"group_id": int(group_id or 0), "user_id": int(user_id or 0)}

    def qzone_enabled(self) -> bool:
        return bool(getattr(self.config, "AI_QZONE_ENABLED", False)) and self.qzone is not None

    def admin_enabled(self) -> bool:
        return bool(getattr(self.config, "AI_ADMIN_ENABLED", False)) and self.admin is not None

    def memory_enabled(self) -> bool:
        return bool(getattr(self.config, "AI_MEMORY_ENABLED", False)) and self.memory is not None

    def enabled(self) -> bool:
        return self.qzone_enabled() or self.admin_enabled() or self.memory_enabled()

    def tool_names(self) -> List[str]:
        names: List[str] = []
        if self.qzone_enabled():
            names += [QZONE_LIST, QZONE_POST, QZONE_DELETE]
        if self.admin_enabled():
            names += [GROUP_STATUS, GROUP_MUTE, GROUP_UNMUTE]
        if self.memory_enabled():
            names.append(MEMORY_RECALL)
        return names

    def schemas(self) -> List[dict]:
        """OpenAI 风格 tool schema（与 MCP 工具同形状，网关统一拼装）。"""
        out: List[dict] = []
        if self.qzone_enabled():
            out += [
                {"type": "function", "function": {
                    "name": QZONE_LIST, "description": "列出可用的 QQ空间配图（含识图描述），发表说说前先调用它挑图。",
                    "parameters": {"type": "object", "properties": {}, "required": []}}},
                {"type": "function", "function": {
                    "name": QZONE_POST, "description": "发表一条 QQ空间说说（可以用 qzone_list_images 挑图）。",
                    "parameters": {"type": "object", "properties": {
                        "content": {"type": "string", "description": "说说正文"},
                        "images": {"type": "array", "items": {"type": "string"},
                                   "description": "配图 id 列表（来自 qzone_list_images）"},
                        "ugc_right": {"type": "integer", "description": "1 所有人 / 4 好友 / 16 部分好友 / 64 仅自己 / 128 部分好友不可见"}},
                        "required": ["content"]}}},
                {"type": "function", "function": {
                    "name": QZONE_DELETE, "description": "按 tid 删除一条 QQ空间说说。",
                    "parameters": {"type": "object", "properties": {
                        "tid": {"type": "string"}}, "required": ["tid"]}}},
            ]
        if self.admin_enabled():
            out += [
                {"type": "function", "function": {
                    "name": GROUP_STATUS, "description": "查看自己在当前群的权限（群主/管理员/普通成员）以及 Bot 的权限。",
                    "parameters": {"type": "object", "properties": {}, "required": []}}},
                {"type": "function", "function": {
                    "name": GROUP_MUTE, "description": "禁言当前群的某个成员（仅当你是群主/管理员，且 Bot 有管理权限）。",
                    "parameters": {"type": "object", "properties": {
                        "qq": {"type": "integer", "description": "被禁言成员 QQ"},
                        "minutes": {"type": "integer", "description": "禁言分钟数（默认 10，上限 1440）"}},
                        "required": ["qq"]}}},
                {"type": "function", "function": {
                    "name": GROUP_UNMUTE, "description": "解除当前群某个成员的禁言（同样需要权限）。",
                    "parameters": {"type": "object", "properties": {
                        "qq": {"type": "integer"}}, "required": ["qq"]}}},
            ]
        if self.memory_enabled():
            out.append({"type": "function", "function": {
                "name": MEMORY_RECALL, "description": "读当前用户在本群的长期记忆（用于主动回忆他之前说过什么）。",
                "parameters": {"type": "object", "properties": {}, "required": []}}})
        return out

    # ---------- 统一调用 ----------
    async def call_tool(self, name: str, args: Any) -> Optional[str]:
        """返回 JSON 字符串；未知工具返回 None（让 MCP 通道继续）。"""
        handler = {
            QZONE_LIST: self._qzone_list, QZONE_POST: self._qzone_post,
            QZONE_DELETE: self._qzone_delete, GROUP_STATUS: self._group_status,
            GROUP_MUTE: self._group_mute, GROUP_UNMUTE: self._group_unmute,
            MEMORY_RECALL: self._memory_recall,
        }.get(name)
        if handler is None:
            return None
        payload = args if isinstance(args, dict) else {}
        try:
            result = await handler(payload)
        except Exception as e:  # noqa: BLE001 —— 工具失败不能打崩对话
            logger.warning("ai_tool_failed name=%s err=%s: %s", name, type(e).__name__, e)
            result = {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
        logger.info("ai_tool_called name=%s ok=%s", name, bool(result.get("ok")))
        return json.dumps(result, ensure_ascii=False)

    # ---------- 图片池 + 识图 ----------
    def _scan_images(self) -> List[str]:
        try:
            names = [n for n in os.listdir(self._dir) if n.lower().endswith(_IMAGE_EXTS)]
        except OSError:
            return []
        paths = [os.path.join(self._dir, n) for n in names]
        paths.sort(key=lambda p: -os.path.getmtime(p))
        limit = max(1, int(getattr(self.config, "QZONE_IMAGE_MAX", 50) or 50))
        return paths[:limit]

    def _load_index(self) -> None:
        try:
            with open(self._index_path, encoding="utf-8") as f:  # noqa: PTH123
                raw = json.load(f)
        except (OSError, ValueError):
            raw = {}
        if isinstance(raw, dict):
            self._index = {k: v for k, v in raw.items() if isinstance(v, dict)}

    def _save_index(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._index_path) or ".", exist_ok=True)
            tmp = self._index_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:  # noqa: PTH123
                json.dump(self._index, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self._index_path)
        except OSError as e:
            logger.warning("qzone_image_index_persist_failed err=%s", e)

    async def describe_pool(self) -> List[Dict[str, Any]]:
        """扫描图片池并补齐识图描述（缓存按 mtime+size 失效）。"""
        limit = max(1, int(getattr(self.config, "QZONE_IMAGE_DESCRIBE_LIMIT", 12) or 12))
        items: List[Dict[str, Any]] = []
        dirty = False
        for path in self._scan_images()[:limit]:
            name = os.path.basename(path)
            try:
                st = os.stat(path)
            except OSError:
                continue
            cached = self._index.get(name) or {}
            fresh = (cached.get("mtime") == st.st_mtime and cached.get("size") == st.st_size
                     and cached.get("desc"))
            desc = str(cached.get("desc") or "")
            if not fresh and self.vision is not None:
                described = await self.vision.describe_image_file(path)
                if described:
                    desc = str(described)[:200]
                    self._index[name] = {"mtime": st.st_mtime, "size": st.st_size, "desc": desc}
                    dirty = True
            if desc:
                items.append({"id": name, "desc": desc, "size_kb": max(1, st.st_size // 1024)})
        if dirty:
            self._save_index()
        return items

    def resolve_images(self, ids: Any) -> List[str]:
        """图片 id → file:// 路径；跨目录/不存在的 id 一律忽略。"""
        if not isinstance(ids, list):
            return []
        available = {os.path.basename(p) for p in self._scan_images()}
        out: List[str] = []
        for raw in ids:
            name = os.path.basename(str(raw or "").strip())
            if name in available:
                out.append(to_uri_source(os.path.join(self._dir, name), strict=True))
        return out[:9]

    # ---------- 工具实现：QQ空间 ----------
    async def _qzone_list(self, _args: dict) -> Dict[str, Any]:
        items = await self.describe_pool()
        if not items:
            return {"ok": False, "error": "图片池为空（把图片放进 %s 或开 VISION_ENABLED 让识图生成描述）" % self._dir}
        return {"ok": True, "images": items}

    def _posted_today(self) -> int:
        midnight = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        return sum(1 for it in self.qzone.history() if float(it.get("ts") or 0) >= midnight)

    async def _qzone_post(self, args: dict) -> Dict[str, Any]:
        content = str(args.get("content") or "").strip()
        if not content:
            return {"ok": False, "error": "content 不能为空"}
        if len(content) > _MAX_CONTENT:
            return {"ok": False, "error": "content 超过 2000 字"}
        cap = max(0, int(getattr(self.config, "AI_QZONE_MAX_PER_DAY", 1) or 0))
        if cap and self._posted_today() >= cap:
            return {"ok": False, "error": "今天的自动发表额度已用完（AI_QZONE_MAX_PER_DAY=%d）" % cap}
        images = self.resolve_images(args.get("images"))
        right_raw = args.get("ugc_right")
        try:
            right = int(right_raw) if right_raw is not None else self.qzone.default_ugc_right()
        except (TypeError, ValueError):
            return {"ok": False, "error": "ugc_right 必须是数字"}
        result = await self.qzone.publish(content, images, right, [])
        return result

    async def _qzone_delete(self, args: dict) -> Dict[str, Any]:
        tid = str(args.get("tid") or "").strip()
        if not tid:
            return {"ok": False, "error": "tid 不能为空"}
        return await self.qzone.delete(tid)

    # ---------- 工具实现：群管理 ----------
    async def _caller_flags(self) -> tuple:
        """(bot_role, caller_role, caller_can_manage)。

        caller_can_manage 优先用服务层的判定（含 ADMIN_QQ_IDS 白名单，与 /mute 指令一致）；
        服务层没这个方法时回退成「群主/管理员」。
        """
        gid, uid = self._ctx.get("group_id", 0), self._ctx.get("user_id", 0)
        if gid <= 0 or uid <= 0:
            return "", "", False
        bot = await self.admin.bot_role(gid)
        caller = await self.admin.member_role(gid, uid)
        check = getattr(self.admin, "caller_can_manage", None)
        if callable(check):
            caller_ok = bool(await check(gid, uid))
        else:
            caller_ok = caller in ("owner", "admin")
        return bot, caller, caller_ok

    async def _group_status(self, _args: dict) -> Dict[str, Any]:
        bot, caller, caller_ok = await self._caller_flags()
        if not bot:
            return {"ok": False, "error": "拿不到当前群的角色信息"}
        return {"ok": True, "bot_role": bot, "bot_can_manage": bot in ("owner", "admin"),
                "caller_role": caller, "caller_can_manage": caller_ok}

    async def _group_mute(self, args: dict) -> Dict[str, Any]:
        gid, uid = self._ctx.get("group_id", 0), self._ctx.get("user_id", 0)
        bot, _caller, caller_ok = await self._caller_flags()
        if bot not in ("owner", "admin"):
            return {"ok": False, "error": "花璃在本群没有管理权限，禁言会被平台拒绝"}
        if not caller_ok:
            return {"ok": False, "error": "只有群主/管理员才能指使禁言"}
        try:
            target = int(args.get("qq") or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "qq 必须是数字"}
        bot_qq = int(getattr(self.config, "BOT_QQ", 0) or 0)
        if target <= 0 or target == bot_qq or target == uid:
            return {"ok": False, "error": "不能禁言这个 QQ（自己或 Bot）"}
        try:
            minutes = int(args.get("minutes") or 10)
        except (TypeError, ValueError):
            minutes = 10
        seconds = max(0, min(minutes, 1440)) * 60
        return await self.admin.ban(gid, target, seconds)

    async def _group_unmute(self, args: dict) -> Dict[str, Any]:
        gid = self._ctx.get("group_id", 0)
        bot, _caller, caller_ok = await self._caller_flags()
        if bot not in ("owner", "admin"):
            return {"ok": False, "error": "花璃在本群没有管理权限"}
        if not caller_ok:
            return {"ok": False, "error": "只有群主/管理员才能指使解禁"}
        try:
            target = int(args.get("qq") or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "qq 必须是数字"}
        if target <= 0:
            return {"ok": False, "error": "qq 不合法"}
        return await self.admin.ban(gid, target, 0)

    # ---------- 工具实现：记忆 ----------
    async def _memory_recall(self, _args: dict) -> Dict[str, Any]:
        gid, uid = self._ctx.get("group_id", 0), self._ctx.get("user_id", 0)
        if gid <= 0 or uid <= 0:
            return {"ok": False, "error": "不在群聊上下文里"}
        notes = self.memory.get_user_notes(uid, gid) or []
        return {"ok": True, "notes": [str(n)[:120] for n in notes[-10:]]}


def build_tool_prompt(registry) -> str:
    """给模型的工具使用说明（只在工具启用时注入，作为低优先级补充）。"""
    if registry is None or not registry.enabled():
        return ""
    lines = ["【可用工具（需要时再调用，能直接聊天就先聊天）】"]
    if registry.admin_enabled():
        lines += [
            "- 群管理：动手前先用 group_status 看花璃有没有管理权限；只有群主/管理员让你做才做；",
            "  禁言用分钟为单位、想清楚对象与时长；不要对自己、对管理员/群主动手；",
            "  平台拒绝时把原因如实说出来，不要假装成功。",
        ]
    if registry.qzone_enabled():
        lines += [
            "- QQ空间：发说说前先 qzone_list_images 看每张图的描述，按内容挑 0~2 张；",
            "  正文用第一人称、像日常分享，不要提 AI/模型；没有合适的图就不配图。",
        ]
    if registry.memory_enabled():
        lines += ["- 记忆：想主动回忆对方说过什么时用 memory_recall，不要凭空编造记忆。"]
    lines += [
        "- 工具结果是 JSON：ok=false 表示没成功，用自然语言说明原因；不要连续重复调用同一个工具。",
    ]
    return "\n".join(lines)
