import asyncio
import base64
import json
import os
import zipfile
from io import BytesIO, StringIO
from itertools import islice
from typing import Dict, List, Optional, Tuple

import httpx

from src.config import DEFAULT_FILE_PARSE_FORMATS, FILE_PARSE_FORMAT_NAMES, Settings
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)

# 可选依赖
try:
    import pypdf as PyPDF2  # PyPDF2 已弃用，pypdf 为其官方继任者（API 兼容）
except ImportError:
    PyPDF2 = None
try:
    import docx
except ImportError:
    docx = None
try:
    import openpyxl
except ImportError:
    openpyxl = None
try:
    import csv
except ImportError:
    csv = None


PLUGIN_FILE_BYTES = 32 * 1024  # JSON-Lines transport has a 64 KiB line limit.
PLUGIN_TEXT_CHARS = 8000


def group_file_parse_enabled(config) -> bool:
    return (getattr(config, "FILE_PARSE_ENABLED", True)
            and getattr(config, "FILE_PARSE_GROUP_UPLOAD_ENABLED", True))


def file_parse_format(config, filename: str, *, fallback: bool) -> str:
    extension = filename.rpartition(".")[2].lower() if "." in filename else ""
    fmt = extension or "txt"
    if fmt not in FILE_PARSE_FORMAT_NAMES:
        if not fallback or not getattr(config, "FILE_PARSE_TEXT_FALLBACK", True):
            return ""
        fmt = "txt"
    allowed = getattr(config, "FILE_PARSE_FORMATS", DEFAULT_FILE_PARSE_FORMATS)
    return fmt if fmt in allowed.split(",") else ""


def file_parse_error(code, error):
    return {"ok": False, "code": code, "error": error}


def _office_size_ok(content: bytes) -> bool:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            return sum(entry.file_size for entry in archive.infolist()) <= 64 * 1024 * 1024
    except zipfile.BadZipFile:
        return False


