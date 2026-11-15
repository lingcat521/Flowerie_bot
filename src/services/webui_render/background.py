"""Responsive background composition using the image ratio and normalized anchors."""

import json
import math
from html import escape
from typing import NamedTuple

MODES = {"auto": "智能适配", "cover": "焦点铺满", "contain": "完整显示", "soft": "完整显示＋柔化补边"}
DEVICES = {"desktop": "电脑", "mobile": "手机"}
POSITIONS = {"center": (.5, .5), "top": (.5, 0), "bottom": (.5, 1), "left": (0, .5), "right": (1, .5)}


class Crop(NamedTuple):
    mode: str
    focus: tuple[float, float]
    protect: tuple[float, float, float, float] | None = None


def parse_crop(mode, focus, protect):
    if mode not in MODES:
        raise ValueError("显示模式无效")

    def percentages(text, count):
        values = tuple(float(item.strip()) / 100 for item in text.replace("，", ",").split(","))
        if len(values) != count or any(not math.isfinite(v) or not 0 <= v <= 1 for v in values):
            raise ValueError("坐标必须是 0～100 的百分比")
        return values

    point = percentages(focus, 2) if focus.strip() else (.5, .5)
    rect = percentages(protect, 4) if protect.strip() else None
    if rect and (rect[0] >= rect[2] or rect[1] >= rect[3]):
        raise ValueError("保护区的右下坐标必须大于左上坐标")
    return Crop(mode, point, rect)


def saved_crops(read_pref):
    raw = read_pref("bg_crop_profiles", "")
    if raw:
        try:
            data = json.loads(raw)
            return {device: parse_crop(*data[device]) for device in DEVICES}
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
    mode = read_pref("bg_size", "")
    focus = POSITIONS.get(read_pref("bg_position", "center"), (.5, .5))
    return {device: Crop(mode if mode in ("cover", "contain") else "auto", focus) for device in DEVICES}


def ratio_limits(ratio, crop, minimum=None):
    # With cover, at most one dimension of the source is cropped.
    keep = minimum if minimum is not None else (.5 if crop.protect else .72)
    left, top, right, bottom = crop.protect or (0, 0, 0, 0)
    return ratio * max(keep, right - left), ratio / max(keep, bottom - top)


def choose_mode(ratio, viewport, crop):
    if crop.mode != "auto":
        return crop.mode
    lo, hi = ratio_limits(ratio, crop)
    return "cover" if lo <= viewport <= hi else "soft"


def _cover(ratio, crop, width, height):
    iw = f"max({width},{ratio:.9f} * {height})"
    ih = f"max({height},{1 / ratio:.9f} * {width})"
    positions = []
    for i, (canvas, image, focus) in enumerate(zip((width, height), (iw, ih), crop.focus, strict=True)):
        lo, hi = f"{canvas} - {image}", "0px"
        if crop.protect:
            start, end = crop.protect[i], crop.protect[i + 2]
            lo = f"max({lo}, -{start:.9f} * {image})"
            hi = f"min(0px, {canvas} - {end:.9f} * {image})"
        preferred = f"calc({canvas} / 2 - {focus:.9f} * {image})"
        # The outer clamp prevents exposed edges even in forced cover.
        pos = f"clamp({canvas} - {image}, {preferred}, 0px)"
        if crop.protect:
            pos = f"clamp({canvas} - {image}, clamp({lo}, {preferred}, {hi}), 0px)"
        positions.append(pos)
    return f"--fit:cover;--position:{' '.join(positions)};--halo:none;"


def _mode_css(mode, ratio, crop, width, height):
    if mode == "cover":
        return _cover(ratio, crop, width, height)
    position = " ".join(f"{value * 100:.8g}%" for value in crop.focus) if mode == "contain" else "center"
    return f"--fit:contain;--position:{position};--halo:{'block' if mode == 'soft' else 'none'};"


