"""LivingMemory（高级记忆）：Embedding / 向量检索 / Rerank / 自动提取（默认 OFF）。

- EmbeddingProvider / Reranker：纯协议（未来接任意供应商；当前 1 个 HTTP 实现）
- VectorSearch：纯 Python cosine（零依赖；内存索引，条目上限治理）
- BlossomMemoryManager：检索（群隔离）/提取（每日限额）/TTL+上限清理/关闭资源
- OFF 时（BLOSSOM_MEMORY_ENABLED=false）：本模块对象不构造（main 门控），
  即便误构造，所有入口 also 检查开关（双保险）
- 安全：记忆文本与检索结果按不可信数据处理（sanitize_untrusted_text 兜底）；
  API URL 复用 MCP 同款 SSRF 校验（sanitizer.validate_mcp_server_url）
"""
import math
import time
from typing import Any, Dict, List, Optional, Protocol, Tuple

import httpx

from src.core.sanitizer import sanitize_untrusted_text, validate_mcp_server_url
from src.repositories.blossom_memory_repository import (
    BlossomMemoryRecord,
    BlossomMemoryRepository,
    SQLiteBlossomMemoryRepository,
)
from src.utils.logging_setup import get_logger
from src.utils.metrics import registry as _registry

logger = get_logger(__name__)

# 指标（低基数：operation/result）
_M_EMBEDDING = _registry.counter("memory_embedding_total", "向量化次数", ["result"])
_M_RETRIEVAL = _registry.counter("memory_retrieval_total", "语义检索次数", ["result"])
_M_RERANK = _registry.counter("memory_rerank_total", "重排序次数", ["result"])
_M_EXTRACT = _registry.counter("memory_extraction_total", "自动提取次数", ["result"])


# ================= 抽象（Protocol） =================
class EmbeddingProvider(Protocol):
    async def embed(self, text: str) -> List[float]: ...


class Reranker(Protocol):
    async def rerank(self, query: str, documents: List[str]) -> List[Tuple[int, float]]:
        """返回 [(index, score)]（score 降序）。"""


# ================= HTTP 实现（OpenAI-compatible） =================
class OpenAICompatibleEmbedding:
    """OpenAI-compatible /v1/embeddings 实现（复用 MCP 同款 SSRF 校验）。"""

    def __init__(self, model: str, api_url: str, api_key: str, timeout: float = 20.0,
                 dimension: int = 1024):
        ok, reason = validate_mcp_server_url(api_url)
        if not ok:
            raise ValueError(f"BLOSSOM_MEMORY_EMBEDDING_API_URL 不合法: {reason}")
        self.model, self.api_url, self.api_key = model, api_url, api_key
        self.timeout = timeout
        self.dimension = max(1, int(dimension or 1024))
        self._client = httpx.AsyncClient(timeout=timeout, follow_redirects=False)

    async def embed(self, text: str) -> List[float]:
        try:
            resp = await self._client.post(
                self.api_url, json={"model": self.model, "input": text},
                headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})
            resp.raise_for_status()
            data = resp.json()
            vec = list(data["data"][0]["embedding"])[: self.dimension]
            if not vec:
                raise ValueError("embedding 返回空向量")
            _M_EMBEDDING.inc({"result": "ok"})
            return [float(v) for v in vec]
        except Exception:  # noqa: BLE001
            _M_EMBEDDING.inc({"result": "fail"})
            raise

    async def close(self) -> None:
        if not self._client.is_closed:
            await self._client.aclose()


