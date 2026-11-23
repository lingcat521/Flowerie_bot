"""群消息分析共用配置与任务覆盖的解析。"""

from dataclasses import dataclass, field
from urllib.parse import urlsplit

_PREFIXES = ("MESSAGE_ANALYSIS", "MESSAGE_ANALYSIS_PREFERENCE", "MESSAGE_ANALYSIS_TOXIC")
ANALYSIS_API_KEYS = tuple(f"{prefix}_API_KEY" for prefix in _PREFIXES)


@dataclass(frozen=True)
class AnalysisEndpoint:
    url: str
    model: str
    key: str = field(repr=False)


def analysis_endpoint(config, task: str) -> AnalysisEndpoint | None:
    def value(key: str) -> str:
        return str(getattr(config, f"MESSAGE_ANALYSIS_{key}", "") or "").strip()

    prefix = task.upper()
    task_url = value(f"{prefix}_API_URL")
    url = task_url or value("API_URL")
    model = value(f"{prefix}_MODEL") or value("MODEL")
    key = value(f"{prefix}_API_KEY") or ("" if task_url else value("API_KEY"))
    return AnalysisEndpoint(url, model, key) if url and model else None


def is_analysis_url(value: str) -> bool:
    try:
        url = urlsplit(value)
        return bool(url.scheme in ("http", "https") and url.hostname and url.username is None
                    and (url.port is None or url.port > 0))
    except ValueError:
        return False


def validate_analysis_config(config) -> None:
    for prefix in _PREFIXES:
        name = f"{prefix}_API_URL"
        value = getattr(config, name, "").strip()
        if value and not is_analysis_url(value):
            raise ValueError(f"{name} 必须是有效的 HTTP(S) 地址")
    if not any(analysis_endpoint(config, task) for task in ("preference", "toxic")):
        raise ValueError("启用群消息 AI 分析时，至少为一个任务配置接口地址和模型名")
