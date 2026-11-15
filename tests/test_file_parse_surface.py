"""File parser configuration, permission boundary, and authenticated upload routes."""

import base64
from io import BytesIO

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer
from multidict import MultiDict

from src.adapters.resource import ResourceRef, build_resource_fetcher
from src.config import Settings
from src.plugins.manager import PluginManager
from src.plugins.platform_actions import PlatformActions
from src.repositories.settings_repository import SettingsRepository
from src.services.config_service import ConfigService
from src.services.file_parser import FileParser
from src.services.web_ui import WebUIServer


@pytest.fixture
def file_services(tmp_path):
    config = Settings(_env_file=None, DEEPSEEK_API_KEY="test", BOT_QQ=10000,
                      MAX_FILE_DOWNLOAD_BYTES=1024, MAX_FILE_TEXT_CHARS=100,
                      PLUGIN_DIR=str(tmp_path / "plugins"))
    repository = SettingsRepository(str(tmp_path / "settings.db"))
    service = ConfigService(config, repository, env_path=str(tmp_path / ".env"))
    return config, repository, service, FileParser(config)


async def test_http_and_panel_use_saved_config(file_services):
    config, _, service, parser = file_services
    server = WebUIServer(config, service, file_parser=parser)
    async with TestClient(TestServer(server.build_app())) as client:
        assert (await client.get("/api/files/status")).status == 401
        assert (await client.post("/api/files/parse", data=b"secret")).status == 401
        auth = {"Authorization": f"Bearer {server._issue_token()}"}
        status = await client.get("/api/files/status", headers=auth)
        assert (await status.json())["plugin_max_bytes"] == 1024

        page = await client.get("/panel?tab=files", headers=auth)
        html = await page.text()
        for label in ("对话与记忆", "QQ 与社群", "工具与扩展", "面板与诊断"):
            assert label in html
        assert 'name="FILE_PARSE_ENABLED"' in html
        assert 'name="MAX_FORWARD_DEPTH"' not in html
        assert 'name="MAX_IMAGES_PER_MESSAGE"' not in html
        assert 'aria-current="page"' in html

        raw = await client.post("/api/files/parse", headers=auth,
                                params={"filename": "notes.txt"}, data=b"x" * 150)
        assert raw.status == 200
        assert (await raw.json())["truncated"] is True

        preview = aiohttp.FormData()
        preview.add_field("file", b"<script>example</script>", filename="sample.txt")
        response = await client.post("/panel/files/preview", headers=auth, data=preview)
        assert response.status == 200
        assert "&lt;script&gt;example&lt;/script&gt;" in await response.text()

        too_large = await client.post("/api/files/parse", headers=auth,
                                      params={"filename": "notes.txt"}, data=b"x" * 1025)
        assert too_large.status == 413

        settings_form = MultiDict([("FILE_PARSE_FORMATS", ""), ("FILE_PARSE_FORMATS", "csv"),
                                   ("FILE_PARSE_FORMATS", "pdf")])
        saved = await client.post("/panel/save?cat=FileParse", data=settings_form,
                                  headers=auth, allow_redirects=False)
        assert saved.status == 302 and config.FILE_PARSE_FORMATS == "csv,pdf"
        assert service.update("FILE_PARSE_FORMATS", "CSV, csv")[0]
        assert config.FILE_PARSE_FORMATS == "csv"
        assert not service.update("FILE_PARSE_FORMATS", "exe")[0]
        assert await parser.parse_document("notes.txt", b"x") == {
            "ok": False, "code": "unsupported_format", "error": "该文件格式未启用或不支持",
        }
        saved = await client.post("/panel/save?cat=FileParse", data={"FILE_PARSE_ENABLED": "false"},
                                  headers=auth, allow_redirects=False)
        assert saved.status == 302 and config.FILE_PARSE_ENABLED is False
        disabled = await client.post("/api/files/parse", headers=auth,
                                     params={"filename": "notes.csv"}, data=b"1,2")
        assert disabled.status == 503


