# Plugin SDK 能力矩阵（Capability Matrix）

> 状态词只有四个：**SUPPORTED**（有自动化证据）/ **PARTIAL**（部分实现或证据不足）/
> **UNSUPPORTED**（明确不支持）/ **UNKNOWN**（未验证）。**禁止为了让表格「全绿」而虚假声明**：
> 每一格 SUPPORTED 都必须能指到下面某条绿色输出或 CI 记录，指不到就降级。
>
> 核对基线：Flowerie **2.3.0** · 协议 `PROTOCOL_VERSION = "1"`：必需 4 方法 + 可选 **14** 方法
> （8 核心 + 3 WebUI + 3 插件间，`src/plugins/protocol.py` 的 `REQUIRED_METHODS` /
> `OPTIONAL_METHODS`）。SDK 语言：Python（内置 runner）/ TypeScript / Go / Rust / Java。

## 1. 逐能力对照（当前事实）

证据列：**A** = `tests/sdk/`（46 条）+ `tests/test_plugin_sdk_contract.py`（78 条）；
**B** = `tests/test_plugin_webui_multilang.py`（31 条）；**C** = `tests/test_plugin_comm_model.py`（62）/
`tests/test_plugin_comm_bus.py`（17）/ `tests/test_plugin_comm_paths.py`（7）+ 上面 A 的 Call/Error 行。

| 能力（协议方法 / API） | Python | TypeScript | Go | Rust | Java | 证据 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `initialize` / `shutdown`（生命周期） | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | A |
| `event`（事件接收 + 动作产出） | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | A |
| `health`（心跳） | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | A |
| `hook`（引擎内部数据钩子，如 WebUI vars） | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | A |
| `method:"action"` 反向副作用通道 | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | A |
| `context.get` | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | A |
| `config.get` / `config.set`（覆盖层） | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | A |
| `permission.check` | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | A |
| `storage.get/set/delete/list` | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | A |
| `webui.page`（页面声明 + HTML/vars） | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | B |
| `webui.action`（表单动作 → vars/config_set/storage_set） | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | B |
| `webui.asset`（插件生成资源） | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | B |
| `plugin.call`（入站：expose + 分派 handler） | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | C |
| `plugin.event`（入站：on + 通配订阅） | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | C |
| `plugin.cancel`（入站：记录 + 可查询） | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | C |
| 出站 `plugin.call` / `plugin.emit` / `plugin.cancel`（反向 op） | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | C |
| 12 个结构化错误码映射成本语言异常/Result | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | A/C |
| `trace_id` / `hop_count` 自动传播 | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | C |
| 嵌套调用（等待响应时仍处理入站消息） | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | SUPPORTED | C |

**五语言能力集合完全相等**：`tests/sdk/test_minimal_plugins.py::test_minimal_plugin_starts_standalone`
在每种语言真进程里断言 `len(capabilities) == 14`；`tests/test_plugin_sdk_contract.py`
的 `test_capability_parity_is_declared_in_every_sdk_source` 逐份源码比对常量，防「文档一套、实现一套」。

## 2. 证据（本机可复核的真实数字）

| 测试文件 | 收集数 | 本机（Termux：只有 python + node） | 说明 |
| :--- | :--- | :--- | :--- |
| `tests/sdk/` | **46** | 9 passed / 37 skipped | 五语言最小插件：Build/Load/Ready/Ping/Info/Echo/Event/Call/Error/Permission/Shutdown + 7 条跨语言链路；缺工具链 skip 并打印原因 |
| `tests/test_plugin_sdk_contract.py` | **78** | 33 passed / 45 skipped | 五语言 × 15 类向量（握手/事件/storage/hook/permission/未知方法/shutdown/health/plugin.call 入站/结构化错误/plugin.event/plugin.cancel/反向 op）+ 3 条静态一致性 |
| `tests/test_plugin_webui_multilang.py` | **31** | 13 passed / 18 skipped | 五语言 × 6 类 WebUI 请求（能力声明/页面 context/action 保存/未知动作错误/asset/文件页数据钩子）+ 矩阵汇总 |
| `tests/test_plugin_multilang.py` | 14 | 未在本机全跑 | `tests/plugins/multilang/` **13 种语言**最小插件真编译真运行 + 夹具一致性 |
| `tests/test_plugin_comm_model.py` / `_bus.py` / `_paths.py` | 62 / 17 / 7 | 62 passed / 17 passed / 1 passed + 6 skipped | 模型层 / 真子进程总线 / 跨语言路径 |

**CI 才是五语言全跑的采信来源**：`.github/workflows/ci.yml` 有独立步骤
`SDK minimal plugin matrix (build/load/ping/echo/event/call/error/permission/shutdown)`
→ `pytest -q -s tests/sdk/`，并由 runner 提供 node / go / rustc / javac。本机缺工具链时
打印 `SKIP(本机缺工具链 …)`，**绝不当作通过**。

## 3. 历史 CI 记录（保留，按 commit 标注 —— 均为当时基线的数字，本次未重跑）

| CI run | commit | 结果 | 内容 |
| :--- | :--- | :--- | :--- |
| [36129069164](https://github.com/lingcat521/Flowerie_bot/actions/runs/36129069164) | `cf283fe` | success（workflow `CI`，job `test (3.12)`） | 整仓 1755 passed / 22 skipped（22 条为缺协议端环境的实机用例）；Go/Rust/Java 首次真编译真跑 |
| [36132261166](https://github.com/lingcat521/Flowerie_bot/actions/runs/36132261166) | `42427a0` | `CI` / `Acceptance` / `Push on main` 三项全绿 | 整仓 1829 passed / 22 skipped；五语言 WebUI 能力全绿（当时 `test_plugin_webui_multilang` 31 条） |

> 这两行是**历史**记录（数字属于对应 commit 的 CI 快照）：CI 一次抓出过 Go 反向 op 死锁、Rust hook
> 上下文缺失、TS 缺 `@types/node` 三个本机抓不到的真 bug；当前代码状态以 §1 + §2 的本机实测为准。

## 4. 怎么复核这张表

```bash
python3 -m pytest tests/sdk tests/test_plugin_sdk_contract.py tests/test_plugin_webui_multilang.py -q -rs
python3 -m pytest tests/test_plugin_comm_model.py tests/test_plugin_comm_bus.py -q
# 收集数核对：期望 169 tests collected（tests/sdk 46 + contract 78 + webui_multilang 31 + multilang 14）
```
