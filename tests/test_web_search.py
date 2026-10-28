"""v2.15.0 原生网页搜索测试：引擎解析 / 回退链 / 缓存 / 工具层装配 / WebUI tab。"""
import asyncio
import base64
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.web_search import (  # noqa: E402
    ENGINE_IDS,
    WebSearchService,
    _days_of,
    _extract_main_text,
    _looks_relevant,
    _strip_tags,
    extract_bing_url,
    extract_ddg_url,
)


class _Cfg:
    AI_SEARCH_ENABLED = True
    SEARCH_ENGINES = "ddg,bing,searxng,ddg-lite"
    SEARCH_MAX_RESULTS = 5
    SEARCH_TIMEOUT = 10
    SEARCH_CACHE_TTL = 5
    SEARCH_SAFE_SEARCH = "off"
    SEARCH_BLOCKED_DOMAINS = ""
    SEARCH_SEARXNG_INSTANCES = ""
    SEARCH_FETCH_MAX_CHARS = 2000


def _svc(cfg=None, fetcher=None):
    return WebSearchService(cfg or _Cfg(), client_factory=fetcher)


# ---------- URL 解包（移植正确性的最小证据） ----------

def test_bing_ck_a_unwrap():
    real = "https://example.com/page?q=1"
    u = "a1" + base64.urlsafe_b64encode(real.encode()).decode().rstrip("=")
    href = f"https://www.bing.com/ck/a?!&&u={u}"
    assert extract_bing_url(href) == real
    assert extract_bing_url("https://example.com/plain") == "https://example.com/plain"
    assert extract_bing_url("") == ""


def test_ddg_uddg_unwrap():
    assert extract_ddg_url("/redirect?uddg=https%3A%2F%2Fexample.com") == "https://example.com"
    assert extract_ddg_url("//example.com/x") == "https://example.com/x"
    assert extract_ddg_url(None) is None


# ---------- Bing 无结果缓存 SERP 判定（issue #38） ----------

def test_bing_irrelevant_serp_detected():
    assert not _looks_relevant("花璃机器人", [{"title": "Completely unrelated content",
                                              "snippet": "nothing matches", "url": "https://x.com"}])
    assert _looks_relevant("花璃机器人", [{"title": "花璃机器人 GitHub", "snippet": "", "url": ""}])
    assert _looks_relevant("机器人", [{"title": "机器人维护手册", "snippet": "", "url": ""}])
    assert _looks_relevant("?!@", [{"title": "x", "snippet": "", "url": ""}])


def test_days_of():
    assert _days_of("week") == 7
    assert _days_of("YEAR") == 365
    assert _days_of("nonsense") == 0


def test_strip_tags_unescapes():
    assert _strip_tags("<a> hello &amp;   world</a>") == "hello & world"


def test_extract_main_text():
    html = "<script>var x=1</script><style>p{}</style><h1>Title</h1><p>正文内容</p>"
    text = _extract_main_text(html)
    assert "var x" not in text and "正文内容" in text


# ---------- 配置读取 ----------

def test_disabled_by_default():
    class Off(_Cfg):
        AI_SEARCH_ENABLED = False
    assert not _svc(Off()).enabled()


def test_engine_order_filters_unknown():
    class C(_Cfg):
        SEARCH_ENGINES = "bing,nonexistent,ddg"
    assert _svc(C())._engine_order() == ["bing", "ddg"]


def test_engine_order_empty_falls_back():
    class C(_Cfg):
        SEARCH_ENGINES = "nonsense"
    order = _svc(C())._engine_order()
    assert len(order) == 4 and set(order) == set(ENGINE_IDS)


def test_searxng_instances_default_and_custom():
    assert len(_svc()._searxng_instances()) == 6
    class C(_Cfg):
        SEARCH_SEARXNG_INSTANCES = "https://a.example, https://b.example"
    assert _svc(C())._searxng_instances() == ["https://a.example", "https://b.example"]


def test_blocked_domains_lowercased():
    class C(_Cfg):
        SEARCH_BLOCKED_DOMAINS = "spam.com, BAD.org"
    assert _svc(C())._blocked_domains() == ("spam.com", "bad.org")


def test_max_results_clamped():
    assert _svc()._max_results(99) == 10
    assert _svc()._max_results(3) == 3


# ---------- 搜索主流程（fake 客户端） ----------

class _FakeResp:
    """_fetch_html 要求响应 >500 字节（防空页），测试 HTML 自动补足到 600+。"""


class _FakeResp:
    """_fetch_html 要求响应 >500 字节（防空页）；测试 HTML 自动补足到 600+。"""

    def __init__(self, status=200, text="", data=None):
        self.status_code = status
        # JSON 响应（searxng）不做长度要求
        self.text = text if (data is not None or status != 200 or len(text) > 500) else text + " " * 600
        self.content = self.text.encode()
        self._data = data

    def json(self):
        return self._data