def adaptive_rules(bg_color, url, opacity, ratio, crops):
    rules = [f".bg-layer{{background-color:{bg_color};}}",
             f'.bg-art{{--wallpaper:url("{url}");opacity:{opacity / 100:.3f};}}']
    for device, crop in crops.items():
        query = "(min-width:1024px)" if device == "desktop" else "(width < 1024px)"
        base = "soft" if crop.mode == "auto" else crop.mode
        selector = ".bg-layer > .bg-art"
        baseline = crop._replace(protect=None) if crop.mode == "cover" else crop
        css = _mode_css(base, ratio, baseline, "100cqw", "100cqh")
        rules.append(f"@media {query}{{{selector}{{{css}}}}}")
        if crop.mode == "auto" or (crop.mode == "cover" and crop.protect):
            lo, hi = ratio_limits(ratio, crop, .000001 if crop.mode == "cover" else None)
            cover = _mode_css("cover", ratio, crop, "100cqw", "100cqh")
            rules.append(f"@media {query}{{@container wallpaper (min-aspect-ratio:{lo:.9f}) and "
                         f"(max-aspect-ratio:{hi:.9f}){{{selector}{{{cover}}}}}}}")
    return "\n".join(rules)


def render_crop_controls(crops, ratio, image_url, bg_color, opacity, *, draft=False):
    sections = []
    for device, name in DEVICES.items():
        crop = crops[device]
        width, height = (1600, 900) if device == "desktop" else (390, 844)
        preview = ""
        if ratio and image_url:
            mode = choose_mode(ratio, width / height, crop)
            keep = min(ratio / (width / height), (width / height) / ratio)
            preview_crop = crop
            if crop.mode == "cover" and crop.protect:
                lo, hi = ratio_limits(ratio, crop, .000001)
                if not lo <= width / height <= hi:
                    preview_crop = crop._replace(protect=None)
            css = _mode_css(mode, ratio, preview_crop, "100cqw", "100cqh")
            css += f'--wallpaper:url("{image_url}");opacity:{opacity / 100:.3f};'
            preview = (
                f'<div class="crop-preview crop-{device}" style="aspect-ratio:{width}/{height};background:{escape(bg_color)}">'
                f'<div class="bg-art" style="{escape(css)}"></div>'
                + ('<div class="crop-sidebar" aria-hidden="true"></div>' if device == "desktop" else "")
                + f'</div><p class="hint">{"预览" if draft else "已保存的效果"} · 铺满保留约 {keep:.0%} · {MODES[mode]}</p>'
            )

        def coords(values):
            return ", ".join(format(value * 100, ".8g") for value in values)

        prefix = f"crop_{device}"
        options = "".join(f'<option value="{mode}"{" selected" if mode == crop.mode else ""}>{label}</option>'
                          for mode, label in MODES.items())
        sections.append(
            f'<section class="crop-settings"><h3>{name}背景</h3>{preview}'
            f'<label for="{prefix}_mode">显示模式</label>'
            f'<select id="{prefix}_mode" name="{prefix}_mode">{options}</select>'
            f'<label for="{prefix}_focus">焦点 X, Y（%）</label>'
            f'<input id="{prefix}_focus" name="{prefix}_focus" value="{coords(crop.focus)}" placeholder="50, 50">'
            f'<label for="{prefix}_protect">保护区域 左, 上, 右, 下（%，可留空）</label>'
            f'<input id="{prefix}_protect" name="{prefix}_protect" value="{coords(crop.protect or ())}" '
            'placeholder="例如 25, 10, 75, 55"></section>'
        )
    return (
        '<p class="hint">坐标从原图左上角算起。电脑以 16:9 预览，手机以 390×844 预览。'
        '实际裁切随窗口变化。先保存新图片，之后可预览未保存的裁剪设置。</p>'
        f'<div class="crop-settings-grid">{"".join(sections)}</div>'
    )
