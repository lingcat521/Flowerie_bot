"""Web UI 配置域处理器（无 JS 分组表单保存）。

从 WebUIServer 拆分（防上帝类）：配置保存走 ConfigService（.env + settings.db 双写）。
"""
from typing import Dict
from urllib.parse import quote

from aiohttp import web

from src.services.config_service import ConfigService
from src.services.file_parser import file_parse_error

_STATUS = {"invalid_argument": 400, "file_too_large": 413, "unsupported_format": 415,
           "parse_failed": 422, "busy": 429, "unavailable": 503}


async def _read_bounded(stream, limit):
    result = bytearray()
    while True:
        size = min(65536, limit + 1 - len(result))
        chunk = await stream(size)
        if not chunk:
            return bytes(result)
        result.extend(chunk)
        if len(result) > limit:
            return None


class ConfigPanelMixin:

    async def _handle_panel_model_test(self, request: web.Request) -> web.Response:
        """模型连接测试（ping）：主聊天模型 / 花语向量模型 / 花语重排模型。

        用当前已保存配置发起真实请求；结果经 msg 回显（零 JS：表单 POST → 重定向）。
        """
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        form = await request.post()
        target = str(form.get("target", "") or "")
        cat = "BlossomMemory" if target in ("embedding", "reranker") else "AI"
        back = str(form.get("back", "") or "")
        try:
            if target == "chat" or target == "deepseek":
                ok, msg = await self._ping_chat()
            elif target == "vision":
                ok, msg = await self._ping_vision()
            elif target == "toxic":
                ok, msg = await self._ping_toxic()
            elif target == "embedding":
                ok, msg = await self._ping_embedding()
            elif target == "reranker":
                ok, msg = await self._ping_reranker()
            else:
                ok, msg = False, "未知测试目标"
        except Exception as e:  # noqa: BLE001 - 测试失败即结果
            ok, msg = False, f"{type(e).__name__}: {e}"
        if back == "account":
            return web.HTTPFound(f"/panel?tab=account&msg={quote(msg)}&err={'1' if not ok else ''}")
        return web.HTTPFound(f"/panel?cat={cat}&msg={quote(msg)}&err={'1' if not ok else ''}")

    async def _ping_chat(self):
        import httpx
        cfg = self.config
        url = str(getattr(cfg, "DEEPSEEK_API_URL", "") or "").strip()
        key = str(getattr(cfg, "DEEPSEEK_API_KEY", "") or "").strip()
        model = str(getattr(cfg, "DEEPSEEK_MODEL", "") or "").strip()
        if not url or not key:
            return False, "未配置 DEEPSEEK_API_URL / DEEPSEEK_API_KEY"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    url, json={"model": model, "messages": [{"role": "user", "content": "ping"}],
                               "max_tokens": 1}, headers={"Authorization": f"Bearer {key}"})
                if resp.status_code == 200:
                    return True, "连接成功（模型已响应 ping）"
                return False, f"HTTP {resp.status_code}：{(resp.text or '')[:160]}"
        except httpx.HTTPError as e:
            return False, f"连接失败：{type(e).__name__}: {e}"

    async def _ping_vision(self):
        import httpx
        cfg = self.config
        url = str(getattr(cfg, "VISION_API_URL", "") or "").strip()
        key = str(getattr(cfg, "VISION_API_KEY", "") or "").strip()
        model = str(getattr(cfg, "VISION_MODEL", "") or "").strip()
        if not url or not key:
            # 未独立配置 → 回退 DeepSeek（生产行为一致）
            return await self._ping_chat()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    url, json={"model": model, "messages": [{"role": "user", "content": "ping"}],
                               "max_tokens": 1}, headers={"Authorization": f"Bearer {key}"})
                if resp.status_code == 200:
                    return True, "视觉识图连接成功"
                return False, f"HTTP {resp.status_code}：{(resp.text or '')[:160]}"
        except httpx.HTTPError as e:
            return False, f"连接失败：{type(e).__name__}: {e}"

    async def _ping_toxic(self):
        import httpx
        cfg = self.config
        url = str(getattr(cfg, "TOXIC_API_URL", "") or "").strip()
        key = str(getattr(cfg, "TOXIC_API_KEY", "") or "").strip()
        model = str(getattr(cfg, "TOXIC_MODEL", "") or "").strip()
        if not url or not key:
            return await self._ping_chat()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    url, json={"model": model, "messages": [{"role": "user", "content": "ping"}],
                               "max_tokens": 1}, headers={"Authorization": f"Bearer {key}"})
                if resp.status_code == 200:
                    return True, "引战检测连接成功"
                return False, f"HTTP {resp.status_code}：{(resp.text or '')[:160]}"
        except httpx.HTTPError as e:
            return False, f"连接失败：{type(e).__name__}: {e}"

    async def _ping_embedding(self):
        from src.services.blossom_memory import EmbeddingClient
        cfg = self.config
        model = str(getattr(cfg, "BLOSSOM_MEMORY_EMBEDDING_MODEL", "") or "").strip()
        url = str(getattr(cfg, "BLOSSOM_MEMORY_EMBEDDING_API_URL", "") or "").strip()
        key = str(getattr(cfg, "BLOSSOM_MEMORY_EMBEDDING_API_KEY", "") or "").strip()
        if not model or not url:
            return False, "未配置向量模型/地址"
        c = EmbeddingClient(model, url, key, timeout=10)
        try:
            vec = await c.embed("ping")
            return True, f"连接成功：返回 {len(vec)} 维向量"
        except Exception as e:  # noqa: BLE001
            return False, f"连接失败：{type(e).__name__}: {str(e)[:160]}"
        finally:
            await c.close()

    async def _ping_reranker(self):
        from src.services.blossom_memory import OpenAICompatibleRerank
        cfg = self.config
        model = str(getattr(cfg, "BLOSSOM_MEMORY_RERANKER_MODEL", "") or "").strip()
        url = str(getattr(cfg, "BLOSSOM_MEMORY_RERANKER_API_URL", "") or "").strip()
        key = str(getattr(cfg, "BLOSSOM_MEMORY_RERANKER_API_KEY", "") or "").strip()
        if not model or not url:
            return False, "未配置重排模型/地址"
        c = OpenAICompatibleRerank(model, url, key, timeout=10)
        try:
            res = await c.rerank("ping", ["花璃"])
            return True, f"连接成功：重排返回 {len(res)} 条结果"
        except Exception as e:  # noqa: BLE001
            return False, f"连接失败：{type(e).__name__}: {str(e)[:160]}"
        finally:
            await c.close()

    async def _handle_panel_save(self, request: web.Request) -> web.Response:
        """配置保存：兼容旧版单键表单（key/value）；分组表单字段名=配置键。

        checkbox 采用 hidden false + checkbox true 同名字段模式：未勾选只提交
        false，勾选提交 false 和 true —— 服务端取同名最后一个值（未提交=false 语义）。
        """
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        cat = request.query.get("cat", "")
        if cat not in ConfigService.CATEGORY_ORDER:
            cat = ""
        _catq = f"&cat={quote(cat)}" if cat else ""
        form = await request.post()
        if "key" in form and "value" in form:
            key = str(form.get("key", ""))
            value = str(form.get("value", ""))
            ok, message = self.config_service.update(key, value)
            return web.HTTPFound(f"/panel?msg={quote(message)}&err={'1' if not ok else ''}{_catq}")
        updates: Dict[str, str] = {}
        for name in form.keys():
            if name not in self.config_service.SCHEMA:
                continue
            if hasattr(form, "getall"):
                vals = form.getall(name)
                updates[name] = (",".join(str(value) for value in vals)
                                 if name == "FILE_PARSE_FORMATS" else str(vals[-1]) if vals else "")
            else:
                updates[name] = str(form.get(name, ""))
        ok, message = self.config_service.update_many(updates)
        return web.HTTPFound(f"/panel?msg={quote(message)}&err={'1' if not ok else ''}{_catq}")

    async def _handle_api_file_parse_status(self, request):
        if not self._check_token(request):
            return web.json_response({"error": "未认证"}, status=401)
        return web.json_response(self._file_parser.status())

    async def _handle_api_file_parse(self, request):
        if not self._check_token(request):
            return web.json_response({"error": "未认证"}, status=401)
        result = await self._parse_uploaded_document(request, multipart=False)
        return web.json_response(result, status=200 if result["ok"] else _STATUS[result["code"]],
                                 headers={"Cache-Control": "no-store"})

    async def _handle_panel_file_preview(self, request):
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        result = await self._parse_uploaded_document(request, multipart=True)
        return web.Response(
            text=self._panel_page(msg=result.get("error", ""), err=not result["ok"],
                                  tab="files", file_result=result),
            content_type="text/html", charset="utf-8",
        )

    async def _parse_uploaded_document(self, request, *, multipart):
        status = self._file_parser.status()
        if not status["enabled"]:
            return file_parse_error("unavailable", "文件解析已关闭")
        limit = status["max_bytes"]
        try:
            if multipart:
                reader = await request.multipart()
                part = await reader.next()
                if part is None or part.name != "file" or not part.filename:
                    return file_parse_error("invalid_argument", "请选择文件")
                filename = part.filename
                # BodyPartReader requires a chunk longer than the multipart boundary.
                raw = await _read_bounded(lambda size: part.read_chunk(max(8192, size)), limit)
            else:
                if request.content_type != "application/octet-stream":
                    return file_parse_error("unsupported_format", "请以 application/octet-stream 提交文件")
                filename = request.query.get("filename", "")
                if not filename:
                    return file_parse_error("invalid_argument", "缺少 filename")
                if request.content_length is not None and request.content_length > limit:
                    return file_parse_error("file_too_large", f"文件超过 {limit} 字节")
                raw = await _read_bounded(request.content.read, limit)
        except (ValueError, AssertionError):
            return file_parse_error("invalid_argument", "上传格式错误或文件不完整")
        if raw is None:
            return file_parse_error("file_too_large", f"文件超过 {limit} 字节")
        return await self._file_parser.parse_document(filename, raw)
