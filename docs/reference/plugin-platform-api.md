# 插件平台 API

五种 SDK 通过同一条 JSON-Lines `action` 请求调用宿主。下表的第一列也是 wire action 名。manifest 中声明权限后仍须由管理员批准；服务关闭时返回 `{ok:false,code:"unavailable"}`，无权限时由插件权限系统拒绝。

## 平台能力

| Action / Python、Rust 方法 | 参数 | 权限 | 成功返回的主要字段 |
|---|---|---|---|
| `profile_get` | `group_id, user_id` | `read_member_profile` | `profile`，不存在时为 null |
| `profile_set_section` | `group_id, user_id, label, text, nickname` | `write_member_profile` | `message` |
| `profile_delete` | `group_id, user_id` | `write_member_profile` | `deleted` |
| `web_search` | `query, limit`（默认 5，1–10） | `web_search` | `sources, engine, engines_used, note` |
| `knowledge_list` | `group_id, query, limit`（默认 20，1–100） | `read_group_knowledge` | `items` |
| `persona_resolve` | `group_id` | `read_group_info` | `persona`，仅 ID、名称及简介，无法解析时为 null |
| `nickname_resolve` | `group_id` | `read_group_info` | `nickname`，按当前人格和群昵称的现有规则解析 |
| `qzone_history` | `limit`（默认 20，1–100） | `read_qzone_history` | `items`，从新到旧 |
| `qzone_rights` | 无 | `read_qzone_history` | `rights, default_ugc_right` |
| `qzone_publish` / `qzone_delete` | 发布 `content, images, ugc_right, target_uins`；删除 `tid` | `qzone` | 现有网关返回 |
| `automation_status` | 无 | `scheduler` | `features`，自动化面板的布尔开关 |
| `schedule_register` | `kind, when, name` | `scheduler` | `schedule_id, name, kind` |
| `schedule_list` | 无 | `scheduler` | `schedules` |
| `schedule_cancel` | `schedule_id` | `scheduler` | `schedule_id` |

- 画像以群号和用户号联合定位，开放 `personality`、`interests`、`life`、`traits` 四项。读取返回头像以外的存储数据（昵称与画像分项）。修改走原有内容校验。画像读取与写入权限独立，批准后插件仍需显式选择目标群和用户。
- 搜索复用花璃当前配置的搜索引擎、缓存和结果消毒，要求 `AI_SEARCH_ENABLED`。结果来自外部网页，插件应作为不可信数据处理。
- QQ 空间历史来自花璃本地的 QQ 空间服务，内容可能截断，图片只返回数量。插件发布成功且网关返回 `tid` 时也记入本地历史，成功删除后移除对应记录。
- 自动化状态只返回开关。插件可注册自己的临时任务，`interval` / `delay` 使用秒数，`daily` 使用服务器本地时间的 `HH:MM`。同名覆盖。任务事件只投递给所属插件，重启后由插件重新注册。

## 私聊和群管理

下列接口包装现有网关动作。操作必须同时具备已批准的插件权限和当前 QQ 网关／Bot 账号所支持的能力。

| Action | 参数 | 权限 |
|---|---|---|
| `send_private_message` | `user_id, message` | `send_message` |
| `user_history` | `user_id, count` | `read_user_info` |
| `get_group_members` | `group_id` | `read_group_info` |
| `group_ban` | `group_id, user_id, duration`（秒，0 解禁） | `group_manage` |
| `group_kick` | `group_id, user_id, reject_add` | `group_manage` |
| `group_admin` | `group_id, user_id, enable` | `group_manage` |
| `group_whole_ban` | `group_id, enable` | `group_manage` |
| `group_rename` | `group_id, name` | `group_manage` |
| `group_card` | `group_id, user_id, card` | `group_manage` |
| `group_title` | `group_id, user_id, title` | `group_manage` |
| `group_shut_list` / `group_leave` | `group_id`；退群另收 `is_dismiss` | `read_group_info` / `group_manage` |

私聊发送沿用插件的主动消息通道。私聊允许名单和冷却配置属于花璃自动回复流程。Python 的经典 `api.send_private_message({...})` 和旧群管理方法仍接收字典。其他语言的新私聊发送便捷方法接收文本；消息段数组使用原有通用 `action`。

## 各语言调用

| 语言 | 搜索 | 查看私聊历史 | 禁言 |
|---|---|---|---|
| Python | `api.web_search("花璃", 5)` | `api.user_history(20001, 20)` | `api.group_ban({"group_id": 10001, "user_id": 20001, "duration": 60})` |
| TypeScript | `await ctx.webSearch("花璃", 5)` | `await ctx.userHistory(20001, 20)` | `await ctx.groupBan(10001, 20001, 60)` |
| Go | `ctx.WebSearch("花璃", 5)` | `ctx.UserHistory(20001, 20)` | `ctx.GroupBan(10001, 20001, 60)` |
| Rust | `ctx.web_search("花璃", 5)?` | `ctx.user_history(20001, 20)?` | `ctx.group_ban(10001, 20001, 60)?` |
| Java | `ctx.webSearch("花璃", 5)` | `ctx.userHistory(20001L, 20)` | `ctx.groupBan(10001L, 20001L, 60)` |

