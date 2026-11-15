"""Verify file parsing actions against real processes using each SDK."""

from pathlib import Path

import pytest

from src.services.file_parser import FileParser
from tests.sdk.harness import LANGUAGES, RigCtx, missing_reason


@pytest.mark.parametrize("lang", LANGUAGES)
async def test_file_parser_methods(tmp_path, lang):
    reason = missing_reason(lang)
    if reason:
        pytest.skip(reason)
    async with RigCtx(tmp_path) as rig:
        parser = FileParser(rig.mgr.config)
        if not parser.status()["plugin_local_supported"]:
            pytest.skip("Host does not support directory-relative no-follow file reads")
        permissions = ["read_message", "send_message", "parse_files", "filesystem_read"]
        plugin_id = await rig.load(lang, declared=permissions, approved=permissions)
        path = Path(rig.plugin_dir) / plugin_id / "data" / "document.txt"
        path.parent.mkdir(exist_ok=True)
        path.write_text("large file " * 5000, encoding="utf-8")
        rig.mgr.platform_actions.file_parser = parser
        result = await rig.send(f"/sdk@{plugin_id} fileparse")
        assert result["inline"]["text"] == "hello"
        assert result["local"]["bytes"] == 55000
        assert result["local"]["text"].startswith("large file ")
        assert result["local"]["truncated"]
        assert result["status"]["plugin_max_bytes"] == 32768
