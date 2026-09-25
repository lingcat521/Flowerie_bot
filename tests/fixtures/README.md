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

## 新增样本的规矩

1. 先在客户端源码里找到**确切的字段定义**（记文件+行号），再写 JSON；
2. `_provenance` 必填 `client` / `status` / `captured` / `evidence` / `note`；
3. 跑 `tests/test_fixtures_corpus.py`（会强制校验溯源字段并断言归一化结果）；
4. 若是**实机抓包**，把 `captured` 置 `true`（脱敏后）并注明来源客户端版本 —— 目前没有这类样本。
