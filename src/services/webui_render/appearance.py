"""webui_render 外观页：主题 / 背景颜色 / 背景图片 / 透明度。"""

from src.services.webui_render.background import render_crop_controls
from src.services.webui_render.theme import THEME_ORDER, THEMES
from src.services.webui_render.util import _esc


def render_appearance(theme: str, bg_color: str, opacity: int,
                      has_bg_image: bool, image_url: str = "", panel_opacity: int = 90,
                      panel_style: str = "clear", *, crops=None, image_ratio=None, draft=False, color_input="") -> str:
    cards = []
    for name in THEME_ORDER:
        t = THEMES.get(name)
        if t is None:
            continue
        checked = ' checked' if name == theme else ""
        palette = t["vars"]
        sample = ";".join(
            f"--sample-{role}:{palette[token]}"
            for role, token in (
                ("bg", "--ui-bg"), ("surface", "--ui-surface"), ("line", "--panel-border"),
                ("accent", "--accent"), ("muted", "--text-muted"),
            )
        )
        current = '<span class="badge">当前生效</span>' if checked else ""
        cards.append(
            f'<label class="theme-card"><span class="theme-preview" aria-hidden="true" style="{sample}">'
            '<span class="sample-nav"></span><span class="sample-main"><span></span></span></span>'
            f'<span class="theme-name">{_esc(t["label"])}</span>'
            f'<input type="radio" name="theme" value="{name}"{checked}>'
            f'<span class="theme-meta">{_esc(t["desc"])}</span>{current}</label>'
        )
    preview = ""
    if has_bg_image and image_url:
        preview = f'<img class="bg-preview" src="{_esc(image_url)}" alt="当前背景图">'
    opacity = max(0, min(100, int(opacity)))
    crop_controls = render_crop_controls(crops, image_ratio, image_url, bg_color, opacity, draft=draft) if crops else ""
    return (
        '<form method="post" action="/panel/appearance" enctype="multipart/form-data">'
        '<fieldset class="group"><legend>主题</legend>'
        f'<div class="theme-grid">{"".join(cards)}</div>'
        '<p class="hint">主题与背景在保存外观设置后生效。</p>'
        '<div class="row"><label class="row-info" for="panel-opacity"><span class="row-title">面板不透明度</span>'
        '<span class="row-key">panel_opacity</span></label>'
        '<div class="row-control">'
        f'<div class="range-row"><input type="range" name="panel_opacity" id="panel-opacity" aria-describedby="panel-opacity-hint" min="0" max="100" value="{max(0,min(100,int(panel_opacity)))}">'
        f'<output>已保存：{max(0,min(100,int(panel_opacity)))}%</output></div>'
        '<span class="hint" id="panel-opacity-hint">适用于日志、配置和结果卡片。100% 为实底，调低数值会透出更多背景。</span>'
        '</div></div>'
        '<div class="row"><span class="row-info" id="panel-style-label"><span class="row-title">卡片效果</span>'
        '<span class="row-key">panel_style</span></span>'
        '<div class="row-control" role="group" aria-labelledby="panel-style-label" style="flex-direction:row;gap:18px;flex-wrap:wrap">'
        f'<label class="opt"><input type="radio" name="panel_style" value="clear"{" checked" if panel_style=="clear" else ""}> 纯透明（淡入淡出）</label>'
        f'<label class="opt"><input type="radio" name="panel_style" value="glass"{" checked" if panel_style=="glass" else ""}> 液态玻璃（磨砂）</label>'
        '</div></div>'
        '</fieldset>'

        '<fieldset class="group"><legend>背景颜色（跟主题绑定）</legend>'
        '<div class="row"><div class="row-control" style="flex-direction:row;align-items:center;gap:14px;flex-wrap:wrap">'
        f'<span class="color-swatch" style="background:{_esc(bg_color)}" title="当前主题背景色"></span>'
        f'<label for="bg-color-input">自定义颜色</label><input type="text" id="bg-color-input" aria-describedby="bg-color-help" name="bg_color_input" value="{_esc(color_input)}" '
        'placeholder="#RRGGBB 或 253,238,243，留空=用主题默认" class="color-text" '
        'title="留空=用当前主题默认背景；想自定义填入 #RRGGBB 或 R,G,B / rgb(r,g,b)">'
        '<span class="hint" id="bg-color-help">背景颜色已随所选主题自动带好（切换主题即整套换肤，选黑色主题自动变黑）；'
        '留空用主题默认；<code>#RRGGBB</code> / <code>253,238,243</code> 输入只改当前主题</span>'
        '</div></div></fieldset>'

        '<fieldset class="group"><legend>背景图片</legend>'
        '<div class="row"><div class="row-control">'
        '<label for="bg-image">上传背景图</label><input type="file" id="bg-image" aria-describedby="bg-image-help" name="bg_image" accept="image/png,image/jpeg,image/webp,image/gif">'
        '<span class="hint" id="bg-image-help">仅允许 PNG / JPEG / WEBP / GIF，最大 5MB；'
        '文件将保存到服务器持久化目录（data/webui/background/），刷新与重启均不会丢失</span>'
        + preview +
        '</div></div>'
        '<div class="row"><label class="row-info" for="bg-image-opacity"><span class="row-title">背景图不透明度</span>'
        '<span class="row-key">bg_image_opacity</span></label>'
        '<div class="row-control">'
        f'<div class="range-row"><input type="range" name="bg_image_opacity" id="bg-image-opacity" min="0" max="100" value="{opacity}">'
        f'<output>已保存：{opacity}%</output></div></div></div>'
        + crop_controls +
        '</fieldset>'
        '<div class="actions-row">'
        + ('<button type="submit" class="btn secondary" name="appearance_action" value="preview">预览裁剪</button>'
           if image_ratio else "") +
        '<button type="submit" class="btn">保存外观设置</button></div>'
        '</form>'
        '<div class="actions-row">'
        '<form method="post" action="/panel/appearance/delete-image">'
        '<button type="submit" class="btn danger">删除背景图片</button></form>'
        '<form method="post" action="/panel/appearance/restore">'
        '<button type="submit" class="btn danger">恢复默认主题</button></form>'
        '</div>'
    )

