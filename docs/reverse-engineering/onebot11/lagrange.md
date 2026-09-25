# Lagrange（OneBot 11）逆向 —— **SOURCE_UNAVAILABLE**

> 任务书 ~/storage/emulated/0/协议.txt §三/§五/§二十三。这一份与其他客户端档案**不同**：
> **实现源码拿不到**，所以本文件记录的是"查了什么、怎么失败、还剩什么证据"，而不是行为结论。

## Source

| 项 | 值 |
| :--- | :--- |
| 目标仓库 | `LagrangeDev/Lagrange.OneBot` |
| 获取结果 | **SOURCE_UNAVAILABLE**（HTTP 404；详见 [../../source-acquisition.md](../../source-acquisition.md) C4）|
| 替代证据 | `LagrangeDev/Lagrange.Doc` `98e96e5`（官方文档仓库，**页面自称已过时**并指向 Apifox）|
| 同组织的其它仓库 | `Lagrange.Core` / `LagrangeV2`（已获取）—— 但它们**只含 Lagrange.Milky**，grep `onebot` 无有效命中 |
| 第三方实现 | GitHub 搜索只找到 `HornCopper/Lagrange-Python.OneBot`（第三方）与 `Lagrange.OneBot.DatabaseShift`（迁移工具）→ **不作为证据** |

可复现命令（2026-09-25 实测）：

```text
$ curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOKEN" \
      https://api.github.com/repos/LagrangeDev/Lagrange.OneBot
404
$ curl -s -H "Authorization: Bearer $TOKEN" 'https://api.github.com/orgs/LagrangeDev/repos?per_page=100' \
  | python3 -c "import json,sys;print([r['name'] for r in json.load(sys.stdin)])"
['Lagrange.Core', 'lagrangejs', 'Lagrange.Doc', 'lagrange-python', 'liblagrange', …]
# 组织仓库清单里没有任何 OneBot 11 实现
$ grep -ril onebot ~/proto_src/Lagrange.Core/ ~/proto_src/LagrangeV2/ --include='*.cs'
Lagrange.Core/Lagrange.Core.Runner/QrCodeHelper.cs      # 无关命中
```

## Version

- 文档：`Lagrange.Doc 98e96e5`（与既有的 `Lagrange.Milky.Document` 同提交）。
- 实现：**无版本可写**（源码不存在）。

## Evidence

- `[DOC]`：`Lagrange.Doc docs/v1/Lagrange.OneBot/` 下的 7 个页面；
- `[SOURCE_UNAVAILABLE]`：OneBot 11 实现本身；
- `[CODE]`：**没有** —— 本文件不含任何源码级行为断言。

## Observed Behavior（文档能给的部分）

`docs/v1/Lagrange.OneBot/Segment/OneBot/index.md` / `API/OneBot/index.md` 正文只有一句
"请参考 OneBot V11 Segment/API" + "并非所有标准 API 都已实现"，**没有字段表**。
唯一有字段表的是扩展段（`Segment/Extend/index.md`）：

| 段 | 字段 [DOC] |
| :--- | :--- |
| File | `group_id(int) / file_id(string) / file_name(string) / busid(int) / file_size(int) / upload_time(int) / dead_time(int) / modify_time(int) / download_times(int) / uploader(int) / uploader_name(string)` |
| Folder | `group_id(int) / folder_id(string) / folder_name(string) / create_time(int) / creator(int) / creator_name(string) / total_file_count(int)` |
| Node | `uin(string) / name(string) / content(OneBotSegment 或 List[OneBotSegment])` |

## Normalized Behavior（Flowerie 现状 [MVP]）

- 客户端档案里 Lagrange 只登记了 `file` / `forward_segment`（有文档字段表的两项），
  其余能力一律 `UNKNOWN~ —— 查询得到 UNKNOWN，**不会**因为"它说参考规范"就默认支持；
- 没有该客户端的 fixture（**没有源码可依**，不允许凭文档正文手写"看起来像"的 JSON）。

## Known Differences

无法给出 —— 没有源码级对照物。已知的**与其它客户端不同之处**仅限文档层面：
扩展段 File/Folder 的字段集与 NapCat/LLBot/go-cqhttp 三家都不一样（可对照各自档案）。

## Unknowns

1. OneBot 11 标准段的实际字段与取值（文档无表、源码缺失）；
2. Action 覆盖范围（文档只说"并非全部实现"，未列清单）；
3. 响应包封细节（`status`/`retcode`/`msg` 形态未知）；
4. 事件字段（`font` / `message_id` 语义 / `sender` 字段集完全未知）；
5. 是否能从 fork / 镜像 / 旧 tag 找回源码 —— 本轮只查了组织仓库清单与 GitHub 搜索，**未穷尽**（后续可再试
   `Lagrange.OneBot.DatabaseShift` 的历史、第三方 fork、CI 产物等）；
6. 实机抓包：**BLOCKED BY EXTERNAL DEPENDENCY**（既要客户端实例，也要先拿到可运行的实现）。

## Tests

- **没有**该客户端的契约测试（没有语料 → 不假装跑过）；
- 相反地，有一条**反向**测试：`tests/test_client_contract_matrix.py::test_every_profile_has_evidence_and_source` 会检查
  每个档案都必须写清证据等级与出处 —— Lagrange 档案的 `[DOC]` + SOURCE_UNAVAILABLE 说明就是它的"证据"。
