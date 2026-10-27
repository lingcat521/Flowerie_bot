"""AI 自主发 QQ空间动态（v2.12.0）：后台定时任务的服务层实现。

为什么独立成模块：MessageRouter 有 650 行硬门禁（tests/test_web_ui_persona_knowledge.py），
自主发动态属于"服务能力"而不是"消息编排"，放这里既能复用测试，也不撑爆路由器。

行为约束：
- AI_QZONE_ENABLED 必须开（registry.qzone_enabled()）；
- 每日条数由 AiToolRegistry（AI_QZONE_MAX_PER_DAY）兜底；
- 模型必须输出 JSON（content + images），否则不发——绝不让模型随手写段话就贴出去；
- 任何异常只记日志，不打断主循环。
"""
import asyncio
import json
from typing import Any, Callable, Dict, Optional

from src.utils.logging_setup import get_logger

logger = get_logger(__name__)


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """从模型输出里抓第一个 JSON 对象（容忍前后废话与代码块包裹）。"""
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                    except ValueError:
                        break
                    if isinstance(obj, dict):
                        return obj
                    break
        start = text.find("{", start + 1)
    return None


class QzoneAutoPoster:
    """定时让模型自己写一条说说 + 挑图并发布。"""

    def __init__(self, config, registry_provider: Callable[[], Any],
                 chat: Callable[..., Any], context_provider=None, persona_provider=None):
        self.config = config
        self._registry = registry_provider
        self._chat = chat
        self._context = context_provider
        self._persona = persona_provider

    def _hours(self) -> int:
        try:
            return max(1, int(getattr(self.config, "AI_QZONE_AUTO_INTERVAL_HOURS", 24) or 24))
        except (TypeError, ValueError):
            return 24

    async def loop(self) -> None:
        hours = self._hours()
        # 启动后先歇一会再发第一条（别抢启动阶段）
        await asyncio.sleep(min(300, hours * 3600))
        while True:
            try:
                await self.once()
            except Exception as e:  # noqa: BLE001 —— 自主任务失败不能打崩主循环
                logger.warning("qzone_auto_failed err=%s: %s", type(e).__name__, e)
            await asyncio.sleep(max(60, hours * 3600))

    async def once(self) -> Optional[Dict[str, Any]]:
        registry = self._registry() if callable(self._registry) else self._registry
        if registry is None or not registry.qzone_enabled():
            return None
        images = await registry.describe_pool()
        if not images:
            logger.info("qzone_auto_skip reason=empty_image_pool")
            return None
        image_lines = "\n".join("- %s：%s" % (it["id"], it["desc"]) for it in images[:8])
        group_id, ctx_text = 0, ""
        if self._context is not None:
            try:
                for gid in list(self._context.groups.keys())[:3]:
                    text = self._context.get_context_text(gid, max_messages=30)
                    if text:
                        group_id, ctx_text = gid, text
                        break
            except Exception:  # noqa: BLE001 —— 取素材失败就纯凭人格发
                group_id, ctx_text = 0, ""
        persona = "花璃"
        if self._persona is not None:
            try:
                persona = self._persona.resolve_persona_name(group_id) or "花璃"
            except Exception:  # noqa: BLE001
                persona = "花璃"
        prompt = (
            "你是一个真实的人，正在经营自己的 QQ空间。\n"
            "请写一条自然的说说（30~120 字，第一人称，不要提到 AI/模型/机器人）。\n"
            "下面是你相册里可用的图片和它们的内容：\n" + image_lines + "\n\n"
            "从里面挑 0~2 张和说说内容相配的图片（用图片名），然后只输出 JSON：\n"
            '{"content": "说说正文", "images": ["图片名"]}\n'
            "如果不需要配图，images 给空数组。"
        )
        if ctx_text:
            prompt += "\n最近的聊天内容（只作素材，不要复述）：\n" + str(ctx_text)[-800:]
        reply, _mem, denied = await self._chat(
            group_id, 0, user_message=prompt, context="", is_mentioned=False)
        if denied or not reply:
            logger.info("qzone_auto_skip reason=denied_or_empty")
            return None
        data = extract_json_object(str(reply))
        if not data or not str(data.get("content") or "").strip():
            logger.info("qzone_auto_skip reason=no_json content_len=%d", len(str(reply or "")))
            return None
        payload = {
            "content": str(data["content"]).strip()[:2000],
            "images": data.get("images") if isinstance(data.get("images"), list) else [],
        }
        result = await registry.call_tool("qzone_post", payload)
        logger.info("qzone_auto_result %s", (result or "")[:200],
                    extra={"event": "qzone_auto_post"})
        try:
            return json.loads(result) if isinstance(result, str) else None
        except ValueError:
            return None


def attach_auto_poster(router) -> "QzoneAutoPoster":
    """在路由器上挂自主发动态任务（组合根式注入，路由器只留一行调用）。"""
    poster = QzoneAutoPoster(
        router.config, lambda: getattr(router, "ai_tools", None), router.guarded_chat,
        context_provider=router.policy_engine, persona_provider=router.persona_manager)
    router._qzone_poster = poster
    router.task_manager.register("qzone_auto", poster.loop())
    return poster
