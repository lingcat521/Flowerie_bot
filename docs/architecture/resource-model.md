# ADR-007：资源抽象（ResourceRef / ResourceFetcher / 纯解码）

- **状态**：已实施（首版）｜**日期**：2026-08-09｜**对应 Gate**：R

## 要回答的问题

任务书 Gate R 要求：建立 Resource Model，三种输入（本地路径 / URL / 协议 resource_id）都要能进
统一 `ResourceRef`，且 **Core 不得直接依赖 OneBot `file_id`，也不得依赖 Milky `resource_id`**。

改造前的实际状态（不是假设，是源码）：

```text
src/core/message_router.py:503     "file_id": file_data.get("id", "")
src/core/message_assembler.py:283  file_id = file_info.get("file_id")
src/services/file_parser.py:59     async def fetch_and_parse_file(file_id, file_name)   # 直接拼 /get_file
```

也就是说：**Core 拿到的是协议字段名，services 直接拼 OneBot 端点并解析 NapCat 响应**
（`decode_napcat_file_response`）。这既是 Gate R 的违规，也藏着一个真实缺陷：
Milky 的群文件上传会把 Milky 的 `file_id` 交给 **OneBot** 端点 `/get_file` 去取 —— 协议串了。

## 决策：三段分离

```text
边界（Adapter）             取数（Adapter）                  解码（Services，纯函数）
解析器把协议字段归一成  ──►  ResourceFetcher.fetch(ref)  ──►  FileParser.decode_bytes(bytes, name)
ResourceRef（带 origin）      协议差异全在这里                  字节 → 文本（txt/pdf/docx/xlsx/csv）
```

| 角色 | 位置 | 职责 | 关键约束 |
| :--- | :--- | :--- | :--- |
| `ResourceRef` | `src/adapters/resource.py` | 协议中立的资源描述（kind/ref/name/size/origin/mime）| 非法 kind 直接 `ValueError`；`origin` 只作诊断与路由 |
| `ResourceFetcher` | Adapter（各协议实现）| 取字节，统一返回 `(bytes, ok)` | **失败不抛**、未接线**明确失败**（绝不静默返回空内容）|
| `decode_bytes` | `src/services/file_parser.py` | 字节 → 文本 | 纯解码，不认识任何协议 |

三种形态各有实现，由 `CompositeResourceFetcher` 按 kind 分派：

| kind | 实现 | 说明 |
| :--- | :--- | :--- |
| `local_path` | `LocalPathFetcher` | 先 `stat` 看大小再读（防止把大文件读进内存）|
| `url` | `URLFetcher` | 下载由注入的 `http_get(url, max_bytes)` 完成（网络库不进 Adapter）|
| `protocol_id` | `ProtocolIdFetcher` → 各协议 fetcher | OneBot `/get_file`；Milky `get_resource_temp_url` + URL 下载 |

### 协议取数的证据链

- **OneBot** `/get_file`：`{status, retcode, data:{file, file_name, file_size, base64?}}`；
  `base64` 是 NapCat / Lagrange 的实现扩展（`[CODE]` 见 docs/onebot-compatibility.md、
  tests/fixtures/napcat/**）。响应也可能是**本地路径**（`data.file`）——那就按 `local_path` 读，
  同一个 fetcher 复用，不重复实现。
- **Milky** `get_resource_temp_url`：`[CODE]` proto_src/LagrangeV2/Lagrange.Milky/Api/Handler/
  Message/GetResourceTempUrlHandler.cs L8-27 —— 参数 `{resource_id}`，结果 `{url}`；
  Lagrange.Core 同名 handler 一致，docs/milky-protocol.md 已登记该动作。两步（取临时 URL → 下载）。

**顺手修掉的真实缺陷**：改造前 Milky 的文件上传走 OneBot 端点（见上）；现在按 `origin` 分派，
Milky 走 Milky 的动作。未接线的 origin 会给出明确日志（`resource_protocol_unwired origin=...`），
而不是发一个错误协议的请求。

### Core 侧长什么样（改造后）

```python
# src/core/message_router.py —— 只搬引用，不认识协议
"resource": file_data.get("resource")

# src/core/message_assembler.py —— 拿引用 → 交给注入的 fetcher → 字节交给解码器
content_bytes, fetched = await self._fetch_resource(resource)
file_content, success = self.file_parser.decode_bytes(content_bytes, file_name)
```

`resource_fetcher` 由组合根注入（`main.py` 用 `build_resource_fetcher(call_api=sender.call_api,
http_get=file_parser.fetch_url_bytes, ...)`）；未接线时 Core **明确失败并写日志**，
不会去猜协议、也不会产出空内容冒充成功。

## 被否决的方案

1. **让 Core 调 `file_parser.fetch_and_parse_file(file_id, ...)` 但把名字改中性**：
   改名不解决依赖——Core 仍然在传协议字段、services 仍然在拼协议端点；
2. **把 ResourceRef 放进 services**：services 不能 import adapters（冻结层规则），
   模型只能放 Adapter 侧、由 Core 以**不透明对象**透传（Core 不需要 import 它）；
3. **URL 下载写在 Adapter 里直接 import httpx**：会让 Adapter 绑定网络库、也无法复用
   services 已有的上限/超时/客户端复用；改为注入 `http_get`（`FileParser.fetch_url_bytes`）；
4. **未接线时返回空内容当成功**：会让"文件解析失败"变成静默丢内容，明确失败 + 日志才是可运维的。

## 诚实边界

| 未做到 / 未验证 | 说明 |
| :--- | :--- |
| 实机未验证 | 取数链路全部在进程内用注入式 fetcher 验证；**真实协议端**的 `/get_file`、`get_resource_temp_url` 仍未联调（G5/G6 BLOCKED，设备未授权）|
| `src/services/sender.py` 仍有协议风格参数 | 群文件管理接口（`delete_group_file(file_id, busid)` 等）保留 OneBot 命名 —— 属**既有** API 面，不在 Gate R 的 "Core 不依赖" 范围内，登记为后续收敛项 |
| 转发/卡片仍在 services | `extract_forward_messages` 仍直连 `/get_forward_msg`（协议耦合），本轮只处理文件资源；已在缺口台账登记 |
| `decode_napcat_file_response` 保留 | 兼容老调用方的 JSON(base64) 解码入口；新路径不再经过它 |

## 复现方式

```bash
python3 -m pytest tests/test_resource_model.py -q                  # 13 项（含端到端资源链路）
# 本地无 aiohttp 时端到端用例会跳过；如需本地真实执行导入链：
PYTHONPATH=$HOME python3 -m pytest -p stubplug -p stubio tests/test_resource_model.py -q
```

## 实施中踩到的坑

- **`to_int(value)` 只接受一个参数**：迁移时按旧习惯写成 `to_int(x, 0)`，直接 TypeError；
  改回 `to_int(x) or 0`（`to_int` 对脏数据返回 None）；
- **isort 会把 import 行内注释规范成"两个空格"**：写成三个空格会被 ruff 判定
  `I001 Import block is un-sorted or un-formatted`（CI 抓到，本地 flake8 代理看不到）——
  现在本地检查器已加"import 行内注释间距"扫描，且约定优先把注释放到独立行；
- **端到端用例的导入链里有 aiohttp**（message_router → budget_manager → sender）：
  本地默认跳过并如实标注；本地验证时用可选的 `-p stubio` 插件补上最小 stub（不伪装网络行为）。
