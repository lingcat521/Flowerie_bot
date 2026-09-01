"""Flowerie 插件 SDK——分组上下文对象（领域语义 API；端点只在主进程下层）。

bot.group(gid) / bot.user(uid) / bot.me：把"操作对象"作为一等公民，
方法名取社交直觉（tap=戳、pin=精华、like=点赞），不暴露任何网关端点名。
"""
from typing import Any, Dict, Optional

from flowerie_sdk.bot import FlowerieBot


class _CtxBase:
    def __init__(self, bot: FlowerieBot):
        self._bot = bot

    def _call(self, action: str, payload: Dict[str, Any]) -> dict:
        return self._bot._api.call(action, payload)

    def _ok(self, res: dict) -> Optional[Dict[str, Any]]:
        return res if isinstance(res, dict) and res.get("ok") else None


class GroupContext(_CtxBase):
    """群操作上下文：bot.group(123).mute(user, 600) ..."""

    def __init__(self, bot: FlowerieBot, group_id: int):
        super().__init__(bot)
        self.group_id = int(group_id)

    async def members(self) -> Optional[list]:
        res = self._ok(await self._bot.get_group_members(self.group_id))
        return res.get("members") if res else None

    async def member(self, user_id: int) -> Optional[dict]:
        res = self._ok(await self._bot.get_group_member(self.group_id, int(user_id)))
        return res

    async def mute(self, user_id: int, seconds: int = 600) -> bool:
        return await self._bot.mute(self.group_id, int(user_id), int(seconds))

    async def kick(self, user_id: int, reject_add: bool = False) -> bool:
        return await self._bot.kick(self.group_id, int(user_id), reject_add=reject_add)

    async def set_admin(self, user_id: int, on: bool = True) -> bool:
        res = self._call("group_admin", {"group_id": self.group_id,
                                         "user_id": int(user_id), "enable": bool(on)})
        return bool((res or {}).get("ok"))

    async def whole_ban(self, on: bool = True) -> bool:
        res = self._call("group_whole_ban", {"group_id": self.group_id, "enable": bool(on)})
        return bool((res or {}).get("ok"))

    async def rename(self, name: str) -> bool:
        res = self._call("group_rename", {"group_id": self.group_id, "name": str(name)})
        return bool((res or {}).get("ok"))

    async def set_card(self, user_id: int, card: str) -> bool:
        res = self._call("group_card", {"group_id": self.group_id,
                                        "user_id": int(user_id), "card": str(card)})
        return bool((res or {}).get("ok"))

    async def set_title(self, user_id: int, title: str) -> bool:
        res = self._call("group_title", {"group_id": self.group_id,
                                         "user_id": int(user_id), "title": str(title)})
        return bool((res or {}).get("ok"))

    async def send_notice(self, content: str, image: str = "") -> bool:
        payload = {"group_id": self.group_id, "content": str(content)}
        if image:
            payload["image"] = str(image)
        res = self._call("group_notice_send", payload)
        return bool((res or {}).get("ok"))

    async def get_notice(self) -> Optional[dict]:
        return self._ok(self._call("group_notice_get", {"group_id": self.group_id}))

    async def files(self) -> Optional[list]:
        res = self._ok(self._call("group_files", {"group_id": self.group_id}))
        if res:
            files = res.get("files") or res.get("data") or []
            return files if isinstance(files, list) else None
        return None

    async def files_in(self, folder_id: str) -> Optional[list]:
        res = self._ok(self._call("group_files_in",
                                  {"group_id": self.group_id, "folder_id": str(folder_id)}))
        if res:
            files = res.get("files") or res.get("data") or []
            return files if isinstance(files, list) else None
        return None

    async def file_url(self, file_id: str, busid: int = 0) -> Optional[str]:
        res = self._ok(self._call("group_file_url", {"group_id": self.group_id,
                                                     "file_id": str(file_id),
                                                     "busid": int(busid)}))
        if res:
            url = res.get("url") or res.get("data", {}).get("url") if isinstance(res, dict) else None
            return str(url) if url else None
        return None

    async def config(self) -> Optional[dict]:
        return self._ok(self._call("group_config", {"group_id": self.group_id}))

    async def config_set(self, **kwargs) -> bool:
        payload = {"group_id": self.group_id, **kwargs}
        res = self._call("group_config_set", payload)
        return bool((res or {}).get("ok"))

    async def pin(self, message_id: int) -> bool:
        res = self._call("pin", {"message_id": int(message_id)})
        return bool((res or {}).get("ok"))

    async def unpin(self, message_id: int) -> bool:
        res = self._call("unpin", {"message_id": int(message_id)})
        return bool((res or {}).get("ok"))

    async def resource(self, res_type: str) -> Optional[dict]:
        return self._ok(self._call("group_res", {"group_id": self.group_id,
                                                 "res_type": str(res_type)}))


class UserContext(_CtxBase):
    """用户操作上下文：bot.user(123).like() ..."""

    def __init__(self, bot: FlowerieBot, user_id: int):
        super().__init__(bot)
        self.user_id = int(user_id)

    async def like(self) -> bool:
        res = self._call("like", {"user_id": self.user_id})
        return bool((res or {}).get("ok"))

    async def tap(self, group_id: Optional[int] = None) -> bool:
        """戳一戳（需群上下文；群成员戳可省略 group_id 时用 0）。"""
        res = self._call("tap", {"group_id": int(group_id or 0), "user_id": self.user_id})
        return bool((res or {}).get("ok"))

    async def card(self, group_id: int, card: str) -> bool:
        res = self._call("group_card", {"group_id": int(group_id),
                                        "user_id": self.user_id, "card": str(card)})
        return bool((res or {}).get("ok"))

    async def info(self) -> Optional[dict]:
        return await self._bot.get_user_info(self.user_id)


class MeContext(_CtxBase):
    """Bot 自我上下文：bot.me.info() / .devices() / .profile(...)"""

    async def info(self) -> Optional[dict]:
        res = self._ok(self._call("login_info", {}))
        return res

    async def devices(self) -> Optional[list]:
        res = self._ok(self._call("devices", {}))
        if res:
            devices = res.get("devices") or res.get("data") or []
            return devices if isinstance(devices, list) else None
        return None

    async def status(self) -> Optional[dict]:
        return self._ok(self._call("status", {}))

    async def profile(self, nickname: str = "", signature: str = "") -> bool:
        res = self._call("profile_set", {"nickname": str(nickname)[:20],
                                         "signature": str(signature)[:20]})
        return bool((res or {}).get("ok"))