class _FakeClient:
    """httpx.AsyncClient 的最小替身：按 host+path 前缀分发响应。"""

    def __init__(self, routes=None, default_status=500):
        self.routes = routes or {}
        self.default_status = default_status
        self.calls = []
        self.is_closed = False

    async def get(self, url, headers=None, params=None, timeout=None):
        from urllib.parse import urlsplit
        host = urlsplit(url).hostname or ""
        self.calls.append(host)
        for (h, path), resp in self.routes.items():
            if h == host and url.startswith("https://" + h + path):
                if isinstance(resp, Exception):
                    raise resp
                return resp
        return _FakeResp(status=self.default_status, text="x" * 600)

    async def aclose(self):
        self.is_closed = True


_DDG_HTML = (
    # 真实 DDG HTML 是双层嵌套 div（外 result results_links + 内 result__body）
    '<div class="result results_links" data-d="1"><div class="links_main links_deep">'
    '<a class="result__a" href="/l/?uddg=https%3A%2F%2Fddg1.com">T1</a>'
    '<a class="result__snippet">S1</a></div></div>'
    '<div class="result results_links" data-d="2"><div class="links_main links_deep">'
    '<a class="result__a" href="/l/?uddg=https%3A%2F%2Fddg2.com">T2</a>'
    '<a class="result__snippet">S2</a></div></div>'
)

_BING_HTML = (
    '<li class="b_algo"><h2><a href="https://www.bing.com/ck/a?u=a1aHR0cHM6Ly9iaW5nMS5jb20v">B1</a></h2>'
    '<p>snippet one</p></li>'
    '<li class="b_algo"><h2><a href="https://plain.com/p">B2</a></h2><p>two</p></li>'
)


@pytest.mark.asyncio
async def test_search_ddg_success():
    client = _FakeClient({("html.duckduckgo.com", "/html/"): _FakeResp(200, _DDG_HTML)})
    svc = _svc(fetcher=lambda: client)
    r = await svc.search("test", max_results=5, engine="ddg")
    assert r["ok"], r
    assert r["engine"] == "ddg"
    urls = [s["url"] for s in r["sources"]]
    assert urls == ["https://ddg1.com", "https://ddg2.com"]
    assert r["sources"][0]["title"] == "T1"


@pytest.mark.asyncio
async def test_search_bing_unwraps_ck_a():
    client = _FakeClient({("www.bing.com", "/search"): _FakeResp(200, _BING_HTML)})
    svc = _svc(fetcher=lambda: client)
    r = await svc.search("snippet one", max_results=5, engine="bing")
    assert r["ok"], r
    urls = [s["url"] for s in r["sources"]]
    assert urls[0] == "https://bing1.com/"
    assert urls[1] == "https://plain.com/p"


@pytest.mark.asyncio
async def test_search_bing_irrelevant_serp_falls_back_to_ddg():
    bad = "<li class=b_algo><h2><a href=https://unrelated.com>Unrelated</a></h2><p>nothing</p></li>"
    client = _FakeClient({
        ("www.bing.com", "/search"): _FakeResp(200, bad),
        ("html.duckduckgo.com", "/html/"): _FakeResp(200, _DDG_HTML),
    })
    svc = _svc(fetcher=lambda: client)
    r = await svc.search("唯一查询词xyzzy", engine="bing")
    assert r["ok"], r
    assert r["engine"] == "ddg"
    assert "bing" in r["engines_used"]


@pytest.mark.asyncio
async def test_search_all_fail_returns_error():
    client = _FakeClient({}, default_status=500)
    svc = _svc(fetcher=lambda: client)
    r = await svc.search("anything")
    assert not r["ok"]
    assert "error" in r


@pytest.mark.asyncio
async def test_searxng_instance_failover():
    data1 = {"results": []}
    data2 = {"results": [{"url": "https://sx.com/1", "title": "S1", "content": "C1"}]}
    client = _FakeClient({
        ("opnxng.com", "/search"): _FakeResp(200, "", data1),
        ("priv.au", "/search"): _FakeResp(200, "", data2),
    })
    svc = _svc(fetcher=lambda: client)
    r = await svc.search("query", engine="searxng")
    assert r["ok"], r
    assert r["sources"][0]["url"] == "https://sx.com/1"


