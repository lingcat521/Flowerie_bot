"""Plugin WebUI 文件空间：穿越/扩展名/魔数/大小/名称 安全校验（manager 工具层）。"""
import sys

import pytest

sys.path.insert(0, "tests/plugins/webui_example")

from src.plugins.manager import PluginManager


@pytest.fixture
def mk(tmp_path):
    """无 pydantic 的轻量 PluginManager（config stub）。"""
    class Cfg:
        PLUGIN_DIR = str(tmp_path)
    class Repo:
        def list_plugins(self):
            return []
    return PluginManager(config=Cfg(), repository=Repo())


def test_save_and_read_roundtrip(mk):
    name, size = mk.webui_save_upload("p1", "note.txt", b"hello")
    assert name == "note.txt" and size == 5
    blob, safe, ext = mk.webui_read_file("p1", "note.txt")
    assert blob == b"hello" and ext == ".txt"


@pytest.mark.parametrize("bad,desc", [
    ("../evil.txt", "路径穿越名"),
    ("..", "纯穿越"),
    ("a/b.txt", "含斜杠"),
    ("a b.txt", "含空格"),
    ("a\\b.txt", "反斜杠"),
    ("", "空名"),
])
def test_bad_name_rejected(mk, bad, desc):
    with pytest.raises(ValueError):
        mk.webui_save_upload("p1", bad, b"x")


def test_bad_extension_rejected(mk):
    with pytest.raises(ValueError):
        mk.webui_save_upload("p1", "evil.html", b"<script>")
    with pytest.raises(ValueError):
        mk.webui_save_upload("p1", "evil.js", b"alert(1)")
    with pytest.raises(ValueError):
        mk.webui_save_upload("p1", "evil.svg", b"<svg onload=alert(1)>")


def test_magic_number_check(mk):
    with pytest.raises(ValueError):
        mk.webui_save_upload("p1", "fake.png", b"not a png")
    name, _ = mk.webui_save_upload("p1", "ok.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    assert name == "ok.png"


def test_size_limit(mk):
    with pytest.raises(ValueError):
        mk.webui_save_upload("p1", "big.txt", b"x" * (10 * 1024 * 1024 + 1))


def test_read_traversal_rejected(mk):
    with pytest.raises(ValueError):
        mk.webui_read_file("p1", "../secret.txt")
    with pytest.raises(ValueError):
        mk.webui_read_file("p1", "..")
