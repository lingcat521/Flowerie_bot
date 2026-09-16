"""启动横幅（ASCII 画）：text 日志格式的第一屏。

设计约束
--------
- **艺术字纯 ASCII**：Windows 控制台（cp936）与「重定向到文件」（cp437 等）都不会变方块或抛 UnicodeEncodeError
- **七彩渐变，自动降级**：ANSI 24-bit 真彩色只在「真终端」启用（isatty + NO_COLOR / FORCE_COLOR）；
  重定向/管道时输出纯文本 —— 日志文件里永不混入转义码
- **LOG_FORMAT=json 时跳过**：JSON lines 要求每行是合法 JSON，横幅会破坏解析
- **输出异常静默忽略**：管道关闭 / 编码不支持都不该让启动失败
- **绝不打印密钥**：摘要只显示「已配置 / 未配置」，URL 一律剥掉查询串（可能含 access_token）
"""
import colorsys
import os
import random
import re
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

# figlet「standard」字体的 FLOWERIE —— 程序生成后逐字母核对（纯 ASCII，66 列宽）
BANNER = r"""
   _____   _        ___   __      __  _____   ____    ___   _____
  |  ___| | |      / _ \  \ \    / / | ____| |  _ \  |_ _| | ____|
  | |_    | |     | | | |  \ \  / /  |  _|   | |_) |  | |  |  _|
  |  _|   | |___  | |_| |   \ \/ /   | |___  |  _ <   | |  | |___
  |_|     |_____|  \___/     \  /    |_____| |_| \_\ |___| |_____|
                              \/
"""

SEP = "  " + "-" * 58
MADE_BY = "  made by lingcat521"

_COLOR_TAGLINE = (255, 157, 198)   # 花璃粉（标题与署名）
_COLOR_QUIP = (255, 205, 150)       # 台词暖杏：压在七彩与粉色之间，不抢戏
_RESET = "\033[0m"

# 花璃的出场台词（随机一句）——风格与人格设定一致：短句、不用 emoji、不话唠
QUIPS = (
    "花璃，已就位。",
    "花璃在。今天想聊点什么？",
    "醒啦。群里有新鲜事吗？",
    "来了。今天也一起吧。",
    "花璃上线了。请多指教。",
)

# 彩虹参数：HSV 色环 0（红）-> 0.83（紫），不回卷到红；终端深色背景下 0.62 饱和度最耐看
_RAINBOW_END_HUE = 0.83
_RAINBOW_SATURATION = 0.62
_RAINBOW_VALUE = 1.0


def _supports_color(stream=None) -> bool:
    """是否可以在 stdout 上使用 ANSI 颜色（真终端 + 未被 NO_COLOR 抑制 + Windows VT 可用）。"""
    stream = stream if stream is not None else sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    try:
        if not stream.isatty():
            return False
    except Exception:  # noqa: BLE001 - 无 isatty 的流（重定向 / 自定义）视为不支持
        return False
    if os.name == "nt":
        try:  # Windows 10+：打开 VT 处理；失败则降级为纯文本
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:  # noqa: BLE001
            return False
    return True


def _rainbow(steps: int) -> List[Tuple[int, int, int]]:
    """生成 steps 级彩虹色（HSV 色环插值）。"""
    if steps <= 0:
        return []
    if steps == 1:
        return [(255, 90, 120)]
    out: List[Tuple[int, int, int]] = []
    for i in range(steps):
        r, g, b = colorsys.hsv_to_rgb(i / (steps - 1) * _RAINBOW_END_HUE,
                                      _RAINBOW_SATURATION, _RAINBOW_VALUE)
        out.append((int(round(r * 255)), int(round(g * 255)), int(round(b * 255))))
    return out


def _paint(text: str, rgb: Tuple[int, int, int], color: bool) -> str:
    if not color or not text:
        return text
    return "\033[38;2;%d;%d;%dm%s%s" % (rgb[0], rgb[1], rgb[2], text, _RESET)


def app_version() -> str:
    """从 pyproject.toml 读版本号；读不到返回空串（不抛异常）。"""
    try:
        text = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
        return match.group(1) if match else ""
    except Exception:  # noqa: BLE001 - 横幅不参与启动成败
        return ""


