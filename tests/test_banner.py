"""启动横幅测试：七彩渐变、json 跳过、密钥不外泄、任何情况下不抛异常。"""
import builtins

from src.utils.banner import (
    BANNER,
    MADE_BY,
    app_version,
    banner_lines,
    banner_text,
    colored_banner,
    print_banner,
    summary_lines,
)


class _FakeConfig:
    """假配置：故意塞满密钥，验证横幅绝不出卖它们。"""
    QQ_PROTOCOL = "milky"
    MILKY_EVENT_URL = "ws://1.2.3.4:8080/event?access_token=SUPERSECRET"
    MILKY_ACCESS_TOKEN = "SUPERSECRET"
    DEEPSEEK_API_KEY = "sk-should-never-appear"
    NAPCAT_ACCESS_TOKEN = "napcat-secret"
    DEEPSEEK_MODEL = "deepseek-flash"
    PERSONA_DEFAULT = "flowerie"
    WEB_UI_ENABLED = True
    WEB_UI_PORT = 8080


# ---------- 内容 ----------
def test_art_is_pure_ascii():
    """艺术字必须纯 ASCII（编码兼容红线）。"""
    BANNER.strip("\n").encode("ascii")


def test_banner_contains_art_head_summary_and_signature():
    text = banner_text("2.2.2222", [("协议", "milky"), ("模型", "deepseek-flash")])
    assert "______" in text                      # 艺术字
    assert "Flowerie · 花璃" in text
    assert "v2.2.2222" in text
    assert "协议" in text and "deepseek-flash" in text
    assert MADE_BY in text
    assert "made by lingcat521" in text


def test_banner_without_version_or_summary():
    lines = banner_lines()
    assert lines[7].strip() == "Flowerie · 花璃"   # 无版本号时不带 vX
    assert MADE_BY in "\n".join(lines)


# ---------- 颜色 ----------
def test_colored_banner_uses_24bit_ansi_for_art():
    out = colored_banner("1.0.0", [("协议", "x")])
    assert "\033[38;2;" in out                  # 24-bit 真彩色
    assert out.count("\033[0m") >= 6            # 每行都重置，避免污染后续日志


def test_rainbow_spans_warm_to_cool():
    from src.utils.banner import _rainbow
    colors = _rainbow(6)
    assert len(colors) == 6
    assert colors[0][0] > colors[0][2]          # 首色偏红
    assert colors[-1][2] > colors[-1][0]        # 末色偏蓝
    assert all(0 <= c <= 255 for rgb in colors for c in rgb)


# ---------- 输出策略 ----------
def test_print_banner_skips_json(capsys):
    assert print_banner(log_format="json") is False
    assert capsys.readouterr().out == ""


def test_print_banner_plain_when_not_tty(capsys, monkeypatch):
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
    assert print_banner("text", version="1.2.3", summary=[("协议", "onebot")]) is True
    out = capsys.readouterr().out
    assert "\033[" not in out                   # 无转义码
    assert "1.2.3" in out


def test_print_banner_colored_when_forced(capsys, monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert print_banner("text", version="1.2.3") is True
    assert "\033[38;2;" in capsys.readouterr().out


def test_print_banner_never_raises(monkeypatch):
    def boom(*_a, **_k):
        raise OSError("broken pipe")
    monkeypatch.setattr(builtins, "print", boom)
    assert print_banner("text", version="1.0.0") is False


# ---------- 摘要安全 ----------
def test_summary_never_leaks_secrets():
    text = banner_text("9.9.9", summary_lines(_FakeConfig()))
    for secret in ("SUPERSECRET", "sk-should-never-appear", "napcat-secret", "access_token"):
        assert secret not in text, secret


def test_summary_shows_configured_state_without_value():
    rows = dict(summary_lines(_FakeConfig()))
    assert rows["Milky 鉴权"] == "已配置"          # 只说已配置，不打印 token
    assert rows["模型"] == "deepseek-flash"
    assert rows["管理后台"].endswith("/panel")


def test_summary_handles_none_config():
    assert summary_lines(None) == []


def test_app_version_reads_pyproject():
    version = app_version()
    assert version == "" or version[0].isdigit()



# ---------- 台词与配色 ----------
def test_banner_contains_quip():
    text = banner_text("1.0", quip="花璃，已就位。")
    assert "「花璃，已就位。」" in text


def test_pick_quip_defaults_to_pool_and_is_random():
    from src.utils.banner import QUIPS, pick_quip
    assert pick_quip("显式") == "显式"
    picked = {pick_quip() for _ in range(40)}
    assert picked and picked <= set(QUIPS)     # 只出自候选池
    assert len(picked) > 1                     # 40 次内至少出现两种，证明是随机的


def test_signature_is_pink_and_quip_is_warm():
    from src.utils.banner import _COLOR_QUIP, _COLOR_TAGLINE, colored_banner
    out = colored_banner("1.0", [("协议", "x")], quip="q")
    assert ("38;2;%d;%d;%d" % _COLOR_TAGLINE) in out   # 标题 / 署名：花璃粉
    assert ("38;2;%d;%d;%d" % _COLOR_QUIP) in out      # 台词：暖杏
    assert _COLOR_TAGLINE == (255, 157, 198)
    assert _COLOR_QUIP == (255, 205, 150)


def test_print_banner_accepts_quip(capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert print_banner("text", version="1.0", quip="固定台词") is True
    assert "「固定台词」" in capsys.readouterr().out

