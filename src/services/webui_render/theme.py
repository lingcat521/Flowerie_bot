"""webui_render 主题与背景：内置主题 / 面板 CSS / 背景合成。

零 JavaScript 保证：只输出 CSS 变量与样式规则。
"""
import hashlib
from typing import Optional

from src.services.webui_render.assets import asset_path, read_asset

# Keep the existing variable names used by the renderers and plugin pages.
_LIGHT = {
    "--ui-bg": "#F4F5FA", "--ui-surface": "#FFFFFF", "--ui-raised": "#EDEFF7",
    "--input-bg": "#FFFFFF", "--panel-border": "#D5D9E5", "--input-border": "#7A849B",
    "--heading": "#202536", "--text": "#30384B", "--secondary": "#536079", "--text-muted": "#606D85",
    "--accent": "#6546BC", "--accent-hover": "#5335A4", "--accent-soft": "#EEE8FC", "--on-accent": "#FFFFFF",
    "--ok": "#176B49", "--ok-bg": "#E7F5ED", "--warn": "#815600", "--warn-bg": "#FFF4DC",
    "--err": "#AE2940", "--err-bg": "#FCE9ED", "color-scheme": "light",
}
_DARK = {
    "--ui-bg": "#0C0E14", "--ui-surface": "#151923", "--ui-raised": "#1D2330",
    "--input-bg": "#10141D", "--panel-border": "#303849", "--input-border": "#65718A",
    "--heading": "#F4F5FB", "--text": "#E4E7F0", "--secondary": "#B0B9CD", "--text-muted": "#929DB5",
    "--accent": "#B6A0FF", "--accent-hover": "#C9B8FF", "--accent-soft": "#272138", "--on-accent": "#151020",
    "--ok": "#6ED5AC", "--ok-bg": "#142D27", "--warn": "#EAC178", "--warn-bg": "#30291C",
    "--err": "#FF96A2", "--err-bg": "#321E29", "color-scheme": "dark",
}


def _theme(label, description, palette, overrides=None):
    values = {**palette, **(overrides or {})}
    surface = values["--ui-surface"].lstrip("#")
    rgb = ",".join(str(int(surface[i:i + 2], 16)) for i in (0, 2, 4))
    return {
        "label": label, "desc": description, "bg": values["--ui-bg"],
        "vars": {
            **values, "--panel-rgb": rgb, "--panel-alpha": "1",
            "--panel-bg": "rgba(var(--panel-rgb),var(--panel-alpha))",
            "--shadow": "none",
        },
    }


THEMES = {
    "default": _theme("默认", "清爽的蓝灰配色", _LIGHT, {
        "--ui-bg": "#F4F6FB", "--accent": "#315DAE", "--accent-hover": "#25498E", "--accent-soft": "#E6EDFA",
    }),
    "dark": _theme("深色", "夜航控制台 · 鸢尾紫", _DARK),
    "light": _theme("浅色", "冷灰底色与鸢尾紫", _LIGHT),
    "sakura": _theme("Sakura", "浅粉底色与玫瑰色", _LIGHT, {
        "--ui-bg": "#FDEEF3", "--ui-raised": "#F9E7EF", "--panel-border": "#EBD0DD", "--text-muted": "#58657D",
        "--accent": "#A12E62", "--accent-hover": "#832350", "--accent-soft": "#F8E0EA",
    }),
    "ocean": _theme("Ocean", "海蓝底色与深蓝色", _LIGHT, {
        "--ui-bg": "#E7F3FC", "--ui-raised": "#E3F0F9", "--panel-border": "#C9E3F6", "--text-muted": "#58657D",
        "--accent": "#08608B", "--accent-hover": "#0A4E72", "--accent-soft": "#D8EDF8",
    }),
    "forest": _theme("Forest", "浅绿底色与常青色", _LIGHT, {
        "--ui-bg": "#EAF6EC", "--ui-raised": "#E5F1E7", "--panel-border": "#CFE9D6", "--text-muted": "#58657D",
        "--accent": "#256638", "--accent-hover": "#1B512B", "--accent-soft": "#DCF0E0",
    }),
    "amoled": _theme("AMOLED", "纯黑背景与浅紫色", _DARK, {
        "--ui-bg": "#000000", "--ui-surface": "#101010", "--ui-raised": "#1C1C1C",
        "--input-bg": "#090909", "--panel-border": "#303030", "--accent": "#C4A9FF",
        "--accent-hover": "#D5C2FF", "--accent-soft": "#261D36",
    }),
}

DEFAULT_THEME = "default"
THEME_ORDER = list(THEMES)


def theme_body_class(name: str) -> str:
    return f"theme-{name}" if name in THEMES else f"theme-{DEFAULT_THEME}"

def theme_default_bg(name: str) -> str:
    t = THEMES.get(name)
    return t["bg"] if t else THEMES[DEFAULT_THEME]["bg"]

def theme_default_alpha(name: str) -> float:
    """主题默认的面板不透明度（0~1）。"""
    t = THEMES.get(name)
    if not t:
        return 1.0
    try:
        return float(t["vars"].get("--panel-alpha", "1"))
    except (TypeError, ValueError):
        return 1.0

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

# 资源路由代际：只要改了「资源是怎么生成的」（不只是 CSS 内容），就 +1。
# 目的：让引用 URL 变化 —— 浏览器即使缓存过旧样式也必然重新下载，
# 用户不需要强刷或清缓存（手机上往往做不到强刷）。
PANEL_ASSET_GEN = "3"
PANEL_ASSET_VER = PANEL_CSS_REV + "-" + PANEL_ASSET_GEN


def panel_asset_body(name: str) -> Optional[str]:
    """返回面板静态资源的响应体；None 表示不存在。

    注意：panel.css **不能**直接回文件内容 —— 文件里保留着 {{THEME_VARS}} 占位符，
    必须回注入主题变量后的 PANEL_CSS，否则 .theme-default{--input-bg:...} 整段失效，
    输入框会变成「透明无边框」（线上真实踩过这个坑）。
    """
    # 纵深防御：不依赖调用方校验 —— 只接受"纯文件名"，任何分隔符/上跳/空名一律拒绝
    if not name or "/" in name or chr(92) in name or ".." in name or not name.endswith(".css"):
        return None
    if name == "panel.css":
        return PANEL_CSS
    path = asset_path(name)
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")
