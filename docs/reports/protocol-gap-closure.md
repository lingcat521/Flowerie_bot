# 协议缺口封口台账（Protocol Gap Closure）

> 现行版本 **v2.3.0**（`pyproject.toml:3`）。任务书 `complete&expand.txt` A 部分 §2/§11/§12 要求：**先建台账，再改代码**；每个 Gap 必须走完 DoD 九段链（Source → Model → Fixture → Unit → Round-trip/Reverse → Real → Docs → CI → CLOSED），缺任何一段都不许标 `CLOSED`。本文件是缺口状态的**唯一权威表**，数字必须来自真实测试输出。
>
> 外部引用锚点（**勿改编号**）：`tests/integration/_realenv.py:32`、`tests/integration/README.md:15`、`docs/architecture/acceptance-metrics.md:19`、`docs/architecture/final-acceptance-report.md:86` 引用本文件 **§6 / §6.5**。

## 0. 状态词表（任务书 §2 给定）

`OPEN` / `IN_PROGRESS` / `SOURCE_VERIFIED` / `IMPLEMENTED` / `FIXTURE_VERIFIED` / `INTEGRATION_VERIFIED` / `CLOSED` / `BLOCKED` / `UNKNOWN`

## 1. 基线

| 口径 | 值 |
| :--- | :--- |
| 历史基线（2026-08-09，HEAD `65068c7`）| pytest 837 passed / 19 failed（全部为缺依赖）/ 13 skipped；测试文件 126；fixtures 7 个（带 `_provenance`）；CI 三项（Push on main / Acceptance / CI）success |
| 当前整仓（2026-09-26，v2.3.0）| **2288 passed / 39 skipped**；另有 `tests/sdk` 46、`tests/webui` 102、`tests/e2e` 21（真浏览器）|
| 本台账相关用例（本机实测，命令见 §7）| `test_temp_scene` 12 / `test_request_events` 12 / `test_media_segments` 10 / `test_reply_inline` 9 / `test_onebot12_adapter` 14 / `test_milky_event_kinds.py` 9 |

## 2. 缺口总表

| ID | 缺口 | 初始状态 | 目标 | 证据要求 | 当前状态 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **G1** | Milky `message_scene=temp` | incomplete（`scope=""`）| complete | source + fixture + test | **CLOSED**（CI `9e4a9fc` 三项全绿，2026-08-09）|
| **G2** | Milky 请求类事件字段级映射 | incomplete（只有 kind/request_kind）| complete | source + fixture + test | **CLOSED**（CI 记录见 §5；封口记录 §4.2）|
| **G3** | Milky `record` / `video` / `xml` | incomplete（仅 `segments_summary`）| complete/explicit | source + fixture + test | **CLOSED**（CI `0ad18aa` 三项全绿）|
| **G4** | Milky `reply.segments` | incomplete（只消费 message_seq）| complete | source + fixture + test | **CLOSED**（CI `c2ee950` 三项全绿）|
| **G5** | Milky 多媒体发送（upload→resource_id→send）| no real validation | complete | source + real device | **BLOCKED**（终态：无实机授权，§6）|
| **G6** | 实机 Integration Test（OneBot11 10 + Milky 12）| missing | complete | integration test | **BLOCKED**（终态：同上）|
| **G7** | OpenShamrock | SOURCE_UNAVAILABLE | researched/validated | source/device | **SOURCE_UNAVAILABLE（已确认）**：上游账号与仓库均 404，§6 |
| **G8** | OneBot v12 | not implemented | researched + mapped | spec/source | **CLOSED**（CI `c0065e2` 全绿；携 `NOT_REAL_DEVICE_VALIDATED`）|

**终值 `Gap Closure Rate = 6/8 = 75%`**：G1/G2/G3/G4/G7/G8 CLOSED，G5/G6 BLOCKED（**不写成 CLOSED**）。注：§3 早期把 G1/G2 写作 `IMPLEMENTED`，与 §2/§5/§6.5 的 CLOSED 冲突 —— 以**唯一权威表**（§2）为准，已在 §3 统一。