class OpenAICompatibleRerank:
    """OpenAI-compatible /rerank 风格实现（jina/voyage/bge-reranker 等 HTTP 端点）。"""

    def __init__(self, model: str, api_url: str, api_key: str, timeout: float = 20.0,
                 top_k: int = 3):
        ok, reason = validate_mcp_server_url(api_url)
        if not ok:
            raise ValueError(f"BLOSSOM_MEMORY_RERANKER_API_URL 不合法: {reason}")
        self.model, self.api_url, self.api_key, self.top_k = model, api_url, api_key, top_k
        self._client = httpx.AsyncClient(timeout=timeout, follow_redirects=False)

    async def rerank(self, query: str, documents: List[str]) -> List[Tuple[int, float]]:
        top_k = max(1, int(self.top_k or 3))
        try:
            resp = await self._client.post(
                self.api_url,
                json={"model": self.model, "query": query, "documents": documents,
                      "top_n": top_k},
                headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results") or []
            _M_RERANK.inc({"result": "ok"})
            return [(int(r["index"]), float(r["relevance_score"])) for r in results]
        except Exception:  # noqa: BLE001
            _M_RERANK.inc({"result": "fail"})
            raise

    async def close(self) -> None:
        if not self._client.is_closed:
            await self._client.aclose()


# ================= 向量检索（纯 Python cosine，零依赖） =================
def cosine_similarity(a: List[float], b: List[float]) -> float:
    """纯 Python cosine（向量维度与条目均有上限治理，性能足够）。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


class VectorSearch:
    """内存索引 + 余弦检索（查询时加载群向量；条目上限治理）。"""

    def __init__(self, threshold: float = 0.6, dimension: int = 1024):
        self.threshold = max(0.0, min(1.0, float(threshold or 0.6)))
        self.dimension = max(1, int(dimension or 1024))

    def search(self, query: List[float], items: List[dict], top_k: int = 5) -> List[dict]:
        """items: [{memory_id, text, vector}] → 相似度降序前 top_k（阈值过滤）。"""
        scored = []
        for it in items:
            vec = it.get("vector") or []
            if not vec:
                continue
            sim = cosine_similarity(query, vec)
            if sim >= self.threshold:
                scored.append((sim, it))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"memory_id": it["memory_id"], "text": it["text"], "score": sim}
                for sim, it in scored[: max(1, int(top_k or 5))]]


# ================= Manager =================
class BlossomMemoryManager:
    """高级记忆门面（默认 OFF：构造即空载；请由 main 按开关决定是否创建）。"""

    def __init__(self, config: Any, repository: Optional[BlossomMemoryRepository] = None,
                 embedding: Optional[Any] = None, reranker: Optional[Any] = None):
        self.config = config
        self.enabled = bool(getattr(config, "BLOSSOM_MEMORY_ENABLED", False))
        self.vector_dim = max(1, int(getattr(config, "BLOSSOM_MEMORY_VECTOR_DIMENSION", 1024)))
        self.top_k = max(1, int(getattr(config, "BLOSSOM_MEMORY_RETRIEVAL_TOP_K", 5)))
        self.rerank_top_k = max(1, int(getattr(config, "BLOSSOM_MEMORY_RERANK_TOP_K", 3)))
        self.threshold = float(getattr(config, "BLOSSOM_MEMORY_SIMILARITY_THRESHOLD", 0.6) or 0.6)
        self.max_entries = max(1, int(getattr(config, "BLOSSOM_MEMORY_MAX_ENTRIES", 2000)))
        self.ttl_days = max(0, int(getattr(config, "BLOSSOM_MEMORY_TTL_DAYS", 90) or 0))
        self.daily_limit = max(1, int(getattr(config, "BLOSSOM_MEMORY_DAILY_EXTRACT_LIMIT", 20)))
        self.extract_enabled = bool(getattr(config, "BLOSSOM_MEMORY_EXTRACT_ENABLED", False))
        self.retrieval_enabled = bool(getattr(config, "BLOSSOM_MEMORY_RETRIEVAL_ENABLED", False))
        self.embedding_enabled = bool(getattr(config, "BLOSSOM_MEMORY_EMBEDDING_ENABLED", False))
        self.reranker_enabled = bool(getattr(config, "BLOSSOM_MEMORY_RERANKER_ENABLED", False))
        # 存储：默认 SQLite（db 路径复用 memory 同目录：config.BLOSSOM_MEMORY_DB_PATH）
        db = getattr(config, "BLOSSOM_MEMORY_DB_PATH", None) or "./data/blossom_memory.db"
        self.repository = repository or SQLiteBlossomMemoryRepository(db)
        self.embedding = embedding
        self.reranker = reranker
        self._search = VectorSearch(self.threshold, self.vector_dim)
        self._daily_extracted: Dict[tuple, int] = {}   # (group_id, date) -> count
        self._mem = self._model_facts_guard()

    def _model_facts_guard(self) -> bool:
        return True

    # ---------- 可用性 ----------
    def ready(self) -> Tuple[bool, str]:
        """配置就绪检查（fail-fast 配合：主开关开启但子项配置缺失时返回原因）。"""
        if not self.enabled:
            return False, "高级记忆未开启"
        if self.embedding_enabled and (not self.embedding or
                                       not getattr(self.config, "BLOSSOM_MEMORY_EMBEDDING_MODEL", "")):
            return False, "向量模型（Embedding）未配置"
        if self.reranker_enabled and (not self.reranker or
                                      not getattr(self.config, "BLOSSOM_MEMORY_RERANKER_MODEL", "")):
            return False, "重排序模型（Reranker）未配置"
        return True, ""

    # ---------- 写入：自动提取（默认关闭；失败静默降级为不写入） ----------
    async def extract_and_store(self, group_id: int, user_id: int, text: str,
                                source_message_id: Optional[int] = None) -> bool:
        if not self.enabled or not self.extract_enabled:
            return False
        ok, reason = self.ready()
        if not ok:
            logger.warning("blossom_memory_skip group=%s reason=%s", group_id, reason)
            return False
        # 每日限额（按群）：超过 limit 不再提取
        day = time.strftime("%Y%m%d", time.localtime())
        key = (group_id, day)
        used = self._daily_extracted.get(key, 0)
        if used >= self.daily_limit:
            _M_EXTRACT.inc({"result": "limit"})
            return False
        # 提取净化：不可信文本清洗后保存（来源=用户消息，无系统指令权限）
        clean, _hit = sanitize_untrusted_text((text or "")[:1000])
        if not clean.strip():
            _M_EXTRACT.inc({"result": "empty"})
            return False
        try:
            vector = await self.embedding.embed(clean)
        except Exception as e:  # noqa: BLE001
            _M_EXTRACT.inc({"result": "embed_fail"})
            logger.warning("blossom_memory_embed_fail group=%s err=%s", group_id, e)
            return False
        now = time.time()
        rec = BlossomMemoryRecord(memory_id=0, group_id=group_id, kind="group",
                                 text=clean[:1000], vector=vector, created_at=now,
                                 last_used_at=now, source_message_id=source_message_id)
        try:
            self.repository.add(rec)
        except Exception as e:  # noqa: BLE001
            _M_EXTRACT.inc({"result": "store_fail"})
            logger.warning("blossom_memory_store_fail group=%s err=%s", group_id, e)
            return False
        self._daily_extracted[key] = used + 1
        _M_EXTRACT.inc({"result": "ok"})
        # 治理：TTL/上限清理（有界长期状态）
        self._prune(group_id)
        return True

    # ---------- 检索（群隔离 + 可重排） ----------
    async def search(self, group_id: int, query: str, top_k: Optional[int] = None) -> str:
        """语义检索 →（可重排）→ 纯文本（已 sanitize）；返回 "" 当不可用/无结果。"""
        if not self.enabled or not self.retrieval_enabled:
            return ""
        ok, reason = self.ready()
        if not ok:
            logger.warning("blossom_memory_skip group=%s reason=%s", group_id, reason)
            return ""
        try:
            vector = await self.embedding.embed(query)
        except Exception as e:  # noqa: BLE001
            _M_RETRIEVAL.inc({"result": "embed_fail"})
            logger.warning("blossom_memory_retrieval_embed_fail group=%s err=%s", group_id, e)
            return ""
        # 群隔离：只取本群记忆（global/user 维度当前不启用）
        items = self.repository.list_by_group(int(group_id or 0), kind="group")
        hits = self._search.search(vector, items, top_k=top_k or self.top_k)
        if not hits:
            _M_RETRIEVAL.inc({"result": "none"})
            return ""
        # 重排（可选）
        if self.reranker_enabled and self.reranker is not None and len(hits) > 1:
            try:
                pairs = await self.reranker.rerank(
                    query, [h["text"] for h in hits])
                if pairs:
                    hits = [hits[i] for i, _s in sorted(pairs, key=lambda x: x[1], reverse=True)]
            except Exception as e:  # noqa: BLE001
                logger.warning("blossom_memory_rerank_fail group=%s err=%s", group_id, e)
        for h in hits:
            self.repository.touch(h["memory_id"])
        texts = [h["text"] for h in hits[: self.rerank_top_k or 3]]
        joined = "\n".join(f"- {t}" for t in texts)
        _M_RETRIEVAL.inc({"result": "ok"})
        return joined

    def _prune(self, group_id: int) -> None:
        ttl_ts = 0.0
        if self.ttl_days > 0:
            ttl_ts = time.time() - self.ttl_days * 86400
        try:
            self.repository.delete_missing_before(group_id, self.max_entries, ttl_ts)
        except Exception as e:  # noqa: BLE001
            logger.warning("blossom_memory_prune_fail group=%s err=%s", group_id, e)

    async def close(self) -> None:
        if self.embedding is not None and hasattr(self.embedding, "close"):
            await self.embedding.close()
        if self.reranker is not None and hasattr(self.reranker, "close"):
            await self.reranker.close()
        self.repository.close()
