# OneBot 12 研究报告（G8）

> **状态：`NOT_REAL_DEVICE_VALIDATED`** —— 规范级研究 + 骨架适配器（`src/adapters/onebot12_parser.py`）已完成，但**没有真实 v12 实现可联调**，
> 且骨架**未接入生产**：`QQ_PROTOCOL` 只认 onebot/milky（`main.py:131`、`main.py:242`），全仓引用 onebot12 的只有 `src/adapters/{capabilities,contract}.py` 与 tests。因此不得声称 "OneBot 12 supported"。

## 1. 源码获取（`[DOC]`）
`botuniverse/onebot-12` / `specification` / `onebot-v12` 三个候选仓库 `git ls-remote` 均失败；最终取得 **`botuniverse/onebot` @ `d533f0f`**（v12 规范正文，文档站 `12.onebot.dev`）：`specs/connect/`（通信与数据协议）+ `specs/interface/`（消息/用户/群/频道/文件接口定义）。

## 2. v11 / v12 / Flowerie 对比表
| 项目 | OneBot 11 | OneBot 12 | Flowerie 现状 |
| :--- | :--- | :--- | :--- |
| **事件信封** | `post_type` + `message_type`/`notice_type`/`request_type`；`time`(int)；`self_id`(int) | `id` + `type`(meta/message/notice/request) + `detail_type` + `sub_type`；`time`(float64 秒)；`self{platform,user_id}` `[DOC]` | `InternalEvent`：`kind`/`scope`/`scene`/`actor_id`/`group_id`… ✅ 可映射 |
| **ID 类型** | 数字 | **全部字符串**（`user_id`/`group_id`/`message_id`）`[DOC]` | 内部用 `int`；解析器 `int(str)` 转换，失败则 `None` 并保留原始串 `[CODE]` |
| **消息** | 段数组或 CQ 码字符串；有 `raw_message` | 事件里**必须**段数组；请求里可为字符串；另有 `alt_message` 纯文本替代 `[DOC]` | 段数组；`alt_message` 仅在无文本段时兜底 `[CODE]` |
| **@** | `at{qq}` | `mention{user_id}` `[DOC]` | 映射到 `mentions` + `is_mentioned` ✅ |
| **语音/音频** | `record`（单一）| **`voice` + `audio` 两种段** `[DOC]` | 都进 `records`，用 `kind` 区分 `[CODE]`（v11/Milky 无 `kind`）|
| **文件** | `file{file,url?,…}` | `file{file_id,file_name?,…}`；另有 `upload_file`/`get_file` 动作 `[DOC]` | 映射到 `files`；下载动作未接线 |
| **回复** | `reply{id,qq?}` | `reply{message_id,user_id?}` `[DOC]` | `reply_id` + `reply_ref`（保留字符串原值）|
| **转发** | `forward{id}` / `node` | `[UNKNOWN]`（本次未在规范中定位到等价段）| 未映射（不猜）|
| **位置** | 非标准 | **标准段 `location`** `[DOC]` | **模型无载体** → 仅 `segments_summary`（缺口见 §5）|
| **动作** | 端点式（`/send_msg`、`/delete_msg`…）| `{action, params, echo?, self?}`，如 `send_message`/`delete_message` `[DOC]` | `V12_ACTION_MAP` 登记 13 条已核对映射 `[CODE]` |
| **动作响应** | `{status,retcode,data}`（各实现不一）| `{status(ok/failed), retcode(int64), data, message, echo?}`；retcode **分段规范**（0/1xxxx/2xxxx/3xxxx…）`[DOC]` | `normalize_action_response()` 归一为 `{ok,data,error,retcode,echo}` `[CODE]` |
| **鉴权/传输** | WS / WS-reverse / HTTP / HTTP-POST | WS / WS-reverse / HTTP / **HTTP-webhook** `[DOC]` | 已实现 WS-reverse + 正向 WS + HTTP；webhook 未实现 |
| **多机器人** | 单账号约定 | 动作可带 `self`，多账号可共享连接；错误码 `10101 Who Am I` / `10102 Unknown Self` `[DOC]` | 单实例；`src/adapters/instance.py` 的多实例注册表未接生产 |

## 3. 已落地的骨架（`src/adapters/onebot12_parser.py`）
- `OneBot12EventParser.parse()`：信封 → `InternalEvent`（`type`→`kind`、`detail_type`+`sub_type`→`scope`/`scene`、字符串 ID → int、`time` float → int）；未知 `type` **原样保留**（不猜成已知类型）；缺字段不抛异常。
- 段扫描：`text` / `mention` / `mention_all` / `image` / `voice` / `audio` / `video` / `file` / `reply`；其余段（含标准段 `location`）一律进 `segments_summary`，**不丢信息**。
- `V12_ACTION_MAP`：13 条 v11→v12 映射。其中 `get_msg`→`get_message`、`get_group_msg_history`→`get_latest_events` 两处**语义不完全等价**（后者是"拉最新事件"而非"拉历史消息"）；代码只有在 L28-36 一句通用注释「未列出的端点表示尚未核对（保持 `[UNKNOWN]`）」，**未逐条标注** → 需实机核对。
- `normalize_action_response()`：按规范把响应归一成 `{ok, data, error, retcode, echo}`。
- 测试：`tests/test_onebot12_adapter.py`（14 用例）；夹具 `tests/fixtures/onebot12/message_group.json`（`[DOC]` 规格样本，带 `_provenance`）。

## 4. 为什么不能声称 "supported"
- 没有找到可运行的 v12 实现（LibOneBot 系实现未在生态清单核验），**无法做任何实机验证**；规范里的段/动作远多于本骨架覆盖（群组/频道/Guild/文件分片上传等均未接线）；`forward` 的等价表达尚未定位 → `[UNKNOWN]`，不伪造。

## 5. 后续缺口（如实登记）
| 缺口 | 状态 |
| :--- | :--- |
| `location` 段无模型载体 | OPEN（消息模型需新增载体或明确不建模）|
| v12 `forward` 等价段 | `[UNKNOWN]`（规范中未定位）|
| HTTP-webhook 传输 / 多账号共享连接（`self` 路由）| 未实现（后者与 Gate S 多实例相关）|
| 全部动作接线（群组/频道/文件分片）| 未接线（骨架只做映射表）|
