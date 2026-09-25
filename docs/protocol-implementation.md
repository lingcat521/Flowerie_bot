# 协议实现说明（Protocol Implementation）

> 任务书 `/storage/emulated/0/协议.txt` §十一/§十四/§十五/§十七/§二十三。
> 本文回答一个问题：**客户端差异在代码里到底停在哪一层**，以及为什么 Core 不需要知道客户端名字。

## 1. 分层与依赖方向

```text
Services（sender / router / AI / 记忆 …）        ← 不认识任何客户端
      │ 归一化模型（InternalEvent / GroupMessage / 段数组）
Adapters（协议语义 + 档案 + 出站序列化）          ← 客户端差异**只**在这里
      │ wire 形态（OneBot 11 / Milky / OneBot 12）
Transport（HTTP / WS / 连接与响应包封）           ← 只认识"发出去、收回来"
      │ 字节
协议端（NapCat / go-cqhttp / LLBot / Lagrange / …）
```

规则（有测试与扫描兜底）：

1. `Services` / `SDK` / `Plugins` / `Core` 里**不出现**客户端名字，也不 import 客户端实现；
2. 客户端差异集中在三处：`src/adapters/client_profile.py`（档案）、
   `src/adapters/*_serializer.py`（出站字段收敛）、`src/adapters/*_parser.py`（入站归一化）；
3. 协议端**行为**差异（同一个字段不同含义）用档案里的 `quirks` 表达，不用 `if client == …`。

## 2. 一次消息往返经过谁

| 阶段 | 位置 | 与客户端差异有关的部分 |
| :--- | :--- | :--- |
| 收到事件 | `src/transport/ws_server.py` / `ws_forward_client.py` | 无（字节 → dict）|
| 解析归一 | `src/adapters/{onebot,milky,onebot12}_parser.py` | **有**：段类型、字段名、命名空间、临时会话来源群 |
| 业务处理 | `src/core/*` / `src/services/*` | 无 |
| 出站构造 | `src/services/sender.py`（今天：原样透传）| 无（由调用方给段数组）|
| 出站序列化 | `src/adapters/onebot_serializer.py` + 档案 | **有**：字段白名单、命名空间、扩展段、越界取值 |
| 发送 | `src/transport/action_channels.py` | 端点映射（Milky action 名）+ 响应包封 |
| 响应解析 | `src/transport/onebot_response.py` | **有**：ok / async / failed 三态与失败字段差异 |

## 3. 归一化模型（Core 只读这些）

- `InternalEvent`（`src/adapters/proto.py`）：kind / scope / **scene** / context_group_id /
  actor / message_id / text / mentions / images / faces / pokes / files / json_cards / forwards /
  records / videos / xmls / reply_* / notice_* / raw_data；
- 语义字段是**跨客户端共同子集**：某个客户端独有的字段（go-cqhttp 的 `temp_source`、
  NapCat 的 `markdown`、Milky 的内联 `reply.segments`）要么映射到最近似的语义字段，
  要么只留在 `raw_data`（业务层禁止读 raw_data）；
- `raw_data` 是 unknown 安全网的底座：解析器**不做**"要么全解析要么丢弃"的赌博。

## 4. 未知数据安全（§十五）的实现方式

| 未知对象 | 行为 | 测试 |
| :--- | :--- | :--- |
| 未知字段 | 保留在原 dict（`raw_data`），已知字段照常解析 | `test_unknown_field_safety` |
| 未知段 | 原样进 `message_segments`，不影响其它段 | `test_unknown_segment_safety` |
| 未知事件 | `kind` 原样保留（不塌缩成 `unknown`）| `test_unknown_event_safety` |
| 未知响应 | `parse_onebot_response` 返回 `ok=False + 原因`，不抛异常 | `test_unknown_response_safety` |
| 未知段（出站）| 原样传递 + note（不复刻客户端兜底）| `test_unknown_segment_serialization_is_passthrough` |

## 5. 客户端档案（ClientProfile）怎么进入运行时

```python
profile = profile_for("onebot11", "go-cqhttp")     # 未调查 → 空档案（全 UNKNOWN）
profile.state("record")        # SUPPORTED / PARTIAL / UNSUPPORTED / UNKNOWN
profile.quirk("record_send_fields")   # ["file"] —— 上报有 url，发送侧只读 file
```