class FileParser:
    def __init__(self, config: Settings):
        self.config = config
        self._parse_slots = asyncio.Semaphore(2)
        self._client: Optional[httpx.AsyncClient] = None  # 复用的 HTTP 客户端（懒创建）

    def _get_client(self, timeout: float = 30) -> httpx.AsyncClient:
        """复用一个 AsyncClient，避免每次请求都新建连接（省连接开销）"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=timeout)
        return self._client

    async def close(self) -> None:
        """优雅关闭：释放复用 HTTP 客户端（修复连接池泄漏）。"""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _cap(self, text: str) -> str:
        """P1-4 资源上限：提取文本统一截断到 MAX_FILE_TEXT_CHARS，防止超长内容烧 token。"""
        if not text:
            return ""
        limit = getattr(self.config, "MAX_FILE_TEXT_CHARS", 8000)
        if len(text) > limit:
            return text[:limit] + "\n...(内容过长已截断)"
        return text

    def status(self) -> dict:
        available = {"txt": True, "pdf": PyPDF2 is not None, "docx": docx is not None,
                     "xlsx": openpyxl is not None, "csv": csv is not None}
        enabled = getattr(self.config, "FILE_PARSE_FORMATS", DEFAULT_FILE_PARSE_FORMATS).split(",")
        max_bytes = getattr(self.config, "MAX_FILE_DOWNLOAD_BYTES", 2 * 1024 * 1024)
        max_chars = getattr(self.config, "MAX_FILE_TEXT_CHARS", 8000)
        return {
            "ok": True,
            "enabled": bool(getattr(self.config, "FILE_PARSE_ENABLED", True)),
            "group_upload_enabled": bool(group_file_parse_enabled(self.config)),
            "text_fallback": bool(getattr(self.config, "FILE_PARSE_TEXT_FALLBACK", True) and "txt" in enabled),
            "formats": {name: {"enabled": name in enabled, "available": ready}
                        for name, ready in available.items()},
            "max_bytes": max_bytes,
            "max_text_chars": max_chars,
            "max_pdf_pages": getattr(self.config, "MAX_PDF_PAGES", 100),
            "max_excel_cells": getattr(self.config, "MAX_EXCEL_CELLS", 50000),
            "max_csv_rows": getattr(self.config, "MAX_CSV_ROWS", 10000),
            "plugin_local_supported": os.open in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW"),
            "plugin_max_bytes": min(PLUGIN_FILE_BYTES, max_bytes),
            "plugin_max_text_chars": min(PLUGIN_TEXT_CHARS, max_chars),
        }

    async def parse_document(self, filename: str, content: bytes, *, plugin: bool = False) -> dict:
        status = self.status()
        if not status["enabled"]:
            return file_parse_error("unavailable", "文件解析已关闭")
        if (not isinstance(filename, str) or not filename.strip() or len(filename) > 255
                or "/" in filename or "\\" in filename
                or any(ord(ch) < 32 or 0xD800 <= ord(ch) <= 0xDFFF for ch in filename)):
            return file_parse_error("invalid_argument", "需要合法文件名（不含路径）")
        fmt = file_parse_format(self.config, filename, fallback=True)
        if not fmt:
            return file_parse_error("unsupported_format", "该文件格式未启用或不支持")
        if not status["formats"][fmt]["available"]:
            return file_parse_error("unavailable", "当前环境缺少该格式的解析依赖")
        limit = status["max_bytes"]
        if len(content) > limit:
            return file_parse_error("file_too_large", f"文件超过 {limit} 字节")
        if not content:
            return file_parse_error("invalid_argument", "文件为空")
        decoded = await self.decode_async(content, filename)
        if decoded is None:
            return file_parse_error("busy", "文件解析繁忙，请稍后重试")
        text, ok = decoded
        if not ok:
            return file_parse_error("parse_failed", "解析失败，请检查文件完整性及格式")
        cap = status["plugin_max_text_chars" if plugin else "max_text_chars"]
        return {"ok": True, "filename": filename, "format": fmt, "bytes": len(content),
                "text": text[:cap], "truncated": len(text) > cap}

    async def decode_async(self, content: bytes, filename: str) -> Optional[Tuple[str, bool]]:
        """Run a shared decoder slot. Cancellation does not free a slot until its worker exits."""
        if self._parse_slots.locked():
            return None
        await self._parse_slots.acquire()
        worker = asyncio.create_task(asyncio.to_thread(self.decode_bytes, content, filename))
        worker.add_done_callback(lambda _: self._parse_slots.release())
        return await asyncio.shield(worker)

    # ========== 通用：URL 下载（协议无关；Gate R 的 ResourceRef(URL) 走这里） ==========
    async def fetch_url_bytes(self, url: str, max_bytes: int = 2 * 1024 * 1024) -> Tuple[bytes, bool]:
        """下载 URL 内容（流式 + 字节上限；任何异常都返回 (b"", False)，不抛给调用方）。

        协议无关：Milky 的临时资源链接、以及未来的图片/文件直链都复用这里。
        """
        try:
            client = self._get_client(timeout=30)
            body = bytearray()
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    logger.error(f"Fetch url failed: HTTP {resp.status_code}")
                    return b"", False
                async for chunk in resp.aiter_bytes():
                    if len(body) + len(chunk) > max_bytes:
                        logger.error(f"Fetch url response exceeds limit ({max_bytes} bytes), aborted")
                        return b"", False
                    body.extend(chunk)
            return bytes(body), True
        except httpx.TimeoutException:
            logger.error("Fetch url timeout")
            return b"", False
        except httpx.HTTPError as e:
            logger.error(f"Fetch url HTTP error: {e}")
            return b"", False
        except Exception as e:
            logger.exception(f"Fetch url unexpected error: {e}")
            return b"", False

    # ========== 解码：字节 -> 文本（协议无关；Gate R 的第三步） ==========
    def decode_bytes(self, content_bytes: bytes, file_name: str) -> Tuple[str, bool]:
        """字节 -> 文本：**纯解码**，不关心资源从哪来、属于哪个协议。

        取数（协议差异）在 Adapter 层的 ResourceFetcher；本方法只做格式分派与安全预检
        （大小上限、xlsx zip 炸弹预检、PDF 页数/Excel 单元格/CSV 行数上限）。
        """
        try:
            max_bytes = getattr(self.config, "MAX_FILE_DOWNLOAD_BYTES", 2 * 1024 * 1024)
            if len(content_bytes) > max_bytes:
                logger.error(f"File decode bytes exceed limit: {len(content_bytes)} > {max_bytes}")
                return "", False
            if not getattr(self.config, "FILE_PARSE_ENABLED", True) or not file_parse_format(
                    self.config, file_name, fallback=True):
                return "", False
            ext = file_name.split('.')[-1].lower() if '.' in file_name else ''
            extracted_text = ""

            if ext == 'txt' or ext == '':
                for enc in ['utf-8', 'gbk']:
                    try:
                        extracted_text = content_bytes.decode(enc)
                        return self._cap(extracted_text), True
                    except UnicodeDecodeError:
                        continue
                return self._cap(content_bytes.decode('utf-8', errors='ignore')), True

            elif ext == 'pdf':
                if PyPDF2 is None:
                    return "", False
                try:
                    pdf_reader = PyPDF2.PdfReader(BytesIO(content_bytes))
                    pages = [page.extract_text() or "" for page in islice(pdf_reader.pages, self.config.MAX_PDF_PAGES)]
                    extracted_text = self._cap("\n".join(pages))
                    return extracted_text, True
                except Exception as e:
                    logger.error(f"PDF parse error: {e}")
                    return "", False

            elif ext == 'docx':
                if docx is None or not _office_size_ok(content_bytes):
                    return "", False
                try:
                    doc = docx.Document(BytesIO(content_bytes))
                    paragraphs = [p.text for p in doc.paragraphs]
                    extracted_text = self._cap("\n".join(paragraphs))
                    return extracted_text, True
                except Exception as e:
                    logger.error(f"DOCX parse error: {e}")
                    return "", False

            elif ext == 'xlsx':
                if openpyxl is None or not _office_size_ok(content_bytes):
                    return "", False
                try:
                    wb = openpyxl.load_workbook(BytesIO(content_bytes), read_only=True, data_only=True)
                    try:
                        rows = []
                        remaining = self.config.MAX_EXCEL_CELLS
                        for sheet in wb.worksheets:
                            rows.append(f"--- 工作表: {sheet.title} ---")
                            if sheet.max_column == 0:
                                continue
                            for row in sheet.iter_rows(max_col=min(sheet.max_column or remaining, remaining),
                                                       values_only=True):
                                if not row:
                                    continue
                                limited = row[:remaining]
                                rows.append("\t".join(str(cell) if cell is not None else "" for cell in limited))
                                remaining -= len(limited)
                                if remaining == 0:
                                    rows.append("...(已达到解析上限)")
                                    break
                            if remaining == 0:
                                break
                    finally:
                        wb.close()
                    extracted_text = self._cap("\n".join(rows))
                    return extracted_text, True
                except Exception as e:
                    logger.error(f"XLSX parse error: {e}")
                    return "", False

            elif ext == 'csv':
                if csv is None or StringIO is None:
                    return "", False
                try:
                    for enc in ['utf-8', 'gbk', 'gb2312']:
                        try:
                            text_content = content_bytes.decode(enc)
                            break
                        except UnicodeDecodeError:
                            continue
                    else:
                        text_content = content_bytes.decode('utf-8', errors='ignore')
                    reader = csv.reader(StringIO(text_content))
                    rows = [",".join(row) for row in islice(reader, self.config.MAX_CSV_ROWS)]
                    extracted_text = self._cap("\n".join(rows))
                    return extracted_text, True
                except Exception as e:
                    logger.error(f"CSV parse error: {e}")
                    return "", False
            else:
                # 尝试作为文本
                try:
                    extracted_text = self._cap(content_bytes.decode('utf-8'))
                    return extracted_text, True
                except Exception:
                    return "", False
        except Exception as e:
            logger.error(f"File decode error: {e}")
            return "", False

    # ========== [兼容保留] 文件接口的 JSON(base64) 响应 -> 文本 ==========
    def decode_base64_json_file_response(self, response_text: str, file_name: str) -> Tuple[str, bool]:
        """解析 {"retcode":0,"data":{"base64":"..."}} 形态的文件下载响应。

        **命名按行为、不按客户端**（任务书 §四/§十一：客户端名字不得进入 Services 层）——
        这种响应的来源客户端证据（NapCat `/get_file` 返回 base64 JSON）记在
        [../../../docs/reverse-engineering/onebot11/napcat.md](../../../docs/reverse-engineering/onebot11/napcat.md)
        与 Adapter 的 resource_fetcher 里；本方法只负责"严格解码"：
        非 JSON / retcode≠0 / 缺 base64 一律拒绝，绝不当成文件内容。
        旧名 `decode_napcat_file_response` 已按边界改名（仓库内无其它调用方）。
        """
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError:
            logger.error("NapCat get_file 响应不是合法 JSON，已拒绝")
            return "", False
        if not isinstance(data, dict) or data.get("retcode") != 0:
            return "", False
        payload = data.get("data")
        b64 = payload.get("base64", "") if isinstance(payload, dict) else ""
        if not b64:
            return "", False
        try:
            content_bytes = base64.b64decode(b64)
        except Exception as e:
            logger.error(f"base64 decode error: {e}")
            return "", False
        return self.decode_bytes(content_bytes, file_name)

    # ========== 提取合并转发消息 ==========
    async def extract_forward_messages(self, message_array: List[Dict]) -> Tuple[str, List[str], bool]:
        """提取合并转发消息中的文本与图片 URL。

        返回: (转发文本, 转发内的图片url列表, 是否有转发)
        图片 url 由调用方逐个交给视觉模型识图（让花璃看到转发里的每一张图）。
        """

        def extract_all_text(obj, sender="未知", prefix="", urls=None):
            results = []
            if isinstance(obj, dict):
                sender_val = obj.get("sender", {})
                if isinstance(sender_val, dict):
                    sender = sender_val.get("user_id", sender)
                elif isinstance(sender_val, (int, str)):
                    sender = str(sender_val)
                # 收集 image 段的 url（NapCat 合并转发里的图片同样带 url）
                if obj.get("type") == "image":
                    img_url = (obj.get("data") or {}).get("url", "")
                    if img_url and urls is not None and img_url not in urls:
                        urls.append(img_url)
                if "text" in obj and isinstance(obj["text"], str):
                    if obj["text"].strip():
                        results.append(f"[用户{sender}]：{obj['text']}")
                for key, value in obj.items():
                    if key == "text":
                        continue
                    results.extend(extract_all_text(value, sender, prefix + key + ".", urls))
            elif isinstance(obj, list):
                for idx, item in enumerate(obj):
                    results.extend(extract_all_text(item, sender, prefix + f"[{idx}]", urls))
            return results

        async def fetch_forward_messages(forward_id) -> Optional[List[Dict]]:
            """通过 NapCat HTTP API 拉取一次转发内容（带缓存去重，同一 id 只拉一次）。"""
            if forward_id in seen_forwards:
                logger.debug(f"Forward {forward_id} served from cache")
                return seen_forwards[forward_id]
            if state["fetches"] >= max_fetches:
                logger.warning(f"Forward fetch budget exceeded ({max_fetches}), stop fetching")
                return None
            state["fetches"] += 1
            try:
                client = self._get_client(timeout=10)
                resp = await client.get(
                    f"{self.config.HTTP_API_BASE}/get_forward_msg",
                    params={"message_id": forward_id}
                )
                if resp.status_code == 200:
                    result = resp.json()
                    if result.get("retcode") == 0:
                        messages = result.get("data", {}).get("messages")
                        seen_forwards[forward_id] = messages
                        return messages
            except Exception as e:
                logger.error(f"Get forward msg error: {e}")
            return None

        async def resolve_nested_forwards(node, depth: int = 0):
            """递归展开嵌套转发（带缓存 + 节点/消息/拉取预算，防套娃转发 DoS）。

            - MAX_FORWARD_DEPTH：展开深度上限
            - MAX_FORWARD_NODES：递归遍历节点总数上限
            - MAX_FORWARD_MESSAGES：展开后消息总数上限（超出截断）
            - MAX_FORWARD_FETCHES：/get_forward_msg 拉取次数上限
            - seen_forwards：同一 forward id 只拉一次（防重复请求）
            """
            state["nodes"] += 1
            if depth > max_depth or state["nodes"] > max_nodes:
                return node
            if isinstance(node, list):
                # 消息总数预算：超出直接截断
                if state["messages"] + len(node) > max_messages:
                    node = node[: max(0, max_messages - state["messages"])]
                    logger.warning(f"Forward message budget exceeded ({max_messages}), truncated")
                state["messages"] += len(node)
                return [await resolve_nested_forwards(item, depth) for item in node]
            if not isinstance(node, dict):
                return node
            if node.get("type") == "forward":
                data = node.get("data") or {}
                messages = data.get("messages")
                if not messages:
                    fid = data.get("id")
                    if fid:
                        fetched = await fetch_forward_messages(fid)
                        if fetched:
                            data["messages"] = fetched
                            messages = fetched
                if messages:
                    return await resolve_nested_forwards(messages, depth + 1)
                return node
            # 普通节点：递归展开所有字段（含 message 数组里的嵌套 forward）
            return {key: await resolve_nested_forwards(value, depth) for key, value in node.items()}

        # 转发预算状态（一次 extract_forward_messages 调用共享）
        max_depth = getattr(self.config, "MAX_FORWARD_DEPTH", 5)
        max_messages = getattr(self.config, "MAX_FORWARD_MESSAGES", 100)
        max_nodes = getattr(self.config, "MAX_FORWARD_NODES", 500)
        max_fetches = getattr(self.config, "MAX_FORWARD_FETCHES", 20)
        state = {"nodes": 0, "messages": 0, "fetches": 0}
        seen_forwards: Dict[str, List[Dict]] = {}

        if not isinstance(message_array, list):
            logger.warning("message_array 不是列表，跳过转发解析")
            return "", [], False

        for msg in message_array:
            if msg.get("type") == "forward":
                forward_data = msg.get("data", {})
                messages = forward_data.get("messages")
                if not messages:
                    messages = await fetch_forward_messages(forward_data.get("id"))
                    if not messages:
                        continue
                # 先展开嵌套转发，再一次性提取文本与图片 url
                resolved = await resolve_nested_forwards(messages)
                image_urls: List[str] = []
                text_lines = extract_all_text(resolved, urls=image_urls)
                if text_lines or image_urls:
                    return "\n".join(text_lines), image_urls, True
                return "", image_urls, False
        return "", [], False

    # ========== 提取 JSON 卡片内容 ==========
    def extract_json_card_content(self, message_array: List[Dict]) -> Tuple[str, bool]:
        """递归提取 JSON 卡片中的所有文本"""
        if not isinstance(message_array, list):
            return "", False

        _MAX_CARD_DEPTH = 20  # 防恶意深层嵌套卡片导致递归过深

        def collect_strings(obj, collected: set, depth: int = 0):
            if depth > _MAX_CARD_DEPTH:
                return
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key in ['url', 'jumpUrl', 'preview', 'icon', 'appid', 'uin', 'scene', 'token', 'ctime', 'width', 'height', 'forward', 'autoSize']:
                        continue
                    collect_strings(value, collected, depth + 1)
            elif isinstance(obj, list):
                for item in obj:
                    collect_strings(item, collected, depth + 1)
            elif isinstance(obj, str):
                if len(obj.strip()) > 1 and not obj.strip().isdigit():
                    collected.add(obj.strip())

        for msg in message_array:
            if msg.get("type") != "json":
                continue
            data = msg.get("data", {})
            json_str = data.get("data") or data.get("content") or data.get("text")
            if isinstance(json_str, dict):
                card_data = json_str
            elif isinstance(json_str, str):
                try:
                    card_data = json.loads(json_str)
                except json.JSONDecodeError:
                    continue
            else:
                if isinstance(data, dict):
                    card_data = data
                else:
                    continue
            collected = set()
            collect_strings(card_data, collected)
            if collected:
                card_text = "；".join(list(collected))
                return f"卡片内容：{card_text}", True
        return "", False

    # ========== 提取 @ 和纯文本 ==========
    def extract_mention_and_text(self, message_array: List[Dict], bot_qq: int) -> Tuple[str, bool]:
        """提取纯文本和是否@机器人"""
        if not isinstance(message_array, list):
            return "", False
        self_id = str(bot_qq)
        is_mentioned = False
        text_parts = []
        for msg in message_array:
            if msg.get("type") == "at":
                qq = str(msg.get("data", {}).get("qq", ""))
                if qq == self_id:
                    is_mentioned = True
            elif msg.get("type") == "text":
                text_parts.append(msg.get("data", {}).get("text", ""))
        return "".join(text_parts).strip(), is_mentioned
