# ADR-004：虚拟协议实验（TestProtocolAdapter / PEC 测量）

- **状态**：已实施（首版）｜**日期**：2026-08-09｜**对应 Gate**：E（PEC=0）、F（最小接入实验 7+1 项）

## 要回答的问题

任务书 B 部分的 Gate E/F 问的是一个**结构性**问题，而不是功能问题：

> 当生态里出现一个新协议（OneBot v12、Satori、Milky 新版本、某个私域协议……），
> 接入它的代价到底是"加一个 Adapter"，还是"改动 Core / Services / SDK / 所有既有插件"？

只靠 OneBot 11 与 Milky 两个**真实**协议回答不了：它们都是本次重构的"当事人"，
Core 里残留的耦合很容易被解释成"历史原因"。于是按任务书要求，**发明一个第三方协议**
（`testproto`）当作"陌生协议"来接入，测量真实成本。它不是 mock —— mock 现有协议会继承现有协议的形状，
无法暴露"Core 偷偷认识协议"的问题。

## 一、虚拟协议长什么样

线格式（虚构，形状贴近真实协议以便覆盖各类能力）：

```json
{
  "kind": "msg",
  "chan": "group:123456",
  "from": 456789,
  "seq": 5,
  "ts": 1700000000,
  "parts": [
    {"t": "text", "v": "hello"},
    {"t": "at",   "v": 10001},
    {"t": "img",  "url": "https://example/a.png", "name": "a.png"},
    {"t": "brand-new-part", "v": {"k": [1, 2]}}
  ]
}
```

- 消息/通知/未知事件三类事件；`parts` 是可扩展段数组（含**未知段**）；
- 通知：`{"kind": "notice", "evt": "poke", "chan": ..., "from": ..., "to": ..., "ts": ...}`；
- 与 OneBot / Milky **字段形状刻意不同**（`chan` 而非 `group_id`、`seq` 而非 `message_id`、
  `from` 而非 `user_id`）—— 如果 Core 里还留着协议字段名，立刻会暴露。

实现（3 个文件，全部自包含）：

| 文件 | 内容 |
| :--- | :--- |
| `src/adapters/testkit/test_protocol.py` | `TestProtocolEventParser`（线格式 → `InternalEvent`）、`TestProtocolChannel`（不联网的发送/撤回记录）、`test_protocol_descriptor()`（能力声明） |
| `src/adapters/testkit/__init__.py` | 公开导出 |
| `src/adapters/contract.py`（改） | `testproto_under_test()` 登记进 `all_adapters()` |

**关键约束**：testkit 只允许 import `src.adapters.proto`（领域契约）与 `src.adapters.capabilities`（能力模型），
不允许 import 任何业务层 —— 有一条测试（`test_pec_static_testkit_is_self_contained`）直接扫源码 import 行钉住它。

## 二、PEC 的口径与测量结果

**PEC（Protocol Extension Cost）**：接入一个新协议需要修改的
**Core / Services / SDK / 既有插件**文件数。阈值：**0**。

用三种互补口径测量（三种都过才算 PASS，避免"口径选得巧"）：

| # | 口径 | 做法 | 实测 | 结论 |
| :--- | :--- | :--- | :--- | :--- |
| 1 | 静态口径（任何环境可跑） | 扫 `src/core`、`src/services`、`src/sdk`、`src/plugins`、`plugin_sdk` 全部 `.py`，查找标记词 `testproto` / `testkit` / `TestProtocol` | 命中 **0** | ✅ |
| 2 | 自包含口径 | 扫 testkit 的 import 行，非 `src.adapters.*` 的 `src.` 依赖 | **0** | ✅ |
| 3 | 变更口径（本地 git 可用时） | `git diff --name-only HEAD` 列出本轮实际改动文件，逐条核对是否落在允许集 `src/adapters/`、`tests/`、`docs/` | 6 个文件全部在允许集内（3 改 + 3 增），禁止层 **0** | ✅ |

**PEC = 0**（口径 1/3 同时成立）。

变更口径的实际清单（本 ADR 所属提交的工作区状态）：
`src/adapters/capabilities.py`、`src/adapters/contract.py`、`tests/test_adapter_contract.py`、
`src/adapters/testkit/__init__.py`、`src/adapters/testkit/test_protocol.py`、`tests/test_pec_experiment.py`
—— 全是 Adapter 层与测试，**没有一行落在 Core / Services / SDK / 插件**。

> CI 是浅克隆，口径 3 会自动 `skip`（而不是伪造 0）；本地与 CI 都以口径 1 为硬断言。

## 三、Gate F：最小接入实验（7 项 + 1）

新协议接入后，用同一个测试文件跑完"一个协议该有的全部基本动作"：

