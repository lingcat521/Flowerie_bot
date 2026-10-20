"""LLM 请求头构造（v2.7.0）：支持本机回环模型免密钥。

背景：自建模型服务（Ollama / llama.cpp / vLLM / LM Studio / Xinference 等）跑在
127.0.0.1 上时通常不校验 Authorization。此前 AI 客户端无条件拼 "Bearer <key>"，
空 key 会发出 "Bearer " 这种非法头，部分服务端会直接 401/400。

规则（只影响空 key 的情形，任何既有配置行为不变）：
- key 非空 → {"Authorization": "Bearer <key>"}（与历史完全一致）
- key 为空且 URL 是回环 → 不发 Authorization（服务端不校验，也不发脏头）
- key 为空且 URL 非回环 → 不发 Authorization（保持历史「空 Bearer」之外的新行为：
  让服务端返回它自己的鉴权错误，日志更可读；启动校验已拦住非回环空 key）
"""
from typing import Dict

from src.config import is_loopback_url


def auth_headers(api_key: str, content_type: str = "application/json") -> Dict[str, str]:
    """构造 LLM 请求头：有 key 就带 Bearer，本机回环无 key 时不发鉴权头。"""
    headers: Dict[str, str] = {}
    key = str(api_key or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def is_local_endpoint(api_url: str) -> bool:
    """URL 是否本机回环（供日志/诊断说明「本地模型不校验密钥」）。"""
    return is_loopback_url(api_url)