## 3. DoD 逐项（任务书 §12 表）

| Gap | Source | Model | Fixture | Unit | Roundtrip | Real | Docs | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| G1 temp | ✓ | ✓ | ✓ | ✓ | ✓ | --（不适用）| ✓ | **CLOSED** |
| G2 request | ✓ | ✓ | ✓ | ✓ | ✓ | --（不适用）| ✓ | **CLOSED** |
| G3 media/XML | ✓ | ✓ | ✓ | ✓ | ✓ | --（不适用）| ✓ | **CLOSED** |
| G4 reply.segments | ✓ | ✓ | ✓ | ✓ | ✓ | --（不适用）| ✓ | **CLOSED** |
| G5 media send | — | — | — | — | — | — | — | OPEN |
| G6 real integration | — | -- | -- | -- | -- | — | — | OPEN |
| G7 OpenShamrock | — | — | — | — | — | — | — | OPEN |

> 表中 `—` = 该项**未做/未验证**；`--（不适用）` = 该项对本 Gap 不适用。G5/G6/G7 保持 OPEN，不写成 CLOSED。

| G8 OneBot12 | ✓ | ✓ | ✓ | ✓ | ✓ | --（不适用）| ✓ | **CLOSED**（携 NOT_REAL_DEVICE_VALIDATED）|

## 4. 封口记录（G1–G4 / G8）

### 4.1 G1 —— Milky `message_scene=temp`

**Source** `[DOC]` Milky 规范 `protocol/src/ir/common.ts` L266-291：`IncomingMessage` 以 **`message_scene`** 判别 `friend / group / temp`；temp 变体字段 `peer_id / message_seq / sender_id / time / segments` + **可选** `group` **实体**（L158-168 `GroupEntity.group_id` —— 群是**实体**，不是 `group_id` 标量）；同枚举 L23/L31 亦为 `friend/group/temp`，**规范里没有 `group_temp`**。`[CODE]` LLBot `src/milky/transform/event.ts` L78-80（temp → `peer_id: data.peerUin`）。`[DOC]` OneBot 11 `event/message.md` L16：私聊 `sub_type=group` 即群临时会话，L10-22 私聊字段表**没有 `group_id`**（实现若额外提供，只能当上下文，不能当协议保证）。

**Model** `InternalEvent` 新增 `scene`（group/friend/temp/stranger）与 `context_group_id`：Milky `temp` → `scope="private"` + `scene="temp"` + `actor_id=sender_id` + `context_group_id=group.group_id`（可选），旧别名 `group_temp` 归一成 `temp`；OneBot `private & sub_type=group` → `scene="temp"`，实现带 `group_id` 时记 `context_group_id` 且**不**写 `group_id`。Core 边界（`src/core/message_router.py:237-239`）：`_handle_message` 首行 `if event.scope != "group": return` —— **Core 当前只处理群会话**，故 temp 归一化成"私聊范围"既不丢信息也不冒充群消息；插件事件投递在 scope 判断之前，仍拿得到 `kind=message`。

**Fixture / Test** `tests/fixtures/milky/temp_message_scene.json`（含 group 实体）、`tests/fixtures/onebot11/private_group_temp.json`（规范纯样本，无 group_id）；`tests/test_temp_scene.py` **12 用例**（本机实测）：带/不带群实体（optional）/ `group_temp` 别名归一 / friend+group 不回归 / OneBot temp / 实现带 `group_id` → 上下文 / 跨协议等价（Milky temp ≡ OneBot temp）/ 两 fixture 解析 + provenance / round-trip 稳定 / go-cqhttp `sender.group_id` 路径。

