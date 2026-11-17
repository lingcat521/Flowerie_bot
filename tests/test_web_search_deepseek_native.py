"""DeepSeek 原生搜索（deepseek-native 引擎）的解析与容错。

搜索由模型在服务端执行（Anthropic 兼容 Messages + web_search_20250305 工具），
这里只验证：结果块解析、citations 摘要映射、去重、以及各类失败的降级语义。
"""
import asyncio
from types import SimpleNamespace

import httpx
import pytest

from src.services.ai_tools import AiToolRegistry
from src.services.web_search import ENGINE_IDS, WebSearchService


def _cfg(**over):
    base = dict(
        SEARCH_DEEPSEEK_API_KEY="sk-test",
        SEARCH_DEEPSEEK_MODEL="deepseek-v4-flash",
        SEARCH_DEEPSEEK_MAX_USES=3,
        SEARCH_TIMEOUT=10,
        SEARCH_BLOCKED_DOMAINS=[],
        SEARCH_SAFE_SEARCH="off",
    )
    base.update(over)
    return SimpleNamespace(**base)


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _Client:
    # WebSearchService.client 会读 is_closed 判断是否重建
    is_closed = False

    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    async def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({'url': url, 'body': json, 'headers': headers or {}})
        return self.resp


def _svc(resp, **over):
    client = _Client(resp)
    svc = WebSearchService(_cfg(**over), client_factory=lambda: client)
    svc._client = client
    return svc, client


def test_engine_registered():
    assert "deepseek-native" in ENGINE_IDS


def test_parses_results_with_citation_snippets_and_pages():
    resp = _Resp(200, {
        "content": [
            {"type": "text", "text": "...",
             "citations": [{"url": "https://a.example/x", "cited_text": "A 摘要"}]},
            {"type": "web_search_tool_result", "content": [
                {"type": "web_search_result", "url": "https://a.example/x",
                 "title": "A", "page_age": "2026-11-10"},
                {"type": "web_search_result", "url": "https://b.example/y", "title": "B"},
                {"type": "web_search_result", "url": "https://a.example/x", "title": "A 重复"},
            ]},
        ]})
    svc, client = _svc(resp)
    out = asyncio.run(svc._search_deepseek_native("q", 10, None, None))
    assert [s["url"] for s in out] == ["https://a.example/x", "https://b.example/y"]
    assert out[0]["snippet"] == "A 摘要"
    assert out[0]["publishedAt"] == "2026-11-10"
    assert "snippet" not in out[1]
    body = client.calls[0]["body"]
    assert body["tools"][0]["type"] == "web_search_20250305"
    assert body["tools"][0]["max_uses"] == 3
    assert body["thinking"] == {"type": "disabled"}
    assert client.calls[0]["headers"]["anthropic-version"] == "2023-06-01"


def test_no_result_block_is_error_not_scraping():
    svc, _ = _svc(_Resp(200, {"content": [{"type": "text", "text": "只有文本"}]}))
    with pytest.raises(httpx.HTTPError, match="web_search_tool_result"):
        asyncio.run(svc._search_deepseek_native("q", 5, None, None))


def test_missing_key_is_error():
    svc, client = _svc(_Resp(200, {}), SEARCH_DEEPSEEK_API_KEY="", DEEPSEEK_API_KEY="")
    with pytest.raises(httpx.HTTPError, match="未配置"):
        asyncio.run(svc._search_deepseek_native("q", 5, None, None))
    assert client.calls == []


def test_401_is_error():
    svc, _ = _svc(_Resp(401, {}))
    with pytest.raises(httpx.HTTPError, match="凭据无效"):
        asyncio.run(svc._search_deepseek_native("q", 5, None, None))


def test_non_200_carries_detail():
    svc, _ = _svc(_Resp(429, {"error": {"message": "rate limited"}}))
    with pytest.raises(httpx.HTTPError, match="rate limited"):
        asyncio.run(svc._search_deepseek_native("q", 5, None, None))


def test_bad_json_is_error():
    svc, _ = _svc(_Resp(200, ValueError("nope")))
    with pytest.raises(httpx.HTTPError, match="合法 JSON"):
        asyncio.run(svc._search_deepseek_native("q", 5, None, None))


# ---------- 「有 key 优先 DeepSeek，无 key 用免费引擎」的自动编排 ----------


def _order(**over):
    svc, _ = _svc(_Resp(200, {}), **over)
    return svc._engine_order()


def test_no_key_uses_free_engines_only():
    assert _order(SEARCH_TIMEOUT=10) == ["ddg", "bing", "searxng", "ddg-lite"]
    assert "deepseek-native" not in _order(SEARCH_TIMEOUT=10)


