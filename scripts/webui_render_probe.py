#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web UI 渲染探针（只读诊断，不改产品代码）：在手机/平板/桌面视口下渲染真实面板并截图。

设计约束（与用户环境一致）：
- 浏览器上下文显式关闭 JavaScript（java_script_enabled=False）——与「Web UI 禁用 JS」一致
- 探针不向页面注入任何脚本：只用 Playwright 的 Python API（截图 / bounding_box / 鼠标滚动）
- 只读：真实启动 WebUIServer（与 main.py 同一路径）+ 登录拿 fb_token，不做任何写操作

产物：probe-out/<页面>-<视口>-<类型>.png  +  末尾打印 ===PROBE-REPORT=== 的 JSON 量测结果
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
PORT = 18099
BASE = "http://127.0.0.1:%d" % PORT
USERNAME = "admin"
PASSWORD = "secret123"

# 覆盖：手机（竖屏）/ 平板（竖屏、横屏）/ 笔记本 / 桌面宽屏
VIEWPORTS = [
    ("phone-390x844", 390, 844),
    ("tablet-820x1180", 820, 1180),
    ("laptop-1366x768", 1366, 768),
    ("desktop-1920x1080", 1920, 1080),
]
# (名字, 路径, 是否需要登录, 纵向滚动几屏后再补一张)
PAGES = [
    ("login", "/panel", False, 0),
    ("config", "/panel", True, 1),
    ("appearance", "/panel?tab=appearance", True, 1),
    ("account", "/panel?tab=account", True, 0),
    ("persona", "/panel?tab=persona", True, 0),
    ("logs", "/panel?tab=logs", True, 0),
]
MEASURE = [".wrap", ".topbar", ".brand", ".tabs", ".tab", ".cats", ".cat", "details",
           ".group", ".row", ".row-info", ".row-control", ".btn", ".auth-card",
           ".theme-grid", ".theme-card"]


def write_env() -> None:
    """验收脚本同款最小 .env（探针只读，不写回）。"""
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
    return wui


async def login_token(session) -> str:
    body = urllib.parse.urlencode({"username": USERNAME, "password": PASSWORD}).encode()
    async with session.post(BASE + "/panel/login", data=body,
                            headers={"Content-Type": "application/x-www-form-urlencoded"},
                            allow_redirects=False) as resp:
        match = re.search(r"fb_token=([^;]+)", resp.headers.get("Set-Cookie", ""))
        return match.group(1) if match else ""


async def measure(page, selector: str):
    """只用 Playwright API 量测（不注入脚本）。"""
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


async def shoot_element(page, selector: str, path: str) -> bool:
    locator = page.locator(selector).first
    try:
        if await page.locator(selector).count() == 0:
            return False
        await locator.screenshot(path=path)
        return True
    except Exception:  # noqa: BLE001
        return False


async def run_probe(report: dict) -> None:
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
            page = await context.new_page()
            report["viewports"][vname] = {"width": width, "height": height, "pages": {}}
            for pname, path, needs_auth, extra_scroll in PAGES:
                entry = {"url": path}
                try:
                    if needs_auth:
                        await context.add_cookies([{"name": "fb_token", "value": report["token"],
                                                   "url": BASE, "httpOnly": True,
                                                   "sameSite": "Strict"}])
                    response = await page.goto(BASE + path, wait_until="load", timeout=30000)
                    entry["status"] = response.status if response else None
                    entry["measures"] = {}
                    for selector in MEASURE:
                        entry["measures"][selector] = await measure(page, selector)
                    out = os.path.join(OUT, "%s-%s-top.png" % (pname, vname))
                    entry["shot"] = await shoot(page, out)
                    entry["group_shot"] = await shoot_element(
                        page, "fieldset.group", os.path.join(OUT, "%s-%s-group.png" % (pname, vname)))
                    entry["row_shot"] = await shoot_element(
                        page, ".row", os.path.join(OUT, "%s-%s-row.png" % (pname, vname)))
                    entry["form_count"] = await page.locator("form").count()
                    entry["details_count"] = await page.locator("details").count()
                    entry["body_scroll_height_px"] = (await page.locator("body").bounding_box() or {}).get("height")
                    if extra_scroll:
                        await page.mouse.move(width // 2, height // 2)
                        await page.mouse.wheel(0, height)
                        await page.wait_for_timeout(250)
                        mid = os.path.join(OUT, "%s-%s-scrolled.png" % (pname, vname))
                        entry["scrolled_shot"] = await shoot(page, mid)
                except Exception as exc:  # noqa: BLE001
                    entry["error"] = str(exc)[:300]
                report["viewports"][vname]["pages"][pname] = entry
                print("[probe] %s / %s -> %s" % (vname, pname, entry.get("error") or "ok"))
            await context.close()
        await browser.close()


async def main() -> int:
    import aiohttp

    os.makedirs(OUT, exist_ok=True)
    write_env()
    report = {"port": PORT, "viewports": {}, "token": ""}
    wui = await start_server()
    try:
        async with aiohttp.ClientSession() as session:
            report["token"] = await login_token(session)
        print("[probe] login token acquired: %s" % bool(report["token"]))
        await run_probe(report)
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

