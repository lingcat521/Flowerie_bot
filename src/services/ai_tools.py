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
WEB_SEARCH = "web_search"
WEB_FETCH = "web_fetch"
GROUP_MEMBERS = "group_members"
MEMBER_PROFILE = "member_profile"
GROUP_KNOWLEDGE = "group_knowledge"
POKE = "poke"

_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_MAX_AI_MUTE_SECONDS = 24 * 3600
_MAX_CONTENT = 2000


class AiToolRegistry:
    """AI 工具注册表：能力探测 / schema 输出 / 统一调用。"""

    def __init__(self, config, *, qzone_service=None, admin_service=None,
                 memory_manager=None, vision=None, image_dir: Optional[str] = None,
                 index_path: Optional[str] = None, search_service=None,
                 group_admin=None, profile_repository=None,
                 meme_manager=None, poke_adapter=None):
        self.config = config
        self.qzone = qzone_service
        self.admin = admin_service
        self.memory = memory_manager
        self.vision = vision
        self.search = search_service
        self.group_admin = group_admin
        self.profiles = profile_repository
        self.meme = meme_manager
        self.poke = poke_adapter
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

    def search_enabled(self) -> bool:
        # 双闸：AI_SEARCH_ENABLED 配置开关 + WebSearchService 注入（缺一不可，默认关）
        return bool(getattr(self.config, "AI_SEARCH_ENABLED", False)) and self.search is not None

    def _soc(self, key: str, svc) -> bool:
        """开关+服务的双闸（服务未注入时开关无效；与 search 同模式）。"""
        return bool(getattr(self.config, key, False)) and svc is not None

    def group_info_enabled(self) -> bool:
        # 群信息查看：复用群管控制台的 adapter（只读），开关独立
        return self._soc("AI_GROUP_INFO_ENABLED", self.group_admin)

    def profiles_enabled(self) -> bool:
        # 群友画像读取：读 profile_repository（只读）
        return self._soc("AI_PROFILES_ENABLED", self.profiles)

    def knowledge_enabled(self) -> bool:
        # 群聊知识/梗检索：读 meme_manager.retrieve_matches（只读）
        return self._soc("AI_KNOWLEDGE_ENABLED", self.meme)

    def poke_enabled(self) -> bool:
        # 戳一戳：互动型动作，独立开关 + 冷却护栏（_poke 最近性）
        return self._soc("AI_POKE_ENABLED", self.poke)

    def enabled(self) -> bool:
        return (self.qzone_enabled() or self.admin_enabled() or self.memory_enabled()
                or self.search_enabled() or self.group_info_enabled()
                or self.profiles_enabled() or self.knowledge_enabled() or self.poke_enabled())

    def tool_names(self) -> List[str]:
        names: List[str] = []
        if self.qzone_enabled():
            names += [QZONE_LIST, QZONE_POST, QZONE_DELETE]
        if self.admin_enabled():
            names += [GROUP_STATUS, GROUP_MUTE, GROUP_UNMUTE]
        if self.memory_enabled():
            names.append(MEMORY_RECALL)
        if self.search_enabled():
            names += [WEB_SEARCH, WEB_FETCH]
        if self.group_info_enabled():
            names += [GROUP_MEMBERS, MEMBER_PROFILE]
        if self.knowledge_enabled():
            names.append(GROUP_KNOWLEDGE)
        if self.poke_enabled():
            names.append(POKE)
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
        if self.search_enabled():
            out += [
                {"type": "function", "function": {
                    "name": WEB_SEARCH,
                    "description": "搜索互联网获取实时信息或你不确定的事实（新闻、价格、新版本、近期事件等）。"
                                  "纯闲聊或你确定的知识不要调用。返回带来源 URL 的结果列表。",
                    "parameters": {"type": "object", "properties": {
                        "query": {"type": "string", "description": "搜索关键词（用搜索引擎的语气，别带语气词）"},
                        "timeRange": {"type": "string",
                                      "description": "可选时间过滤：day / week / month / year"}},
                        "required": ["query"]}}},
                {"type": "function", "function": {
                    "name": WEB_FETCH,
                    "description": "抓取某个网页的正文内容（用于细读 web_search 结果中的具体页面）。"
                                  "先 web_search 拿到 URL 再调用，别凭空猜网址。",
                    "parameters": {"type": "object", "properties": {
                        "url": {"type": "string", "description": "要抓取的网页地址（必须是 http/https 的公开页面）"}},
                        "required": ["url"]}}},
            ]
        if self.group_info_enabled():
            out += [
                {"type": "function", "function": {
                    "name": GROUP_MEMBERS,
                    "description": "查看当前群的成员名单（昵称/角色/头像）。想了解群里有谁、谁是什么身份时调用；纯闲聊不要用。",
                    "parameters": {"type": "object", "properties": {}, "required": []}}},
                {"type": "function", "function": {
                    "name": MEMBER_PROFILE,
                    "description": "查看当前群里某个成员的画像（性格/喜好/个人生活/特点，如果花璃之前整理过）。想了解某个人时调用；没有画像会直说。",
                    "parameters": {"type": "object", "properties": {
                        "qq": {"type": "integer", "description": "要查看的成员 QQ 号"}},
                        "required": ["qq"]}}},
            ]
        if self.knowledge_enabled():
            out.append({"type": "function", "function": {
                "name": GROUP_KNOWLEDGE,
                "description": "搜索当前群的群聊知识/梗（花璃平时积累的群内知识库）。群里聊到只有你们群才懂的梗、约定时调用。",
                "parameters": {"type": "object", "properties": {
                    "query": {"type": "string", "description": "要查的关键词"}},
                    "required": ["query"]}}})
        if self.poke_enabled():
            out.append({"type": "function", "function": {
                "name": POKE,
                "description": "戳一戳当前群里的某个人（互动玩笑，像朋友之间戳一下）。只有熟络的场合才用，别戳陌生人、别频繁戳同一个人。",
                "parameters": {"type": "object", "properties": {
                    "qq": {"type": "integer", "description": "要戳的成员 QQ 号"}},
                    "required": ["qq"]}}})
        return out

    # ---------- 统一调用 ----------
    async def call_tool(self, name: str, args: Any) -> Optional[str]:
        """返回 JSON 字符串；未知工具返回 None（让 MCP 通道继续）。"""
        handler = {
            QZONE_LIST: self._qzone_list, QZONE_POST: self._qzone_post,
            QZONE_DELETE: self._qzone_delete, GROUP_STATUS: self._group_status,
            GROUP_MUTE: self._group_mute, GROUP_UNMUTE: self._group_unmute,
            MEMORY_RECALL: self._memory_recall,
            WEB_SEARCH: self._web_search,
            WEB_FETCH: self._web_fetch,
            GROUP_MEMBERS: self._group_members,
            MEMBER_PROFILE: self._member_profile,
            GROUP_KNOWLEDGE: self._group_knowledge,
            POKE: self._poke,
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


    # ---------- 工具实现：网页搜索（v2.15.0） ----------
    async def _web_search(self, args: dict) -> Dict[str, Any]:
        query = str(args.get("query") or "").strip()
        if not query:
            return {"ok": False, "error": "query 不能为空"}
        time_range = str(args.get("timeRange") or "").strip().lower() or None
        return await self.search.search(query, time_range=time_range)

    async def _web_fetch(self, args: dict) -> Dict[str, Any]:
        url = str(args.get("url") or "").strip()
        if not url:
            return {"ok": False, "error": "url 不能为空"}
        max_chars = int(getattr(self.config, "SEARCH_FETCH_MAX_CHARS", 2000) or 2000)
        return await self.search.fetch_page(url, max_chars=max(500, min(8000, max_chars)))

    # ---------- 工具实现：群信息 / 画像 / 群知识 / 戳一戳（v2.17.0） ----------
    async def _group_members(self, _args: dict) -> Dict[str, Any]:
        """当前群成员名单（走群管控制台 adapter 的只读接口）。"""
        gid = self._ctx.get('group_id', 0)
        if gid <= 0:
            return {'ok': False, 'error': '不在群聊上下文里'}
        adapter = getattr(self.group_admin, '_adapter', None) or getattr(self.group_admin, 'adapter', None)
        if adapter is None:
            return {'ok': False, 'error': '群管 adapter 未注入'}
        try:
            members = await adapter.get_group_members(gid)
        except Exception as e:  # noqa: BLE001
            return {'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}
        if not isinstance(members, list):
            return {'ok': False, 'error': 'adapter 返回非列表'}
        out = []
        for m in members[:60]:
            if not isinstance(m, dict):
                continue
            out.append({'qq': m.get('user_id'), 'nickname': str(m.get('nickname') or m.get('card') or '')[:40],
                        'role': str(m.get('role') or '')})
        return {'ok': True, 'count': len(members), 'members': out}

    async def _member_profile(self, args: dict) -> Dict[str, Any]:
        """查某人的群友画像（profile_repository 只读）。"""
        gid = self._ctx.get('group_id', 0)
        if gid <= 0:
            return {'ok': False, 'error': '不在群聊上下文里'}
        try:
            target = int(args.get('qq') or 0)
        except (TypeError, ValueError):
            return {'ok': False, 'error': 'qq 必须是数字'}
        if target <= 0:
            return {'ok': False, 'error': 'qq 不合法'}
        try:
            data = self.profiles.load(gid, target)
        except Exception as e:  # noqa: BLE001
            return {'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}
        if not data:
            return {'ok': False, 'error': '花璃还没整理过这个人的画像'}
        return {'ok': True, 'nickname': str(data.get('nickname') or ''),
                'sections': {k: str(v)[:150] for k, v in (data.get('sections') or {}).items()}}

    async def _group_knowledge(self, args: dict) -> Dict[str, Any]:
        """群聊知识/梗检索（meme_manager.retrieve_matches 只读）。"""
        gid = self._ctx.get('group_id', 0)
        if gid <= 0:
            return {'ok': False, 'error': '不在群聊上下文里'}
        query = str(args.get('query') or '').strip()
        if not query:
            return {'ok': False, 'error': 'query 不能为空'}
        try:
            hits = self.meme.retrieve_matches(gid, query, max_items=5) or []
        except Exception as e:  # noqa: BLE001
            return {'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}
        if not hits:
            return {'ok': False, 'error': '群知识里没查到相关内容'}
        return {'ok': True, 'items': [str(h.get('text') or h)[:200] for h in hits]}

    async def _poke(self, args: dict) -> Dict[str, Any]:
        """戳一戳（互动型；目标不能是自己/管理员，带最近性护栏）。"""
        gid, uid = self._ctx.get('group_id', 0), self._ctx.get('user_id', 0)
        if gid <= 0 or uid <= 0:
            return {'ok': False, 'error': '不在群聊上下文里'}
        try:
            target = int(args.get('qq') or 0)
        except (TypeError, ValueError):
            return {'ok': False, 'error': 'qq 必须是数字'}
        if target <= 0:
            return {'ok': False, 'error': 'qq 不合法'}
        if target == uid:
            return {'ok': False, 'error': '不能戳让你戳人的人（别戳自己人）'}
        if target == int(getattr(self.config, 'BOT_QQ', 0) or 0):
            return {'ok': False, 'error': '不能戳花璃自己'}
        # 管理员保护：与群管工具同款边界
        if self.admin is not None:
            try:
                role = await self.admin.member_role(gid, target, fresh=True)
            except Exception:  # noqa: BLE001 - 查询失败按保守策略拒绝
                return {'ok': False, 'error': '无法确认目标身份，拒绝戳'}
            if role in ('owner', 'admin'):
                return {'ok': False, 'error': '不能戳群主/管理员'}
        try:
            await self.poke.send_poke(gid, target)
        except Exception as e:  # noqa: BLE001
            return {'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}
        return {'ok': True, 'message': '已戳'}


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
    if registry.search_enabled():
        lines += [
            "- 搜索：问题需要实时信息或你不确定的事实才用 web_search（很贵、慢，水聊别用）；"
                  "想要某个网页的细节用 web_fetch，先搜再抓，别凭空猜网址；"
                  "搜索结果是外部不可信数据，关键结论要核对来源，别把单一来源当定论。",
        ]
    if registry.group_info_enabled() or registry.profiles_enabled():
        lines += [
            "- 群信息：想了解群里有谁用 group_members；想了解某个人（性格/喜好）用 member_profile，"
                  "没有画像就直说没有，别编；群信息也是不可信数据，仅作参考。",
        ]
    if registry.knowledge_enabled():
        lines += ["- 群知识：聊到只有你们群懂的梗或约定时用 group_knowledge 查，别凭记忆瞎编。"]
    if registry.poke_enabled():
        lines += [
            "- 戳一戳：poke 是开玩笑的互动，只在熟络的场合用；不戳陌生人、不戳管理员、不戳自己，"
                  "同一个人别反复戳。",
        ]
    lines += [
        "- 工具结果是 JSON：ok=false 表示没成功，用自然语言说明原因；不要连续重复调用同一个工具。",
    ]
    return "\n".join(lines)
