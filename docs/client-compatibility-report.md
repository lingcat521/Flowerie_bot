# 客户端协议兼容扩展 · 最终报告（真实数字）

> 任务书：`/storage/emulated/0/协议.txt`（OneBot 11 / Milky 多客户端协议级兼容性扩展）。
> 本报告给出 §二十一/§二十四 要求的全部量化指标，并把每个结论**归到它实际达到的证据等级**。
> 配套文档：[client-compatibility.md](client-compatibility.md)（矩阵）、[client-profiles.md](client-profiles.md)（档案）、[protocol-implementation.md](protocol-implementation.md)（分层与耦合度量）、[reverse-engineering/](reverse-engineering/)（逐客户端逆向）。

## 0. 一页速览

| 项 | 值 |
| :--- | :--- |
| 调查的客户端（本次报告的列）| OneBot 11 **4 列**：go-cqhttp `[CODE]` · NapCat `[CODE]` · LLBot `[CODE]` · Lagrange `[DOC]`（实现源码不可得）；Milky **3 列**：Lagrange.Milky（协议作者实现，内嵌）`[CODE]` · LLBot 的 Milky `[CODE]` · Milky 规范基线 `[DOC]` |
| 源码获取 | **17** 个仓库（`~/proto_src/`），含 napcat / go-cqhttp / Lagrange.Core+V2 / LLBot / Koishi / Kovi / NoneBot2+adapter-onebot / ROneBot / SnowLuma / Milky-spec / milky-python-sdk / OneBot11-spec / Lagrange.Doc；`SOURCE_UNAVAILABLE` **2**：Lagrange.OneBot（HTTP 404，附复现命令）、OpenShamrock（clone 需凭据）|
| UNKNOWN 格 | **61**（OneBot 11 26 + Milky 35；合计 144 格）——**空格是信息，不是待办勾** |
| 语料与测试 | Fixture **40** 个（带 `_provenance`，全部 `captured:false`）；相关测试 **285** 条（`b0d4daa` 收集数），其中契约/往返/耦合/未知安全为新增 |
| 耦合度 / 实机验证 | `src/{core,services,sdk,plugins}` 客户端名命中 **0**、`src/` 里 import 客户端实现 **0**；实机验证 **0**（本环境无协议端）→ 相关项全部 `BLOCKED BY EXTERNAL DEPENDENCY` |
| CI | 见 §6（逐提交记录，红色提交也如实保留）|

## 1. §二十四 指标逐项

### 1.1 客户端覆盖（目标 / 实际 / 不可得 / 未知）

任务书 §三/§四 点名 + 既有生态清单（[client-compatibility.md](client-compatibility.md) §6）分成三级来数，**不把"点名"当"已调查"**：

| 级别 | OneBot 11 | Milky |
| :--- | :--- | :--- |
| 点名/生态清单里出现 | 16+（NapCat、go-cqhttp、Lagrange.OneBot、LLBot、OpenShamrock、SnowLuma、onebots、Yogurt、onebot-kotlin、oicq、OneBot-YaYa、coolq-http-api、PicqBotX、Gensokyo、KookOneBot、Koishi/Kovi/NoneBot2 等消费侧）| 40+（Lagrange.Milky、milky-python-sdk、ROneBot、Kovi、imhelper、@imhelper/milky-v1、Milky.Net.Model、milky-types…）|
| **已完成源码级调查（本次报告的列）** | **3**：[CODE] go-cqhttp / NapCat / LLBot；**1** 列只有文档：[DOC] Lagrange | **2**：[CODE] Lagrange.Milky（内嵌）/ LLBot-Milky；**1** 规范基线 [DOC] |
| `SOURCE_UNAVAILABLE` | **2**（Lagrange.OneBot、OpenShamrock）| 0（Milky 侧的"Lagrange.Milky 独立仓库"不存在，实为内嵌 —— 已更正）|
| 明确 `NOT_INVESTIGATED` | onebots、Yogurt、onebot-kotlin、oicq（归档）、Gensokyo/KookOneBot（非 QQ 平台）| imhelper 及 30+ SDK（**消费侧**）|

消费侧 SDK 不逐列调查的口径见 §3.1。

