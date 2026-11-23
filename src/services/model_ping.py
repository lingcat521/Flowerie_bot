"""Probe the saved model endpoints using only fixed, minimal test payloads."""

import asyncio
import json
import time
from dataclasses import dataclass, field

import httpx

from src.config import is_loopback_url
from src.core.sanitizer import validate_mcp_server_url
from src.services.web_search import WebSearchService
from src.utils.llm_headers import auth_headers
from src.utils.message_analysis_config import analysis_endpoint, is_analysis_url

MODEL_LABELS = {
    "chat": "聊天",
    "vision": "视觉识图",
    "toxic": "引战检测（关键词预筛）",
    "analysis_preference": "喜好提取",
    "analysis_toxic": "语义引战检测",
    "embedding": "向量模型",
    "reranker": "重排模型",
    "search": "DeepSeek 搜索",
}
_MAX_RESPONSE_BYTES = 512 * 1024
_API_TIMEOUT = 8


@dataclass(frozen=True)
class _Probe:
    kind: str
    url: str
    model: str
    key: str = field(repr=False)

    def request(self) -> tuple[dict, dict]:
        if self.kind == "embedding":
            payload = {"input": "ping"}
        elif self.kind == "reranker":
            payload = {"query": "ping", "documents": ["花璃"], "top_n": 1}
        else:
            payload = {"messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}
        if self.kind == "search":
            payload.update(max_tokens=16, thinking={"type": "disabled"})
            headers = {"x-api-key": self.key, "anthropic-version": "2023-06-01"}
        else:
            headers = auth_headers(self.key)
        return {"model": self.model, **payload}, headers

    def describe_response(self, body: bytearray) -> str:
        """Validate the endpoint's response shape and describe the result for the UI."""
        data = json.loads(body)
        if self.kind == "search":
            if not isinstance(data["content"], list):
                raise ValueError
            return "连接成功（未消耗搜索额度）"
        if self.kind == "embedding":
            vector = data["data"][0]["embedding"]
            if not isinstance(vector, list) or not vector:
                raise ValueError
            for number in vector:
                float(number)
            return f"连接成功：返回 {len(vector)} 维向量"
        if self.kind == "reranker":
            results = data["results"]
            if not isinstance(results, list) or not results:
                raise ValueError
            for row in results:
                int(row["index"])
                float(row["relevance_score"])
            return f"连接成功：重排返回 {len(results)} 条结果"
        if not isinstance(data["choices"][0]["message"], dict):
            raise ValueError
        return "模型连接成功（已响应 ping）"


class ModelPingService:
    def __init__(self, config):
        self.config = config
        self._active = False

    def _setting(self, key: str) -> str:
        return str(getattr(self.config, key, "") or "").strip()

    def _resolve(self, target: str) -> tuple[_Probe | None, str]:
        if target == "search":
            search = WebSearchService(self.config)
            base, model, key, _ = search._deepseek_search_conf()
            if not key.strip():
                return None, "未配置搜索 Key（自动搜索使用免费引擎）"
            if not search.deepseek_native_ready():
                return None, "搜索 Key 仍是模板值，请填真实 Key"
            return _Probe("search", base + "/messages", model, key.strip()), ""
        if target.startswith("analysis_"):
            endpoint = analysis_endpoint(self.config, target.removeprefix("analysis_"))
            if endpoint is None:
                return None, f"{MODEL_LABELS[target]}模型未配置接口地址或模型名"
            return _Probe("chat", endpoint.url, endpoint.model, endpoint.key), ""

        prefix = {
            "chat": "DEEPSEEK", "vision": "VISION", "toxic": "TOXIC",
            "embedding": "BLOSSOM_MEMORY_EMBEDDING", "reranker": "BLOSSOM_MEMORY_RERANKER",
        }[target]
        url, model, key = (self._setting(f"{prefix}_{name}") for name in ("API_URL", "MODEL", "API_KEY"))
        if target in ("vision", "toxic"):
            # 生产路径按字段回退，独立模型名可以共用聊天地址和密钥。
            url = url or self._setting("DEEPSEEK_API_URL")
            key = key or self._setting("DEEPSEEK_API_KEY")
            model = model or ("deepseek-flash" if target == "vision" else self._setting("DEEPSEEK_MODEL"))
        if not url or not model:
            return None, "未配置模型或接口地址"
        if target == "chat" and not key and not (
                getattr(self.config, "AI_ALLOW_LOOPBACK_NO_KEY", True) and is_loopback_url(url)):
            return None, "未配置 DEEPSEEK_API_KEY"
        return _Probe(target if target in ("embedding", "reranker") else "chat", url, model, key), ""

    async def ping(self, args: dict, *, panel: bool = False) -> dict:
        """Run one saved target or all eight targets, sharing identical probes within a batch."""
        if not isinstance(args, dict) or args.keys() - {"target"}:
            return {"ok": False, "code": "invalid_argument", "error": "只接受 target 参数"}
        target = args.get("target", "all")
        if target == "deepseek":
            target = "chat"
        if not isinstance(target, str) or (target not in MODEL_LABELS and (panel or target != "all")):
            return {"ok": False, "code": "invalid_argument", "error": "未知测试目标"}
        if self._active:
            return {"ok": False, "code": "busy", "error": "已有模型探测正在运行"}
        self._active = True
        try:
            targets = MODEL_LABELS if target == "all" else (target,)
            plan = {name: self._resolve(name) for name in targets}
            probes = list(dict.fromkeys(probe for probe, _ in plan.values() if probe is not None))
            outcomes = {}
            if probes:
                timeout = (20 if target == "search" else 10) if panel else _API_TIMEOUT
                async with httpx.AsyncClient(timeout=timeout) as client:
                    outcomes = dict(zip(probes, await asyncio.gather(
                        *(self._probe(client, probe, timeout) for probe in probes)), strict=True))
            results = {}
            for name, (probe, reason) in plan.items():
                if probe is None:
                    results[name] = {"ok": False, "status": "unconfigured", "message": reason}
                    continue
                result = outcomes[probe].copy()
                if name.startswith("analysis_") and result["status"] != "invalid_response":
                    result["message"] = MODEL_LABELS[name] + result["message"]
                results[name] = result
            ok = any(item["ok"] for item in results.values()) and all(
                item["ok"] or item["status"] == "unconfigured" for item in results.values())
            return {"ok": ok, "results": results}
        finally:
            self._active = False

    @staticmethod
    async def _probe(client: httpx.AsyncClient, probe: _Probe, timeout: int) -> dict:
        start = time.monotonic()

        def result(status: str, message: str, **details) -> dict:
            return {"ok": status == "reachable", "status": status, "model": probe.model, "message": message,
                    "latency_ms": round((time.monotonic() - start) * 1000), **details}

        if not is_analysis_url(probe.url) or (
                probe.kind in ("embedding", "reranker") and not validate_mcp_server_url(probe.url)[0]):
            return result("invalid_configuration", "模型接口地址无效")
        try:
            payload, headers = probe.request()
            async with asyncio.timeout(timeout), client.stream(
                    "POST", probe.url, headers=headers, json=payload, follow_redirects=False) as response:
                code = response.status_code
                if code != 200:
                    hint = {401: "：Key 无效或尚未开通 Anthropic 兼容端点",
                            404: "：端点路径有误（应以 /anthropic/v1 结尾）"}.get(code, "")
                    return result("http_error", f"模型连接失败（HTTP {code}{hint if probe.kind == 'search' else ''}）",
                                  http_status=code)
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
                        return result("invalid_response", "模型响应超过大小限制")
                    body.extend(chunk)
                return result("reachable", probe.describe_response(body))
        except (TimeoutError, httpx.TimeoutException):
            return result("timeout", f"模型连接超时（{timeout} 秒）")
        except (httpx.HTTPError, httpx.InvalidURL, UnicodeError):
            return result("connection_error", "模型连接失败")
        except (ValueError, KeyError, IndexError, TypeError, OverflowError, RecursionError):
            expected = {"chat": "Chat Completions", "embedding": "向量", "reranker": "重排",
                        "search": "Anthropic Messages"}[probe.kind]
            return result("invalid_response", f"模型返回的格式不是有效的 {expected} 响应")
