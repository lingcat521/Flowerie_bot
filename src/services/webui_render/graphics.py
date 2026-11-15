"""Decorative, script-free SVG used by the built-in panel."""
from math import cos, radians, sin


def _svg(view_box, body, css_class):
    return (f'<svg class="{css_class}" viewBox="{view_box}" aria-hidden="true" focusable="false" '
            f'xmlns="http://www.w3.org/2000/svg">{body}</svg>')


def _flower():
    petals = "".join(
        f'<ellipse cx="16" cy="9" rx="4" ry="7" transform="rotate({angle} 16 16)"/>'
        for angle in (0, 90, 180, 270)
    )
    return f'<g fill="var(--accent)">{petals}</g><circle cx="16" cy="16" r="2" fill="var(--brand-core,var(--ui-bg))"/>'


def flower(css_class="brand-flower"):
    return _svg("0 0 32 32", _flower(), css_class)


_ICONS = {
    "files": 'M4 2h8l4 4v12H4ZM12 2v5h4M7 10h6m-6 4h6',
    "config": 'M2 5h5m3 0h8M2 10h9m3 0h4M2 15h3m3 0h10 M10 5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0Zm4 5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0Zm-6 5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0Z',
    "persona": 'M13 6a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM4 17v-1a6 6 0 0 1 12 0v1',
    "knowledge": 'M10 5v12M10 5C8 3 5 3 2 4v11c3-1 6-1 8 2 2-3 5-3 8-2V4c-3-1-6-1-8 1Z',
    "profiles": 'M2 5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2Zm7 3a2 2 0 1 1-4 0 2 2 0 0 1 4 0ZM4 14q3-5 6 0m2-6h3m-3 4h3',
    "admin": 'M10 2 17 5v4c0 4-3 7-7 9-4-2-7-5-7-9V5Zm-3 8 2 2 4-4',
    "qzone": 'M2 5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2Zm0 9 5-5 4 4 2-2 5 4m-3-8a1 1 0 1 0-2 0 1 1 0 0 0 2 0Z',
    "private": 'M5 3h10a3 3 0 0 1 3 3v5a3 3 0 0 1-3 3H8l-4 4v-4a3 3 0 0 1-2-3V6a3 3 0 0 1 3-3Zm1 5h8m-8 3h5',
    "nicknames": 'M2 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2Zm4 3h7m-7 3h4',
    "plugins": 'M3 3h5a2 2 0 1 1 4 0h5v5a2 2 0 1 1 0 4v5h-5a2 2 0 1 0-4 0H3Z',
    "search": 'M14 8a6 6 0 1 1-12 0 6 6 0 0 1 12 0Zm-2 4 6 6',
    "automation": 'm11 2-8 10h6l-1 6 9-10h-6l1-6Z',
    "appearance": 'M10 2c5 0 8 3 8 7 0 2-2 3-4 3h-1a2 2 0 0 0-1 3c0 2-1 3-3 3-4 0-7-4-7-8a8 8 0 0 1 8-8ZM6 9h.1M9 6h.1M13 6h.1',
    "logs": 'M2 5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2Zm4 2 3 3-3 3m5 0h3',
    "account": 'M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-5-2a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM4 15q6-6 12 0',
    "logout": 'M9 3H4a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h5m0-7h8m-3-3 3 3-3 3',
    "lock": 'M5 9V6a5 5 0 0 1 10 0v3M4 9h12a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1Zm6 4v2',
    "ok": 'M3 10l5 5 9-10',
    "error": 'M10 5v6m0 4h.1M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z',
}


def icon(name, css_class="nav-icon"):
    return _svg("0 0 20 20", f'<path fill="none" stroke="currentColor" stroke-width="1.5" '
                f'stroke-linecap="round" stroke-linejoin="round" d="{_ICONS[name]}"/>', css_class)


def _path(d, css_class=""):
    return f'<path class="{css_class}" d="{d}"/>'


def _rect(x, y, width, height, radius, css_class=""):
    return (f'<rect x="{x}" y="{y}" width="{width}" height="{height}" '
            f'rx="{radius}" class="{css_class}"/>')


def _circle(x, y, radius, css_class=""):
    return f'<circle cx="{x}" cy="{y}" r="{radius}" class="{css_class}"/>'


