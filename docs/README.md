# Flowerie 文档

> 对应 **v2.2.22222**：停更期间的维护性更新 —— Code Scanning 全量安全整改、原生多条回复（Multi-Reply +
> **AI 自主拆分的 Native Reply Tool**）、Milky 能力补齐（协议 1.3 / 65 动作全量对照）、花语记忆门控修复；
> 更早版本见 [archive/](archive/README.md)。

## 先挑一条路线走

| 你的目标 | 按顺序读 |
| --- | --- |
| 🧩 **写插件** | [quick-start](quick-start.md)（10 分钟小白版）→ [plugin-developer-guide](plugin-developer-guide.md)（完整参考）→ 按需查 [plugin-webui](plugin-webui.md) / [sdk](sdk.md) / [api](api.md)；**不用 Python/Node？** 直接看 [plugin-developer-guide](plugin-developer-guide.md) §31（13 种语言最小实现）（13 种语言最小实现，照抄即可） |
| 🔧 **部署运维** | 安装（[Windows](install-release-windows.md) · [Linux/macOS/Termux 资产](install-release-guide.md) · [**Termux 权威步骤**](install-termux.md)）→ [configuration](configuration.md) → [web-ui](web-ui.md) → [security](security.md) |
| 🛠 **改代码** | [development](development.md)（目录结构 / 测试 / CI）→ [sdk](sdk.md)（三层架构）→ [archive/](archive/README.md)（历史审计） |

## 核心文档（每主题的唯一事实来源）

> ✍️ **维护约定（防重复）**：一个主题**只在下表对应的那一份文档里详细写**，其他地方只放一句摘要 + 链接。
> 改行为时先改这份，再回头核对别处有没有抄旧值 —— **测试数、默认值、页签数、版本号**最容易漂。

