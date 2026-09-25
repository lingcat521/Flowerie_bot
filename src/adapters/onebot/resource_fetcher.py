"""OneBot 11 资源取数：`/get_file` → base64（或本地路径）→ 字节。

**迁移说明（Gate R）**：这段逻辑原先在 `src/services/file_parser.py`——services 层直接拼
OneBot 端点、解析 NapCat 响应，属协议耦合，也是"Core 依赖 file_id"的源头。
现在取数整体搬到 Adapter 层，services 只保留"字节 → 文本"的纯解码（`decode_bytes`）。

证据 / 行为：
- OneBot 11 `/get_file`：`{status, retcode, data:{file, file_name, file_size, base64?}}`；
  `base64` 是 NapCat / Lagrange 的实现扩展（`[CODE]` 见 docs/onebot-compatibility.md
  与 tests/fixtures/napcat/**）；
- 协议端也可能回一个**本地路径**（`data.file`）：那本质是 local_path 资源，交给 `LocalPathFetcher` 读；
- 响应的读取走注入的 `call_api(endpoint, params) -> {"ok","data"}`（HTTP 或 WS 通道），
  本模块**不 import 网络库**。
"""
import base64
from typing import Any, Optional

from src.adapters.resource import FetchResult, LocalPathFetcher, ResourceFetcher, ResourceRef
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)


class OneBotResourceFetcher(ResourceFetcher):
    """协议 id → 字节（OneBot 11 / NapCat / Lagrange 的 `/get_file`）。"""

    name = "onebot11-resource"

    def __init__(self, call_api: Any, max_bytes: int = 2 * 1024 * 1024,
                 endpoint: str = "get_file", id_field: str = "file_id",
                 local_fetcher: Optional[ResourceFetcher] = None) -> None:
        if call_api is None:
            raise ValueError("OneBotResourceFetcher 需要注入 call_api（协议调用出口）")
        self._call_api = call_api
        self.max_bytes = max(1, int(max_bytes))
        self.endpoint = endpoint
        self.id_field = id_field
        self._local = local_fetcher or LocalPathFetcher(max_bytes=self.max_bytes)

    async def fetch(self, ref: Any) -> FetchResult:
        target = ResourceRef.coerce(ref)
        if target is None or not target.is_protocol_id or not target.fetchable:
            return b"", False
        try:
            res = await self._call_api(self.endpoint, {self.id_field: str(target.ref)})
        except Exception as exc:  # noqa: BLE001 - 契约：失败返回而不是抛
            logger.warning("onebot_get_file_failed ref=%s err=%s", target.ref, exc)
            return b"", False
        if not isinstance(res, dict) or not res.get("ok"):
            logger.warning("onebot_get_file_rejected ref=%s res=%s", target.ref,
                           str(res)[:200] if res is not None else None)
            return b"", False
        data = res.get("data")
        if not isinstance(data, dict):
            logger.warning("onebot_get_file_bad_payload ref=%s", target.ref)
            return b"", False

        b64 = data.get("base64") or ""
        if b64:
            # base64 文本 ≈ 原始字节 × 4/3：先按文本长度拒绝超大响应，避免无谓解码
            cap = self.max_bytes * 4 // 3 + 4096
            if len(b64) > cap:
                logger.warning("onebot_get_file_base64_too_large ref=%s len=%d cap=%d",
                               target.ref, len(b64), cap)
                return b"", False
            try:
                content = base64.b64decode(b64)
            except Exception as exc:  # noqa: BLE001
                logger.warning("onebot_get_file_base64_invalid ref=%s err=%s", target.ref, exc)
                return b"", False
            if len(content) > self.max_bytes:
                logger.warning("onebot_get_file_bytes_too_large ref=%s size=%d limit=%d",
                               target.ref, len(content), self.max_bytes)
                return b"", False
            return content, True

        # 协议端只给了本地路径：按 local_path 资源读（同一套 fetcher，不重复实现）
        path = data.get("file") or data.get("path") or ""
        if path:
            return await self._local.fetch(ResourceRef.from_local_path(str(path), name=target.name))
        logger.warning("onebot_get_file_no_content ref=%s keys=%s", target.ref, sorted(data)[:8])
        return b"", False
