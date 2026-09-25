"""Core Router 与 Plugin Communication Bus（任务书《通信》§十一–§十八、§二十二–§二十三）。

职责边界（§三）：Core 只做 **Routing / Identity / Permission / Serialization / Timeout /
Error / Lifecycle**，不碰任何插件业务逻辑。

    PluginBus.call()   <- 插件 A 的一次 plugin.call
        │
        ├─ 1. 身份：caller 由连接（进程）决定，插件无法自报（§四）
        ├─ 2. 循环保护：hop_count 超限 -> PLUGIN_CALL_LOOP，直接终止（§二十二）
        ├─ 3. Router：解析 target（实例 / 任意健康实例）-> 生命周期结构化错误（§十六/§十七）
        ├─ 4. Permission：plugin.call.<target>[.<method>]（§十四）—— 同语言直连同样要过（§十五）
        ├─ 5. 能力：目标必须声明 plugin.call，否则 METHOD_NOT_FOUND（不撒谎）
        ├─ 6. Trace：trace_id / call_id 全链路传播（§二十三），日志逐跳可见
        └─ 7. 投递 + 超时 + 取消（§十八）：超时返回 TIMEOUT 并向目标发 CANCEL，不占用请求

事件（§九）走同一条总线的另一条方法（plugin.event），广播给所有 READY 且声明了
plugin.event 的实例；RPC 与 Event 是两类消息，不共用响应语义（§十）。
"""
import asyncio
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.plugins import comm
from src.plugins.comm import PluginCommError
from src.plugins.permissions import call_permission_granted, emit_permission_granted
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)

#: 子进程运行时的 status -> §十七 生命周期状态
_STATE_OF_STATUS = {
    "starting": "STARTING",
    "running": "READY",
    "stopping": "STOPPING",
    "stopped": "STOPPED",
    "crashed": "FAILED",
    "unhealthy": "FAILED",
    "error": "FAILED",
}
#: 不可用（崩溃/已停止）与未就绪（启动中/停止中）的分界
_UNAVAILABLE_STATES = ("FAILED", "STOPPED")


def lifecycle_state(runtime: Any) -> str:
    """运行时的生命周期状态（§十七）：未知一律按 STARTING 处理（宁可说未就绪）。"""
    status = str(getattr(runtime, "status", "") or "").lower()
    return _STATE_OF_STATUS.get(status, "STARTING")


class PluginInstance:
    """一个可被路由的插件实例：身份 + 运行时句柄（§四/§十六）。"""

    def __init__(self, identity: Dict[str, Any], runtime: Any):
        self.identity = dict(identity)
        self.runtime = runtime

    @property
    def plugin_id(self) -> str:
        return str(self.identity.get("plugin_id") or "")

    @property
    def instance_id(self) -> str:
        return str(self.identity.get("instance_id") or "")

    @property
    def full_id(self) -> str:
        return comm.format_instance_id(self.plugin_id, self.instance_id)

    @property
    def runtime_name(self) -> str:
        return str(self.identity.get("runtime") or "")

    @property
    def state(self) -> str:
        return lifecycle_state(self.runtime)

    @property
    def healthy(self) -> bool:
        return self.state == "READY"

    def to_dict(self) -> Dict[str, Any]:
        out = dict(self.identity)
        out["state"] = self.state
        out["healthy"] = self.healthy
        return out


