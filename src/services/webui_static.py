"""面板静态资源与缓存策略。

为什么单独一个模块：web_ui.py 有行数上限（防上帝类回归），
这里承载「面板 CSS 的路由」与「HTML 不许缓存」这两件事。
"""
from aiohttp import web

from src.services.web_ui_assets import PANEL_ASSET_VER, panel_asset_body


@web.middleware
async def no_store_html(request, handler):
    """面板是服务端渲染的动态 HTML，绝不能被浏览器缓存。

    否则会出现「代码已更新并重启，页面上还是旧布局」——用户只能靠强刷自救。
    只对 text/html 生效，背景图等静态资源照常缓存。
    """
    resp = await handler(request)
    if getattr(resp, "content_type", "") == "text/html":
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
    return resp


async def handle_panel_static(request: web.Request) -> web.Response:
    """面板样式：/panel/static/{name}。

    登录页也要能加载样式，所以这里不做 token 校验；只允许白名单文件名，杜绝路径穿越。
    返回的是**注入主题变量后**的 CSS（见 panel_asset_body），不是文件原文。
    缓存用 no-cache + ETag：每次回源校验（未变 304），服务端行为一变立刻生效。
    """
    name = request.match_info.get("name", "")
    if not name or "/" in name or "\\" in name or ".." in name:
        return web.Response(status=404, text="Not Found")
    body = panel_asset_body(name)
    if body is None:
        return web.Response(status=404, text="Not Found")
    resp = web.Response(text=body, content_type="text/css", charset="utf-8")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    etag = 'W/"' + PANEL_ASSET_VER + '"'
    resp.headers["ETag"] = etag
    resp.headers["Cache-Control"] = "no-cache"
    if request.headers.get("If-None-Match") == etag:
        return web.Response(status=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    return resp
