# 协议实现说明（Protocol Implementation）

> 核对版本 **v2.3.0**。任务书 `/storage/emulated/0/协议.txt` §十一/§十四/§十五/§十七/§二十三。本文回答一个问题：**客户端差异在代码里到底停在哪一层**，以及为什么 Core 不需要知道客户端名字。

## 1. 分层与依赖方向

```text
Services / Core / SDK / Plugins        ← 不认识任何客户端（只读归一化模型：InternalEvent / GroupMessage / 段数组）
      │
Adapters（协议语义 + 客户端档案 + 出站序列化）← 客户端差异**只**在这里（wire 形态：OneBot 11 / Milky / OneBot 12）
      │
Transport（HTTP / WS / 连接与响应包封）  ← 只认识"发出去、收回来" → 字节 → 协议端（NapCat / LLBot / Lagrange / …）
```

规则（有测试与扫描兜底）：① `Services` / `SDK` / `Plugins` / `Core` 里**不出现**客户端名字，也不 import 客户端实现（`tests/test_protocol_coupling.py`）；② 客户端差异集中在三处 —— `src/adapters/client_profile.py`（档案）、`src/adapters/*_serializer.py`（出站字段收敛）、`src/adapters/*_parser.py`（入站归一化）；③ 协议端**行为**差异（同一字段不同含义）用档案里的 `quirks` 表达，不用 `if client == …`。

## 2. 一次消息往返经过谁

| 阶段 | 位置 | 与客户端差异有关的部分 |
| :--- | :--- | :--- |
| 收到事件 | `src/transport/ws_server.py` / `ws_forward_client.py` / `milky_ws_client.py` | 无（字节 → dict）|
| 解析归一 | `src/adapters/{onebot,milky,onebot12}_parser.py` | **有**：段类型、字段名、命名空间、临时会话来源群、请求类字段 |
| 业务处理 | `src/core/*` / `src/services/*` | 无 |
| 出站构造 | `src/services/sender.py`（`_prepare_outgoing`）| 无客户端名：只调注入的适配器，notes 写日志 |
| 出站序列化 | `src/adapters/{onebot,milky}_serializer.py` + `client_profile` + `outgoing.py`（路由）| **有**：字段白名单、命名空间、扩展段、越界取值；**经组合根 `main.py:123-126` 注入 Sender**（`CLIENT_PROFILE=""` 时完全不生效）|
| 发送 / 响应解析 | `src/transport/action_channels.py` / `src/transport/onebot_response.py` / `src/transport/milky_response.py` | 端点映射（`_MILKY_ACTIONS` 36 条）+ ok / async / failed 三态与失败字段差异（两套响应模型不通用）；`action_channels` 是**唯一**读取 `QQ_PROTOCOL` / `SEND_VIA_WS` 的地方 |

**传输层 8 项契约**（`src/transport/contract.py` + `tests/test_transport_contract.py`）：`connect / disconnect / send / receive / request / authentication / error / reconnect` —— 每项必须 implemented 或标 `N/A` + 理由（`check_transport_contract()` 把 missing 与 N/A 分开统计）。`WebSocketTransport`（`transports.py`）**8/8 implemented**；`HTTPTransport` **6 implemented + 2 N/A**（`receive` 无推送通道、`reconnect` 的等价能力是请求级 `RetryPolicy`）；`ws_server.py` / `ws_forward_client.py` / `milky_ws_client.py` **未迁移** —— 仍是各自一套 API 的旧连接类，契约只覆盖两个参考实现。

## 3. 归一化模型（Core 只读这些）

- `InternalEvent`（`src/adapters/proto.py`，149 行）：`kind / scope / scene / context_group_id / group_id / actor_id / message_id / timestamp / text / mentions / images / image_files / reply_id / reply_ref / reply_segments / reply_text / notice_kind / request_kind / request_scene / request_id / request_uid / request_filtered / comment / lifecycle_kind / operator_id / target_id / notice_file / is_mentioned / is_reply_to_bot / has_reply_to_other / has_at_others / faces / pokes / files / json_cards / forwards / records / videos / xmls / segments_summary / message_segments / raw_data`；
- 语义字段是**跨客户端共同子集**：客户端独有字段（go-cqhttp 的 `temp_source`、NapCat 的 `markdown`、Milky 的内联 `reply.segments`）要么映射到最近似的语义字段（`context_group_id` / `text` / `reply_segments`），要么只留在 `raw_data`（业务层禁止读 `raw_data`）；`raw_data` 是 unknown 安全网的底座 —— 解析器**不做**"要么全解析要么丢弃"的赌博。

## 4. 未知数据安全（任务书 §十五）的实现方式

| 未知对象 | 行为 | 测试（`tests/test_client_contract_matrix.py`）|
| :--- | :--- | :--- |
| 未知字段 | 保留在原 dict（`raw_data`），已知字段照常解析 | `test_unknown_field_safety` |
| 未知段 | 原样进 `segments_summary`，不影响其它段 | `test_unknown_segment_safety` |
| 未知事件 | `kind` 原样保留（不塌缩成 `unknown`）| `test_unknown_event_safety` |
| 未知响应 | `parse_onebot_response` 返回 `ok=False + 原因`，不抛异常 | `test_unknown_response_safety` |
| 未知段（出站）| 原样传递 + note（不复刻客户端兜底）| `test_unknown_segment_serialization_is_passthrough` |

