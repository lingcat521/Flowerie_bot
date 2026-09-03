"""Web UI 配置域处理器（无 JS 分组表单保存）。

从 WebUIServer 拆分（防上帝类）：配置保存走 ConfigService（.env + settings.db 双写）。
"""
from typing import Dict
from urllib.parse import quote

from aiohttp import web

from src.services.config_service import ConfigService


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
                updates[name] = str(vals[-1]) if vals else ""
            else:
                updates[name] = str(form.get(name, ""))
        ok, message = self.config_service.update_many(updates)
        return web.HTTPFound(f"/panel?msg={quote(message)}&err={'1' if not ok else ''}{_catq}")
