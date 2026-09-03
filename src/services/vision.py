"""VisionService：视觉识图（从 AIClient 拆分，防上帝类）。

职责：图片下载（SSRF/大小/魔数校验）→ 视觉模型描述。
client 通过 provider 惰性获取（AIClient 的 httpx.AsyncClient 生命周期由其管理）。
"""
import asyncio
import base64
import os
from typing import Optional

import httpx

from src.core.sanitizer import check_image_url
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)


def _looks_like_image(data: bytes) -> bool:
    """MIME 嗅探：按魔数判断是否为常见图片格式（jpg/png/gif/webp/bmp）。"""
    if not data or len(data) < 8:
        return False
    # JPEG: FF D8 FF
    if data[:3] == b"\xff\xd8\xff":
        return True
    # PNG: 89 50 4E 47 0D 0A 1A 0A
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    # GIF: "GIF87a" / "GIF89a"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    # WebP: "RIFF" .... "WEBP"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    # BMP: "BM"
    if data[:2] == b"BM":
        return True
    return False


class VisionService:
    """视觉识图服务：describe_image / describe_image_file。"""

    def __init__(self, config, client_provider):
        self.config = config
        self._client_provider = client_provider  # () -> httpx.AsyncClient
        self.last_error = ""  # 最近一次下载/描述失败原因（供上层日志）

    @property
    def client(self) -> httpx.AsyncClient:
        return self._client_provider()


    @staticmethod
    def _url_for_log(url: str) -> str:
            """日志用 URL：只保留 scheme://host/path，去掉 query（CDN 直链的签名参数不入日志）。"""
            try:
                from urllib.parse import urlsplit
                p = urlsplit(url or "")
                return f"{p.scheme}://{p.netloc}{p.path}"[:80] or (url or "")[:60]
            except Exception:
                return (url or "")[:60]

    async def describe_image(self, image_url: str) -> Optional[str]:
            """下载图片并调用视觉模型识别，返回一句话描述；失败返回 None。

            视觉模型/网址/key 由环境变量 VISION_MODEL / VISION_API_URL / VISION_API_KEY
            独立配置，留空时回退用 DeepSeek 的 key/网址，默认模型 deepseek-v4-flash-vision-exp。
            """
            if not image_url:
                return None
            model = self.config.VISION_MODEL or "deepseek-v4-flash-vision-exp"
            api_url = self.config.VISION_API_URL or self.config.DEEPSEEK_API_URL
            api_key = self.config.VISION_API_KEY or self.config.DEEPSEEK_API_KEY
            timeout = self.config.VISION_TIMEOUT or 30

            # 1) 获取图片字节（支持 http(s) url 与 data: URI），下载失败重试 1 次
            # P2-7 SSRF/资源防线：scheme 白名单、大小上限、MIME 嗅探、重定向上限。
            image_bytes = await self._download_image(image_url, timeout)
            if not image_bytes:
                if not self.last_error:
                    self.last_error = "下载返回空或非图片"
                logger.warning(f"Vision download failed ({self.last_error}): {self._url_for_log(image_url)}")
                return None
            return await self._describe_image_bytes(image_bytes, model, api_url, api_key, timeout)

    async def _download_image(self, image_url: str, timeout: float = 10.0) -> Optional[bytes]:
        self.last_error = ""
        """下载图片字节（http(s)/data: URI；SSRF/大小/魔数校验 + 每跳校验重定向）。"""
        # P2-7 SSRF/资源防线：scheme 白名单、大小上限、MIME 嗅探、重定向上限。
        # 注：NapCat 本地图片 url 是 127.0.0.1 loopback，因此故意放行 loopback。
        if image_url.startswith("data:"):
            if not image_url.lower().startswith("data:image/"):
                logger.error(f"Image data: URI not an image type: {self._url_for_log(image_url)}")
                return None
            size_cap = self.config.MAX_IMAGE_DOWNLOAD_BYTES
            b64_cap = int(size_cap * 1.4) + 1024
            b64_part = image_url.split(",", 1)[1] if "," in image_url else ""
            if not b64_part or len(b64_part) > b64_cap:
                logger.error(f"Image data: URI too large (> {size_cap} bytes): {self._url_for_log(image_url)}")
                return None
            image_bytes = base64.b64decode(b64_part)
            if not _looks_like_image(image_bytes):
                logger.error(f"Image data: URI content is not an image: {self._url_for_log(image_url)}")
                return None
            return image_bytes
        ok, reason = check_image_url(image_url, getattr(self.config, "IMAGE_ALLOWED_HOSTS", None))
        if not ok:
            logger.error(f"Image url rejected ({reason}): {self._url_for_log(image_url)}")
            return None
        size_cap = self.config.MAX_IMAGE_DOWNLOAD_BYTES
        from urllib.parse import urljoin
        current_url = image_url
        redirects = 0
        for attempt in range(2):
            try:
                body = b""
                rejected = False
                while True:
                    async with self.client.stream("GET", current_url, timeout=timeout,
                                                  follow_redirects=False,
                                                  headers={
                                                      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                                                      "Referer": "https://q.qq.com/",
                                                  }) as resp:
                        if resp.status_code in (301, 302, 303, 307, 308):
                            loc = resp.headers.get("location", "")
                            if not loc or redirects >= 3:
                                return None
                            nxt = urljoin(str(current_url), loc)
                            ok2, reason2 = check_image_url(
                                nxt, getattr(self.config, "IMAGE_ALLOWED_HOSTS", None))
                            if not ok2:
                                logger.error(f"Image redirect rejected ({reason2}): {self._url_for_log(nxt)}")
                                return None
                            current_url = nxt
                            redirects += 1
                            continue
                        if resp.status_code != 200:
                            logger.error(f"Image fetch failed HTTP {resp.status_code} (attempt {attempt + 1}): {self._url_for_log(image_url)}")
                            break
                        cl = resp.headers.get("content-length")
                        if cl and cl.isdigit() and int(cl) > size_cap:
                            logger.error(f"Image content-length too large: {cl} bytes > {size_cap}")
                            rejected = True
                            break
                        async for chunk in resp.aiter_bytes():
                            body += chunk
                            if len(body) > size_cap:
                                rejected = True
                                body = b""
                                break
                        break
                if rejected:
                    logger.error(f"Image too large (> {size_cap} bytes), download aborted: {self._url_for_log(image_url)}")
                    return None
                if body and _looks_like_image(body):
                    return body
                if body:
                    logger.error(f"Downloaded content is not an image: {self._url_for_log(image_url)}")
            except Exception as e:
                logger.error(f"Image fetch error (attempt {attempt + 1}): {e}")
            if attempt == 0:
                await asyncio.sleep(2)
        return None


    async def _describe_image_bytes(self, image_bytes: bytes, model: str, api_url: str,
                                        api_key: str, timeout: float) -> Optional[str]:
            """把图片字节交给视觉模型，返回一句话描述（describe_image 与本地文件共用）。"""
            if not image_bytes:
                return None
            b64 = base64.b64encode(image_bytes).decode("ascii")

            payload = {
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        {"type": "text", "text": "请用一句简短自然的话（25字以内）描述这张图片的内容，不要提'这是一张图片'之类的话。"},
                    ],
                }],
                "temperature": 0.3,
                "max_tokens": 200,
            }
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            try:
                r = await self.client.post(api_url, headers=headers, json=payload, timeout=timeout)
                if r.status_code != 200:
                    logger.error(f"Vision API HTTP {r.status_code}: {r.text[:200]}")
                    return None
                data = r.json()
                if "choices" in data and len(data["choices"]) > 0:
                    content = (data["choices"][0].get("message") or {}).get("content")
                    content = (content or "").strip()
                    return content or None
                logger.error(f"Vision API unexpected response: {str(data)[:200]}")
            except Exception as e:
                logger.error(f"Vision API error: {e}")
            return None

    async def describe_image_file(self, file_path: str) -> Optional[str]:
            """描述本地图片文件（表情包/群消息图），失败返回 None。"""
            try:
                fp = str(file_path or "")
                if fp.startswith("file://"):
                    fp = fp[len("file://"):]
                if not os.path.isabs(fp):
                    # 相对路径：先试 CWD，再试 NapCat 默认图目录（实现差异兜底）
                    for base in (os.getcwd(), "/storage/emulated/0/Android/data"):
                        candidate = os.path.join(base, fp.lstrip("/"))
                        if os.path.exists(candidate):
                            fp = candidate
                            break
                size = os.path.getsize(fp)
                cap = self.config.MAX_IMAGE_DOWNLOAD_BYTES
                if size <= 0 or size > cap:
                    logger.error("Sticker file size out of range: %s (%s bytes)", file_path, size)
                    return None
                with open(file_path, "rb") as f:
                    data = f.read()
                if not _looks_like_image(data):
                    logger.error("Sticker file is not an image: %s", file_path)
                    return None
            except OSError as e:
                logger.error("Sticker file read error: %s err=%s", file_path, e)
                return None
            model = self.config.VISION_MODEL or "deepseek-v4-flash-vision-exp"
            api_url = self.config.VISION_API_URL or self.config.DEEPSEEK_API_URL
            api_key = self.config.VISION_API_KEY or self.config.DEEPSEEK_API_KEY
            timeout = self.config.VISION_TIMEOUT or 30
            return await self._describe_image_bytes(data, model, api_url, api_key, timeout)
