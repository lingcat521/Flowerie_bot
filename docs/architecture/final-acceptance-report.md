# 最终验收报告（任务书 §36 要求的真实数字）

- **日期**：2026-08-09｜**仓库**：Flowerie_bot｜**验收提交**：`7bf3e24`（CI / Acceptance / Push on main **三项全绿**）
- 本报告只写**能追溯到证据**的数字：每条都给出 test / grep / CI / fixture / 源码出处。
  证据等级沿用全项目约定：`[CODE]` / `[DOC]` / `[FIXTURE]` / `[MVP]` / `[INFERENCE]` / `[UNKNOWN]`。

## 一、结论

| | |
| :--- | :--- |
| **B 部分（生态扩展 / 低耦合架构）** | ✅ **完成**：Gate A–Z 全部有结论（25 PASS + 1 项由本轮 CI 转绿），八项绝对门槛 **8/8 PASS** |
| **A 部分（协议缺口封口 G1–G8）** | 6/8 **CLOSED**（G1–G4、G7、G8）｜🚫 **2 项 BLOCKED（终态）**：G5、G6 —— 需真实设备/协议端，证据见 §五 |
| **实机验证覆盖率（门槛 4b）** | 🚫 **BLOCKED BY EXTERNAL DEPENDENCY（终态，0%）**：用户已确认无真机环境（2026-09-25），按任务书 §20 允许的唯一例外分支结案 |
| **是否 FAKE PASS** | 无。所有未完成项都标 BLOCKED 并附可复现证据；实机 22 例标 `[UNVERIFIED]`；所有 PASS 数字都来自真实测试/CI 输出 |

> **最终判定（按任务书口径）**：
> - **架构验收（B 部分 + §35 八项绝对门槛）**：✅ **PASS** —— Gate A–Z 26/26、八项门槛 8/8、CI 三项全绿（`b13053b`）。
> - **缺口封口（A 部分）**：**Gap Closure Rate = 6/8 = 75%**，其余 2 项为 §20 允许的
>   `BLOCKED BY EXTERNAL DEPENDENCY`（终态，非待办）。
> - 按任务书 §25 的字面要求，**本任务不能宣布"完全完成"**（G5/G6 的实机 22/22 未执行）；
>   本报告不回避这一点 —— 这正是"绝不 FAKE PASS"的落点。

## 二、§36 要求的数字块

```text
Core protocol imports: 0          # tests/test_architecture_gates.py::test_gate_a_...
Core protocol branches: 0         # tests/test_architecture_gates.py::test_gate_b_...
Plugin protocol imports: 0        # 同上（Gate T：src/plugins + plugin_sdk 各 0）

OneBot11 Contract: 12/12          # tests/test_adapter_contract.py（4 适配器 × 12 项 = 48/48）
Milky Contract: 12/12
OneBot12 Contract: 12/12
TestProtocol Contract: 12/12

Unknown Segment: 20/20            # OneBot 10 + Milky 10（tests/test_unknown_tolerance.py）
Unknown Event: 20/20              # OneBot 10 + Milky 10（同上）

Cross-protocol equivalence: 7/7   # tests/test_cross_protocol_equivalence.py（3 协议 × 7 类）
Round-trip: 14/14                 # tests/test_roundtrip_matrix.py（7 类 × 2 协议；3 项 lossy 已显式标注）
Existing regression: 18/18        # tests/test_regression_matrix.py（任务书要求 ≥15）

PEC: 0                            # tests/test_pec_experiment.py（三口径：静态零标记 / 自包含 / 变更集）
PCI: 0                            # Core/Services/SDK/Plugins 协议专用引用 = 0
UDSR: 100%                        # 40/40 未知段与未知事件全部安全处理（Gate J/K/L）
ACC: 100%                         # 48/48 契约项（4 适配器）
Typed Coverage: 86.8%             # 33/38 段类型已有 Typed Model（Gate I，≥80%）
Instance Cross-talk: 0            # tests/test_multi_instance.py（3 实例并发 20 轮 × 3）
Transport Contract: WS 8/8 ; HTTP 6 implemented + 2 N/A(附理由) = 8/8 covered

pytest（本地，无 aiohttp/pydantic 等依赖）:
1203 passed / 37 skipped（含 22 个实机用例默认 skip）/ 19 failed（19 项全部是本地缺依赖）
pytest（CI，依赖齐全）:
1605 passed / 26 skipped（含 22 个实机用例 skip）/ 0 failed
CI: success（CI + Acceptance + Push on main 三项）
```