def test_placeholder_key_is_treated_as_unconfigured():
    # 模板值不该让链路先打一个必然 401 的端点
    for placeholder in ("sk-original", "sk-your-key-here", "changeme"):
        order = _order(SEARCH_TIMEOUT=10, SEARCH_DEEPSEEK_API_KEY=placeholder)
        assert order == ["ddg", "bing", "searxng", "ddg-lite"], placeholder


def test_real_key_puts_deepseek_first():
    order = _order(SEARCH_TIMEOUT=10, SEARCH_DEEPSEEK_API_KEY="", DEEPSEEK_API_KEY="sk-" + "a" * 32)
    assert order[0] == "deepseek-native"
    assert order[1:] == ["ddg", "bing", "searxng", "ddg-lite"]


def test_explicit_position_is_respected():
    order = _order(SEARCH_TIMEOUT=10, SEARCH_DEEPSEEK_API_KEY="sk-" + "b" * 32,
                   SEARCH_ENGINES="ddg,deepseek-native,bing")
    assert order == ["ddg", "deepseek-native", "bing"]


def test_priority_switch_off():
    order = _order(SEARCH_TIMEOUT=10, SEARCH_DEEPSEEK_API_KEY="sk-" + "c" * 32,
                   SEARCH_DEEPSEEK_PRIORITY=False)
    assert order == ["ddg", "bing", "searxng", "ddg-lite"]


def test_explicit_but_unconfigured_is_removed():
    # 显式写了 deepseek-native 但没凭据：剔除（否则每次必挂）
    assert _order(SEARCH_TIMEOUT=10, SEARCH_ENGINES="deepseek-native,ddg") == ["ddg"]


def test_empty_config_falls_back_to_free_chain():
    assert _order(SEARCH_TIMEOUT=10, SEARCH_ENGINES="nonsense") == ["ddg", "bing", "searxng", "ddg-lite"]


# ---------- 模型自主选择引擎（有 API 凭据时才暴露 engine 参数） ----------


def _tool_props(cfg):
    svc = WebSearchService(cfg)
    reg = AiToolRegistry(cfg, search_service=svc)
    found = [s['function'] for s in reg.schemas() if s['function']['name'] == 'web_search']
    return (found[0]['parameters']['properties'] if found else {}), svc, reg


@pytest.fixture
def _base_cfg():
    def mk(**over):
        base = dict(
            SEARCH_TIMEOUT=10, SEARCH_MAX_RESULTS=5, SEARCH_BLOCKED_DOMAINS=[],
            SEARCH_SAFE_SEARCH="off", SEARCH_CACHE_TTL=0, AI_SEARCH_ENABLED=True,
            SEARCH_FETCH_MAX_CHARS=2000,
        )
        base.update(over)
        return SimpleNamespace(**base)
    return mk


def test_engine_param_exposed_only_with_api_credentials(_base_cfg):
    props, svc, _ = _tool_props(_base_cfg(SEARCH_DEEPSEEK_API_KEY="sk-" + "a" * 32))
    assert "engine" in props
    assert "deepseek-native" in props["engine"]["enum"]
    assert "ddg" in props["engine"]["enum"]
    asyncio.run(svc.close())


def test_engine_param_hidden_without_credentials(_base_cfg):
    props, svc, _ = _tool_props(_base_cfg(SEARCH_DEEPSEEK_API_KEY="", DEEPSEEK_API_KEY=""))
    assert "engine" not in props, "无凭据时不该让模型在免费引擎间做无意义选择"
    asyncio.run(svc.close())


def test_engine_param_hidden_for_placeholder_key(_base_cfg):
    props, svc, _ = _tool_props(
        _base_cfg(SEARCH_DEEPSEEK_API_KEY="sk-original", DEEPSEEK_API_KEY="")
    )
    assert "engine" not in props
    asyncio.run(svc.close())


def test_engine_hint_mentions_cost_tradeoff(_base_cfg):
    props, svc, _ = _tool_props(_base_cfg(SEARCH_DEEPSEEK_API_KEY="sk-" + "b" * 32))
    desc = props["engine"]["description"]
    assert "deepseek-native" in desc
    assert "计费" in desc or "token" in desc
    assert "免费" in desc
    asyncio.run(svc.close())