**改动文件**：`src/adapters/proto.py`、`src/adapters/milky_parser.py`、`src/adapters/onebot_parser.py`、`tests/test_temp_scene.py`、两个 fixture。**DoD** Source ✓ Model ✓ Fixture ✓ Unit ✓ Roundtrip ✓ Real（不适用）Docs ✓ → **CLOSED**（CI `9e4a9fc`）。

### 4.2 G2 —— Milky 请求类事件字段级映射

**Source** `[DOC]` Milky 规范 `common.ts` L35-58：`friend_request{initiator_id, initiator_uid, comment, via}`、`group_join_request{group_id, notification_seq, is_filtered, initiator_id, comment}`、`group_invited_join_request{group_id, notification_seq, initiator_id, target_user_id}`、`group_invitation{group_id, invitation_seq, initiator_id, source_group_id?}`。**规范里没有 `request_id` / `flag`**：群请求标识是 `notification_seq`/`invitation_seq`，好友请求**没有标识**（`api/friend.ts` L22-29 用 `initiator_uid` 同意/拒绝）→ 不给它编 flag。`[DOC]` `api/group.ts` L104 `accept_group_invitation` → `group_invitation` 属**请求类**（旧实现归 notice 是错的，本 Gap 纠正）。`[DOC]` OneBot 11 `event/request.md` L10-18（friend：user_id/comment/flag）、L31-41（group：sub_type ∈ add|invite，invite = 邀请登录号入群）→ 与 Milky `group_invitation` 同义。

**Model** `InternalEvent` 新增 5 字段：`request_scene`（friend / group_join / group_invited_join / group_invitation）、`request_id`（OneBot=`flag`；Milky=`notification_seq`/`invitation_seq`）、`request_uid`（Milky `initiator_uid`）、`request_filtered`（Milky `is_filtered`）、`comment`。粗细两档并存：`request_kind` 保持 friend/group（插件/SDK 既有契约不破坏），`request_scene` 表达协议真实语义；两协议都不存在的字段一律留空（`test_absent_fields_are_not_fabricated` 钉住）。

**Fixture / Test** 5 个新 fixture（均带 `_provenance`）：`tests/fixtures/milky/friend_request.json`、`tests/fixtures/milky/group_join_request.json`、`tests/fixtures/milky/group_invited_join_request.json`、`tests/fixtures/onebot11/friend_request.json`、`tests/fixtures/onebot11/group_request_invite.json`；`tests/test_request_events.py` **12 用例**（Milky 四类 / OneBot 三类 / 跨协议等价 / 不伪造 / 夹具 / round-trip）；`tests/test_protocol_roundtrip.py` 扩展请求类重建路径 → 语料 round-trip **0 skip**。

**DoD** Source ✓ Model ✓ Fixture ✓ Unit ✓ Roundtrip ✓ Real（不适用：请求事件无实机语义验证项）Docs ✓ → **CLOSED**。

### 4.3 G3 —— Milky `record` / `video` / `xml` 类型化 Segment

**Source** `[DOC]` Milky 规范 `common.ts` L342-346 `record{resource_id,temp_url,duration}`、L347-353 `video{resource_id,temp_url,width,height,duration}`、L377-380 `xml{service_id,xml_payload}`。`[CODE]` NapCat `napcat-onebot/types/message.ts` L80-86 `FileBaseDataSchema{file,path?,url?,name?,thumb?}`；L106-109 `record` 段 data = FileBaseData（枚举 `voice = 'record'`，**线上值 record**，L8）；L112-115 `video` 同 FileBaseData；L228-233 `xml{data}`。任务书 §5.3（XML 不得塞进 text、不得擅自解析）、§5.4（未知字段不得导致解析失败并要保留）。

