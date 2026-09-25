"""TransportContract 的两个参考实现（任务书 Gate Q）：WebSocketTransport / HTTPTransport。

设计要点
--------
1. **不 import 网络库**：I/O 原语由组合根注入 ——
   - `WebSocketTransport(connector=...)`：`connector(url, headers)` 返回连接对象（`send/recv/close`）
   - `HTTPTransport(poster=...)`：`poster(url, json=..., headers=..., timeout=...)` 返回 `(status, body_text)`
   真实绑定见文件末尾 `websockets_connector` / `aiohttp_poster`（懒 import）。这样"传输契约 + 语义"
   可以在没有网络库的环境里被完整测试（本仓库的测试就是这么做契约测试的）。
2. **信封可替换**：`request()` 默认按 OneBot 11 的 `{action, params, echo}` 信封组帧/解帧
   （ws_server.py 目前的形状），但组帧与解帧都可以通过 `frame_builder` / `response_reader` 注入，
   所以"通用 WS 传输"不再绑定某一种协议信封。
3. **错误可观测**：任何失败都写进 `error()`（最近一次），并可注册 `on_error` 回调 —— 契约第 7 项。
"""
import asyncio
import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from src.transport.contract import TransportContract
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)

#: 连接对象需要满足的最小接口（duck typing，不引入具体库的类型）
ConnectionLike = Any


@dataclass(frozen=True)
class ReconnectPolicy:
    """重连退避策略：第 n 次重试前等待 base_delay * 2^(n-1)，上限 max_delay。"""

    attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0

    def delay_for(self, attempt: int) -> float:
        attempt = max(1, int(attempt))
        return min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))


@dataclass(frozen=True)
class RetryPolicy:
    """请求级重试策略（HTTP 没有连接级重连，等价能力是请求重试）。"""

    attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0

    def delay_for(self, attempt: int) -> float:
        attempt = max(1, int(attempt))
        return min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))


def _onebot_request_frame(action: str, params: Dict[str, Any], echo: str) -> Dict[str, Any]:
    return {"action": action, "params": dict(params or {}), "echo": echo}


def _onebot_response_reader(frame: Dict[str, Any]) -> Tuple[bool, Any, Optional[str]]:
    """(ok, data, error)：OneBot 11 响应 {status, retcode, data}。"""
    status = frame.get("status")
    retcode = frame.get("retcode")
    ok = (status in (None, "ok")) and (retcode in (None, 0))
    err = None if ok else "retcode=%s status=%s" % (retcode, status)
    return ok, frame.get("data"), err


