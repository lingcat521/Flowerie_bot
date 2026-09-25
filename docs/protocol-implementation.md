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

## 7. 明确还没做的（如实）

1. **出站序列化尚未接入发送热路径**：`Sender.send_msg_raw()` 目前原样透传段数组；
   接入需要"按配置选择 profile"的开关 + CI 验证（计划中的下一步）。
2. **Milky 出站序列化**未实现（本轮只做了 OneBot 11）；Milky 侧目前只有入站归一化与动作名映射。
3. **实机验证全缺**：本环境没有可运行的协议端 → 所有"客户端实际行为"都是源码级 [CODE]，
   实机项在 [client-compatibility.md](client-compatibility.md) 与最终报告里标 BLOCKED。
4. `docs/reverse-engineering/` 目前只有 go-cqhttp 一份；NapCat / LLBot / Lagrange / Milky 各客户端
   文档在后续轮次补齐（内容大部分已在 [protocol-reverse-engineering.md](protocol-reverse-engineering.md) 里，
   需要按 §二十三 的八段格式重整）。
