"""下层：OneBotAdapter（OneBot11/NapCat HTTP 实现）——唯一 import OneBot 语义的适配处。

机械职责：BotMessage → OneBot 段数组（transformer.to_bot_message_payload）；
sender 返回结果 → 统一 BotError 体系（retcode/超时/消息不存在/不支持）。
"""
import asyncio
from typing import Any, Dict, List, Optional

from src.sdk.adapter import BotAdapter
from src.sdk.errors import (
    BotAPIError,
    BotTimeoutError,
    MessageNotFoundError,
    UnsupportedOperationError,
)
from src.sdk.message import BotMessage
from src.sdk.onebot.transformer import to_bot_message_payload


class OneBotAdapter(BotAdapter):
    def __init__(self, sender, context_manager=None, timeout: float = 15.0):
        self._sender = sender
        self._context_manager = context_manager
        self._timeout = float(timeout)

    @staticmethod
    def _ensure(ok: Any, message: str = "平台返回失败") -> None:
        if not ok:
            raise BotAPIError(message)

    async def _call(self, coro, *, timeout: Optional[float] = None):
        try:
            return await asyncio.wait_for(coro, timeout=timeout or self._timeout)
        except asyncio.TimeoutError:
            raise BotTimeoutError("平台调用超时") from None

    # ---------- BotAdapter 实现 ----------
    async def send(self, target: str, target_id: int, message,
                   reply_id: Optional[int] = None) -> int:
        # reply 段唯一来源：BotMessage 自带 reply_id 优先；否则用显式 reply_id。
        # （绝不双段：BotMessage 场景 reply 段由 to_bot_message_payload 输出）
        if isinstance(message, BotMessage) and message.reply_id is not None:
            reply_id = message.reply_id
        payload = to_bot_message_payload(message)
        if reply_id is not None:
            if isinstance(payload, list):
                if not (isinstance(message, BotMessage) and message.reply_id is not None):
                    payload = [{"type": "reply", "data": {"id": int(reply_id)}}] + payload
            else:
                payload = [{"type": "reply", "data": {"id": int(reply_id)}},
                           {"type": "text", "data": {"text": str(payload)}}]
        result = await self._call(self._sender.send_msg_raw(target, int(target_id), payload))
        if not result.get("ok"):
            raise BotAPIError(f"发送失败（target={target}）: {result.get('error', '')}")
        mid = result.get("message_id")
        if mid is None:
            raise BotAPIError("发送成功但服务端未返回 message_id")
        return int(mid)

    async def recall(self, message_id: int) -> None:
        self._ensure(await self._call(self._sender.delete_msg(message_id)),
                     f"撤回失败 message_id={message_id}（可能已不存在或无权操作）")

    async def get_message(self, message_id: int) -> BotMessage:
        d = await self._call(self._sender.get_msg(message_id))
        if not d.get("ok"):
            raise MessageNotFoundError(f"消息不存在 message_id={message_id}")
        return BotMessage(str(d.get("text") or ""))

    async def get_user_info(self, user_id: int) -> Dict[str, Any]:
        raise UnsupportedOperationError("当前平台不支持独立 get_user_info（可用 get_group_member）")

    async def get_group_info(self, group_id: int) -> Dict[str, Any]:
        raise UnsupportedOperationError("当前平台不支持独立 get_group_info（可用 get_group_member 查询）")

    async def get_group_member(self, group_id: int, user_id: int) -> Dict[str, Any]:
        d = await self._call(self._sender.get_group_member_info(group_id, user_id))
        if not d.get("ok"):
            raise BotAPIError(f"成员信息查询失败: {d.get('error', '')}")
        return d

    async def get_group_members(self, group_id: int) -> List[Dict[str, Any]]:
        d = await self._call(self._sender.get_group_member_list(group_id))
        if not d.get("ok"):
            raise BotAPIError(f"成员列表查询失败: {d.get('error', '')}")
        return d.get("members", [])

    async def mute(self, group_id: int, user_id: int, duration_seconds: int) -> None:
        self._ensure(await self._call(self._sender.set_group_ban(group_id, user_id, duration_seconds)),
                     f"禁言失败 group={group_id} user={user_id}")

    async def kick(self, group_id: int, user_id: int) -> None:
        self._ensure(await self._call(self._sender.set_group_kick(group_id, user_id)),
                     f"移出群成员失败 group={group_id} user={user_id}")

    async def get_context(self, group_id: int, max_messages: int = 10) -> List[Dict[str, Any]]:
        """复用 Flowerie 现有 ContextManager（领域数据源，不调平台历史接口）。"""
        if self._context_manager is None:
            return await super().get_context(group_id, max_messages)
        state = self._context_manager.get_group_state(int(group_id))
        entries = list(state.context)[-max(1, min(int(max_messages), 50)):]
        return [{"user_id": e.get("user_id"), "message": str(e.get("message", "")),
                 "is_bot": bool(e.get("is_bot")), "time": e.get("time")} for e in entries]

    # ---------- v1.5 社交/群管语义（端点只在 Sender；支持矩阵见 docs/sdk.md） ----------
    async def tap(self, group_id: int, user_id: int) -> dict:
        return await self._call(self._sender.send_poke(int(group_id), int(user_id)))

    async def react(self, message_id: int, emoji_id: int) -> dict:
        # 网关回退（换网关自动激活）：NapCat=set_react（主端点）；Lagrange=set_group_reaction
        if getattr(self._sender, "set_react", None) is not None:
            return await self._call(self._sender.set_react(int(message_id), int(emoji_id)))
        lagrange = getattr(self._sender, "set_group_reaction", None)
        if lagrange is not None:
            return await self._call(lagrange(int(message_id), int(emoji_id)))
        return {"ok": False, "error": "当前网关不支持表情回应"}

    async def pin(self, message_id: int) -> dict:
        return await self._call(self._sender.set_essence_msg(int(message_id)))

    async def unpin(self, message_id: int) -> dict:
        return await self._call(self._sender.delete_essence_msg(int(message_id)))

    async def friends(self) -> list:
        return (await self._call(self._sender.get_friend_list())).get("data") or []

    async def like(self, user_id: int) -> dict:
        return await self._call(self._sender.set_friend_profile_like(int(user_id)))

    async def login_info(self) -> dict:
        return await self._call(self._sender.get_login_info())

    async def online_devices(self) -> dict:
        return await self._call(self._sender.get_online_clients())

    async def set_profile(self, nickname: str = "", signature: str = "") -> dict:
        return await self._call(self._sender.set_qq_profile(nickname=nickname, signature=signature))

    async def group_whole_ban(self, group_id: int, enable: bool) -> dict:
        return await self._call(self._sender.set_group_whole_ban(int(group_id), bool(enable)))

    async def group_rename(self, group_id: int, name: str) -> dict:
        return await self._call(self._sender.set_group_name(int(group_id), name))

    async def group_card(self, group_id: int, user_id: int, card: str) -> dict:
        return await self._call(self._sender.set_group_card(int(group_id), int(user_id), card))

    async def group_title(self, group_id: int, user_id: int, title: str) -> dict:
        return await self._call(self._sender.set_group_special_title(int(group_id), int(user_id), title))

    async def group_notice(self, group_id: int, content: str, image: str = "") -> dict:
        return await self._call(self._sender.send_group_notice(int(group_id), content, image))

    async def group_config(self, group_id: int) -> dict:
        """群配置读取（部分网关支持；不支持时返回明确错误）。"""
        return await self._call(self._sender.get_group_config(int(group_id)))

    async def group_files(self, group_id: int) -> dict:
        return await self._call(self._sender.get_group_root_files(int(group_id)))

    # ---------- v1.7.0 拉格朗日补齐（端点名仅存在于 Sender） ----------
    async def user_history(self, user_id: int, count: int = 20) -> dict:
        """好友/私聊消息历史。"""
        return await self._call(self._sender.get_friend_msg_history(int(user_id), int(count)))

    async def user_poke(self, user_id: int) -> dict:
        """私聊戳一戳。"""
        return await self._call(self._sender.friend_poke(int(user_id)))

    async def group_forward(self, group_id: int, messages: list) -> dict:
        """群合并转发消息。"""
        return await self._call(self._sender.send_group_forward_msg(int(group_id), list(messages)))

    async def user_forward(self, user_id: int, messages: list) -> dict:
        """私聊合并转发消息。"""
        return await self._call(self._sender.send_private_forward_msg(int(user_id), list(messages)))

    async def essence_list(self, group_id: int) -> dict:
        """群精华消息列表。"""
        return await self._call(self._sender.get_essence_msg_list(int(group_id)))

    async def group_honor(self, group_id: int, honor_type: str = "") -> dict:
        """群荣誉信息（honor_type: talkative/performer/legend/strong_newbie/emotion）。"""
        return await self._call(self._sender.get_group_honor_info(int(group_id), honor_type))

    async def group_notice_delete(self, group_id: int, notice_id: str) -> dict:
        """删除群公告。"""
        return await self._call(self._sender.delete_group_notice(int(group_id), notice_id))

    async def group_portrait(self, group_id: int, file: str) -> dict:
        """修改群头像（file 本地路径/base64）。"""
        return await self._call(self._sender.set_group_portrait(int(group_id), file))

    async def group_folder_create(self, group_id: int, name: str) -> dict:
        """创建群文件文件夹。"""
        return await self._call(self._sender.create_group_file_folder(int(group_id), name))

    async def group_file_delete(self, group_id: int, file_id: str, busid: int = 0) -> dict:
        """删除群文件。"""
        return await self._call(self._sender.delete_group_file(int(group_id), file_id, int(busid)))

    async def group_folder_delete(self, group_id: int, folder_id: str) -> dict:
        """删除群文件文件夹。"""
        return await self._call(self._sender.delete_group_folder(int(group_id), folder_id))

    async def group_file_move(self, group_id: int, file_id: str, busid: int = 0,
                              target_folder_id: str = "") -> dict:
        """移动群文件到目标文件夹。"""
        return await self._call(self._sender.move_group_file(
            int(group_id), file_id, int(busid), target_folder_id))

    async def group_folder_rename(self, group_id: int, folder_id: str, name: str) -> dict:
        """重命名群文件文件夹。"""
        return await self._call(self._sender.rename_group_file_folder(int(group_id), folder_id, name))

    async def group_list(self) -> dict:
        """群列表。"""
        return await self._call(self._sender.get_group_list())


def make_onebot_adapter(sender, context_manager=None) -> OneBotAdapter:
    """下层工厂（上层/主进程按需创建）。"""
    return OneBotAdapter(sender, context_manager)
