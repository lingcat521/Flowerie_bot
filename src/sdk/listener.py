"""Event Listener：统一事件注册与分发（进程内）。

- 支持 message / notice / request / lifecycle 类型
- listener 异常隔离：一个 listener 抛错不拖垮其他 listener
- priority：数字大者先执行（与 Matcher 一致）
- event.stop()：阻断后续低优先级 listener（本分发表内）
- shutdown()：正确结束（清空注册表）
"""
from typing import Callable, List, Optional


# 生命周期与边界（road.txt §六）：
# - 本模块是**进程内**的事件分发器：谁构造谁负责（register/on 后自行 shutdown），
#   不持有全局注册表，也不跨进程；
# - 它不是插件间通信通道：跨插件的 call/event 走 Plugin Bus / Core Router
#   （src/plugins/comm.py + manager 的 _engine_op_comm），插件不得直接互相连接；
# - 公开面见 src/sdk/__init__.py 的 __all__（BotEvent 语义，零 OneBot 命名）。
class EventListener:
    def __init__(self, types, handler: Callable, *, priority: int = 0,
                 name: Optional[str] = None, stop: bool = False):
        if isinstance(types, str):
            types = [types]
        self.types = set(types or [])
        self.handler = handler
        self.priority = int(priority)
        self.name = name or getattr(handler, "__name__", "listener")
        self.stop = bool(stop)

    def accepts(self, event) -> bool:
        return event.kind in self.types


class EventDispatcher:
    """事件分发器（进程内多监听器）。"""

    def __init__(self):
        self._listeners: List[EventListener] = []

    def register(self, listener: EventListener) -> None:
        self._listeners.append(listener)

    def on(self, types, *, priority: int = 0, name: Optional[str] = None, stop: bool = False):
        """装饰器：@dispatcher.on("message", priority=10)"""
        def wrap(func):
            self.register(EventListener(types, func, priority=priority, name=name, stop=stop))
            return func
        return wrap

    async def dispatch(self, event) -> None:
        """按 priority 大者先分发（异常隔离；event.stop 阻断低优先级）。"""
        ordered = sorted(self._listeners, key=lambda lst: lst.priority, reverse=True)
        for listener in ordered:
            if event.stopped:
                break
            if not listener.accepts(event):
                continue
            try:
                await listener.handler(event)
            except Exception:  # noqa: BLE001 - 单 listener 失败不拖垮其他
                continue
            if listener.stop or event.stopped:
                break

    @property
    def count(self) -> int:
        return len(self._listeners)

    def shutdown(self) -> None:
        self._listeners.clear()
