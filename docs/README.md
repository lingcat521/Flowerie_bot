# Flowerie 文档

> 对应 **v2.2.2222**：v2.2.2 封版后的兼容性维护 —— 任意语言插件（**13 种语言** CI 实测）、
> 启动横幅、`.env` 模板与 Web UI 配置页同源、默认模型统一 `deepseek-flash`。更早版本见 [archive/](archive/README.md)。

## 先挑一条路线走

| 你的目标 | 按顺序读 |
| --- | --- |
| 🧩 **写插件** | [quick-start](quick-start.md)（10 分钟小白版）→ [plugin-developer-guide](plugin-developer-guide.md)（完整参考）→ 按需查 [plugin-webui](plugin-webui.md) / [sdk](sdk.md) / [api](api.md) |
| 🔧 **部署运维** | 安装（[Windows](install-release-windows.md) · [Linux/macOS/Termux 资产](install-release-guide.md) · [**Termux 权威步骤**](install-termux.md)）→ [configuration](configuration.md) → [web-ui](web-ui.md) → [security](security.md) |
| 🛠 **改代码** | [development](development.md)（目录结构 / 测试 / CI）→ [sdk](sdk.md)（三层架构）→ [archive/](archive/README.md)（历史审计） |

## 核心文档（每主题的唯一事实来源）

> ✍️ **维护约定（防重复）**：一个主题**只在下表对应的那一份文档里详细写**，其他地方只放一句摘要 + 链接。
> 改行为时先改这份，再回头核对别处有没有抄旧值 —— **测试数、默认值、页签数、版本号**最容易漂。

| 文档 | 内容 | 谁需要 |
| --- | --- | --- |
| **[quick-start.md](quick-start.md)** | **第一层·小白快速开始**（10 分钟：创建 / manifest / 收发消息 / 记忆 / HTTP / 权限 / 完整例子 / 安装测试） | 插件新人 |
| **[plugin-developer-guide.md](plugin-developer-guide.md)** | **第二层·完整参考**（Manifest 规则 / Python·Node·JSON / **任意语言 exec §4.5** 与 **§31 十三种语言实测清单** / 生命周期 / Event·Action·Permission API / 超时·资源·安全 / 打包 / WebUI 安装） | 插件开发者 |
| [plugin-webui.md](plugin-webui.md) | **Plugin WebUI**（DSL 组件全集 / hook / 权限 / 文件 / 安全边界） | 插件开发者 |
| [sdk.md](sdk.md) | SDK 模式全参考：Event 字段 / BotMessage / Matcher / 多轮交互 / 定时 / 权限 / FAQ | 插件开发者 |
| [api.md](api.md) | **API 权威速查总表**（方法 × 作用 × 权限 × 章节，自动生成） | 插件开发者 |
| [configuration.md](configuration.md) | 全部配置项 / `.env` / 优先级 / 功能开关表 / 存储后端与迁移工具 | 运维 |
| [web-ui.md](web-ui.md) | Web UI 八个页签 / 如何开启 / 零 JavaScript / 注册与登录 | 运维 |
| [security.md](security.md) | **安全规则权威**：SSRF / 注入 / 权限 / 资源上限 / 指标 / 已知边界 | 运维 + 开发者 |
| [memory.md](memory.md) | 记忆体系：Context / Memory / 群知识 / 花语记忆（BlossomMemory） | 运维 + 开发者 |
| [persona.md](persona.md) | 人格系统（内置三套 / 群 / 全局 / 管理员补充规则） | 运维 |
| [mcp.md](mcp.md) | MCP 工具服务器（单 server / 插件式多 server / SSRF 防护） | 运维 + 开发者 |
| [stickers.md](stickers.md) | 表情包系统 | 运维 |
| [development.md](development.md) | 开发约定 / 目录结构 / 测试与 CI / 存储后端扩展 | 开发者 |
| [install-termux.md](install-termux.md) | **Termux 部署权威步骤**（镜像源 / 依赖 / SSL 与编译报错排查） | 运维 |
| [install-release-guide.md](install-release-guide.md) | Release 资产用法：Linux / macOS / Termux 源码包（含 `build-termux.sh`） | 运维 |
| [install-release-windows.md](install-release-windows.md) | Windows exe 用法 / 首次配置 / 常见问题 | 运维 |
| [onebot-compatibility.md](onebot-compatibility.md) | OneBot v11 全平台兼容（连接层 / 发送通道 / 识图 / 能力矩阵） | 运维 |
| [milky-protocol.md](milky-protocol.md) | Milky 协议支持（配置 / 事件格式 / API 调用 / 已知边界） | 运维 |

## 归档

各阶段的审计 / 评审 / 交付报告见 [archive/](archive/README.md) —— 它们是**当时的既定事实记录，不随版本更新**；
查当前行为一律以上表为准。
