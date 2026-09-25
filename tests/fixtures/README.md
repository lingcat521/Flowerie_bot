# tests/fixtures —— 真实协议形态样本语料

> 任务书 §22 交付物之一。**目的**：把"客户端真实字段形态"从源码里固化成可回归的样本，
> 以后改 Adapter 时能一眼看出"哪种客户端的哪种段被改坏了"。

## 诚实声明（重要）

- 这些样本是**按客户端源码逐字段构造**的，**不是实机抓包** —— 本环境无法运行 QQ 客户端，
  也没有真实账号事件流。每个文件里的 `_provenance` 写明证据文件与行号，可逐条回溯核对。
- 状态用任务书 §20 的词汇标注：`[CODE]`（源码实测）/ `[DOC]`（规范文档）/ `[MVP]`（本地 MVP 实测）。
- **未验证的东西不写进样本**：字段名没在源码里见过的，一律不出现（宁缺不编）。

## 语料清单

| 文件 | 客户端 | 覆盖形态 | 归一化去向 |
| :--- | :--- | :--- | :--- |
| `napcat/group_message_text_at_image.json` | NapCat | 群消息：at + text + image | `text` / `mentions` / `images` / `image_files` |
| `napcat/group_message_ark_multimsg.json` | NapCat | ARK 合并转发卡片（`app=com.tencent.multimsg`）| `json_cards`（`is_forward_card=true`）|
| `napcat/notice_group_upload.json` | NapCat | 群文件上传通知 | `notice_kind=group_upload` + `notice_file` |
| `napcat/notice_poke.json` | NapCat | 戳一戳通知（`notify/poke`）| `notice_kind=poke` + `target_id` |
| `llbot/onebot_message_file_and_shake.json` | LLBot | 文件段（带 file_id/path）+ `shake`（LLBot 的戳一戳段）| `files` / `pokes` |
| `milky/group_message_segments.json` | Milky | 八种段混合（text/mention/face/market_face/light_app/forward/file/markdown）| 六个归一化字段全命中 |
| `milky/group_nudge_event.json` | Milky | 戳一戳**事件**（`group_nudge`）| `kind=notice` + `notice_kind=poke` |
| `go-cqhttp/group_message_media_array.json` | go-cqhttp | 群消息：record/video/image(含闪照)/face/dice/rps | `records` / `videos` / `images` / `image_files`（url、subType、type 原样保留）|
| `go-cqhttp/group_message_marketface_as_text.json` | go-cqhttp | 商城表情被客户端**降级成 text** | `text`（与 NapCat 的 `mface` 段相对）|
| `go-cqhttp/group_message_service_xml.json` | go-cqhttp | `ServiceElement` → `xml{data,resid}` | `xmls` |
| `go-cqhttp/group_message_service_json_keeps_resid.json` | go-cqhttp | 内容不含 `<?xml` 时 type 改 json 但 **resid 仍留着** | `json_cards` + 原始段 |
| `go-cqhttp/group_message_file_segment.json` | go-cqhttp | 群文件段 `file{path,name,size*,busid*}`（size/busid 是字符串）| `files` |
| `go-cqhttp/group_message_anonymous.json` | go-cqhttp | 匿名消息：`sub_type=anonymous` + `anonymous{flag,id,name}` | `raw_data` 保留（未提升为语义字段，见 RE 文档 Unknowns）|
| `go-cqhttp/private_temp_message.json` | go-cqhttp | 群临时会话：来源群在 **`sender.group_id`** + `temp_source` | `scene=temp` + `context_group_id`（本轮修复）|
| `go-cqhttp/notice_group_upload.json` | go-cqhttp | 群文件上传通知（`size/busid` 是 **int**，与段里的字符串相对）| `notice_file` |

### 响应类语料放 `actions/` 子目录

`tests/fixtures/<client>/actions/*.json` 放 **Action 响应包封**（不是事件）。
语料回归 `tests/test_fixtures_corpus.py` 只扫 `fixtures/<client>/*.json`（一层），
所以响应样本不会被事件解析器误扫；它们由 `tests/test_onebot_response_contract.py` 驱动生产代码
`src/transport/onebot_response.py` 断言：

```text
tests/fixtures/go-cqhttp/actions/
├── action_get_msg_response.json      # {data,retcode:0,status:"ok",message:""}
└── action_failed_response.json       # {data:null,retcode,msg,wording,message,status:"failed"}
```

## 新增样本的规矩

1. 先在客户端源码里找到**确切的字段定义**（记文件+行号），再写 JSON；
2. `_provenance` 必填 `client` / `status` / `captured` / `evidence` / `note`；
3. 跑 `tests/test_fixtures_corpus.py`（会强制校验溯源字段并断言归一化结果）；
4. 若是**实机抓包**，把 `captured` 置 `true`（脱敏后）并注明来源客户端版本 —— 目前没有这类样本。
