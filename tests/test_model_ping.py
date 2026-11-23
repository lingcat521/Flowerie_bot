"""Coverage for the shared Web UI, HTTP and plugin model probes."""

import asyncio
import json

import httpx
import pytest
from aiohttp.test_utils import TestClient, TestServer

from src.config import Settings
from src.plugins.manager import PluginManager
from src.repositories.settings_repository import SettingsRepository
from src.services.config_service import ConfigService
from src.services.model_ping import MODEL_LABELS, ModelPingService
from src.services.web_ui import WebUIServer


@pytest.fixture
def stack(tmp_path):
    cfg = Settings(
        _env_file=None, BOT_QQ=10001, DEEPSEEK_API_KEY="sample-model-secret",
        DEEPSEEK_API_URL="https://example.test/chat",
        MESSAGE_ANALYSIS_API_URL="https://example.test/preferences",
        MESSAGE_ANALYSIS_PREFERENCE_MODEL="preferences",
        MESSAGE_ANALYSIS_TOXIC_MODEL="moderator",
        MESSAGE_ANALYSIS_TOXIC_API_URL="https://example.test/moderator",
        BLOSSOM_MEMORY_EMBEDDING_MODEL="embed",
        BLOSSOM_MEMORY_EMBEDDING_API_URL="https://example.test/embed",
        BLOSSOM_MEMORY_RERANKER_MODEL="rerank",
        BLOSSOM_MEMORY_RERANKER_API_URL="https://example.test/rerank",
        SEARCH_DEEPSEEK_BASE_URL="https://example.test/anthropic/v1",
        SEARCH_DEEPSEEK_API_KEY="example-credential-123456",
        PLUGIN_DIR=str(tmp_path / "plugins"),
    )
    repo = SettingsRepository(str(tmp_path / "settings.db"))
    pings = ModelPingService(cfg)
    server = WebUIServer(cfg, ConfigService(cfg, repo), data_dir=str(tmp_path / "webui"), model_pings=pings)
    try:
        yield cfg, repo, pings, server
    finally:
        repo.close()


def mock_transport(monkeypatch, handler):
    original_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))


@pytest.mark.asyncio
async def test_http_ping_all_runs_parallel_deduplicates_and_reports_failures(stack, monkeypatch):
    cfg, _, _, server = stack
    six_requests_started = asyncio.Event()
    sent = {}

    async def respond(request):
        path = request.url.path
        sent[path] = json.loads(request.content)
        if len(sent) == 6:
            six_requests_started.set()
        await asyncio.wait_for(six_requests_started.wait(), timeout=2)
        if path == "/preferences":
            return httpx.Response(200, text="<html>reverse proxy</html>")
        if path == "/moderator":
            return httpx.Response(307, headers={"Location": "https://other.example/"},
                                  text=cfg.DEEPSEEK_API_KEY)
        if path == "/embed":
            return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})
        if path == "/rerank":
            return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.9}]})
        if path == "/anthropic/v1/messages":
            return httpx.Response(200, json={"content": [{"type": "text", "text": "pong"}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})

    mock_transport(monkeypatch, respond)
    async with TestClient(TestServer(server.build_app())) as client:
        path = "/api/models/ping"
        assert (await client.post(path)).status == 401
        headers = {"Authorization": "Bearer " + server._issue_token()}
        assert (await client.post(path, json={"url": "https://other.example/"}, headers=headers)).status == 400
        assert (await client.post(path, json={"target": []}, headers=headers)).status == 400
        assert not sent
        response = await client.post(path, headers=headers)
        assert response.status == 200
        data = await response.json()
        assert not data["ok"]
        rows = data["results"]
        assert rows.keys() == MODEL_LABELS.keys()
        assert rows["vision"] == rows["toxic"] == rows["chat"]
        assert rows["chat"]["status"] == rows["search"]["status"] == "reachable"
        assert rows["embedding"]["status"] == rows["reranker"]["status"] == "reachable"
        assert rows["analysis_preference"]["status"] == "invalid_response"
        assert rows["analysis_toxic"]["http_status"] == 307
        assert cfg.DEEPSEEK_API_KEY not in await response.text()
        assert set(sent) == {"/chat", "/preferences", "/moderator", "/embed", "/rerank", "/anthropic/v1/messages"}
        assert sent["/chat"]["messages"] == [{"role": "user", "content": "ping"}]
        assert sent["/embed"]["input"] == "ping"
        assert sent["/rerank"]["query"] == "ping"
        assert "tools" not in sent["/anthropic/v1/messages"]


@pytest.mark.asyncio
async def test_plugin_ping_requires_permission_and_busy_is_shared(stack, monkeypatch):
    cfg, repo, pings, server = stack
    manager = PluginManager(cfg, repo, model_pings=pings)
    approved = []
    monkeypatch.setattr(manager, "get_plugin", lambda _: {"enabled": True, "approved_permissions": approved})
    denied = await manager._handle_engine_op("example", "models.ping", {"target": "chat"})
    assert denied["denied"]
    approved.append("ping_models")
    assert (await manager._handle_engine_op("example", "models.ping", {}))["code"] == "invalid_argument"
    arrived, finish = asyncio.Event(), asyncio.Event()

    async def respond(request):
        arrived.set()
        await finish.wait()
        raise httpx.ReadTimeout("upstream error text", request=request)

    mock_transport(monkeypatch, respond)
    cfg.BLOSSOM_MEMORY_EMBEDDING_API_URL = ""
    skipped = await manager._handle_engine_op("example", "models.ping", {"target": "embedding"})
    assert skipped["results"]["embedding"]["status"] == "unconfigured"
    assert not arrived.is_set()
    ping = asyncio.create_task(manager._handle_engine_op("example", "models.ping", {"target": "chat"}))
    try:
        await asyncio.wait_for(arrived.wait(), timeout=2)
        async with TestClient(TestServer(server.build_app())) as client:
            headers = {"Authorization": "Bearer " + server._issue_token()}
            response = await client.post("/api/models/ping", json={"target": "all"}, headers=headers)
            assert response.status == 429
    finally:
        finish.set()
        outcome = await ping
    assert outcome["results"]["chat"]["status"] == "timeout"
    assert "upstream error text" not in json.dumps(outcome)


@pytest.mark.asyncio
async def test_single_vision_ping_keeps_distinct_model_on_shared_endpoint(stack, monkeypatch):
    cfg, _, pings, _ = stack
    cfg.VISION_MODEL = "separate-vision"
    sent = []

    def respond(request):
        sent.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})

    mock_transport(monkeypatch, respond)
    outcome = await pings.ping({"target": "vision"})
    request, = sent
    assert str(request.url) == cfg.DEEPSEEK_API_URL
    assert json.loads(request.content)["model"] == "separate-vision"
    assert outcome["ok"] and list(outcome["results"]) == ["vision"]
