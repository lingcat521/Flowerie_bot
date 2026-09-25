"""动作通道（Action Channel）：把"协议怎么发"从 MessageSender 剥离到 Adapter 层。

依赖方向（任务书 §16/§17）：services/sender.py（统一出口）→ 本模块（Adapter）→ Transport/Session。
**本模块是唯一读取协议开关（QQ_PROTOCOL / SEND_VIA_WS）的地方**；sender.py 里不再有任何协议分支
（Gate B/O）。行为与重构前**逐字一致**（仅搬移）。

证据：
- Milky action 名与端点：docs/milky-protocol.md（Milky 规范 api/*.ts + 作者实现）；
- 群/私聊撤回是**不同 action**：Lagrange.Milky RecallGroupMessageHandler.cs L36 /
  RecallPrivateMessageHandler.cs L36（入参 message_seq）；SendGroupMessageHandler.cs L41（响应 message_seq）；
- OneBot 11 撤回：/delete_msg {message_id}。
"""
import json

import aiohttp

from src.transport.milky_response import parse_milky_response
from src.transport.onebot_response import parse_onebot_response
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)

# OneBot 端点 → Milky action（原 sender._MILKY_ACTIONS，逐字保留；只许增删需有证据）
_MILKY_ACTIONS = {
    "_del_group_notice": "delete_group_announcement",
    "create_group_file_folder": "create_group_folder",
    "delete_group_file": "delete_group_file",
    "delete_group_folder": "delete_group_folder",
    "friend_poke": "send_friend_nudge",
    "get_essence_msg_list": "get_group_essence_messages",
    "get_friend_list": "get_friend_list",
    "get_friend_msg_history": "get_history_messages",
    "get_group_config": "get_group_info",
    "get_group_file_url": "get_group_file_download_url",
    "get_group_files_by_folder": "get_group_files",
    "get_group_info": "get_group_info",
    "get_group_list": "get_group_list",
    "get_group_notice": "get_group_announcements",
    "get_group_res": "get_resource_temp_url",
    "get_group_root_files": "get_group_files",
    "get_login_info": "get_login_info",
    "get_status": "get_impl_info",
    "move_group_file": "move_group_file",
    "rename_group_file_folder": "rename_group_folder",
    "send_group_msg": "send_group_message",
    "send_group_notice": "send_group_announcement",
    "send_poke": "send_group_nudge",
    "send_private_msg": "send_private_message",
    "set_essence_msg": "set_group_essence_message",
    "set_friend_profile_like": "send_profile_like",
    "set_group_card": "set_group_member_card",
    "set_group_ban": "set_group_member_mute",
    "set_group_kick": "kick_group_member",
    "set_group_admin": "set_group_member_admin",
    "set_group_name": "set_group_name",
    "set_group_portrait": "set_group_avatar",
    "set_group_reaction": "send_group_message_reaction",
    "set_group_special_title": "set_group_member_special_title",
    "set_group_whole_ban": "set_group_whole_mute",
    "set_react": "send_group_message_reaction",
}

# 已确认 Milky 无对应能力的端点：调用时给出明确错误，而不是让协议端回 404
_MILKY_UNSUPPORTED = frozenset({
    "delete_essence_msg",
    "get_group_honor_info",
    "get_online_clients",
    "send_group_forward_msg",
    "send_private_forward_msg",
    "set_friend_add_request",
    "set_group_add_request",
    "set_group_config",
    "set_self_profile",
})


