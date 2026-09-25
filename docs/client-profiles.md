# 客户端档案（Client Profiles）

> 任务书 `/storage/emulated/0/协议.txt` §九/§十/§十二/§十一/§二十三。
> 实现：`src/adapters/client_profile.py`（档案）+ `src/adapters/onebot_serializer.py`（出站序列化）。
> 逐客户端逆向记录：[reverse-engineering/](reverse-engineering/)；矩阵：[client-compatibility.md](client-compatibility.md)。

## 1. 为什么是"档案"而不是"每个客户端一套 Adapter"

```text
OneBot11Adapter / MilkyAdapter
      │
      ├── ClientProfile(go-cqhttp)      ← 已验证差异写在这里
      ├── ClientProfile(napcat)
      ├── ClientProfile(llbot)
      └── ClientProfile(lagrange)       ← 源码不可得 → 只有 [DOC]，能力格大量 UNKNOWN
```

- **协议基线**（spec）与**客户端实现**分开：`ONEBOT11_SPEC` 只有规范条文支持的能力；
  某客户端"多做了一点"不会污染基线，某客户端"少做"也不会让基线降级。
- 档案是**纯数据**：`capabilities`（四态）+ `quirks`（已验证字段/取值/命名空间）。
- **禁止**在 Core/Services/SDK/Plugins 里出现 `if client == "napcat"`：上层只问
  `profile.state("capability")` / `profile.quirk(name)`。

四态与证据等级沿用任务书词汇：`SUPPORTED / PARTIAL / UNSUPPORTED / UNKNOWN`、
`[CODE] / [DOC] / [MVP] / [INFERENCE] / [UNKNOWN] / [SOURCE_UNAVAILABLE]`。

## 2. 当前档案总览（截至本轮）

| 协议 | 客户端 | 版本 | 证据 | 覆盖情况 |
| :--- | :--- | :--- | :--- | :--- |
| onebot11 | **spec**（基线）| botuniverse/onebot-11 `d4456ee` | [DOC] | 段/API/响应三态；**没有** poke/mface/dice/rps（规范里确实不存在 → UNSUPPORTED）|
| onebot11 | **go-cqhttp** | `a5923f1`（archived）| **[CODE]** | 发送侧 case 表 + 上报侧逐字段（见 RE 文档）|
| onebot11 | **napcat** | `0b4cfe6` | [CODE] | 元素模型/段/合并转发（既有逆向，字段级）|
| onebot11 | **llbot** | `9f374f6` | [CODE] | OneBot 入站 + `shake` 戳一戳段；其余多格 UNKNOWN |
| onebot11 | **lagrange** | Lagrange.Doc `98e96e5` | [DOC]（且页面自称过时）| 实现源码 **SOURCE_UNAVAILABLE**（404，见 [source-acquisition.md](source-acquisition.md) C4）→ 只登记文档给出的 File/Node 段 |
| milky | **spec** / 实现 | Milky-spec `151dd90` / 内嵌实现 | [DOC]+[CODE] | 段与事件（既有逆向：milky-protocol.md）|

> 未调查的（onebots / Yogurt / OpenShamrock / imhelper 等）**不登记**，也不在矩阵里写 SUPPORTED ——
> 查询它们会得到 `UNKNOWN`（`profile_for()` 返回空档案）。

## 3. go-cqhttp 的已验证差异（本轮新增，全部 [CODE]）

来源：`~/proto_src/go-cqhttp coolq/cqcode.go`（发送侧 L404-1010）、`coolq/converter.go`、`coolq/event.go`、`coolq/api.go`。