| 文档 | 内容 | 谁需要 |
| --- | --- | --- |
| **[quick-start.md](quick-start.md)** | **第一层·小白快速开始**（10 分钟：创建 / manifest / 收发消息 / 记忆 / HTTP / 权限 / 完整例子 / 安装测试） | 插件新人 |
| **[plugin-developer-guide.md](plugin-developer-guide.md)** | **第二层·完整参考**（Manifest 规则 / Python·Node·JSON / **任意语言 exec §4.5** 与 **§31 十三种语言实测清单** / 生命周期 / Event·Action·Permission API / 超时·资源·安全 / 打包 / WebUI 安装） | 插件开发者 |
| **[plugin-developer-guide.md](plugin-developer-guide.md) §31** | **任意语言插件**：exec 协议三分钟说明 + **13 种语言完整最小实现**（C/C++/Go/Rust/Java/Kotlin/C#/TS/PHP/Lua/Ruby/Perl/R）+ 构建入口速查 + 排查清单 | 非 Python/Node 的插件作者 |
| [plugin-webui.md](plugin-webui.md) | **Plugin WebUI**（DSL 组件全集 / hook / 权限 / 文件 / 安全边界） | 插件开发者 |
| [client-profiles.md](client-profiles.md) | **客户端档案**：一个协议基线 + 多个客户端实现的已验证差异（四态 + quirks）、出站序列化怎么用、新客户端接入清单 | 协议/适配层开发者 |
| [client-compatibility.md](client-compatibility.md) | **Client Compatibility Matrix**：逐能力 × 逐客户端（SUPPORTED/PARTIAL/UNSUPPORTED/UNKNOWN + 证据）| 协议/适配层开发者 |
| [plugin-webui-protocol.md](plugin-webui-protocol.md) | **统一 Plugin WebUI 协议**：`webui.page/action/asset` 三个协议方法 + 六项 `webui.*` 权限 + 受控 context + 20 类安全用例落点（五种语言同一套） | 插件开发者 |
| [plugin-protocol.md](plugin-protocol.md) | **Plugin Protocol v1 规范**：JSON-Lines 线格式 / 必需 4 + 可选 11 方法 / 错误模型 / 版本与能力协商 / 选型理由 | 插件开发者 |
| [plugin-sdk.md](plugin-sdk.md) | **多语言 SDK 指南**：五语言 API 对照 / 能力对齐 / 新语言接入清单；单语言参考见 [typescript](plugin-sdk-typescript.md) · [go](plugin-sdk-go.md) · [rust](plugin-sdk-rust.md) · [java](plugin-sdk-java.md) | 插件开发者（非 Python）|
| [plugin-sdk-capabilities.md](plugin-sdk-capabilities.md) | **Capability Matrix**：逐能力四态（SUPPORTED/PARTIAL/UNSUPPORTED/UNKNOWN）+ CI 证据 | 插件开发者 + 评审 |
| [plugin-final-report.md](plugin-final-report.md) | **三份任务书最终报告**：逐条必答清单 + 真实数字 + 复核命令 | 评审 |
| [sdk.md](sdk.md) | SDK 模式全参考：Event 字段 / BotMessage / Matcher / 多轮交互 / 定时 / 权限 / FAQ + **附录 A 能力与兼容矩阵**（端点映射 / 网关兼容 / v2.1 缺口台账） | 插件开发者 |
| [api.md](api.md) | **API 权威速查总表**（方法 × 作用 × 权限 × 章节，自动生成） | 插件开发者 |
| [configuration.md](configuration.md) | 全部配置项 / `.env` / 优先级 / 功能开关表 / **多条回复与 Native Reply Tool** / 存储后端与迁移工具 | 运维 |
| [web-ui.md](web-ui.md) | Web UI 八个页签 / 如何开启 / 零 JavaScript / 注册与登录 / **分辨率自适应五档断点** / **缓存策略** / 静态资源与模板结构 | 运维 |
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
| [protocol-reverse-engineering.md](protocol-reverse-engineering.md) | **协议逆向总报告**：客户端源码证据（`[CODE]` 行号）/ 归一化差距 / 下一步 / **更正记录** | 开发者 |
| [client-compatibility.md](client-compatibility.md) | **客户端兼容矩阵**：OneBot 11 / Milky / NapCat / Lagrange / SnowLuma / LLBot 逐项对照 + 生态覆盖分级 | 开发者 |
| [message-model.md](message-model.md) | **归一化消息模型**：`InternalEvent` / `NormalizedSegment` 字段、四协议映射表、`[UNKNOWN]` 清单 | 开发者 |
| [adapter-architecture.md](adapter-architecture.md) | **Adapter 分层架构**：依赖方向硬约束 / 数据流 / 归一化契约 / 接入新客户端五步清单 | 开发者 |
| [mvp-analysis.md](mvp-analysis.md) | **MVP 对照报告**：事实清单 / 为什么能工作 / 值得迁移 / 不能直接迁移 | 开发者 |
| [source-acquisition.md](source-acquisition.md) | **源码获取台账**：15 个仓库与 commit、各客户端 `SOURCE_*` 状态（含失败与更正） | 开发者 |
| [architecture/](architecture/README.md) | **架构 ADR 集**：ADR-001 传输解耦 / ADR-002 能力模型 / ADR-003 Adapter 边界与契约 / ADR-004 虚拟协议实验（新增协议 PEC = 0） | 开发者 |
| [architecture/final-acceptance-report.md](architecture/final-acceptance-report.md) | **最终验收报告**（任务书 §36 数字块）：真实数字 + 八项绝对门槛 + BLOCKED 证据 | 开发者 |
| [architecture/acceptance-metrics.md](architecture/acceptance-metrics.md) | **验收 Dashboard**：八项绝对门槛 + Gate A–Z 实测值 + 逐提交 CI 真实结论 | 开发者 |
| [protocol-gap-closure.md](protocol-gap-closure.md) | **协议缺口台账**：A 部分 G1–G8 封口状态 / DoD 九段链 / BLOCKED 与证据 | 开发者 |

## 归档

各阶段的审计 / 评审 / 交付报告见 [archive/](archive/README.md) —— 它们是**当时的既定事实记录，不随版本更新**；
查当前行为一律以上表为准。
