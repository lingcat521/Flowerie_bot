"""启动横幅（ASCII 画）：仅 text 日志格式输出，任何异常都不影响启动。

设计约束
--------
- **纯 ASCII 艺术字**：不用 emoji / 框线等宽字符 —— Windows 控制台与「重定向到文件」
  的编码（cp936 / cp437 / UTF-8）各不相同，宽字符容易变方块或直接抛 UnicodeEncodeError
- **LOG_FORMAT=json 时跳过**：JSON lines 日志要求每行都是合法 JSON，横幅会破坏解析
- **输出失败静默忽略**：管道关闭 / 编码不支持都不该让启动失败
- 版本号从 pyproject.toml 读取（打包产物读不到就省略，不影响横幅）
"""
import re
from pathlib import Path
from typing import Optional

# figlet「standard」字体的 FLOWERIE
BANNER = r"""
   ______ _                 _
  |  ____| |               (_)
  | |__  | | _____      __  _  ___
  |  __| | |/ _ \ \ /\ / / | |/ _ \
  | |    | | (_) \ V  V /  | |  __/
  |_|    |_|\___/ \_/\_/   |_|\___|
"""

TAGLINE = "  Flowerie · 花璃"
SUBTITLE = "  DeepSeek 驱动 · QQ 群聊机器人 · 零 JS 管理后台"
CAPS = "  OneBot v11 / Milky 双协议 · 插件系统 v1（Python / Node / 任意语言 exec）"


def app_version() -> str:
    """从 pyproject.toml 读版本号；读不到返回空串（不抛异常）。"""
    try:
        text = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
        return match.group(1) if match else ""
    except Exception:  # noqa: BLE001 - 横幅不参与启动成败
        return ""


def banner_text(version: str = "") -> str:
    """组装横幅文本（纯字符串，便于单测与预览）。"""
    head = TAGLINE + (("   v" + version) if version else "")
    return "\n".join([BANNER.strip("\n"), "", head, SUBTITLE, CAPS])


def print_banner(log_format: str = "text", version: Optional[str] = None) -> bool:
    """打印启动横幅；返回是否真的输出了。

    log_format=json 时跳过（保持每行合法 JSON）；任何输出异常静默忽略。
    """
    if str(log_format or "text").strip().lower() == "json":
        return False
    text = banner_text(version if version is not None else app_version())
    try:
        print(text, flush=True)
        return True
    except Exception:  # noqa: BLE001 - 启动不让横幅影响
        return False