- 档案是**纯数据**（不 import 任何客户端代码），因此可以被测试、被文档生成器、被未来的配置开关复用；
- 文档里的矩阵由 `render_matrix()` 生成，并有漂移测试逐字比对 ——
  **文档不可能在代码之外单独漂移**。

## 6. 契约与语料的组织

```text
tests/fixtures/<client>/            # 事件语料（带 _provenance：client/status/captured/evidence/note/source）
tests/fixtures/<client>/actions/    # 响应包封语料（不是事件，语料回归只扫一层）
tests/test_fixtures_corpus.py       # 溯源强制 + 按目录选解析器
tests/test_client_contract_matrix.py# Client × Capability × Direction + Unknown 安全 + 文档漂移
tests/test_onebot_serializer.py     # 出站字段收敛 + fixture 往返
tests/test_onebot_response_contract.py # 响应三态矩阵
```

## 7. 协议耦合度量（§二十一：Client Imports = 0，**已可执行**）

规则与度量都在 `tests/test_protocol_coupling.py` 里（三条规则 + 一次度量输出），
口径：**注释与字符串不计**（引用客户端源码行号是任务书要求，不能算耦合）。

当前实测（commit `4741794` 之后）：

| 层 | 代码级客户端名命中 | 说明 |
| :--- | ---: | :--- |
| `src/core` | **0** | 核心不认识任何客户端 |
| `src/services` | **0** | 本轮清掉最后一处：`decode_napcat_file_response` → `decode_base64_json_file_response`（按行为命名，客户端事实留在注释与 Adapter）|
| `src/sdk` | **0** | |
| `src/plugins` | **0** | |
| `src/adapters` | 11 | **允许**：档案/序列化/解析都在这里 |
| `src/transport` | 1 | **允许**：端点映射 |
| `src`（全部）里的 `import` 客户端实现 | **0** | §十一 的第一条硬规则 |

三条可执行规则：

1. `test_no_client_implementation_imports` —— `src/` 不得 import 任何客户端实现；
2. `test_client_names_do_not_leak_into_core_layers` —— Core/Services/SDK/Plugins 的**代码**里不得出现客户端名
   （例外清单 `ALLOWED_CODE_MENTIONS` 当前为空，加一条必须写理由）；
3. `test_no_per_client_branching_in_core_layers` —— 不得出现 `== "napcat"` 这类按客户端分支（§九：走 ClientProfile）。

度量输出示例（`pytest tests/test_protocol_coupling.py -q -s`）：

```text
协议耦合度量（代码级；注释与字符串不计）：
  src/core         代码级客户端名命中 0
  src/services     代码级客户端名命中 0
  src/sdk          代码级客户端名命中 0
  src/plugins      代码级客户端名命中 0
  src/adapters     代码级客户端名命中 11
  src/transport    代码级客户端名命中 1
  src（全部）        import 客户端实现 0
```

## 8. 明确还没做的（如实）

1. **出站序列化尚未接入发送热路径**：两个序列化器（`onebot_serializer` / `milky_serializer`）已有契约与往返测试，
   但 `Sender.send_msg_raw()` 仍原样透传段数组；接入需要"按配置选择 profile"的开关 + CI 验证（下一轮）；
2. **实机验证全缺**：本环境没有可运行的协议端 → 所有客户端行为结论都是源码级 `[CODE]` 或官方文档 `[DOC]`，
   实机项一律 `BLOCKED BY EXTERNAL DEPENDENCY`（见 [client-compatibility.md](client-compatibility.md)）；
3. **未调查的客户端仍是 UNKNOWN**：onebots / Yogurt / OpenShamrock（源码不可得）/ imhelper 等；
   查询它们的档案得到空档案（全 UNKNOWN），**没有**任何"应该也能用"的推断；
4. **Lagrange.OneBot 实现源码不可得**（[source-acquisition.md](source-acquisition.md) C4）→ 该列只有文档级证据，
   大量格子保持 UNKNOWN；Milky 侧的 Lagrange 实现（内嵌）不受影响；
5. **最终报告未写**：§二十四 的量化指标（覆盖率 / 测试数 / 阻塞项 / 证据等级分层）在下一轮汇总，
   数字来源就是本文件 §7、[client-compatibility.md](client-compatibility.md) §4.x 与各测试的打印输出。
