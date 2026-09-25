"""传输层（Transport）：只负责连接、收发与重连，不承载业务语义。

依赖方向（任务书 §5/§16）：Transport →（协议封装在 Adapter 内）；**Core 不得 import websockets/aiohttp**。
本层当前包含：
- ws_server.py        反向 WebSocket 服务端（客户端连 Flowerie）；内含 OneBot action/echo 信封
- ws_forward_client.py 正向 WebSocket 客户端（Flowerie 连客户端 WS server）
- milky_ws_client.py   Milky 事件 WebSocket 客户端（Bearer 鉴权）

**已知边界（后续拆分，见 docs/architecture/transport-abstraction.md）**：
ws_server.py 里的 action/params/echo 信封属 OneBot 约定，理想形态是"通用 WS 传输 + OneBot 信封适配器"；
本阶段先完成"从 Core 搬出"（Gate P），信封拆分单独进行。
"""
from src.transport.milky_ws_client import MilkyClient
from src.transport.ws_forward_client import NapCatForwardClient, redact_ws_url
from src.transport.ws_server import WebSocketServer

__all__ = ["WebSocketServer", "NapCatForwardClient", "redact_ws_url", "MilkyClient"]
