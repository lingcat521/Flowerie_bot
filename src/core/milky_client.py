"""Milky 事件客户端（应用端主动连协议端 /event；Bearer 鉴权；断线重连）。

与 OneBot 反向 WS 的差异：这里是**客户端**（websockets.connect），
连接 Milky 协议端（Lagrange.Milky / Yogurt 等）的 ws://{host}:{port}/event。
事件信封原样交给 message_router.process_event（内部经 milky_parser 解析）。
"""
import asyncio
import json
import logging
from typing import Optional

import websockets

logger = logging.getLogger(__name__)


class MilkyClient:
    """Milky 事件连接（单连接客户端；自动重连 + 退避；事件并发走 router）。"""

    def __init__(self, config, message_router):
        self.config = config
        self.message_router = message_router
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._ws = None

    def _event_url(self) -> str:
        url = str(getattr(self.config, "MILKY_EVENT_URL", "") or "")
        tok = str(getattr(self.config, "MILKY_ACCESS_TOKEN", "") or "")
        if tok and "access_token" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}access_token={tok}"
        return url

    async def run(self):
        """启动连接循环（自动重连；退避 5→10→20→40→60）。"""
        self._running = True
        backoff = [5, 10, 20, 40, 60]
        idx = 0
        while self._running:
            try:
                url = self._event_url()
                logger.info("Connecting to Milky event: %s", url.split("?")[0])
                async with websockets.connect(url, ping_interval=30, ping_timeout=20,
                                              close_timeout=10) as ws:
                    self._ws = ws
                    idx = 0
                    logger.info("Milky event connected", extra={"event": "milky_connected"})
                    async for message in ws:
                        if not self._running:
                            break
                        try:
                            if isinstance(message, bytes):
                                message = message.decode("utf-8")
                            data = json.loads(message) if isinstance(message, str) else message
                            if not isinstance(data, dict):
                                continue
                            async with self.message_router.process_semaphore:
                                await asyncio.wait_for(
                                    self.message_router.process_event(data),
                                    timeout=getattr(self.config, "EVENT_PROCESS_TIMEOUT", 120),
                                )
                        except asyncio.TimeoutError:
                            logger.error("Milky event processing timeout, skipped")
                        except json.JSONDecodeError:
                            logger.error("Milky JSON decode error")
                        except Exception as e:  # noqa: BLE001
                            logger.exception("Milky event processing error: %s", e)
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                logger.warning("Milky event 连接异常，%ss 后重连: %s",
                               backoff[idx] if idx < len(backoff) else 60, e)
                await asyncio.sleep(backoff[idx] if idx < len(backoff) else 60)
                idx = min(idx + 1, len(backoff) - 1)
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass

    async def start(self):
        self._task = asyncio.create_task(self.run())
        return self._task

    async def shutdown(self):
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
