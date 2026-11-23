"""群消息分析管理 API 和插件授权的端到端测试。"""
import json
import shutil
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from src.config import Settings
from src.plugins.manager import PluginManager
from src.repositories.settings_repository import SettingsRepository
from src.services.config_service import ConfigService
from src.services.web_ui import WebUIServer

PATH = "/api/config/message-analysis"
URL = "MESSAGE_ANALYSIS_API_URL"
KEY = "MESSAGE_ANALYSIS_API_KEY"
MODEL = "MESSAGE_ANALYSIS_MODEL"
PREFERENCE_KEY = "MESSAGE_ANALYSIS_PREFERENCE_API_KEY"
TOXIC_MODEL = "MESSAGE_ANALYSIS_TOXIC_MODEL"
GROUPS = "MESSAGE_ANALYSIS_GROUP_IDS"
PERMISSION = "manage_message_analysis"


@pytest.fixture
def service(tmp_path):
    repo = SettingsRepository(str(tmp_path / "settings.db"))
    cfg = Settings(
        _env_file=None, BOT_QQ=10001, DEEPSEEK_API_KEY="fake-test-key",
        PLUGIN_DIR=str(tmp_path / "plugins"),
        MESSAGE_ANALYSIS_API_URL="https://example.test/chat/completions",
        MESSAGE_ANALYSIS_API_KEY="private-shared-secret",
        MESSAGE_ANALYSIS_PREFERENCE_API_KEY="private-preference-secret",
        MESSAGE_ANALYSIS_MODEL="shared-model",
    )
    yield ConfigService(cfg, repo, env_path=str(tmp_path / ".env"))
    repo.close()


@pytest.mark.asyncio
async def test_http_analysis_patch_validates_and_hot_reloads(service, tmp_path):
    web = WebUIServer(service.config, service, data_dir=str(tmp_path / "webui"))
    async with TestClient(TestServer(web.build_app())) as client:
        assert (await client.get(PATH)).status == 401
        assert (await client.patch(PATH, json={MODEL: "rejected"})).status == 401
        headers = {"Authorization": "Bearer " + web._issue_token()}
        response = await client.get(PATH, headers=headers)
        data = await response.json()
        assert data["values"][MODEL] == "shared-model"
        assert data["secrets_configured"][KEY] is True
        assert KEY not in data["values"]
        assert "private-shared-secret" not in await response.text()
        for patch in ([123], {MODEL: "rejected", GROUPS: [True]},
                      {MODEL: "rejected", "DEEPSEEK_API_KEY": "x"},
                      {MODEL: "rejected", "MESSAGE_ANALYSIS_TIMEOUT": 31}):
            assert (await client.patch(PATH, json=patch, headers=headers)).status == 400
        assert service.config.MESSAGE_ANALYSIS_MODEL == "shared-model"
        assert not (tmp_path / ".env").exists()

        switch = {URL: "https://new.example.test/chat/completions", KEY: None}
        assert (await client.patch(PATH, json=switch, headers=headers)).status == 400
        assert service.config.MESSAGE_ANALYSIS_API_KEY == "private-shared-secret"
        switch.update({PREFERENCE_KEY: None, TOXIC_MODEL: "moderator",
                       GROUPS: [10001], "TOXIC_GROUP_IDS": [10001]})
        response = await client.patch(PATH, json=switch, headers=headers)
        assert response.status == 200
        assert set((await response.json())["saved"]) == set(switch)
        assert service.config.MESSAGE_ANALYSIS_TOXIC_MODEL == "moderator"
        assert service.config.MESSAGE_ANALYSIS_GROUP_IDS == [10001]
        assert service.config.MESSAGE_ANALYSIS_API_KEY == ""
        restarted = Settings(_env_file=tmp_path / ".env", BOT_QQ=10001, DEEPSEEK_API_KEY="fake-test-key")
        ConfigService(restarted, service.repository, env_path=str(tmp_path / ".env")).apply_persisted()
        assert restarted.MESSAGE_ANALYSIS_GROUP_IDS == [10001]
        assert restarted.MESSAGE_ANALYSIS_PREFERENCE_API_KEY == ""
        assert restarted.MESSAGE_ANALYSIS_TOXIC_MODEL == "moderator"


@pytest.mark.asyncio
async def test_analysis_ops_over_real_python_sdk_transport(service):
    from src.plugins.manifest import PluginManifest

    plugin_dir = Path(service.config.PLUGIN_DIR) / "analysis_test"
    plugin_dir.mkdir(parents=True)
    shutil.copytree(Path(__file__).resolve().parents[1] / "plugin_sdk" / "flowerie_sdk",
                    plugin_dir / "flowerie_sdk", ignore=shutil.ignore_patterns("__pycache__"))
    (plugin_dir / "plugin.py").write_text(
        "from flowerie_sdk import FlowerieBot\n"
        "bot = FlowerieBot()\n"
        "api_ref = None\n"
        "def on_startup(context, api):\n"
        "    global api_ref\n"
        "    api_ref = api\n"
        "    bot.attach(api)\n"
        "def edit_analysis():\n"
        "    return [api_ref.message_analysis_get(),\n"
        "            bot.message_analysis_update({'MESSAGE_ANALYSIS_TOXIC_MODEL': 'moderator'})]\n",
        encoding="utf-8",
    )
    manifest_data = dict(id="analysis_test", name="Analysis SDK", version="1.0.0",
                         api_version="1", runtime="python", entry="plugin.py",
                         permissions=["read_message", PERMISSION])
    manifest = PluginManifest.from_dict(manifest_data)
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")
    service.repository.upsert_plugin({"id": manifest.id, "manifest_json": manifest.to_json(),
                                      "enabled": False, "approved_permissions": []})
    manager = PluginManager(service.config, service.repository, config_service=service)
    try:
        for permissions in (["read_message"], [PERMISSION]):
            ok, reason = await manager.enable(manifest.id, permissions)
            assert ok, reason
            reply = await manager._runtimes[manifest.id].request("hook", {"name": "edit_analysis"})
            assert reply["ok"], reply
            read, write = reply["result"]
            if PERMISSION not in permissions:
                assert read["denied"] and write["denied"]
                assert service.config.MESSAGE_ANALYSIS_TOXIC_MODEL == ""
            else:
                assert read["secrets_configured"][KEY] is True
                assert "private-shared-secret" not in json.dumps(read)
                assert write == {"ok": True, "saved": [TOXIC_MODEL]}
                assert service.config.MESSAGE_ANALYSIS_TOXIC_MODEL == "moderator"
    finally:
        await manager.shutdown()
