# -*- coding: utf-8 -*-
"""Flowerie SDK 缺口层（v2.1）：上下文对象 / 分面客户端 / 任务管理器 / 组合器 / 明确 NS。

设计：
  · 所有对象零依赖（标准库），与 bot.py 门面同构——转发到 FlowerieBot 已有方法
  · 本地可实现的能力（任务/会话/翻译/mock/过滤）为真实现
  · 主进程网关不支持的（WS/SSE/中间件）→ 显式 PluginFeatureError（绝不静默）
  · 分面：bot.ai / bot.memory / bot.mcp / bot.db / bot.cache / bot.task / bot.runtime /
    bot.metrics / bot.media / bot.i18n / bot.config / bot.mock
"""
import asyncio
import json
import os
import threading
import time
from typing import Any, Dict, List, Optional


class PluginFeatureError(RuntimeError):
    """v1 明确不支持的插件能力（调用时抛出，绝不静默降级）。"""


# ---------------- 消息段 / 过滤器（真实现） ----------------

def seg_text(text: str) -> dict:
    return {"type": "text", "data": {"text": str(text)}}


def seg_image(file: str) -> dict:
    return {"type": "image", "data": {"file": str(file)}}


def seg_at(user_id: int) -> dict:
    return {"type": "at", "data": {"qq": str(user_id)}}


def seg_face(id: int) -> dict:
    return {"type": "face", "data": {"id": str(id)}}


def seg_reply(message_id: int) -> dict:
    return {"type": "reply", "data": {"id": str(message_id)}}


class MessageSegment:
    """消息段工厂（等价 OneBot segment 结构；组合成消息列表）。"""

    text = staticmethod(seg_text)
    image = staticmethod(seg_image)
    at = staticmethod(seg_at)
    face = staticmethod(seg_face)
    reply = staticmethod(seg_reply)


class MessageFilter:
    """消息过滤（纯本地）：按文本/类型/目录条件过滤段或消息。"""

    def __init__(self, where: Optional[dict] = None):
        self.where = where or {}

    def apply(self, items: List[Any]) -> List[Any]:
        out = []
        for it in items:
            if isinstance(it, dict):
                text = str(it.get("text", "") or "")
                if all(str(it.get(k)) == str(v) for k, v in self.where.items()
                       if k != "text_contains"):
                    if self.where.get("text_contains") in ("", None) \
                            or self.where["text_contains"] in text:
                        out.append(it)
        return out


# ---------------- 上下文对象（真实现：数据 + 方法转发） ----------------

class _Ctx:
    def __init__(self, bot, **data):
        self.bot = bot
        self.data = dict(data)

    def __repr__(self):
        return f"<{type(self).__name__} {self.data}>"


class FriendContext(_Ctx):
    """好友上下文：详情/备注/删除/在线（网关能力自动降级为明确错误）。"""

    def detail(self):
        return self.bot.friend_detail(self.data.get("user_id"))

    def remark(self, text):
        return self.bot.friend_remark(self.data.get("user_id"), text)

    def delete(self):
        return self.bot.friend_delete(self.data.get("user_id"))

    def online(self):
        return self.bot.friend_online(self.data.get("user_id"))


class GroupMemberContext(_Ctx):
    def search(self, query=""):
        return self.bot.group_member_search(self.data.get("group_id"), query)

    def title(self, user_id, title):
        return self.bot.group_title(self.data.get("group_id"), user_id, title)

    def mute_status(self, user_id):
        return self.bot.group_mute_status(self.data.get("group_id"), user_id)


class ReactionContext(_Ctx):
    def react(self, react_type):
        return self.bot.reaction(self.data.get("message_id"), react_type)

    def list(self):
        return self.bot.emoji_list(self.data.get("message_id"))


class SessionContext(_Ctx):
    """会话上下文（群/私聊）：记忆读写 + 上下文取用。"""

    def remember(self, text):
        return self.bot.memory_update({"user_id": self.data.get("user_id"),
                                       "group_id": self.data.get("group_id"), "text": text})

    def recall(self, query, top_k=3):
        return self.bot.memory_search(query, self.data.get("group_id", 0), top_k)

    def context(self):
        return self.bot.get_context({"user_id": self.data.get("user_id"),
                                     "group_id": self.data.get("group_id")}) \
            if hasattr(self.bot, "_api") else None


class Conversation:
    """会话管理器：跟踪多轮会话（本地 + 记忆桥接）。"""

    def __init__(self, bot):
        self.bot = bot
        self._rounds: Dict[Any, list] = {}

    def session(self, key) -> SessionContext:
        return SessionContext(self.bot, key=key,
                              group_id=(key if isinstance(key, int) else None))

    def add_round(self, key, line):
        self._rounds.setdefault(key, []).append(str(line))
        self._rounds[key] = self._rounds[key][-20:]

    def history(self, key):
        return list(self._rounds.get(key, []))


