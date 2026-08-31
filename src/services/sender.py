import asyncio

import aiohttp

from src.config import Settings
from src.utils.logging_setup import get_logger
from src.utils.metrics import registry

logger = get_logger(__name__)

_M_SEND_FAIL = registry.counter("message_send_failure_total", "消息发送失败次数（按目标类型）", ["target"])


class Sender:
    def __init__(self, config: Settings):
        self.config = config
        self.session: aiohttp.ClientSession = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def close(self):
        if self.session:
            await self.session.close()

    async def _post(self, endpoint: str, payload: dict, timeout: float = 10.0) -> dict:
        """通用 OneBot/Lagrange 端点调用（薄封装；统一返回 {ok, data|error}）。"""
        try:
            async with self.session.post(
                    f"{self.config.HTTP_API_BASE}{endpoint}",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status != 200:
                    return {"ok": False, "error": f"HTTP {resp.status}"}
                body = await resp.json(content_type=None)
                return {"ok": body.get("status", "ok") == "ok", "data": body.get("data")}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    async def send_group_message_with_image(self, group_id: int, text: str, image_path: str,
                                            retries: int = 2) -> bool:
        """发送文字 + 本地图片（段数组消息，OneBot11 image 段用 file:// 绝对路径）。"""
        if not image_path:
            return False
        segments = []
        if text and text.strip():
            segments.append({"type": "text", "data": {"text": text[: self.config.MAX_REPLY_LENGTH]}})
        segments.append({"type": "image", "data": {"file": f"file://{image_path}"}})
        url = f"{self.config.HTTP_API_BASE}/send_group_msg"
        payload = {"group_id": group_id, "message": segments}
        logger.info("message_send_started group=%s image=%s", group_id, image_path,
                    extra={"event": "message_send_started"})
        for attempt in range(max(1, retries + 1)):
            try:
                async with self.session.post(url, json=payload, headers=self._headers(),
                                             timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        logger.error("message_send_failed group=%s http=%s", group_id, resp.status,
                                     extra={"event": "message_send_failed"})
                    else:
                        data = await resp.json()
                        if data.get("retcode") == 0:
                            logger.info("message_send_finished group=%s image=%s", group_id, image_path,
                                        extra={"event": "message_send_finished"})
                            return True
                        logger.error("message_send_failed group=%s retcode=%s", group_id, data.get("retcode"),
                                     extra={"event": "message_send_failed"})
            except Exception as e:
                logger.error("message_send_failed group=%s err=%s", group_id, e,
                             extra={"event": "message_send_failed"})
            _M_SEND_FAIL.inc({"target": "group"})
            if attempt < retries:
                await asyncio.sleep(2)
        return False

    async def send_group_message(self, group_id: int, message: str, retries: int = 2) -> bool:
        if not message:
            return False
        if len(message) > self.config.MAX_REPLY_LENGTH:
            message = message[:self.config.MAX_REPLY_LENGTH] + "..."
        url = f"{self.config.HTTP_API_BASE}/send_group_msg"
        payload = {"group_id": group_id, "message": message}
        logger.info("message_send_started group=%s", group_id, extra={"event": "message_send_started"})
        for attempt in range(max(1, retries + 1)):
            try:
                async with self.session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        logger.error("message_send_failed group=%s http=%s", group_id, resp.status,
                                     extra={"event": "message_send_failed"})
                    else:
                        data = await resp.json()
                        if data.get("retcode") == 0:
                            logger.info("message_send_finished group=%s", group_id,
                                        extra={"event": "message_send_finished"})
                            return True
                        else:
                            logger.error("message_send_failed group=%s retcode=%s", group_id, data.get("retcode"),
                                         extra={"event": "message_send_failed"})
            except Exception as e:
                logger.error("message_send_failed group=%s err=%s", group_id, e,
                             extra={"event": "message_send_failed"})
            _M_SEND_FAIL.inc({"target": "group"})
            if attempt < retries:
                logger.info("Send retry in 2s... (%s/%s)", attempt + 1, retries)
                await asyncio.sleep(2)
        return False

    async def send_msg_raw(self, target: str, target_id: int, message,
                           reply_id=None, retries: int = 2) -> dict:
        """通用发送（OneBot11 段数组 / CQ 码字符串；回复自动加 reply 段）。

        - target: group / private
        - message: str（含 [CQ:...] 由 NapCat 解析）或 list（OneBot 段数组，
          如 [{"type":"image","data":{"file": ...}}]）——插件由此获得图片/视频/语音/文件/at 等能力
        - reply_id: 若提供，自动在最前插入 reply 段（引用回复）
        返回 {"ok": bool, "message_id": int|None}（message_id 供 delete_message 撤回）。
        """
        if not message:
            return {"ok": False, "message_id": None}
        if isinstance(message, str):
            message = message[:4000]
        segments = []
        if reply_id is not None:
            segments.append({"type": "reply", "data": {"id": int(reply_id)}})
        if isinstance(message, list):
            segments.extend(message[:40])
        else:
            segments.append({"type": "text", "data": {"text": str(message)}})
        url = f"{self.config.HTTP_API_BASE}/send_group_msg" if target == "group" \
            else f"{self.config.HTTP_API_BASE}/send_private_msg"
        payload = {"group_id": target_id, "message": segments} if target == "group" \
            else {"user_id": target_id, "message": segments}
        for attempt in range(max(1, retries + 1)):
            try:
                async with self.session.post(url, json=payload,
                                             timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        logger.error("message_send_failed target=%s http=%s", target, resp.status,
                                     extra={"event": "message_send_failed"})
                    else:
                        data = await resp.json()
                        if data.get("retcode") == 0:
                            mid = data.get("data", {}).get("message_id")
                            logger.info("message_send_finished target=%s id=%s", target, mid,
                                        extra={"event": "message_send_finished"})
                            return {"ok": True, "message_id": mid}
                        logger.error("message_send_failed target=%s retcode=%s", target, data.get("retcode"),
                                     extra={"event": "message_send_failed"})
            except Exception as e:
                logger.error("message_send_failed target=%s err=%s", target, e,
                             extra={"event": "message_send_failed"})
            if attempt < retries:
                await asyncio.sleep(2)
        return {"ok": False, "message_id": None}

    async def delete_msg(self, message_id: int) -> bool:
        """撤回消息（OneBot11 /delete_msg）。"""
        try:
            async with self.session.post(
                    f"{self.config.HTTP_API_BASE}/delete_msg",
                    json={"message_id": int(message_id)},
                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                ok = resp.status == 200
                if not ok:
                    logger.error("message_delete_failed id=%s http=%s", message_id, resp.status,
                                 extra={"event": "message_delete_failed"})
                return ok
        except Exception as e:
            logger.error("message_delete_failed id=%s err=%s", message_id, e,
                         extra={"event": "message_delete_failed"})
            return False

    async def get_msg(self, message_id: int) -> dict:
        """消息详情（OneBot11 /get_msg）。裁剪为最小字段：text/user/time/segments 摘要。"""
        try:
            async with self.session.post(
                    f"{self.config.HTTP_API_BASE}/get_msg",
                    json={"message_id": int(message_id)},
                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                d = data.get("data", {}) if data.get("retcode") == 0 else {}
                return {"ok": bool(d), "message_id": int(message_id),
                        "user_id": d.get("user_id"), "time": d.get("time"),
                        "text": str(d.get("raw_message") or "")[:2000]}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    async def get_group_msg_history(self, group_id: int, count: int = 15) -> dict:
        """群最近消息（NapCat 扩展 /get_group_msg_history）。裁剪为最小字段，最多 count 条。"""
        count = max(1, min(int(count or 15), 20))
        try:
            async with self.session.post(
                    f"{self.config.HTTP_API_BASE}/get_group_msg_history",
                    json={"group_id": int(group_id), "count": count},
                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                items = data.get("data", {}).get("messages") if data.get("retcode") == 0 else []
                if not isinstance(items, list):
                    return {"ok": False, "error": "服务端不支持 get_group_msg_history"}
                out = [{"message_id": m.get("message_id"), "user_id": m.get("user_id"),
                        "time": m.get("time"),
                        "text": str(m.get("raw_message") or "")[:2000]} for m in items]
                return {"ok": True, "messages": out[:count]}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    async def get_group_member_info(self, group_id: int, user_id: int) -> dict:
        """群成员详情（OneBot11 /get_group_member_info），裁剪为角色/名片/昵称/QQ。"""
        try:
            async with self.session.post(
                    f"{self.config.HTTP_API_BASE}/get_group_member_info",
                    json={"group_id": int(group_id), "user_id": int(user_id)},
                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                d = data.get("data", {}) if data.get("retcode") == 0 else {}
                if not d:
                    return {"ok": False, "error": "成员信息不可用"}
                return {"ok": True, "group_id": int(group_id), "user_id": int(user_id),
                        "role": d.get("role", "member"),            # owner/admin/member
                        "card": str(d.get("card") or "")[:50],
                        "nickname": str(d.get("nickname") or "")[:50],
                        "join_time": d.get("join_time"), "last_sent_time": d.get("last_sent_time"),
                        "title": str(d.get("title") or "")[:30]}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    async def get_group_member_list(self, group_id: int) -> dict:
        """群成员列表（OneBot11 /get_group_member_list），裁剪为最小字段。"""
        try:
            async with self.session.post(
                    f"{self.config.HTTP_API_BASE}/get_group_member_list",
                    json={"group_id": int(group_id)},
                    timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()
                items = data.get("data", []) if data.get("retcode") == 0 else []
                if not isinstance(items, list) or not items:
                    return {"ok": False, "error": "成员列表不可用（检查权限/平台支持）"}
                out = [{"user_id": m.get("user_id"), "role": m.get("role", "member"),
                        "card": str(m.get("card") or "")[:50], "nickname": str(m.get("nickname") or "")[:50]}
                       for m in items]
                return {"ok": True, "group_id": int(group_id), "members": out}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    async def set_group_ban(self, group_id: int, user_id: int, duration_seconds: int) -> bool:
        """群禁言（OneBot11 /set_group_ban；duration=0 解除）。"""
        try:
            async with self.session.post(
                    f"{self.config.HTTP_API_BASE}/set_group_ban",
                    json={"group_id": int(group_id), "user_id": int(user_id),
                          "duration": max(0, int(duration_seconds))},
                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                return resp.status == 200
        except Exception:
            return False

    async def set_group_kick(self, group_id: int, user_id: int, reject_add: bool = False) -> bool:
        """移出群成员（OneBot11 /set_group_kick）。"""
        try:
            async with self.session.post(
                    f"{self.config.HTTP_API_BASE}/set_group_kick",
                    json={"group_id": int(group_id), "user_id": int(user_id), "reject_add_request": bool(reject_add)},
                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                return resp.status == 200
        except Exception:
            return False

    async def set_group_admin(self, group_id: int, user_id: int, enable: bool) -> bool:
        """设为/取消管理员（OneBot11 /set_group_admin）。"""
        try:
            async with self.session.post(
                    f"{self.config.HTTP_API_BASE}/set_group_admin",
                    json={"group_id": int(group_id), "user_id": int(user_id), "enable": bool(enable)},
                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                return resp.status == 200
        except Exception:
            return False

    async def set_friend_add_request(self, flag: str, approve: bool, remark: str = "") -> bool:
        """处理好友请求（OneBot11 /set_friend_add_request）。"""
        try:
            async with self.session.post(
                    f"{self.config.HTTP_API_BASE}/set_friend_add_request",
                    json={"flag": str(flag), "approve": bool(approve), "remark": str(remark)[:30]},
                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                return resp.status == 200
        except Exception:
            return False

    async def set_group_add_request(self, flag: str, approve: bool, reason: str = "") -> bool:
        """处理加群请求（OneBot11 /set_group_add_request）。"""
        try:
            async with self.session.post(
                    f"{self.config.HTTP_API_BASE}/set_group_add_request",
                    json={"flag": str(flag), "approve": bool(approve),
                          "reason": str(reason)[:30]},
                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                return resp.status == 200
        except Exception:
            return False

    # ---------- v1.5：Lagrange 全量 API 端点（OneBot11 标准优先；社区通用/Lagrange 扩展） ----------
    async def send_poke(self, group_id: int, user_id: int) -> dict:
        """戳一戳（群成员）。NapCat/Lagrange 均支持。"""
        return await self._post("/send_poke", {"group_id": int(group_id), "user_id": int(user_id)})

    async def set_react(self, message_id: int, react_type: int) -> dict:
        """消息表情回应（emoji id；NapCat/Lagrange 支持）。"""
        return await self._post("/set_react", {"message_id": int(message_id),
                                               "react_type": int(react_type), "message_seq": None})

    # ---------- v1.7.0 拉格朗日补齐：端点仅登记于此（语义层不感知端点名） ----------

    async def get_friend_msg_history(self, user_id: int, count: int = 20,
                                     message_id: int = 0) -> dict:
        """好友/私聊消息历史（拉格朗日/NapCat 扩展）。"""
        return await self._post("/get_friend_msg_history",
                                {"user_id": int(user_id), "count": int(count),
                                 "message_id": int(message_id)})

    async def send_group_forward_msg(self, group_id: int, messages: list) -> dict:
        """发送群合并转发消息（messages 为 [{name,uin,content}] 列表）。"""
        return await self._post("/send_group_forward_msg",
                                {"group_id": int(group_id), "messages": list(messages)})

    async def send_private_forward_msg(self, user_id: int, messages: list) -> dict:
        """发送私聊合并转发消息。"""
        return await self._post("/send_private_forward_msg",
                                {"user_id": int(user_id), "messages": list(messages)})

    async def get_essence_msg_list(self, group_id: int) -> dict:
        """群精华消息列表。"""
        return await self._post("/get_essence_msg_list", {"group_id": int(group_id)})

    async def get_group_honor_info(self, group_id: int, honor_type: str = "") -> dict:
        """群荣誉信息（honor_type: talkative/performer/legend/strong_newbie/emotion）。"""
        return await self._post("/get_group_honor_info",
                                {"group_id": int(group_id), "honor_type": str(honor_type)})

    async def delete_group_notice(self, group_id: int, notice_id: str) -> dict:
        """删除群公告（拉格朗日端点 _del_group_notice）。"""
        return await self._post("/_del_group_notice",
                                {"group_id": int(group_id), "notice_id": str(notice_id)})

    async def set_group_portrait(self, group_id: int, file: str) -> dict:
        """修改群头像（file 为本地路径/base64；拉格朗日/NapCat 扩展）。"""
        return await self._post("/set_group_portrait",
                                {"group_id": int(group_id), "file": str(file)})

    async def create_group_file_folder(self, group_id: int, name: str) -> dict:
        """创建群文件文件夹。"""
        return await self._post("/create_group_file_folder",
                                {"group_id": int(group_id), "name": str(name)})

    async def delete_group_file(self, group_id: int, file_id: str, busid: int = 0) -> dict:
        """删除群文件。"""
        return await self._post("/delete_group_file",
                                {"group_id": int(group_id), "file_id": str(file_id),
                                 "busid": int(busid)})

    async def delete_group_folder(self, group_id: int, folder_id: str) -> dict:
        """删除群文件文件夹。"""
        return await self._post("/delete_group_folder",
                                {"group_id": int(group_id), "folder_id": str(folder_id)})

    async def move_group_file(self, group_id: int, file_id: str, busid: int = 0,
                              target_folder_id: str = "") -> dict:
        """移动群文件到目标文件夹。"""
        return await self._post("/move_group_file",
                                {"group_id": int(group_id), "file_id": str(file_id),
                                 "busid": int(busid), "target_folder_id": str(target_folder_id)})

    async def rename_group_file_folder(self, group_id: int, folder_id: str, name: str) -> dict:
        """重命名群文件文件夹。"""
        return await self._post("/rename_group_file_folder",
                                {"group_id": int(group_id), "folder_id": str(folder_id),
                                 "name": str(name)})

    async def get_group_info(self, group_id: int, no_cache: bool = False) -> dict:
        """群信息。"""
        return await self._post("/get_group_info",
                                {"group_id": int(group_id), "no_cache": bool(no_cache)})

    async def get_group_list(self, no_cache: bool = False) -> dict:
        """群列表。"""
        return await self._post("/get_group_list", {"no_cache": bool(no_cache)})

    async def friend_poke(self, user_id: int) -> dict:
        """私聊戳一戳（拉格朗日端点 friend_poke）。"""
        return await self._post("/friend_poke", {"user_id": int(user_id)})

    async def set_group_reaction(self, message_id: int, react_type: int,
                                 is_emoji_id: bool = False) -> dict:
        """消息回应（拉格朗日端点 set_group_reaction；与 set_react 参数同构便于回退）。"""
        return await self._post("/set_group_reaction",
                                {"message_id": int(message_id), "code": int(react_type),
                                 "is_emoji_id": bool(is_emoji_id), "message_seq": None})

    async def set_group_whole_ban(self, group_id: int, enable: bool) -> dict:
        return await self._post("/set_group_whole_ban",
                                {"group_id": int(group_id), "enable": bool(enable)})

    async def set_group_name(self, group_id: int, name: str) -> dict:
        return await self._post("/set_group_name",
                                {"group_id": int(group_id), "name": str(name)[:30]})

    async def set_group_card(self, group_id: int, user_id: int, card: str) -> dict:
        return await self._post("/set_group_card", {"group_id": int(group_id),
                                                    "user_id": int(user_id),
                                                    "card": str(card)[:20]})

    async def set_group_special_title(self, group_id: int, user_id: int, title: str) -> dict:
        return await self._post("/set_group_special_title", {"group_id": int(group_id),
                                                             "user_id": int(user_id),
                                                             "title": str(title)[:12]})

    async def send_group_notice(self, group_id: int, content: str, image: str = "") -> dict:
        body = {"group_id": int(group_id), "content": str(content)[:2000]}
        if image:
            body["image"] = str(image)[:300]
        return await self._post("/send_group_notice", body)

    async def get_group_notice(self, group_id: int) -> dict:
        return await self._post("/get_group_notice", {"group_id": int(group_id)})

    async def get_group_root_files(self, group_id: int) -> dict:
        return await self._post("/get_group_root_files", {"group_id": int(group_id)})

    async def get_group_files_by_folder(self, group_id: int, folder_id: str) -> dict:
        return await self._post("/get_group_files_by_folder",
                                {"group_id": int(group_id), "folder_id": str(folder_id)})

    async def get_group_file_url(self, group_id: int, file_id: str, busid: int) -> dict:
        return await self._post("/get_group_file_url", {"group_id": int(group_id),
                                                        "file_id": str(file_id),
                                                        "busid": int(busid)})

    async def set_essence_msg(self, message_id: int) -> dict:
        return await self._post("/set_essence_msg", {"message_id": int(message_id)})

    async def delete_essence_msg(self, message_id: int) -> dict:
        return await self._post("/delete_essence_msg", {"message_id": int(message_id)})

    async def set_friend_profile_like(self, user_id: int) -> dict:
        return await self._post("/set_friend_profile_like", {"user_id": int(user_id)})

    async def get_friend_list(self) -> dict:
        return await self._post("/get_friend_list", {})

    async def get_login_info(self) -> dict:
        return await self._post("/get_login_info", {})

    async def get_online_clients(self) -> dict:
        return await self._post("/get_online_clients", {})

    async def set_qq_profile(self, nickname: str = "", signature: str = "") -> dict:
        body = {}
        if nickname:
            body["nickname"] = str(nickname)[:20]
        if signature:
            body["signature"] = str(signature)[:20]
        return await self._post("/set_self_profile", body)

    async def get_group_config(self, group_id: int) -> dict:
        """群配置读取（Lagrange/Lagrange.OneBot 独有扩展；NapCat 通常无此端点）。"""
        return await self._post("/get_group_config", {"group_id": int(group_id)})

    async def set_group_config(self, group_id: int, **kwargs) -> dict:
        """群配置修改（Lagrange 独有；可用键以网关为准：welcome_text/approval 等）。"""
        return await self._post("/set_group_config",
                                {"group_id": int(group_id), **{k: v for k, v in kwargs.items()
                                                               if k != "group_id"}})

    async def get_group_res(self, group_id: int, res_type: str) -> dict:
        """群资源（头像直链等；Lagrange 独有）。res_type: small_head/great_head。"""
        return await self._post("/get_group_res", {"group_id": int(group_id), "group_res": res_type})

    async def send_private_message(self, user_id: int, message: str) -> bool:
        if not message:
            return False
        url = f"{self.config.HTTP_API_BASE}/send_private_msg"
        payload = {"user_id": user_id, "message": message}
        try:
            async with self.session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    _M_SEND_FAIL.inc({"target": "private"})
                    return False
                data = await resp.json()
                ok = data.get("retcode") == 0
                if not ok:
                    _M_SEND_FAIL.inc({"target": "private"})
                return ok
        except Exception:
            _M_SEND_FAIL.inc({"target": "private"})
            return False
