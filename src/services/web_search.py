"""原生网页搜索服务（v2.15.0）：免 key 引擎 + 失败感知回退链 + 正文抓取。

移植自 dsh-free-search v0.9.14（MIT，DDDMUC）的 keyless 引擎层，
适配 Flowerie 的安全边界与配置体系。**不含任何 key 引擎**。

设计原则（与 ai_tools 一致）：
- 默认关（AI_SEARCH_ENABLED）：模型不能自行发动网络访问
- 失败感知回退：transient 重试一次、bot-wall 冷却 60s、总预算 30s
- Bing 空 SERP 不重试（插件实测：重试会加重反爬封禁，#38/#71）
- 结果是不可信外部输入：一律过 sanitize_untrusted_text + 长度/条数上限
- 出口走 httpx（与 vision 同模式，绕开 Gate P 的 aiohttp 白名单）
"""
import asyncio
import base64
import html as html_mod
import re
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlsplit

import httpx

from src.core.sanitizer import sanitize_untrusted_text, validate_mcp_server_url
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)

#: 结果硬上限（与 mcp_tool_manager 的不可信结果边界同量级）
_MAX_RESULTS = 10
_MAX_RESULT_CHARS = 2000

#: 回退链总预算（秒）——插件 SEARCH_BUDGET_MS
_BUDGET_SECONDS = 30.0

#: bot-wall 冷却（秒）；transient 不冷却（只重试一次）
_BOT_WALL_COOLDOWN = 60.0

_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_ACCEPT_LANG = "zh-CN,zh;q=0.9,en;q=0.8"

ENGINE_IDS = ("ddg", "ddg-lite", "bing", "searxng")

ENGINE_LABELS = {
    "ddg": "DuckDuckGo · HTML",
    "ddg-lite": "DuckDuckGo · Lite",
    "bing": "Bing",
    "searxng": "SearXNG · 元搜索（公共实例）",
}

DEFAULT_SEARXNG_INSTANCES = (
    "https://opnxng.com",
    "https://priv.au",
    "https://searx.be",
    "https://searx.tiekoetter.com",
    "https://search.inetol.net",
    "https://paulgo.io",
)

#: 时间过滤档 → 各引擎参数（只支持固定档，自定义天数取近似档）
_TIME_RANGE_STEPS = (("day", 1), ("week", 7), ("month", 30), ("year", 365))
_DDG_DF = {"day": "d", "week": "w", "month": "m", "year": "y"}
_SEARXNG_TIME = {"day": "day", "week": "week", "month": "month", "year": "year"}