class WebSocketTransport(TransportContract):
    """全双工 WS 传输：8/8 项契约全部实现（连接、收发、请求-响应、鉴权、错误、重连）。"""

    name = "websocket"

    def __init__(self, url: str = "", *, connector: Optional[Callable[..., Any]] = None,
                 access_token: str = "", auth_header: str = "Authorization",
                 auth_scheme: str = "Bearer", auth_payload_key: str = "",
                 reconnect_policy: Optional[ReconnectPolicy] = None,
                 request_timeout: float = 10.0,
                 frame_builder: Optional[Callable[[str, Dict[str, Any], str], Dict[str, Any]]] = None,
                 response_reader: Optional[Callable[[Dict[str, Any]], Tuple[bool, Any, Optional[str]]]] = None,
                 on_event: Optional[Callable[[Dict[str, Any]], Any]] = None,
                 on_error: Optional[Callable[[str], Any]] = None) -> None:
        if connector is None:
            raise ValueError("WebSocketTransport 需要注入 connector（I/O 原语），见模块 docstring")
        self.url = str(url or "")
        self._connector = connector
        self._access_token = str(access_token or "")
        self._auth_header = auth_header
        self._auth_scheme = auth_scheme
        self._auth_payload_key = str(auth_payload_key or "")
        self._reconnect_policy = reconnect_policy or ReconnectPolicy()
        self._request_timeout = float(request_timeout)
        self._frame_builder = frame_builder or _onebot_request_frame
        self._response_reader = response_reader or _onebot_response_reader
        self._on_event = on_event
        self._on_error = on_error
        self._conn: Optional[ConnectionLike] = None
        self._reader: Optional[asyncio.Task] = None
        self._inbox: Any = None
        self._pending: Dict[str, Any] = {}
        self._last_error: Optional[str] = None
        self._echo_seq = 0
        self._connected = False
        self._closing = False
        #: 最近一次 reconnect() 用掉的尝试次数（可观测，便于测试与运维）
        self.reconnect_attempts = 0

    # ---------- 契约 6：鉴权材料 ----------
    def authentication(self) -> Dict[str, Any]:
        """有 token 时返回 header（如 Authorization: Bearer xxx）；无 token 返回 {}。"""
        if not self._access_token:
            return {}
        value = ("%s %s" % (self._auth_scheme, self._access_token)).strip()
        return {self._auth_header: value}

    def auth_frame(self) -> Dict[str, Any]:
        """需要"首帧带 token"的网关用这个（auth_payload_key 为空则返回 {}）。"""
        if not self._access_token or not self._auth_payload_key:
            return {}
        return {self._auth_payload_key: self._access_token}

    # ---------- 契约 1：连接 ----------
    async def connect(self) -> bool:
        if self._connected:
            return True
        headers = self.authentication()
        try:
            self._conn = await self._connector(self.url, headers)
        except Exception as exc:  # noqa: BLE001 - 契约要求失败返回 False 而不是抛给调用方
            self._conn = None
            self._record_error("connect", exc)
            return False
        frame = self.auth_frame()
        self._connected = True
        self._closing = False
        self._inbox = asyncio.Queue()
        self._reader = asyncio.ensure_future(self._reader_loop())
        if frame:
            await self.send(frame)
        return True

    # ---------- 契约 2：断开（幂等） ----------
    async def disconnect(self) -> bool:
        self._closing = True
        reader, self._reader = self._reader, None
        if reader is not None:
            reader.cancel()
            try:
                await reader
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - 关闭阶段的异常不影响幂等语义
                pass
        conn, self._conn = self._conn, None
        self._connected = False
        for echo, fut in list(self._pending.items()):
            if not fut.done():
                fut.set_result({"status": "failed", "retcode": -1, "echo": echo})
        self._pending.clear()
        if conn is not None:
            try:
                await conn.close()
            except Exception as exc:  # noqa: BLE001
                self._record_error("disconnect", exc)
        return True

    # ---------- 契约 3：单向发送 ----------
    async def send(self, payload: Dict[str, Any]) -> bool:
        if not self._connected or self._conn is None:
            self._last_error = "send: 未连接"
            return False
        try:
            await self._conn.send(json.dumps(payload, ensure_ascii=False))
            return True
        except Exception as exc:  # noqa: BLE001
            self._record_error("send", exc)
            return False

    # ---------- 契约 4：接收 ----------
    async def receive(self, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        if self._inbox is None:
            return None
        try:
            if timeout is None:
                return await self._inbox.get()
            return await asyncio.wait_for(self._inbox.get(), timeout)
        except asyncio.TimeoutError:
            return None

    # ---------- 契约 5：请求-响应（echo 配对） ----------
    async def request(self, action: str, params: Optional[Dict[str, Any]] = None,
                      timeout: Optional[float] = None) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()   # request() 一定在运行中的循环内被调用
        self._echo_seq += 1
        echo = "e%d" % self._echo_seq
        fut = loop.create_future()
        self._pending[echo] = fut
        frame = self._frame_builder(action, dict(params or {}), echo)
        if not await self.send(frame):
            self._pending.pop(echo, None)
            return {"ok": False, "error": self._last_error or "send failed"}
        try:
            resp = await asyncio.wait_for(fut, timeout or self._request_timeout)
        except asyncio.TimeoutError:
            self._pending.pop(echo, None)
            self._last_error = "request %s: timeout" % action
            return {"ok": False, "error": "timeout"}
        ok, data, err = self._response_reader(resp if isinstance(resp, dict) else {})
        return {"ok": bool(ok), "data": data, "error": err}

    # ---------- 契约 7：错误可观测 ----------
    def error(self) -> Optional[str]:
        return self._last_error

    # ---------- 契约 8：重连 ----------
    async def reconnect(self) -> bool:
        policy = self._reconnect_policy
        await self.disconnect()
        for attempt in range(1, max(1, policy.attempts) + 1):
            self.reconnect_attempts = attempt
            if attempt > 1:
                delay = policy.delay_for(attempt)
                if delay > 0:
                    await asyncio.sleep(delay)
            if await self.connect():
                return True
        return False

    # ---------- 内部 ----------
    async def _reader_loop(self) -> None:
        conn = self._conn
        try:
            while conn is not None and not self._closing:
                raw = await conn.recv()
                if raw is None:
                    break
                self._dispatch(raw)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 读取失败进 error()，连接标记为断开
            if not self._closing:
                self._record_error("receive", exc)
        finally:
            if not self._closing:
                self._connected = False

    def _dispatch(self, raw: Any) -> None:
        """把一帧分派给等待中的 request（echo 命中）或事件队列。"""
        frame: Any = raw
        if isinstance(raw, (str, bytes)):
            try:
                frame = json.loads(raw)
            except (ValueError, TypeError):
                frame = {"raw": raw}
        if not isinstance(frame, dict):
            frame = {"raw": frame}
        echo = frame.get("echo")
        if echo is not None:
            fut = self._pending.pop(str(echo), None)
            if fut is not None and not fut.done():
                fut.set_result(frame)
                return
        if self._inbox is not None:
            self._inbox.put_nowait(frame)
        if self._on_event is not None:
            try:
                result = self._on_event(frame)
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)
            except Exception as exc:  # noqa: BLE001 - 回调异常不能打断读取循环
                self._record_error("on_event", exc)

    def _record_error(self, stage: str, exc: BaseException) -> None:
        self._last_error = "%s: %s: %s" % (stage, type(exc).__name__, exc)
        logger.warning("transport_error transport=%s stage=%s err=%s", self.name, stage, exc)
        if self._on_error is not None:
            try:
                result = self._on_error(self._last_error)
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)
            except Exception:  # noqa: BLE001 - 错误回调自身出错只能忽略（否则递归）
                logger.debug("on_error 回调自身抛错，已忽略")


