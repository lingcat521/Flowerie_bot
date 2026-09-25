# 实机（real-device）Integration Test

> 任务书 §13 要求：**必须区分** unit test / integration test / manual real-device test，
> **不要把手工测试伪装成 CI 自动测试**。本目录就是这条边界的落点。

## 三层测试的分工

| 层 | 位置 | 运行条件 | CI 是否执行 | 当前状态 |
| :--- | :--- | :--- | :--- | :--- |
| unit / 静态测试 | `tests/test_*.py`（含 12 个 Gate 专项文件） | 无外部依赖 | 是（每次） | 全绿（1203 passed） |
| integration（可自动判定） | 本目录 `test_onebot11_real.py` / `test_milky_real.py` | 需要真实协议端 + 测试群（环境变量） | 否（默认 skip） | **harness 就绪，执行 BLOCKED** |
| manual real-device | 本 README §manual 步骤 | 需要人工触发（另一账号操作） | 否（永不） | BLOCKED |

**本目录的用例从未在真实客户端上执行过**（设备控制未授权，见
[../../docs/protocol-gap-closure.md](../../docs/protocol-gap-closure.md) §6），
因此它们的状态是 `[UNVERIFIED]`：代码路径本身也未经实机验证 —— 这一点必须如实标注，
不能因为"写了测试"就当作实机验证完成。

## 怎么跑（拿到设备/协议端之后）

```bash
# OneBot 11（NapCat / Lagrange / LLBot 任一）
export FLOWERIE_REAL_ONEBOT_HTTP=http://127.0.0.1:3000
export FLOWERIE_REAL_ONEBOT_TOKEN=...        # 可选
export FLOWERIE_REAL_GROUP=123456            # 测试群
export FLOWERIE_REAL_IMAGE=/sdcard/a.png     # 可选：图片（URL 或本地路径）
export FLOWERIE_REAL_RECORD=/sdcard/a.silk   # 可选：语音
export FLOWERIE_REAL_FILE=/sdcard/a.zip      # 可选：文件

python3 -m pytest tests/integration -q -rs

# Milky（Lagrange.Milky / LLBot）
export FLOWERIE_REAL_MILKY_API=http://127.0.0.1:3010
export FLOWERIE_REAL_MILKY_TOKEN=...         # 可选
python3 -m pytest tests/integration -q -rs
```

未配置环境变量时全部用例 skip，并打印 **缺失条件**（§8.3 要求：阻塞原因 / 已验证的源码证据 /
已尝试步骤 / 缺失条件）。

## 覆盖情况（§8.3：OneBot11 10/10 + Milky 12/12 = 22/22）

| 协议 | 用例 | 数量 | 自动/手工 |
| :--- | :--- | :--- | :--- |
| OneBot 11 | text send/receive、image send/receive、file send/receive、forward receive、JSON/Ark receive、poke、recall | 10 | 自动（poke 的**接收**侧需事件流 → §manual） |
| Milky | text send/receive、image send/receive、record send/receive、file send/receive、forward receive、reply、poke、request event | 12 | 自动；`request event` 为 §manual |

## 证据格式（§14）

每次实机执行由 `_realenv.record_evidence()` 落一份 JSON 到 `tests/integration/evidence/`：

```json
{
  "client": "Lagrange/Milky", "version": "xxx", "protocol": "Milky",
  "commit": "客户端版本", "environment": "Android/Linux",
  "date": "2026-08-09T12:00:00", "test_case": "image send",
  "input": "...", "expected": "...", "actual": "...", "result": "PASS"
}
```

**禁止记录**：access token / password / Cookie / 私人聊天敏感内容（记录器只接受调用方显式传入的字段）。

## §manual：必须人工触发的步骤

1. **戳一戳接收**（OneBot 11 / Milky）：让另一个账号在测试群里戳机器人 →
   机器人日志应出现 `notice_kind=poke`；把原始事件贴进证据 JSON 的 `input`。
2. **入群 / 加好友请求**（Milky `request event`）：让另一个账号发起申请 →
   断言解析结果 `kind=request` 且 `request_kind` 正确、`comment` / `request_id` 非空。
3. **多媒体接收**：用手机客户端**手动**发一张图/一段语音/一个文件（而不是 API 构造）→
   确认归一化字段与素材一致（这是"客户端真实行为"而非"API 回显"）。
