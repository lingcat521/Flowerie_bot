"""中层：BotAdapter 平台无关接口（领域语义，无 OneBot 依赖）。

SDK 只依赖本接口；下层（src/adapters/onebot/）提供 OneBot 实现。
换平台 = 新增一个 Adapter 实现，中层/上层零改动。
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from src.sdk.errors import UnsupportedOperationError
from src.sdk.message import BotMessage


class BotAdapter(ABC):
    """平台无关能力接口（最小能力集）。"""

    @abstractmethod
    async def send(self, target: str, target_id: int, message,
                   reply_id: Optional[int] = None) -> int:
        """发送（target: group/private）；message: str/BotMessage；返回 message_id。"""

    @abstractmethod
    async def recall(self, message_id: int) -> None:
        """撤回。"""

    @abstractmethod
    async def get_message(self, message_id: int) -> BotMessage:
        """消息详情（领域消息）。"""

    @abstractmethod
    async def get_user_info(self, user_id: int) -> Dict[str, Any]:
        """用户信息。"""

    @abstractmethod
    async def get_group_info(self, group_id: int) -> Dict[str, Any]:
        """群信息。"""

    @abstractmethod
    async def get_group_member(self, group_id: int, user_id: int) -> Dict[str, Any]:
        """群成员信息（role: owner/admin/member）。"""

    @abstractmethod
    async def get_group_members(self, group_id: int) -> List[Dict[str, Any]]:
        """群成员列表。"""

    @abstractmethod
    async def mute(self, group_id: int, user_id: int, duration_seconds: int) -> None:
        """禁言（0=解除）。"""

    @abstractmethod
    async def kick(self, group_id: int, user_id: int) -> None:
        """移出群成员。"""

    async def get_context(self, group_id: int, max_messages: int = 10) -> List[Dict[str, Any]]:
        """近期上下文（默认=历史；下层/领域数据源可覆盖）。"""
        raise UnsupportedOperationError("当前 Adapter 未实现 get_context")

    # ---------- 私聊（v2.14.0；默认不支持，子类按需实现） ----------
    async def get_private_history(self, user_id: int, count: int = 20) -> Any:
        """好友/私聊最近消息（各协议实现不同；默认不支持）。"""
        raise UnsupportedOperationError("当前 Adapter 未实现 get_private_history")

    # ---------- 群管理员扩展（v2.10；默认不支持，子类按需实现） ----------
    async def set_group_admin(self, group_id: int, user_id: int, enable: bool = True) -> Any:
        """设置/取消群管理员。"""
        raise UnsupportedOperationError("当前 Adapter 未实现 set_group_admin")

    async def kick_with_reject(self, group_id: int, user_id: int) -> Any:
        """移出群成员并拒绝再次加群。"""
        raise UnsupportedOperationError("当前 Adapter 未实现 kick_with_reject")

    async def get_group_shut_list(self, group_id: int) -> Any:
        """当前被禁言成员列表。"""
        raise UnsupportedOperationError("当前 Adapter 未实现 get_group_shut_list")

    async def quit_group(self, group_id: int, dismiss: bool = False) -> Any:
        """Bot 退出群聊（群主且 dismiss=True 时解散）。"""
        raise UnsupportedOperationError("当前 Adapter 未实现 quit_group")

    # ---------- QQ空间（v2.10；默认不支持，子类按需实现） ----------
    async def qzone_publish(self, content: str, images: List[str],
                            ugc_right: int = 1, target_uins: Optional[List[int]] = None) -> Any:
        """发表 QQ空间说说（返回 {ok, tid}）。"""
        raise UnsupportedOperationError("当前 Adapter 未实现 qzone_publish")

    async def qzone_delete(self, tid: str) -> Any:
        """删除 QQ空间说说（按 tid）。"""
        raise UnsupportedOperationError("当前 Adapter 未实现 qzone_delete")
