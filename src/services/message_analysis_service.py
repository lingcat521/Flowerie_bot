"""群消息分析配置的读写（从 ConfigService 抽出，避免上帝类）。

只负责 MESSAGE_ANALYSIS_* 一组键：读取脱敏视图、校验后走统一持久化。
调用方仍通过 ConfigService.message_analysis_get/update 的薄委托进入。
"""
import json
import sqlite3
from types import SimpleNamespace
from typing import Any, Dict

from loguru import logger

from src.services.config_schema import SCHEMA
from src.utils.message_analysis_config import ANALYSIS_API_KEYS, validate_analysis_config

_ANALYSIS_FIELDS = {
    key: ctype for key, (_, ctype, *_) in SCHEMA.items()
    if key.startswith("MESSAGE_ANALYSIS_") or key in {"TOXIC_GROUP_IDS", "TOXIC_WARNING_COOLDOWN"}
}


class MessageAnalysisService:
    """基于 ConfigService 的校验/持久化能力实现群消息分析配置的读写。"""

    def __init__(self, config_service):
        self._svc = config_service
        self.config = config_service.config
        self._validate = config_service._validate
        self._coerce = config_service._coerce
        self._commit = config_service._commit

    def get(self) -> Dict[str, Any]:
        """读取运行中的配置，密钥仅返回是否已设置。"""
        values = {key: getattr(self.config, key) for key in _ANALYSIS_FIELDS}
        return {
            "ok": True,
            "values": {key: list(value) if isinstance(value, list) else value
                       for key, value in values.items() if key not in ANALYSIS_API_KEYS},
            "secrets_configured": {key: bool(values[key].strip()) for key in ANALYSIS_API_KEYS},
        }

    def update(self, values: Any) -> Dict[str, Any]:
        """校验整个补丁，再走统一的持久化和热更新路径。"""
        if not isinstance(values, dict) or not values:
            return {"ok": False, "error": "values 必须是非空对象"}
        current = {key: getattr(self.config, key) for key in _ANALYSIS_FIELDS}
        proposed = current.copy()
        validated: Dict[str, str] = {}
        ctypes: Dict[str, str] = {}
        for key, value in values.items():
            ctype = _ANALYSIS_FIELDS.get(key)
            if ctype is None:
                return {"ok": False, "error": "包含不受支持的群消息分析配置项"}
            if ctype == "list-int" and isinstance(value, list):
                if any(type(item) is not int or item <= 0 for item in value):
                    return {"ok": False, "error": f"{key} 必须是正整数数组"}
                raw = json.dumps(value)
            elif ctype == "int" and type(value) is int:
                raw = str(value)
            elif ctype in ("str", "secret") and isinstance(value, str):
                # 避免 dotenv 重启时插值，以及 API 密钥内的非法 HTTP 头字符。
                if "${" in value or (value and not value.isprintable()) or (
                        ctype == "secret" and not value.isascii()):
                    return {"ok": False, "error": f"{key} 含有不支持的字符"}
                raw = value
            elif ctype == "secret" and value is None:
                raw = ""
            else:
                return {"ok": False, "error": f"{key} 的类型不正确"}
            clean = self._validate(key, ctype, raw)
            if clean is None or (ctype == "secret" and value is not None and not clean):
                return {"ok": False, "error": f"{key} 值不合法（清除密钥请传 null）"
                        if ctype == "secret" else f"{key} 值不合法"}
            validated[key] = clean
            ctypes[key] = ctype
            proposed[key] = self._coerce(ctype, clean)

        if proposed["MESSAGE_ANALYSIS_GROUP_IDS"]:
            try:
                validate_analysis_config(SimpleNamespace(**proposed))
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
        # 未启用的模型也需要保护，之后启用时会沿用这里保存的配置。
        shared_url = "MESSAGE_ANALYSIS_API_URL"
        for key in ANALYSIS_API_KEYS:
            url_key = key.removesuffix("_KEY") + "_URL"
            old_url = current[url_key].strip() or current[shared_url].strip()
            new_url = proposed[url_key].strip() or proposed[shared_url].strip()
            new_key = proposed[key].strip()
            if new_url and new_url != old_url and new_key and new_key == current[key].strip():
                return {"ok": False, "error": f"切换接口地址时，请同时更换或清除 {key}"}

        try:
            self._commit(validated, ctypes)
        except (OSError, sqlite3.Error):
            logger.error("message_analysis_config_write_failed keys=%s", sorted(validated))
            return {"ok": False, "code": "write_failed", "error": "保存群消息分析配置失败"}
        logger.info("message_analysis_config_updated keys=%s", sorted(validated))
        return {"ok": True, "saved": sorted(validated)}
