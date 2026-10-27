

from contextvars import ContextVar
from typing import Optional

from src.config import Settings
from src.services.memory_manager import MemoryManager
from src.services.prompt_manager import PromptManager
from src.services.sender import Sender
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)

# 当前指令是否来自私聊：由 handle(private_user_id=...) 设置，_reply 据此选发送通道
_PRIVATE_UID: ContextVar = ContextVar("private_uid", default=None)


class CommandHandler:
    """指令处理：用户指令（/help /memory /forget /forget_me）+ 管理员指令（/memory_clear /memory_dump /prompt）。

    从 MessageRouter 拆分（上帝类第二拆）：指令与流程控制解耦，新增指令只需改这里。
    所有指令都只操作调用者自己的记忆（或管理员清群），不经过 LLM，无注入面。
    """

    def __init__(self, config: Settings, sender: Sender, memory_manager: MemoryManager,
                 prompt_manager: PromptManager = None, profile_service=None, admin_service=None):
        self.config = config
        self.sender = sender
        self.memory_manager = memory_manager
        self.prompt_manager = prompt_manager
        # 群友画像服务（/profile 命令的数据源；main 按开关在构造后注入）
        self.profile_service = profile_service
        # 群管理服务（/admin /mute /unmute 的数据源；main 在构造后注入）
        self.admin_service = admin_service

    async def handle(self, text: str, user_id: int, group_id: int,
                     private_user_id: Optional[int] = None) -> bool:
        """处理指令，返回 True 表示已处理（不再走正常聊天流程）。

        private_user_id：私聊入口传当前 QQ（回复走私聊，记忆 key 用虚拟群号）；
        群聊入口不传。用 ContextVar 传递，避免并发下串号。
        """
        token = _PRIVATE_UID.set(private_user_id)
        try:
            return await self._dispatch(text, user_id, group_id)
        finally:
            _PRIVATE_UID.reset(token)

    async def _reply(self, group_id: int, text: str) -> None:
        """按入口通道回复：私聊→send_private_message，群聊→send_group_message。"""
        uid = _PRIVATE_UID.get()
        if uid:
            await self.sender.send_private_message(int(uid), text)
        else:
            await self.sender.send_group_message(group_id, text)

    async def _dispatch(self, text: str, user_id: int, group_id: int) -> bool:
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        is_admin = self.config.ADMIN_QQ_IDS and user_id in self.config.ADMIN_QQ_IDS

        if cmd == "/help":
            await self._cmd_help(group_id, is_admin)
            return True
        if cmd == "/memory":
            await self._cmd_memory(user_id, group_id)
            return True
        if cmd == "/forget":
            await self._cmd_forget(user_id, group_id, arg)
            return True
        if cmd == "/forget_me":
            await self._cmd_forget_me(user_id, group_id)
            return True
        if is_admin and cmd == "/memory_clear":
            await self._cmd_memory_clear(group_id)
            return True
        if is_admin and cmd == "/memory_dump":
            await self._cmd_memory_dump(group_id)
            return True
        if cmd == "/prompt":
            await self._cmd_prompt(arg, user_id, group_id, is_admin)
            return True
        if cmd == "/profile":
            await self._cmd_profile(user_id, group_id)
            return True
        if cmd in ("/admin", "/mute", "/unmute"):
            await self._cmd_admin(cmd, arg, user_id, group_id)
            return True
        return False

    # ---------- 群管理（Bot 自检权限 + 禁言/解禁） ----------
    @staticmethod
    def parse_duration(arg: str, default: int = 600) -> Optional[int]:
        """把 "10m" / "1h" / "90s" / "600" 解析成秒；非法返回 None。

        单位：s 秒 / m 分钟 / h 小时 / d 天（不写单位=秒）；上限 30 天（OneBot 上限）。
        """
        text = str(arg or "").strip().lower()
        if not text:
            return default
        unit = 1
        if text[-1] in ("s", "m", "h", "d"):
            unit = {"s": 1, "m": 60, "h": 3600, "d": 86400}[text[-1]]
            text = text[:-1]
        try:
            value = int(text)
        except ValueError:
            return None
        if value < 0:
            return None
        return min(value * unit, 30 * 24 * 3600)

    async def _cmd_admin(self, cmd: str, arg: str, user_id: int, group_id: int) -> None:
        """/admin（自检权限）· /mute <QQ> [时长] · /unmute <QQ>。

        权限模型：必须由群主/管理员（或 ADMIN_QQ_IDS）发起；Bot 自己也要有管理员权限，
        否则平台会拒绝——这里先自检并给出明确原因，避免"喊了没反应"。
        """
        if int(group_id) <= 0:
            await self._reply(group_id, "私聊里不能执行群管理指令哦，回到群里再用吧")
            return
        service = self.admin_service
        if service is None or not bool(getattr(self.config, "ADMIN_COMMANDS_ENABLED", True)):
            await self._reply(group_id, "群管理指令没有开启哦（ADMIN_COMMANDS_ENABLED）")
            return
        caller_ok = await service.caller_can_manage(group_id, user_id)
        bot_role = await service.bot_role(group_id)
        role_label = {"owner": "群主", "admin": "管理员", "member": "普通成员"}.get(bot_role, "未知")
        if cmd == "/admin":
            mine = await service.member_role(group_id, user_id)
            mine_label = {"owner": "群主", "admin": "管理员", "member": "普通成员"}.get(mine, "未知")
            can = bot_role in ("owner", "admin")
            lines = [
                f"{self.config.BOT_NICKNAME} 在本群的权限：{role_label}"
                + ("（可以禁言/解禁）" if can else "（没有管理权限，禁言会被平台拒绝）"),
                f"你的权限：{mine_label}",
            ]
            if not can:
                lines.append("让群主给花璃一个管理员吧，之后才能执行 /mute")
            await self._reply(group_id, "\n".join(lines))
            return
        if not caller_ok:
            await self._reply(group_id, "只有群主/管理员能使用这条指令哦")
            return
        if bot_role not in ("owner", "admin"):
            await self._reply(
                group_id,
                f"花璃在本群没有管理权限（当前：{role_label}），禁言会被平台拒绝；先请群主授予管理员")
            return
        parts = arg.split(maxsplit=1)
        try:
            target = int(parts[0])
        except (IndexError, ValueError):
            await self._reply(
                group_id, "用法：/mute QQ号 [时长]（如 /mute 123456 10m）；/unmute QQ号")
            return
        if target <= 0 or target == int(getattr(self.config, "BOT_QQ", 0) or 0):
            await self._reply(group_id, "这个 QQ 号不能禁言哦")
            return
        if cmd == "/unmute":
            duration = 0
        else:
            duration = self.parse_duration(parts[1] if len(parts) > 1 else "", default=600)
            if duration is None:
                await self._reply(
                    group_id, "时长写法：10m（分钟）/ 1h / 90s / 600（秒）；上限 30 天")
                return
        result = await service.ban(group_id, target, duration)
        if result.get("ok"):
            if duration == 0:
                await self._reply(group_id, f"已解除 {target} 的禁言")
            else:
                await self._reply(
                    group_id, f"已禁言 {target}，时长 {duration} 秒（约 {duration // 60} 分钟）")
        else:
            await self._reply(
                group_id, f"操作失败：{str(result.get('error') or '平台返回失败')[:120]}")

    # ---------- 自定义 Prompt ----------
    async def _cmd_prompt(self, arg: str, user_id: int, group_id: int, is_admin: bool) -> None:
        """/prompt 命令族：查看/设置/重置全局与群聊 Prompt（管理员才能修改）。"""
        if self.prompt_manager is None:
            await self._reply(group_id, "本实例未启用自定义 Prompt 功能")
            return
        parts = arg.split(maxsplit=1)
        sub = parts[0] if parts else ""
        rest = parts[1].strip() if len(parts) > 1 else ""

        if sub in ("", "show"):
            # 查看当前生效 Prompt
            effective = self.prompt_manager.get_effective_prompt(group_id)
            if not effective:
                await self._reply(group_id, "当前没有自定义 Prompt（使用内置人设）")
            else:
                await self._reply(group_id, f"当前生效 Prompt：{effective[:200]}")
            return
        if sub == "group" and not rest:
            # /prompt group show
            gp = self.prompt_manager.get_group_prompt(group_id)
            if not gp:
                await self._reply(group_id, "本群未设置 Prompt（使用全局/内置）")
            else:
                await self._reply(group_id, f"本群 Prompt：{gp[:200]}")
            return
        if not is_admin:
            await self._reply(group_id, "只有管理员能修改 Prompt 哦")
            return
        if sub == "set":
            if not rest:
                await self._reply(group_id, "用法：/prompt set <内容>（设置全局 Prompt）")
                return
            try:
                self.prompt_manager.set_global_prompt(rest)
                await self._reply(group_id, "全局 Prompt 已更新，立即生效")
            except ValueError as e:
                await self._reply(group_id, str(e))
            return
        if sub == "reset":
            self.prompt_manager.reset_global_prompt()
            await self._reply(group_id, "全局 Prompt 已重置（回退到内置人设）")
            return
        if sub == "group":
            gsub = rest.split(maxsplit=1)[0] if rest else ""
            grest = rest.split(maxsplit=1)[1].strip() if " " in rest else ""
            if gsub == "set":
                if not grest:
                    await self._reply(group_id, "用法：/prompt group set <内容>（设置本群 Prompt）")
                    return
                try:
                    self.prompt_manager.set_group_prompt(group_id, grest)
                    await self._reply(group_id, "本群 Prompt 已更新，立即生效")
                except ValueError as e:
                    await self._reply(group_id, str(e))
                return
            if gsub == "reset":
                self.prompt_manager.reset_group_prompt(group_id)
                await self._reply(group_id, "本群 Prompt 已重置（回退到全局/内置）")
                return
            await self._reply(group_id, "用法：/prompt group set <内容> | /prompt group reset")
            return
        await self._reply(
            group_id,
            "用法：/prompt show | /prompt set <内容> | /prompt reset | /prompt group set <内容> | /prompt group reset",
        )

    # ---------- 各指令实现 ----------
    async def _cmd_help(self, group_id: int, is_admin: bool) -> None:
        nick = self.config.BOT_NICKNAME
        lines = [
            f"{nick}指令菜单：",
            "/help 显示本菜单",
            "/memory 看看我记住了你什么",
            "/forget 关键词 删掉包含该词的记忆",
            "/forget_me 清空我对你的全部记忆",
            "/profile 看看我对你的群友画像",
            "/admin 看看花璃和你在本群的权限",
            "/mute QQ号 [时长] 禁言（如 /mute 123456 10m）",
            "/unmute QQ号 解除禁言",
        ]
        if is_admin:
            lines.append("/memory_clear 清空本群所有记忆（管理员）")
            lines.append("/memory_dump 导出本群记忆（管理员）")
        lines.append(f"另外 @{self.config.BOT_NICKNAME} 或在群里聊天就有机会被{self.config.BOT_NICKNAME}接话～")
        await self._reply(group_id, "\n".join(lines))

    async def _cmd_memory(self, user_id: int, group_id: int) -> None:
        notes = self.memory_manager.get_user_notes(user_id, group_id)
        if not notes:
            await self._reply(group_id, "关于你的记忆：目前一条都没有哦")
        else:
            snippet = "；".join(notes[-10:])[:200]
            await self._reply(group_id, f"关于你的记忆：{snippet}")

    async def _cmd_forget(self, user_id: int, group_id: int, arg: str) -> None:
        if not arg:
            await self._reply(group_id, "用法：/forget 关键词（删除包含该词的记忆）")
            return
        removed = await self.memory_manager.remove_notes_containing(user_id, group_id, arg)
        if removed:
            await self._reply(group_id, f"已删除 {removed} 条包含「{arg[:20]}」的记忆")
        else:
            await self._reply(group_id, f"没找到包含「{arg[:20]}」的记忆")

    async def _cmd_forget_me(self, user_id: int, group_id: int) -> None:
        removed = await self.memory_manager.clear_user_memory(user_id, group_id)
        if removed:
            await self._reply(group_id, f"已清空关于你的 {removed} 条记忆")
        else:
            await self._reply(group_id, "你还没有被我记住什么")

    async def _cmd_memory_clear(self, group_id: int) -> None:
        group_cleared = 0
        for uid, gid in self.memory_manager.iter_user_groups():
            if gid == group_id:
                group_cleared += await self.memory_manager.clear_user_memory(uid, group_id)
        await self._reply(group_id, f"已清空本群 {group_cleared} 条记忆")

    async def _cmd_profile(self, user_id: int, group_id: int) -> None:
        """/profile：查看花璃对自己的群友画像（性格/喜好/个人生活/特点）。"""
        if self.profile_service is None or not self.profile_service.enabled():
            await self._reply(group_id, "群友画像功能没有开启哦（PROFILE_ENABLED）")
            return
        desc = self.profile_service.describe(group_id, user_id)
        if not desc:
            await self._reply(group_id, "我还没有记住你的画像，多在群里聊聊吧～")
            return
        await self._reply(group_id, desc[:300])

    async def _cmd_memory_dump(self, group_id: int) -> None:
        lines = []
        for uid, gid in self.memory_manager.iter_user_groups():
            if gid == group_id:
                notes = self.memory_manager.get_user_notes(uid, group_id)
                if notes:
                    lines.append(f"用户{uid}: " + "；".join(notes[-5:])[:100])
        dump = "\n".join(lines) if lines else "本群暂无记忆"
        await self._reply(group_id, dump[:400])
