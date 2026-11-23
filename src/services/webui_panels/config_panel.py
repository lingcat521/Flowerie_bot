"""Web UI 配置域处理器（无 JS 分组表单保存）。

从 WebUIServer 拆分（防上帝类）：配置保存走 ConfigService（.env + settings.db 双写）。
"""
from typing import Dict
from urllib.parse import quote

from aiohttp import web

from src.services.config_service import ConfigService
from src.services.file_parser import file_parse_error
from src.services.web_search import WebSearchService
from src.utils.message_analysis_config import ANALYSIS_API_KEYS

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
        """用已保存配置向指定模型发送 ping 请求。

        用当前已保存配置发起真实请求；结果经 msg 回显（零 JS：表单 POST → 重定向）。
        """
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        form = await request.post()
        target = str(form.get("target", "") or "")
        cat = "BlossomMemory" if target in ("embedding", "reranker") else "AI"
        if target == "search":
            cat = "Search"
        back = str(form.get("back", "") or "")
        result = await self._model_pings.ping({"target": target}, panel=True)
        entry = next(iter(result.get("results", {}).values()), result)
        ok, msg = entry["ok"], entry.get("message") or entry["error"]
        if target == "search" and not WebSearchService(self.config).paid_search_enabled():
            msg += "。付费搜索当前已关闭，此测试仅验证连接。"
        if back == "account":
            return web.HTTPFound(f"/panel?tab=account&msg={quote(msg)}&err={'1' if not ok else ''}")
        return web.HTTPFound(f"/panel?cat={cat}&msg={quote(msg)}&err={'1' if not ok else ''}")

    async def _handle_api_model_ping(self, request: web.Request) -> web.Response:
        if not self._check_token(request):
            return web.json_response({"error": "未认证"}, status=401)
        try:
            args = await request.json() if request.can_read_body else {}
        except ValueError:
            return web.json_response({"ok": False, "code": "invalid_argument", "error": "请求格式错误"}, status=400)
        result = await self._model_pings.ping(args)
        status = _STATUS.get(result.get("code"), 200)
        return web.json_response(result, status=status, headers={"Cache-Control": "no-store"})

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
        search_key = "SEARCH_DEEPSEEK_API_KEY"
        if search_key in updates:
            if form.get("clear_search_key") == "true":
                updates[search_key] = ""
            elif not updates[search_key].strip():
                del updates[search_key]
        for key in ANALYSIS_API_KEYS:
            if form.get(f"clear_{key}") == "true":
                updates[key] = ""
                updates[f"clear_{key}"] = "true"
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
