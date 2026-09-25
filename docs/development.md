# 开发

> 当前版本 **v2.3.0**。SDK 三层架构见 [sdk.md](sdk.md)，安全边界见 [security.md](security.md)，
> 历史审计报告见 [archive/](archive/README.md)。

## 环境

```bash
pip install -r requirements.txt          # 运行依赖
pip install -r requirements-dev.txt      # pytest / pytest-asyncio / ruff
```

## 测试

```bash
pytest                                    # 全部（实机用例默认 skip）
pytest tests/test_config_service.py       # 单文件
pytest -m "not real_device"               # 排除实机用例
```

**四层测试必须分清**（不要把手工测试伪装成 CI 自动测试；分层口径见 [tests/integration/README.md](../tests/integration/README.md)）：

| 层 | 位置 | 命令 | 当前状态 |
| :--- | :--- | :--- | :--- |
| unit / 静态（含架构 Gate） | `tests/test_*.py` | `pytest -q -rs --ignore=tests/sdk --ignore=tests/webui --ignore=tests/e2e` | **2288 passed / 39 skipped**（CI 的 pytest 步骤就是这个口径） |
| 多语言 SDK 最小插件实测 | `tests/sdk/` | `pytest -q -s tests/sdk/` | **46**：真 build（go/rustc/javac/tsc…）→ 真加载 → ping/echo/event/call/权限/关机 |
| Plugin WebUI（真服务器 + 真插件进程） | `tests/webui/` | `pytest -q -s tests/webui/` | **102**：HTTP / 静态 / 安全 / 隔离 / 动作 / 插件间通信 |
| 真浏览器 E2E（Playwright Chromium） | `tests/e2e/` | `pytest -q -rs -s tests/e2e/` | **21**：真 WebUI 服务器 + 真插件进程 + 真 Chromium；缺浏览器即 `BLOCKED BY ENVIRONMENT` skip（**绝不写 PASS**） |
| 实机 integration（可自动判定） | `tests/integration/` | `pytest tests/integration -q -rs` + 环境变量 | **22**，默认全 skip：需真实协议端 + 测试群 |

真浏览器 E2E 准备与分层跑法：

```bash
pip install playwright && python -m playwright install --with-deps chromium
pytest -q -rs -s tests/e2e/                            # 全部（浏览器层）
pytest -q -rs tests/e2e/test_plugin_chain_engine.py     # 只跑引擎层（真插件进程 + Core Router，任何环境可跑）
```

本机缺依赖（aiohttp / pydantic / httpx）时的跑法：

```bash
PYTHONPATH=$HOME python3 -m pytest -p stubplug tests/ -q            # 最小 stub（与 CI 同一基线）
PYTHONPATH=$HOME python3 -m pytest -p stubplug -p stubio tests/ -q  # 追加 aiohttp/websockets stub（跑更宽的导入链）
```

> 带 commit 的历史数字：**2.3.0（2026-09-25）发布时记录 1121 个测试**（见 [CHANGELOG](../CHANGELOG.md)）；
> 上表是当前实测（2288 / 46 / 102 / 21 / 22）。

## 代码检查

```bash
ruff check .        # lint（E/F/W/I/B 规则集，line-length=120）
```

## CI（三档 workflow + CodeQL 默认分析）

| workflow / job | 触发 | 内容 |
| :--- | :--- | :--- |
| `ci.yml` → **test** | push main / PR | Python **3.9 与 3.12** 双版本 + PostgreSQL 16 service + Node 20 + lua/R 工具链；`ruff check .` → `pytest -q -s tests/sdk/` → `pytest -q -s tests/webui/` → 主套件（`--ignore` 三个专项目录，带 `TEST_POSTGRES_URL`） |
| `ci.yml` → **webui-e2e** | 同上 | `continue-on-error`：装 Playwright Chromium 后跑 `pytest -q -rs -s tests/e2e/`（真浏览器证据由 CI 产出） |
| `acceptance.yml` | push main / PR | `python tests/acceptance_check.py`：起真实 Web UI + 真 HTTP + `.env` round-trip + 零 JS/安全 + pytest + ruff，逐项 `rec()`（37 项），非 0 即失败 |
| `compiler.yml` | release created | 5 个平台 × builtin/portable 打包 + Termux 源码包 → 上传 Release 资产（见 [install-release-guide.md](install-release-guide.md)） |
| CodeQL | 仓库默认分析设置（无独立 workflow 文件） | `actions` / `javascript-typescript` / `python`；告警逐条判定见 [security.md](security.md) |

