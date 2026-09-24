# 花璃 · QQ 群聊机器人

<p align="center">
  <b>银发灰瞳的小恶魔系青梅竹马 · DeepSeek 驱动 ·  OneBot11/Milky</b>
</p>


<p align="center">
  <b>「戳我干嘛，再戳就不理你了哦」</b>
</p>

<div align="center">
<div align="center">

[![GitHub Tag](https://img.shields.io/github/v/tag/lingcat521/Flowerie_bot)](https://github.com/lingcat521/Flowerie_bot) [![Build Flowerie_bot](https://github.com/lingcat521/Flowerie_bot/actions/workflows/compiler.yml/badge.svg)](https://github.com/lingcat521/Flowerie_bot/actions/workflows/compiler.yml)
[![Acceptance](https://github.com/lingcat521/Flowerie_bot/actions/workflows/acceptance.yml/badge.svg)](https://github.com/lingcat521/Flowerie_bot/actions/workflows/acceptance.yml)
[![Tests](https://img.shields.io/badge/tests-1140%20passed%20(CI%20pytest)-2ea043)](https://github.com/lingcat521/Flowerie_bot/actions/workflows/ci.yml)
[![Acceptance Tests](https://img.shields.io/badge/acceptance-37%20passed-2ea043)](https://github.com/lingcat521/Flowerie_bot/actions/workflows/acceptance.yml)

</div>

---
## 这是什么

**花璃** 是一个基于 **DeepSeek API** 的 **QQ 群聊机器人**：像真实群友一样聊天、识图、看转发、记记忆、被戳会回应，还能自定义人格、发表情包、用 MCP 工具上网查信息，并且可以通过 Web UI 管理配置（当前版本 **v2.2.22222**）。

## 功能

| 功能 | 说明 |
| :--- | :--- |
| 💬 AI 对话 | DeepSeek 驱动，小恶魔系人设，@ 或群聊接话 |
| 👁️ 识图 | 图片/表情包/转发内图片，视觉模型描述后自然回复（`VISION_ENABLED` 总开关可关闭）|
| 📦 转发/卡片解析 | 合并转发递归展开（含图片）、JSON 卡片 |
| 🧠 记忆库 | 按用户×群隔离，SQLite 持久化，自动去重，用户可查/删 |
| 🎭 人格系统（Persona） | 全局 / 群聊 / 自定义三级人格，内置花璃 + 亚托莉（ATRI）+ 艾拉（Isla）三套官方预设，Web UI 管理 |
| 💬 群聊梗知识（Meme） | 每群独立梗/黑话知识库，按消息命中注入，24h 批量总结 + MCP 辅助检索 |
| 🎭 自定义 Prompt | 全局 + 群聊两级人格补充（`/prompt` 命令，管理员可改） |
| 🎲 主动发言概率配置化 | `PROACTIVE_MESSAGE_*` 上下文随机回复概率 + `ACTIVE_CHAT_*` 主动聊天循环，全部可配置 |
| 🗣️ 发言规则 | 管理员补充规则（人格页，默认 4 行）+ 按群专属覆盖，注入所有人格最高优先级 |
| 🧩 插件系统（Plugin System v1） | 受控插件运行时：Python / Node / **任意语言（exec，13 种语言 CI 实测：C/C++·Go·Rust·Java·C#·Kotlin·PHP·Lua·Ruby·Perl·R·TypeScript）** / JSON 声明式插件，独立子进程 + 权限批准 + 保护级别（每插件自动 `data/` 数据目录）|
| 🔌 NapCat WebSocket | 正向 / 反向二选一（`NAPCAT_WS_MODE`），forward 支持鉴权 token + 断线重连 |
| 🖼️ 表情包 | 目录扫描 + Vision 索引缓存，模型按语境选择发送 |
| 🔧 MCP 工具 | 外部工具调用（如搜索），插件式多 server + 工具白名单 + 独立熔断 |
| ⚔️ 引战检测 | 关键词 + AI 双重确认 |
| 🎯 冷却/预算 | 用户/机器人冷却、全局+群+用户三层 AI 预算、复读检测、主动聊天 |
| 🖥️ Web UI | 管理后台：配置/人格/群昵称/群聊知识/外观/日志/用户状态/插件，全零 JS，热更新 |
| 🛡️ 安全 | SSRF 防护、Prompt 注入多层防线、知识防污染、日志脱敏、双层熔断、Web UI 注册 Bootstrap Lock、插件权限强制 |

## 快速开始

> 💿 **安装说明**：[Windows exe](docs/install-release-windows.md) · [Linux/macOS/Termux](docs/install-release-guide.md) · [Milky 协议](docs/milky-protocol.md)



### 环境要求

- Python 3.9+（Linux / macOS / Termux）
- NapCat（或任意 OneBot11 实现），开启反向 WebSocket
- DeepSeek API Key

### 安装


```bash
git clone https://github.com/lingcat521/Flowerie_bot.git
cd Flowerie_bot
pip install -r requirements.txt
cp .env_example .env        # 然后编辑 .env
```

> 📱 **安卓 / Termux 用户**  
> 若在手机上（Termux）安装，请勿使用上述步骤直接装依赖——安卓环境需**绕过 `pydantic` 编译**并依赖预编译库，直接安装会长时间源码编译甚至失败。请务必查看专用安装文档：**[📱 安卓 (Termux) 专用安装](docs/install-termux.md)**。

### 配置（必填两项）

```ini
DEEPSEEK_API_KEY=sk-你的密钥
BOT_QQ=你的机器人QQ号
```

### 启动

```bash
# 推荐：守护脚本（崩溃自动重启）
bash run.sh

# 或前台运行
python main.py
```

启动成功先看到七彩 **FLOWERIE** 启动横幅（协议 / 模型 / 人格 / Web UI 地址摘要），随后日志出现：

```
OneBot WebSocket connected
```

## 配置

完整配置见 [配置](docs/configuration.md)，常用项：

| 变量 | 说明 | 默认 |
| :--- | :--- | :--- |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` | DeepSeek 密钥 / 模型 | 必填 / `deepseek-flash` |
| `BOT_QQ` / `BOT_NICKNAME` | 机器人 QQ / 昵称 | 必填 / 花璃 |
| `WS_PORT` / `HTTP_API_BASE` | 反向 WS 端口 / NapCat HTTP 地址 | `3001` / `http://127.0.0.1:3000` |
| `STICKER_DIR` / `STICKER_ENABLED` | 表情包目录 / 开关 | 空 / `false` |
| `MCP_ENABLED` / `MCP_SERVER_URL` / `MCP_SERVERS` / `MCP_ALLOWED_TOOLS` / `MCP_ALLOWED_HOSTS` | MCP 开关 / 单 server 地址 / 多 server 列表(JSON，插件式) / 工具白名单（留空=放行所有）/ 本地·内网主机白名单 | `false` / 空 / 空 / 空 / 空 |
| `PERSONA_DEFAULT` / `MAX_PERSONA_PROMPT_LENGTH` | 默认人格 id（兜底）/ 人格 system_prompt 长度上限 | `flowerie` / `8000` |
| `ADMIN_RESPONSE_RULES` | 管理员补充发言规则（每行一条；优先级：安全策略 > 人格 > 人格内置规则 > 本条，不覆盖安全策略） | 空 |
| `PROACTIVE_MESSAGE_MIN/MAX/_BASE/_USER_BOOST/_SINGLE_USER/_SHORT_MESSAGE/_EMPTY_CONTEXT/_BOT_MULTIPLIER` | 上下文随机回复概率（详见 configuration.md） | `0.01`/`0.05`/`0.03`/`0.01`/`0.02`/`0.02`/`0.02`/`0.3` |
| `ACTIVE_CHAT_PROBABILITY` / `ACTIVE_CHAT_INTERVAL_MIN/MAX_SECONDS` / `ACTIVE_CHAT_CONSECUTIVE_COOLDOWN_SECONDS` | 主动聊天循环概率与间隔/冷却 | `0.10` / `5`/`10` / `1800` |
| `NAPCAT_WS_MODE` / `NAPCAT_WS_URL` / `NAPCAT_ACCESS_TOKEN` | NapCat WS 模式（`reverse`/`forward`）/ forward 地址 / forward 鉴权 token | `reverse` / 空 / 空 | · `NAPCAT_WS_AUTH_MODE`（header/query 互斥鉴权）
| `PLUGIN_DIR` / `PLUGIN_PROTECTION` / `PLUGIN_MAX_COUNT` / `PLUGIN_URL_MAX_BYTES` / `PLUGIN_URL_TIMEOUT` / `PLUGIN_ZIP_MAX_UNZIPPED_BYTES` / `PLUGIN_ZIP_MAX_FILES` | 插件系统：目录 / 保护级别 / 总数上限 / URL 下载大小上限 / 超时 / 解压后总大小上限 / 文件数上限 | `./plugins` / `normal` / `100` / `5242880` / `15` / `52428800` / `200` |
| `MEME_LEARNING_ENABLED` / `MEME_SUMMARY_INTERVAL_HOURS` / `MAX_GROUP_MEMES` | 群聊梗知识学习开关 / 总结周期（小时）/ 每群知识条数上限 | `false` / `24` / `500` |
| `WEB_UI_ENABLED` / `WEB_UI_PORT` / `WEB_UI_USERNAME` / `WEB_UI_PASSWORD` | Web UI 开关 / 端口 / 登录账号 / 密码 | `false` / `8080` / `admin` / 空 |
| `LOG_FORMAT` | 日志格式 `text`/`json` | `text` |

> ⚠️ `WEB_UI_PORT` 不能与 `WS_PORT` 相同（端口冲突时启动会报错）。

## 指令

| 命令 | 权限 | 作用 |
| :--- | :--- | :--- |
| `/help` | 所有人 | 指令菜单 |
| `/memory` / `/forget 关键词` / `/forget_me` | 所有人 | 查看/删除自己的记忆 |
| `/prompt show` | 所有人 | 查看当前生效 Prompt |
| `/prompt set <内容>` / `/prompt reset` | 管理员 | 设置/重置全局 Prompt |
| `/prompt group set <内容>` / `/prompt group reset` | 管理员 | 设置/重置本群 Prompt |
| `/memory_clear` / `/memory_dump` | 管理员 | 清空/导出本群记忆 |

## Web UI

**默认开启**（只监听本机回环 `127.0.0.1`，不对外）—— 访问 `http://127.0.0.1:8080/panel`
（无 JS 兼容面板，手机浏览器也能用）。首次进入是**注册页**，创建第一个管理员即可；
也可提前在 `.env` 设 `WEB_UI_USERNAME` / `WEB_UI_PASSWORD`。
想彻底关闭：`WEB_UI_ENABLED=false`；想让局域网设备访问：`WEB_UI_ALLOW_LAN=true`（默认关闭）。

八个页签，全部纯 HTML + CSS + 服务端渲染，**零 JavaScript**：

- **配置**：全部变量按功能分组（bool/int/secret/文本/列表/JSON 各有控件），每组独立保存，
  修改**真正写入项目根 `.env`**（原子更新、保留注释与原变量），Secret 只显示掩码、留空不覆盖
- **人格**：人格库 CRUD、群聊绑定与解除、`PERSONA_*` 配置 · **群聊知识**：按群查看/搜索/增删改，严格隔离
- **群昵称**：按群专属称呼（× 人设隔离，留空恢复默认）
- **外观**：7 套主题（默认/深色/浅色/Sakura/Ocean/Forest/AMOLED）、背景图上传（≤5MB，魔数校验）、透明度与显示方式
- **日志**：最近 200 条运行日志 · **用户状态**：凭据来源 / 改账号 / 注销 / 服务器状态 / MCP / API 厂商连接
- **插件**：保护级别（normal/relaxed/unsafe）、上传 ZIP / URL 安装、启用（含权限批准）、禁用、卸载

完整功能指南（各页细节 + 安全说明）见 **[Web UI 说明](docs/web-ui.md)**；人格见 [人格系统](docs/persona.md)，
记忆/知识见 [记忆与知识](docs/memory.md)，插件开发见 **[插件开发指南](docs/plugin-developer-guide.md)**（§31 已内联 **13 种语言任意语言插件**完整实现：C/C++/Go/Rust/Java/Kotlin/C#/TS/PHP/Lua/Ruby/Perl/R），
安全模型见 **[安全模型](docs/security.md)**，变量说明见 [配置](docs/configuration.md)。

### 如何开启

**默认已开启**，无需任何配置：浏览器打开 `http://127.0.0.1:8080/panel`，首次进入是注册页，创建管理员即可。

> 改端口 / 预设账号密码（`WEB_UI_PORT` 不能与 `WS_PORT` 相同）、对局域网开放（`WEB_UI_ALLOW_LAN=true`，
> 绑定 0.0.0.0 并输出安全警告，请设强密码、勿直接暴露公网）→ 见 [Web UI 说明](docs/web-ui.md)。

## MCP

默认关闭。配置 `MCP_ENABLED=true` + `MCP_SERVER_URL`（或插件式多 server：`MCP_SERVERS` JSON，可自行添加任意数量的 MCP 服务，支持本地/内网地址）后，模型可调用白名单内的工具获取实时信息。群聊梗知识的每日总结也会在需要时通过 MCP 检索验证新梗。详见 [MCP 工具](docs/mcp.md)。

## Persona（人格系统）

内置三套官方人格：**花璃**（默认）、**亚托莉（ATRI）** 与 **艾拉（Isla）**；管理员可创建完全独立的自定义人格。
人格优先级：**群聊人格 > 全局人格 > 内置默认**，切换人格不影响记忆与上下文。
Web UI「人格」页管理；详细设计见 [人格系统](docs/persona.md)。

## 插件系统（Plugin System v1）

受控插件运行时：插件以**独立子进程**运行（Python / Node / **任意语言 exec**），或为**进程内声明式规则**
（JSON，无代码执行），通过 stdin/stdout JSON-Lines 协议与 Flowerie 通信，动作一律由 PermissionManager 强制鉴权。
SDK 模式提供统一 Event / Message / Matcher / Permission 与 Bot Adapter 分层，插件**不接触 OneBot payload**
（最小示例：`@command("hello") async def hello(event): await event.reply("你好")`）。

安装途径：Web UI 上传 ZIP / URL 下载（SSRF 防护 + 大小限制），或放入 `plugins/` 目录自动发现
（**发现 ≠ 自动执行**，默认 disabled，须管理员启用并批准权限）。保护级别 `PLUGIN_PROTECTION`
（`normal`/`relaxed`/`unsafe`）只影响运行时限制，**任何级别都不豁免**权限检查 / 进程隔离 / 日志 /
崩溃保护 / 资源限制 / manifest 校验 / 管理员权限。

开发文档：**[插件开发指南](docs/plugin-developer-guide.md)（完整参考，含 §31 十三种语言任意语言插件）** · [快速开始](docs/quick-start.md) ·
[Plugin WebUI](docs/plugin-webui.md) · [SDK 手册](docs/sdk.md) · [API 速查](docs/api.md) · [文档中心](docs/README.md)

## 群聊梗知识（Meme Knowledge）

每个群拥有**完全隔离**的梗/黑话知识库：消息命中时只注入相关词条（不可信上下文知识），
`MEME_LEARNING_ENABLED=true` 时每 24 小时批量总结一次群聊并写入新梗（必要时经 MCP 检索验证）。
Web UI「群聊知识」页管理；详细设计见 [记忆与知识](docs/memory.md)。

## 开发

```bash
pip install -r requirements-dev.txt
pytest              # 1140 个测试（CI：Python 3.9/3.12 + PostgreSQL）
acceptance          # 37 项黑盒验收（tests/acceptance_check.py）
ruff check .        # 代码检查
```

CI：GitHub Actions 自动跑 Python 3.9 / 3.12 的 ruff + pytest。

更多工程细节：架构审计见 [架构审计](docs/archive/architecture-audit.md)（历史快照），表情包见 [表情包](docs/stickers.md)，
安全模型见 [安全模型](docs/security.md)。

## License

[MIT](LICENSE) © 2026 铃樱（lingcat521）


## 功能开关（Web UI 可切换）

- **AI / 长期记忆 / 主动聊天 / 复读 / 防刷 / 戳戳 / 表情包 / MCP / 存档 / 群梗学习**：Web UI「配置」按分类折叠，每分类顶部开关徽标
- **花语记忆（BlossomMemory，默认关闭）**：语义长期记忆（向量化检索 + 可重排 + 自动提取 + 群隔离）
- **存储后端**：默认 SQLite；可选 PostgreSQL——两者细节与迁移工具见 [配置说明](docs/configuration.md)

## 📚 文档

完整索引（含阅读顺序与「谁需要」）见 **[文档中心](docs/README.md)**，常用入口：

- **安装上手**：[Windows exe](docs/install-release-windows.md) · [Linux/macOS](docs/install-release-guide.md) · [Termux](docs/install-termux.md) · [配置说明](docs/configuration.md)
- **功能使用**：[Web UI](docs/web-ui.md) · [人格系统](docs/persona.md) · [记忆与知识](docs/memory.md) · [MCP 工具](docs/mcp.md) · [表情包](docs/stickers.md)
- **插件开发**：[快速开始](docs/quick-start.md) · [完整指南](docs/plugin-developer-guide.md)（**含任意语言：13 种语言最小实现 §31**） · [Plugin WebUI](docs/plugin-webui.md) · [SDK](docs/sdk.md) · [API](docs/api.md)
- **运维开发**：[安全模型](docs/security.md) · [开发说明](docs/development.md) · [OneBot 兼容](docs/onebot-compatibility.md) · [Milky 协议](docs/milky-protocol.md) · [历史归档](docs/archive/README.md)
