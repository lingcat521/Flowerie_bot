import json

import httpx
import pytest
from yarl import URL

from src.config import Settings, validate_config
from tests.test_router_regression import build_router, make_config
from tests.test_web_ui_panel import FakeRequest, _login, _make_stack


def event(message_id, text, group_id=123):
    return {"post_type": "message", "message_type": "group", "group_id": group_id,
            "user_id": 456, "message_id": message_id, "message": text}


def completion(toxic=False, preference=None):
    content = json.dumps({"toxic": toxic, "preference": preference})
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def analysis_router(**overrides):
    options = dict(MESSAGE_ANALYSIS_GROUP_IDS=[123], MESSAGE_ANALYSIS_MODEL="test-analyzer",
                   MESSAGE_ANALYSIS_API_URL="http://model.test/v1/chat/completions", MESSAGE_ANALYSIS_API_KEY="",
                   MESSAGE_ANALYSIS_TIMEOUT=1, MESSAGE_ANALYSIS_DAILY_LIMIT=10,
                   MESSAGE_ANALYSIS_GROUP_DAILY_LIMIT=10, TOXIC_GROUP_IDS=[123], ONLY_REPLY_WHEN_AT=True)
    return build_router(make_config(**(options | overrides)))


@pytest.mark.asyncio
async def test_group_analysis_routes_both_tasks_and_keeps_legacy_for_other_groups():
    router, _, ai, sender, memory = analysis_router()
    requests = []
    phrase = "每次点单我都选无糖，奶茶也一样"
    attack = "你的出现就是我们群唯一需要解决的问题"

    def respond(request):
        payload = json.loads(request.content)
        assert payload["model"] == "test-analyzer"
        message = json.loads(payload["messages"][1]["content"])
        requests.append(message)
        return completion(toxic=message["message"] == attack,
                          preference="每次点单我都选无糖" if message["message"] == phrase else None)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as ai.client:
        await router.process_event(event(1, phrase))
        await router.process_event(event(2, attack))
        await router.process_event(event(3, attack))
        await router.process_event(event(4, attack))
        await router.process_event(event(5, "我喜欢喝奶茶", group_id=124))

    assert len(requests) == 4
    assert requests[0]["detect_preference"] and requests[0]["detect_toxic"]
    assert requests[0]["recent"] == []
    assert requests[1]["recent"] == [{"speaker": 0, "text": phrase}]
    assert [(uid, gid, text) for uid, gid, text, _ in memory.writes] == [
        (456, 123, phrase), (456, 124, "我喜欢喝奶茶"),
    ]
    assert len(sender.sent) == 1 and "引战" in sender.sent[0][1]
    assert ai.calls == router.global_state.ai_budget_count == 0


@pytest.mark.asyncio
async def test_analysis_rejects_invented_preference_and_enforces_group_limit():
    router, _, ai, sender, memory = analysis_router(MESSAGE_ANALYSIS_GROUP_DAILY_LIMIT=1, TOXIC_GROUP_IDS=[])
    requests = []

    def respond(request):
        requests.append(request)
        return completion(toxic=True, preference="我喜欢芹菜")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as ai.client:
        await router.process_event(event(1, "我从来都不吃芹菜"))
        await router.process_event(event(2, "我喜欢喝奶茶"))

    assert len(requests) == 1
    assert not memory.writes
    assert not sender.sent
    assert len(router.policy_engine.get_group_state(123).context) == 2


@pytest.mark.asyncio
async def test_analysis_error_preserves_mentioned_chat_and_memory_switch():
    router, _, ai, sender, memory = analysis_router(MEMORY_DISABLED_GROUPS=[123])
    requests = []

    def respond(request):
        requests.append(json.loads(json.loads(request.content)["messages"][1]["content"]))
        return httpx.Response(503)

    message = event(1, "我喜欢喝奶茶")
    message["message"] = [{"type": "at", "data": {"qq": "10001"}},
                          {"type": "text", "data": {"text": "我喜欢喝奶茶"}}]
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as ai.client:
        await router.process_event(message)
        await router.process_event(event(2, "我喜欢喝咖啡"))

    assert len(requests) == 1 and requests[0]["detect_preference"] is False
    assert ai.calls == 1 and sender.sent == [(123, "回复内容")]
    assert not memory.writes