**Model** `InternalEvent` 新增 `records` / `videos` / `xmls` 三个段载体，两侧解析器**复用同一组归一化函数**（`_normalize_record_segment` / `_normalize_video_segment` / `_normalize_xml_segment`）保证键名同形：`{resource_id, url, file, path, name, duration, extra}` / `{…+width, height}` / `{service_id, raw_xml, extra}`；`extra` 承载**已知字段之外的全部原始字段**（§5.4 前向兼容），XML 只保真保存（`raw_xml` 原样，**不解析**）。组装层新增 `_assemble_media`（`src/core/message_assembler.py`）：语音/视频/XML 各上限 3 条渲染成一句话，XML 只报 service_id 与字符数。

**Fixture / Test** 4 个新 fixture：`tests/fixtures/milky/segment_record.json`、`tests/fixtures/milky/segment_video.json`、`tests/fixtures/milky/segment_xml.json`、`tests/fixtures/napcat/message_media_segments.json`（一条消息含三种段）；`tests/test_media_segments.py` **10 用例**（Milky 三种段 + extra 保真 + NapCat FileBase/xml + 跨协议语义等价 + Assembler 渲染 + 夹具解析）；`tests/test_protocol_roundtrip.py` 段级比较扩展到 `records/videos/xmls` → round-trip **0 skip**。

**DoD** Source ✓ Model ✓ Fixture ✓ Unit ✓ Roundtrip ✓ Real（不适用）Docs ✓ → **CLOSED**（CI `0ad18aa`）。

### 4.4 G4 —— Milky `reply.segments` 内联被引内容

**Source** `[DOC]` Milky 规范 `common.ts` L327-333：`reply{message_seq, sender_id, sender_name?, time, segments[]}` —— 被引消息的**完整段数组内联**（Milky 独有：无需再调 API 拉引用）。`[DOC]`/`[CODE]` OneBot 侧 `reply` 段**只有 id（+qq）**（`event/message.md`；NapCat `OB11MessageReplySchema`）→ 内联字段必须保持空，**不得伪造**。任务书 §6.2：必须同时保留 `message_seq`。

**Model** `InternalEvent` 新增 `reply_ref`（id/sender_id/sender_name/time）、`reply_segments`（内联段，原样保真、保序）、`reply_text`（内联文本段拼接摘要，上限 200 字符）；原 `reply_id` 不变（Milky=`message_seq`，OneBot=`id`）。组装层新增 `_assemble_quote`：**只有拿到内联文本才渲染** `[引用的消息：…]`，OneBot 侧渲染为空（不编造引用内容）。

**Fixture / Test** `tests/fixtures/milky/reply_with_inline_segments.json`（内联 text+image）、`tests/fixtures/onebot11/reply_segment.json`（无内联，钉住"不许伪造"）；`tests/test_reply_inline.py` **9 用例**（任务书 §6.3 四类：reply+text / reply+image / reply+多段 / reply 无 segments，另加 OneBot 无内联、旧行为不回归、Assembler 渲染、夹具、round-trip）；`tests/test_protocol_roundtrip.py` 增加引用字段比较。

**DoD** Source ✓ Model ✓ Fixture ✓ Unit ✓ Roundtrip ✓ Real（不适用）Docs ✓ → **CLOSED**（CI `c2ee950`）。

### 4.5 G8 —— OneBot 12 研究（CLOSED，目标=研究+映射）

**Source** `[DOC]` 官方规范 `botuniverse/onebot` @ `d533f0f`（`specs/connect/` + `specs/interface/`）；三个候选仓库（`botuniverse/onebot-12` / `specification` / `onebot-v12`）`ls-remote` 均失败，已如实记录在 `docs/onebot12-research.md` §1。

**Model** `src/adapters/onebot12_parser.py` 骨架：事件信封（`id`/`time`/`type`/`detail_type`/`sub_type`/`self`）→ `InternalEvent`；字符串 ID 转换；`alt_message` 兜底；段映射 `text/mention/mention_all/image/voice/audio/video/file/reply`；`V12_ACTION_MAP` 13 条；`normalize_action_response()`。

