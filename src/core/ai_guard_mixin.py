"""AI 准入守卫 mixin：AI 开关 / 预算闸门 / 引战检测准入（防上帝类：从 MessageRouter 拆出）。

宿主（MessageRouter）需提供 config 与 ai_gateway。
"""
from typing import Optional, Tuple


class AiGuardMixin:
    async def guarded_chat(self, group_id: int, user_id: int,
                           **kwargs) -> Tuple[Optional[str], Optional[str], bool]:
        """统一 AI 对话入口（委托 AiGateway：熔断/预算/人格/知识/重试）。

        AI_ENABLED=false：不执行 AI 回复（普通功能/记忆/知识不受影响）。
        """
        if not getattr(self.config, "AI_ENABLED", True):
            return None, None, False
        return await self.ai_gateway.guarded_chat(group_id, user_id, **kwargs)

    async def _ai_allowed(self, group_id: int, user_id: int, user_interval: bool = True) -> bool:
        """预算闸门（委托 AiGateway）。"""
        return await self.ai_gateway._ai_allowed(group_id, user_id, user_interval=user_interval)

    async def guarded_is_toxic(self, group_id: int, user_id: int, text: str) -> bool:
        """引战检测准入（委托 AiGateway）。"""
        return await self.ai_gateway.guarded_is_toxic(group_id, user_id, text)
