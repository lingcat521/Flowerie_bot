#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web UI 渲染探针（只读诊断，不改产品代码）：手机/平板/桌面视口下渲染真实面板并截图。

- 浏览器上下文显式关闭 JavaScript（java_script_enabled=False）——与「Web UI 禁用 JS」一致
- 探针不向页面注入任何脚本：只用 Playwright 的 Python API（截图 / bounding_box / 鼠标滚动）
- 页面来源：① 真实 WebUIServer（与 main.py 同一路径）+ 登录 cookie；② 渲染层直出的合成页
  （人格/群聊知识/插件/群昵称/液态玻璃，这些页需要注入管理器才能通过服务端渲染）
- 只读：服务端页只发 GET；合成页只写 probe-out/html/

产物：probe-out/*.png + probe-out/report.json + 末尾 ===PROBE-REPORT=== JSON
"""
import asyncio
import json
import os
import re
import sys
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

OUT = os.path.join(ROOT, "probe-out")
HTML_DIR = os.path.join(OUT, "html")
PORT = 18099
BASE = "http://127.0.0.1:%d" % PORT
USERNAME = "admin"
PASSWORD = "secret123"

VIEWPORTS = [
    ("phone-390x844", 390, 844),
    ("tablet-820x1180", 820, 1180),
    ("laptop-1366x768", 1366, 768),
    ("desktop-1920x1080", 1920, 1080),
]
# (名字, 路径, 是否需要登录, 额外滚动几屏)
PAGES = [
    ("login", "/panel", False, 0),
    ("config", "/panel", True, 1),
    ("appearance", "/panel?tab=appearance", True, 1),
    ("account", "/panel?tab=account", True, 0),
    ("logs", "/panel?tab=logs", True, 0),
]
MEASURE = [".wrap", ".topbar", ".tabs", ".cats", ".group", ".row", ".row-info", ".row-control",
           ".btn", ".auth-card", ".theme-grid", ".theme-card", ".row .row", ".row-control .row"]


def write_env() -> None:
    values = {
        "DEEPSEEK_API_KEY": "sk-probe-key-123456",
        "BOT_QQ": "10001",
        "WS_PORT": "3001",
        "WEB_UI_ENABLED": "true",
        "WEB_UI_PORT": str(PORT),
        "WEB_UI_USERNAME": USERNAME,
        "WEB_UI_PASSWORD": PASSWORD,
        "LOG_FORMAT": "text",
    }
    with open(".env", "w", encoding="utf-8") as fh:
        fh.write("\n".join("%s=%s" % (k, v) for k, v in values.items()) + "\n")


async def start_server():
    from src.config import load_config
    from src.repositories.settings_repository import SettingsRepository
    from src.services.config_service import ConfigService
    from src.services.web_ui import WebUIServer

    cfg = load_config()
    cfg.WEB_UI_PORT = PORT
    repo = SettingsRepository(cfg.SETTINGS_DB_PATH)
    svc = ConfigService(cfg, repo, env_path=os.path.join(ROOT, ".env"))
    wui = WebUIServer(cfg, svc, data_dir=os.path.join(ROOT, "data", "webui_probe"))
    await wui.start()
    return wui, svc


async def login_token(session) -> str:
    body = urllib.parse.urlencode({"username": USERNAME, "password": PASSWORD}).encode()
    async with session.post(BASE + "/panel/login", data=body,
                            headers={"Content-Type": "application/x-www-form-urlencoded"},
                            allow_redirects=False) as resp:
        match = re.search(r"fb_token=([^;]+)", resp.headers.get("Set-Cookie", ""))
        return match.group(1) if match else ""


def build_synth_pages(configs) -> dict:
    """用渲染层直出需要注入管理器才能看到的页面（人格/知识/插件/昵称/玻璃）。"""
    from src.services.webui_render.account import render_account_tab  # noqa: F401
    from src.services.webui_render.appearance import render_appearance
    from src.services.webui_render.config_panel import render_config_sections
    from src.services.webui_render.knowledge import render_knowledge_tab
    from src.services.webui_render.nicknames import render_nicknames_tab
    from src.services.webui_render.pages import render_panel_page
    from src.services.webui_render.persona import render_persona_tab
    from src.services.webui_render.plugins import render_plugin_tab
    from src.services.webui_render.theme import (
        background_rules,
        theme_body_class,
        theme_default_bg,
    )

    personas = [
        {"id": "flowerie", "name": "花璃", "description": "内置默认人格", "builtin": True},
        {"id": "atri", "name": "亚托莉", "description": "内置人格", "builtin": True},
        {"id": "custom_x", "name": "自定义人格", "description": "管理员创建", "builtin": False},
    ]
    bindings = [{"group_id": 123456, "persona_id": "atri"},
                {"group_id": 654321, "persona_id": "custom_x"}]
    persona_cfgs = [c for c in configs if c.get("key", "").startswith("PERSONA_")][:3]
    knowledge_rows = [
        {"term": "电子宠物", "meaning": "群里对某人的调侃称呼", "examples": "你今天又跑了？",
         "confidence": "high", "status": "active"},
        {"term": "花璃", "meaning": "机器人本体的自称", "examples": "", "confidence": "medium",
         "status": "active"},
    ]
    plugins = [
        {"id": "demo_py", "name": "示例 Python 插件", "version": "1.0.0", "runtime": "python",
         "manifest_valid": True, "enabled": False, "status": "disabled", "description": "演示用插件",
         "declared_permissions": ["network", "storage"], "approved_permissions": [],
         "install_source": "local"},
        {"id": "demo_json", "name": "声明式 JSON 插件", "version": "2.1.0", "runtime": "json",
         "manifest_valid": True, "enabled": True, "status": "running", "description": "",
         "declared_permissions": [], "approved_permissions": [], "install_source": "url"},
    ]
    plugin_cfgs = [c for c in configs if c.get("key", "").startswith("PLUGIN_")][:5]
    nicknames = {"123456": "小璃", "123456:atri": "阿特", "777777": "花璃酱"}

    def page(body_html, active_tab, glass=False, theme="default"):
        bg_rules = background_rules(theme_default_bg(theme), "", 100, "cover", "center")
        return render_panel_page(
            theme_class=theme_body_class(theme), bg_rules=bg_rules, msg_html="",
            body_html=body_html, active_tab=active_tab,
            panel_bg_css="rgba(255,255,255,0.90)", glass=glass,
        )

    pages = {
        "synth-persona": page(render_persona_tab(
            personas, "flowerie", bindings, persona_configs=persona_cfgs,
            admin_rules=["回复尽量在15～20字以内 简洁自然", "用空格代替逗号",
                         "绝对不使用任何 emoji 表情"],
            rules_text="回复尽量简短", group_rules={"123456": "本群禁止剧透"},
            group_gids=["123456", "654321"], global_prompt="全局补充 Prompt",
            group_prompt="本群补充 Prompt", prompt_gid=123456), "persona"),
        "synth-knowledge": page(render_knowledge_tab(
            123456, knowledge_rows, search="", count=len(knowledge_rows),
            max_memes=500, meme_configs=[c for c in configs if c.get("key", "").startswith("MEME_")][:4]),
            "knowledge"),
        "synth-plugins": page(render_plugin_tab(
            plugins, protection="normal", plugin_configs=plugin_cfgs, protection_warning=False,
            webui_links=[("示例面板", "/panel/plugins/webui/demo_py/main")]), "plugins"),
        "synth-nicknames": page(render_nicknames_tab(
            nicknames, "花璃", group_ids=["123456", "654321"],
            personas=[("flowerie", "花璃"), ("atri", "亚托莉")]), "nicknames"),
        "synth-config-glass": page(
            render_config_sections(configs, active_cat="all",
                                   category_labels={c["category"]: c["category"] for c in configs}),
            "config", glass=True),
        "synth-appearance": page(render_appearance(
            "default", theme_default_bg("default"), 100, "cover", "center", False,
            panel_opacity=90, panel_style="clear"), "appearance"),
        "synth-appearance-glass": page(render_appearance(
            "default", theme_default_bg("default"), 100, "cover", "center", False,
            panel_opacity=90, panel_style="glass"), "appearance", glass=True),
    }
    return pages


def write_synth(pages: dict) -> dict:
    os.makedirs(HTML_DIR, exist_ok=True)
    paths = {}
    for name, html in pages.items():
        path = os.path.join(HTML_DIR, name + ".html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        paths[name] = "file://" + path
    return paths


async def measure(page, selector: str):
    locator = page.locator(selector)
    try:
        count = await locator.count()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:120]}
    if not count:
        return {"count": 0}
    box = await locator.first.bounding_box()
    if not box:
        return {"count": count, "box": None}
    return {"count": count, "box": {k: round(float(v), 1) for k, v in box.items()}}


async def shoot(page, path: str) -> bool:
    try:
        await page.screenshot(path=path)
        return True
    except Exception:  # noqa: BLE001
        return False


async def shoot_filtered(page, selector: str, text: str, path: str) -> bool:
    """按文本过滤后对单个元素截图（纯 Playwright API，不注入脚本）。"""
    try:
        locator = page.locator(selector).filter(has_text=text)
        if await locator.count() == 0:
            return False
        await locator.first.screenshot(path=path)
        return True
    except Exception:  # noqa: BLE001
        return False


async def shoot_element(page, selector: str, path: str) -> bool:
    try:
        if await page.locator(selector).count() == 0:
            return False
        await page.locator(selector).first.screenshot(path=path)
        return True
    except Exception:  # noqa: BLE001
        return False


async def run_probe(report: dict, synth_paths: dict) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--hide-scrollbars", "--force-color-profile=srgb"])
        for vname, width, height in VIEWPORTS:
            context = await browser.new_context(
                viewport={"width": width, "height": height},
                java_script_enabled=False,
                device_scale_factor=1,
                user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            )
            await context.add_cookies([{"name": "fb_token", "value": report["token"],
                                        "url": BASE, "httpOnly": True, "sameSite": "Strict"}])
            page = await context.new_page()
            vp = {"width": width, "height": height, "pages": {}}
            report["viewports"][vname] = vp
            targets = [(n, BASE + p, auth, extra) for n, p, auth, extra in PAGES]
            targets += [(n, url, True, 1 if "persona" in n or "knowledge" in n else 0)
                        for n, url in synth_paths.items()]
            for pname, url, _auth, extra_scroll in targets:
                entry = {"url": url if url.startswith("file:") else url.replace(BASE, "")}
                try:
                    response = await page.goto(url, wait_until="load", timeout=30000)
                    entry["status"] = response.status if response else None
                    entry["measures"] = {}
                    for selector in MEASURE:
                        entry["measures"][selector] = await measure(page, selector)
                    entry["shot"] = await shoot(page, os.path.join(OUT, "%s-%s-top.png" % (pname, vname)))
                    entry["group_shot"] = await shoot_element(
                        page, "fieldset.group", os.path.join(OUT, "%s-%s-group.png" % (pname, vname)))
                    entry["row_shot"] = await shoot_element(
                        page, ".row", os.path.join(OUT, "%s-%s-row.png" % (pname, vname)))
                    if pname in ("synth-persona", "persona"):
                        entry["bind_group_shot"] = await shoot_filtered(
                            page, "fieldset.group", "群聊人格",
                            os.path.join(OUT, "%s-%s-bindgroup.png" % (pname, vname)))
                    entry["nested_row_count"] = await page.locator(".row .row").count()
                    entry["nested_control_count"] = await page.locator(".row-control .row-control").count()
                    entry["form_count"] = await page.locator("form").count()
                    entry["details_count"] = await page.locator("details").count()
                    body = await page.locator("body").bounding_box()
                    entry["body_height_px"] = body.get("height") if body else None
                    if extra_scroll:
                        await page.mouse.move(width // 2, height // 2)
                        await page.mouse.wheel(0, height)
                        await page.wait_for_timeout(250)
                        entry["scrolled_shot"] = await shoot(
                            page, os.path.join(OUT, "%s-%s-scrolled.png" % (pname, vname)))
                except Exception as exc:  # noqa: BLE001
                    entry["error"] = str(exc)[:300]
                vp["pages"][pname] = entry
                print("[probe] %s / %s -> nested=%s %s" % (
                    vname, pname, entry.get("nested_row_count"),
                    entry.get("error") or "ok"))
            await context.close()
        await browser.close()


async def main() -> int:
    import aiohttp

    os.makedirs(OUT, exist_ok=True)
    write_env()
    report = {"port": PORT, "viewports": {}, "token": ""}
    wui, svc = await start_server()
    try:
        async with aiohttp.ClientSession() as session:
            report["token"] = await login_token(session)
        print("[probe] login token acquired: %s" % bool(report["token"]))
        synth_paths = write_synth(build_synth_pages(svc.list_configs()))
        print("[probe] synth pages: %s" % ", ".join(sorted(synth_paths)))
        await run_probe(report, synth_paths)
    finally:
        await wui.stop()
    report.pop("token", None)
    with open(os.path.join(OUT, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print("===PROBE-REPORT===")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    print("===PROBE-REPORT-END===")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

