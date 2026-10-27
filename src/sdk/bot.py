"""Bot 门面：插件面向的统一入口（bot.send / bot.reply / bot.recall / ...）。

构造：Bot(adapter, config=None, permission_checker=None)；adapter 为 BotAdapter 实例。
所有网络 API 保持 async；失败抛统一 BotError 体系。
"""
from typing import Any, Dict, List, Optional

from src.core.reply_plan import ReplyPlan
from src.core.reply_sender import send_plan
from src.sdk.event import BotEvent
from src.sdk.message import BotMessage
from src.sdk.permissions import PermissionChecker


class Bot:
    def __init__(self, adapter, config=None, permission_checker: Optional[PermissionChecker] = None):
        self._adapter = adapter
        self._config = config
        self._permission = permission_checker or PermissionChecker(config=config, bot=self,
                                                                   adapter=adapter)

    # ---------- 消息 ----------
    async def send(self, target, message, *, reply_id: Optional[int] = None) -> int:
        """发送消息：target 为元组 ("group"|"private", id) 或群号 int（默认群）。

        message: str / BotMessage。返回 message_id。
        """
        if isinstance(target, int) or str(target).isdigit():
            target = ("group", int(target))
        kind, target_id = target
        return await self._adapter.send(kind, int(target_id), message, reply_id=reply_id)

    async def send_private(self, user_id: int, message, *, reply_id: Optional[int] = None) -> int:
        """发私聊（v2.14.0 便捷入口；等价 send(("private", qq), msg)）。"""
        return await self.send(("private", int(user_id)), message, reply_id=reply_id)

    async def get_private_history(self, user_id: int, count: int = 20):
        """好友/私聊最近消息（协议不支持时抛 UnsupportedOperationError）。"""
        return await self._adapter.get_private_history(int(user_id), int(count))

    def private_chat_status(self, user_id: Optional[int] = None) -> dict:
        """私聊功能状态（给插件/面板做前置判断，不发起网络请求）。

        返回 {enabled, memory_enabled, allowed, allow_strangers, cooldown_seconds}；
        allowed 为 False 时，私聊消息会被引擎直接忽略。
        """
        config = self._config
        if config is None:
            return {"enabled": False, "allowed": False}
        allowed_ids = set()
        for raw in list(getattr(config, "PRIVATE_CHAT_ALLOWED_QQS", None) or []) + \
                list(getattr(config, "ADMIN_QQ_IDS", None) or []):
            try:
                allowed_ids.add(int(raw))
            except (TypeError, ValueError):
                continue
        return {
            "enabled": bool(getattr(config, "PRIVATE_CHAT_ENABLED", False)),
            "memory_enabled": bool(getattr(config, "PRIVATE_CHAT_MEMORY_ENABLED", True)),
            "allow_strangers": bool(getattr(config, "PRIVATE_CHAT_ALLOW_STRANGERS", False)),
            "cooldown_seconds": int(getattr(config, "PRIVATE_CHAT_COOLDOWN_SECONDS", 0) or 0),
            "allowed": (int(user_id) in allowed_ids) if user_id is not None else False,
        }

    async def reply(self, event_or_target, message, **kwargs) -> int:
        """回复：传入 BotEvent 自动推导目标（群/私聊）。"""
        if isinstance(event_or_target, BotEvent):
            kind = "group" if event_or_target.is_group else "private"
            target_id = event_or_target.group_id or event_or_target.user_id
            reply_id = kwargs.pop("reply_id", event_or_target.message_id)
            return await self._adapter.send(kind, int(target_id), message, reply_id=reply_id)
        return await self.send(event_or_target, message, **kwargs)

    # ---------- 多条回复（Multi-Reply）----------
    def _build_plan(self, messages, interval_mode=None, min_interval=None, max_interval=None):
        """把「要发的若干条」变成 Core 的 ReplyPlan（条数受配置上限约束）。"""
        max_messages = int(getattr(self._config, "MULTI_REPLY_MAX_MESSAGES", 3) or 3)
        if interval_mode is None:
            interval_mode = str(getattr(self._config, "MULTI_REPLY_INTERVAL_MODE", "random") or "random")
        if min_interval is None:
            min_interval = float(getattr(self._config, "MULTI_REPLY_MIN_INTERVAL", 1.5) or 0.0)
        if max_interval is None:
            max_interval = float(getattr(self._config, "MULTI_REPLY_MAX_INTERVAL", 4.0) or 0.0)
        plan = ReplyPlan.of(messages, interval_mode=interval_mode,
                            min_interval=min_interval, max_interval=max_interval)
        return plan.normalize_mode().clamped(max_messages)

    async def send_many(self, target, messages, *, reply_id=None, interval_mode=None,
                        min_interval=None, max_interval=None):
        """一次发送多条独立消息（按 Core 的间隔策略逐条发）。

        与「插件自己写 for 循环」的区别：条数受 MULTI_REPLY_MAX_MESSAGES 约束、
        间隔由 Core 统一控制、每条都走同一条发送与记录路径、失败策略统一。
        返回每条消息的 message_id 列表。
        """
        if isinstance(target, int) or str(target).isdigit():
            target = ("group", int(target))
        kind, target_id = target
        plan = self._build_plan(messages, interval_mode, min_interval, max_interval)

        async def send_one(msg, idx):
            return await self._adapter.send(kind, int(target_id), msg,
                                            reply_id=reply_id if idx == 0 else None)

        return await send_plan(plan, send_one)

    async def reply_many(self, event_or_target, messages, **kwargs):
        """回复并拆成多条（传入 BotEvent 自动推导目标；单条时等价于 reply）。"""
        if isinstance(event_or_target, BotEvent):
            kind = "group" if event_or_target.is_group else "private"
            target_id = event_or_target.group_id or event_or_target.user_id
            reply_id = kwargs.pop("reply_id", event_or_target.message_id)
            interval_mode = kwargs.pop("interval_mode", None)
            min_interval = kwargs.pop("min_interval", None)
            max_interval = kwargs.pop("max_interval", None)
            plan = self._build_plan(messages, interval_mode, min_interval, max_interval)

            async def send_one(msg, idx):
                return await self._adapter.send(kind, int(target_id), msg,
                                                reply_id=reply_id if idx == 0 else None)

            return await send_plan(plan, send_one)
        return await self.send_many(event_or_target, messages, **kwargs)

    async def recall(self, message_id: int) -> None:
        await self._adapter.recall(int(message_id))

    async def get_message(self, message_id: int) -> BotMessage:
        return await self._adapter.get_message(int(message_id))

    async def get_context(self, group_id: int, max_messages: int = 10) -> List[Dict[str, Any]]:
        return await self._adapter.get_context(int(group_id), max_messages)

    # ---------- 用户 ----------
    async def get_user_info(self, user_id: int) -> Dict[str, Any]:
        return await self._adapter.get_user_info(int(user_id))

    async def is_admin(self, event) -> bool:
        """bot 管理员（复用 Flowerie ADMIN_QQ_IDS）。"""
        return await self._permission.check(event, "bot_admin")

    async def is_owner(self, event) -> bool:
        """bot owner（当前与 admin 同源，见 docs/reference/sdk.md 说明）。"""
        return await self._permission.check(event, "bot_owner")

    # ---------- 群 ----------
    async def get_group_info(self, group_id: int) -> Dict[str, Any]:
        return await self._adapter.get_group_info(int(group_id))

    async def get_group_member(self, group_id: int, user_id: int) -> Dict[str, Any]:
        return await self._adapter.get_group_member(int(group_id), int(user_id))

    async def get_group_members(self, group_id: int) -> List[Dict[str, Any]]:
        return await self._adapter.get_group_members(int(group_id))

    async def is_group_admin(self, group_id: int, user_id: int) -> bool:
        member = await self._adapter.get_group_member(int(group_id), int(user_id))
        role = str((member or {}).get("role") or "member")
        return role in ("owner", "admin")

    async def is_group_owner(self, group_id: int, user_id: int) -> bool:
        member = await self._adapter.get_group_member(int(group_id), int(user_id))
        return str((member or {}).get("role") or "member") == "owner"

    # ---------- 群管理 ----------
    async def mute(self, group_id: int, user_id: int, duration_seconds: int) -> None:
        await self._adapter.mute(int(group_id), int(user_id), int(duration_seconds))

    async def kick(self, group_id: int, user_id: int) -> None:
        await self._adapter.kick(int(group_id), int(user_id))

    # ---------- 群管理员扩展（v2.10） ----------
    async def set_group_admin(self, group_id: int, user_id: int, enable: bool = True) -> Any:
        """设置/取消群管理员。"""
        return await self._adapter.set_group_admin(int(group_id), int(user_id), bool(enable))

    async def kick_with_reject(self, group_id: int, user_id: int) -> Any:
        """移出群成员并拒绝再次加群。"""
        return await self._adapter.kick_with_reject(int(group_id), int(user_id))

    async def get_group_shut_list(self, group_id: int) -> Any:
        """当前被禁言成员列表。"""
        return await self._adapter.get_group_shut_list(int(group_id))

    async def leave_group(self, group_id: int, dismiss: bool = False) -> Any:
        """Bot 退出群聊（群主且 dismiss=True 时解散）。"""
        return await self._adapter.quit_group(int(group_id), bool(dismiss))

    async def set_group_whole_ban(self, group_id: int, enable: bool) -> Any:
        """全员禁言开关。"""
        return await self._adapter.group_whole_ban(int(group_id), bool(enable))

    async def set_group_card(self, group_id: int, user_id: int, card: str = "") -> Any:
        """修改群名片（空=清除）。"""
        return await self._adapter.group_card(int(group_id), int(user_id), str(card))

    async def set_group_name(self, group_id: int, name: str) -> Any:
        """修改群名称。"""
        return await self._adapter.group_rename(int(group_id), str(name))

    async def set_group_special_title(self, group_id: int, user_id: int, title: str = "") -> Any:
        """设置专属头衔（空=清除）。"""
        return await self._adapter.group_title(int(group_id), int(user_id), str(title))

    # ---------- QQ空间（v2.10） ----------
    async def qzone_publish(self, content: str, images: Optional[List[str]] = None,
                            ugc_right: int = 1, target_uins: Optional[List[int]] = None) -> Any:
        """发表 QQ空间说说（ugc_right：1 所有人 / 4 好友 / 16 部分好友 / 64 仅自己 / 128 部分好友不可见）。"""
        return await self._adapter.qzone_publish(
            str(content), list(images or []), int(ugc_right),
            [int(x) for x in (target_uins or [])])

    async def qzone_delete(self, tid: str) -> Any:
        """删除 QQ空间说说（按 tid）。"""
        return await self._adapter.qzone_delete(str(tid))

    # ---------- 权限检查（require_permission 装饰器配套） ----------
    async def check_permission(self, event, kind: str) -> bool:
        return await self._permission.check(event, kind)

    def permission(self, event, kind: str) -> bool:
        raise RuntimeError("请使用 await bot.check_permission(event, kind)")  # pragma: no cover
