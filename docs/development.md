# 开发

> 开发环境/仓库约定见本文件；SDK 三层架构见 [sdk.md](sdk.md)（v1.6.0 交付记录见 [archive/qwq-final-report.md](archive/qwq-final-report.md)）；存储后端扩展（SQLite 默认 / PG 可选 + 迁移工具）见本文 §存储后端扩展。


## 环境

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

## 测试

```bash
pytest                            # 全部（含默认 skip 的实机用例）
pytest tests/xxx                  # 单文件
pytest -m "not real_device"       # 排除实机用例（CI 就是这种语义：无环境即 skip）
```

**三层测试必须分清**（任务书 §13，详见 [tests/integration/README.md](../tests/integration/README.md)）：

| 层 | 位置 | 运行条件 |
| :--- | :--- | :--- |
| unit / 静态 | `tests/test_*.py` | 无外部依赖，CI 每次跑 |
| integration（可自动判定）| `tests/integration/`（22 例）| 需真实协议端 + 测试群（环境变量），否则 skip |
| manual real-device | 该目录 README 的手工步骤 | 人工触发 |

当前 **1259** 个测试（随版本增长）：并发安全、故障隔离、熔断、状态治理、Prompt/Sticker/MCP/Web UI、SSRF/注入回归与 Code Scanning 整改回归、MCP 额度/安全、配置持久化/校验、Web UI 注册/无 JS 面板、Persona 系统、群聊 Meme Knowledge、多条回复与 Native Reply Tool、任意语言插件（13 种语言黑盒端到端）、**架构 Gate 专项 12 个文件**（契约 / 能力 / 未知容错 / PEC / 传输契约 / 多实例 / 资源 / 覆盖率 / 跨协议等价 / Round-trip / 回归矩阵）等，详见 `tests/`。

本机缺依赖（aiohttp / pydantic / httpx）时的跑法：

```bash
PYTHONPATH=$HOME python3 -m pytest -p stubplug tests/ -q            # 最小 stub（与 CI 同一基线）
PYTHONPATH=$HOME python3 -m pytest -p stubplug -p stubio tests/ -q  # 追加 aiohttp/websockets stub（跑更宽的导入链）
```

## 代码检查

```bash
ruff check .        # lint（E/F/W/I/B 规则集）
```

## CI

GitHub Actions 在 push/PR 时自动运行：

- **CI**（`.github/workflows/ci.yml`）：Python 3.9 / 3.12 双版本 + PostgreSQL service；`ruff check .` + `pytest`
- **Acceptance**（`.github/workflows/acceptance.yml`）：`tests/acceptance_check.py` 黑盒验收（起真实面板 + 37 项检查）
- **CodeQL**（默认分析）：`actions` / `javascript-typescript` / `python` 三路；告警审计结论见 [security.md](security.md)
- **行数护栏**（`tests/test_web_ui_persona_knowledge.py`）：web_ui / ai_client ≤430、webui_assets ≤120、
  config_service ≤700、message_router ≤650 —— 超限请继续拆分而不是提高上限

## 目录结构

```
src/
├── core/           # 消息路由(委托AiGateway)/组装/策略/预算/WS 服务
│   ├── ai_gateway.py      # AI 准入层（熔断/预算/人格/知识/工具装配/重试）
│   ├── reply_plan.py      # ReplyPlan：多条回复的计划与裁剪（协议无关）
│   ├── reply_sender.py    # send_plan：逐条发送编排（失败策略 stop/continue）
│   └── reply_dispatch.py  # ReplyDispatchMixin：单条/多条统一分发 + 逐条记历史
├── services/       # AI 客户端/记忆/文件解析/发送/表情包/MCP/配置服务/Web UI
│   ├── ai_client.py       # 薄封装：chat/工具循环/回复解析（~410 行）
│   ├── reply_tool.py      # Native Reply Tool：AI 自主拆分（只捕获，不发送）
│   ├── prompt_builder.py  # system prompt 组装（从 AIClient 拆分）
│   ├── vision.py          # 视觉识图 VisionService（从 AIClient 拆分）
│   ├── toxic_detector.py  # 引战检测 ToxicDetector（从 AIClient 拆分）
│   ├── config_schema.py   # 配置声明 SCHEMA（从 ConfigService 拆分）
│   ├── web_ui.py          # Web UI 薄门面（~395 行；面板 mixin 聚合）
│   ├── webui_panels/      # 各功能域 mixin（account/auth/config/appearance/mcp/persona/knowledge/nickname/prompt/plugin）
│   ├── webui_render/      # 渲染层（theme/pages/config_panel/appearance/persona/knowledge/account/plugins/nicknames/plugin_dsl/plugin_webui/category_constants）
│   │   ├── templates/       # 真实 HTML 页面壳（panel/login/register）
│   │   ├── static/panel.css # 真实 CSS 文件（Python 只注入 {{THEME_VARS}}）
│   │   └── assets.py        # 资源读取（兼容 PyInstaller _MEIPASS）
│   ├── webui_static.py   # /panel/static/{name} 路由 + HTML no-store 中间件
│   ├── persona_manager/persona_presets（人格）
│   ├── meme_knowledge_manager/meme_summary（群聊梗知识/每日总结）
│   └── system_status.py     # 服务器状态采集（用户状态页用，零依赖 /proc）
├── repositories/   # SQLite 存储层（记忆/设置/表情包索引/梗知识）
└── utils/          # 日志/trace/指标/熔断/过期容器/任务管理
tests/              # 1142 个测试（含 CI 资产/响应式回归/安全回归）
docs/               # 文档
```

## 架构

架构审计报告见 [archive/architecture-audit.md](archive/architecture-audit.md)（五轮工程审计 + v1.3.0 SDK 分层，历史快照）。

## Bot SDK 开发（v1.3.0+）

- 分层：上层 `plugin_sdk/` → 中层 `src/sdk/`（零 OneBot）→ 下层 `src/adapters/onebot/`
- 新增平台能力：只改下层 `onebot/`（dto/transformer/adapter），中层上层不动
- 测试：`tests/test_sdk_*.py`（matcher/listener/adapter/permission/message）
- 文档：[sdk.md](sdk.md) / [api.md](api.md) / [plugin-developer-guide.md](plugin-developer-guide.md)（导航 [README.md](README.md)）


## 存储后端扩展（SQLite 默认 / PostgreSQL 可选）

- 业务只依赖 Repository 接口（`src/repositories/base.py` / `src/repositories/blossom_memory_repository.py`）
- 新增后端 = 平行实现接口（参考 Postgres*Repository）；`STORAGE_BACKEND` 切换
- 迁移工具幂等 + 失败安全（源库不动）；测试：CI postgres service（TEST_POSTGRES_URL）
- 安全：API URL 一律过 `sanitizer.validate_mcp_server_url`（SSRF）；记忆文本过
  `sanitize_untrusted_text`；metrics label 仅低基数（operation/result，禁 id 类）