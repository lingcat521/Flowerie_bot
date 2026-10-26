"""Bot 群管理员操作服务（OneBot 11 群管动作统一入口，供 Web UI / SDK / 插件复用）。

设计要点：
- 只做"参数归一化 + 调用 + 错误收敛"，协议差异全在 Adapter 层（Gate B/O）；
- 每个操作返回统一结构 {ok: bool, error?: str, result?: Any}，不向上抛异常（管理页零崩溃）；
- 操作清单 OPERATIONS 是面板下拉与文档的单一事实来源，新增操作只改这里。

对应 NapCat 实测动作（见 docs/reference/napcat-admin-qzone.md）：
set_group_admin / set_group_ban / set_group_kick / set_group_card / set_group_name /
set_group_special_title / set_group_whole_ban / get_group_shut_list / set_group_leave
"""
from typing import Any, Dict, List, Optional

from src.utils.logging_setup import get_logger

logger = get_logger(__name__)

# (操作名, 显示名, 是否需要 user_id, 额外参数, 说明)
OPERATIONS: List[tuple] = [
    ("set_admin", "设为管理员", True, "none", "把群成员设为管理员"),
    ("unset_admin", "取消管理员", True, "none", "撤销群成员的管理员身份"),
    ("ban", "禁言", True, "duration", "禁言指定成员（秒，0=解除）"),
    ("unban", "解除禁言", True, "none", "解除指定成员的禁言"),
    ("kick", "移出群聊", True, "reject", "把成员踢出群聊（可选拒绝再次加群）"),
    ("set_card", "修改群名片", True, "card", "设置成员群名片（空=清除）"),
    ("set_group_name", "修改群名称", False, "group_name", "修改群名称"),
    ("set_title", "设置专属头衔", True, "title", "设置成员专属头衔（空=清除）"),
    ("whole_ban", "开启全员禁言", False, "none", "开启全群禁言"),
    ("whole_unban", "关闭全员禁言", False, "none", "关闭全群禁言"),
    ("shut_list", "查看禁言列表", False, "none", "读取当前被禁言成员"),
    ("leave", "退出群聊", False, "dismiss", "Bot 退出群聊（群主=解散群）"),
]

OP_BY_NAME = {op[0]: op for op in OPERATIONS}