TypeScript 和 Java 使用 lowerCamelCase，Go 使用首字母大写形式（如 `GetGroupMembers`）。Rust 的 `schedule_register` 时间参数用 `Json::num(60)` 或 `Json::str("09:30")`。Python 高层 `FlowerieBot` 也提供 `bot.send_private_message(user_id, message)`、`bot.group_ban(group_id, user_id, duration)` 等便捷方法。

已有 AI、记忆、MCP 工具调用、存储、消息、插件通信和 Web UI 继续使用原接口。后台管理员凭据与任意配置写入由管理入口负责。

## 扩展能力与管理接口

便捷方法沿用相同的 action 名。Python 和 Rust 使用 snake_case，TypeScript 和 Java 使用 lowerCamelCase，Go 使用 PascalCase。表中的 **对象** 使用协议字段名，例如 `group_id`。标为 **位置** 的方法按表中的顺序接收参数。MCP 在经典 Python API 上接收对象，`FlowerieBot` 的现有 `mcp_resource(server, uri)` 和 `mcp_prompt(server, name, arguments)` 仍可用。

| Action | 便捷方法参数 | 权限 | 成功返回 |
|---|---|---|---|
| `digest_get` | 位置 `group_id` | `read_daily_digest` | `digest: {date, text}`，无记录时为 null |
| `memory_semantic` | 便捷名 `blossom_search(group_id, query, top_k)` | `read_memory` | `memory`，来自真实花语记忆服务 |
| `sticker_search` | 对象 `keyword, limit`（默认 8，上限 50） | `read_sticker_library` | `stickers`，只返回文件名和描述 |
| `sticker_send` | 对象 `group_id, filename, text?` | `send_sticker` | `filename`，仅发送已索引的库内图片，应用表情包冷却 |
| `knowledge_get` / `knowledge_delete` | 位置 `group_id, knowledge_id` | `read_group_knowledge` / `write_group_knowledge` | `item` / `message` |
| `knowledge_match` | 对象 `group_id, text, limit?` | `read_group_knowledge` | `items`，使用群知识命中规则 |
| `knowledge_add` | 对象 `group_id, term, meaning, examples?, confidence?` | `write_group_knowledge` | `message` |
| `knowledge_update` | 对象 `group_id, knowledge_id, meaning?, examples?, confidence?, status?` | `write_group_knowledge` | `message`，仅更新传入字段 |
| `knowledge_clear` | 位置 `group_id` | `write_group_knowledge` | `message` |
| `profile_list` | 对象 `group_id, page?, limit?`（默认第 1 页、20 条，单页最多 100） | `read_member_profile` | `items, page, count`，分项含时间戳 |
| `profile_clear` | 位置 `group_id` | `write_member_profile` | `deleted` |
| `persona_list` | 无 | `read_group_info` | `items`，仅基本信息 |
| `persona_get` | 位置 `persona_id` | `read_persona_content` | `persona`，包含原文；无记录时为 null |
| `persona_bind` / `persona_unbind` | 位置 `group_id, persona_id` / `group_id` | `manage_group_persona` | `message` |
| `persona_create` / `persona_update` | 对象 `persona_id, name?, system_prompt?, description?, vocabulary?, behavior_rules?, response_style?`；创建时必填名称与核心 Prompt | `manage_personas` | `message` |
| `persona_delete` / `persona_set_global` | 位置 `persona_id` | `manage_personas` | `message` |
| `nickname_list` / `nickname_set` | 位置 `group_id` / 对象 `group_id, persona_id?, nickname`（空昵称清除指定条目） | `read_group_info` / `manage_group_persona` | `items` / `nickname` |
| `group_prompt_get` / `group_rules_get` | 位置 `group_id` | `read_group_prompt` | `content` |
| `group_prompt_set` / `group_rules_set` | 位置 `group_id, content` | `write_group_prompt` | `content` |
| `group_prompt_reset` | 位置 `group_id` | `write_group_prompt` | `deleted` |
| `global_prompt_get` / `global_prompt_reset` | 无 | `read_global_prompt` / `write_global_prompt` | `content` / `deleted` |
| `global_prompt_set` | 位置 `content` | `write_global_prompt` | `content` |
| `private_users` | 对象 `limit?`（默认 20，上限 100） | `read_private_memory` | `items`，每项含用户 ID 和记忆数量 |
| `private_policy` / `private_allowlist_set` | 无 / 对象 `user_ids` | `read_private_memory` / `manage_private_policy` | `enabled, allowed_qqs` / `message` |
| `private_memory_clear` | 位置 `user_id` | `write_private_memory` | `deleted`，只清理该用户的私聊记忆 |
| `web_search` | 便捷名 `web_search_options(payload)`，对象 `query, limit?, time_range?, engine?` | `web_search` | `sources, engine, engines_used, note` |
| `web_fetch` | 位置 `url, max_chars`（1–4000） | `web_search` | `url, title, text, truncated`；沿用插件 HTTP 出站限制 |
| `automation_tasks` | 无 | `scheduler` | `tasks`，含后台活跃状态；摘要、梗总结、自动发动态附进程内最近一轮结果 |
| `automation_set_flags` | 对象 `flags`，只接受自动化面板的布尔开关 | `manage_automation` | `message`；沿用现有热更新与重启语义 |
| `mcp_resource` | 对象 `server, uri?, cursor?`，空 URI 列表 | `mcp_read_resource` | `result` |
| `mcp_prompt` | 对象 `server, name?, cursor?, arguments?`，空名称列表 | `mcp_read_prompt` | `result` |

