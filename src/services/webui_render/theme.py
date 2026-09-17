"""webui_render 主题与背景：内置主题 / 面板 CSS / 背景合成。

零 JavaScript 保证：只输出 CSS 变量与样式规则。
"""
import hashlib
from typing import Optional

from src.services.webui_render.assets import asset_path, read_asset

THEMES = {
    "default": {
        "label": "默认",
        "desc": "明亮清爽的默认配色",
        "bg": "#F4F6FB",
        "vars": {
            "--panel-rgb": "255,255,255",
            "--panel-alpha": "0.9",
            "--panel-border": "#E3E7EF",
            "--text": "#3A4456",
            "--text-muted": "#7C8798",
            "--heading": "#1F2637",
            "--accent": "#5B8DEF",
            "--accent-hover": "#4A7AE0",
            "--accent-soft": "rgba(91, 141, 239, 0.12)",
            "--input-bg": "#FFFFFF",
            "--input-border": "#D9DEEA",
            "--ok": "#1A7F37",
            "--err": "#CF222E",
            "--shadow": "0 10px 30px rgba(50, 60, 90, .12)",
        },
    },
    "dark": {
        "label": "深色",
        "desc": "更深的近黑风格，护眼",
        "bg": "#121417",
        "vars": {
            "--panel-rgb": "24,27,31",
            "--panel-alpha": "0.9",
            "--panel-border": "#2a2f37",
            "--text": "#c9d1d9",
            "--text-muted": "#768390",
            "--heading": "#e1e6ec",
            "--accent": "#6cb6ff",
            "--accent-hover": "#539bf5",
            "--accent-soft": "rgba(108, 182, 255, 0.13)",
            "--input-bg": "#1c2026",
            "--input-border": "#333a45",
            "--ok": "#57ab5a",
            "--err": "#e5534b",
            "--shadow": "0 10px 30px rgba(0,0,0,.5)",
        },
    },
    "light": {
        "label": "浅色",
        "desc": "明亮清爽的日间风格",
        "bg": "#eef1f6",
        "vars": {
            "--panel-rgb": "255,255,255",
            "--panel-alpha": "0.9",
            "--panel-border": "#d9dee8",
            "--text": "#333a45",
            "--text-muted": "#7a8290",
            "--heading": "#1f2733",
            "--accent": "#3b82f6",
            "--accent-hover": "#2563eb",
            "--accent-soft": "rgba(59, 130, 246, 0.1)",
            "--input-bg": "#f7f9fc",
            "--input-border": "#ccd3de",
            "--ok": "#1a7f37",
            "--err": "#cf222e",
            "--shadow": "0 10px 30px rgba(30, 41, 59, .12)",
        },
    },
    "sakura": {
        "label": "Sakura",
        "desc": "樱花粉，明亮的浅粉少女系",
        "bg": "#FDEEF3",
        "vars": {
            "--panel-rgb": "255,255,255",
            "--panel-alpha": "0.82",
            "--panel-border": "#f4d8e2",
            "--text": "#7a4b5e",
            "--text-muted": "#b08a98",
            "--heading": "#5a2e42",
            "--accent": "#e75480",
            "--accent-hover": "#d64072",
            "--accent-soft": "rgba(231, 84, 128, 0.14)",
            "--input-bg": "#ffffff",
            "--input-border": "#f4d8e2",
            "--ok": "#1a7f37",
            "--err": "#cf222e",
            "--shadow": "0 10px 30px rgba(231, 84, 128, 0.2)",
        },
    },
    "ocean": {
        "label": "Ocean",
        "desc": "明亮天空蓝，清澈惬意",
        "bg": "#E7F3FC",
        "vars": {
            "--panel-rgb": "255,255,255",
            "--panel-alpha": "0.88",
            "--panel-border": "#C9E3F6",
            "--text": "#24475F",
            "--text-muted": "#6B8FA8",
            "--heading": "#15354D",
            "--accent": "#0B93E7",
            "--accent-hover": "#0284C7",
            "--accent-soft": "rgba(11, 147, 231, 0.12)",
            "--input-bg": "#FFFFFF",
            "--input-border": "#C6E1F4",
            "--ok": "#1A7F37",
            "--err": "#CF222E",
            "--shadow": "0 10px 30px rgba(40, 100, 150, .14)",
        },
    },
    "forest": {
        "label": "Forest",
        "desc": "明亮草绿，清新自然",
        "bg": "#EAF6EC",
        "vars": {
            "--panel-rgb": "255,255,255",
            "--panel-alpha": "0.9",
            "--panel-border": "#CFE9D6",
            "--text": "#2F5A39",
            "--text-muted": "#7A9C82",
            "--heading": "#1F3D27",
            "--accent": "#2FA85A",
            "--accent-hover": "#228B46",
            "--accent-soft": "rgba(47, 168, 90, 0.12)",
            "--input-bg": "#FFFFFF",
            "--input-border": "#CBE7D2",
            "--ok": "#1A7F37",
            "--err": "#CF222E",
            "--shadow": "0 10px 30px rgba(60, 120, 80, .14)",
        },
    },
    "amoled": {
        "label": "AMOLED",
        "desc": "纯黑，OLED 屏最省电",
        "bg": "#000000",
        "vars": {
            "--panel-rgb": "16,16,16",
            "--panel-alpha": "0.92",
            "--panel-border": "#262626",
            "--text": "#d4d4d4",
            "--text-muted": "#7a7a7a",
            "--heading": "#f0f0f0",
            "--accent": "#8b5cf6",
            "--accent-hover": "#7c3aed",
            "--accent-soft": "rgba(139, 92, 246, 0.16)",
            "--input-bg": "#111111",
            "--input-border": "#2e2e2e",
            "--ok": "#34d399",
            "--err": "#f87171",
            "--shadow": "0 10px 30px rgba(0,0,0,.8)",
        },
    },
}

