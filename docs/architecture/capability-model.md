# ADR-002：能力模型（Capability Model）

- **状态**：已实施（首版）｜**日期**：2026-08-09｜**对应 Gate**：G / H（并作为 D/E/F 的地基）
- **背景**：任务书 §7-§10 要求把"支持什么"变成一等概念，并明确禁止两类做法：
  ① 设计一个要求所有协议实现全部方法的**万能协议接口**；② 把"存在 image 段"等同于"能发图片"。

## 决策

1. **receive / send / action 分离**：`image.receive` 与 `image.send` 是两个能力。
   例：Milky 能收图片（`image.receive` = supported），但发送需要先 upload 取 `resource_id`，
   管道未接线 -> `image.send` = **unsupported**（并在 note 里指向缺口台账 G5）。
2. **五态显式**：`supported` / `partial` / `emulated` / `unsupported` / `unknown`。
   `unknown` 表示**证据不足**（例如 OneBot 12 规范里没有 face 段，但实现可扩展），
   **不得**与 `unsupported` 混用；未声明的能力 `state()` 返回 `unknown`，由调用方决定。
3. **只有声明，没有继承**：每个协议独立声明自己的 18 项状态，不做"默认支持"的隐式继承。
4. **状态必须可解释**：`partial` / `emulated` 逐条写理由；`unsupported` / `unknown` 允许由描述符级
   说明统一覆盖，但不允许整片状态没有解释（`tests/test_capability_model.py` 强制）。
5. **能力查询由描述符提供**：`get_descriptor(pid).capabilities.supports(cap)`；
   覆盖率 `capability_coverage(pid)`（Gate G 口径：已显式声明 / 规范能力总数）。

## 被否决的方案

- **"万能 Protocol 接口"**（send_message/send_image/send_video/... 全塞一个类）：任务书 §7 明确禁止；
  会让每个新协议被迫实现一堆用不到的方法，并把协议差异重新压回单一实现里。
- **布尔能力表**（支持/不支持两态）：无法表达"通道在但没专用封装"（partial）与"没有证据"（unknown），
  会把 G5 这类未接线缺口伪装成"已支持"。
- **按 Message Segment 类型推导能力**：收得到 `image` 段 ≠ 发得出去图片；段类型是数据形态，能力是"能不能做"。

## 当前实测（2026-08-09）

| 协议 | 已登记能力 | 覆盖率（Gate G ≥95%）| 关键缺口（note 里写明）|
| :--- | ---: | ---: | :--- |
| onebot11 | 18/18 | 100% | `file.send` / `face.send` / `market_face.send` = partial；`forward.send` = unsupported |
| milky | 18/18 | 100% | `image.send`（需 upload 管道，G5）/ `file.send` / `forward.send` = unsupported |
| onebot12 | 18/18 | 100% | 骨架：接收侧 partial，发送侧 unsupported，无证据处 unknown |

## 未做（下一步）

- Gate D：Adapter Contract 测试（12 项 × OneBot11/Milky）—— 需要把描述符接进容器（`make_adapters`）；
- Gate E/F：`TestProtocolAdapter` 实验与 PEC 测量；
- §35：把能力暴露给插件（`ctx.capabilities`）—— 属于 SDK 面变更，与 Gate E 一起做。
