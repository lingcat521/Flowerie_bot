"""Web UI「自动化」域处理器（独立 tab）：AI 内置工具层 + QQ空间配套配置。

把原散落在 Qzone/Admin/AI 分类的 15 个键集中到此（v2.16.0）：
配置页不再展示这些键（CATEGORY_ORDER 不含 Automation），统一在本 tab 编辑。
保存复用 ConfigService 双写（.env + settings.db + 热更新），同插件页模式。
"""
from typing import Dict
from urllib.parse import quote

from aiohttp import web

from src.services.webui_render.config_panel import _render_config_row
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)

#: 本页管理的键（与 config_schema.py 的 Automation 分类同源，显式声明便于校验）
AUTOMATION_KEYS = (
    "AI_QZONE_ENABLED", "AI_QZONE_MAX_PER_DAY",
    "AI_QZONE_AUTO_ENABLED", "AI_QZONE_AUTO_INTERVAL_HOURS",
    "AI_ADMIN_ENABLED", "AI_MEMORY_ENABLED", "AI_TOOL_PROMPT",
    "QZONE_IMAGE_DIR", "QZONE_IMAGE_INDEX_PATH",
    "QZONE_IMAGE_MAX", "QZONE_IMAGE_DESCRIBE_LIMIT",
    "QZONE_ENABLED", "QZONE_DEFAULT_UGC_RIGHT",
    "QZONE_HISTORY_PATH", "QZONE_MAX_HISTORY",
)

#: 分组展示（兼容老导入名；键与 AUTOMATION_KEYS 一致）
AUTOMATION_KEYS_LIST = list(AUTOMATION_KEYS)


class AutomationPanelMixin:
    """「自动化」tab：AI 自主行为开关 + QQ空间配套参数，单表单保存。"""

    def _render_automation_page(self, msg: str = "", err: bool = False) -> str:
        configs = [c for c in self.config_service.list_configs()
                   if c["key"] in AUTOMATION_KEYS]
        # 按声明顺序排（表单字段顺序稳定）
        order = {k: i for i, k in enumerate(AUTOMATION_KEYS)}
        configs.sort(key=lambda c: order.get(c["key"], 999))
        rows = "".join(_render_config_row(c) for c in configs)
        hint = (
            '<div class="hint">AI 内置工具默认全部关闭——打开对应开关后，模型才能在对话中'
            '自主调用 QQ空间 / 群管理 / 记忆 / 搜索工具。保存即刻生效（写入 .env）。</div>')
        return (
            "<h2>自动化（AI 内置工具层）</h2>" + hint
            + f'<form method="post" action="/panel/automation/save">'
            + rows
            + '<div class="group-actions"><button type="submit" class="btn">保存自动化配置</button></div>'
            + "</form>")

    async def _handle_panel_automation_save(self, request: web.Request) -> web.Response:
        """保存自动化配置（复用 ConfigService.update_many：校验 + 双写 + 热更新）。"""
        if not self._check_token(request):
            return web.HTTPFound("/panel")
        form = await request.post()
        updates: Dict[str, str] = {}
        for name in form.keys():
            if name not in AUTOMATION_KEYS:
                continue
            if hasattr(form, "getall"):
                vals = form.getall(name)
                updates[name] = str(vals[-1]) if vals else ""
            else:
                updates[name] = str(form.get(name, ""))
        ok, message = self.config_service.update_many(updates)
        return web.HTTPFound(f"/panel?tab=automation&msg={quote(message)}&err={'1' if not ok else ''}")