class FriendRequest(_Ctx):
    """好友申请（approve/deny）。"""

    def approve(self, remark=""):
        return self.bot.handle_friend_request({"flag": self.data.get("flag"),
                                               "approve": True, "remark": remark})

    def deny(self):
        return self.bot.handle_friend_request({"flag": self.data.get("flag"),
                                               "approve": False})


class GroupRequest(_Ctx):
    def approve(self, reason=""):
        return self.bot.handle_group_request({"flag": self.data.get("flag"),
                                              "approve": True, "reason": reason})

    def deny(self):
        return self.bot.handle_group_request({"flag": self.data.get("flag"),
                                              "approve": False})


class FileContext(_Ctx):
    """文件上下文：上传/下载/信息/删除（安全闸门走主进程）。"""

    def upload(self, name, data):
        return self.bot.file_upload(name, data)

    def download(self, name):
        return self.bot.file_download(name)

    def info(self, name=None):
        return self.bot.file_info(name or self.data.get("name"))

    def delete(self, name=None):
        return self.bot.file_delete(name or self.data.get("name"))


class MediaContext(_Ctx):
    def info(self, name):
        ext = "." + str(name).rsplit(".", 1)[-1].lower()
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            return self.bot.file_info(name)
        if ext in (".mp3", ".m4a", ".wav", ".flac"):
            return self.bot.audio_info(name)
        return self.bot.video_info(name)


# ---------------- 任务管理器（真实现：插件进程内 asyncio） ----------------

class TaskHandle:
    """任务句柄（concurrent.futures.Future 包装；跨线程兼容插件同步上下文）。"""

    def __init__(self, task_id: str, name: str, future, manager=None):
        self.task_id = task_id
        self.name = name
        self._future = future
        self._manager = manager
        self._paused = threading.Event()
        self._paused.set()
        self.started_at = time.time()

    @property
    def done(self):
        return self._future.done()

    @property
    def cancelled(self):
        return self._future.cancelled()

    def pause(self):
        self._paused.clear()
        return {"ok": True, "paused": self.task_id}

    def resume(self):
        self._paused.set()
        return {"ok": True, "resumed": self.task_id}

    def cancel(self):
        self._future.cancel()
        return {"ok": True, "cancelled": self.task_id}

    def wait(self, timeout=None):
        return self._future.result(timeout=timeout)

    def status(self) -> dict:
        return {"task_id": self.task_id, "name": self.name,
                "done": self.done, "cancelled": self.cancelled,
                "paused": not self._paused.is_set(),
                "uptime_s": int(time.time() - self.started_at)}


class _LoopManager:
    """专用后台事件循环（插件同步上下文也能跑后台任务）。"""

    def __init__(self):
        self._loop = None
        self._thread = None

    def _ensure(self):
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._loop.run_forever,
                                            daemon=True, name="flowerie-task-loop")
            self._thread.start()
        return self._loop

    def submit(self, coro):
        loop = self._ensure()
        return asyncio.run_coroutine_threadsafe(coro, loop)

    def call(self, coro):
        loop = self._ensure()
        return asyncio.run_coroutine_threadsafe(coro, loop)


class TaskManager(_LoopManager):
    """插件任务注册表：submit/status/cancel/pause/resume（真；专用后台 loop）。"""

    def __init__(self, bot=None):
        super().__init__()
        self.bot = bot
        self._tasks: Dict[str, TaskHandle] = {}

    def submit(self, name: str, coro, task_id: Optional[str] = None) -> TaskHandle:
        tid = task_id or f"{name}-{int(time.time() * 1000) % 100000}"
        if not asyncio.iscoroutine(coro):

            async def _wrap_call(fn):
                return fn()

            coro = _wrap_call(coro)
        async def _guarded():
            h0 = self._tasks.get(tid)
            if h0 is not None:
                await asyncio.to_thread(h0._paused.wait)
            return await coro
        future = super().submit(_guarded())
        h = TaskHandle(tid, name, future, manager=self)
        self._tasks[tid] = h
        return h

    def _lookup(self, task_id: str):
        h = self._tasks.get(task_id)
        if h is None:
            for t in self._tasks.values():
                if t.name == task_id:
                    h = t
                    break
        return h

    def status(self, task_id: str) -> dict:
        h = self._lookup(task_id)
        if h is None:
            return {"ok": False, "error": "任务不存在"}
        return {"ok": True, **h.status()}

    def cancel(self, task_id: str) -> dict:
        h = self._lookup(task_id)
        if h is None:
            return {"ok": False, "error": "任务不存在"}
        return h.cancel()

    def pause(self, task_id: str) -> dict:
        h = self._lookup(task_id)
        if h is None:
            return {"ok": False, "error": "任务不存在"}
        return h.pause()

    def resume(self, task_id: str) -> dict:
        h = self._lookup(task_id)
        if h is None:
            return {"ok": False, "error": "任务不存在"}
        return h.resume()

    def list(self) -> list:
        return [h.status() for h in self._tasks.values()]


