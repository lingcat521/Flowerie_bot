"""传输层（Transport）：只负责连接、收发与重连，不承载业务语义。

依赖方向（任务书 §5/§16）：Transport →（协议封装在 Adapter 内）；**Core 不得 import websockets/aiohttp**。
本层包含：
- contract.py          TransportContract：8 项传输契约（Gate Q，只依赖标准库）
- transports.py        契约参考实现：WebSocketTransport / HTTPTransport（I/O 原语注入 + 懒 import 绑定）
- ws_server.py         反向 WebSocket 服务端（客户端连 Flowerie）；内含 OneBot action/echo 信封
- ws_forward_client.py 正向 WebSocket 客户端（Flowerie 连客户端 WS server）
- milky_ws_client.py   Milky 事件 WebSocket 客户端（Bearer 鉴权）

**已知边界（后续拆分，见 docs/architecture/transport-abstraction.md）**：
ws_server.py 里的 action/params/echo 信封属 OneBot 约定；通用形态已在 transports.py 给出
（frame_builder / response_reader 可替换），现有连接路径仍走旧实现。

**为什么旧连接类是懒加载（PEP 562）**：传输契约与语义不该被某个网络库绑死——
`import src.transport.contract` 在没装 websockets/aiohttp 的环境里也必须成功。
旧名字保持可用：`from src.transport import WebSocketServer` 仍然有效，只是推迟到访问时才 import。
"""
from src.transport.contract import (
    CONTRACT_ITEMS,
    TRANSPORT_CONTRACT_ITEMS,
    ContractReport,
    TransportContract,
    check_transport_contract,
)
from src.transport.transports import (
    HTTPTransport,
    ReconnectPolicy,
    RetryPolicy,
    WebSocketTransport,
    aiohttp_poster,
    websockets_connector,
)

_LEGACY_EXPORTS = {
    "WebSocketServer": ("src.transport.ws_server", "WebSocketServer"),
    "NapCatForwardClient": ("src.transport.ws_forward_client", "NapCatForwardClient"),
    "redact_ws_url": ("src.transport.ws_forward_client", "redact_ws_url"),
    "MilkyClient": ("src.transport.milky_ws_client", "MilkyClient"),
}

__all__ = [
    "CONTRACT_ITEMS",
    "TRANSPORT_CONTRACT_ITEMS",
    "ContractReport",
    "HTTPTransport",
    "ReconnectPolicy",
    "RetryPolicy",
    "TransportContract",
    "WebSocketTransport",
    "aiohttp_poster",
    "check_transport_contract",
    "websockets_connector",
    "WebSocketServer",
    "NapCatForwardClient",
    "redact_ws_url",
    "MilkyClient",
]


def __getattr__(name):
    """旧连接类的懒加载（避免 transport 包被 websockets 依赖绑死）。"""
    target = _LEGACY_EXPORTS.get(name)
    if target is None:
        raise AttributeError("module %r has no attribute %r" % (__name__, name))
    from importlib import import_module

    return getattr(import_module(target[0]), target[1])