`time_range` 取 `day`、`week`、`month` 或 `year`，各搜索引擎有各自的过滤支持。定时循环的最近结果在进程重启后清空；群摘要仍从持久化存储读取。MCP 资源和提示词使用已启用的服务器配置，旧的 `http_request` 权限不授予这两项读取权限。

五语言另有群公告、群文件/文件夹、好友和私聊动作的同名便捷方法，复用既有 action 契约。当前网关缺少执行端点时，`group_file_upload`、`group_file_rename`、`group_invite`、`friend_remark`、`friend_delete` 仍返回 `not supported`。文件管理已支持的操作包括列目录、取文件 URL、移动和删除文件、创建/重命名/删除文件夹，具体取决于运行网关。

## 群消息分析配置

管理员可在 Web UI 服务上用 Bearer token 请求 `GET /api/config/message-analysis` 查询，用 `PATCH /api/config/message-analysis` 批量修改。PATCH 请求体是配置键值对象，例如：

```json
{
  "MESSAGE_ANALYSIS_PREFERENCE_MODEL": "qwen2.5:3b",
  "MESSAGE_ANALYSIS_TOXIC_MODEL": "qwen2.5:7b",
  "MESSAGE_ANALYSIS_GROUP_IDS": [123456],
  "TOXIC_GROUP_IDS": [123456]
}
```

支持全部 `MESSAGE_ANALYSIS_*` 字段，以及 `TOXIC_GROUP_IDS` 和 `TOXIC_WARNING_COOLDOWN`。两个群列表使用正整数数组，`[]` 清空。语义引战检测要求群在两个列表中，喜好提取还受现有长期记忆开关控制。模型与地址用字符串，预算、超时与冷却用整数。专用模型或接口地址传空字符串可恢复继承共用配置。密钥传新字符串设置，传 `null` 清除。切换地址时，若有原本绑定到旧地址的密钥将随配置发往新地址，须在同一请求中更换或清除这些密钥。

读取返回 `{ok, values, secrets_configured}`，密钥只返回各自是否已配置。修改成功返回 `{ok, saved}`，`saved` 为本次写入的键。只提交要修改的字段，任一字段校验失败会拒绝整批。成功保存后立即生效并持久化。

插件须在 manifest 的 `permissions` 中声明 `manage_message_analysis` 并获得管理员批准。这项权限能改适用群和模型服务地址，只应授予受信任的插件。自行实现协议的插件使用反向 `engine` 操作 `message_analysis.get`（`args: {}`）和 `message_analysis.update`（`args: {"values": {...}}`）。

| SDK | 查询 | 修改 |
|---|---|---|
| Python `api` / `bot` | `message_analysis_get()` | `message_analysis_update(values)` |
| TypeScript `ctx` | `await ctx.messageAnalysisGet()` | `await ctx.messageAnalysisUpdate(values)` |
| Go `ctx` | `ctx.MessageAnalysisGet()` | `ctx.MessageAnalysisUpdate(values)` |
| Rust `ctx` | `ctx.message_analysis_get()?` | `ctx.message_analysis_update(&values)?` |
| Java `ctx` | `ctx.messageAnalysisGet()` | `ctx.messageAnalysisUpdate(values)` |

请检查响应的 `ok` 字段。Java 清除密钥时请用支持 `null` 值的 `Map`，例如 `HashMap`。

## 模型连通性探测

管理员用 Bearer token 请求 `POST /api/models/ping`。请求体使用 `{"target":"all"}`，也可用空对象或省略请求体来并行探测全部模型。通过 `target` 指定单个模型：