#: 引擎 HTML 解析正则（模块级，避免反复编译）
_DDG_BLOCK_RE = re.compile(r'<div class="result results_links[\s\S]*?</div>\s*</div>')
_DDG_HREF_RE = re.compile(r'<a[^>]*class="result__a"[^>]*href="([^"]*)"')
_DDG_TITLE_RE = re.compile(r'<a[^>]*class="result__a"[^>]*>(.*?)</a>', re.S)
_DDG_SNIP_RE = re.compile(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', re.S)
_DDGL_LINK_RE = re.compile(r'<a[^>]*class=["\']result-link["\'][^>]*>[\s\S]*?</a>')
_DDGL_TITLE_RE = re.compile(r'class=["\']result-link["\'][^>]*>(.*?)</a>', re.S)
_DDGL_SNIP_RE = re.compile(r'class=["\']result-snippet["\'][^>]*>([\s\S]*?)</td>')
_HREF_RE = re.compile(r'href="([^"]*)"')
_BING_BLOCK_RE = re.compile(r'<li class="b_algo"[\s\S]*?</li>')
_BING_TITLE_RE = re.compile(r'<h2[^>]*>[\s\S]*?<a[^>]*>(.*?)</a>[\s\S]*?</h2>', re.S)
_BING_SNIP_RE = re.compile(r'<p[^>]*>([\s\S]*?)</p>', re.S)


def _approximate_time_range(days: int) -> str:
    """天数取最近档（插件 approximateTimeRange）。"""
    for label, step in _TIME_RANGE_STEPS:
        if days <= step:
            return label
    return "year"


def _strip_tags(raw: str) -> str:
    """HTML 标签剥除 + 实体解码（插件 stripTags）。"""
    text = re.sub(r"<[^>]+>", " ", str(raw or ""))
    text = html_mod.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _decode_entities(raw: str) -> str:
    return html_mod.unescape(str(raw or ""))


# ---------- Bing：ck/a 跳转解包 + 无结果缓存 SERP 判定 ----------

_CK_A_RE = re.compile(r"^https?://(?:www\.)?bing\.com/ck/a", re.I)


def extract_bing_url(href: str) -> str:
    """Bing 把结果 URL 包成 bing.com/ck/a?u=a1<base64url>：真实地址在 u 参数。"""
    if not href:
        return href
    url = _decode_entities(href)
    if not _CK_A_RE.match(url):
        return href
    try:
        parts = urlsplit(url)
        u = parts.query.split("u=", 1)[1].split("&", 1)[0] if "u=" in parts.query else ""
        if not u:
            return href
        if u.startswith("a1"):
            u = u[2:]
        decoded = base64.urlsafe_b64decode(u + "=" * (-len(u) % 4)).decode("utf-8", "replace")
        return decoded if re.match(r"^https?://", decoded, re.I) else href
    except Exception:  # noqa: BLE001 - 解包失败回退原链接
        return href


def _query_overlap_tokens(query: str) -> List[str]:
    """查询 token：CJK 取二元组，拉丁/数字取长度 >=2 的词（插件 queryOverlapTokens）。"""
    tokens = set()
    for run in re.findall(r"[\u4e00-\u9fff]+", query or ""):
        if len(run) <= 2:
            tokens.add(run)
        for i in range(len(run) - 1):
            tokens.add(run[i:i + 2])
    for word in re.split(r"[^a-z0-9]+", (query or "").lower()):
        if len(word) >= 2:
            tokens.add(word)
    return list(tokens)


def _looks_relevant(query: str, sources: List[dict]) -> bool:
    """Bing「无结果返回无关缓存 SERP」判定（issue #38）。"""
    tokens = _query_overlap_tokens(query)
    if not tokens:
        return True  # 纯符号查询无法判定，不拦截
    return any(
        any(t in (str(s.get("title", "")) + " " + str(s.get("snippet", "")) + " "
                  + str(s.get("url", ""))).lower() for t in tokens)
        for s in sources)


# ---------- DDG：uddg= 重定向解包 ----------

def extract_ddg_url(rel: str) -> Optional[str]:
    """DDG 结果链接是 /redirect?uddg=<urlencoded> 或 //协议相对 URL。"""
    if not rel:
        return None
    m = re.search(r"uddg=([^&]+)", rel)
    if m:
        try:
            return unquote(m.group(1))
        except Exception:  # noqa: BLE001
            return m.group(1)
    if rel.startswith("//"):
        return "https:" + rel
    return rel


def _domain_of(url: str) -> str:
    try:
        host = (urlsplit(url).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:  # noqa: BLE001
        return ""


def _is_domain_blocked(url: str, blocked: Tuple[str, ...]) -> bool:
    if not blocked:
        return False
    host = _domain_of(url)
    return any(host == b or host.endswith("." + b) for b in blocked)


def _unique_sources(sources: List[dict], limit: int, blocked: Tuple[str, ...]) -> List[dict]:
    """按 URL 去重 + 域名黑名单过滤（先剔黑名单再去重，候选自动补位）。"""
    kept = [s for s in sources if not _is_domain_blocked(str(s.get("url", "")), blocked)]
    seen = set()
    out: List[dict] = []
    for s in kept:
        u = str(s.get("url", "")).rstrip("/")
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(s)
        if len(out) >= limit:
            break
    return out


class WebSearchService:
    """原生网页搜索：4 个免 key 引擎 + 失败感知回退 + LRU 缓存 + 正文抓取。

    生命周期由 main 管理（随 ai_tools 注入，惰性建 httpx client）。
    配置全部走 ConfigService（SEARCH_* 热更新），**默认关闭**。
    """

    def __init__(self, config, *, client_factory=None):
        self.config = config
        # client_factory 注入便于单测替换；默认惰性创建短连客户端
        self._client_factory = client_factory
        self._client: Optional[httpx.AsyncClient] = None
        self._cache: "OrderedDict[Tuple[str, ...], Tuple[float, dict]]" = OrderedDict()
        self._cache_max = 64
        self._cooldowns: Dict[str, float] = {}  # engine -> until(monotonic)

    # ---------- 配置读取（getattr 容错，与 ai_tools 同模式） ----------

    def _cfg(self, key: str, default):
        try:
            v = getattr(self.config, key, None)
        except Exception:  # noqa: BLE001
            v = None
        return default if v is None or v == "" else v

    def enabled(self) -> bool:
        return bool(self._cfg("AI_SEARCH_ENABLED", False))

    def _engine_order(self) -> List[str]:
        raw = str(self._cfg("SEARCH_ENGINES", "ddg,bing,searxng,ddg-lite") or "")
        order = [x.strip() for x in raw.split(",") if x.strip() in ENGINE_IDS]
        if not order:
            order = ["ddg", "bing", "searxng", "ddg-lite"]
        return order

    def _searxng_instances(self) -> List[str]:
        raw = str(self._cfg("SEARCH_SEARXNG_INSTANCES", "") or "").strip()
        if not raw:
            return list(DEFAULT_SEARXNG_INSTANCES)
        return [x.strip() for x in re.split(r"[,\n\s]+", raw) if x.strip()]

    def _blocked_domains(self) -> Tuple[str, ...]:
        raw = str(self._cfg("SEARCH_BLOCKED_DOMAINS", "") or "")
        return tuple(x.strip().lower() for x in raw.split(",") if x.strip())

    def _safe_search(self) -> str:
        v = str(self._cfg("SEARCH_SAFE_SEARCH", "off") or "off").lower()
        return v if v in ("off", "moderate", "strict") else "off"

    def _timeout(self) -> float:
        try:
            return max(3.0, float(self._cfg("SEARCH_TIMEOUT", 10)))
        except (TypeError, ValueError):
            return 10.0

    def _cache_ttl(self) -> int:
        try:
            return max(0, min(5, int(self._cfg("SEARCH_CACHE_TTL", 5))))
        except (TypeError, ValueError):
            return 5

    def _max_results(self, hint: Optional[int] = None) -> int:
        try:
            cap = int(self._cfg("SEARCH_MAX_RESULTS", 5))
        except (TypeError, ValueError):
            cap = 5
        n = int(hint) if hint else cap
        return max(1, min(_MAX_RESULTS, n))

    # ---------- httpx client ----------

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            if self._client_factory is not None:
                self._client = self._client_factory()
            else:
                self._client = httpx.AsyncClient(
                    headers={"user-agent": _USER_AGENT},
                    follow_redirects=False,  # 3xx 按失败处理（SSRF 重定向边界）
                    timeout=httpx.Timeout(self._timeout()),
                )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def _fetch_html(self, url: str, accept_lang: Optional[str] = None) -> str:
        """GET HTML：3 次重试（间隔 1.5s），>500 字节才算成功（插件 fetchHtmlWithRetry）。"""
        headers = {"accept": "text/html,application/xhtml+xml", "accept-language": accept_lang or _ACCEPT_LANG}
        last: Optional[Exception] = None
        for attempt in range(3):
            try:
                r = await self.client.get(url, headers=headers)
                if r.status_code == 200 and len(r.content) > 500:
                    return r.text
                last = httpx.HTTPError("bad status %s or empty" % r.status_code)
            except Exception as e:  # noqa: BLE001 - 聚合失败原因
                last = e
            if attempt < 2:
                await asyncio.sleep(1.5)
        raise last or httpx.HTTPError("fetch failed")

    # ---------- 引擎实现（4 个免 key） ----------

    async def _search_ddg_html(self, query, limit, time_range, signal):
        params = {"q": query, "kl": "wt-wt"}
        adlt = self._safe_search()
        params["adlt"] = {"strict": "1", "moderate": "0"}.get(adlt, "-1")
        if time_range:
            df = _DDG_DF.get(_approximate_time_range(_days_of(time_range)))
            if df:
                params["df"] = df
        url = "https://html.duckduckgo.com/html/?" + "&".join(
            "%s=%s" % (k, v) for k, v in params.items())
        html = await self._fetch_html(url)
        blocks = re.findall(_DDG_BLOCK_RE, html)
        sources = []
        for block in blocks:
            href = _DDG_HREF_RE.search(block)
            title = _DDG_TITLE_RE.search(block)
            snip = _DDG_SNIP_RE.search(block)
            u = extract_ddg_url(href.group(1) if href else "")
            if not u:
                continue
            entry = {"url": u}
            if title:
                entry["title"] = _strip_tags(title.group(1))
            if snip:
                entry["snippet"] = _strip_tags(snip.group(1))
            sources.append(entry)
        return _unique_sources(sources, limit, self._blocked_domains())

    async def _search_ddg_lite(self, query, limit, time_range, signal):
        params = {"q": query, "kl": "wt-wt"}
        adlt = self._safe_search()
        params["adlt"] = {"strict": "1", "moderate": "0"}.get(adlt, "-1")
        if time_range:
            df = _DDG_DF.get(_approximate_time_range(_days_of(time_range)))
            if df:
                params["df"] = df
        url = "https://lite.duckduckgo.com/lite/?" + "&".join(
            "%s=%s" % (k, v) for k, v in params.items())
        html = await self._fetch_html(url)
        links = re.findall(_DDGL_LINK_RE, html)
        snippets = re.findall(_DDGL_SNIP_RE, html)
        sources = []
        for i, tag in enumerate(links):
            href = _HREF_RE.search(tag)
            title = _DDGL_TITLE_RE.search(tag)
            if not href:
                continue
            u = extract_ddg_url(href.group(1))
            if not u:
                continue
            entry = {"url": u}
            if title:
                entry["title"] = _strip_tags(title.group(1))
            if i < len(snippets) and snippets[i]:
                entry["snippet"] = _strip_tags(snippets[i])
            sources.append(entry)
        return _unique_sources(sources, limit, self._blocked_domains())

    async def _search_bing(self, query, limit, time_range, signal):
        # mkt 默认不发：海外 IP + mkt=zh-CN 会返回空 SERP（插件 #71）
        url = "https://www.bing.com/search?q=" + _quote(query)
        adlt = self._safe_search()
        if adlt != "off":
            url += "&adlt=" + adlt
        html = await self._fetch_html(url)
        blocks = re.findall(_BING_BLOCK_RE, html)
        sources = []
        for block in blocks:
            href = _HREF_RE.search(block)
            title = _BING_TITLE_RE.search(block)
            snip = _BING_SNIP_RE.search(block)
            if not href:
                continue
            entry = {"url": extract_bing_url(href.group(1))}
            if title:
                entry["title"] = _strip_tags(title.group(1))
            if snip:
                entry["snippet"] = _strip_tags(snip.group(1))
            sources.append(entry)
        if sources and not _looks_relevant(query, sources):
            return []  # 无结果缓存 SERP：判 0 结果交给回退链
        return _unique_sources(sources, limit, self._blocked_domains())

    async def _search_searxng(self, query, limit, time_range, signal):
        errors = []
        for base_url in self._searxng_instances():
            if signal.is_set():
                raise asyncio.TimeoutError("search aborted")
            params = {"q": query, "format": "json"}
            if time_range:
                tr = _SEARXNG_TIME.get(_approximate_time_range(_days_of(time_range)))
                if tr:
                    params["time_range"] = tr
            try:
                r = await self.client.get(
                    base_url + "/search", params=params,
                    headers={"user-agent": _USER_AGENT, "accept": "application/json"},
                    timeout=httpx.Timeout(min(8.0, self._timeout())))
                if r.status_code != 200:
                    errors.append("%s: HTTP %d" % (base_url, r.status_code))
                    continue
                data = r.json()
                results = data.get("results") if isinstance(data, dict) else None
                if not isinstance(results, list):
                    errors.append("%s: invalid JSON" % base_url)
                    continue
                sources = [{"url": str(x.get("url", "")),
                            "title": str(x.get("title", "")),
                            "snippet": str(x.get("content", ""))}
                           for x in results if x.get("url")]
                sources = _unique_sources(sources, limit, self._blocked_domains())
                if sources:
                    return sources
                errors.append("%s: 0 results" % base_url)
            except Exception as e:  # noqa: BLE001 - 聚合错误继续下一实例
                errors.append("%s: %s" % (base_url, type(e).__name__))
        raise httpx.HTTPError("all SearXNG instances failed: " + "; ".join(errors)[:300])

    # ---------- 回退链（失败感知） ----------

    def _dispatch(self, engine: str, query, limit, time_range, signal):
        return {
            "ddg": self._search_ddg_html,
            "ddg-lite": self._search_ddg_lite,
            "bing": self._search_bing,
            "searxng": self._search_searxng,
        }[engine](query, limit, time_range, signal)

    async def _search_chain(self, query: str, limit: int, time_range: Optional[str],
                            engine: Optional[str]) -> Tuple[List[dict], str, List[str]]:
        """串行回退 + 失败分类（bot-wall 冷却 60s / transient 同引擎重试一次）。

        空结果也触发回退（Bing 无结果缓存 SERP 判 0 结果 → 继续下一个引擎）。
        返回 (sources, 命中引擎, 尝试过的全部引擎)。
        """
        order = self._engine_order()
        if engine and engine in ENGINE_IDS:
            order = [engine] + [e for e in order if e != engine]
        now = time.monotonic()
        chain = [e for e in order if self._cooldowns.get(e, 0.0) <= now]
        if not chain:
            raise httpx.HTTPError("all search engines are cooling down")
        deadline = now + _BUDGET_SECONDS
        signal = asyncio.Event()
        attempted: List[str] = []
        retries: set = set()
        last_error: Optional[BaseException] = None

        async def _try(eng: str) -> List[dict]:
            """单引擎一次尝试：空结果抛错（触发回退），成功返回 sources。"""
            attempted.append(eng)
            result = await self._dispatch(eng, query, limit, time_range, signal)
            if not result:
                raise httpx.HTTPError("%s: 0 results" % eng)
            return result

        for eng in chain:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError("search timed out after %ss" % _BUDGET_SECONDS)
            try:
                return await _try(eng), eng, attempted
            except asyncio.TimeoutError:
                raise  # 总预算耗尽，不再回退
            except Exception as e:  # noqa: BLE001 - 回退链就是为容错而存在
                last_error = e
                cls = _failure_class(e)
                logger.warning("search_engine_failed engine=%s class=%s err=%s", eng, cls, e)
                if cls == "transient" and eng not in retries:
                    retries.add(eng)
                    try:
                        return await _try(eng), eng, attempted
                    except Exception as e2:  # noqa: BLE001
                        last_error = e2
                elif cls == "bot-wall":
                    self._cooldowns[eng] = time.monotonic() + _BOT_WALL_COOLDOWN
        raise httpx.HTTPError("all search engines failed: %s" % (last_error or "unknown"))

    # ---------- 缓存 ----------

    def _cache_key(self, query: str, limit: int, time_range: Optional[str]) -> tuple:
        return (query.strip().lower(), limit, str(time_range or ""),
                tuple(self._engine_order()), tuple(self._blocked_domains()))

    def _cache_get(self, key: tuple) -> Optional[dict]:
        ttl = self._cache_ttl()
        if ttl <= 0:
            return None
        hit = self._cache.get(key)
        if hit is None:
            return None
        expires, value = hit
        if time.time() > expires:
            self._cache.pop(key, None)
            return None
        self._cache.move_to_end(key)
        return value

    def _cache_put(self, key: tuple, value: dict) -> None:
        ttl = self._cache_ttl()
        if ttl <= 0:
            return
        self._cache[key] = (time.time() + ttl * 60, value)
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_max:
            self._cache.popitem(last=False)

    # ---------- 公共 API ----------

    async def search(self, query: str, max_results: Optional[int] = None,
                     time_range: Optional[str] = None,
                     engine: Optional[str] = None) -> Dict[str, Any]:
        """搜索：返回 {ok, sources[], engine, note}。sources 是不可信外部输入（已截断+消毒）。"""
        query = str(query or "").strip()
        if not query:
            return {"ok": False, "error": "query is required"}
        limit = self._max_results(max_results)
        key = self._cache_key(query, limit, time_range)
        cached = self._cache_get(key)
        if cached is not None:
            return dict(cached, cached=True)
        try:
            sources, hit, attempted = await self._search_chain(query, limit, time_range, engine)
        except asyncio.TimeoutError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:  # noqa: BLE001 - 工具失败不能打崩对话
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
        clean = []
        total = 0
        for s in sources[:_MAX_RESULTS]:
            clean_s, _ = sanitize_untrusted_text(str(s.get("snippet", "")))
            item = {"url": str(s.get("url", ""))}
            total += len(item["url"])
            if s.get("title"):
                item["title"] = str(s["title"])[:200]
                total += len(item["title"])
            if clean_s:
                item["snippet"] = clean_s[:400]
                total += len(item["snippet"])
            clean.append(item)
            if total >= _MAX_RESULT_CHARS:
                break
        result = {
            "ok": True,
            "sources": clean,
            "engine": hit,  # 实际命中引擎（可能是回退后的备选）
            "engines_used": attempted,  # 全部尝试过的引擎（含失败/空结果）
            "note": ("部分引擎失败，结果可能不完整" if len(attempted) > 1 else ""),
        }
        self._cache_put(key, result)
        return result

    async def fetch_page(self, url: str, max_chars: int = 2000) -> Dict[str, Any]:
        """抓正文：URL 安全校验 + 正文提取。结果是不可信外部输入（已消毒+截断）。"""
        url = str(url or "").strip()
        ok_url, reason = validate_mcp_server_url(url)
        if not ok_url:
            return {"ok": False, "error": "URL 被拒绝（%s）" % reason}
        try:
            r = await self.client.get(url, headers={
                "user-agent": _USER_AGENT,
                "accept-language": _ACCEPT_LANG,
            })
            if r.status_code != 200:
                return {"ok": False, "error": "HTTP %d" % r.status_code}
            text = _extract_main_text(r.text)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
        text, _ = sanitize_untrusted_text(text)
        return {"ok": True, "url": url, "title": _extract_title(r.text), "text": text[:max_chars],
                "truncated": len(text) > max_chars}

    async def test_engines(self, query: str = "Flowerie", limit: int = 2) -> Dict[str, Dict[str, Any]]:
        """逐引擎连通性自检（设置页手动按钮调用，不给 AI 用）。

        预算 = 单引擎超时 × 4：内部 _fetch_html 重试 3 次（间隔 1.5s），
        SearXNG 串行 6 实例 × 8s——10s 的 SEARCH_TIMEOUT 必然提前杀掉，
        自检会清一色报 TimeoutError（此前确实现过）。
        """
        out: Dict[str, Dict[str, Any]] = {}
        signal = asyncio.Event()
        # 自检给足预算（最小 40s）；真实搜索仍受 _BUDGET_SECONDS 总预算约束
        per_engine = max(40.0, self._timeout() * 4)
        for eng in self._engine_order():
            started = time.monotonic()
            try:
                sources = await asyncio.wait_for(
                    self._dispatch(eng, query, limit, None, signal), timeout=per_engine)
                out[eng] = {"ok": True, "results": len(sources),
                            "seconds": round(time.monotonic() - started, 1)}
            except Exception as e:  # noqa: BLE001 - 自检就是来看谁挂的
                out[eng] = {"ok": False, "error": ("%s: %s" % (type(e).__name__, e))[:160],
                            "seconds": round(time.monotonic() - started, 1)}
        return out


def _extract_main_text(html: str) -> str:
    """粗暴正文提取：去 script/style/tag，压空白。"""
    text = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", html or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    return re.sub(r"[ \t\r\n\f]+", " ", text).strip()


def _extract_title(html: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html or "")
    return _strip_tags(m.group(1)) if m else ""


def _days_of(time_range) -> int:
    """时间过滤档 -> 天数（day/week/month/year）；不识别返回 0。"""
    tr = str(time_range or "").strip().lower()
    return {"day": 1, "week": 7, "month": 30, "year": 365}.get(tr, 0) or 0


def _quote(s: str) -> str:
    from urllib.parse import quote_plus
    return quote_plus(str(s or ""), safe="")


def _failure_class(exc: BaseException) -> str:
    """失败分类（transient 重试一次 / bot-wall 冷却 60s）。"""
    msg = str(exc)
    if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError)):
        return "transient"
    if isinstance(exc, httpx.HTTPStatusError) or "HTTP 4" in msg or "HTTP 5" in msg:
        return "bot-wall" if ("429" in msg or "403" in msg) else "transient"
    return "transient"