class PluginRouter:
    """身份注册表 + 路由决策（§四/§十六/§十七）。

    同一 plugin_id 可以有多个实例（plugin.a#instance1 / #instance2）。当前 Flowerie 一个
    插件一个进程，因此每个插件默认注册一个实例（instance_id 取自 runtime.instance_id）；
    但路由决策本身**不假设只有一个实例** —— 这正是 §十六 要求的「specific instance 或
    any healthy instance」。未来要负载均衡时，只需在注册表里多注册几个实例，不用改调用方。
    """

    def __init__(self) -> None:
        self._instances: Dict[str, PluginInstance] = {}

    # ---------- 注册表 ----------
    def register(self, plugin_id: str, runtime: Any, *, runtime_name: str = "",
                 version: str = "", protocol_version: str = "",
                 instance_id: str = "") -> PluginInstance:
        iid = str(instance_id or getattr(runtime, "instance_id", "") or "0")
        identity = comm.make_identity(
            plugin_id, runtime_name or str(getattr(runtime, "runtime_name", "") or ""),
            version, protocol_version or comm.PROTOCOL_VERSION, iid)
        inst = PluginInstance(identity, runtime)
        self._instances[inst.full_id] = inst
        logger.debug("comm_register instance=%s runtime=%s", inst.full_id, identity.get("runtime"))
        return inst

    def unregister(self, plugin_id: str, instance_id: str = "") -> None:
        if instance_id:
            self._instances.pop(comm.format_instance_id(plugin_id, instance_id), None)
            return
        for key in [k for k, v in self._instances.items() if v.plugin_id == plugin_id]:
            self._instances.pop(key, None)

    def instances_of(self, plugin_id: str) -> List[PluginInstance]:
        return [v for v in self._instances.values() if v.plugin_id == plugin_id]

    def all_instances(self) -> List[PluginInstance]:
        return list(self._instances.values())

    def get(self, plugin_id: str, instance_id: str = "") -> Optional[PluginInstance]:
        if instance_id:
            return self._instances.get(comm.format_instance_id(plugin_id, instance_id))
        for inst in self.instances_of(plugin_id):
            if inst.healthy:
                return inst
        found = self.instances_of(plugin_id)
        return found[0] if found else None

    # ---------- 路由（§十六/§十七） ----------
    def resolve(self, target: Any) -> PluginInstance:
        """解析目标 -> 实例；任何失败都抛**结构化**错误（§十七 必须返回结构化错误）。"""
        plugin_id, instance_id = comm.parse_target(target)
        if not plugin_id:
            raise PluginCommError.invalid("target 为空（需要 plugin_id 或 plugin_id#instance）")
        instances = self.instances_of(plugin_id)
        if not instances:
            raise PluginCommError.not_found(plugin_id, instance_id)
        if instance_id:
            exact = self._instances.get(comm.format_instance_id(plugin_id, instance_id))
            if exact is None:
                raise PluginCommError(
                    "PLUGIN_NOT_FOUND",
                    "目标实例不存在: %s#%s" % (plugin_id, instance_id),
                    {"plugin_id": plugin_id, "instance_id": instance_id,
                     "available": sorted(i.instance_id for i in instances)})
            return self._ensure_usable(exact)
        ready = [i for i in instances if i.healthy]
        if ready:
            return ready[0]                      # 任意健康实例（§十六）
        return self._ensure_usable(instances[0])

    @staticmethod
    def _ensure_usable(inst: PluginInstance) -> PluginInstance:
        state = inst.state
        if state in _UNAVAILABLE_STATES:
            raise PluginCommError.unavailable(inst.full_id, state)
        if state != "READY":
            raise PluginCommError.not_ready(inst.full_id, state)
        return inst

    # ---------- 路由策略（§十一/§十三） ----------
    @staticmethod
    def route_for(source_runtime: str, target_runtime: str, policy: str = comm.ROUTE_AUTO) -> str:
        """策略 -> 实际路径。**跨语言一律 core**（§十二）。

        同语言时是否真的能走 local 取决于两个插件是否在**同一个 runtime 进程**里：
        当前 Flowerie 一个插件一个子进程，所以引擎侧永远只能给 core；SDK 的 Local Registry
        若命中（同进程托管多插件）会自行短路，那时不会走到这里。这个函数不撒谎：
        它只在确实同进程时才可能返回 local，而引擎侧没有这种情况。
        """
        if policy == comm.ROUTE_CORE:
            return comm.ROUTE_CORE
        if policy == comm.ROUTE_LOCAL:
            # 引擎侧无法提供 local 通道 -> 明确回落 core（绝不静默假装走了 local）
            return comm.ROUTE_CORE
        return comm.ROUTE_CORE

    # ---------- 权限（§十四/§十五） ----------
    @staticmethod
    def authorize_call(approved: Iterable[str], target: str, method: str) -> None:
        if not call_permission_granted(approved, target, method):
            raise PluginCommError.denied(str(target), str(method), sorted(set(approved or ())))

    @staticmethod
    def authorize_emit(approved: Iterable[str]) -> None:
        if not emit_permission_granted(approved):
            raise PluginCommError(
                "PERMISSION_DENIED", "缺少事件广播权限 plugin.emit",
                {"required": ["plugin.emit"], "granted": sorted(set(approved or ()))})