## 三、八项绝对门槛（任务书 §35）

| # | 门槛 | 实测 | 状态 |
| :--- | :--- | :--- | :--- |
| 1 | PCI = 0 | 0 | ✅ |
| 2 | PEC = 0 | 0 | ✅ |
| 3 | Adapter Contract = 100% | 48/48 | ✅ |
| 4 | Unknown Data Safety = 100% | 40/40 | ✅ |
| 5 | Existing Regression = 100% | 零新增失败（1203 passed）| ✅ |
| 6 | CI = 100% success | `7bf3e24`：CI / Acceptance / Push on main 三项 success | ✅ |
| 7 | Plugin Protocol Imports = 0 | 0 | ✅ |
| 8 | TestProtocol 不修改 Core | 虚拟协议接入改动 6 文件全在 Adapter/测试；Core 零改动 | ✅ |

## 四、Gate A–Z（26 项）

✅ PASS（25 项）：A B C D E F G H I J K L M N O P Q R S T U V X Y Z
⏳→✅ W：CI 在本验收提交转绿（历史红提交与根因逐条记在 Dashboard 的 CI 记录里，未删改）

关键数字与出处见 [acceptance-metrics.md](acceptance-metrics.md)（逐项实测 + 逐提交 CI 真实结论）。

## 五、BLOCKED 项与证据（绝不 FAKE PASS）

| 项 | 状态 | 已尝试 | 缺失条件 |
| :--- | :--- | :--- | :--- |
| **G5** Milky 多媒体发送实机联调（6/6）| 🚫 BLOCKED（**终态**，用户 2026-09-25 确认无真机环境）| 设备控制授权查询（无障碍/ADB 两条路径）均返回未授权；`android_device_info` / `android_adb_shell_exec` 返回 `denied: true` | ① 系统设置开启「DSH 设备控制」无障碍，或无线调试 ADB 配对；② 一个运行中的协议端（NapCat/Lagrange/LLBot）；③ 测试群号（拿到后跑 `pytest tests/integration -q -rs`）|
| **G6** 真实 Integration Test（OneBot11 10/10 + Milky 12/12 = 22/22）| 🚫 BLOCKED（**harness 就绪，执行 0/22**）| 同上；已按 §13 建好 `tests/integration/`（22 个用例 + 证据记录器 + manual 流程），默认 skip 并打印缺失条件 | 同上 |
| **门槛 4b** 实机验证覆盖率 ≥90% | 🚫 BLOCKED（0%）| 同上 | 同上 |
| **G7** OpenShamrock | ✅ 按任务书允许的分支结案 | 带 token 查询 `GET /repos/whitechi73/OpenShamrock` → **404**；`/users/whitechi73` → **404**（账号与仓库均已不存在，非鉴权问题）→ `SOURCE_UNAVAILABLE` + 真实原因 + 已完成文档研究（docs/source-acquisition.md）| —— |

BLOCKED 的完整证据链（含每次尝试的命令与返回）记录在 [../protocol-gap-closure.md](../protocol-gap-closure.md) §6。

### 指标口径（任务书 §19 / §20 / §21）