## 5. 客户端档案（ClientProfile）怎么进入运行时

```python
profile = profile_for("onebot11", "napcat")          # 已调查 → 该客户端档案（[CODE]）
profile = profile_for("onebot11", "some-new-client") # 未调查 → 空档案（全 UNKNOWN，不假装支持）
profile.state("record")        # SUPPORTED / PARTIAL / UNSUPPORTED / UNKNOWN
profile.quirk("record_send_fields")   # ["file"] —— 上报有 url，发送侧只读 file
```

- 档案是**纯数据**（不 import 任何客户端代码），可被测试、文档生成器、未来的配置开关复用；已登记：OneBot 11 = `spec/go-cqhttp/napcat/llbot/lagrange`，Milky = `spec/llbot/lagrange`（`src/adapters/client_profile.py` 的 `PROFILES`）；
- 文档里的矩阵由 `render_matrix()`（`client_profile.py:201`）生成，`tests/test_client_contract_matrix.py:179-186` 逐字比对 —— **文档不可能在代码之外单独漂移**。

## 6. 契约与语料的组织

```text
tests/fixtures/<client>/             # 事件语料（42 个文件带 _provenance：client/status/captured/evidence/note/source）
tests/fixtures/<client>/actions/     # 响应包封语料（不是事件，语料回归只扫一层）
tests/test_fixtures_corpus.py        # 溯源强制 + 按目录选解析器；test_client_contract_matrix.py # Client × Capability × Direction + Unknown 安全 + 文档漂移
tests/test_adapter_contract.py       # 12 项 Adapter 契约 × 4 个适配器（onebot11 / milky / onebot12 / testproto）
tests/test_onebot_serializer.py      # 出站字段收敛 + fixture 往返；tests/test_onebot_response_contract.py # 响应三态矩阵（语料 go-cqhttp/actions/）
tests/test_transport_contract.py     # 传输 8 项契约 + WS/HTTP 行为（进程内假连接，不联网）
```

## 7. 协议耦合度量（任务书 §二十一：Client Imports = 0）

规则与度量都在 `tests/test_protocol_coupling.py`（4 条规则 + 一次度量输出），口径：**注释与字符串不计**（引用客户端源码行号是任务书要求，不能算耦合）。本机实测（commit `4741794` 之后口径未变；`python3 -m pytest tests/test_protocol_coupling.py -q -s`，5 passed）：

| 层 | 代码级客户端名命中 |
| :--- | ---: |
| `src/core` / `src/services` / `src/sdk` / `src/plugins` | 0 / 0 / 0 / 0 |
| `src/adapters`（**允许**：档案 / 序列化 / 解析）| 11 |
| `src/transport`（**允许**：端点映射）| 1 |
| `src`（全部）里的 `import` 客户端实现 | 0 |

三条可执行规则：`test_no_client_implementation_imports`（`src/` 不得 import 客户端实现）、`test_client_names_do_not_leak_into_core_layers`（Core/Services/SDK/Plugins 的**代码**里不得出现客户端名；例外清单 `ALLOWED_CODE_MENTIONS` 当前为空，加一条必须写理由）、`test_no_per_client_branching_in_core_layers`（不得出现 `== "napcat"` 这类分支，走 ClientProfile）。

## 8. 明确还没做的（如实）

1. **实机验证全缺**：本环境没有可运行的协议端 → 所有客户端行为结论都是源码级 `[CODE]` 或官方文档 `[DOC]`，实机项一律 `BLOCKED BY EXTERNAL DEPENDENCY`（[protocol-gap-closure.md](protocol-gap-closure.md) §6、[client-compatibility.md](client-compatibility.md)）；
2. **能力缺口**（`src/adapters/capabilities.py` 的显式声明）：OneBot 11 `forward.send` / Milky `image.send` `file.send` `forward.send` = `unsupported`（upload 管道未接线或协议端明确不支持）；`face.send` / `market_face.send` / OneBot `file.send` = `partial`（只能调用方自拼段数组）；OneBot 12 全部 send = `unsupported`、多数 receive = `unknown`（骨架未接入组合根，`container_wired=False`）；
3. **传输契约未覆盖旧连接类**：`ws_server.py` / `ws_forward_client.py` / `milky_ws_client.py` 仍是各自一套 API（8 项契约只由 `transports.py` 两个参考实现满足，见 §2）；
4. **未调查的客户端仍是 UNKNOWN**：onebots / Yogurt / imhelper 等（`docs/client-compatibility.md` §6.2）；查询它们的档案得到空档案（全 UNKNOWN），**没有**任何"应该也能用"的推断；**OpenShamrock 源码不可得**（上游 404）→ Android 端 OneBot11 差异保持 `[UNKNOWN]`；
5. **Lagrange.OneBot 实现源码不可得**（[source-acquisition.md](source-acquisition.md) C4）→ 该列只有文档级证据（页面自称过时），大量格子保持 UNKNOWN；Milky 侧的 Lagrange 实现（内嵌两份副本）不受影响。