| target | 模型 |
|---|---|
| `chat` | 主聊天模型 |
| `vision` | 视觉识图模型 |
| `toxic` | 关键词预筛后的引战判定模型 |
| `analysis_preference` | 喜好提取模型 |
| `analysis_toxic` | 语义引战检测模型 |
| `embedding` | 向量模型 |
| `reranker` | 重排模型 |
| `search` | DeepSeek 原生搜索模型 |

有效请求返回 HTTP 200 和 `{ok, results}`。`results` 按目标名索引，每项含 `ok`、`status`、`message`，实际探测项还含 `model`、`latency_ms`，上游 HTTP 失败时附 `http_status`。至少一项可达且已配置项均成功时，总体 `ok` 为真。逐项状态包括 `reachable`、`unconfigured`、`invalid_configuration`、`timeout`、`http_error`、`connection_error`、`invalid_response`。无效参数返回 HTTP 400，并发探测请求返回 HTTP 429。

探测使用已保存的配置和固定测试内容，单次请求最多等待约 8 秒。同一批里共用地址、模型、凭据和请求格式的目标只请求一次，未配置的目标直接跳过。探测会实际调用模型，可能产生少量推理费用。视觉探测测试模型连通性，搜索探测测试模型接口且不触发搜索工具。

插件须声明并获得管理员批准的 `ping_models` 权限。五种 SDK 均使用同一反向 `engine` 操作 `models.ping`，参数为 `{"target":"all"}`。

| SDK | 并行探测全部 |
|---|---|
| Python `api` / `bot` | `ping_models()` |
| TypeScript `ctx` | `await ctx.pingModels()` |
| Go `ctx` | `ctx.PingModels("all")` |
| Rust `ctx` | `ctx.ping_models("all")?` |
| Java `ctx` | `ctx.pingModels("all")` |

## 文件解析

文件解析复用 Bot 的文档提取服务和当前格式、页数、行数设置。三个动作都需在 manifest 中声明 `parse_files` 并由管理员批准。

| Action | 参数 | 返回 |
|---|---|---|
| `file_parse_status` | 无 | 总开关、群文件开关、各格式启用和依赖状态，以及字节、文本和格式上限 |
| `file_parse` | `filename`、`content_base64`（标准 Base64） | `filename, format, bytes, text, truncated` |
| `file_parse_local` | `path`（相对于本插件 `data/` 的路径） | 同上；另需批准 `filesystem_read` |

内联请求最多 32 KiB 原始字节，若配置更小则采用配置值。更大的文档用 `file_parse_local`，输入上限为 `MAX_FILE_DOWNLOAD_BYTES`。本地入口仅支持能够按已打开的目录句柄读取且拒绝跟随链接的宿主，查看 `plugin_local_supported` 可检测。插件返回文本最多 8,000 字符，配置更小时采用更小值。`truncated` 表示输出超过字符上限。扫描 PDF 需要先做 OCR 才能提取正文。

| SDK | 查询状态 | 解析 Base64 | 解析插件文件 |
|---|---|---|---|
| Python `api` / `bot` | `file_parse_status()` | `file_parse(filename, content_base64)` | `file_parse_local(path)` |
| TypeScript `ctx` | `fileParseStatus()` | `fileParse(filename, contentBase64)` | `fileParseLocal(path)` |
| Go `ctx` | `FileParseStatus()` | `FileParse(filename, contentBase64)` | `FileParseLocal(path)` |
| Rust `ctx` | `file_parse_status()` | `file_parse(filename, content_base64)` | `file_parse_local(path)` |
| Java `ctx` | `fileParseStatus()` | `fileParse(filename, contentBase64)` | `fileParseLocal(path)` |

解析结果是文档中的原始提取文本，插件应按不可信输入处理。API 不需要 AI 模型。关闭总开关后解析返回 `unavailable`，状态仍可查询。

### 管理 HTTP API

持管理员 Bearer token 请求 Web UI 服务。用 `GET /api/files/status` 查询有效配置，用 `POST /api/files/parse?filename=report.pdf` 发送 `application/octet-stream` 文件字节。文件名包含非 ASCII 字符时需 URL 编码。返回字段同插件 API，输入与文本长度采用管理配置上限。

```bash
curl -H "Authorization: Bearer ${FLOWERIE_TOKEN}" \
  -H "Content-Type: application/octet-stream" --data-binary @report.pdf \
  "http://127.0.0.1:8080/api/files/parse?filename=report.pdf"
```

错误返回 `{ok:false,code,error}`，常见 HTTP 状态有 400（参数）、401（未认证）、413（超限）、415（格式）、422（文件无法解析）、429（繁忙）和 503（关闭或缺少依赖）。
