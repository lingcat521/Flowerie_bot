# Adapter 架构（协议归一化层）

> 交付物④（任务书 §22.4 / §十六依赖方向）。本文描述 Flowerie 现状分层、归一化契约、扩展步骤，
> 以及**尚未做**的部分与理由。全部结论有代码/测试实测支撑。

## 1. 硬约束（任务书 §十六）

```
Plugin SDK → Core / Event / Session → Adapter → OneBot 11 / Milky / 具体客户端
```

- Core 与业务层**不得** import 任何具体客户端代码；
- 客户端差异**只能**在 Adapter 层出现；
- 归一化后的 `InternalEvent` 是 Core 唯一认识的消息形态。

**实测核查（本轮）**：`grep -rn "import.*napcat\|import.*milky\|from.*napcat" src/` → **无命中**，
即仓库不存在对客户端源码/包的真实依赖；Core/Services 里出现的客户端名字**全部位于注释或 docstring**
（例如 `websocket_server.py` 的传输层说明、`sanitizer.py` 的 loopback 信任边界说明、
`message_assembler.py` 的 `[CODE]` 证据引用）—— 这些是**证据标注**，不是依赖。

## 2. 目录与职责（现状，实测行数）

| 文件 | 行数 | 职责 |
| :--- | ---: | :--- |
| `src/adapters/proto.py` | 109 | **归一化契约**：`InternalEvent` 数据类 + `EventParser` / `MessageSender` 两个 Protocol |
| `src/adapters/onebot_parser.py` | 250 | OneBot 11 raw → `InternalEvent`（含 Segment 分类、`json`/`face`/`mface`/`poke`/`shake`/`file`/`forward`）|
| `src/adapters/milky_parser.py` | 136 | Milky raw → `InternalEvent` |
| `src/adapters/compat.py` | 49 | 兼容兜底（旧字段/别名容错）|
| `src/adapters/container.py` | 62 | **组合根**：`make_adapters(BOT_QQ, sender)` 装配 parser+sender，业务层不 import 本模块 |

组合根 docstring 明写依赖图（`Settings → Sender → make_adapters → Adapters{parser, sender}`），
并声明「业务层（core/services/repositories）不 import 本模块（反向依赖测试保障）」——
保障测试：见 tests/ 下 adapter 相关用例

## 3. 数据流（接收方向）

```
客户端 → WS/HTTP → 传输层(src/core/websocket_server.py 或 napcat_forward_client.py)
                      │  raw dict（OneBot 或 Milky 原生 JSON）
                      ▼
              Adapter: OneBotEventParser.parse(raw)  /  MilkyEventParser.parse(raw)
                      │  InternalEvent（归一化，字段见 proto.py）
                      ▼
        MessageAssembler（core）：把事件 + 段负载拼成"给模型看的上下文文本"
                      │  文本 / 表情描述 / 卡片 / 转发展开 / 文件正文 / 图片(→Vision)
                      ▼
            MessageRouter（业务，不含任何客户端判断）
```

**关键点**：客户端差异在 `parse()` 内被消化；`MessageAssembler` 只消费**归一化字段**
（`text`/`mentions`/`images`/`faces`/`pokes`/`files`/`json_cards`/`forwards`/`notice_file` 等），
并通过注释保留 `[CODE]` 出处，便于回溯。

## 4. 归一化契约（`InternalEvent` 实况）

| 字段 | 语义 | 主要来源段 |
| :--- | :--- | :--- |
| `text` | 纯文本（at/text 拼合后 strip）| text, at |
| `mentions` | 被 @ 的 QQ（含 all）| at |
| `images` / `image_files` | 图片 URL（兼容视图）/ 本地 file（识别优先）| image |
| `faces` | QQ 表情与商城表情（`kind` 区分）| face, mface |
| `pokes` | **消息段形态**的戳一戳（含 `shake`）| poke, shake |
| `files` | 文件段（file_id/name/size/url/path）| file |
| `json_cards` | JSON/Ark 卡片（`app` + `is_forward_card` + payload）| json |
| `forwards` | 合并转发段（`id` / 是否内联）| forward |
| `reply_id` / `target_id` / `operator_id` | 引用 / 被戳者等边界提取 | reply, notice |
| `notice_file` | 上传通知携带的文件对象 | notice/group_upload |
| `raw_data` / `message_segments` / `segments_summary` | 原始与兼容通道（**保留**：旧测试与旧插件依赖）| — |

**注意**：新字段与 `segments_summary` **并存**（同一个段会被分类进新字段，同时仍追加一条 summary 元组），
这是刻意的向后兼容决策 —— 见 `529e6ae`（回归修复提交）。

## 5. 发送方向

- 统一入口：`Sender.send_msg_raw()`（`src/services/sender.py:229`），由 `MessageSender` Protocol 约束；
- 上层只表达"发给谁 + 发什么（段/文本/图片路径）"，**不判断客户端类型**；
- 已知协议差异（待纳入发送侧规则）见 `docs/protocol-reverse-engineering.md` §7：
  NapCat `SendMsg.ts` L413-420 规定 **FILE / VIDEO / ARK / PTT 必须单独成条**；
  Flowerie 目前未对该规则做发送侧拆分（**待办，见 §7**）。

## 6. 接入一个新客户端的标准步骤（可操作清单）

1. **取证**：拿到客户端源码，定位"协议出口"（如 NapCat `SendMsg.ts`、LLBot `incoming.ts`），
   记录文件+行号，按 `[CODE]` 标注；
2. **采样**：把真实事件 JSON 存进 `tests/fixtures/<client>/`（脱敏后），标明来源与状态；
3. **映射**：写 `parse()`，逐段对照本文 §4 表；无法确定的字段**填 `[UNKNOWN]` 并保留原文**，不要猜；
4. **回归**：跑 `tests/test_adapter_segment_normalization.py` 同形用例 + 全量 pytest；
5. **文档**：更新 `docs/client-compatibility.md` 与 `docs/source-acquisition.md`（含失败状态）。

## 7. 尚未做的与理由（诚实清单）

| 项 | 状态 | 理由 / 阻塞 |
| :--- | :--- | :--- |
| 发送侧"独占消息"规则（FILE/VIDEO/ARK/PTT）| **未实现** | 需先确认 Flowerie 现有调用点是否可能混发；规则来源为 NapCat `[CODE]`，属客户端约束 |
| 多段卡片合并策略 | **未定** | 一条消息含多个 `json` 段时，`_assemble_card` 目前只处理第一个；是否合并需真实样本佐证 |
| 能力声明（capability）系统 | **未实现** | 任务书 §十四提到；当前规模下 parser 直接判定即可，过早抽象无收益 |
| Android 端客户端（OpenShamrock 等）| **SOURCE_UNAVAILABLE** | 仓库需鉴权克隆失败，差异保持 `[UNKNOWN]`，不编造 |

## 8. 证据等级说明

本文结论来源：`[CODE]`（客户端源码实测）、`[MVP]`（本地 MVP 实测）、`[DOC]`（官方文档）、
`[INFERENCE]`（由上述推导）、`[UNKNOWN]`（未验证）。
未验证项一律显式标注，不做"看起来应该如此"的补全（任务书 §20/§22）。
