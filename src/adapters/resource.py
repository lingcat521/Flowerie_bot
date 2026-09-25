"""资源抽象（ResourceRef + ResourceFetcher）—— 任务书 Gate R §19。

三种来源统一成一个模型：

    本地路径 local path ─┐
    URL                 ─┼─► ResourceRef ─► ResourceFetcher（取字节）─► FileParser.decode_bytes（纯解码）
    协议 resource_id     ─┘

分工（Gate R 的核心，也是"Core 不依赖 file_id / resource_id"的实现方式）：

| 角色 | 负责 | 在哪里 |
| :--- | :--- | :--- |
| `ResourceRef` | 资源**是什么**（协议中立；`origin` 只用于诊断与路由，Core 只透传不解释）| `src/adapters/resource.py` |
| `ResourceFetcher` | 资源**怎么取**（协议差异全部在这一层）| Adapter（OneBot/Milky 各自实现）|
| `decode_bytes` | 字节**怎么读**成文本（纯函数，不认识任何协议）| `src/services/file_parser.py` |

因此 Core 只需要"拿一个 ref 交给注入的 fetcher，再把字节交给解码器"，
既不需要知道 `file_id`，也不需要知道 `resource_id`。
"""
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from src.adapters.proto import to_int
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)

#: fetcher 统一返回 (内容字节, 是否成功)；失败**不得**抛给调用方
FetchResult = Tuple[bytes, bool]
#: 协议取数实现（origin -> 异步取数函数）
ProtocolFetch = Callable[["ResourceRef"], Awaitable[FetchResult]]


class ResourceKind:
    """资源来源三形态（Gate R 要求 3/3）。"""

    LOCAL_PATH = "local_path"
    URL = "url"
    PROTOCOL_ID = "protocol_id"
    ALL: Tuple[str, ...] = (LOCAL_PATH, URL, PROTOCOL_ID)


@dataclass(frozen=True)
class ResourceRef:
    """协议中立的资源引用。

    - `kind`：见 `ResourceKind`（非法值直接报错，避免"半个模型"悄悄流通）
    - `ref`：按 kind 解释（本地路径 / URL / 协议侧 id）
    - `name` / `size` / `mime`：尽力而为的元数据（协议端不给就是空/0，不推断）
    - `origin`：产生它的协议标识（如 `onebot11` / `milky`）——**只用于诊断与选择 fetcher**
    """

    kind: str
    ref: str
    name: str = ""
    size: int = 0
    mime: str = ""
    origin: str = ""

    def __post_init__(self) -> None:
        if self.kind not in ResourceKind.ALL:
            raise ValueError("未知资源类型：%r（可选 %s）" % (self.kind, list(ResourceKind.ALL)))
        object.__setattr__(self, "ref", str(self.ref or ""))
        object.__setattr__(self, "name", str(self.name or ""))
        object.__setattr__(self, "origin", str(self.origin or ""))
        object.__setattr__(self, "mime", str(self.mime or ""))
        object.__setattr__(self, "size", to_int(self.size) or 0)

    # ---------- 三个工厂（对应 3/3 的三种输入） ----------
    @classmethod
    def from_local_path(cls, path: str, name: str = "", size: int = 0) -> "ResourceRef":
        return cls(kind=ResourceKind.LOCAL_PATH, ref=str(path or ""), name=name, size=size)

    @classmethod
    def from_url(cls, url: str, name: str = "", size: int = 0, mime: str = "") -> "ResourceRef":
        return cls(kind=ResourceKind.URL, ref=str(url or ""), name=name, size=size, mime=mime)

    @classmethod
    def from_protocol_id(cls, resource_id: str, origin: str = "", name: str = "",
                         size: int = 0) -> "ResourceRef":
        return cls(kind=ResourceKind.PROTOCOL_ID, ref=str(resource_id or ""), origin=origin,
                   name=name, size=size)

    # ---------- 判定 ----------
    @property
    def is_local_path(self) -> bool:
        return self.kind == ResourceKind.LOCAL_PATH

    @property
    def is_url(self) -> bool:
        return self.kind == ResourceKind.URL

    @property
    def is_protocol_id(self) -> bool:
        return self.kind == ResourceKind.PROTOCOL_ID

    @property
    def fetchable(self) -> bool:
        """有实际引用才谈得上取（空 ref 直接判不可取，不浪费一次请求）。"""
        return bool(self.ref.strip())

    def as_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "ref": self.ref, "name": self.name, "size": self.size,
                "mime": self.mime, "origin": self.origin}

    def __str__(self) -> str:  # 诊断输出：不打印完整 URL/路径之外的内容
        return "%s(%s%s)" % (self.kind, self.ref, ", origin=%s" % self.origin if self.origin else "")

    # ---------- 宽松归一（脏输入不炸；这是 Adapter 边界的既有风格） ----------
    @classmethod
    def coerce(cls, value: Any) -> Optional["ResourceRef"]:
        """把"可能是资源的东西"归一成 ResourceRef；无法识别返回 None（绝不猜）。"""
        if value is None:
            return None
        if isinstance(value, ResourceRef):
            return value
        if isinstance(value, dict):
            inner = value.get("resource")
            if isinstance(inner, (ResourceRef, dict)):
                got = cls.coerce(inner)
                if got is not None:
                    return got
            if value.get("kind") and value.get("ref") is not None:
                try:
                    return cls(kind=str(value.get("kind")), ref=str(value.get("ref")),
                               name=value.get("name") or "", size=value.get("size") or 0,
                               mime=value.get("mime") or "", origin=value.get("origin") or "")
                except ValueError:
                    return None
            for key in ("url", "temp_url"):
                if value.get(key):
                    return cls.from_url(str(value[key]), name=str(value.get("name") or ""))
            for key in ("path", "file"):
                if value.get(key):
                    return cls.from_local_path(str(value[key]), name=str(value.get("name") or ""))
            for key in ("id", "file_id", "resource_id"):
                if value.get(key):
                    return cls.from_protocol_id(str(value[key]), origin=str(value.get("origin") or ""),
                                                name=str(value.get("name") or value.get("file_name") or ""))
            return None
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            if text.startswith(("http://", "https://")):
                return cls.from_url(text)
            if text.startswith(("/", "file://", "./", "../")):
                return cls.from_local_path(text)
            return cls.from_protocol_id(text)
        return None