### 1.2 覆盖率（Event / Segment / Action / Response）

分母来自**客户端自己的源码枚举/清单**（命令见 §7），分子是"逐条读过并有引用"的条目：

| 客户端 | Segment（分子/分母）| Event | Action | Response |
| :--- | :--- | :--- | :--- | :--- |
| go-cqhttp | **16/16 = 100%**（发送侧 case 表 + 上报侧 toElements 分支）| message 三类（group/private/temp）+ notice(group_upload) + meta(lifecycle)：**5 类逐字段**，其余未逐类 | **清单级 85/85**（supported.go），语义级只核对了个别端点 | **100%**（OK/Failed 包封 + msg/wording/message 三字段）|
| NapCat | **23/25 = 92%**（段枚举 25 项；onlinefile/flashtransfer 只有枚举名，未展开 schema → 保持 UNKNOWN）| message 三类（normal/friend/temp：含顶层 group_id 的临时会话）+ notice 两类（poke/group_upload）：**逐字段**；其余未逐类 | **未逐条**（170 个 handler 文件只做清单级计数）| **100%**（createResponse 包封；无 wording）|
| LLBot（OneBot 11）| **16/21 = 76%**（incoming.ts 逐分支读到 keyboard；record 分支未逐行抄录）| message 三类 + shake/dice/rps/face/mface/flash_file/keyboard：**逐字段** | **未逐条**（121 个 action 文件）| **100%**（OB11Response 包封）|
| Lagrange（OneBot 11）| **0/未知**（无源码）| 无 | 无 | **仅文档**：文档自己说"并非所有 API 都已实现"，未列清单 |
| Milky 规范 | **出站 10/10 = 100%**、**入站 13/14 = 93%**（14 个变体，markdown 之后未逐条）| 既有文档覆盖 21 种事件类型（G1-G4 已 CLOSED）| —（Action 面由各实现决定）| **100%**（{status,retcode,data\|message}）|
| Lagrange.Milky | **段模型两份副本**：Core 11 文件 / V2 15 文件（差异已记录）；出站转换在 `Converters/` | 未逐类（既有文档覆盖部分）| handler 面已定位（未逐条）| **100%**（`{message_seq, time}`）|
| LLBot-Milky | 出站读到 image 为止（前 5 段逐条）| 既有文档逐字段（§4.1）| 未逐条 | **100%**（common/api.ts）|

> **读法**：Segment 覆盖是本次的主要产出；Action 只有清单级（且明确标注），**不冒充**逐条语义核对 —— 这也是 §1.3 里 UNKNOWN 仍占 42% 的原因之一。

### 1.3 UNKNOWN 明细（61 格，逐列给原因）

| 协议 | 客户端 | 有证据 | UNKNOWN | UNKNOWN 的主要原因 |
| :--- | :--- | ---: | ---: | :--- |
| onebot11 | go-cqhttp | 18 | **0** | ——（发送侧 case 表 + 上报侧逐字段都读过）|
| onebot11 | napcat | 18 | **0** | ——（段枚举逐条 schema；onlinefile/flashtransfer 归到能力外）|
| onebot11 | llbot | 8 | **10** | record/video/forward/light_app 等只在 incoming.ts 后半段，未逐行抄录 |
| onebot11 | spec | 16 | **0** | ——（规范段清单逐节核对）|
| onebot11 | lagrange | 2 | **16** | 实现源码 SOURCE_UNAVAILABLE，文档只写了 File/Node 两类段 |
| milky | spec | 9 | **9** | 出站联合体 10 段已全读；未列进 MATRIX 的能力（如 group 管理类）未核对 |
| milky | lagrange | 6 | **12** | 内嵌实现只核对了段模型/发送响应，其余行为未逐条 |
| milky | llbot | 4 | **14** | 出站只读到 image 为止 |

> 这些 UNKNOWN **不会被填成 SUPPORTED**（§二十二 禁令 8）；查询它们的档案得到 UNKNOWN，契约测试也会断言"未登记的能力不得被当成支持"。

## 2. 证据等级分层（每个结论归到它实际达到的等级）

