"""搜索 Web UI 路由、配置热更新和连通性测试。"""
import json
import time
from unittest.mock import AsyncMock

import httpx
import pytest
from yarl import URL

from src.services.config_service import ConfigService
from src.services.web_search import WebSearchService
from tests.test_web_ui_panel import FakeRequest, _login, _make_stack

_VALID_KEY = "fixture-only-0123456789abcdef"
_FREE = ["ddg", "bing", "searxng", "ddg-lite"]


@pytest.fixture
def server(tmp_path):
    config, _, _, server = _make_stack(tmp_path)
    config.DEEPSEEK_API_KEY = ""
    server._search_service_ref = WebSearchService(config)
    return server


@pytest.mark.parametrize(
    "paid,key,configured,order,search_status,account_status",
    [
        (True, _VALID_KEY, ",".join(_FREE), ["deepseek-native", *_FREE], "可用", "已配置"),
        (True, "", ",".join(_FREE), _FREE, "未配置", "未配置（自动使用免费引擎）"),
        (True, "sk-original-replace-me", ",".join(_FREE), _FREE, "模板值", "仍是模板值"),
        (False, _VALID_KEY, ",".join(_FREE), _FREE, "已禁用", "已禁用（付费搜索关闭）"),
        (False, _VALID_KEY, "deepseek-native,ddg", ["ddg"], "已禁用", "已禁用（付费搜索关闭）"),
    ],
)
async def test_search_and_account_status(server, paid, key, configured, order, search_status, account_status):
    server.config.SEARCH_PAID_ENABLED = paid
    server.config.SEARCH_DEEPSEEK_API_KEY = key
    server.config.SEARCH_ENGINES = configured
    cookies = {"fb_token": await _login(server)}
    response = await server._handle_panel(FakeRequest(cookies=cookies, query={"tab": "search"}))
    html = response.text
    assert response.status == 200
    assert server._search_service()._engine_order() == order
    chain = html.split('class="search-chain">', 1)[1].split("</p>", 1)[0]
    assert [piece.split("</code>", 1)[0] for piece in chain.split("<code>")[1:]] == order
    native_card = html.split('DeepSeek · 原生搜索（服务端工具）', 1)[1].split("</article>", 1)[0]
    assert f">{search_status}</span>" in native_card
    assert "按 token 计费" in native_card
    for name, metadata in ConfigService.SCHEMA.items():
        if metadata[0] == "Search":
            assert f'name="{name}"' in html
    assert "<script" not in html
    account = await server._handle_panel(FakeRequest(cookies=cookies, query={"tab": "account"}))
    assert account_status in account.text
    assert 'name="target" value="search"' in account.text
    if key:
        assert key not in html and key not in account.text


async def test_priority_and_paid_toggle_persist_on_search_page(server):
    server.config.DEEPSEEK_API_KEY = _VALID_KEY
    server.config.SEARCH_DEEPSEEK_PRIORITY = False
    server.config.SEARCH_ENGINES = "ddg,deepseek-native,bing"
    cookies = {"fb_token": await _login(server)}
    assert "字面配置" in server._render_search_page()
    assert server._search_service()._engine_order() == ["ddg", "deepseek-native", "bing"]
    for paid in (False, True):
        response = await server._handle_panel_save(FakeRequest(
            cookies=cookies, query={"cat": "Search"},
            form={"key": "SEARCH_PAID_ENABLED", "value": str(paid).lower()},
        ))
        assert "cat=Search" in str(response.location)
        assert server.config_service.repository.get_config("SEARCH_PAID_ENABLED") == str(paid).lower()
        assert ("deepseek-native" in server._search_service()._engine_order()) is paid
    page = await server._handle_panel(FakeRequest(cookies=cookies, query={"cat": "Search"}))
    assert 'id="search-order"' in page.text
    assert "复用聊天 Key" in server._render_account_page()


async def test_dedicated_key_is_masked_preserved_and_can_be_cleared(server):
    server.config.SEARCH_DEEPSEEK_API_KEY = _VALID_KEY
    server.config.DEEPSEEK_API_KEY = _VALID_KEY + "-fallback"
    cookies = {"fb_token": await _login(server)}
    entry = next(c for c in server.config_service.list_configs() if c["key"] == "SEARCH_DEEPSEEK_API_KEY")
    assert entry["secret"] and _VALID_KEY not in entry["current"]
    form = {"SEARCH_DEEPSEEK_API_KEY": "", "SEARCH_MAX_RESULTS": "4"}
    await server._handle_panel_save(FakeRequest(cookies=cookies, query={"cat": "Search"}, form=form))
    assert server.config.SEARCH_DEEPSEEK_API_KEY == _VALID_KEY
    form["clear_search_key"] = "true"
    await server._handle_panel_save(FakeRequest(cookies=cookies, query={"cat": "Search"}, form=form))
    assert server.config.SEARCH_DEEPSEEK_API_KEY == ""
    assert server._search_service().deepseek_native_ready()
    assert "复用聊天 Key" in server._render_account_page()