@pytest.mark.asyncio
async def test_search_cache_hits_second_call():
    client = _FakeClient({("html.duckduckgo.com", "/html/"): _FakeResp(200, _DDG_HTML)})
    svc = _svc(fetcher=lambda: client)
    r1 = await svc.search("cached", engine="ddg")
    assert r1["ok"]
    r2 = await svc.search("cached", engine="ddg")
    assert r2.get("cached") is True
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_time_range_fixed_steps():
    client = _FakeClient({("html.duckduckgo.com", "/html/"): _FakeResp(200, _DDG_HTML)})
    svc = _svc(fetcher=lambda: client)
    r = await svc.search("recent", time_range="week", engine="ddg")
    assert r["ok"]


@pytest.mark.asyncio
async def test_empty_query_rejected():
    r = await _svc().search("   ")
    assert not r["ok"] and r["error"] == "query is required"


@pytest.mark.asyncio
async def test_blocked_domain_filtered():
    class C(_Cfg):
        SEARCH_BLOCKED_DOMAINS = "ddg1.com"
    client = _FakeClient({("html.duckduckgo.com", "/html/"): _FakeResp(200, _DDG_HTML)})
    svc = _svc(C(), fetcher=lambda: client)
    r = await svc.search("x", engine="ddg")
    assert r["ok"]
    assert [s["url"] for s in r["sources"]] == ["https://ddg2.com"]


# ---------- fetch_page（SSRF + 正文） ----------

@pytest.mark.asyncio
async def test_fetch_page_ssrf_loopback_rejected():
    r = await _svc().fetch_page("http://127.0.0.1:8080/admin")
    assert not r["ok"]
    assert "拒绝" in r["error"]


@pytest.mark.asyncio
async def test_fetch_page_success():
    client = _FakeClient({("example.com", "/page"): _FakeResp(
        200, "<title>页</title><p>正文内容</p>")})
    svc = _svc(fetcher=lambda: client)
    r = await svc.fetch_page("https://example.com/page")
    assert r["ok"], r
    assert r["title"] == "页" and "正文内容" in r["text"]
    assert r["truncated"] is False


@pytest.mark.asyncio
async def test_fetch_page_truncates():
    long = "<p>" + "很长的正文内容。" * 500 + "</p>"
    client = _FakeClient({("example.com", "/p"): _FakeResp(200, long)})
    svc = _svc(fetcher=lambda: client)
    r = await svc.fetch_page("https://example.com/p", max_chars=100)
    assert r["ok"] and r["truncated"] is True
    assert len(r["text"]) <= 100


# ---------- 自检 ----------

@pytest.mark.asyncio
async def test_test_engines_reports_per_engine():
    client = _FakeClient({
        ("html.duckduckgo.com", "/html/"): _FakeResp(200, _DDG_HTML),
    })
    svc = _svc(fetcher=lambda: client)
    out = await asyncio.wait_for(svc.test_engines("q", limit=2), timeout=20)
    assert set(out.keys()) == set(svc._engine_order())
    assert out["ddg"]["ok"] is True and out["ddg"]["results"] == 2


# ---------- WebUI tab 渲染 ----------

def test_search_panel_renders():
    from src.services.webui_panels import SearchPanelMixin
    svc = _svc()
    class FakeServer(SearchPanelMixin):
        def __init__(self):
            self._search_service_ref = svc
    html = FakeServer()._render_search_page()
    assert "网页搜索" in html and "DuckDuckGo" in html and "SearXNG" in html
    assert "/panel/search/probe" in html and "/panel/search/test" in html
    assert "AI 搜索已开启" in html


def test_search_panel_xss_escaped():
    from src.services.webui_panels import SearchPanelMixin
    class FakeServer(SearchPanelMixin):
        def __init__(self):
            self._search_service_ref = _svc()
            self._search_probe_cache = {"ok": True, "engine": "x",
                                        "sources": [{"url": "https://e.com",
                                                     "title": "<script>alert(1)</script>",
                                                     "snippet": "<img src=x>"}]}
    html = FakeServer()._render_search_page()
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_search_panel_disabled_hint():
    class Off(_Cfg):
        AI_SEARCH_ENABLED = False
    from src.services.webui_panels import SearchPanelMixin
    class FakeServer(SearchPanelMixin):
        def __init__(self):
            self._search_service_ref = _svc(Off())
    html = FakeServer()._render_search_page()
    assert "未开启" in html


def test_plugin_page_legacy_keys_alignable():
    """配置对齐：插件页白名单补上 LEGACY_CALL_TIMEOUT 两键（.env 与 WebUI 对齐）。"""
    import src.services.webui_panels.plugin_panel as pp_mod
    import src.services.webui_render.plugins as plugins_mod
    for mod in (pp_mod, plugins_mod):
        src = open(mod.__file__, encoding="utf-8").read()
        assert "PLUGIN_LEGACY_CALL_TIMEOUT_MAX" in src