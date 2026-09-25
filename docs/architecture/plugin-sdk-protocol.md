# ADR-009 语言无关 Plugin Protocol v1 与五语言 SDK

**状态**：已实施 · **日期**：2026-09-25 · **对应任务书**：第 2 份（多语言 Plugin SDK）§三–§十五

## 要回答的问题

1. 插件与引擎之间用什么通信方式？（现有 exec runner 已经能跑 13 种语言的最小插件，是推倒重来还是形式化？）
2. 其它语言 SDK 的能力如何与 Python **对齐**，而不是"Python 有、别人没有"？
3. 如何证明"真的跨语言"，而不是 mock 出来的兼容？

## 决定了什么

**通信方式：JSON-Lines over stdio**（一行一个 JSON、UTF-8、写完立即 flush；stdout 只放协议，日志走 stderr）。

- 协议本身形式化为 `src/plugins/protocol.py`（必需 4 + 可选 11 方法、错误模型、版本协商、能力握手），
  规范文档 `docs/plugin-protocol.md`；runner 内联一份常量并由测试逐项比对，杜绝"文档一套、实现一套"。
- 能力握手：插件在 `initialize` 里声明 `capabilities`；**引擎绝不调用未声明的可选方法**。
- 五语言 SDK（TypeScript / Go / Rust / Java + Python runner）全部**零第三方依赖**；
  契约测试用同一批向量驱动五种语言的**真子进程**。

### 被否决的方案

| 方案 | 为什么否决 |
| :--- | :--- |
| gRPC / Protobuf | 需要为每种语言引入运行时与代码生成；插件作者要先装工具链，违背"零依赖"与"任何语言都能实现" |
| HTTP / WebSocket 回调插件 | 插件要自己起服务器、自己管端口与生命周期；与任务书 §十"HTTP 由 Runtime 负责"直接冲突 |
| 只在 Python 里做，其它语言"适配补丁" | 任务书第 2 份的核心原则明确反对："Flowerie 不应该成为 Python Bot 框架 + 四个语言适配补丁" |
| 自定义二进制帧 | 没有收益，调试与跨语言实现成本反而更高（JSON 的可读性直接降低了插件作者的排错成本）|

## 诚实边界（这次**没有**证明什么）

- 只证明了**这五种语言**；"任何语言都能实现"是设计推论，没有对 13 种之外的其它语言做端到端验证；
- 能力对等是**协议层**的（11 项可选方法 + 具名钩子语义）；语言习语层面的便利（如 Python 的 160+ 动作包装）
  刻意不做多语言复制，对照表见 [../plugin-sdk.md](../plugin-sdk.md) §6；
- 真机（协议端）相关行为不在本 ADR 范围（那属于上一轮任务书的实机门槛，本环境无协议端，如实标 BLOCKED）。

## 实施中踩到的坑（后人成本主要在这里）

1. **Go：反向请求自锁** —— 读循环与请求处理挤在同一个 goroutine，插件一发 `engine op` 就
   "all goroutines are asleep - deadlock!"。修法：读循环独立 goroutine，应答立即投递、请求排队顺序处理。
2. **Rust：hook 闭包拿不到上下文** —— `Fn(&[Json]) -> Json` 让示例只能返回写死的 null；
   改成 `Fn(&Context, &[Json]) -> Json`，并用 `plugin.webui()` 注册器暴露 WebUI 通道。
3. **TypeScript：CI 的 tsc 没有 `@types/node`** —— `TS2307` ×3 + `TS2580` ×6；
   自研最小宿主声明 `sdk/typescript/shims/node.d.ts`，run.sh 在缺 `@types/node` 时自动带上。
4. **Java：lambda 形参不能与 `main(String[] args)` 重名** —— javac 直接拒绝编译（CI 抓到）。
5. **示例口径漂移**：Go/Java/Rust 的 WebUI 处理器一开始用插件自己的 `ctx.pluginId`（= unknown），
   没有用引擎给的 `context.plugin.id` —— 多语言一致性用例当场抓住（这正是"真跑"的价值）。