def test_analysis_group_ids_load_from_env(monkeypatch):
    monkeypatch.setenv("MESSAGE_ANALYSIS_GROUP_IDS", "[123,456]")
    settings = Settings(_env_file=None, BOT_QQ=10001, DEEPSEEK_API_KEY="fake")
    assert settings.MESSAGE_ANALYSIS_GROUP_IDS == [123, 456]


@pytest.mark.asyncio
async def test_separate_analysis_models_isolate_credentials_and_failures():
    router, _, ai, sender, memory = analysis_router(
        MESSAGE_ANALYSIS_API_KEY="shared-fixture-token",
        MESSAGE_ANALYSIS_PREFERENCE_API_URL="http://memory.test/v1/chat/completions",
        MESSAGE_ANALYSIS_PREFERENCE_MODEL="memory-model",
        MESSAGE_ANALYSIS_TOXIC_MODEL="toxicity-model",
    )
    seen = []

    def respond(request):
        payload = json.loads(request.content)
        message = json.loads(payload["messages"][1]["content"])
        seen.append((request.url.host, payload["model"], request.headers.get("Authorization"),
                     message["detect_toxic"], message["detect_preference"]))
        if request.url.host == "model.test":
            return httpx.Response(503)
        assert message["recent"] == []
        return completion(toxic=True, preference=message["message"])

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as ai.client:
        await router.process_event(event(1, "每次都选无糖"))
        await router.process_event(event(2, "我从不吃香菜"))

    assert seen == [("model.test", "toxicity-model", "Bearer shared-fixture-token", True, False),
                    ("memory.test", "memory-model", None, False, True),
                    ("memory.test", "memory-model", None, False, True)]
    assert [write[2] for write in memory.writes] == ["每次都选无糖", "我从不吃香菜"]
    assert not sender.sent


@pytest.mark.asyncio
async def test_analysis_provider_settings_save_to_env_and_clear_key(tmp_path):
    config, repo, service, server = _make_stack(tmp_path)
    cookies = {"fb_token": await _login(server)}
    query = {"cat": "AI"}
    values = {
        "MESSAGE_ANALYSIS_GROUP_IDS": "123",
        "MESSAGE_ANALYSIS_PREFERENCE_API_URL": "http://localhost:11434/v1/chat/completions",
        "MESSAGE_ANALYSIS_PREFERENCE_API_KEY": "memory-fixture-token",
        "MESSAGE_ANALYSIS_PREFERENCE_MODEL": "memory-test-model",
        "MESSAGE_ANALYSIS_TOXIC_API_URL": "https://model.test/v1/chat/completions",
        "MESSAGE_ANALYSIS_TOXIC_API_KEY": "toxic-fixture-token",
        "MESSAGE_ANALYSIS_TOXIC_MODEL": "toxicity-test-model",
    }
    try:
        response = await server._handle_panel_save(FakeRequest(cookies=cookies, query=query, form=values))
        assert URL(response.location).query["err"] == ""
        assert config.MESSAGE_ANALYSIS_GROUP_IDS == [123]
        assert config.MESSAGE_ANALYSIS_TOXIC_MODEL == values["MESSAGE_ANALYSIS_TOXIC_MODEL"]
        page = await server._handle_panel(FakeRequest(cookies=cookies, query=query))
        assert all(f'name="{key}"' in page.text for key in values)
        assert all(value not in page.text for key, value in values.items() if key.endswith("_KEY"))

        key = "MESSAGE_ANALYSIS_PREFERENCE_API_KEY"
        assert f'name="clear_{key}"' in page.text
        await server._handle_panel_save(FakeRequest(cookies=cookies, query=query, form={key: ""}))
        assert getattr(config, key) == values[key]
        response = await server._handle_panel_save(FakeRequest(
            cookies=cookies, query=query, form={key: "", f"clear_{key}": "true"},
        ))
        assert URL(response.location).query["err"] == ""
        assert getattr(config, key) == repo.get_config(key) == ""

        env_path = tmp_path / ".env"
        settings = Settings(_env_file=env_path, BOT_QQ=10001, DEEPSEEK_API_KEY="test-fixture-key")
        validate_config(settings)
        assert settings.MESSAGE_ANALYSIS_PREFERENCE_API_KEY == ""
        assert settings.MESSAGE_ANALYSIS_PREFERENCE_MODEL == "memory-test-model"
        assert settings.MESSAGE_ANALYSIS_TOXIC_API_KEY == values["MESSAGE_ANALYSIS_TOXIC_API_KEY"]

        env_path.write_text(env_path.read_text().replace("memory-test-model", "manual-model"))
        settings = Settings(_env_file=env_path, BOT_QQ=10001, DEEPSEEK_API_KEY="test-fixture-key")
        type(service)(settings, repo, env_path=str(env_path)).apply_persisted()
        assert settings.MESSAGE_ANALYSIS_PREFERENCE_MODEL == "manual-model"
        assert settings.MESSAGE_ANALYSIS_TOXIC_MODEL == "toxicity-test-model"
    finally:
        repo.close()


