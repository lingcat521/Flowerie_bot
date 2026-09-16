"""启动横幅测试：json 日志格式跳过、内容完整、任何情况下不抛异常。"""
from src.utils.banner import BANNER, CAPS, SUBTITLE, TAGLINE, banner_text, print_banner


def test_banner_contains_art_and_tagline():
    text = banner_text("2.2.2222")
    assert "______" in text                       # ASCII 艺术字
    assert TAGLINE in text
    assert "v2.2.2222" in text
    assert SUBTITLE in text and CAPS in text


def test_banner_without_version():
    text = banner_text()
    assert TAGLINE in text
    assert " v" not in text.split(TAGLINE)[1][:6]  # 没有版本号时不出现 vX


def test_banner_is_pure_ascii_art():
    """艺术字部分必须是纯 ASCII（编码兼容）。"""
    BANNER.strip("\n").encode("ascii")


def test_print_banner_skips_json(capsys):
    assert print_banner(log_format="json") is False
    assert capsys.readouterr().out == ""


def test_print_banner_outputs_for_text(capsys):
    assert print_banner(log_format="text", version="9.9.9") is True
    out = capsys.readouterr().out
    assert "Flowerie" in out and "9.9.9" in out


def test_print_banner_never_raises(monkeypatch):
    import builtins
    def boom(*_a, **_k):
        raise OSError("broken pipe")
    monkeypatch.setattr(builtins, "print", boom)
    assert print_banner(log_format="text", version="1.0.0") is False


def test_app_version_reads_pyproject():
    from src.utils.banner import app_version
    v = app_version()
    assert v == "" or v[0].isdigit()      # 读不到就是空串，读到必须是版本号样式