def _safe_endpoint(url: object, limit: int = 46) -> str:
    """URL 只保留 scheme://host:port/path —— 查询串可能含 access_token，必须剥掉。"""
    return str(url or "").split("?", 1)[0].strip()[:limit]


def summary_lines(config) -> List[Tuple[str, str]]:
    """从配置提取启动摘要（**绝不包含密钥**，只显示是否已配置）。"""
    if config is None:
        return []
    rows: List[Tuple[str, str]] = []
    protocol = str(getattr(config, "QQ_PROTOCOL", "onebot") or "onebot").lower()
    if protocol == "milky":
        endpoint = _safe_endpoint(getattr(config, "MILKY_EVENT_URL", ""))
        rows.append(("协议", "milky" + (("  %s" % endpoint) if endpoint else "")))
        rows.append(("Milky 鉴权", "已配置" if getattr(config, "MILKY_ACCESS_TOKEN", "") else "未配置"))
    else:
        mode = str(getattr(config, "NAPCAT_WS_MODE", "reverse") or "reverse")
        rows.append(("协议", "onebot（%s）" % mode))
    rows.append(("模型", str(getattr(config, "DEEPSEEK_MODEL", "") or "-")))
    rows.append(("人格", str(getattr(config, "PERSONA_DEFAULT", "flowerie") or "flowerie")))
    if getattr(config, "WEB_UI_ENABLED", False):
        rows.append(("管理后台", "http://127.0.0.1:%s/panel" % getattr(config, "WEB_UI_PORT", 8080)))
    else:
        rows.append(("管理后台", "未启用（WEB_UI_ENABLED=false）"))
    return rows


def _head_line(version: str = "") -> str:
    return "  Flowerie · 花璃" + (("   v" + version) if version else "")


def pick_quip(quip: Optional[str] = None) -> str:
    """挑一句出场台词（显式传入则用传入值——测试与固定展示用）。"""
    return quip if quip is not None else random.choice(QUIPS)


def banner_lines(version: str = "", summary: Optional[Sequence[Tuple[str, str]]] = None,
                 quip: Optional[str] = None) -> List[str]:
    """组装横幅的纯文本行（不含颜色），便于单测与预览。"""
    lines = BANNER.strip("\n").split("\n") + [""]
    lines.append(_head_line(version))
    lines.append(SEP)
    for label, value in (summary or []):
        lines.append("  %-8s %s" % (label, value))
    lines.append(SEP)
    lines.append("  「%s」" % pick_quip(quip))
    lines.append(MADE_BY)
    return lines


def banner_text(version: str = "", summary: Optional[Sequence[Tuple[str, str]]] = None,
                quip: Optional[str] = None) -> str:
    return "\n".join(banner_lines(version, summary, quip))


def colored_banner(version: str = "", summary: Optional[Sequence[Tuple[str, str]]] = None,
                   quip: Optional[str] = None) -> str:
    """带七彩渐变的横幅（调用方需自行确认终端支持颜色）。"""
    art = BANNER.strip("\n").split("\n")
    out = [_paint(line, rgb, True) for line, rgb in zip(art, _rainbow(len(art)))]
    out.append("")
    out.append(_paint(_head_line(version), _COLOR_TAGLINE, True))   # 标题：花璃粉
    out.append(SEP)
    for label, value in (summary or []):
        out.append("  %-8s %s" % (label, value))
    out.append(SEP)
    out.append(_paint("  「%s」" % pick_quip(quip), _COLOR_QUIP, True))  # 台词：暖杏
    out.append(_paint(MADE_BY, _COLOR_TAGLINE, True))                   # 署名：花璃粉
    return "\n".join(out)


def print_banner(log_format: str = "text", version: Optional[str] = None,
                 summary: Optional[Sequence[Tuple[str, str]]] = None,
                 quip: Optional[str] = None) -> bool:
    """打印启动横幅；返回是否真的输出了。

    log_format=json 时跳过（保持每行合法 JSON）；非终端自动去色；任何异常静默忽略。
    """
    if str(log_format or "text").strip().lower() == "json":
        return False
    try:
        ver = version if version is not None else app_version()
        text = (colored_banner(ver, summary, quip) if _supports_color()
                else banner_text(ver, summary, quip))
        print(text, flush=True)
        return True
    except Exception:  # noqa: BLE001 - 启动不让横幅影响
        return False