# ---------------- I18n（真：插件 i18n/<lang>.json） ----------------

class I18n:
    def __init__(self, bot=None, base_dir: str = "", default_lang: str = "zh"):
        self.bot = bot
        self.base_dir = base_dir
        self.lang = default_lang
        self._cache: Dict[str, dict] = {}

    def set_lang(self, lang: str) -> None:
        self.lang = lang

    def _load(self, lang: str) -> dict:
        if lang in self._cache:
            return self._cache[lang]
        path = os.path.join(self.base_dir, "i18n", f"{lang}.json")
        data = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                got = json.load(f)
                if isinstance(got, dict):
                    data = got
        except (OSError, ValueError):
            pass
        self._cache[lang] = data
        return data

    def t(self, key: str, **kwargs) -> str:
        text = self._load(self.lang).get(key)
        if text is None:
            text = self._load("zh").get(key, key)
        try:
            return str(text).format(**kwargs) if kwargs else str(text)
        except (KeyError, IndexError):
            return str(text)


# ---------------- 分面客户端（转发到 FlowerieBot） ----------------

class _Facade:
    def __init__(self, bot):
        self.bot = bot


class AiFacade(_Facade):
    def chat(self, prompt, **kw):
        return self.bot.ai_stream(prompt=prompt, **kw)

    stream = chat
    vision = lambda self, url, q="": self.bot.ai_vision(url, q)  # noqa: E731
    embedding = lambda self, text: self.bot.ai_embedding(text)  # noqa: E731
    rerank = lambda self, q, docs: self.bot.ai_rerank(q, docs)  # noqa: E731
    token = lambda self, text: self.bot.ai_token(text)  # noqa: E731
    models = lambda self: self.bot.ai_models()  # noqa: E731
    model_info = lambda self, k: self.bot.ai_model_info(k)  # noqa: E731
    usage = lambda self: self.bot.ai_usage()  # noqa: E731
    budget = lambda self: self.bot.ai_budget()  # noqa: E731


class MemoryFacade(_Facade):
    get = lambda self, **kw: self.bot.memory_get(**kw)  # noqa: E731
    search = lambda self, q, g=0, k=3: self.bot.memory_search(q, g, k)  # noqa: E731
    semantic = lambda self, q, g=0, k=3: self.bot.memory_semantic(q, g, k)  # noqa: E731
    update = lambda self, **kw: self.bot.memory_update(**kw)  # noqa: E731
    delete = lambda self, key: self.bot.memory_delete(key)  # noqa: E731
    tag = lambda self, n, v="1": self.bot.memory_tag(n, v)  # noqa: E731
    pin = lambda self, k: self.bot.memory_pin(k)  # noqa: E731
    expire = lambda self, k=None, d=30: self.bot.memory_expire(k, d)  # noqa: E731


class McpFacade(_Facade):
    servers = lambda self: self.bot.mcp_server()  # noqa: E731
    tools = lambda self: self.bot.mcp_tools()  # noqa: E731
    call = lambda self, s, t, a=None: self.bot.mcp_call(s, t, a)  # noqa: E731
    resource = lambda self, s, u: self.bot.mcp_resource(s, u)  # noqa: E731
    prompt = lambda self, s, n, a=None: self.bot.mcp_prompt(s, n, a)  # noqa: E731
    status = lambda self, s: self.bot.mcp_status(s)  # noqa: E731


class DbFacade(_Facade):
    query = lambda self, w=None, limit=50, o=0: self.bot.db_query(w, limit, o)  # noqa: E731
    transaction = lambda self, ops: self.bot.db_transaction(ops)  # noqa: E731
    migration = lambda self, v: self.bot.db_migration(v)  # noqa: E731
    index = lambda self, f: self.bot.db_index(f)  # noqa: E731


class CacheFacade(_Facade):
    get = lambda self, k: self.bot.cache_get(k)  # noqa: E731
    set = lambda self, k, v: self.bot.cache_set(k, v)  # noqa: E731
    delete = lambda self, k: self.bot.cache_delete(k)  # noqa: E731