def test_unknown_engine_is_ignored_not_fatal(_base_cfg):
    """模型乱传引擎名时不该打断对话：忽略该参数，回退自动编排。"""
    cfg = _base_cfg(SEARCH_DEEPSEEK_API_KEY="sk-" + "c" * 32)
    svc = WebSearchService(cfg)
    reg = AiToolRegistry(cfg, search_service=svc)
    assert "not-a-real-engine" not in reg._available_engines()
    # 只看校验逻辑：把 search 换成记录调用的桩
    captured = {}

    async def fake_search(query, time_range=None, engine=None):
        captured["engine"] = engine
        return {"ok": True, "sources": []}

    reg.search = SimpleNamespace(search=fake_search)
    asyncio.run(reg._web_search({"query": "x", "engine": "not-a-real-engine"}))
    assert captured["engine"] is None, "非法引擎应被清空"


def test_explicit_engine_is_passed_through(_base_cfg):
    cfg = _base_cfg(SEARCH_DEEPSEEK_API_KEY="sk-" + "d" * 32)
    svc = WebSearchService(cfg)
    reg = AiToolRegistry(cfg, search_service=svc)
    captured = {}

    async def fake_search(query, time_range=None, engine=None):
        captured["engine"] = engine
        return {"ok": True, "sources": []}

    reg.search = SimpleNamespace(search=fake_search)
    asyncio.run(reg._web_search({"query": "x", "engine": "ddg"}))
    assert captured["engine"] == "ddg"


# ---------- 付费搜索总开关 SEARCH_PAID_ENABLED ----------


def _real_key():
    return "sk-" + "17343de97489477988ba1b24474d70c4"


def test_paid_switch_off_removes_engine_even_with_key():
    order = _order(SEARCH_TIMEOUT=10, SEARCH_DEEPSEEK_API_KEY=_real_key(),
                   SEARCH_PAID_ENABLED=False)
    assert order == ["ddg", "bing", "searxng", "ddg-lite"]


def test_paid_switch_off_overrides_explicit_config():
    """显式写进 SEARCH_ENGINES 也不用 —— 这是「允许不允许」而非「排前面」."""
    order = _order(SEARCH_TIMEOUT=10, SEARCH_DEEPSEEK_API_KEY=_real_key(),
                   SEARCH_PAID_ENABLED=False,
                   SEARCH_ENGINES="deepseek-native,ddg")
    assert order == ["ddg"]


def test_paid_switch_on_with_key_uses_engine():
    order = _order(SEARCH_TIMEOUT=10, SEARCH_DEEPSEEK_API_KEY=_real_key(),
                   SEARCH_PAID_ENABLED=True)
    assert order[0] == "deepseek-native"


def test_usable_requires_both_switch_and_key():
    svc_on, _ = _svc(_Resp(200, {}), SEARCH_TIMEOUT=10,
                     SEARCH_DEEPSEEK_API_KEY=_real_key(), SEARCH_PAID_ENABLED=True)
    assert svc_on.deepseek_native_usable() is True
    assert svc_on.deepseek_native_ready() is True

    svc_off, _ = _svc(_Resp(200, {}), SEARCH_TIMEOUT=10,
                      SEARCH_DEEPSEEK_API_KEY=_real_key(), SEARCH_PAID_ENABLED=False)
    assert svc_off.deepseek_native_usable() is False
    assert svc_off.deepseek_native_ready() is True, "凭据本身仍可用，只是不允许花钱"


def test_paid_switch_hides_engine_from_ai_tool():
    props, svc, _ = _tool_props(SimpleNamespace(
        SEARCH_TIMEOUT=10, SEARCH_MAX_RESULTS=5, SEARCH_BLOCKED_DOMAINS=[],
        SEARCH_SAFE_SEARCH="off", SEARCH_CACHE_TTL=0, AI_SEARCH_ENABLED=True,
        SEARCH_FETCH_MAX_CHARS=2000,
        SEARCH_DEEPSEEK_API_KEY=_real_key(), SEARCH_PAID_ENABLED=False))
    assert "engine" not in props, "关了付费开关就不该让模型选它"
    asyncio.run(svc.close())


def test_paid_switch_defaults_on():
    svc, _ = _svc(_Resp(200, {}), SEARCH_TIMEOUT=10)
    assert svc.paid_search_enabled() is True


def test_paid_switch_registered_in_env_and_schema():
    """开关必须同时存在于 .env 模板与 Web UI 的 SCHEMA 里。"""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    env_example = (root / ".env_example").read_text(encoding="utf-8")
    assert "SEARCH_PAID_ENABLED" in env_example
    from src.services.config_schema import SCHEMA
    assert "SEARCH_PAID_ENABLED" in SCHEMA
    assert SCHEMA["SEARCH_PAID_ENABLED"][0] == "Search"
    from src.config import Settings
    assert "SEARCH_PAID_ENABLED" in Settings.model_fields
