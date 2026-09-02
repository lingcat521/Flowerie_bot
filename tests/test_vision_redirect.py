"""图片下载：每跳校验重定向（SSRF 不因跳转失守；NT CDN 3xx 图片可下载）。"""
import asyncio

import httpx

from src.services.vision import VisionService


class _Cfg:
    MAX_IMAGE_DOWNLOAD_BYTES = 5 * 1024 * 1024
    IMAGE_ALLOWED_HOSTS = None
    IMAGE_ALLOWED_REDIRECTS = 3
    IMAGE_DOWNLOAD_MAX_REDIRECTS = 3


class _NoImage:
    def _looks_like_image(self, b):
        return True


def _make(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return VisionService(_Cfg(), lambda: client), client


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 128


def test_redirect_followed_with_validation(tmp_path):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.path.startswith("/img"):
            return httpx.Response(302, headers={"location": "https://cdn.example.com/real.png"})
        return httpx.Response(200, content=PNG)

    svc, client = _make(handler)
    out = asyncio.run(svc._download_image("https://multimedia.example.com/img?x=1", timeout=10))
    assert out == PNG
    assert seen == ["https://multimedia.example.com/img?x=1", "https://cdn.example.com/real.png"]
    asyncio.run(client.aclose())


def test_redirect_to_private_rejected():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.path.startswith("/a"):
            return httpx.Response(302, headers={"location": "http://169.254.169.254/meta"})
        return httpx.Response(200, content=PNG)

    svc, client = _make(handler)
    out = asyncio.run(svc._download_image("https://pub.example.com/a", timeout=10))
    assert out is None            # 内网元数据跳转被拒 → 不下载
    assert seen == ["https://pub.example.com/a"]   # 只请求了第一跳
    asyncio.run(client.aclose())


def test_no_redirect_plain_download():
    def handler(request):
        return httpx.Response(200, content=PNG)

    svc, client = _make(handler)
    out = asyncio.run(svc._download_image("https://cdn.example.com/x.png", timeout=10))
    assert out == PNG
    asyncio.run(client.aclose())