def attach_resource(notice: Dict[str, Any], origin: str,
                    id_keys: Tuple[str, ...] = ("id", "file_id", "resource_id")) -> Dict[str, Any]:
    """给边界通知对象补上统一 `resource` 字段（键名保持原样，只**新增**）。

    Adapter 解析上传通知时调用：这样 Core 拿到的是 ResourceRef，而不是某个协议的 id 字段名。
    `origin` 由调用方（各自的解析器）给出，是本函数唯一需要协议知识的地方。
    """
    data = dict(notice or {})
    rid = ""
    for key in id_keys:
        if data.get(key):
            rid = str(data[key])
            break
    if rid:
        name = str(data.get("name") or data.get("file_name") or "")
        data["resource"] = ResourceRef.from_protocol_id(rid, origin=origin, name=name,
                                                        size=to_int(data.get("size")) or 0)
    return data


# ---------------------------------------------------------------- 取数实现

class ResourceFetcher:
    """取字节的基类。

    **刻意不用 `abc.ABC`**（ADR-005 的 B024 教训）：实现者可以只覆盖自己支持的分支，
    其余交给组合（`CompositeResourceFetcher`）。失败一律返回 `(b"", False)`，不抛给调用方。
    """

    name = "fetcher"

    async def fetch(self, ref: Any) -> FetchResult:
        raise NotImplementedError


class NullResourceFetcher(ResourceFetcher):
    """没有接线任何取数能力时使用：**明确失败**并说明原因（绝不静默返回空内容）。"""

    name = "null"

    def __init__(self, reason: str = "未接线资源取数能力（resource_fetcher=None）") -> None:
        self.reason = reason

    async def fetch(self, ref: Any) -> FetchResult:
        logger.warning("resource_fetch_skipped reason=%s ref=%s", self.reason,
                       ResourceRef.coerce(ref) or ref)
        return b"", False


class LocalPathFetcher(ResourceFetcher):
    """本地路径：直接读文件（stat 先看大小，避免把大文件读进内存）。"""

    name = "local-path"

    def __init__(self, max_bytes: int = 2 * 1024 * 1024) -> None:
        self.max_bytes = max(1, int(max_bytes))

    async def fetch(self, ref: Any) -> FetchResult:
        target = ResourceRef.coerce(ref)
        if target is None or not target.is_local_path or not target.fetchable:
            return b"", False
        path = target.ref[7:] if target.ref.startswith("file://") else target.ref
        try:
            import os

            size = os.path.getsize(path)
            if size > self.max_bytes:
                logger.warning("resource_local_too_large path=%s size=%d limit=%d",
                               path, size, self.max_bytes)
                return b"", False
            with open(path, "rb") as fh:
                return fh.read(self.max_bytes), True
        except OSError as exc:
            logger.warning("resource_local_read_failed path=%s err=%s", path, exc)
            return b"", False