```text
Gap Closure Rate = 6/8 = 75%          # G1 G2 G3 G4 G7 G8 = CLOSED；G5 G6 = BLOCKED（不是 CLOSED）
Real Integration Coverage = 0%        # BLOCKED BY EXTERNAL DEPENDENCY（§20 允许的唯一例外分支），证据见 §五
Milky Gap Phase = NOT COMPLETE        # §21：G1/G2/G3/G4 = 100%；G5（多媒体发送实机）BLOCKED → 如实标 NOT COMPLETE
```

### §13 实机测试目录（已建立，执行 BLOCKED）

| 文件 | 内容 |
| :--- | :--- |
| `tests/integration/test_onebot11_real.py` | §8.1 的 10 项：text/image/file/forward/JSON-Ark/poke/recall（通过客户端 API 发送 → 取回 → **真解析器**归一化）|
| `tests/integration/test_milky_real.py` | §8.2 的 12 项：text/image/record/file/forward/reply/poke/request event |
| `tests/integration/_realenv.py` | 环境探测 + §8.3 缺失条件文案 + §14 证据记录器（禁止记录 token/cookie/私聊内容）|
| `tests/integration/README.md` | 三层测试边界（unit / integration / **manual real-device**）+ 运行方式 + 手工步骤 |

**诚实标注**：这 22 个用例**从未在真实客户端上执行过**（`[UNVERIFIED]`），代码路径本身也未经实机验证；
本地/CI 里它们全部 skip 并打印缺失条件（`22 skipped`）。

### §22 合规声明（禁止用文档修改代替修复）

```text
删除 docs 中的缺口                      → 未做（缺口台账 G1–G8 全量保留，BLOCKED 项照实写）
把 UNKNOWN 改成 SUPPORTED               → 未做（docs/message-model.md §5 仍列 [UNKNOWN] 项）
把"未验证"改成"已支持"                   → 未做（onebot12 标 NOT_REAL_DEVICE_VALIDATED；实机项标 BLOCKED）
减少 capability matrix 项目             → 未做（能力项 18 项 × 4 适配器描述符，只增不减；有测试钉住）
删除失败 fixture / 失败测试              → 未做（fixture 21 个；失败用例与其原因逐条保留在 Dashboard）
```

## 六、证据可追溯性抽样

| 数字 | 追溯方式 |
| :--- | :--- |
| Core protocol imports = 0 | `python3 -m pytest tests/test_architecture_gates.py -q`（静态扫 4 层目录）|
| Contract 48/48 | `python3 -m pytest tests/test_adapter_contract.py -q`（4 适配器 × 12 项，逐项断言）|
| PEC = 0 | `python3 -m pytest tests/test_pec_experiment.py -q`（三口径，含"禁止层零标记"）|
| Typed Coverage 86.8% | `python3 -m pytest tests/test_normalized_coverage.py -q`（台账 + 33 条真解析验证）|
| Cross-talk = 0 | `python3 -m pytest tests/test_multi_instance.py -q`（并发 20 轮 × 3 实例）|
| CI = success | GitHub Actions 三个 workflow 的结论（逐提交写入 Dashboard）|
| 协议字段与段清单 | `[CODE]` proto_src 源码行号 / `[DOC]` 规范行号，逐条写在对应 ADR 与 docs 里 |

## 七、复现命令

```bash
# 架构 Gate 全套（不依赖网络与设备）
python3 -m pytest tests/test_architecture_gates.py tests/test_adapter_contract.py \
    tests/test_capability_model.py tests/test_unknown_tolerance.py tests/test_pec_experiment.py \
    tests/test_transport_contract.py tests/test_multi_instance.py tests/test_resource_model.py \
    tests/test_normalized_coverage.py tests/test_cross_protocol_equivalence.py \
    tests/test_roundtrip_matrix.py tests/test_regression_matrix.py -q

# 全量（CI 环境即 requirements 全装）
python3 -m pytest -q
```

> 本地缺 aiohttp/pydantic/httpx 时的跑法见 docs/development.md（`-p stubplug`；需要更宽的导入链时再加 `-p stubio`）。