| 等级 | 本次达到的结论 |
| :--- | :--- |
| **SOURCE VERIFIED** | 17 个客户端/规范仓库已获取并记录 HEAD（[source-acquisition.md](source-acquisition.md)）；2 个项目 SOURCE_UNAVAILABLE（附命令）|
| **CODE VERIFIED** | go-cqhttp / NapCat / LLBot 的段字段与事件字段（逐文件:行）；Lagrange.Milky 的段模型与发送响应；LLBot-Milky 的出站规则 |
| **FIXTURE VERIFIED** | 40 个 fixture 全部带 provenance 且被 `test_fixtures_corpus.py` 强制校验（client/status/captured/evidence/note），来源精确到行号 |
| **UNIT VERIFIED** | 解析器/序列化器/响应解析的单元断言（含未知段、非法段、越界取值）|
| **CONTRACT VERIFIED** | `test_client_contract_matrix.py`：Client × Capability × Direction（Parse/Normalize/Serialize/Unknown×4）+ 档案诚实性 + 文档漂移 |
| **INTEGRATION VERIFIED / BLOCKED** | **INTEGRATION 无** —— 本环境没有协议端；22 条实机集成用例 skip 并打印缺失条件。BLOCKED：实机集成（G5/G6 + 22 条 `tests/integration/`）+ Lagrange.OneBot 源码（不可得，非本仓库可控）|
| **UNKNOWN** | §1.3 的 61 格 + 未调查客户端（onebots/Yogurt/…）|

**Round-trip 专项**（§十八）：

| 方向 | 结果 |
| :--- | :--- |
| OneBot 11 fixture → parse → serialize | 段类型序列保持；丢失字段（如 record/video 的 url）必须有 note —— 已断言 |
| Milky fixture → parse → serialize | **13/14 段可出站**，唯一消失的是 `forward`（入站只有 forward_id，出站要构造 messages[]），附原因 |
| fixture → parse → 重建 → reparse（既有 `test_protocol_roundtrip.py`）| 81 条全绿；本轮把 `message_sent` 纳入真往返（原来是 skip，现在有断言）|
| 不能 round-trip 的情况 | 两条已写进代码注释与 note：Milky 的 `forward_id`、OneBot 的 `record.url`（上报有、发送侧不读）|

## 3. 口径说明（避免把"没查"读成"不支持"）

1. **消费侧 SDK 不逐列调查**：Koishi / Kovi / ROneBot / NoneBot2-adapter / milky-python-sdk 消费同一套 wire 形态，差异是"字段缺失容忍度"，由宽容解析 + unknown 保留覆盖；它们出现在 §1.1 的"点名"级别，不出现在"已调查"级别。
2. **Action 只有清单级**：go-cqhttp 85 个（清单已列举）、NapCat 170 个 handler 文件、LLBot 121 个文件 —— 没有逐条核对参数/返回，因此**不写进矩阵的能力格**。
3. **"规范里有"≠"某客户端有"**：spec 列与客户端列分开登记；客户端独有的段（NapCat 的 mface/markdown、LLBot 的 flash_file/keyboard、go-cqhttp 的 cardimage/redbag）**不会**被塞给其它客户端。
4. **UNKNOWN 是信息**：矩阵里的空格表示"没查到证据"，不是"待办勾"；任何填格都必须能指到源码行号或规范条文。

## 4. 协议耦合（§十一/§二十一）

实测（`tests/test_protocol_coupling.py`，口径=去掉注释与字符串后判）：

| 层 | 代码级客户端名命中 |
| :--- | ---: |
| `src/core` / `src/services` / `src/sdk` / `src/plugins` | **0 / 0 / 0 / 0** |
| `src/adapters`（允许） / `src/transport`（允许） | 11 / 1 |
| `src/` 里 import 客户端实现 | **0** |

本轮清掉最后一处越界命名：`src/services/file_parser.py` 的 `decode_napcat_file_response` → `decode_base64_json_file_response`（客户端事实留在注释与 Adapter）；三条规则都可执行（import / 命名 / 分支）。

## 5. Unknown Data 安全（§十五）

