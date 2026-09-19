"""webui_render 资产读取：真实文件形式的 CSS 与 HTML 模板。

为什么要这个模块：
- 面板的 CSS 与页面壳过去是 Python 字符串（改样式要改 Python，且无法被浏览器缓存）；
- 现在放成真实文件（static/panel.css、templates/*.html），改样式只动文件；
- 打包（PyInstaller --onefile）会把资源解到 sys._MEIPASS，所以路径必须兼容两种运行方式。
"""
import sys
from pathlib import Path

# 资源缺失时给一个最小兜底，保证面板至少可读（不白屏）
FALLBACK_CSS = (
    "*{box-sizing:border-box}"
    "body{margin:0;font-family:system-ui,-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;"
    "background:#f4f6fb;color:#3a4456;line-height:1.5}"
    ".wrap{max-width:1080px;margin:0 auto;padding:16px 20px 72px}"
    ".group{background:#fff;border:1px solid #e3e7ef;border-radius:14px;padding:16px 18px;margin-bottom:18px}"
    ".btn{background:#5b8def;color:#fff;border:none;border-radius:9px;padding:9px 22px;cursor:pointer}"
)


def _root() -> Path:
    """资源根目录：兼容 PyInstaller 打包后的 _MEIPASS 与源码运行。"""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "src" / "services" / "webui_render"
    return Path(__file__).resolve().parent


def asset_path(name: str) -> Path:
    base = (_root() / "static").resolve()
    candidate = (base / name).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError("Invalid asset path") from exc
    return candidate


def template_path(name: str) -> Path:
    return _root() / "templates" / name


def read_asset(name: str) -> str:
    """读取 static/<name>；缺失时返回兜底 CSS（并保持进程不崩）。"""
    try:
        return asset_path(name).read_text(encoding="utf-8")
    except OSError:
        return FALLBACK_CSS


def read_template(name: str) -> str:
    """读取 templates/<name>；缺失时抛出（模板缺失属于部署错误，要立刻暴露）。"""
    return template_path(name).read_text(encoding="utf-8")

def render_template(name: str, **ctx) -> str:
    """极简模板渲染：把 {{key}} 替换成上下文值（不引第三方模板引擎，保持零依赖）。"""
    text = read_template(name)
    for key, value in ctx.items():
        text = text.replace("{{" + key + "}}", "" if value is None else str(value))
    return text
