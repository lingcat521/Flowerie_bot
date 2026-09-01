"""插件侧 FlowerieBot：SDK 模式入口。

用法（插件 plugin.py）：
    from flowerie_sdk import FlowerieBot, command
    bot = FlowerieBot()

    @command("hello")
    async def hello(event):
        await event.reply("你好")

    def on_startup(context, api=None):
        bot.attach(api)
        bot.register()          # 上报 matchers（一次性）

    def on_message(event, api=None):
        return bot.route(event)  # SDK 路由；无匹配返回 None
"""
from typing import Any, Dict, List, Optional

from flowerie_sdk.event import BotEvent
from flowerie_sdk.matcher import collect
from flowerie_sdk.message import BotMessage


class FlowerieBot:
    def __init__(self):
        self._api = None
        self._handlers: List[tuple] = []  # (matcher定义, handler)
        self._listeners: Dict[str, List[tuple]] = {}  # kind -> [(priority, stop, handler)]
        self._waiters: List[dict] = []   # 等待中的消息（wait_for/ask/confirm/select）
        self._schedules: List[tuple] = []  # (name, kind, when, handler) 待注册
        self._cooldowns: Dict[str, float] = {}  # key -> last mark 时间戳
        self._registered_schedules: List[tuple] = []  # (name, kind, when, schedule_id)
        self._matched_name = ""
        self._last_args = ""
        self._registered = False
        self._module = None

    # ---------- 生命周期 ----------
    def attach(self, api, module=None) -> None:
        """绑定 api；默认自动识别调用方（插件入口）模块用于 matcher 收集。"""
        self._api = api
        if module is None:
            import inspect
            for f in inspect.stack()[2:]:
                g = f.frame.f_globals
                mod_name = str(g.get("__name__") or "")
                if not mod_name.startswith("flowerie_sdk"):
                    self._module = g  # 插件模块命名空间（f_globals）
                    break
        else:
            self._module = getattr(module, "__dict__", module) if not isinstance(module, dict) else module

    def register(self) -> Optional[dict]:
        """收集插件模块级 matcher handlers 并上报主进程（幂等）。"""
        if self._api is None or self._registered:
            return None
        import inspect
        if self._module is not None:
            items = (self._module.items() if isinstance(self._module, dict) else vars(self._module).items())
            for _name, val in list(items):
                if inspect.isfunction(val):
                    for m in collect(val):
                        self._handlers.append((m, val))
        if not self._handlers:
            import sys
            for _, mod in list(sys.modules.items()):
                if mod is not None and "flowerie_plugin_" in getattr(mod, "__name__", ""):
                    for _name, val in vars(mod).items():
                        if inspect.isfunction(val):
                            for m in collect(val):
                                self._handlers.append((m, val))
        if self._schedules:
            self._collect_schedules()
        if not self._handlers:
            return None
        matchers = [{"kind": m["kind"], "pattern": m["pattern"], "priority": m["priority"],
                     "block": m["block"], "name": m["name"], "rule": m.get("rule")}
                    for m, _ in self._handlers]
        try:
            result = self._api.matcher_register(matchers)
        except Exception:  # noqa: BLE001 - 权限不足降级：不阻断插件启动
            result = {"ok": False, "error": "matcher register failed"}
        self._registered = True
        return result

    def listen(self, post_type: str, priority: int = 0, stop: bool = False):
        """@bot.listen("notice")——本地事件监听（主进程全量投递时过滤分发）。"""
        def wrap(func):
            self._listeners.setdefault(post_type, []).append((priority, stop, func))
            return func
        return wrap

    # ---------- 路由 ----------
    async def route(self, event_dict: Dict[str, Any]):
        """事件入口（插件 on_message/on_notice 调用）：先喂等待队列，再按 matched/监听器分发。

        返回 actions 结果列表（SDK 模式下通常为空=无动作回传）。
        """
        # 等待队列先行（wait_for/ask 不依赖 api；未 attach 也可 receive）
        event = BotEvent(event_dict, self)
        await self._feed_waiters(event)
        if self._api is None:
            return None
        matched = event_dict.get("matched") or {}
        if isinstance(matched, list):
            matched = matched[0] if matched else {}   # 主进程按 priority 降序；命中链第一优先
        self._matched_name = str(matched.get("name") or "")
        self._last_args = str(matched.get("args") or "")
        if self._matched_name:
            for m, handler in self._handlers:
                if self._matched_name == m.get("name"):
                    await self._invoke(handler, event)
                    break
        else:
            listeners = sorted(self._listeners.get(event.kind, []),
                               key=lambda x: x[0], reverse=True)
            for _priority, stop, handler in listeners:
                if event._stopped:
                    break
                try:
                    await self._invoke(handler, event)
                except Exception:  # noqa: BLE001 - 监听器异常隔离
                    continue
                if stop or event._stopped:
                    break
        return None

    async def route_schedule(self, event_dict: Dict[str, Any]) -> None:
        """定时任务事件（on_schedule 钩子）→ 按 name 分发到 @bot.schedule handler。"""
        name = str((event_dict or {}).get("name") or "")
        for sched in self._schedules:   # (name, kind, when, func)
            if sched[0] == name:
                await self._invoke_schedule(sched[3], event_dict)
                return

    # ---------- 等待消息 / Session（插件侧轻量实现；勿与 matcher 同一插件混用） ----------
    async def wait_for(self, condition, timeout: float = 60.0):
        """等待下一条满足 condition(event)->bool 的消息（超时返回 None）。

        需要插件**不注册 matcher**（否则只收匹配事件，wait_for 会饿死）。
        """
        import asyncio
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        waiter = {"cond": condition, "fut": fut}
        self._waiters.append(waiter)
        try:
            return await asyncio.wait_for(fut, timeout=float(timeout or 60))
        except asyncio.TimeoutError:
            return None
        finally:
            if waiter in self._waiters:
                self._waiters.remove(waiter)

    async def ask(self, event, prompt, timeout: float = 60.0) -> Optional[str]:
        """提问并等待回答（发送 prompt；下一消息视为回答）。"""
        await self.reply(event, prompt)
        return await self.wait_for(
            lambda ev: ev.scope == event.scope
            and ev.group_id == getattr(event, "group_id", None)
            and ev.user_id == getattr(event, "user_id", None)
            and ev.text and ev.text.strip() != "",
            timeout=timeout)

    async def confirm(self, event, prompt, timeout: float = 60.0) -> bool:
        """Ask + 是/否解析（是/好/可以/对/确定=真；否/不要/不行/取消=假）。"""
        reply_text = await self.ask(event, prompt, timeout=timeout)
        if reply_text is None:
            return False
        t = str(reply_text).strip().lower()
        if t in ("是", "好", "可以", "对", "确定", "yes", "y", "ok", "1"):
            return True
        if t in ("否", "不要", "不行", "取消", "no", "n", "0"):
            return False
        return False

    async def select(self, event, prompt, options, timeout: float = 60.0):
        """Ask + 选项匹配（返回选中项文本；未选返回 None）。选项可为文本或带答案的 dict。"""
        lines = "\n".join(f"{i + 1}. {o if isinstance(o, str) else o.get('label')}"
                           for i, o in enumerate(options))
        reply_text = await self.ask(event, f"{prompt}\n{lines}", timeout=timeout)
        if reply_text is None:
            return None
        t = str(reply_text).strip()
        if t.isdigit():
            idx = int(t) - 1
            if 0 <= idx < len(options):
                return options[idx] if isinstance(options[idx], str) else options[idx].get("answer")
        for o in options:
            label = o if isinstance(o, str) else o.get("label")
            if t == str(label):
                return o if isinstance(o, str) else o.get("answer")
        return None

    async def _feed_waiters(self, event) -> None:
        if not self._waiters:
            return
        for waiter in list(self._waiters):
            fut = waiter.get("fut")
            if fut is None or fut.done():
                self._waiters.remove(waiter)
                continue
            try:
                ok = waiter["cond"](event)
            except Exception:  # noqa: BLE001
                ok = False
            if ok and not fut.done():
                fut.set_result(event)
                self._waiters.remove(waiter)

    # ---------- 调度（轻量：interval/delay/daily；无第三方依赖） ----------
    # ---------- v2.1 缺口池：消息 / 好友 ----------
    def edit_message(self, message_id, **kw):
        """编辑已发送消息（网关支持时；否则返回 not supported）。"""
        return self._api.edit_message({"message_id": message_id, **kw}) if self._api else self._no_api()

    def forward_message(self, messages, group_id=None, user_id=None, text=None):
        """转发消息（messages=段列表或 text=纯文本；自动选群/私聊通道）。"""
        return self._api.forward_message({"messages": messages, "text": text,
                                          "group_id": group_id,
                                          "user_id": user_id}) if self._api else self._no_api()

    def split_message(self, text, limit=2000):
        """把长文本按 limit 拆段（纯本地；返回 segments 列表）。"""
        return self._api.split_message({"text": str(text), "limit": limit}) if self._api else self._no_api()

    def merge_message(self, segments):
        """段列表合并为文本。"""
        return self._api.merge_message({"segments": list(segments)}) if self._api else self._no_api()

    def favorite_message(self, message_id):
        """收藏消息（v1 网关可能不支持）。"""
        return self._api.favorite_message({"message_id": message_id}) if self._api else self._no_api()

    def mark_message(self, message_id, read=True):
        """标记消息已读/未读。"""
        return self._api.mark_message({"message_id": message_id, "read": read}) if self._api else self._no_api()

    def read_status(self, message_id=None):
        """会话/消息已读状态。"""
        return self._api.read_status({"message_id": message_id}) if self._api else self._no_api()

    def search_message(self, query="", group_id=None, user_id=None, count=20):
        """消息搜索（本地过滤历史；返回 results）。"""
        return self._api.search_message({"query": query, "group_id": group_id,
                                         "user_id": user_id, "count": count}) if self._api else self._no_api()

    def quote_chain(self, message_id, depth=3):
        """引用链（message_id 回溯，≤depth 层）。"""
        return self._api.quote_chain({"message_id": message_id, "depth": depth}) if self._api else self._no_api()

    def friend_detail(self, user_id):
        """好友详细信息。"""
        return self._api.friend_detail({"user_id": user_id}) if self._api else self._no_api()

    def friend_remark(self, user_id, remark):
        """设置好友备注。"""
        return self._api.friend_remark({"user_id": user_id, "remark": remark}) if self._api else self._no_api()

    def friend_delete(self, user_id):
        """删除好友。"""
        return self._api.friend_delete({"user_id": user_id}) if self._api else self._no_api()

    def friend_group(self, user_id=None, group_name=None):
        """好友分组管理。"""
        return self._api.friend_group({"user_id": user_id, "group_name": group_name}) if self._api else self._no_api()

    def friend_category(self, user_id=None, category=None):
        """好友分类（等价 friend_group）。"""
        return self._api.friend_category({"user_id": user_id, "category": category}) if self._api else self._no_api()

    def friend_online(self, user_id):
        """好友在线状态。"""
        return self._api.friend_online({"user_id": user_id}) if self._api else self._no_api()

    # ---------- v2.1 缺口池：Memory / MCP ----------
    def memory_get(self, **kw):
        """记忆读取（等价 get_memory）。"""
        return self._api.memory_get(kw) if self._api else self._no_api()

    def memory_search(self, query, group_id=0, top_k=3):
        """语义记忆检索（花语记忆相似度召回）。"""
        return self._api.memory_search({"query": query, "group_id": group_id,
                                        "top_k": top_k}) if self._api else self._no_api()

    def memory_semantic(self, query, group_id=0, top_k=3):
        """语义检索（等价 memory_search）。"""
        return self._api.memory_semantic({"query": query, "group_id": group_id,
                                          "top_k": top_k}) if self._api else self._no_api()

    def memory_update(self, **kw):
        """记忆更新（等价 write_memory）。"""
        return self._api.memory_update(kw) if self._api else self._no_api()

    def memory_delete(self, key):
        """记忆删除（KV 域）。"""
        return self._api.memory_delete({"key": key}) if self._api else self._no_api()

    def memory_tag(self, name, value="1"):
        """记忆标签（tag: 前缀 KV）。"""
        return self._api.memory_tag({"name": name,
                                     "value": value}) if self._api else self._no_api()

    def memory_pin(self, key):
        """记忆置顶（网关需支持）。"""
        return self._api.memory_pin({"key": key}) if self._api else self._no_api()

    def memory_expire(self, key=None, days=30):
        """记忆过期查询（网关需支持）。"""
        return self._api.memory_expire({"key": key,
                                        "days": days}) if self._api else self._no_api()

    def mcp_server(self):
        """MCP 服务器列表。"""
        return self._api.mcp_server({}) if self._api else self._no_api()

    def mcp_tools(self):
        """MCP 工具清单。"""
        return self._api.mcp_tools({}) if self._api else self._no_api()

    def mcp_call(self, server, tool, arguments=None):
        """MCP 工具调用（白名单内）。"""
        return self._api.mcp_call({"server": server, "tool": tool,
                                   "arguments": arguments or {}}) if self._api else self._no_api()

    def mcp_resource(self, server, uri):
        """MCP 资源读取（v1 未实现）。"""
        return self._api.mcp_resource({"server": server,
                                       "uri": uri}) if self._api else self._no_api()

    def mcp_prompt(self, server, name, arguments=None):
        """MCP Prompt 模板（v1 未实现）。"""
        return self._api.mcp_prompt({"server": server, "name": name,
                                     "arguments": arguments or {}}) if self._api else self._no_api()

    def mcp_status(self, server):
        """MCP 服务器在线状态。"""
        return self._api.mcp_status({"server": server}) if self._api else self._no_api()

    # ---------- v2.1 缺口池：AI ----------
    def ai_stream(self, messages=None, prompt=None):
        """AI 流式对话（返回 text + chunks）。"""
        return self._api.ai_stream({"messages": messages,
                                    "prompt": prompt}) if self._api else self._no_api()

    def ai_vision(self, image_url, question=""):
        """AI 视觉识图（返回描述）。"""
        return self._api.ai_vision({"image_url": image_url,
                                    "question": question}) if self._api else self._no_api()

    def ai_embedding(self, text):
        """AI 向量化（复用花语向量模型；返回 dim+vector 预览）。"""
        return self._api.ai_embedding({"text": text}) if self._api else self._no_api()

    def ai_rerank(self, query, documents):
        """AI 重排（返回 index+score 列表）。"""
        return self._api.ai_rerank({"query": query,
                                    "documents": list(documents)}) if self._api else self._no_api()

    def ai_token(self, text):
        """Token 估算。"""
        return self._api.ai_token({"text": text}) if self._api else self._no_api()

    def ai_models(self):
        """已配置模型列表。"""
        return self._api.ai_models({}) if self._api else self._no_api()

    def ai_model_info(self, model_key):
        """模型信息（key→名称/类型/URL）。"""
        return self._api.ai_model_info({"model": model_key}) if self._api else self._no_api()

    def ai_usage(self):
        """用量统计（指标快照 AI 相关键）。"""
        return self._api.ai_usage({}) if self._api else self._no_api()

    def ai_budget(self):
        """预算/限额配置。"""
        return self._api.ai_budget({}) if self._api else self._no_api()

    # ---------- v2.1 缺口池：社交互动 / 文件 / 媒体 ----------
    def reaction(self, message_id, react_type):
        """表情回应（等价 react）。"""
        return self._api.reaction({"message_id": message_id,
                                   "react_type": react_type}) if self._api else self._no_api()

    def poke(self, user_id=None, group_id=None):
        """戳一戳（好友戳真；群戳网关需支持）。"""
        return self._api.poke({"user_id": user_id,
                               "group_id": group_id}) if self._api else self._no_api()

    def like(self, user_id):
        """点赞。"""
        return self._api.like({"user_id": user_id}) if self._api else self._no_api()

    def emoji(self, message_id, emoji):
        """Emoji 回应（等价反应）。"""
        return self._api.emoji({"message_id": message_id,
                                "emoji": emoji}) if self._api else self._no_api()

    def emoji_list(self, message_id):
        """表情回应列表（网关需支持）。"""
        return self._api.emoji_list({"message_id": message_id}) if self._api else self._no_api()

    def file_upload(self, name, data):
        """上传文件到插件 WebUI 空间（web_ui.files 权限）。"""
        return self._api.file_upload({"name": name,
                                      "data": data}) if self._api else self._no_api()

    def file_download(self, name):
        """下载插件空间文件。"""
        return self._api.file_download({"name": name}) if self._api else self._no_api()

    def file_info(self, name):
        """文件信息（大小/类型/图片宽高）。"""
        return self._api.file_info({"name": name}) if self._api else self._no_api()

    def file_delete(self, name):
        """删除插件空间文件。"""
        return self._api.file_delete({"name": name}) if self._api else self._no_api()

    def file_convert(self, name, target_format):
        """文件转换（网关需支持）。"""
        return self._api.file_convert({"name": name,
                                       "target_format": target_format}) if self._api else self._no_api()

    def image_compress(self, name, quality=80):
        """图片压缩（网关需支持）。"""
        return self._api.image_compress({"name": name,
                                         "quality": quality}) if self._api else self._no_api()

    def image_resize(self, name, width, height=0):
        """图片缩放（网关需支持）。"""
        return self._api.image_resize({"name": name, "width": width,
                                       "height": height}) if self._api else self._no_api()

    def image_screenshot(self, name, box=None):
        """图片截图（网关需支持）。"""
        return self._api.image_screenshot({"name": name,
                                           "box": box}) if self._api else self._no_api()

    def audio_info(self, name):
        """音频信息（大小/格式）。"""
        return self._api.audio_info({"name": name}) if self._api else self._no_api()

    def video_info(self, name):
        """视频信息（大小/格式）。"""
        return self._api.video_info({"name": name}) if self._api else self._no_api()

    # ---------- v2.1 缺口池：群 ----------
    def group_member_search(self, group_id, query="", count=100):
        """群成员搜索（昵称/群名片/ID 模糊）。"""
        return self._api.group_member_search({"group_id": group_id, "query": query,
                                              "count": count}) if self._api else self._no_api()

    def group_member_update(self, group_id, user_id, card=None):
        """更新群名片（等价设置成员资料）。"""
        return self._api.group_member_update({"group_id": group_id, "user_id": user_id,
                                              "card": card}) if self._api else self._no_api()

    def group_mute_status(self, group_id, user_id):
        """群成员禁言状态查询（网关需支持）。"""
        return self._api.group_mute_status({"group_id": group_id,
                                            "user_id": user_id}) if self._api else self._no_api()

    def group_title(self, group_id, user_id, title):
        """设置群头衔（等价 set_group_special_title）。"""
        return self._api.group_title({"group_id": group_id, "user_id": user_id,
                                      "title": title}) if self._api else self._no_api()

    def group_notice_create(self, group_id, content):
        """创建群公告。"""
        return self._api.group_notice_create({"group_id": group_id,
                                              "content": content}) if self._api else self._no_api()

    def group_notice_update(self, group_id, content, notice_id=None):
        """更新群公告（删除旧+发送新）。"""
        return self._api.group_notice_update({"group_id": group_id, "content": content,
                                              "notice_id": notice_id}) if self._api else self._no_api()

    def group_file_upload(self, group_id, path, name):
        """上传群文件（网关需支持）。"""
        return self._api.group_file_upload({"group_id": group_id, "path": path,
                                            "name": name}) if self._api else self._no_api()

    def group_file_rename(self, group_id, file_id, name):
        """重命名群文件。"""
        return self._api.group_file_rename({"group_id": group_id, "file_id": file_id,
                                            "name": name}) if self._api else self._no_api()

    def group_essence(self, group_id):
        """群精华消息列表。"""
        return self._api.group_essence({"group_id": group_id}) if self._api else self._no_api()

    def group_invite(self, group_id, user_id):
        """群邀请（网关需支持）。"""
        return self._api.group_invite({"group_id": group_id,
                                       "user_id": user_id}) if self._api else self._no_api()

    def group_apply(self, flag, approve=True, reason=""):
        """处理加群申请（等价 handle_group_request）。"""
        return self._api.group_apply({"flag": flag, "approve": approve,
                                      "reason": reason}) if self._api else self._no_api()

    def group_admins(self, group_id):
        """群管理员列表（admin+owner）。"""
        return self._api.group_admins({"group_id": group_id}) if self._api else self._no_api()

    def group_honor(self, group_id, honor_type=""):
        """群荣誉。"""
        return self._api.group_honor({"group_id": group_id,
                                      "honor_type": honor_type}) if self._api else self._no_api()

    def _no_api(self):
        return {"ok": False, "error": "未 attach（api 不可用）"}

    def schedule_cancel(self, schedule_id: str) -> dict:
        """取消定时任务（api.schedule_cancel 的 bot 门面转发）。"""
        if self._api is None:
            return {"ok": False, "error": "未 attach（api 不可用）"}
        return self._api.schedule_cancel(schedule_id)

    def schedule_list(self) -> dict:
        """列出本插件定时任务。"""
        if self._api is None:
            return {"ok": False, "error": "未 attach（api 不可用）"}
        return self._api.schedule_list()

    def schedule(self, *, interval: Optional[float] = None,
                 delay: Optional[float] = None, daily: Optional[str] = None,
                 name: str = ""):
        """注册定时任务：@bot.schedule(interval=60) / (delay=10) / (daily="09:30")。

        必须实现为 async def job(event)：event.schedule_id/name/trigger 可用。
        """
        if interval is not None:
            kind, when = "interval", float(interval)
        elif delay is not None:
            kind, when = "delay", float(delay)
        elif daily is not None:
            kind, when = "daily", str(daily)
        else:
            raise ValueError("schedule 需要 interval/delay/daily 之一")

        def deco(func):
            self._schedules.append((str(name or func.__name__), kind, when, func))
            return func
        return deco

    def _collect_schedules(self):
        """on_startup 后由 register() 调用：上报全部调度定义（重复注册幂等）。"""
        if self._api is None:
            return
        for name, kind, when, _func in self._schedules:
            try:
                self._r(self._api.schedule_register(kind, when, name))
            except Exception:  # noqa: BLE001 - 权限不足/网关不支持：降级为日志，不阻断启动
                pass

    # ---------- 冷却（插件进程内轻量实现） ----------
    def is_cooled(self, key: str, seconds: float) -> bool:
        """key 在 seconds 秒内是否已触发过（未触发过=False）。"""
        import time
        last = self._cooldowns.get(str(key))
        return last is not None and (time.time() - last) < float(seconds)

    def mark_cooled(self, key: str) -> None:
        import time
        self._cooldowns[str(key)] = time.time()

    async def cool_down(self, key: str, seconds: float) -> bool:
        """一键冷却检查：冷却中返回 False；否则标记并返回 True（推荐用法）。"""
        if self.is_cooled(key, seconds):
            return False
        self.mark_cooled(key)
        return True

    @staticmethod
    async def _invoke(handler, event) -> None:
        import asyncio
        result = handler(event)
        if asyncio.iscoroutine(result):
            await result

    @staticmethod
    async def _invoke_schedule(handler, event_dict) -> None:
        import asyncio
        import inspect as _inspect
        args = [BotEvent(dict(event_dict or {}))] if _inspect.signature(handler).parameters             else []
        if not args:
            result = handler()
        else:
            result = handler(args[0])
        if asyncio.iscoroutine(result):
            await result

    # ---------- 日志（插件级：级别 + 消息；跟随主进程结构化日志与审计） ----------
    def log(self, level: str, message: str) -> None:
        """插件日志规范入口：level=debug/info/warning/error；message≤500 字符。

        规范：关键动作 info / 可恢复问题 warning / 异常 error（附异常类型与摘要）。
        日志由主进程统一写入（含 plugin_id/事件上下文），切勿 print 到 stdout
        （stdout 是协议通道，污染会导致插件异常）。
        """
        if self._api is None:
            raise BotAPIError("bot 未 attach")
        self._r(self._api.log(str(level or "info")[:16], str(message or "")[:500]))

    # ---------- v1.5：分组上下文与语义化社交动作 ----------
    def group(self, group_id):
        from flowerie_sdk.contexts import GroupContext
        return GroupContext(self, int(group_id))

    def user(self, user_id):
        from flowerie_sdk.contexts import UserContext
        return UserContext(self, int(user_id))

    @property
    def me(self):
        from flowerie_sdk.contexts import MeContext
        return MeContext(self)

    def tap(self, group_id, user_id) -> bool:
        """戳一戳（群内 @ 动作的 QQ 原生版）。"""
        return bool(self._r(self._api.call("tap", {"group_id": int(group_id),
                                                   "user_id": int(user_id)})).get("ok"))

    def emoji(self, message_id, emoji_id: int) -> bool:
        """消息表情回应（emoji_id 为平台表情编号）。"""
        return bool(self._r(self._api.call("react", {"message_id": int(message_id),
                                                     "react_type": int(emoji_id)})).get("ok"))

    def pin(self, message_id) -> bool:
        """加精华消息（群里置顶质感）。"""
        return bool(self._r(self._api.call("pin", {"message_id": int(message_id)})).get("ok"))

    def unpin(self, message_id) -> bool:
        return bool(self._r(self._api.call("unpin", {"message_id": int(message_id)})).get("ok"))

    def like(self, user_id) -> bool:
        """给好友点个赞。"""
        return bool(self._r(self._api.call("like", {"user_id": int(user_id)})).get("ok"))

    def friends(self) -> Optional[list]:
        res = self._r(self._api.call("friends", {}))
        if not res.get("ok"):
            return None
        data = res.get("data") or res.get("friends") or []
        return data if isinstance(data, list) else None

    # ---------- 消息 API（经协议 action，插件不碰 OneBot） ----------
    def _r(self, result):
        if not isinstance(result, dict):
            return {}
        if result.get("ok") is False or result.get("error"):
            raise BotAPIError(str(result.get("error") or result.get("reason") or "动作失败"))
        return result

    # ---------- v1.4 能力（请求处理/群管理/存储/AI/记忆/工具/网络） ----------
    def handle_friend_request(self, flag: str, approve: bool, remark: str = "") -> dict:
        """处理好友请求（权限 request_handle）。"""
        return self._r(self._api.handle_friend_request(str(flag), bool(approve), str(remark)[:30]))

    def handle_group_request(self, flag: str, approve: bool, reason: str = "") -> dict:
        """处理加群请求（权限 request_handle）。"""
        return self._r(self._api.handle_group_request(str(flag), bool(approve), str(reason)[:30]))

    def get_group_info(self, group_id) -> dict:
        """群状态信息（复用主进程状态查询；返回 info 字典）。"""
        return self._r(self._api.get_group_info({"group_id": int(group_id)}))

    def set_group_admin(self, group_id, user_id, enable: bool = True) -> dict:
        """设置/取消群管理员（权限 group_manage）。"""
        return self._r(self._api.group_admin(
            {"group_id": int(group_id), "user_id": int(user_id), "enable": bool(enable)}))

    def kv_get(self, key: str):
        res = self._r(self._api.kv_get(str(key)))
        return res.get("value") if res.get("ok") and res.get("exists") else None

    def kv_set(self, key: str, value) -> bool:
        import json as _json
        val = value if isinstance(value, str) else _json.dumps(value, ensure_ascii=False)
        return bool(self._r(self._api.kv_set(str(key)[:128], val)).get("ok"))

    def kv_delete(self, key: str) -> bool:
        return bool(self._r(self._api.kv_delete(str(key))).get("ok"))

    def kv_list(self) -> list:
        return list(self._r(self._api.kv_list()).get("items") or [])

    async def ai_chat(self, message: str, system: str = "") -> Optional[str]:
        """受限 AI 对话（权限 ai_chat；独立于聊天预算——务必命令级冷却限制频次）。"""
        res = self._r(self._api.ai_chat(str(message)[:2000], str(system)[:1000]))
        return res.get("reply") if res.get("ok") else None

    async def mem_update(self, user_id, group_id, key: str, value: str) -> bool:
        return bool(self._r(self._api.mem_update(int(user_id), int(group_id), str(key),
                                                 str(value)[:2000])).get("ok"))

    async def mem_clear(self, user_id, group_id) -> Optional[int]:
        res = self._r(self._api.mem_clear(int(user_id), int(group_id)))
        return res.get("cleared") if res.get("ok") else None

    def random_choice(self, choices: list):
        return self._r(self._api.random_choice(list(choices))).get("choice")

    def random_int(self, low: int, high: int):
        return self._r(self._api.random_int(int(low), int(high))).get("value")

    def now(self) -> dict:
        return self._r(self._api.now())

    def format_time(self, timestamp: float = 0, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
        return str(self._r(self._api.format_time(float(timestamp), str(fmt))).get("text") or "")

    def http_put(self, url: str, body=None, json=None, headers=None, timeout: float = 15) -> dict:
        return self._r(self._api.http_put({"url": url, "body": body, "json": json,
                                           "headers": headers, "timeout": timeout}))

    def http_delete(self, url: str, timeout: float = 15) -> dict:
        return self._r(self._api.http_delete({"url": url, "timeout": timeout}))

    def http_head(self, url: str, timeout: float = 15) -> dict:
        return self._r(self._api.http_head({"url": url, "timeout": timeout}))

    def http_download(self, url: str, save_to: str) -> Optional[int]:
        """下载到插件目录相对路径（SSRF 校验 + 10MB 上限；返回字节数）。"""
        res = self._r(self._api.http_download({"url": url, "save_to": save_to}))
        return res.get("bytes") if res.get("ok") else None

    async def send(self, target, message, *, reply_id=None) -> int:
        if self._api is None:
            raise BotAPIError("bot 未 attach")
        if isinstance(target, int) or str(target).isdigit():
            target = ("group", int(target))
        payload = {"group_id": int(target[1])} if target[0] == "group" else {"user_id": int(target[1])}
        payload["message"] = to_onebot(message)
        if reply_id:
            payload["reply_id"] = int(reply_id)
        res = self._api.send_message(payload) if target[0] == "group" else \
            self._api.send_private_message(payload)
        return int(self._r(res).get("message_id") or 0)

    async def reply(self, event, message=None, **kwargs) -> int:
        if not event.message_id:
            raise BotAPIError("事件无 message_id，无法回复")
        if event.group_id:
            res = self._api.send_reply({"group_id": int(event.group_id),
                                        "message": to_onebot(message),
                                        "reply_id": int(event.message_id)})
        else:
            res = self._api.send_private_message({"user_id": int(event.user_id),
                                                 "message": to_onebot(message)})
        return int(self._r(res).get("message_id") or 0)

    async def recall(self, message_id: int) -> None:
        self._r(self._api.delete_message({"message_id": int(message_id)}))

    async def get_message(self, message_id: int):
        return self._r(self._api.get_message({"message_id": int(message_id)}))

    async def get_context(self, group_id: int, max_messages: int = 10):
        return self._r(self._api.get_context({"group_id": int(group_id),
                                              "count": int(max_messages)}))

    async def get_group_member(self, group_id: int, user_id: int):
        return self._r(self._api.get_group_member({"group_id": int(group_id),
                                                   "user_id": int(user_id)}))

    async def get_group_members(self, group_id: int):
        return self._r(self._api.get_group_members({"group_id": int(group_id)}))

    async def is_group_admin(self, group_id: int, user_id: int) -> bool:
        res = self._r(self._api.is_group_admin({"group_id": int(group_id), "user_id": int(user_id)}))
        return bool(res.get("result", res.get("ok")))

    async def is_group_owner(self, group_id: int, user_id: int) -> bool:
        res = self._r(self._api.is_group_owner({"group_id": int(group_id), "user_id": int(user_id)}))
        return bool(res.get("result", res.get("ok")))

    async def mute(self, group_id: int, user_id: int, duration_seconds: int) -> None:
        self._r(self._api.group_ban({"group_id": int(group_id), "user_id": int(user_id),
                                     "duration": int(duration_seconds)}))

    async def kick(self, group_id: int, user_id: int) -> None:
        self._r(self._api.group_kick({"group_id": int(group_id), "user_id": int(user_id)}))


class BotAPIError(Exception):
    """SDK 动作失败（协议层错误文本）。"""


def to_onebot(message) -> Any:
    """str / BotMessage → 协议可传形式（段数组；下层在协议边界做 OneBot 拼装）。

    插件只构造领域消息：text/at/image/reply 在此转成段数组交给主进程。
    """
    if isinstance(message, BotMessage):
        segments = []
        if message.reply_id is not None:
            segments.append({"type": "reply", "data": {"id": int(message.reply_id)}})
        if message.text:
            segments.append({"type": "text", "data": {"text": message.text}})
        for uid in message.at_list:
            segments.append({"type": "at", "data": {"qq": str(uid)}})
        for img in message.images:
            segments.append({"type": "image", "data": {"file": str(img)}})
        for v in message.videos:
            segments.append({"type": "video", "data": {"file": str(v)}})
        for v in message.voices:
            segments.append({"type": "record", "data": {"file": str(v)}})
        for f in message.files:
            seg = {"type": "file", "data": {"file": str(f)}}
            name = getattr(message, "_file_names", {}).get(str(f))
            if name:
                seg["data"]["name"] = str(name)
            segments.append(seg)
        segments.extend(getattr(message, "segments", []))
        return segments
    return message
