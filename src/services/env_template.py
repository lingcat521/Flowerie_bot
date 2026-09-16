"""首次启动释放的 .env 模板：以 config_schema.SCHEMA 为单源（分组 + 中文说明）。

设计意图
--------
构建产物不含 .env，首次运行由 main.ensure_env_template 释放一份完整模板。
本模块让这份模板与 **Web UI 配置页同源**（同一份 SCHEMA / 分类常量）——
两处说明永不漂移，也不再依赖 pydantic Field.description（大多为空）。

单独成模块的原因：main.py 是入口，import 它会拉起 aiohttp/pydantic 等重依赖；
模板渲染逻辑需要能被单元测试直接导入（零第三方依赖）。
"""
import json
from typing import Any, Dict, Iterable, Mapping, Optional

# 必填项占位值（首次释放的模板里给出可替换的示例值）
REQUIRED_PLACEHOLDERS: Dict[str, str] = {
    "DEEPSEEK_API_KEY": "sk-your-key-here",
    "BOT_QQ": "10001",
}

_HEADER = (
    "# Flowerie .env 完整配置模板（首次启动自动生成；编辑后重启生效）",
    "# 分组与说明与 Web UI 配置页同源（config_schema.SCHEMA），不会漂移",
    "# ⚠️ 必填项当前为占位值，请替换为真实值后再启动",
    "# Web UI 保存的配置会写回本文件（原子更新，保留注释与原有变量）",
)


def format_value(value: Any) -> str:
    """把配置值渲染成 .env 里的字面量（bool 用 true/false，list/dict 用 JSON）。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def render_env_template(schema: Mapping[str, tuple],
                        category_order: Iterable[str],
                        category_labels: Mapping[str, str],
                        defaults: Mapping[str, Any],
                        placeholders: Optional[Mapping[str, str]] = None) -> str:
    """按 SCHEMA 渲染带分组/说明注释的 .env 模板（纯函数，便于测试）。

    schema 条目格式与 config_schema.SCHEMA 一致：
        key -> (分类, 类型, 是否敏感, 是否热更新, 说明)
    """
    placeholders = dict(REQUIRED_PLACEHOLDERS if placeholders is None else placeholders)
    lines = list(_HEADER)
    lines.append("")
    rendered = set()

    for cat in category_order:
        keys = [k for k, meta in schema.items() if meta[0] == cat and k not in rendered]
        if not keys:
            continue
        lines.append("# ========== %s ==========" % category_labels.get(cat, cat))
        for key in keys:
            meta = schema[key]
            type_name, is_secret, hot_reload, desc = meta[1], meta[2], meta[3], meta[4]
            raw = placeholders[key] if key in placeholders else defaults.get(key, "")
            marks = []
            if key in placeholders:
                marks.append("⚠️ 必填")
            if is_secret:
                marks.append("密钥")
            if not hot_reload:
                marks.append("需重启")
            if desc:
                note = str(desc).replace("\n", " ").strip()
                if note:
                    lines.append("# %s" % note)
            suffix = ("  # " + " · ".join(marks)) if marks else ""
            lines.append("%s=%s%s" % (key, format_value(raw), suffix))
            rendered.add(key)
        lines.append("")

    # SCHEMA 未覆盖但 Settings 里存在的字段：追加到末尾，保证「全量导出」不退化
    rest = [k for k in defaults if k not in rendered]
    if rest:
        lines.append("# ========== 其它（Settings 模型里的常量，通常无需修改） ==========")
        for key in rest:
            lines.append("%s=%s" % (key, format_value(defaults.get(key, ""))))
        lines.append("")

    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def collect_defaults(settings_cls) -> Dict[str, Any]:
    """从 Settings 模型收集默认值（必填/无默认 → 空串，由 placeholders 覆盖）。"""
    from pydantic_core import PydanticUndefined

    defaults: Dict[str, Any] = {}
    for name, field in settings_cls.model_fields.items():
        if name.startswith("_"):
            continue
        default = field.default
        if field.is_required() or default is PydanticUndefined:
            defaults[name] = ""
        else:
            defaults[name] = default
    return defaults


def default_env_text(settings_cls) -> str:
    """生成首次启动释放的 .env 全文（SCHEMA 分组 + 中文说明 + 默认值）。"""
    from src.services.config_schema import SCHEMA
    from src.services.webui_render.category_constants import CATEGORY_LABELS, CATEGORY_ORDER

    return render_env_template(SCHEMA, CATEGORY_ORDER, CATEGORY_LABELS,
                               collect_defaults(settings_cls))