class URLFetcher(ResourceFetcher):
    """URL：下载交给注入的 `http_get(url, max_bytes) -> (bytes, ok)`（本模块不 import 网络库）。"""

    name = "url"

    def __init__(self, http_get: Optional[Callable[..., Awaitable[FetchResult]]] = None,
                 max_bytes: int = 2 * 1024 * 1024) -> None:
        self._http_get = http_get
        self.max_bytes = max(1, int(max_bytes))

    async def fetch(self, ref: Any) -> FetchResult:
        target = ResourceRef.coerce(ref)
        if target is None or not target.is_url or not target.fetchable:
            return b"", False
        if self._http_get is None:
            logger.warning("resource_url_no_downloader url=%s", target.ref)
            return b"", False
        try:
            return await self._http_get(target.ref, self.max_bytes)
        except Exception as exc:  # noqa: BLE001 - 契约：失败返回而不是抛
            logger.warning("resource_url_fetch_failed url=%s err=%s", target.ref, exc)
            return b"", False


class ProtocolIdFetcher(ResourceFetcher):
    """协议 resource_id：按 `origin` 分派到各协议自己的取数实现。"""

    name = "protocol-id"

    def __init__(self, fetchers: Optional[Dict[str, ProtocolFetch]] = None) -> None:
        self._fetchers: Dict[str, ProtocolFetch] = dict(fetchers or {})

    def register(self, origin: str, fetcher: ProtocolFetch) -> None:
        self._fetchers[str(origin)] = fetcher

    @property
    def origins(self) -> Tuple[str, ...]:
        return tuple(sorted(self._fetchers))

    async def fetch(self, ref: Any) -> FetchResult:
        target = ResourceRef.coerce(ref)
        if target is None or not target.is_protocol_id or not target.fetchable:
            return b"", False
        fetcher = self._fetchers.get(target.origin)
        if fetcher is None:
            logger.warning("resource_protocol_unwired origin=%s ref=%s（已接线：%s）",
                           target.origin or "(空)", target.ref, list(self.origins))
            return b"", False
        try:
            return await fetcher(target)
        except Exception as exc:  # noqa: BLE001
            logger.warning("resource_protocol_fetch_failed origin=%s err=%s", target.origin, exc)
            return b"", False


class CompositeResourceFetcher(ResourceFetcher):
    """按 kind 分派：本地路径 / URL / 协议 id 各走各的实现（三种输入 3/3 的统一入口）。"""

    name = "composite"

    def __init__(self, local: Optional[ResourceFetcher] = None, url: Optional[ResourceFetcher] = None,
                 protocol: Optional[ResourceFetcher] = None) -> None:
        self._by_kind: Dict[str, ResourceFetcher] = {}
        if local is not None:
            self._by_kind[ResourceKind.LOCAL_PATH] = local
        if url is not None:
            self._by_kind[ResourceKind.URL] = url
        if protocol is not None:
            self._by_kind[ResourceKind.PROTOCOL_ID] = protocol

    @property
    def kinds(self) -> Tuple[str, ...]:
        return tuple(sorted(self._by_kind))

    async def fetch(self, ref: Any) -> FetchResult:
        target = ResourceRef.coerce(ref)
        if target is None or not target.fetchable:
            return b"", False
        fetcher = self._by_kind.get(target.kind)
        if fetcher is None:
            logger.warning("resource_kind_unwired kind=%s（已接线：%s）", target.kind, list(self.kinds))
            return b"", False
        return await fetcher.fetch(target)


def build_resource_fetcher(call_api: Any = None, http_get: Any = None,
                           max_bytes: int = 2 * 1024 * 1024) -> CompositeResourceFetcher:
    """组合根辅助：一次接上三种资源形态（本地路径 / URL / 协议 id）。

    - `call_api(endpoint, params) -> {"ok","data"}`：协议调用出口（`Sender.call_api`）；
    - `http_get(url, max_bytes) -> (bytes, ok)`：URL 下载（`FileParser.fetch_url_bytes`，协议无关）；
    - 协议 id 按 `origin` 分派：`onebot11` → `/get_file`；`milky` → `get_resource_temp_url` + URL 下载。

    缺哪一项就少接一条：对应形态会**明确失败并写日志**（绝不静默返回空内容）。
    函数内的 import 是刻意的：避免 `resource.py` 与两个协议 fetcher 形成循环导入。
    """
    local = LocalPathFetcher(max_bytes=max_bytes)
    url = URLFetcher(http_get, max_bytes=max_bytes)
    protocol = ProtocolIdFetcher()
    if call_api is not None:
        from src.adapters.milky_resource_fetcher import MilkyResourceFetcher
        from src.adapters.onebot.resource_fetcher import OneBotResourceFetcher

        protocol.register("onebot11", OneBotResourceFetcher(call_api, max_bytes=max_bytes,
                                                            local_fetcher=local).fetch)
        protocol.register("milky", MilkyResourceFetcher(call_api, url_fetcher=url).fetch)
    else:
        logger.warning("build_resource_fetcher: 未提供 call_api，协议资源（协议侧 id）将无法取数")
    return CompositeResourceFetcher(local=local, url=url, protocol=protocol)
