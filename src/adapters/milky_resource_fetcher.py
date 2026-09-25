"""Milky 资源取数：`get_resource_temp_url` 取临时 URL → 下载（两步）。

证据 `[CODE]` proto_src/LagrangeV2/Lagrange.Milky/Api/Handler/Message/GetResourceTempUrlHandler.cs L8-27：
    [Api("get_resource_temp_url")]
    GetResourceTempUrlParameter{ resource_id }   （[JsonRequired]）
    GetResourceTempUrlResult{ url }
（Lagrange.Core 同名 handler 一致；docs/milky-protocol.md 已登记该动作 ↔ OneBot `get_group_res`。）

两步里的"下载"复用注入的 `url_fetcher`（`URLFetcher`），所以本模块同样不 import 网络库。
"""
from typing import Any, Optional

from src.adapters.resource import FetchResult, ResourceFetcher, ResourceRef
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)


class MilkyResourceFetcher(ResourceFetcher):
    """协议 id → 临时 URL → 字节。"""

    name = "milky-resource"

    def __init__(self, call_api: Any, url_fetcher: Optional[ResourceFetcher] = None,
                 action: str = "get_resource_temp_url") -> None:
        if call_api is None:
            raise ValueError("MilkyResourceFetcher 需要注入 call_api（协议调用出口）")
        self._call_api = call_api
        self._url_fetcher = url_fetcher
        self.action = action

    async def fetch(self, ref: Any) -> FetchResult:
        target = ResourceRef.coerce(ref)
        if target is None or not target.is_protocol_id or not target.fetchable:
            return b"", False
        if self._url_fetcher is None:
            logger.warning("milky_resource_no_downloader ref=%s（未注入 url_fetcher）", target.ref)
            return b"", False
        try:
            res = await self._call_api(self.action, {"resource_id": str(target.ref)})
        except Exception as exc:  # noqa: BLE001 - 契约：失败返回而不是抛
            logger.warning("milky_temp_url_failed ref=%s err=%s", target.ref, exc)
            return b"", False
        if not isinstance(res, dict) or not res.get("ok"):
            logger.warning("milky_temp_url_rejected ref=%s res=%s", target.ref,
                           str(res)[:200] if res is not None else None)
            return b"", False
        data = res.get("data")
        url = (data or {}).get("url") if isinstance(data, dict) else None
        if not url:
            logger.warning("milky_temp_url_missing ref=%s", target.ref)
            return b"", False
        return await self._url_fetcher.fetch(ResourceRef.from_url(str(url), name=target.name))