class PluginBus:
    """Plugin Communication Bus：投递 / 超时 / 取消 / 事件广播 / 统计。

    统计是给验收报告用的**真实数字**（不是估计）：每次调用、拒绝、超时、取消、环保护
    都会落到这里，报告直接读 snapshot()。
    """

    def __init__(self, router: PluginRouter):
        self.router = router
        self._inflight: Dict[str, str] = {}         # request_id -> 目标实例全名
        self._stats: Dict[str, Any] = {
            "calls": 0, "calls_ok": 0, "calls_error": 0, "denied": 0,
            "timeouts": 0, "cancels_sent": 0, "cancels_acked": 0, "loop_aborted": 0,
            "events": 0, "events_delivered": 0, "events_failed": 0,
            "by_error_code": {}, "by_route": {}, "latency_ms_total": 0.0,
        }

    # ---------- 统计 ----------
    def _bump(self, key: str, delta: int = 1) -> None:
        self._stats[key] = int(self._stats.get(key, 0)) + delta

    def _bump_code(self, code: str) -> None:
        table = self._stats["by_error_code"]
        table[code] = int(table.get(code, 0)) + 1

    def snapshot(self) -> Dict[str, Any]:
        out = dict(self._stats)
        out["by_error_code"] = dict(self._stats["by_error_code"])
        out["by_route"] = dict(self._stats["by_route"])
        return out

    # ---------- 调用（§五/§六/§七/§十八/§二十二） ----------
    async def call(self, caller_id: str, request: Dict[str, Any], *,
                   approved: Iterable[str] = ()) -> Dict[str, Any]:
        """执行一次 plugin.call，返回**响应模型**（§七）——失败也是响应，不是异常。

        为什么返回响应而不是抛异常：调用方可能是任意语言，异常无法跨语言；统一响应模型
        才能让五种 SDK 各自映射成自己的异常/Result（§七）。引擎内部调用的地方（测试、
        管理面）可以直接看 code。
        """
        err = comm.validate_request(request)
        if err is not None:
            self._bump("calls_error")
            self._bump_code(err.code)
            return err.to_response(str((request or {}).get("request_id") or ""))

        request_id = str(request.get("request_id") or "")
        method = str(request.get("method") or "")
        target_spec = request.get("target")
        plugin_id, _instance_id = comm.parse_target(target_spec)
        trace_id = str(request.get("trace_id") or comm.new_trace_id())
        hop_count = int(request.get("hop_count") or 0)
        route_policy = str(request.get("route") or comm.ROUTE_AUTO)
        timeout_ms = comm.normalize_timeout_ms(request.get("timeout"))
        self._bump("calls")

        # 1) 循环保护（§二十二）：超过最大 hop 直接终止，且**不再向下转发**
        if comm.hop_exceeded(hop_count):
            e = PluginCommError.loop(hop_count, trace_id)
            self._bump("loop_aborted")
            self._bump_code(e.code)
            logger.warning("plugin_call_loop trace=%s caller=%s target=%s hop=%d",
                           trace_id, caller_id, plugin_id, hop_count,
                           extra={"event": "plugin_comm"})
            return comm.make_error_response(request_id, e)

        # 2) 身份 + 路由 + 权限 + 能力
        try:
            source = self._identity_of(caller_id)
            target = self.router.resolve(target_spec)
            self.router.authorize_call(approved, target.plugin_id, method)
            route = PluginRouter.route_for(str(source.get("runtime") or ""),
                                           target.runtime_name, route_policy)
            if not self._supports(target, "plugin.call"):
                raise PluginCommError(
                    "METHOD_NOT_FOUND",
                    "目标插件未声明 plugin.call 能力（无法接收插件间调用）",
                    {"plugin_id": target.plugin_id, "capability": "plugin.call",
                     "capabilities": sorted(self._capabilities_of(target))})
        except PluginCommError as e:
            self._bump("calls_error")
            self._bump_code(e.code)
            if e.code == "PERMISSION_DENIED":
                self._bump("denied")
            logger.warning("plugin_call_rejected code=%s trace=%s caller=%s target=%s reason=%s",
                           e.code, trace_id, caller_id, plugin_id, e.message,
                           extra={"event": "plugin_comm"})
            return comm.make_error_response(request_id, e)

        # 3) 投递给目标（带 trace / hop+1 / 解析后的 target）
        forward = dict(request)
        forward["source"] = source
        forward["target"] = {"plugin_id": target.plugin_id, "runtime": target.runtime_name,
                             "instance_id": target.instance_id}
        forward["trace_id"] = trace_id
        forward["hop_count"] = comm.next_hop(hop_count)
        forward["route"] = route
        forward["timeout"] = timeout_ms
        self._inflight[request_id] = target.full_id
        started = time.monotonic()
        try:
            reply = await self._deliver(target, "plugin.call", forward, timeout_ms)
        except asyncio.TimeoutError:
            self._bump("timeouts")
            self._bump_code("TIMEOUT")
            await self._send_cancel(target, request_id, "caller timeout")
            logger.warning("plugin_call_timeout trace=%s caller=%s target=%s method=%s ms=%d",
                           trace_id, caller_id, target.full_id, method, timeout_ms,
                           extra={"event": "plugin_comm"})
            return comm.make_error_response(
                request_id, PluginCommError.timeout(target.full_id, method, timeout_ms))
        except Exception as e:  # noqa: BLE001 - 传输层异常 -> 结构化 INTERNAL_ERROR/PLUGIN_UNAVAILABLE
            self._bump("calls_error")
            code = comm.LIFECYCLE_ERROR_CODE if target.state in _UNAVAILABLE_STATES \
                else "INTERNAL_ERROR"
            self._bump_code(code)
            return comm.make_error_response(
                request_id, PluginCommError(code, "投递失败: %s: %s" % (type(e).__name__, e),
                                            {"target": target.full_id}))
        finally:
            self._inflight.pop(request_id, None)
            self._stats["latency_ms_total"] += (time.monotonic() - started) * 1000.0

        # 4) 目标返回的是插件自己的响应模型；原样透传（code/message/data 不重写）
        route_table = self._stats["by_route"]
        route_table[route] = int(route_table.get(route, 0)) + 1
        if isinstance(reply, dict) and reply.get("ok") is False:
            e = PluginCommError.from_error(reply.get("error"))
            self._bump("calls_error")
            self._bump_code(e.code)
            logger.info("plugin_call_error trace=%s caller=%s target=%s method=%s code=%s",
                        trace_id, caller_id, target.full_id, method, e.code,
                        extra={"event": "plugin_comm"})
            return comm.make_error_response(request_id, e)
        result = reply.get("result") if isinstance(reply, dict) else reply
        self._bump("calls_ok")
        logger.info("plugin_call_ok trace=%s caller=%s target=%s method=%s route=%s",
                    trace_id, caller_id, target.full_id, method, route,
                    extra={"event": "plugin_comm"})
        return comm.make_response(request_id, result)

    # ---------- 事件广播（§九） ----------
    async def emit(self, caller_id: str, event: Dict[str, Any], *,
                   approved: Iterable[str] = (), timeout_ms: Optional[int] = None) -> Dict[str, Any]:
        """广播一个插件事件。返回 {"ok","delivered","failed"}（不是 RPC 响应，§十）。"""
        err = comm.validate_event(event)
        if err is not None:
            return {"ok": False, "error": err.to_error(), "delivered": 0, "failed": []}
        try:
            self.router.authorize_emit(approved)
        except PluginCommError as e:
            self._bump("denied")
            self._bump_code(e.code)
            return {"ok": False, "error": e.to_error(), "delivered": 0, "failed": []}
        if comm.hop_exceeded(event.get("hop_count")):
            e = PluginCommError.loop(int(event.get("hop_count") or 0),
                                     str(event.get("trace_id") or ""))
            self._bump("loop_aborted")
            self._bump_code(e.code)
            return {"ok": False, "error": e.to_error(), "delivered": 0, "failed": []}

        self._bump("events")
        source = self._identity_of(caller_id)
        forward = dict(event)
        forward["source"] = source
        forward["hop_count"] = comm.next_hop(event.get("hop_count"))
        per_target = comm.normalize_timeout_ms(timeout_ms, comm.DEFAULT_TIMEOUT_MS)
        delivered, failed = 0, []
        for inst in self.router.all_instances():
            if inst.plugin_id == caller_id or not inst.healthy:
                continue
            if not self._supports(inst, "plugin.event"):
                continue
            try:
                await self._deliver(inst, "plugin.event", forward, per_target)
                delivered += 1
            except asyncio.TimeoutError:
                failed.append({"plugin_id": inst.plugin_id, "code": "TIMEOUT"})
            except Exception as e:  # noqa: BLE001 - 单个订阅者失败不影响其它订阅者
                failed.append({"plugin_id": inst.plugin_id, "code": "INTERNAL_ERROR",
                               "message": "%s: %s" % (type(e).__name__, e)})
        self._bump("events_delivered", delivered)
        self._bump("events_failed", len(failed))
        logger.info("plugin_event name=%s trace=%s caller=%s delivered=%d failed=%d",
                    forward.get("name"), forward.get("trace_id"), caller_id, delivered, len(failed),
                    extra={"event": "plugin_comm"})
        return {"ok": True, "delivered": delivered, "failed": failed,
                "trace_id": str(forward.get("trace_id") or "")}

    # ---------- 取消（§十八） ----------
    async def cancel(self, caller_id: str, request_id: str, reason: str = "") -> Dict[str, Any]:
        """取消一次**自己发起的**调用（插件侧 plugin.cancel 走这里）。"""
        rid = str(request_id or "")
        owner = self._inflight.get(rid)
        if not owner:
            return {"ok": False, "error": PluginCommError(
                "CANCELLED", "request_id 不存在或已完成", {"request_id": rid}).to_error()}
        plugin_id, _, instance_id = owner.partition("#")
        inst = self.router.get(plugin_id, instance_id)
        if inst is None:
            return {"ok": False, "error": PluginCommError.not_found(plugin_id, instance_id).to_error()}
        return {"ok": True, "cancelled": await self._send_cancel(inst, rid, str(reason or caller_id)),
                "target": inst.full_id, "request_id": rid}

    async def _send_cancel(self, inst: PluginInstance, request_id: str, reason: str) -> bool:
        """尽力而为地把 CANCEL 送到目标；目标不支持就如实返回 False（不假装成功）。"""
        if not self._supports(inst, "plugin.cancel"):
            return False
        payload = comm.make_cancel(request_id, reason)
        try:
            await self._deliver(inst, "plugin.cancel", payload, 1000, cancel_message=True)
        except asyncio.TimeoutError:
            # CANCEL 已经写进目标的管道，只是目标正忙、没在 1s 内应答 —— 这是"已发出未确认"，
            # 统计必须如实分开记（cancels_sent vs cancels_acked），不能混成一个好看的数
            self._bump("cancels_sent")
            return True
        except Exception:  # noqa: BLE001 - 取消失败不影响调用方已得到的 TIMEOUT
            return False
        self._bump("cancels_sent")
        self._bump("cancels_acked")
        return True

    # ---------- 内部工具 ----------
    def _identity_of(self, plugin_id: str) -> Dict[str, Any]:
        inst = self.router.get(plugin_id)
        if inst is None:
            raise PluginCommError.internal("调用方未注册到 Core Router: %s" % plugin_id,
                                           {"plugin_id": plugin_id})
        return {"plugin_id": inst.plugin_id, "runtime": inst.runtime_name,
                "instance_id": inst.instance_id}

    @staticmethod
    def _capabilities_of(inst: PluginInstance) -> Iterable[str]:
        caps = getattr(inst.runtime, "capabilities", None)
        return caps if caps is not None else ()

    def _supports(self, inst: PluginInstance, method: str) -> bool:
        runtime = inst.runtime
        supports = getattr(runtime, "supports", None)
        if callable(supports):
            try:
                return bool(supports(method))
            except Exception:  # noqa: BLE001
                return False
        return method in self._capabilities_of(inst)

    @staticmethod
    async def _deliver(inst: PluginInstance, method: str, params: Dict[str, Any],
                       timeout_ms: int, cancel_message: bool = False) -> Dict[str, Any]:
        """把一条 CALL/EVENT/CANCEL 送到目标插件进程。

        超时**不杀进程**（与事件超时不同）：插件间调用超时是正常的业务失败，
        杀掉对方进程会让一次慢调用升级成一次插件崩溃 —— 那是放大器，不是保护。
        """
        deliver = getattr(inst.runtime, "comm_request", None)
        if not callable(deliver):
            raise PluginCommError.internal("目标运行时没有 comm_request（不支持插件间通信）",
                                           {"plugin_id": inst.plugin_id})
        timeout = max(0.05, float(timeout_ms) / 1000.0)
        return await deliver(method, params, timeout=timeout)

