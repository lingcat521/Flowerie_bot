#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.adapters import make_adapters
from src.config import load_config, validate_config
from src.core.message_router import MessageRouter
from src.core.policy_engine import PolicyEngine
from src.core.websocket_server import WebSocketServer
from src.repositories.meme_knowledge_repository import MemeKnowledgeRepository
from src.repositories.settings_repository import SettingsRepository
from src.repositories.sticker_repository import StickerRepository
from src.services.ai_client import AIClient
from src.services.blossom_memory import BlossomMemoryManager
from src.services.config_service import ConfigService
from src.services.file_parser import FileParser
from src.services.mcp_tool_manager import McpToolManager
from src.services.meme_knowledge_manager import MemeKnowledgeManager
from src.services.meme_summary import MemeSummaryService
from src.services.memory_manager import MemoryManager
from src.services.persona_manager import PersonaManager
from src.services.prompt_manager import PromptManager
from src.services.sender import Sender
from src.services.sticker_manager import StickerManager
from src.services.web_ui import WebUIServer
from src.utils.logging_setup import get_logger, init_logging
from src.utils.metrics import registry

logger = get_logger(__name__)



async def main():
    config = load_config()
    # P2-2：启动阶段先加载持久化配置（settings.db）覆盖 .env/代码默认，
    # 使"Persistent Config > Environment > Code Default"对**运行时组件**真正生效
    # （而非仅 UI 显示层）。合并后再做启动校验，保证最终运行配置合法。
    settings_repo = SettingsRepository(config.SETTINGS_DB_PATH)
    # P2-2：启动阶段先加载持久化配置（settings.db）覆盖 .env/代码默认，
    # 使"Persistent Config > Environment > Code Default"对**运行时组件**真正生效
    # （而非仅 UI 显示层）。合并后再做启动校验，保证最终运行配置合法。
    # env_path：Web UI 保存的配置会真正写入项目根 .env（原子更新，保留注释），
    # 重启后由 pydantic-settings 读取；settings.db 保持同步（既有优先级链不变）。
    config_service = ConfigService(config, settings_repo, env_path=ConfigService.default_env_path())
    config_service.apply_persisted()
    # 启动阶段即校验配置：类型错误/必填缺失直接报错退出
    validate_config(config)
    init_logging(level=config.LOG_LEVEL, fmt=config.LOG_FORMAT)

    logger.info("花璃启动中...", extra={"event": "startup"})

    # ---- 存储后端选择（默认 SQLite；STORAGE_BACKEND=postgres 走 PG 平行实现）----
    if str(getattr(config, "STORAGE_BACKEND", "sqlite") or "sqlite").lower() == "postgres":
        from src.repositories.postgres_memory_repository import PostgresMemoryRepository
        memory_repo = PostgresMemoryRepository(config.DATABASE_URL)
    else:
        memory_repo = None
    memory_manager = MemoryManager(config.MEMORY_PATH, config.MEMORY_TTL_DAYS, config.AUDIT_LOG_PATH, config.MODEL_MEMORY_TTL_DAYS, memory_enabled=config.MEMORY_ENABLED,
                                   repository=memory_repo)

    # ---- 花语记忆（BlossomMemory）：默认 OFF——不初始化任何模型资源（embedding/reranker/向量库）
    blossom_memory = None
    if config.BLOSSOM_MEMORY_ENABLED:
        from src.services.blossom_memory import (
            OpenAICompatibleEmbedding,
            OpenAICompatibleRerank,
        )
        embedding = reranker = None
        if config.BLOSSOM_MEMORY_EMBEDDING_ENABLED:
            embedding = OpenAICompatibleEmbedding(
                config.BLOSSOM_MEMORY_EMBEDDING_MODEL,
                config.BLOSSOM_MEMORY_EMBEDDING_API_URL,
                config.BLOSSOM_MEMORY_EMBEDDING_API_KEY,
                dimension=config.BLOSSOM_MEMORY_VECTOR_DIMENSION)
        if config.BLOSSOM_MEMORY_RERANKER_ENABLED:
            reranker = OpenAICompatibleRerank(
                config.BLOSSOM_MEMORY_RERANKER_MODEL,
                config.BLOSSOM_MEMORY_RERANKER_API_URL,
                config.BLOSSOM_MEMORY_RERANKER_API_KEY,
                top_k=config.BLOSSOM_MEMORY_RERANK_TOP_K)
        blossom_memory = BlossomMemoryManager(config, embedding=embedding, reranker=reranker)
    prompt_manager = PromptManager(settings_repo, max_length=config.MAX_CUSTOM_PROMPT_LENGTH)

    # 优雅管理异步资源（HTTP session / AI 客户端）
    async with AIClient(config, memory_manager) as ai_client, Sender(config) as sender:
        # ---- 消息边界组合根（Phase 4）：解析器 + 现有 Sender（共享实例，不重复构造）----
        # 依赖链: Settings(config) → Sender(config) → make_adapters(BOT_QQ, sender)
        #         → OneBotEventParser + Adapters{parser, sender}
        # 契约校验：sender 不满足 MessageSender 契约 → 启动期即失败（Behavior 不变）
        adapters = make_adapters(config.BOT_QQ, sender)
        if adapters.sender is not sender:
            raise RuntimeError("adapters 必须复用现有的 sender 实例")
        sticker_repo = StickerRepository(config.STICKER_DB_PATH)
        sticker_manager = StickerManager(config, sticker_repo, ai_client)
        tool_manager = McpToolManager(config)
        # 人格系统（内置预设自动播种；Group > Global > 内置默认）
        persona_manager = PersonaManager(
            settings_repo,
            default_persona_id=getattr(config, "PERSONA_DEFAULT", "flowerie"),
            max_system_prompt_length=getattr(config, "MAX_PERSONA_PROMPT_LENGTH", 8000),
            config=config,  # 动态读取 PERSONA_DEFAULT：Web UI 热更新立即生效
        )
        # 群聊梗知识（独立库，按群隔离）+ 每日总结任务
        meme_repo = MemeKnowledgeRepository(config.MEME_KNOWLEDGE_DB_PATH)
        meme_manager = MemeKnowledgeManager(
            meme_repo,
            max_memes_per_group=getattr(config, "MAX_GROUP_MEMES", 500),
            buffer_per_group=getattr(config, "MEME_BUFFER_PER_GROUP", 1000),
        )
        meme_summary = MemeSummaryService(
            config,
            ai_client,
            meme_manager,
            tool_manager=tool_manager,
            min_messages=getattr(config, "MEME_MIN_MESSAGES_PER_SUMMARY", 10),
            max_groups_per_run=getattr(config, "MEME_MAX_GROUPS_PER_RUN", 20),
            max_candidates=getattr(config, "MEME_MAX_SUMMARY_CANDIDATES", 20),
            interval_hours=getattr(config, "MEME_SUMMARY_INTERVAL_HOURS", 24),
            budget=None,  # 与 MessageRouter 共享的预算实例在 policy_engine 创建后注入
        )
        web_ui = None
        # 插件系统（受控插件运行时）：子进程隔离 + 权限强制 + 安全安装；
        # 事件由 MessageRouter 投递，Web UI 管理页负责安装/启用（管理员操作）
        from src.plugins.manager import PluginManager

        def _plugin_state_provider(kind, ident):
            try:
                if kind == "group":
                    state = message_router.policy_engine.groups.get(ident)
                    return {
                        "context_len": len(state.context) if state else 0,
                        "last_activity": state.last_activity if state else 0,
                    }
                return None
            except Exception:  # noqa: BLE001
                return None

        # policy_engine（含 ContextManager）先于插件管理器构造：
        # 插件 SDK 的 get_context 复用现有 ContextManager（领域数据源，不重造）
        policy_engine = PolicyEngine(config, memory_manager)
        plugin_manager = PluginManager(
            config, settings_repo, sender=sender, memory_manager=memory_manager,
            state_provider=_plugin_state_provider, context_manager=policy_engine.context,
            ai_client=ai_client,
        )
        if config.WEB_UI_ENABLED:
            def _status_provider():
                return {
                    "ws_connected": message_router.global_state.ws_connected,
                    "groups": len(message_router.policy_engine.groups),
                }
            web_ui = WebUIServer(
                config, config_service, status_provider=_status_provider,
                tool_manager=tool_manager, persona_manager=persona_manager,
                meme_manager=meme_manager, prompt_manager=prompt_manager,
                plugin_manager=plugin_manager,
            )
        file_parser = FileParser(config)
        # 共享 AI 预算实例：聊天与每日梗总结复用同一套全局/群计数（总结不绕过预算）
        from src.core.budget_manager import BudgetManager
        budget_manager = BudgetManager(config, policy_engine.global_state, sender)
        meme_summary.budget = budget_manager  # 总结任务复用同一预算计数（不绕过三层预算）
        message_router = MessageRouter(
            config=config,
            ai_client=ai_client,
            memory_manager=memory_manager,
            file_parser=file_parser,
            sender=sender,
            policy_engine=policy_engine,
            prompt_manager=prompt_manager,
            sticker_manager=sticker_manager,
            tool_manager=tool_manager,
            persona_manager=persona_manager,
            meme_manager=meme_manager,
            meme_summary=meme_summary,
            budget=budget_manager,
            plugin_manager=plugin_manager,
            event_parser=adapters.parser,
            blossom_memory=blossom_memory,
        )
        # NapCat WebSocket：反向（NapCat 连过来，原有行为）或正向（连接 NapCat 的 WS server），二选一
        if str(getattr(config, "NAPCAT_WS_MODE", "reverse") or "reverse").lower() == "forward":
            from src.core.napcat_forward_client import NapCatForwardClient
            ws_server = NapCatForwardClient(config, message_router)
            logger.info("NapCat WS 模式: forward（连接 %s）",
                        str(getattr(config, "NAPCAT_WS_URL", "") or ""))
        else:
            ws_server = WebSocketServer(config, message_router)

        # 启动后台任务（主动聊天 / 上下文备份，经 TaskManager 统一管理）
        await message_router.start()
        # 启动插件运行时（enabled 插件；发现新插件默认 disabled）
        await plugin_manager.start_all()
        # Web UI（默认关闭；启用时需认证，端口已与 WS_PORT 错开校验）
        if web_ui is not None:
            await web_ui.start()

        # 启动 WebSocket 服务（会自动阻塞直到中断）
        try:
            await ws_server.run()
        finally:
            # ===== 优雅关闭顺序 =====
            # 1) 停止接收新任务、取消后台任务并等待
            logger.info("shutdown_started: 停止后台任务", extra={"event": "shutdown_started"})
            await message_router.stop()
            # 2) 关闭 WebSocket 服务
            await ws_server.shutdown()
            # 2.5) 关闭 Web UI（如有）
            if web_ui is not None:
                await web_ui.stop()
            # 3) 关闭 HTTP 客户端 / 数据库连接
            await file_parser.close()
            await plugin_manager.shutdown()
            memory_manager.close()
            if blossom_memory is not None:
                await blossom_memory.close()
            settings_repo.close()
            sticker_manager.close()
            meme_manager.close()
            await tool_manager.close()
            # 4) 输出进程内 metrics 摘要
            logger.info(
                "shutdown metrics=%s", registry.export_text().replace("\n", " | ")[:800],
                extra={"event": "shutdown_metrics"},
            )
            logger.info("shutdown_finished", extra={"event": "shutdown_finished"})


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("收到退出信号 (Ctrl+C)，正在关闭...")
    except Exception as e:
        logger.exception("运行异常: %s", e)
        sys.exit(1)