@pytest.mark.parametrize(("target", "result", "expected"), [
    ("analysis_preference", "success", "喜好提取模型连接成功"),
    ("analysis_toxic", "denied", "HTTP 401"),
    ("analysis_toxic", "invalid", "不是有效的 Chat Completions 响应"),
])
async def test_account_analysis_ping_uses_effective_model(tmp_path, monkeypatch, target, result, expected):
    config, repo, _, server = _make_stack(tmp_path)
    config.MESSAGE_ANALYSIS_API_URL = "http://127.0.0.1:11434/v1/chat/completions"
    config.MESSAGE_ANALYSIS_PREFERENCE_MODEL = "preference-fixture-model"
    config.MESSAGE_ANALYSIS_TOXIC_API_URL = "https://moderation.test/v1/chat/completions"
    config.MESSAGE_ANALYSIS_TOXIC_API_KEY = "moderation-fixture-secret"
    config.MESSAGE_ANALYSIS_TOXIC_MODEL = "moderation-fixture-model"
    cookies = {"fb_token": await _login(server)}
    client_type = httpx.AsyncClient
    sent = []

    def respond(request):
        sent.append(request)
        if result == "denied":
            # 错误响应可能回显请求凭据，不应带入重定向 URL 或页面。
            return httpx.Response(401, text=config.MESSAGE_ANALYSIS_TOXIC_API_KEY)
        if result == "invalid":
            return httpx.Response(200, text="<html>proxy</html>")
        return completion()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(respond), **kw))
    try:
        page = await server._handle_panel(FakeRequest(cookies=cookies, query={"tab": "account"}))
        for title, name in (("喜好提取", "analysis_preference"), ("语义引战检测", "analysis_toxic")):
            assert title in page.text and f'name="target" value="{name}"' in page.text
        assert config.MESSAGE_ANALYSIS_TOXIC_API_KEY not in page.text
        response = await server._handle_panel_model_test(FakeRequest(
            cookies=cookies, form={"target": target, "back": "account"},
        ))
        query = URL(response.location).query
        assert query["tab"] == "account" and expected in query["msg"]
        assert query["err"] == ("" if result == "success" else "1")
        assert config.MESSAGE_ANALYSIS_TOXIC_API_KEY not in query["msg"]

        request, = sent
        payload = json.loads(request.content)
        if target == "analysis_preference":
            assert str(request.url) == config.MESSAGE_ANALYSIS_API_URL
            assert payload["model"] == config.MESSAGE_ANALYSIS_PREFERENCE_MODEL
            assert "Authorization" not in request.headers
        else:
            assert str(request.url) == config.MESSAGE_ANALYSIS_TOXIC_API_URL
            assert payload["model"] == config.MESSAGE_ANALYSIS_TOXIC_MODEL
            assert request.headers["Authorization"] == "Bearer " + config.MESSAGE_ANALYSIS_TOXIC_API_KEY
        assert payload["messages"] == [{"role": "user", "content": "ping"}]
    finally:
        repo.close()