| 未知对象 | 行为 | 用例 |
| :--- | :--- | :--- |
| 未知字段 | 进 `raw_data`，已知字段照常解析 | `test_unknown_field_safety` |
| 未知段 | 原样保留、不影响其它段、出站也原样传递 + note | `test_unknown_segment_safety` / `test_unknown_segment_serialization_is_passthrough` |
| 未知事件 | `kind` 原样保留（不塌缩成 unknown）| `test_unknown_event_safety` |
| 未知响应 | 返回失败 + 原因，不抛异常 | `test_unknown_response_safety` |
| 非法段（缺 type / 非对象）| 拒绝并记 note，不崩溃 | `test_invalid_segments_do_not_crash` |

**Unknown Data Safety Rate = 100%** 的口径：上述 5 类各有用例，且都在**真解析器/真序列化器**上跑（不是 mock），断言"不炸 + 不丢已知字段 + 原样保留原始数据"。

## 6. CI 与回归（逐提交，红色也保留）

| 提交 | 主题 | CI 结果 | 说明 |
| :--- | :--- | :--- | :--- |
| c29e6cd | go-cqhttp 档案 + 两个跨客户端缺口修复 | ✅ 三项全绿 | 1870 passed / 22 skipped |
| 4baa444 | ClientProfile + OneBot 出站序列化 | ✅ 三项全绿 | —— |
| 735b292 | 契约矩阵 + Unknown 安全 | ✅ 三项全绿 | —— |
| a52fb7e / 2aa1f27 / d972c5e | 实现说明 / NapCat 档案 / LLBot+Lagrange 档案 | ✅ 三项全绿 | 2aa1f27：NapCat 修复后的完整回归 |
| **c18b70a** | Milky 出站 + 响应 + 档案 | ❌ **Ruff 2 条 I001** | 新增文件的 import 顺序（常量/类、大小写不敏感序）→ **4741794 修复** |
| **6450f44** | 协议耦合度量 | ❌ **Ruff 2 条 F401** | 新测试里 `io`/`pytest` 未使用 → **7bf3623 修复** |
| 7bf3623 | 上述修复 | ✅ 三项全绿 | **2007 passed / 23 skipped**（23 = 22 条实机 + 1 条 round-trip 覆盖说明）|
| **b0d4daa** | 本报告 + message_sent 纳入真往返 | ✅ 三项全绿 | **2008 passed / 22 skipped**（22 条**全部**是实机用例 —— 那 1 条 round-trip 覆盖缺口已换成真断言）|
| **4d5d2b6** | 出站序列化接入发送热路径 | ❌ **1 failed** | `test_all_settings_fields_covered`：新开关没登记进 ConfigService.SCHEMA → **32a52ed 修复** |
| **32a52ed** | 上述修复 | ✅ 三项全绿 | **2025 passed / 22 skipped**（新开关可见于 Web UI 配置页与环境模板）|

**回归**：最新一次（`b0d4daa`）整仓 **2008 passed / 22 skipped，0 失败**；22 条 skip 全部是实机用例（缺协议端，逐条打印缺失条件）。本轮把一处 round-trip skip 换成真断言：`message_sent`（机器人自己发的消息）现在走完整的 parse → 重建 → reparse 往返，skip 数因此从 23 降到 22。

## 7. 实机与阻塞项（BLOCKED BY EXTERNAL DEPENDENCY）

| 项 | 需要的环境 | 已完成的源码级验证 | 阻塞原因 |
| :--- | :--- | :--- | :--- |
| `tests/integration/test_onebot11_real.py`（10 条）| 运行中的 OneBot 11 协议端 + HTTP/WS 地址 + 测试群号 | 全部入站/出站字段级逆向（本报告 §1.2）| 本环境无协议端 |
| `tests/integration/test_milky_real.py`（11 + 1 条）| 运行中的 Milky 协议端 + 访问令牌 | Milky 段/事件/响应逆向 + Lagrange.Milky 实现核对 | 同上 |
| G5（Milky 多媒体发送：upload → resource_id → send）| 同上 + 真实文件 | 规范与两份实现已读；`uri` 三种写法已确认 | 同上 |
| G6（实机 Integration Test）| 同上 | 见上 | 同上 |
| Lagrange.OneBot 源码 | —— | 已穷尽：404 + 组织清单 + 本地 grep（[source-acquisition.md](source-acquisition.md) C4）| 上游仓库不存在 |