**行数护栏**（`tests/test_web_ui_persona_knowledge.py`）：`web_ui.py` ≤430、`web_ui_assets.py` ≤120、
`ai_client.py` ≤430、`config_service.py` ≤700、`message_router.py` ≤650 —— 超限请继续拆分，而不是提高上限。

## 目录结构

```text
src/
├── core/           # 消息路由（委托 AiGateway）/组装/策略/预算/ReplyPlan/WS 服务
├── services/       # AI 客户端/记忆/文件解析/发送/表情包/MCP/配置服务/Web UI（webui_panels + webui_render）
├── plugins/        # 插件运行时：manager / runtime / runner / permissions / installer / webui_security / router
├── sdk/            # 中层 SDK（零 OneBot 命名的领域层）
├── adapters/       # 下层适配层（onebot/ + testkit/）：唯一接触协议语义的地方
├── transport/      # 反向 WS 服务器 / 正向 WS 客户端 / 动作通道
├── repositories/   # 存储层（SQLite 默认；Postgres*Repository 平行实现）
└── utils/          # 日志脱敏/trace/指标/熔断/过期容器/任务管理
plugin_sdk/         # 上层插件 SDK（随插件分发的零依赖副本）
scripts/            # gen_api_md.py（生成 docs/api.md）、multi_reply_demo.py
tests/
├── test_*.py       # 主套件 + 架构 Gate（契约/能力/未知容错/多实例/资源/跨协议等价…）
├── sdk/            # 多语言最小插件实测（13 种语言真编译真运行）
├── webui/          # Plugin WebUI 专项（真服务器 + 真插件进程）
├── e2e/            # 真浏览器 E2E（Playwright Chromium）
├── integration/    # 实机 integration（需真实协议端，默认 skip）
├── plugins/        # 测试用插件夹具（doc_example / sdk_plugin / multilang…）
└── fixtures/       # 协议语料与客户端夹具（napcat / llbot / milky…）
docs/               # 文档（索引见 docs/README.md）
```

## Bot SDK 开发

- 分层方向单一：上层 `plugin_sdk/flowerie_sdk/` → 中层 `src/sdk/`（零 OneBot 命名）→ 下层 `src/adapters/onebot/`。
- 新增平台能力只改下层（dto / transformer / adapter），中上层不动；协议耦合由 Gate 测试锁基线（只许减少）。
- 测试：`tests/test_sdk_*.py`、`tests/test_adapter_contract.py`、`tests/test_architecture_gates.py`。
- 文档：[sdk.md](sdk.md) / [api.md](api.md) / [plugin-developer-guide.md](plugin-developer-guide.md)。

## 存储后端扩展（SQLite 默认 / PostgreSQL 可选）

- 业务只依赖 Repository 接口（`src/repositories/base.py`、`blossom_memory_repository.py`）；
  新增后端 = 平行实现接口（参考 `Postgres*Repository`），用 `STORAGE_BACKEND` 切换。
- 迁移工具幂等 + 失败安全（源库不动）：
  `python -m src.services.storage_migrate --sqlite ./data/memory.db --postgres <DSN> [--blossom ./data/blossom_memory.db]`
- CI 用 PostgreSQL service（`TEST_POSTGRES_URL`）真跑 CRUD；API URL 一律过 SSRF 校验、记忆文本过
  `sanitize_untrusted_text`、metrics label 仅低基数（operation/result，禁 id 类）。
