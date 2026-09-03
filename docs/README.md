# Flowerie 文档

> 文档对应 **v2.2.2（封版最终版）**；更早版本见 `docs/archive/`。中心（导航）

> 阅读顺序：**插件新人先看 [quick-start](quick-start.md)（第一层）** → 深入再看 [plugin-developer-guide](plugin-developer-guide.md)（第二层·完整参考）+ [sdk](sdk.md) + [api](api.md)；运维/配置 → [configuration](configuration.md) + [web-ui](web-ui.md) + [install-termux](install-termux.md)。

## 核心文档（唯一事实来源）

| 文档 | 内容 | 谁需要 |
| --- | --- | --- |
| **[quick-start.md](quick-start.md)** | **第一层·小白快速开始**（10 分钟：创建/manifest/收发消息/记忆/HTTP/权限/完整例子/安装测试） | 插件新人 |
| [plugin-webui.md](plugin-webui.md) | **Plugin WebUI**（DSL 组件全集 / hook / 权限 / 文件 / 安全边界） | 插件开发者 |
| [plugin-developer-guide.md](plugin-developer-guide.md) | **第二层·完整参考**（Manifest 规则/Python·Node·JSON/生命周期/Event·Action·Permission API/超时/资源/安全/打包/WebUI 安装） | 插件开发者 |
| [sdk.md](sdk.md) | SDK 模式全参考：Event 字段 / BotMessage / Matcher / 多轮交互 / 定时 / 权限 / FAQ | 插件开发者 |
| [api.md](api.md) | **API 权威速查总表**（59 方法 × 作用 × 权限 × 章节，自动生成） | 插件开发者 |
| [configuration.md](configuration.md) | 全部配置项 / .env / 优先级 / 功能开关表 | 运维 |
| [web-ui.md](web-ui.md) | Web UI 面板 / 折叠 / 零 JS / 登录 | 运维 |
| [security.md](security.md) | **安全规则权威**：SSRF / 注入 / 权限 / 资源上限 / 指标 | 运维+开发者 |
| [memory.md](memory.md) | 记忆体系：Context / Memory / 群知识 / 花语记忆（BlossomMemory） | 运维+开发者 |
| [persona.md](persona.md) | 人格系统（内置/群/全局） | 运维 |
| [mcp.md](mcp.md) | MCP 工具服务器 | 运维+开发者 |
| [stickers.md](stickers.md) | 表情包系统 | 运维 |
| [development.md](development.md) | 开发约定 / 存储后端扩展 / 迁移 | 开发者 |
| [install-termux.md](install-termux.md) | Termux 部署 | 运维 |

## 归档

历史审计/评审/封口报告见 [archive/](archive/README.md)（记录既定事实，不随版本更新）。