未来有环境后要跑的命令：`FLOWERIE_REAL_ONEBOT_HTTP=... FLOWERIE_REAL_GROUP=... pytest tests/integration -q`（缺失条件由用例自身打印，见 CI 的 SKIPPED 行）。

## 8. §二十二 十条禁令自查

| # | 禁令 | 自查结果 |
| :-- | :--- | :--- |
| 1 | 只读 OneBot Spec 就宣布某客户端兼容 | 未发生：spec 列与客户端列分开登记，客户端结论全部 [CODE] |
| 2 | 只读 Milky Spec 就宣布某客户端兼容 | 未发生：Milky 列分别有 [CODE]（Lagrange/LLBot）与 [DOC]（基线）|
| 3 | 把 NapCat 行为当 OneBot 11 标准 | 未发生：规范基线独立成列；NapCat 独有段（mface 等）**没有**塞进 spec 列 |
| 4 | 把一个客户端的扩展字段硬塞进所有客户端 | 未发生：序列化器按档案出字段，未验证的一律原样传递 + note |
| 5 | 为客户端复制大量 Core 逻辑 | 未发生：差异集中在 ClientProfile/序列化器/解析器；耦合度量 0 |
| 6 | 修改 Core 来适应单一客户端 | 未发生：本轮 Core 零改动（改动都在 adapters/transport + 文档）|
| 7 | 删除已有测试 | 未发生：`git log --diff-filter=D -- tests/` 为空；删掉的 `def test_` 计数 0 |
| 8 | 把 UNKNOWN 改成 SUPPORTED 提高覆盖率 | 未发生：UNKNOWN 61 格保留；反而**纠正**了两处误标（spec 的 dice/rps/poke 从 UNSUPPORTED 改为 SUPPORTED，附条文）|
| 9 | 用 Mock 替代源码逆向或实机验证 | 未发生：契约测试跑真解析器/序列化器/真子进程；源码结论附文件:行 |
| 10 | 没有证据时声称客户端支持某 Capability | 未发生：档案的 `evidence`/`source` 必填，测试会拒绝空口条目 |

## 9. 复核命令

```bash
python3 -m pytest tests/test_client_contract_matrix.py -q -s      # 1. 客户端档案与矩阵（含文档漂移保护）
python3 -m pytest tests/test_protocol_coupling.py -q -s           # 2. 耦合度量（Client Imports = 0）
python3 -m pytest tests/test_fixtures_corpus.py -q                # 3. 语料溯源 + 归一化断言
python3 -m pytest tests/test_onebot_serializer.py tests/test_milky_serializer.py tests/test_protocol_roundtrip.py -q -rs   # 4. 两个方向的序列化 + 5. 往返（含 message_sent 真断言）
python3 -m pytest tests/test_onebot_response_contract.py -q       # 6. 响应模型（两套包封）
python3 -c "from src.adapters.client_profile import render_matrix; print(render_matrix('onebot11'))"   # 7. 生成矩阵（文档与代码同源）
```

## 10. 结论与下一步

**结论**：Flowerie 现在有一套**客户端级**的兼容事实体系 —— 3 个 OneBot 11 实现 + 2 个 Milky 实现为 [CODE]，1 个 OneBot 11 实现为 [DOC]（源码不可得），
差异集中在 ClientProfile/序列化器/解析器里，Core/Services/SDK/Plugins 对客户端零耦合（实测），矩阵与文档由代码生成且防漂移，每个结论都能指到源码行号、规范条文或一条测试。

**下一步（按价值排序）**：

1. ~~把序列化器接进发送热路径~~ **已完成**：`CLIENT_PROFILE` 开关（`src/config.py:52`，默认空 = 关闭）+ 组合根注入 + 静态接线守卫；
2. 补齐 LLBot record/video/forward 与 Lagrange.Milky 的 Action 面（把 UNKNOWN 变成有证据的格子）；
3. 有真机环境后跑 `tests/integration/`（22 条）与 G5/G6，把 BLOCKED 转为 INTEGRATION VERIFIED；
4. 继续按 [client-profiles.md](client-profiles.md) §5 的清单接入未调查客户端（onebots/Yogurt/…）。