async def test_probe_uses_preferred_engine_and_reports_actual_hit(server, monkeypatch):
    svc = server._search_service()
    search = AsyncMock(return_value={"ok": True, "engine": "ddg", "sources": []})
    monkeypatch.setattr(svc, "search", search)
    cookies = {"fb_token": await _login(server)}
    request = FakeRequest(cookies=cookies, form={"query": "Flowerie", "engine": "bing"})
    await server._handle_panel_search_probe(request)
    search.assert_awaited_once_with("Flowerie", max_results=5, engine="bing")
    assert "实际命中引擎 ddg" in server._render_search_page()
    search.reset_mock()
    server.config.SEARCH_PAID_ENABLED = False
    server.config.DEEPSEEK_API_KEY = _VALID_KEY
    for engine in ("deepseek-native", "invalid"):
        response = await server._handle_panel_search_probe(FakeRequest(cookies=cookies, form={"engine": engine}))
        assert URL(response.location).query["err"] == "1"
    search.assert_not_awaited()


async def test_self_check_reports_elapsed_budget_and_failure(server, monkeypatch):
    server.config.SEARCH_DEEPSEEK_API_KEY = _VALID_KEY
    server.config.SEARCH_ENGINES = "ddg,bing"
    svc = server._search_service()
    svc._cooldowns["bing"] = time.monotonic() + 60
    dispatch = AsyncMock(side_effect=[[{"url": "https://example.com"}], [], TimeoutError()])
    monkeypatch.setattr(svc, "_dispatch", dispatch)
    cookies = {"fb_token": await _login(server)}
    response = await server._handle_panel_search_test(FakeRequest(cookies=cookies))
    assert URL(response.location).query["tab"] == "search"
    assert [call.args[0] for call in dispatch.await_args_list] == ["deepseek-native", "ddg", "bing"]
    result = server._search_test_cache
    assert result["deepseek-native"]["budget"] > result["ddg"]["budget"] == 40
    assert not result["ddg"]["ok"] and not result["bing"]["ok"]
    html = server._render_search_page()
    for text in ("本次耗时", "预算 45 秒", "预算 40 秒", "完整模型回合", "上次失败", "冷却中"):
        assert text in html


@pytest.mark.parametrize(
    "status,message",
    [(200, "未消耗搜索额度"), (401, "Key 无效"), (404, "端点路径有误")],
)
async def test_account_ping_uses_no_search_tools(server, monkeypatch, status, message):
    server.config.SEARCH_PAID_ENABLED = False
    server.config.DEEPSEEK_API_KEY = _VALID_KEY
    cookies = {"fb_token": await _login(server)}
    client_class = httpx.AsyncClient
    sent = []

    def respond(request):
        sent.append(request)
        return httpx.Response(status, json={"content": [{"type": "text", "text": "pong"}]})

    def client(*, timeout):
        assert timeout == 20
        return client_class(timeout=timeout, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(httpx, "AsyncClient", client)
    response = await server._handle_panel_model_test(FakeRequest(
        cookies=cookies, form={"target": "search", "back": "account"},
    ))
    assert URL(response.location).query["tab"] == "account"
    result = URL(response.location).query["msg"]
    assert message in result and "付费搜索当前已关闭" in result
    request, = sent
    assert request.url.path == "/anthropic/v1/messages"
    assert request.headers["x-api-key"] == _VALID_KEY
    payload = json.loads(request.content)
    assert payload["max_tokens"] == 16 and "tools" not in payload


@pytest.mark.parametrize("key,status", [("", "未配置搜索 Key"), ("sk-test-template", "仍是模板值")])
async def test_account_ping_handles_unusable_key_locally(server, monkeypatch, key, status):
    server.config.SEARCH_DEEPSEEK_API_KEY = key

    def unexpected_client(*args, **kwargs):
        pytest.fail("未配置有效 Key 时不应创建网络客户端")

    monkeypatch.setattr(httpx, "AsyncClient", unexpected_client)
    cookies = {"fb_token": await _login(server)}
    response = await server._handle_panel_model_test(FakeRequest(cookies=cookies, form={"target": "search"}))
    assert URL(response.location).query["cat"] == "Search"
    assert status in URL(response.location).query["msg"]
