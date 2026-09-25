# ADR-005：TransportContract（8 项传输契约）

- **状态**：已实施（首版）｜**日期**：2026-08-09｜**对应 Gate**：Q（并为 S 多实例铺路）

## 要回答的问题

任务书 Gate Q 要求"建立 TransportContract，至少 8 项：connect / disconnect / send / receive /
request / authentication / error / reconnect，且 WebSocketTransport ≥ 8/8、HTTPTransport ≥ 8/8；
不适用项必须标 N/A 并说明原因"。

这个问题在重构前是真实存在的：传输层有**四套互不相干的 API**——

| 现有实现 | 形状 | 问题 |
| :--- | :--- | :--- |
| `WebSocketServer`（反向 WS） | 起服务、回调 `MessageRouter` | 调用方必须知道它是"服务端" |
| `NapCatForwardClient`（正向 WS） | 连出去、重连循环 | 另一套重连/鉴权写法 |
| `MilkyClient`（Milky WS） | Bearer 鉴权 + 自己解析帧 | 第三种连接约定 |
| `OneBotHTTPChannel` / `MilkyHTTPChannel` | `post(endpoint, payload)` | 第四套（且与协议耦合） |

结果：想换一种传输方式，调用方只能按**类型**分支 —— 这正是 Gate B/Q 要消灭的耦合。

## 决策

### 1. 定义 8 项语义契约（`src/transport/contract.py`）

| # | 项 | 语义（实现者的承诺） |
| :--- | :--- | :--- |
| 1 | `connect` | 成功 True 并进入可用状态；失败 False 且 `error()` 有原因（**不抛给调用方**） |
| 2 | `disconnect` | 幂等；断开后 `send/request` 必须失败而不是静默丢弃 |
| 3 | `send` | 单向发送，不等待业务响应；失败 False + `error()` |
| 4 | `receive` | 返回下一条事件；超时返回 None（不是异常） |
| 5 | `request` | 请求-响应配对，返回 `{'ok','data','error'}`；超时/未连接都不抛 |
| 6 | `authentication` | 返回本次连接应使用的鉴权材料；无鉴权配置返回 `{}` |
| 7 | `error` | 返回最近一次错误描述（可被上层读到，不能只写日志） |
| 8 | `reconnect` | 按退避策略重试；返回是否成功 |

### 2. 三种状态分开统计（关键设计）

`check_transport_contract()` 给每一项打分：

- `implemented`：**类上真实覆盖**了方法。只继承基类占位实现（`NotImplementedError`）算 **missing** ——
  防止"看起来有方法其实没实现"的假通过；
- `N/A`：显式声明不适用，且**必须写理由**（`NA_REASONS`），理由为空视为未交代；
- `missing`：既没实现也没声明。

"没写"和"明确说明不适用"是两件事。Gate Q 的 8/8 指 `covered = implemented + N/A = 8`。

### 3. 两个参考实现（`src/transport/transports.py`）

| 传输 | 实测 | 说明 |
| :--- | :--- | :--- |
| `WebSocketTransport` | **8/8 implemented** | 全双工：连接、收发、`echo` 配对请求-响应、鉴权（header 或首帧 token）、错误可观测、指数退避重连 |
| `HTTPTransport` | **6 implemented + 2 N/A = 8/8 covered** | `receive` N/A：HTTP 没有服务端推送通道（推送由 WS/回调提供）；`reconnect` N/A：HTTP 无长连接，等价能力是请求级重试（`RetryPolicy`） |

两条实现共同的设计约束：

1. **不 import 网络库**：I/O 原语注入（`connector` / `poster`），真实绑定
   （`websockets_connector` / `aiohttp_poster`）放在文件末尾**懒 import**。
   有一条测试用 `sys.meta_path` 拦截器**屏蔽 websockets 与 aiohttp** 后 import 本包，
   证明"传输契约不绑库"；
2. **信封可替换**：`request()` 默认按 OneBot 11 的 `{action, params, echo}` 组帧（`ws_server.py` 现状），
   但 `frame_builder` / `response_reader` 可注入 —— "通用 WS 传输"不再绑定某一种协议信封。

### 4. 包导入改为懒加载（PEP 562）

`src/transport/__init__.py` 对旧连接类（`WebSocketServer` / `NapCatForwardClient` /
`redact_ws_url` / `MilkyClient`）改用模块级 `__getattr__` 懒加载：
`import src.transport.contract` 在**没装 websockets/aiohttp** 的环境里也能成功（本机实测）。
旧写法 `from src.transport import WebSocketServer` 仍然有效，只是推迟到访问时才 import
（缺依赖时如实抛 ImportError，见测试）。

## 被否决的方案

1. **直接把四套实现改造成契约实现**：一次改三条真实连接路径，回归风险大且不好定位；
   改为"先立契约 + 给出参考实现 + 用测试钉住语义"，生产路径迁移单独进行（见"诚实边界"）。
2. **让 HTTPTransport 假装实现 `receive`/`reconnect`**（例如 `receive` 直接返回 None）：
   会把"HTTP 收不到推送"这一事实掩盖掉。显式 N/A + 写明等价能力才是诚实的交代。
3. **调用方按类型分支驱动传输**：契约的意义就是让调用方按**语义**编程；类型分支正是 Gate B 的病灶。
4. **把 N/A 也算 missing**：会让"HTTP 天生不适用"变成永远修不好的红灯，指标失去意义。

## 诚实边界（本轮**没有**做到的）

| 未做到 | 说明 |
| :--- | :--- |
| 生产连接路径未切换 | `main.py` 仍使用旧栈（`WebSocketServer` / `NapCatForwardClient` / `MilkyClient` / 动作通道）。契约与参考实现已就位，迁移是后续独立动作 |
| 无实机联调 | 契约语义全部在进程内用注入式 I/O 验证；**真实网络收发**仍属 G5/G6，当前 BLOCKED（设备未授权） |
| 心跳/半开检测 | 8 项契约里没有心跳项；`WebSocketTransport` 未实现 `ping/pong` 保活 —— 这是已知缺口，不冒充实装 |

## 复现方式

```bash
python3 -m pytest tests/test_transport_contract.py -q     # 19 项（18 通过 + 1 依赖真网络库时跳过）
```

## 实施中踩到的坑

- **Python 3.9 的 `asyncio.Queue()` 不能在无事件循环时构造**：`WebSocketTransport` 把队列创建放进
  `connect()`（那时一定在循环里），而不是 `__init__`；
- **`asyncio.get_event_loop()` 在 3.12+ 无运行循环时不再隐式建循环**（直接 RuntimeError）：
  在协程内统一用 `asyncio.get_running_loop()` 建 Future（与 Gate E/F 的异步用例同类教训）；
- **HTTP 200 但响应体不是 JSON** 必须判为失败：否则协议端的错误页/网关拦截会被当成"成功但没数据"，
  静默吞掉故障（本实现在 `_attempt` 里显式返回 `invalid json response`）。