**Fixture / Test** `tests/fixtures/onebot12/message_group.json` + `tests/test_onebot12_adapter.py`（14 用例）；v12 语料已接入 corpus 与 round-trip 通道（`_rebuild_onebot12`）。

**状态** `IMPLEMENTED` / **`NOT_REAL_DEVICE_VALIDATED`**（无 v12 实现可联调；任务书 §10.2 允许骨架交付，但不得声称 supported）；骨架**未接入组合根**（`src/adapters/contract.py` 的 `container_wired=False`）。研究见 `docs/onebot12-research.md`（含 v11/v12 对比与 5 项后续缺口）。

## 5. 量化指标（任务书 §19/§20/§21）

| 指标 | 定义 | 当前（终值）| 目标 |
| :--- | :--- | :--- | :--- |
| Gap Closure Rate | CLOSED / 8 | **6/8 = 75%**（G1/G2/G3/G4 有 CI 全绿记录；G7 按任务书允许的 `SOURCE_UNAVAILABLE + 真实原因 + 文档研究` 分支结案；G5/G6 = BLOCKED，不是 CLOSED）| 8/8 或明确 BLOCKED |
| Real Integration Coverage | 实机验证能力 / 要求验证能力 | **0% —— BLOCKED BY EXTERNAL DEPENDENCY**（§20 允许的例外分支）；harness 已就绪：`tests/integration/` 22 用例（§8.1 的 10 + §8.2 的 12），本机实测 `22 skipped` 并打印缺失条件 | ≥90% 或 BLOCKED |
| 实机 harness 状态 | §13/§14 | 目录、用例、证据记录器、manual 流程全部就位；**用例从未在真实客户端执行过** → `[UNVERIFIED]`；证据 JSON 目标目录 `tests/integration/evidence/`（`.gitignore` 排除，当前不存在）| 拿到设备后跑 §7 命令 |
| 新增测试（G1–G5）| 任务书 §17 | G1 = 12、G2 = 12、G3 = 10、G4 = 9（要求 G4 ≥4）—— 已 43；G8 另加 14 | ≥19 累计 |

## 6. BLOCKED 记录（G5 / G6 / G7）—— 2026-09-25T08:09Z

任务书 §8.3/§18：无法实机验证时必须明确 BLOCKED，并给出阻塞原因、已验证的源码证据、已尝试步骤、缺失条件。

### 6.1 阻塞原因（三条，独立成立）

1. **设备控制通道未授权**：`android_privilege_status` 返回空结构；`android_device_info` 与 `android_adb_shell_exec` 均 `denied:true` 并给出两条开启路径（① 系统设置 → 无障碍 → 开启「DSH 设备控制」；② 开发者选项 → 无线调试完成 ADB 完全访问 + 配对）→ 无法观察/驱动设备上的任何客户端。
2. **无运行中的协议端与测试账号**：本机没有 NapCat / Lagrange.Milky / LLBot / Yogurt 等协议端进程，也没有可用于联调的测试群/账号凭据（任务书 §24 禁止把 token/隐私数据写进仓库）。
3. **OpenShamrock 上游消失**（G7 专属）：2026-09-25T08:09Z 第二轮尝试 —— `git ls-remote whitechi73/OpenShamrock` 触发鉴权失败；**带 token** 的 `GET /repos/whitechi73/OpenShamrock` = **HTTP 404**，`/releases` = 404，`/users/whitechi73` = Not Found；仓库搜索只剩第三方分支（★0-4）→ **账号与仓库均已不存在**（不是鉴权/网络问题），状态保持 `SOURCE_UNAVAILABLE`。

### 6.2 已被源码证据覆盖的部分（不依赖实机即可确认）