_SHIELD = "M80 8L124 24V42Q122 62 80 74Q38 62 36 42V24Z"
_HEADING_ART = {
    "config": _path("M16 20h128M16 40h128M16 60h128") + "".join(
        _circle(x, y, 6, "art-accent art-surface") for x, y in ((48, 20), (112, 40), (76, 60))
    ),
    "persona": _rect(62, 8, 64, 60, 8) + _rect(34, 16, 64, 60, 8, "art-raised art-accent")
    + _circle(66, 36, 8, "art-accent") + _path("M50 62Q66 44 82 62", "art-accent"),
    "knowledge": _rect(30, 8, 100, 52, 6, "art-raised") + _rect(24, 14, 100, 52, 6, "art-raised")
    + _rect(18, 20, 100, 52, 6, "art-raised art-accent") + _path("M30 36h68M30 46h68"),
    "profiles": _path("M28 18L132 62M132 18L28 62") + _circle(80, 40, 12, "art-selected art-accent")
    + "".join(_circle(x, y, 5, "art-raised") for x in (28, 132) for y in (18, 62)),
    "admin": _path(_SHIELD) + '<g transform="translate(24 12) scale(.7)">'
    + _path(_SHIELD, "art-accent") + "</g>" + _path("M65 40l11 11 21-22", "art-accent"),
    "qzone": _rect(58, 8, 78, 54, 6) + _rect(22, 20, 88, 52, 6, "art-raised art-accent")
    + _circle(88, 34, 4, "art-accent") + _path("M32 62l19-20 16 15 9-8 24 13", "art-accent"),
    "private": _path("M76 12h52q8 0 8 8v24q0 8-8 8v8l-12-8H76q-8 0-8-8V20q0-8 8-8Z")
    + _path("M32 30h60q8 0 8 8v20q0 8-8 8H44l-12 8v-8q-8 0-8-8V38q0-8 8-8Z", "art-raised art-accent")
    + _path("M39 43h46M39 53h31"),
    "nicknames": "".join(
        _rect(x, y, 100, 18, 6, "art-raised art-accent" if y == 54 else "art-raised")
        + _circle(x + 12, y + 9, 3) + _path(f"M{x + 23} {y + 9}h40")
        for x, y in ((20, 10), (40, 32), (20, 54))
    ),
    "plugins": _path("M74 22h8M74 54h8M62 34v8M94 34v8") + "".join(
        _rect(x, y, 24, 24, 4, "art-selected art-accent" if (x, y) == (82, 42) else "art-raised")
        for x in (50, 82) for y in (10, 42)
    ),
    "search": _circle(66, 34, 23, "art-accent") + _path("M83 51l26 21", "art-accent art-handle")
    + _path("M18 20h16M12 36h18"),
    "automation": _rect(8, 26, 36, 28, 6, "art-raised") + _rect(62, 26, 36, 28, 6, "art-selected art-accent")
    + _rect(116, 26, 36, 28, 6, "art-raised") + _path("M46 40h13l-4-4m4 4-4 4m45-4h13l-4-4m4 4-4 4"),
    "appearance": _rect(22, 16, 36, 48, 6, "art-input") + _rect(62, 16, 36, 48, 6, "art-raised")
    + _rect(102, 16, 36, 48, 6, "art-selected") + _rect(114, 34, 12, 12, 3, "art-solid"),
    "logs": "".join(_path(f"M20 {y}h120") + _circle(20, y, 3, "art-solid" if y == 60 else "art-raised")
                    for y in (20, 40, 60)) + _path("M76 60h40", "art-accent"),
    "account": _circle(80, 40, 30) + _circle(80, 30, 9, "art-accent")
    + _path("M60 58Q80 34 100 58", "art-accent") + _path("M25 40h16M119 40h16"),
}


def heading_art(tab):
    return _svg("0 0 160 80", _HEADING_ART["knowledge" if tab == "files" else tab], "heading-art")


def auth_art(page):
    if page == "login":
        orbit = _circle(180, 180, 84, "art-accent") + _circle(180, 180, 136, "art-accent")
        points = "".join(_circle(round(180 + 136 * cos(radians(a)), 2),
                                 round(180 + 136 * sin(radians(a)), 2), 4, "art-solid")
                         for a in (30, 120, 210, 300))
        return _svg("0 0 360 360", orbit + points + _path("M180 180l76 56", "art-accent")
                    + f'<g transform="translate(144 144) scale(2.25)">{_flower()}</g>', "auth-art")
    if page == "register":
        return _svg("0 0 360 360", _rect(100, 50, 180, 220, 16, "art-raised")
                    + _rect(60, 90, 180, 220, 16, "art-raised art-accent")
                    + _circle(150, 155, 20, "art-accent") + _path("M110 216Q150 161 190 216", "art-accent")
                    + _path("M106 245h88M122 266h56"), "auth-art")
    return _svg("0 0 240 240", _path("M120 26l72 27v63q0 59-72 99-72-40-72-99V53Z")
                + _rect(96, 98, 48, 56, 8, "art-raised art-accent")
                + _path("M106 98V86a14 14 0 0 1 28 0v12m-14 24v13", "art-accent"), "auth-art auth-art-lock")


def empty_state(tab, description):
    return f'<div class="empty-state">{icon(tab, "empty-icon")}<p>{description}</p></div>'