class OneBotHTTPChannel:
    """OneBot 11 HTTP：POST {HTTP_API_BASE}/<endpoint>，响应 {status, retcode, data}。"""

    name = "onebot-http"

    def __init__(self, config, session):
        self.config = config
        self.session = session

    async def post(self, endpoint: str, payload: dict, timeout: float = 10.0) -> dict:
        try:
            async with self.session.post(
                    "%s/%s" % (str(self.config.HTTP_API_BASE).rstrip("/"), endpoint.lstrip("/")),
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status != 200:
                    return {"ok": False, "error": f"HTTP {resp.status}"}
                body = await resp.json(content_type=None)
                # 响应模型见 parse_onebot_response 的 docstring（ok / async / failed 三态）
                return parse_onebot_response(body)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    async def recall(self, message_id: int, scope: str = "group") -> bool:
        """撤回：OneBot 11 /delete_msg {message_id}（保持重构前的直连行为）。"""
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
        except Exception as e:  # noqa: BLE001
            logger.error("message_delete_failed id=%s err=%s", message_id, e,
                         extra={"event": "message_delete_failed"})
            return False


class OneBotWSChannel(OneBotHTTPChannel):
    """OneBot 11 经 WS（action/echo 请求-响应）；失败时**不**回退 HTTP（与重构前一致）。"""

    name = "onebot-ws"

    def __init__(self, config, session, ws_sender):
        super().__init__(config, session)
        self._ws_sender = ws_sender

    async def post(self, endpoint: str, payload: dict, timeout: float = 10.0) -> dict:
        try:
            resp = await self._ws_sender(endpoint.lstrip("/"), payload)
            result = parse_onebot_response(resp)
            if not result.get("ok"):
                result["error"] = "WS " + str(result.get("error"))
            return result
        except Exception as e:  # noqa: BLE001
            logger.error("message_send_action_failed action=%s err=%s", endpoint, e,
                         extra={"event": "message_send_failed", "action": endpoint})
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}


class MilkyHTTPChannel(OneBotHTTPChannel):
    """Milky：POST {MILKY_API_BASE}/api/<action>，Bearer 鉴权；消息必须是段数组。"""

    name = "milky-http"

    async def post(self, endpoint: str, payload: dict, timeout: float = 10.0) -> dict:
        ep = endpoint.lstrip("/")
        if ep in _MILKY_UNSUPPORTED:
            logger.warning("milky_unsupported endpoint=%s", ep,
                           extra={"event": "milky_unsupported"})
            return {"ok": False, "error": "Milky 协议不支持该能力：%s" % ep}
        action = _MILKY_ACTIONS.get(ep, ep)
        url = f"{str(getattr(self.config, 'MILKY_API_BASE', '')).rstrip('/')}/api/{action}"
        # Milky 消息必须是段数组（OutgoingSegment）；字符串自动转 text 段
        _m = payload.get("message")
        if isinstance(_m, str):
            payload = dict(payload)
            payload["message"] = [{"type": "text", "data": {"text": _m}}]
        headers = {"Content-Type": "application/json"}
        tok = str(getattr(self.config, "MILKY_ACCESS_TOKEN", "") or "")
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
        try:
            async with self.session.post(url, json=payload, headers=headers,
                                         timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                body = await resp.text()
                try:
                    j = json.loads(body) if body else {}
                except ValueError:
                    j = {}
                if resp.status != 200:
                    return {"ok": False, "error": f"HTTP {resp.status} {body[:160]}"}
                # Milky 响应模型见 parse_milky_response 的 docstring（与 OneBot 11 不同）
                return parse_milky_response(j)
        except Exception as e:  # noqa: BLE001
            logger.error("milky_action_failed action=%s err=%s", action, e,
                         extra={"event": "message_send_failed", "action": action})
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    async def recall(self, message_id: int, scope: str = "group") -> bool:
        """Milky 撤回：群/私聊是不同 action，入参是 message_seq（证据见模块 docstring）。"""
        action = "recall_private_message" if scope == "private" else "recall_group_message"
        res = await self.post(action, {"message_seq": int(message_id)}, timeout=10.0)
        if not res.get("ok"):
            logger.error("message_delete_failed id=%s err=%s", message_id, res.get("error"),
                         extra={"event": "message_delete_failed"})
        return bool(res.get("ok"))


def _ws_enabled(config, ws_sender) -> bool:
    """SEND_VIA_WS 解析（false/true/auto；兼容旧布尔配置）——与重构前逐字一致。"""
    raw = getattr(config, "SEND_VIA_WS", "auto")
    if raw is False or raw is None or raw is True:
        mode = "true" if raw is True else "false"
    else:
        mode = str(raw).strip().lower()
    if mode == "false":
        return False
    if mode == "true":
        return bool(ws_sender)
    return bool(ws_sender)  # auto：WS 优先（不可用时按旧行为直接报错，不静默换通道）


def make_action_channel(config, session, ws_sender=None) -> OneBotHTTPChannel:
    """组合根：按配置选择动作通道。**唯一**读取协议开关的位置。"""
    if str(getattr(config, "QQ_PROTOCOL", "onebot")).lower() == "milky":
        return MilkyHTTPChannel(config, session)
    if _ws_enabled(config, ws_sender):
        return OneBotWSChannel(config, session, ws_sender)
    return OneBotHTTPChannel(config, session)