| 项 | 结论 | 证据 |
| :--- | :--- | :--- |
| Milky 多媒体链路 | 图片/语音发送需先上传取 `resource_id`，再以段数组发送 | `[DOC]` Milky 规范 api 定义 + `[CODE]` Lagrange.Milky 作者实现 |
| OneBot 发送 | 图片/文件走 `/send_group_msg` 段数组；`file://` 本地路径 | `[CODE]` NapCat `types/message.ts` + 现有实现 |
| 撤回语义 | OneBot `/delete_msg{message_id}`；Milky `recall_*{message_seq}` | `[CODE]` 两份 Handler 源码 |
| 发送响应 | OneBot `message_id` / Milky `message_seq` 双字段兼容 | `[CODE]` `SendGroupMessageHandler.cs` L41 |

### 6.3 已尝试步骤（可复现）

```text
1. android_privilege_status            -> 空结构（无授权信息）
2. android_device_info                 -> denied:true（设备控制未授权）
3. android_adb_shell_exec (pm list)    -> denied:true（同上）
4. git ls-remote whitechi73/OpenShamrock (2026-09-25T08:09:39Z) -> could not read Username
5. GET /repos/whitechi73/OpenShamrock  (带 token) -> HTTP 404
6. GET /users/whitechi73               (带 token) -> 404 Not Found
7. GitHub 仓库搜索 OpenShamrock in:name -> 仅第三方分支（total=5）
```

### 6.4 解锁条件（缺一不可）

1. 设备控制授权：开启「DSH 设备控制」无障碍服务，或完成无线调试 ADB 配对；
2. 设备上运行一个协议端（NapCat / Lagrange.Milky / LLBot / Yogurt 任一）并连上 Flowerie；
3. 提供测试群号（与可选测试账号）—— 仅用于联调，不写入仓库。

满足后即可执行 G5（6 项多媒体收发）与 G6（22 项实机 case），命令见 §7。**在此之前不会把这两项写成完成。**

### 6.5 终态确认 —— 结案（2026-09-25）

用户确认：**没有可用于真机测试的环境**（无设备控制授权、无协议端、无测试群），且明确表示不必强求。据此 G5 / G6 / 门槛 4b 按任务书 §20 允许的唯一例外分支**最终结案**：`Real Integration Coverage = 0%`、`状态 = BLOCKED BY EXTERNAL DEPENDENCY（附证据：§6.1–§6.4）`、`含义 = 终态，不是"待办"；不因为"写了 harness"就当作实机验证完成`。

| 项 | 终态 | 说明 |
| :--- | :--- | :--- |
| G5 Milky 多媒体发送实机 | 🚫 BLOCKED（终态）| 已用源码证据覆盖可覆盖的部分（§6.2）；实机 6/6 未执行 |
| G6 真实 Integration Test | 🚫 BLOCKED（终态，0/22 执行）| harness 就绪（`tests/integration/`，22 例默认 skip 并打印缺失条件），用例状态 `[UNVERIFIED]` |
| 门槛 4b 实机验证覆盖率 | 🚫 BLOCKED（终态，0%）| 见上 |
| G7 OpenShamrock | ✅ 已按允许分支结案 | `SOURCE_UNAVAILABLE` + 真实原因（账号与仓库 404）+ 文档研究 |

**未完成项的数量与原因在此冻结**：任何人拿到真实设备后，跑 §7 命令即可把 G5/G6 从 BLOCKED 推进到 CLOSED，并把证据 JSON 落到 `tests/integration/evidence/`。

## 7. 可复现命令

```bash
cd /storage/emulated/0/Flowerie_bot
# 本台账相关用例（本机 python3 缺 pydantic → 用仓库自带 stub 插件；依赖齐全的机器去掉 -p stubplug 与 PYTHONPATH）
PYTHONPATH=$HOME python3 -m pytest -p stubplug tests/test_temp_scene.py tests/test_request_events.py \
    tests/test_media_segments.py tests/test_reply_inline.py tests/test_onebot12_adapter.py tests/test_milky_event_kinds.py -q
# 实机 harness（无环境 → 全部 skip 并打印缺失条件，实测 22 skipped）
python3 -m pytest tests/integration -q -rs
```