class RuntimeFacade(_Facade):
    usage = lambda self: self.bot.resource_usage()  # noqa: E731
    quota = lambda self: self.bot.resource_quota()  # noqa: E731
    status = lambda self: self.bot.runtime_status()  # noqa: E731


class MetricsFacade(_Facade):
    snapshot = lambda self: self.bot.metrics()  # noqa: E731
    trace = lambda self, tid: self.bot.trace(tid)  # noqa: E731
    health = lambda self: self.bot.health()  # noqa: E731


class MediaFacade(_Facade):
    file = lambda self, n=None: FileContext(self.bot, name=n)  # noqa: E731
    info = lambda self, n: MediaContext(self.bot).info(n)  # noqa: E731


class MockFacade:
    """测试 mock：轻量 fixture（真；只用于插件自测）。"""

    def __init__(self, bot=None):
        self.bot = bot
        self._fixtures: Dict[str, Any] = {}

    def set(self, key, value):
        self._fixtures[key] = value
        return {"ok": True, "set": key}

    def get(self, key):
        return {"ok": True, "value": self._fixtures.get(key)}

    def clear(self):
        self._fixtures.clear()
        return {"ok": True}


class ConfigFacade:
    """插件配置（自身 manifest config + 插件空间 config.json 覆盖）。"""

    def __init__(self, bot, base_dir: str = ""):
        self.bot = bot
        self.base_dir = base_dir
        self._override_path = os.path.join(base_dir, "config.json")

    def get(self, key=None, default=None):
        mf = self.bot.plugin_config() if self.bot and hasattr(self.bot, "_api") else None
        data = dict((mf or {}).get("config") or {}) if isinstance(mf, dict) else {}
        try:
            with open(self._override_path, "r", encoding="utf-8") as f:
                data.update(json.load(f))
        except (OSError, ValueError):
            pass
        if key is None:
            return data
        return data.get(key, default)

    def set(self, key, value):
        data = self.get()
        data[key] = value
        with open(self._override_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return {"ok": True, "key": key}


# ---------------- 明确 NS（v1 不支持；抛 PluginFeatureError，绝不静默） ----------------

class WebSocketServer:
    def __init__(self, *a, **k):
        raise PluginFeatureError("WebSocket Server：v1 明确不支持（零 JS+安全红线）")


class SseServer:
    def __init__(self, *a, **k):
        raise PluginFeatureError("SSE：v1 明确不支持（零 JS 红线；轮询替代）")


class HttpMiddleware:
    def __init__(self, *a, **k):
        raise PluginFeatureError("HTTP Middleware：主进程专属（v1 不支持插件中间件）")


class PluginDependency:
    """插件依赖查询（等价 plugin_dependency/plugin_discovery 读取）。"""

    def __init__(self, bot):
        self.bot = bot

    def declared(self):
        return self.bot.plugin_dependency()

    def peers(self):
        return self.bot.plugin_discovery()


class PluginEventBus:
    """插件事件总线（发布/订阅；投递走主进程 plugin_call/plugin_event）。"""

    def __init__(self, bot):
        self.bot = bot

    def publish(self, name, data=None, target=""):
        return self.bot.plugin_event(name, data, target)

    def call(self, target, name="", data=None):
        return self.bot.plugin_call(target, name, data)


class PluginServiceBus:
    """插件服务总线：register（主进程表）+ call（目标插件事件投递）。"""

    def __init__(self, bot):
        self.bot = bot

    def register(self, name, desc=""):
        return self.bot.plugin_service("register", name=name, desc=desc)

    def call(self, target, name="", data=None):
        return self.bot.plugin_service("call", name=name, target=target, data=data)


class PluginRpc:
    pass  # 与 PluginEventBus.call 同源（快捷别名见 bot.sdk.rpc）


def build_sdk(bot, base_dir: str = "") -> dict:
    """组装全部缺口 SDK 分面（bot.sdk.ai / .memory / ...）。"""
    task = TaskManager(bot)
    return {
        "ai": AiFacade(bot), "memory": MemoryFacade(bot), "mcp": McpFacade(bot),
        "db": DbFacade(bot), "cache": CacheFacade(bot), "runtime": RuntimeFacade(bot),
        "metrics": MetricsFacade(bot), "media": MediaFacade(bot), "mock": MockFacade(bot),
        "i18n": I18n(bot, base_dir), "config": ConfigFacade(bot, base_dir),
        "task": task, "tasks": task,
        "conversation": Conversation(bot),
        "events": PluginEventBus(bot), "services": PluginServiceBus(bot),
        "dependency": PluginDependency(bot),
    }
