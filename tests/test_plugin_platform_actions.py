"""Exercise the new action names through the existing plugin permission boundary."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.plugins.manager import PluginManager
from src.plugins.platform_actions import PlatformActions
from src.repositories.settings_repository import SettingsRepository
from src.services.profile_manager import MemberProfileService, ProfileStore
from src.services.qzone import QzoneService

pytestmark = pytest.mark.asyncio


@pytest.fixture
def platform(tmp_path):
    config = SimpleNamespace(PLUGIN_DIR=str(tmp_path / "plugins"), PROFILE_ENABLED=True,
                             AI_SEARCH_ENABLED=True, QZONE_ENABLED=True, AI_TOOL_PROMPT="private")
    repo = SettingsRepository(str(tmp_path / "settings.db"))
    manager = PluginManager(config, repo)
    approved = {"allowed": "read_member_profile,write_member_profile,web_search,read_qzone_history,"
                          "read_group_knowledge,read_group_info,scheduler",
                "reader": "read_member_profile"}
    for pid, permissions in approved.items():
        repo.upsert_plugin({"id": pid, "manifest_json": "{}", "approved_permissions": permissions.split(","), "enabled": True})
    profiles = MemberProfileService(config, None, ProfileStore(str(tmp_path / "profiles.db")))
    search = SimpleNamespace(enabled=lambda: config.AI_SEARCH_ENABLED,
                             search=AsyncMock(return_value={"ok": True, "sources": [{"title": "示例"}]}))
    qzone = QzoneService(None, config, str(tmp_path / "qzone.json"))
    manager.platform_actions = PlatformActions(
        config, profiles=profiles, search=search, qzone=qzone,
        knowledge=SimpleNamespace(list_for_group=lambda gid, search, limit: [{"group_id": gid, "term": search}]),
        personas=SimpleNamespace(resolve_persona=lambda _: {"id": "flowerie", "name": "花璃", "system_prompt": "private"},
                                 resolve_persona_id=lambda _: "flowerie"),
        nicknames=SimpleNamespace(get=lambda gid, pid: f"{pid}-{gid}"),
    )
    yield manager, search, config
    profiles.close()


async def test_profile_lifecycle_checks_permissions_and_group(platform):
    manager, _, _ = platform
    target = {"group_id": "10001", "user_id": 20001}
    read = await manager._handle_action("reader", "profile_get", target)
    assert read == {"ok": True, "profile": None}
    changed = {**target, "label": "interests", "text": "喜欢收集唱片"}
    assert (await manager._handle_action("reader", "profile_set_section", changed))["denied"]
    assert (await manager._handle_action("allowed", "profile_set_section", changed))["ok"]
    stored = await manager._handle_action("reader", "profile_get", target)
    assert stored["profile"]["sections"]["interests"]["text"] == changed["text"]
    other = await manager._handle_action("reader", "profile_get", {**target, "group_id": 10002})
    assert other["profile"] is None
    assert (await manager._handle_action("allowed", "profile_delete", target))["deleted"]


async def test_search_calls_configured_service_only_with_valid_approved_arguments(platform):
    manager, search, config = platform
    handler = manager._handle_action
    assert (await handler("reader", "web_search", {"query": "花璃"}))["denied"]
    assert (await handler("allowed", "web_search", {"query": "花璃", "limit": 11}))["code"] == "invalid_argument"
    search.search.assert_not_awaited()
    assert (await handler("allowed", "web_search", {"query": " 花璃 ", "limit": 3}))["ok"]
    search.search.assert_awaited_once_with("花璃", max_results=3)
    config.AI_SEARCH_ENABLED = False
    assert (await handler("allowed", "web_search", {"query": "花璃"}))["code"] == "unavailable"


async def test_platform_read_queries_and_automation(platform):
    manager, _, _ = platform

    async def call(action, **payload):
        return await manager._handle_action("allowed", action, payload)

    assert (await call("persona_resolve", group_id=10001))["persona"] == {
        "id": "flowerie", "name": "花璃", "description": None}
    assert (await call("nickname_resolve", group_id=10001))["nickname"] == "flowerie-10001"
    assert (await call("knowledge_list", group_id=10001, query="夜航"))["items"] == [
        {"group_id": 10001, "term": "夜航"}]
    assert (await call("qzone_history"))["items"] == []
    assert (await call("qzone_rights"))["default_ugc_right"] == 1
    assert (await manager._handle_action("reader", "qzone_history", {}))["denied"]
    flags = (await call("automation_status"))["features"]
    assert flags["AI_SEARCH_ENABLED"] and "AI_TOOL_PROMPT" not in flags
    try:
        result = await call("schedule_register", kind="delay", when=100, name="example")
        assert result["ok"]
        assert (await call("schedule_list"))["schedules"][0]["schedule_id"] == result["schedule_id"]
        assert (await call("schedule_cancel", schedule_id=result["schedule_id"]))["ok"]
        assert (await call("schedule_list"))["schedules"] == []
    finally:
        manager.cancel_all_schedules()


async def test_schedule_event_only_reaches_its_owner(platform):
    manager, _, _ = platform
    manager._started = True
    manager._manifest_of = lambda _: SimpleNamespace(runtime="python")
    for pid in ("allowed", "reader"):
        manager.repository.upsert_plugin({"id": pid, "manifest_json": "{}",
                                          "approved_permissions": ["scheduler"], "enabled": True})
        manager._runtimes[pid] = SimpleNamespace(healthy=True, dispatch_event=AsyncMock(return_value=[]))
    event = {"plugin_id": "allowed", "schedule_id": "allowed:daily"}
    await manager.dispatch_event("schedule", event)
    manager._runtimes["allowed"].dispatch_event.assert_awaited_once_with("schedule", event)
    manager._runtimes["reader"].dispatch_event.assert_not_awaited()


async def test_expanded_group_permissions_and_isolation(platform, tmp_path):
    from src.repositories.meme_knowledge_repository import MemeKnowledgeRepository
    from src.services.meme_knowledge_manager import MemeKnowledgeManager

    manager, _, _ = platform
    manager.repository.upsert_plugin({"id": "writer", "manifest_json": "{}", "enabled": True,
                                      "approved_permissions": ["write_group_knowledge", "read_group_knowledge",
                                                               "read_member_profile"]})
    store = MemeKnowledgeRepository(str(tmp_path / "knowledge.db"))
    manager.platform_actions.knowledge = MemeKnowledgeManager(store)
    target = {"group_id": 10001, "term": "夜航", "meaning": "花璃主题"}
    try:
        assert (await manager._handle_action("allowed", "knowledge_add", target))["denied"]
        assert (await manager._handle_action("writer", "knowledge_add", target))["ok"]
        listed = await manager._handle_action("writer", "knowledge_list", {"group_id": 10001})
        item = {"group_id": 10001, "knowledge_id": listed["items"][0]["id"]}
        assert not (await manager._handle_action("writer", "knowledge_delete", {**item, "group_id": 10002}))["ok"]
        assert (await manager._handle_action("writer", "knowledge_update", {**item, "meaning": "新释义"}))["ok"]
        assert (await manager._handle_action("writer", "knowledge_get", item))["item"]["meaning"] == "新释义"
        assert (await manager._handle_action("writer", "knowledge_delete", item))["ok"]
        assert (await manager._handle_action("writer", "profile_list", {"group_id": 10001}))["count"] == 0
    finally:
        store.close()


async def test_blossom_and_private_use_separate_services(platform):
    manager, _, _ = platform
    manager.repository.upsert_plugin({"id": "memory", "manifest_json": "{}", "enabled": True,
                                      "approved_permissions": ["read_memory", "write_private_memory"]})
    manager.blossom_memory = SimpleNamespace(ready=lambda: (True, ""), search=AsyncMock(return_value="花璃"))
    clear = AsyncMock(return_value=2)
    manager.platform_actions.memory = SimpleNamespace(clear_user_memory=clear)
    result = await manager._handle_action("memory", "memory_semantic", {"group_id": 123, "query": "花"})
    assert result == {"ok": True, "memory": "花璃"}
    assert (await manager._handle_action("memory", "private_memory_clear", {"user_id": 23}))["deleted"] == 2
    clear.assert_awaited_once_with(23, -23)


async def test_fetch_uses_bounded_host_transport(platform, monkeypatch):
    manager, _, _ = platform
    request = AsyncMock(return_value={"ok": True, "status": 200, "content_type": "text/plain", "body": "花璃夜航"})
    monkeypatch.setattr("src.plugins.platform_actions.plugin_http_request", request)
    assert (await manager._handle_action("reader", "web_fetch", {"url": "https://example.test/"}))["denied"]
    request.assert_not_awaited()
    payload = {"url": "https://example.test/", "max_chars": 2}
    result = await manager._handle_action("allowed", "web_fetch", payload)
    assert result["text"] == "花璃" and result["truncated"]


async def test_mcp_catalog_uses_separate_permission_and_configured_server(platform, monkeypatch):
    manager, _, config = platform
    config.MCP_ENABLED = True
    monkeypatch.setattr("src.plugins.manager.parse_mcp_servers", lambda *a, **kw: [
        {"name": "fixture", "url": "https://example.test/mcp", "enabled": True},
    ])
    manager.repository.upsert_plugin({"id": "catalog", "manifest_json": "{}", "enabled": True,
                                      "approved_permissions": ["mcp_read_resource"]})
    catalog = AsyncMock(return_value={"resources": [{"uri": "fixture://notes"}]})
    close = AsyncMock()
    monkeypatch.setattr("src.services.mcp_client.McpClient",
                        lambda *a, **kw: SimpleNamespace(read_catalog=catalog, close=close))
    result = await manager._handle_action("catalog", "mcp_resource", {"server": "fixture"})
    assert result["result"]["resources"] == [{"uri": "fixture://notes"}]
    catalog.assert_awaited_once_with("resources", "", cursor="", arguments={})
    close.assert_awaited_once()
    assert (await manager._handle_action("catalog", "mcp_prompt", {"server": "fixture"}))["denied"]


async def test_qzone_gateway_history_preserves_existing_action_result(platform):
    manager, _, _ = platform
    manager.repository.upsert_plugin({"id": "qzone", "manifest_json": "{}", "enabled": True,
                                      "approved_permissions": ["qzone", "read_qzone_history"]})
    original = {"ok": True, "data": {"tid": "fixture-post", "other_field": True}}
    manager.sender = SimpleNamespace(send_qzone_msg=AsyncMock(return_value=original),
                                     delete_qzone_msg=AsyncMock(return_value={"ok": True}))
    posted = await manager._handle_action("qzone", "qzone_publish", {
        "content": "花璃", "images": [], "ugc_right": 1,
    })
    assert posted == original
    listed = await manager._handle_action("qzone", "qzone_history", {})
    assert listed["items"][0]["tid"] == "fixture-post"
    await manager._handle_action("qzone", "qzone_delete", {"tid": "fixture-post"})
    assert (await manager._handle_action("qzone", "qzone_history", {}))["items"] == []


async def test_plugin_cannot_select_unusable_paid_search_engine(platform):
    manager, search, config = platform
    from src.services.web_search import WebSearchService

    config.DEEPSEEK_API_KEY = "fixture-only-0123456789abcdef"
    search.deepseek_native_usable = WebSearchService(config).deepseek_native_usable
    payload = {"query": "花璃", "engine": "deepseek-native"}
    config.SEARCH_PAID_ENABLED = False
    assert (await manager._handle_action("allowed", "web_search", payload))["ok"]
    search.search.assert_awaited_once_with("花璃", max_results=5)
    search.search.reset_mock()
    config.SEARCH_PAID_ENABLED = True
    assert (await manager._handle_action("allowed", "web_search", payload))["ok"]
    search.search.assert_awaited_once_with("花璃", max_results=5, engine="deepseek-native")
