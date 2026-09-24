"""多条回复的发送编排（协议无关）。

本模块只做一件事：把 ReplyPlan 里的若干条消息，按计划的间隔策略**逐条**交给
一个「发送单条」的 async 回调，并汇总结果。它不关心 OneBot / Milky / HTTP：
调用方把「怎么发一条」传进来即可 —— 于是所有协议天然共用同一套 Multi-Reply 逻辑。

失败策略（任务书 §12）：
- stop（默认）：某条失败即停止后续，抛 MultiReplyError（已发出的不回滚，如实告知）；
- continue：记录失败继续发剩下的，最终把失败明细一并抛出。
"""
import asyncio
from typing import Awaitable, Callable, List, Optional, Sequence

from src.core.reply_plan import ReplyPlan


class MultiReplyError(Exception):
    """多条回复过程中出错（携带已发送条数与失败下标）。"""

    def __init__(self, message: str, sent: Sequence[int], failed_index: int):
        super().__init__(message)
        self.sent = list(sent)
        self.failed_index = failed_index


async def send_plan(
    plan: ReplyPlan,
    send_one: Callable[[str, int], Awaitable[object]],
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    on_sent: Optional[Callable[[int, object], None]] = None,
    on_error: str = "stop",
    rng=None,
) -> List[object]:
    """按计划逐条发送，返回每条消息的发送结果（顺序对应）。

    send_one(message, index) -> 任意发送结果（message_id 等）
    on_sent(index, result)   -> 发送成功后的钩子（记历史/指标用）
    """
    results: List[object] = []
    for i, msg in enumerate(plan.messages):
        delay = plan.delay_before(i, rng)
        if delay > 0:
            await sleep(delay)
        try:
            res = await send_one(msg, i)
        except Exception as exc:  # noqa: BLE001 - 逐条失败要如实上报，不让整轮崩掉
            if on_error == "continue":
                results.append(exc)
                continue
            raise MultiReplyError(
                "第 %d/%d 条发送失败：%s" % (i + 1, len(plan.messages), exc),
                sent=[r for r in results if not isinstance(r, Exception)],
                failed_index=i,
            ) from exc
        results.append(res)
        if on_sent is not None:
            on_sent(i, res)
    return results