DEFAULT_THEME = "default"

THEME_ORDER = ["default", "dark", "light", "sakura", "ocean", "forest", "amoled"]

def theme_body_class(name: str) -> str:
    return f"theme-{name}" if name in THEMES else f"theme-{DEFAULT_THEME}"

def theme_default_bg(name: str) -> str:
    t = THEMES.get(name)
    return t["bg"] if t else THEMES[DEFAULT_THEME]["bg"]

def theme_default_alpha(name: str) -> float:
    """主题默认的面板不透明度（0~1）。"""
    t = THEMES.get(name)
    if not t:
        return 0.9
    try:
        return float(t["vars"].get("--panel-alpha", "0.9"))
    except (TypeError, ValueError):
        return 0.9

def theme_css_block() -> str:
    """生成全部主题的 CSS variables（body.theme-xxx 作用域）。"""
    chunks = [f".theme-{name} {{ {_join_vars(t['vars'])} }}" for name, t in THEMES.items()]
    return "\n".join(chunks)

def _join_vars(vars_dict) -> str:
    return "; ".join(f"{k}: {v}" for k, v in vars_dict.items())

def hex_to_rgb(hex_color: str):
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return 30, 34, 41
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return 30, 34, 41

def background_rules(bg_color: str, image_url: str, opacity: int, size: str, position: str) -> str:
    """合成独立的背景层 CSS：背景颜色 + 图片透明度 → 同一视觉层。

    背景放在 `position:fixed; inset:0` 的 `.bg-layer` 上（而非 body），这样：
    - 图片始终按**视口**大小做 `cover` 缩放并裁剪（移动端 body 的
      background-attachment: fixed 支持差，会按整页高度把图拉伸，无法比例缩放裁剪）
    - 页面滚动时背景固定不动
    图片作为第二层背景，上面叠一层"背景颜色 + (100-透明度)% 不透明度"的渐变遮罩：
    - 透明度 100% → 遮罩全透明，图片完全显示
    - 透明度 0%   → 遮罩不透明，只剩背景颜色
    图片不透明度与背景颜色因此共同组成最终背景视觉。
    """
    rules = [
        "position: fixed;",
        "inset: 0;",
        "z-index: -1;",
        "pointer-events: none;",
        f"background-color: {bg_color};",
    ]
    if image_url:
        alpha = max(0.0, min(1.0, (100 - max(0, min(100, int(opacity)))) / 100.0))
        r, g, b = hex_to_rgb(bg_color)
        overlay = f"rgba({r},{g},{b},{alpha:.3f})"
        # 第一层线性渐变是"背景颜色遮罩"，叠在第二层图片之上，透明度合成同一视觉层
        rules.append(f"background-image: linear-gradient({overlay}, {overlay}), url('{image_url}');")
        rules.append(f"background-size: cover, {size};")
        rules.append(f"background-position: center, {position};")
        rules.append("background-repeat: no-repeat, no-repeat;")
    return ".bg-layer {\n  " + "\n  ".join(rules) + "\n}"

PANEL_CSS = read_asset("panel.css").replace("{{THEME_VARS}}", theme_css_block())

# 面板样式指纹：改了 CSS 就会变，用来核对「服务端跑的是哪一版样式」
PANEL_CSS_REV = hashlib.sha256(PANEL_CSS.encode("utf-8")).hexdigest()[:8]


def panel_asset_body(name: str) -> Optional[str]:
    """返回面板静态资源的响应体；None 表示不存在。

    注意：panel.css **不能**直接回文件内容 —— 文件里保留着 {{THEME_VARS}} 占位符，
    必须回注入主题变量后的 PANEL_CSS，否则 .theme-default{--input-bg:...} 整段失效，
    输入框会变成「透明无边框」（线上真实踩过这个坑）。
    """
    if name == "panel.css":
        return PANEL_CSS
    path = asset_path(name)
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")