| # | 实验 | 断言 | 结果 |
| :--- | :--- | :--- | :--- |
| 1 | 文本接收 | `kind/scope/group_id/actor_id/text/is_mentioned/mentions` 全部正确归一 | ✅ |
| 2 | 文本发送 | 走通道发出，载荷映射正确（`send_message` + `parts`） | ✅ |
| 3 | 图片接收 | `images`（URL）与 `image_files`（文件名）分别落到领域字段 | ✅ |
| 4 | 未知段 | `("brand-new-part", {"k": [1, 2]})` 原样进 `segments_summary`，不丢不炸 | ✅ |
| 5 | 未知事件 | `kind` 原样保留（`future_kind`），`raw_data` 逐字段保真 | ✅ |
| 6 | 撤回 | 撤回动作经通道记录，语义与 OneBot/Milky 一致 | ✅ |
| 7 | 能力查询 | `capabilities.supports("message.send")` = True、`forward.send` = False、覆盖率 100% | ✅ |
| 8 | **Core 消费者真跑**（补充项） | 虚拟协议事件喂给 `src/core/message_assembler.py` 的 `MessageAssembler`，Core 零改动产出可读文本 | ✅ |

## 四、第 8 项为什么最重要

前 7 项证明"Adapter 能把新协议翻译成领域对象"；第 8 项才证明**领域对象真的被 Core 消费**：

```text
testproto 线格式 → TestProtocolEventParser → InternalEvent → MessageAssembler（src/core，零改动）→ 文本
```

Core 侧的代码在本轮**一个字都没改**（口径 1/3 已证明），而它能直接消费陌生协议的输入。
这就是"Normalized Model 是真实边界"的实证，而不是文档承诺。

## 五、新增一个协议到底要写什么

本次新增协议的完整清单（可当作未来的接入 checklist）：

1. `EventParser`：线格式 → `InternalEvent`（复用 `as_event_dict` / `to_int` 做输入容错）；
2. `AdapterDescriptor` + `CapabilitySet`：18 项能力显式声明五态（`unknown ≠ unsupported`）；
3. 动作通道：在 `src/transport/action_channels.py` 增加该协议的发送/撤回映射（Transport 层，唯一读协议开关处）；
4. 契约登记：在 `src/adapters/contract.py` 加一行 `AdapterUnderTest`。

**第 4 步是本次重构的直接收益**：登记一行之后，12 项契约测试 ×`all_adapters()`
自动覆盖新协议 —— 契约测试从 36 项涨到 **48 项**（4 适配器 × 12），一行代码换来 12 项回归保护。

## 六、诚实边界（本轮**没有**证明的事）

| 未证明 | 说明 | 归属 |
| :--- | :--- | :--- |
| "真实第三方协议接入一律 0 改动" | 虚拟协议与现有协议一样，都能被现有 Normalized Model 表达。真实协议若出现模型无法表达的形状，就需要扩展领域字段（Core 的合法演进），那部分成本不计入 PEC 而由 Gate I（Normalized Message 覆盖率）量化 | [INFERENCE] 明确标出，不当作已证明 |
| 真实收发链路 | 8 项实验全部在进程内（`inproc` 通道），**没有**经过真实网络与真实协议端；"发出去并被收到"仍属 G5/G6，当前 BLOCKED（设备未授权，见 docs/protocol-gap-closure.md §6） | [FIXTURE] |
| 契约第 7/8 项 | 仍是静态探查（源码标记存在性），不是实机验证（同 ADR-003 的说明） | [CODE] |

PEC=0 证明的是**结构性事实**：新增协议的差异被完整隔离在 Adapter + Transport 内，
Core/Services/SDK/既有插件无需知道它的存在。它不是"接入任何协议都零成本"的证明。

## 七、复现方式

```bash
python3 -m pytest tests/test_pec_experiment.py -q          # 11 项（Gate E 3 + Gate F 8）
python3 -m pytest tests/test_adapter_contract.py -q        # 49 项（4 适配器 × 12 + 汇总）
```

## 八、实施中踩到的坑（值得记录）

- **pytest 会把 testkit 的符号当测试收集**：`TestProtocolEventParser`、`TestProtocolChannel`
  以 `Test` 开头，`test_protocol_descriptor` 以 `test_` 开头；它们被 import 进 `tests/` 命名空间后，
  pytest 会把函数当用例收集（返回值触发 `PytestReturnNotNoneWarning`）、把类当测试类扫描
  （`PytestCollectionWarning`）。修法是 pytest 官方机制：类/函数上显式声明 `__test__ = False`。
  接入新协议时若发现"用例数莫名多了一个"，先查这里。
- **异步用例的写法**：`asyncio.get_event_loop()` 在新版本 Python 上不再隐式创建事件循环（直接 `RuntimeError`），
  统一改用仓库既有的 `@pytest.mark.asyncio` 写法。