class GroupAdminService:
    """群管理员操作门面：所有方法返回 {ok, error?, result?}。"""

    def __init__(self, adapter, config=None):
        self._adapter = adapter
        self.config = config

    def enabled(self) -> bool:
        """是否启用管理控制台（默认开启；关=面板提示不可用，SDK 直接调用不受限）。"""
        return bool(getattr(self.config, "ADMIN_CONSOLE_ENABLED", True))

    def operations(self) -> List[Dict[str, Any]]:
        """操作清单（面板/文档共用）。"""
        return [
            {"op": op, "label": label, "need_user": need_user, "extra": extra, "desc": desc}
            for op, label, need_user, extra, desc in OPERATIONS
        ]

    async def _run(self, name: str, coro) -> Dict[str, Any]:
        try:
            result = await coro
        except Exception as e:  # noqa: BLE001 —— 管理操作失败不能打崩面板
            logger.warning("group_admin_failed op=%s err=%s: %s", name, type(e).__name__, e,
                           extra={"event": "group_admin_failed"})
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        if isinstance(result, dict) and result.get("ok") is False:
            return {"ok": False, "error": str(result.get("error") or "平台返回失败")}
        logger.info("group_admin_done op=%s", name, extra={"event": "group_admin_done"})
        return {"ok": True, "result": result}

    async def execute(self, op: str, group_id: int, user_id: Optional[int] = None,
                      duration: int = 0, card: str = "", group_name: str = "",
                      title: str = "", reject: bool = False, dismiss: bool = False) -> Dict[str, Any]:
        """面板/API 统一入口：按操作名分发（参数校验失败返回 ok=False）。"""
        if op not in OP_BY_NAME:
            return {"ok": False, "error": f"未知操作：{op}"}
        try:
            gid = int(group_id)
        except (TypeError, ValueError):
            return {"ok": False, "error": "群号必须是数字"}
        if gid <= 0:
            return {"ok": False, "error": "群号必须是正整数"}
        need_user = OP_BY_NAME[op][2]
        uid: Optional[int] = None
        if need_user:
            try:
                uid = int(user_id)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return {"ok": False, "error": "该操作需要有效的成员 QQ 号"}
            if uid <= 0:
                return {"ok": False, "error": "成员 QQ 号必须是正整数"}

        if op == "set_admin":
            return await self.set_admin(gid, uid, True)
        if op == "unset_admin":
            return await self.set_admin(gid, uid, False)
        if op == "ban":
            return await self.ban(gid, uid, duration)
        if op == "unban":
            return await self.ban(gid, uid, 0)
        if op == "kick":
            return await self.kick(gid, uid, reject=reject)
        if op == "set_card":
            return await self.set_card(gid, uid, card)
        if op == "set_group_name":
            return await self.set_group_name(gid, group_name)
        if op == "set_title":
            return await self.set_special_title(gid, uid, title)
        if op == "whole_ban":
            return await self.whole_ban(gid, True)
        if op == "whole_unban":
            return await self.whole_ban(gid, False)
        if op == "shut_list":
            return await self.shut_list(gid)
        if op == "leave":
            return await self.leave(gid, dismiss=dismiss)
        return {"ok": False, "error": f"未知操作：{op}"}

    # ---------- 具体操作 ----------
    async def set_admin(self, group_id: int, user_id: int, enable: bool = True) -> Dict[str, Any]:
        """设置/取消群管理员（OneBot set_group_admin）。"""
        return await self._run("set_admin", self._adapter.set_group_admin(group_id, user_id, bool(enable)))

    async def ban(self, group_id: int, user_id: int, duration: int = 0) -> Dict[str, Any]:
        """群禁言（秒；0=解除）。"""
        dur = max(0, int(duration or 0))
        return await self._run("ban", self._adapter.mute(group_id, user_id, dur))

    async def kick(self, group_id: int, user_id: int, reject: bool = False) -> Dict[str, Any]:
        """移出群成员（reject=True 拒绝再次加群）。"""
        if reject:
            return await self._run("kick", self._adapter.kick_with_reject(group_id, user_id))
        return await self._run("kick", self._adapter.kick(group_id, user_id))

    async def set_card(self, group_id: int, user_id: int, card: str = "") -> Dict[str, Any]:
        """修改群名片（空字符串=清除）。"""
        return await self._run("set_card", self._adapter.group_card(group_id, user_id, str(card or "")))

    async def set_group_name(self, group_id: int, name: str = "") -> Dict[str, Any]:
        """修改群名称。"""
        clean = str(name or "").strip()
        if not clean:
            return {"ok": False, "error": "群名称不能为空"}
        return await self._run("set_group_name", self._adapter.group_rename(group_id, clean))

    async def set_special_title(self, group_id: int, user_id: int, title: str = "") -> Dict[str, Any]:
        """设置专属头衔（空字符串=清除）。"""
        return await self._run("set_title", self._adapter.group_title(group_id, user_id, str(title or "")))

    async def whole_ban(self, group_id: int, enable: bool) -> Dict[str, Any]:
        """全员禁言开关。"""
        return await self._run("whole_ban", self._adapter.group_whole_ban(group_id, bool(enable)))

    async def shut_list(self, group_id: int) -> Dict[str, Any]:
        """当前禁言成员列表。"""
        return await self._run("shut_list", self._adapter.get_group_shut_list(group_id))

    async def leave(self, group_id: int, dismiss: bool = False) -> Dict[str, Any]:
        """Bot 退出群聊（群主且 dismiss=True 时解散）。"""
        return await self._run("leave", self._adapter.quit_group(group_id, bool(dismiss)))