async def test_plugin_actions_require_approval_and_cannot_read_paths(file_services):
    config, repository, _, parser = file_services
    manager = PluginManager(config, repository)
    manager.platform_actions = PlatformActions(config, file_parser=parser)
    for pid, approved in [("allowed", ["parse_files"]), ("denied", [])]:
        repository.upsert_plugin({"id": pid, "manifest_json": "{}", "approved_permissions": approved, "enabled": True})

    payload = {"filename": "notes.txt", "content_base64": base64.b64encode("花璃".encode()).decode()}
    assert (await manager._handle_action("denied", "file_parse", payload))["denied"]
    assert (await manager._handle_action("denied", "file_parse_status", {}))["denied"]
    assert (await manager._handle_action("allowed", "file_parse", payload))["text"] == "花璃"
    assert (await manager._handle_action("allowed", "file_parse", {
        **payload, "filename": "../notes.txt",
    }))["code"] == "invalid_argument"
    assert (await manager._handle_action("allowed", "file_parse", {
        **payload, "content_base64": "AA@@",
    }))["code"] == "invalid_argument"
    config.FILE_PARSE_GROUP_UPLOAD_ENABLED = False
    status = await manager._handle_action("allowed", "file_parse_status", {})
    assert status["enabled"] and not status["group_upload_enabled"]


async def test_fetch_limit_is_hot_reloaded(tmp_path):
    path = tmp_path / "file.txt"
    path.write_bytes(b"12345")
    caps = [4]
    fetcher = build_resource_fetcher(max_bytes=lambda: caps[0])
    reference = ResourceRef.from_local_path(str(path))
    assert await fetcher.fetch(reference) == (b"", False)
    caps[0] = 5
    assert await fetcher.fetch(reference) == (b"12345", True)


async def test_real_document_formats_and_row_limits(file_services):
    from docx import Document
    from openpyxl import Workbook
    from pypdf import PdfWriter

    config, _, _, parser = file_services
    config.MAX_FILE_DOWNLOAD_BYTES = 2 * 1024 * 1024
    config.MAX_CSV_ROWS = 1
    config.MAX_EXCEL_CELLS = 1
    assert (await parser.parse_document("table.csv", b"a,b\nc,d"))["text"] == "a,b"

    word = Document()
    word.add_paragraph("Word 正文")
    docx = BytesIO()
    word.save(docx)
    assert (await parser.parse_document("doc.docx", docx.getvalue()))["text"] == "Word 正文"

    workbook = Workbook()
    workbook.active.append(["第一格", "第二格"])
    xlsx = BytesIO()
    workbook.save(xlsx)
    workbook.close()
    text = (await parser.parse_document("book.xlsx", xlsx.getvalue()))["text"]
    assert "第一格" in text and "第二格" not in text

    pdf = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(pdf)
    result = await parser.parse_document("empty.pdf", pdf.getvalue())
    assert result["ok"] and result["format"] == "pdf" and result["text"] == ""


async def test_local_document_requires_both_permissions_and_rejects_links(file_services, tmp_path):
    config, repository, _, parser = file_services
    if not parser.status()["plugin_local_supported"]:
        pytest.skip("Host does not support directory-relative no-follow file reads")
    manager = PluginManager(config, repository)
    manager.platform_actions = PlatformActions(config, file_parser=parser)
    for pid, approved in [("allowed", ["parse_files", "filesystem_read"]), ("denied", ["parse_files"])]:
        repository.upsert_plugin({"id": pid, "manifest_json": "{}", "approved_permissions": approved, "enabled": True})
    data = tmp_path / "plugins" / "allowed" / "data"
    data.mkdir(parents=True)
    file = data / "notes.txt"
    file.write_text("plugin text")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    (data / "link.txt").symlink_to(outside)
    denied = await manager._handle_action("denied", "file_parse_local", {"path": "notes.txt"})
    assert denied["denied"] and "filesystem_read" in denied["error"]
    result = await manager._handle_action("allowed", "file_parse_local", {"path": "notes.txt"})
    assert result["text"] == "plugin text"
    for path in ("link.txt", "../notes.txt"):
        result = await manager._handle_action("allowed", "file_parse_local", {"path": path})
        assert result["code"] == "invalid_argument"
