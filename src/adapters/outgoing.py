"""出站段路由：按**配置的客户端档案**把内部段数组收敛成该客户端能接受的形态。

任务书 ~/storage/emulated/0/协议.txt §十/§十一/§十四：客户端差异只停留在 Adapter 层，
且**服务层不得反向依赖 Adapter**（ADR-001 冻结层规则）——所以这里不 import 任何 services，
只暴露一个纯函数 + 一个可注入的适配器工厂：

- `main.py`（组合根，允许同时认识两层）：`Sender(config, outgoing_adapter=make_outgoing_adapter(cfg.CLIENT_PROFILE))`
- `Sender`（services）：只在"传进来了适配器"时调用，默认 None = 行为完全不变
- 本模块（adapters）：认识客户端档案与两个序列化器

配置取值（`CLIENT_PROFILE`）：
- `""`（默认）→ 不做任何收敛（原样发送，行为与今天一致）；
- `"go-cqhttp"` / `"napcat"` / `"llbot"` → 客户端名；协议按**通道**推断（OneBot 通道 → onebot11）；
- `"onebot11:llbot"` / `"milky:llbot"` → 显式协议 + 客户端（同一个客户端名出现在两套协议里时必须这样写）；
- 未调查的客户端名 → **不做收敛**，只返回一条 note 说明（不伪造支持）。
"""
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.adapters.client_profile import PROFILES, ClientProfile, profile_for

#: 通道名前缀 → 协议（action_channels 里各通道的 `name`：onebot-http / onebot-ws / milky-http）
CHANNEL_PROTOCOLS = (("milky", "milky"), ("onebot", "onebot11"))

#: 已知客户端（用于"这个名字到底调没调查过"的判断）
KNOWN_CLIENTS = {client for (_protocol, client) in PROFILES}

NOTE_UNKNOWN_CLIENT = "unknown_client_no_adaptation"
NOTE_PASSTHROUGH = "no_profile_configured"


def channel_protocol(channel_name: str) -> str:
    """通道名 → 协议名（认不出来就按 onebot11；调用方通常直接给协议）。"""
    name = str(channel_name or "").lower()
    for prefix, protocol in CHANNEL_PROTOCOLS:
        if name.startswith(prefix):
            return protocol
    return "onebot11"


def parse_profile_setting(value: Any) -> Tuple[str, str]:
    """`CLIENT_PROFILE` → `(protocol_hint, client)`；`""` 或非法值返回 `("", "")`（=关闭）。"""
    text = str(value or "").strip()
    if not text:
        return "", ""
    if ":" in text:
        protocol, _, client = text.partition(":")
        protocol, client = protocol.strip().lower(), client.strip().lower()
        if protocol in {p for (p, _c) in PROFILES}:
            return protocol, client
        return "", ""
    return "", text.lower()


def prepare_outgoing(segments: Any, *, protocol: str = "onebot11", client: str = "",
                     is_group: bool = True) -> Tuple[List[dict], List[Dict[str, Any]]]:
    """按档案收敛出站段；返回 `(segments, notes)`。

    三种情况：
    1. `client` 为空 → **原样返回**（不产生 note）；
    2. `client` 未调查 → 原样返回 + 一条 note（**不伪装**成已适配）；
    3. 有档案 → 调对应协议的序列化器（OneBot 11 / Milky 各一个）。
    """
    if not client:
        return list(segments or []), []
    if client not in KNOWN_CLIENTS:
        return list(segments or []), [{"type": "(client)", "reason": NOTE_UNKNOWN_CLIENT,
                                       "client": client,
                                       "detail": "未调查的客户端：不做字段收敛，原样发送"}]
    profile: ClientProfile = profile_for(protocol, client)
    if protocol == "milky":
        from src.adapters.milky_serializer import serialize_milky_segments

        return serialize_milky_segments(segments, profile=profile, is_group=is_group)
    from src.adapters.onebot_serializer import serialize_segments

    return serialize_segments(segments, profile=profile)


def make_outgoing_adapter(setting: Any) -> Optional[Callable[..., Tuple[List[dict], List[dict]]]]:
    """把配置值变成可注入 Sender 的适配器；空/非法值返回 None（调用方据此完全不改变行为）。"""
    protocol_hint, client = parse_profile_setting(setting)
    if not client:
        return None

    def _adapter(segments: Any, is_group: bool = True,
                 protocol: str = "") -> Tuple[List[dict], List[dict]]:
        return prepare_outgoing(segments, protocol=(protocol or protocol_hint or "onebot11"),
                                client=client, is_group=is_group)

    _adapter.client = client          # 供日志/测试读取
    _adapter.protocol_hint = protocol_hint
    return _adapter