class HTTPTransport(TransportContract):
    """HTTP 传输：请求-响应模型。

    8 项里 **6 项实现 + 2 项明确 N/A**（Gate Q 允许，但必须给理由）：
    - `receive`：HTTP 没有服务端推送通道（事件推送由 WS 传输/回调通道提供）；
    - `reconnect`：HTTP 没有长连接，等价能力是请求级重试（RetryPolicy）。
    """

    name = "http"

    NA_REASONS = {
        "receive": "HTTP 是请求-响应模型，没有服务端推送通道；事件推送由 WebSocketTransport / 回调通道提供",
        "reconnect": "HTTP 没有长连接，不存在连接级重连；等价能力是请求级重试（RetryPolicy，见 request()）",
    }

    def __init__(self, base_url: str = "", *, poster: Optional[Callable[..., Any]] = None,
                 access_token: str = "", auth_header: str = "Authorization",
                 auth_scheme: str = "Bearer", timeout: float = 10.0,
                 retry_policy: Optional[RetryPolicy] = None,
                 on_error: Optional[Callable[[str], Any]] = None) -> None:
        if poster is None:
            raise ValueError("HTTPTransport 需要注入 poster（I/O 原语），见模块 docstring")
        self.base_url = str(base_url or "").rstrip("/")
        self._poster = poster
        self._access_token = str(access_token or "")
        self._auth_header = auth_header
        self._auth_scheme = auth_scheme
        self._timeout = float(timeout)
        self._retry_policy = retry_policy or RetryPolicy()
        self._on_error = on_error
        self._last_error: Optional[str] = None
        self._ready = False
        self.requests = 0          # 实际发出的请求次数（含重试，可观测）
        self.last_attempts = 0     # 最近一次 request 用掉的尝试次数

    # ---------- 契约 1：连接（HTTP 无连接可建 -> 就绪校验） ----------
    async def connect(self) -> bool:
        if not self.base_url:
            self._record_error("connect", ValueError("缺少 base_url"))
            return False
        self._ready = True
        return True

    # ---------- 契约 2：断开 ----------
    async def disconnect(self) -> bool:
        self._ready = False
        return True

    @property
    def ready(self) -> bool:
        return self._ready

    # ---------- 契约 3：单向发送 ----------
    async def send(self, payload: Dict[str, Any], endpoint: str = "") -> bool:
        """单向发送：只要求请求**送达**（2xx），不解释业务响应体（fire-and-forget 语义）。"""
        res = await self._attempt(endpoint, payload, self._timeout, verify_body=False)
        return bool(res.get("ok"))

    # ---------- 契约 4：N/A ----------

    # ---------- 契约 5：请求-响应（带重试） ----------
    async def request(self, action: str, params: Optional[Dict[str, Any]] = None,
                      timeout: Optional[float] = None) -> Dict[str, Any]:
        policy = self._retry_policy
        attempts = max(1, policy.attempts)
        last: Dict[str, Any] = {"ok": False, "error": "no attempt"}
        for attempt in range(1, attempts + 1):
            self.last_attempts = attempt
            last = await self._attempt(action, dict(params or {}), timeout or self._timeout)
            if last.get("ok"):
                return last
            if attempt < attempts:
                delay = policy.delay_for(attempt + 1)
                if delay > 0:
                    await asyncio.sleep(delay)
        return last

    # ---------- 契约 6：鉴权材料 ----------
    def authentication(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self._access_token:
            headers[self._auth_header] = ("%s %s" % (self._auth_scheme, self._access_token)).strip()
        return headers

    # ---------- 契约 7：错误可观测 ----------
    def error(self) -> Optional[str]:
        return self._last_error

    # ---------- 契约 8：N/A（请求级重试见 request()） ----------

    # ---------- 内部 ----------
    async def _attempt(self, endpoint: str, payload: Dict[str, Any], timeout: float,
                       verify_body: bool = True) -> Dict[str, Any]:
        url = self._url(endpoint)
        self.requests += 1
        try:
            status, body = await self._poster(url, json=payload, headers=self.authentication(),
                                             timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - 契约要求返回错误而不是抛给调用方
            self._record_error("request", exc)
            return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
        if int(status) != 200:
            self._last_error = "HTTP %s" % status
            return {"ok": False, "error": "HTTP %s" % status, "status": int(status)}
        if not verify_body:
            return {"ok": True, "data": None, "error": None, "status": int(status)}
        if body:
            try:
                data = json.loads(body)
            except (ValueError, TypeError):
                # 200 但响应体不是 JSON：绝不能当成"成功但没数据"（会掩盖协议端错误页/网关拦截）
                self._last_error = "invalid json response"
                return {"ok": False, "error": "invalid json response", "status": int(status)}
        else:
            data = {}
        ok, parsed, err = _onebot_response_reader(data if isinstance(data, dict) else {})
        if not ok:
            self._last_error = err
        return {"ok": bool(ok), "data": parsed, "error": err, "status": int(status)}

    def _url(self, endpoint: str) -> str:
        ep = str(endpoint or "").lstrip("/")
        return "%s/%s" % (self.base_url, ep) if ep else self.base_url

    def _record_error(self, stage: str, exc: BaseException) -> None:
        self._last_error = "%s: %s: %s" % (stage, type(exc).__name__, exc)
        logger.warning("transport_error transport=%s stage=%s err=%s", self.name, stage, exc)
        if self._on_error is not None:
            try:
                result = self._on_error(self._last_error)
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)
            except Exception:  # noqa: BLE001
                logger.debug("on_error 回调自身抛错，已忽略")


# ---------------------------------------------------------------- 真实 I/O 绑定（懒 import）
class _WebsocketsConnection:
    """把 websockets 客户端连接包装成契约要求的 send/recv/close 三个动作。"""

    def __init__(self, ws: Any) -> None:
        self._ws = ws

    async def send(self, text: str) -> None:
        await self._ws.send(text)

    async def recv(self) -> Any:
        return await self._ws.recv()

    async def close(self) -> None:
        await self._ws.close()


def websockets_connector() -> Callable[..., Any]:
    """真实 WS 连接工厂（`import websockets` 延迟到调用时，缺依赖不影响本模块 import）。"""

    async def _connect(url: str, headers: Optional[Dict[str, str]] = None) -> _WebsocketsConnection:
        import websockets

        ws = await websockets.connect(url, extra_headers=dict(headers or {}))
        return _WebsocketsConnection(ws)

    return _connect


def aiohttp_poster() -> Callable[..., Any]:
    """真实 HTTP 请求工厂：复用同一个 aiohttp.ClientSession（`aclose()` 挂在返回的函数上）。"""
    state: Dict[str, Any] = {"session": None}

    async def _poster(url: str, json: Optional[Dict[str, Any]] = None,
                      headers: Optional[Dict[str, str]] = None,
                      timeout: float = 10.0) -> Tuple[int, str]:
        import aiohttp

        session = state["session"]
        if session is None or session.closed:
            session = state["session"] = aiohttp.ClientSession()
        async with session.post(url, json=json, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            return resp.status, await resp.text()

    async def _aclose() -> None:
        session = state["session"]
        if session is not None and not session.closed:
            await session.close()
        state["session"] = None

    _poster.aclose = _aclose  # type: ignore[attr-defined]
    return _poster
