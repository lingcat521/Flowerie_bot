# ADR-001：传输层从 Core 搬出（Transport Abstraction）

- **状态**：已实施（本阶段第一步）｜**日期**：2026-08-09｜**对应 Gate**：A / B / P
- **背景**：任务书 B 部分要求 "Transport 必须独立"（§5）与 Gate P "Core 不得直接引用 websocket/aiohttp"。
  实测现状：`src/core/` 下住着三个传输文件且都 `import websockets` ——
  `websocket_server.py`（反向 WS 服务端）、`napcat_forward_client.py`（正向 WS 客户端）、
  `milky_client.py`（Milky 事件 WS 客户端），Gate P 直接 FAIL。

## 决策

1. 新建 `src/transport/` 包，三个文件迁入并改名：
   | 原路径 | 新路径 | 类 |
   | :--- | :--- | :--- |
   | `src/core/websocket_server.py` | `src/transport/ws_server.py` | `WebSocketServer` |
   | `src/core/napcat_forward_client.py` | `src/transport/ws_forward_client.py` | `NapCatForwardClient` / `redact_ws_url` |
   | `src/core/milky_client.py` | `src/transport/milky_ws_client.py` | `MilkyClient` |
2. `ws_server.py` 对 `MessageRouter` 的依赖改为 **`TYPE_CHECKING` 类型注解**：传输层不再在运行期依赖 Core 业务模块
   （依赖方向从 `Transport → Core` 变为"仅类型引用"）。
3. `main.py` 与 3 个测试文件的 import 同步更新；行为**零改动**（纯搬迁 + 类型注解）。

## 为什么不一次拆干净

`ws_server.py` 里还带着 `action/params/echo` 信封（OneBot 约定）。理想形态是
"通用 WS 传输 + OneBot 信封适配器"，但那需要同时改 `sender.py` 的 WS 通道与 `main.py` 装配，
一次做完风险高（任务书 §43：不要大规模重写）。故本步只完成"从 Core 搬出"，信封拆分单独进行。

## 被否决的方案

- **保留文件在 `src/core/` 只加 re-export shim**：Gate A 的静态检查按**文件位置**判定（`src/core/` 下不得有
  以客户端/协议命名的模块），shim 会让检查形同虚设。
- **一步到位拆成 `src/transport/` + `src/adapters/onebot_ws.py`**：会同时改动 sender/main 的装配路径，
  测试面过大，违反"每步保持 tests green"。

## 当前基线（写入 `tests/test_architecture_gates.py`，只许缩小）

| Gate | 现状 | 基线 |
| :--- | :--- | :--- |
| A：Core/Services/SDK/Plugins 的协议 import | 3 处（`sdk/onebot/` 子树 2 处 + `plugins/manager.py` 1 处）| `KNOWN_PROTOCOL_IMPORTS` |
| B：协议分支 | 3 处（均 `services/sender.py`：`if self._milky` ×2、`if self._use_ws` ×1）| `KNOWN_PROTOCOL_BRANCHES` |
| P：`src/core/` 传输库 import | **0** ✅ | 硬性 0 |
| P：`src/services/` aiohttp | 13 个文件（Web UI 应用服务器 + 发送出口）| `KNOWN_SERVICES_AIOHTTP` |
| A：`src/core/` 客户端命名模块 | **0** ✅ | 硬性 0 |
| P：`websockets` 使用者 | 仅 `src/transport/` ✅ | 硬性限 `src/transport/` |

## 未完成的耦合（下一步）

1. `services/sender.py` 的 `if self._milky` 分支 → 下沉为 Adapter 的发送策略（Gate B/O）；
2. `src/sdk/onebot/` 子树 → SDK 不得依赖具体协议（Gate T/§34）；
3. `ws_server.py` 的 OneBot 信封 → 拆到 Adapter；
4. `src/services/` 的 aiohttp：Web UI 部分**不是**协议传输（属应用服务器），已在 ADR 中显式区分，
   基线冻结，允许后续把 Web UI 独立成 app 层（不属本阶段硬门槛）。

## 实施记录与教训（2026-08-09）

本次重构在 CI 上连续暴露三类问题，全部为非功能性但会直接失败：

1. **ruff I001（import 顺序）**：把 \`from src.transport...\` 留在原 \`src.core.websocket_server\` 的位置 →
   模块名排序错误（\`adapters < config < core < repositories < services < transport < utils\`）。
   **本地 flake8 代理只覆盖 F 规则，抓不到 I001**；本地也装不上 ruff（无预编译包）。
   处置：新增 \`~/check_import_order.py\` 作为推送前自检（仅对**同一 import 块**内 \`from src.\` 的字母序告警，
   已知会误报函数内 import 与 \`TYPE_CHECKING\` 块 → 以 CI 的 ruff 为唯一权威）。
2. **TYPE_CHECKING 引发运行时 NameError**：\`message_router: MessageRouter\` 的参数注解在**定义期求值**，
   改成 TYPE_CHECKING 导入后 \`import src.transport.ws_server\` 直接报 \`NameError\`。
   处置：注解改字符串 \`"MessageRouter"\`。**教训：参数注解不是惰性的**，改 TYPE_CHECKING 时必须同步加引号。
3. **本地测试盲区**：本机缺 \`websockets\`，\`src/transport/*\` 与 3 个 WS 测试在本地只能收集失败，
   该类改动**只有 CI 能验证**。处置：涉及传输层的改动一律以 CI 结果为准，本地只跑可导入的测试子集。