| 事实 | 值 | 与谁不同 |
| :--- | :--- | :--- |
| 支持发送的段（case 表）| text / image / reply / forward / poke / tts / face / share / music / dice / rps / xml / json / `cardimage` / video / **file** | NapCat 有 `mface`，go-cqhttp **没有** → 商城表情在它这里降级为 `text` |
| `image.file` 支持的写法 | `http(s)` / `file://` / `base64://` / `base16384://` / hex（`<md5>.image`）/ 裸路径 | 其它客户端未逐条验证 |
| `image.type` | `flash`、`show`（`show` 需 `id`，区间外被夹到 40000）| NapCat 的闪照/特效字段名不同（见矩阵）|
| `reply` | `id` = **客户端 DB 的 global id**；一条消息只保留一个 reply 且**提到最前**；自定义回复用 `text`+`user_id/qq`（+`time/seq`）| 上报侧 `message_seq` 是另一个命名空间；Milky 用 `message_seq` |
| `record` 发送 | **只读 `file`**（本地文件，自动转 SILK/AMR）| 上报侧却有 `url` → **同段不同方向字段不同** |
| `video` 发送 | `file` + `cover` + `cache` | —— |
| `file` 发送 | `path/name/size/busid`（`size` 字符串转 int）| NapCat 用 `file_id` 命名空间 → 跨客户端不可直接复用 |
| `at` | `qq`，缺失时读 `target`；`qq=="all"` → AtAll；可选 `name` | 规范只有 `qq` |
| `poke` 段 | 字段是 `qq` | NapCat 是 `{type,id}`；LLBot 是 `shake` |
| `dice` / `rps` | `value` 范围 0..6 / 0..2，越界**报错** | —— |
| 未知段 | `IgnoreInvalidCQCode=false`（默认）时回退成**字面 CQ 文本** | 各客户端兜底策略不同 → 序列化器只标记，不复刻转义 |
| 响应包封 | `ok` / `async` / `failed`；失败带 `msg+wording+message` | 规范定义三态；NapCat 同构但字段更少 |

## 4. 出站序列化怎么用（本轮新增）

```python
from src.adapters.client_profile import GO_CQHTTP, profile_for
from src.adapters.onebot_serializer import serialize_segments

profile = profile_for("onebot11", "go-cqhttp")     # 未调查客户端 → 空档案（全 UNKNOWN）
wire, notes = serialize_segments(internal_segments, profile=profile)
# wire  = 该客户端能接受的段数组
# notes = 每一次降级/丢弃/原样传递的理由（测试与日志都断言它，**不静默改语义**）
```

规则（三条）：

1. **档案未验证的段：原样传递 + note**（不伪造支持，也不吞掉用户内容）；
2. 只有"有证据表明客户端会拒绝/误解"的字段才被移除，并且**一定**留下 note；
3. 客户端自己的兜底行为（如 go-cqhttp 把未知段变成字面 CQ 文本）**不由我们复刻** —— note 里写明即可。

**当前接入状态（如实）**：序列化器已就绪并有契约/往返测试，但**尚未接入发送热路径** ——
接入需要"按档案选择 profile"的配置开关与 CI 验证（下一轮）。在那之前，
`Sender.send_msg_raw()` 保持原样透传，行为与今天一致。

## 5. 怎么加一个新客户端（清单）

1. 先取源码：`git clone --depth 1` 到 `~/proto_src/`；取不到就写
   `SOURCE_UNAVAILABLE`（附命令与输出），**不要**用别的客户端实现代替；
2. 找三处证据：**发送侧**（入参段 → 内部结构）、**上报侧**（内部结构 → 段/事件 JSON）、**响应包封**；
3. 建 `tests/fixtures/<client>/`（每个文件带 `_provenance`，`source` 精确到文件:行）；
4. 在 `client_profile.py` 里登记 `capabilities`（只写有证据的；其余留空 = UNKNOWN）与 `quirks`；
5. 写 `docs/reverse-engineering/{onebot11,milky}/<client>.md`（Source/Version/Evidence/Observed/
   Normalized/Known Differences/Unknowns/Tests 八段）；
6. 跑 `tests/test_fixtures_corpus.py` / `tests/test_onebot_serializer.py` / `tests/test_client_contract_matrix.py`。

> 未验证的东西不写进档案 —— 矩阵里的空格是**信息**，不是待办清单上的勾。
