# Flowerie Bot SDK 开发手册（Plugin API v1 · 版本 2.3.0）

> 讲 **`flowerie_sdk` 这一层怎么用**。运行时与协议（Manifest / 生命周期 / 打包 / 任意语言）见 [plugin-developer-guide.md](plugin-developer-guide.md)，
> 协议本身见 [plugin-protocol.md](plugin-protocol.md)，多语言总览见 [plugin-sdk.md](plugin-sdk.md)。所有 API 名都对着 `plugin_sdk/flowerie_sdk/` 核实过；
> 示例与 `tests/plugins/doc_example/` 同源，由 `tests/test_doc_example_plugin.py`（真加载 + 真路由）与 `tests/test_api_gap_consistency.py`（入口一致性）钉住。

## 1. 最小插件（可直接复制，跑得起来）

```text
plugins/myplugin/            # 默认 PLUGIN_DIR=./plugins，启动时自动发现
├── manifest.json
├── plugin.py
└── flowerie_sdk/            # cp -r "$REPO/plugin_sdk/flowerie_sdk" plugins/myplugin/  （插件自带副本，零依赖）
```

```json
{ "id": "myplugin", "name": "我的插件", "version": "1.0.0",
  "runtime": "python", "entry": "plugin.py", "api_version": "1",
  "permissions": ["read_message", "send_message"] }
```

```python
# plugins/myplugin/plugin.py —— 与 tests/plugins/doc_example/plugin.py 同源（CI 真加载、真路由、真 reply）
from flowerie_sdk import FlowerieBot, command, require_permission

bot = FlowerieBot()

@command("hi")
async def hello(event):
    await event.reply("你好呀")                 # 自动引用原消息

@command("add")
async def add(event):
    a, b = event.args[:2]                       # shlex 拆分后的参数
    await event.reply(str(int(a) + int(b)))

@command("ban")
@require_permission("group_admin")              # 仅群管理/群主可触发（主进程按 Rule 过滤，无法绕过）
async def ban(event):
    await event.reply("已执行管理操作")

def on_startup(context, api=None):
    bot.attach(api)                             # 绑定协议 api
    bot.register()                              # 上报 matcher（幂等，一次性）

def on_message(event, api=None):
    return bot.route(event)                     # SDK 路由；未匹配自动忽略
```

**跑起来**：放 `plugins/` → `bash run.sh`（或 `python3 main.py`）→ Web UI「插件」页**启用**并批准 `read_message` / `send_message`
→ 群里发 `!hi`（也支持 `/hi`、`.hi`）。不想带 `flowerie_sdk/` 副本也行：经典模式用 runner 给的回调
（`def on_message(event, api)` + `api.send_message({...})`），见 [plugin-developer-guide.md §3](plugin-developer-guide.md)。

### 1.5 30 秒速查（常用 API 一行例）

```python
@command("hi", rule=rule(is_group=True))    # !hi 且仅群聊
async def h(event):
    await event.reply("你好")                 # 回复当前上下文（返回 message_id）

await bot.send(("group", 777), "hi")        # 直发群（私聊用 ("private", 1001)）；await bot.recall(message_id) 撤回（仅本 bot 已发送记录）
await bot.mute(777, 123, 600) / bot.kick(777, 123)          # 禁言 10 分钟 / 踢人
await bot.get_context(777, 20)              # 群最近历史
await bot.wait_for(lambda e: e.text == "是", timeout=30)     # §7 等待下一条
await bot.cool_down("k", 60)                # §9 冷却（True=首次，False=冷却中）
bot.log("info", "hello")                    # §6 日志（走 stderr；永远别 print 到 stdout）
```

## 2. Event 完整参考（`BotEvent`，`plugin_sdk/flowerie_sdk/event.py`）

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `kind` | str | `message` / `notice` / `request` / `lifecycle`（`unknown` 兜底）|
| `scope` | str | `group` / `private` / `""`（无会话）|
| `notice_kind` / `request_kind` | str | notice 子类型（`group_increase` / `group_decrease` / `group_upload` / `poke` / `notify` …）/ 申请子类型（`friend` / `group`）|
| `user_id` / `group_id` / `message_id` / `time` | int/None | 触发者 / 群号 / 消息 id（`recall` 需要）/ 时间戳 |
| `text` | str | **纯文本**（引擎投递时截 2000 字符，`BotEvent` 再兜底截 4000）|
| `at_list` / `images` | list[str] | 被 @ 的 QQ（≤20，`"all"`=全体）/ 图片 URL 或路径（≤10）|
| `reply_id` / `message` | int/None · BotMessage | 本条是引用回复时被引用的 message_id / 由 text/at_list/images/reply_id 派生的结构化消息 |
| `matcher_name` / `matcher_args` | str | 命中的 Matcher 名 / 命令参数（`!hi 世界` → `"世界"`）|
| `schedule_id` / `trigger` | str | 定时事件专用（`interval` / `delay` / `daily`）|
| `is_group` / `is_private` | bool | 会话类型判定 |
| `event.args` | list[str] | `matcher_args` 的 shlex 拆分（`!add 1 "2 3"` → `["1", "2 3"]`）|
| `await event.reply(msg)` · `recall()` · `reply_many(list)` | — | 回复本事件（群→群自动引用）/ 撤回本条 / 拆多条（§4.5）|
| `event.stop()` · `event.stopped` | — | 阻断本插件后续 Matcher / Listener |

> 引擎投递的原始字典里还有 `operator_id` / `trace_id`（非消息事件可能带 `lifecycle_kind`），**`BotEvent` 目前不透传**；
> 要用就走经典模式（`event` 是 dict：`event["operator_id"]`）。

```python
@bot.listen("notice", priority=10)          # 消息之外：监听 notice / request / lifecycle
async def on_increase(event):
    if event.notice_kind == "group_increase":
        await event.reply(BotMessage().add_text("欢迎新成员！").at(event.user_id))
```
> **注意**：注册了 matcher 的插件**只收到匹配事件**；要全量 notice 就别在该插件注册 matcher（或拆插件）。

## 3. BotMessage 完整参考（消息构造）

| 属性 / Builder（链式，返回自身）| 说明 |
| --- | --- |
| `BotMessage("文本")` / `.add_text("x")` | 构造 / 追加文本（**读取用 `.text` 属性**）|
| `.at(qq)` / `.at("all")` | @ 某人（可多次）/ 全体 |
| `.image(url)` / `.video(url)` / `.voice(url)` | 图片 / 视频 / 语音（http(s) URL 或本地路径）|
| `.file(url, name="报告.pdf")` / `.reply(message_id)` / `.add_segment("keyboard", {...})` | 文件（可带显示名）/ 引用回复 / 通用段（高级、平台相关）|
| `.card(app_data)` / `.markdown(text, style)` / `.button(label, action, style)` | 富内容，底层转 json / markdown / keyboard 段（网关支持度自担）|
| `.merge(other)` / `.has(kind)` / `iter(msg)` | 合并另一条 / 判定 `"text"`·`"at"`·`"image"`·`"video"`·`"voice"`·`"file"`·`"reply"` / 产出有序元组 |

```python
@command("看图")
async def show_image(event):
    await event.reply(BotMessage("今天的美图：").image("https://example.com/a.png"))   # 引用回复（文字+图片）

@command("领文件")
async def send_file(event):
    await bot.send(("group", event.group_id),
                   BotMessage("文档请查收：").file("https://example.com/report.pdf", name="报告.pdf"))
```
- **本地文件**：插件目录内用 `file_read` / `file_write`（[plugin-developer-guide.md §12](plugin-developer-guide.md)）；图片/语音路径要平台可访问。
- **按钮 / Markdown / 卡片**不在 OneBot11 标准段内，能否生效取决于网关；段被丢弃或整条失败（`BotAPIError`）都属正常，先小范围验证。

## 4. 完整 Bot API（`FlowerieBot`，全部 await）

| API | 说明 |
| --- | --- |
| `await bot.send(target, message, reply_id=None)` | target：`("group", 123)` / `("private", 456)` / 群号 int；返回 message_id |
| `await bot.reply(event, message)` | 回复事件（自动 target + 引用）|
| `await bot.recall(message_id)` / `get_message(message_id)` | 撤回（**仅本 bot 已发送记录**）/ 消息详情 |
| `await bot.get_context(group_id, max_messages=10)` | 群近期上下文（复用 ContextManager）|
| `await bot.get_group_member(gid, uid)` / `get_group_members(gid)` | 成员信息 / 成员列表 |
| `await bot.is_group_admin(gid, uid)` / `is_group_owner(gid, uid)` | 群角色判定 |
| `await bot.mute(gid, uid, seconds)` / `kick(gid, uid)` · `bot.log(level, message)` | 群管理（需 `group_manage`）· 插件日志（§6）|

> **`FlowerieBot` 上没有** `is_admin` / `is_owner` / `check_permission`（那是引擎中层 `src/sdk/bot.py` 的内部 API）；
> 插件侧的等价物是 §5 的 `rule(...)` / `@require_permission(...)` 与经典模式的 `api.permission_check(p)`。

### 4.5 多条回复（reply_many / send_many）

一次发多条**独立**消息：条数受配置上限、间隔由 Core 控制、每条走同一条发送与记录路径、失败策略统一。

```python
await event.reply_many(["你好呀", "今天怎么样"])   # 回复并拆多条（首条引用原消息）
await bot.send_many(123456, ["第一句", "第二句"])   # 群号；私聊用 ("private", 10001)
```

| 方法 | 参数 | 返回 |
| :--- | :--- | :--- |
| `bot.send_many(target, messages)` | target 同 `send`（群号 / 元组）| `list[int]`（message_id）|
| `bot.reply_many(event, messages)` / `event.reply_many(messages)` | 传 `BotEvent` 自动推导目标 | `list[int]` |

间隔与上限由 `MULTI_REPLY_*` 决定（[configuration.md](configuration.md#多条回复multi-reply)）；每条都计一次连续回复，`MAX_CONSECUTIVE_REPLIES` 依然生效；单条 `event.reply()` 不受影响。AI 侧 `reply` 工具由模型自主拆分，走同一链路与同一套上限。

## 5. Matcher / Rule

| 装饰器 | 匹配 |
| --- | --- |
| `@command("hello")` | 自动支持 `/` `!` `.` 前缀与空白参数（`event.matcher_args` / `event.args`）|
| `@keyword("花璃")` / `@regex(r"^!天气\s")` / `@prefix("!hi")` / `@exact("ping")` | 包含 / 正则（截断 200 字符，非法正则按不命中）/ 前缀 / 精确 |

- **priority**：数字大者先匹配（50 先于 10）；**`block=True`**：命中后阻断本插件后续 Matcher（`event.stop()` 同义）。
- **Rule（AND）**：`rule(is_group=True, user_id=123)`；内置条件 `is_group` / `is_private` / `is_bot_admin` / `is_bot_owner` /
  `is_group_admin` / `is_group_owner` / `user_id` / `group_id`，自定义谓词 `rule(custom=lambda ev, bot: ...)`（支持 async）；
  组合 `rule_or(...)` / `rule_all(...)` / `rule_not(...)`、`r1 + r2`。
- **权限门**：`@require_permission("group_admin")`（也支持 `group_owner` / `bot_admin` / `bot_owner`），与 `@command` 任意顺序组合；
  不通过的 handler 根本不会触发（主进程按 Rule 过滤，不存在绕过路径）。

```python
@command("禁言", rule=rule(is_group=True, is_group_admin=True), block=True)
async def ban(event):
    await bot.mute(event.group_id, 12345, 600)
    await event.reply("已禁言 10 分钟")
```

## 6. 日志与异常

**规则一**：日志必须走 `bot.log(level, message)`（经典模式 `api.log`）。**绝不 `print()` 到 stdout**——stdout 是插件与主进程的
协议通道，打印会污染协议导致插件异常退出；`print(..., file=sys.stderr)` 仅供调试。级别：`debug`（排查入参）/ `info`（关键动作）/
`warning`（可恢复问题、降级）/ `error`（异常，含类型与摘要）；单行 ≤500 字符，主进程自动加 plugin_id 前缀。

```python
from flowerie_sdk import BotAPIError

@command("天气")
async def weather(event):
    try:
        ...                                   # 查询/网络
    except BotAPIError as e:                  # 引擎侧动作失败（SDK 只导出这一个异常，其余见下）
        bot.log("error", f"weather api failed: {e}")
        await event.reply("服务暂不可用")
```
异常体系：`BotError` ← `BotAPIError` / `BotTimeoutError` / `BotPermissionError` / `MessageNotFoundError` / `UnsupportedOperationError`（经典 `api` 层同名同义）。日志三要素：事件标识（group/user/message_id）+ 结果或异常摘要。

## 7. 多轮交互与等待（Session）

> 轻量实现：插件进程内「未来 + 条件闭包」，事件到达时先喂等待队列。**同一插件若注册了 Matcher 只会收到匹配事件**——
> 等待场景建议拆成独立插件（或该插件不注册 matcher），否则 `wait_for` 可能永远等不到。

```python
@command("打卡")
async def checkin(event):
    await event.reply("请回复群号：")
    answer = await bot.wait_for(lambda e: e.scope == "group" and e.text.isdigit(), timeout=30)
    if answer is None:
        await event.reply("超时了，打卡作废"); return
    await event.reply(f"已登记群 {answer.text}")
```

| API | 说明 |
| --- | --- |
| `await bot.wait_for(cond, timeout=60)` | 等满足 `cond(event)->bool` 的下一条消息；超时返回 None |
| `await bot.ask(event, prompt, timeout=60)` | 发问并等同一用户/会话的下一条消息 |
| `await bot.confirm(event, prompt, timeout=60)` | 是/否解析（是/好/可以/确定=真；否/不要/取消=假）；`select(event, prompt, options, timeout=60)` 编号/文本选择（`options=[{"label","answer"}]`，返回选中项 `answer`）|

## 8. 定时任务（轻量）

```python
@bot.schedule(interval=60)                  # 每 60 秒（1~86400）；event.trigger="interval"、event.schedule_id
async def hourly(event): bot.log("info", "hourly job")

@bot.schedule(daily="09:30")                # 每天 09:30
async def morning(event): await bot.send(("group", 123456), "早安！")

@bot.schedule(delay=10)                     # 一次性延时，触发后自动清理
async def one_shot(event): ...
```
- 主进程轻量调度（asyncio Task，**没有 cron 表达式**：复杂排期就组合多个 `daily` 或插件内自管）；同插件同名注册幂等（覆盖）；`await bot.schedule_list()` / `bot.schedule_cancel(schedule_id)`；权限 `scheduler`。

## 9. 命令参数 / 子命令 / 冷却

```python
@command("add")            # !add 1 "2 3" → event.args == ["1", "2 3"]（shlex 拆分，引号/空白正确处理）
async def add(event): ...

@command("admin.ban")      # 子命令约定：命令名含 "."（!admin.ban 123）
async def sub_command(event): ...

@command("签到")
async def daily(event):
    if not await bot.cool_down("cmd:signin", 3600):   # 冷却检查+标记一体（冷却中 False，否则标记并 True）
        await event.reply("今天已签过啦"); return
```
手动组合：`bot.is_cooled(key, seconds)` / `bot.mark_cooled(key)`（同步）。

## 10. 请求处理（好友/加群）

```python
@bot.listen("request")
async def on_request(event):
    if event.request_kind == "friend":
        bot.log("info", f"好友申请 {event.user_id}")
        bot.handle_friend_request(flag, approve=True, remark="你好")     # 权限 request_handle
    elif event.request_kind == "group":
        bot.handle_group_request(flag, approve=False, reason="暂不加群")
```
> ⚠️ **已知缺口（已核实）**：批准动作需要网关的 `flag`，但引擎投递给插件的事件负载里没有 `flag`/`request_id`
> （`src/core/message_router.py:209-230`；`flag` 在解析期存进了 `event.request_id`）。所以上面两行拿不到 `flag`：
> `request` 事件能正常收到，但批准暂不可用（要批准得等引擎补齐投递或走插件外的人工路径）。

## 11. AI / 记忆 / KV / 网络扩展

```python
reply = await bot.ai_chat("今天花璃怎么样", system="你是花璃的助手")   # 权限 ai_chat；独立于主聊天预算与三层限频，自己加冷却
await bot.mem_update(event.user_id, event.group_id, "nick", "小璃")   # 权限 write_memory
n = await bot.mem_clear(event.user_id, event.group_id)                 # 清记忆（返回条数）

bot.kv_set("count", 1) / bot.kv_get("count") / bot.kv_delete("count") / bot.kv_list()   # 插件私有 KV，权限 storage
bot.http_put("https://api.example.com/x", json={"a": 1}) / bot.http_delete(url) / bot.http_head(url)   # 权限 http_request
bot.http_download("https://example.com/a.png", save_to="assets/a.png")  # 落插件目录，≤10MB
```
- KV 按插件命名空间隔离（别的插件读不到），单值 ≤64KB；`http_download` 有 SSRF 双闸（字面量 + DNS），`save_to` 只允许插件目录内相对路径。

## 12. 工具类（内建，无权限）
```python
bot.random_choice(["a", "b", "c"]) / bot.random_int(1, 100)      # 随机选一个 / 随机整数
bot.now()                                                        # {"timestamp", "iso"}
bot.format_time(1700000000, "%Y-%m-%d %H:%M:%S")
```

## 13. 社交与群管（Flowerie 语义 API）

> 操作对象是一等公民：`bot.group(gid)` / `bot.user(uid)` / `bot.me`；方法名取社交直觉（tap=戳、pin=精华、like=点赞），不暴露网关端点名。

```python
g = bot.group(123456)
await g.members() / await g.member(10001)          # 成员列表 / 成员信息（role/card/nickname）
await g.mute(10001, 600) / await g.set_admin(10001, on=True)   # 禁言 10 分钟 / 设为管理员
await g.whole_ban(on=True) / await g.rename("新群名") / await g.set_card(10001, "新名片") / await g.set_title(10001, "队长")
await g.send_notice("明天升级维护") / notice = await g.get_notice()      # 群公告发 / 读最新
await g.pin(123) / await g.unpin(123)              # 精华消息 / 取消精华
await g.config_set(welcome_text="欢迎") / conf = await g.config()        # 群配置（Lagrange 独有）
files = await g.files() / await g.files_in("folder_id") / await g.file_url("file_id", busid=0)

u = bot.user(10001)
await u.like() / await u.tap(123456) / await u.card(123456, "名片")      # 点赞 / 戳一戳 / 设名片

await bot.me.info() / bot.me.devices() / bot.me.status()                 # 登录信息 / 在线设备 / 网关状态
await bot.me.profile(nickname="花璃")                                    # 改 Bot 资料（权限 bot_profile）

bot.tap(group_id, user_id) / bot.emoji(message_id, emoji_id)             # 顶层语义动作：戳 / 表情回应
bot.pin(message_id) / bot.unpin(message_id) / bot.like(user_id) / bot.friends()
```
> ⚠️ **已知缺口（已核实）**：`g.kick(uid)` 会把 `reject_add` 传给 `bot.kick(gid, uid)`（签名没有该参数）→ TypeError，
> 暂用 `await bot.kick(gid, uid)`；`bot.user(uid).info()` 依赖的 `bot.get_user_info` 在 `FlowerieBot` 上不存在 → AttributeError。

**Milky 协议下的行为**：SDK 与插件 API **完全协议无关**——同一份 `event.reply()` / `bot.send()` / `bot.send_many()` 在 OneBot 与 Milky
下都能跑，差异由 `Sender` 内部处理（动作名映射、Bearer、段数组转换）。Milky 下发送/回复/多条回复、群成员/群信息/群列表、群名片/管理员/
禁言/踢人、表情回应/戳一戳、群公告/精华/群文件均 ✓；撤回 ⚠️（`delete_msg` 仍绕过统一入口）；群荣誉/在线客户端/转发消息发送/批准申请/
群配置写入/改自身资料 ✗（返回 `Milky 协议不支持该能力：xxx`，插件据此降级）。详见 [milky-protocol.md](milky-protocol.md)。

## 14. 权限与安全

**装饰器 / 规则**（SDK 模式，主进程按 Rule 过滤，不存在绕过路径）：`@require_permission("group_admin")`（`group_admin` /
`group_owner` / `bot_admin` / `bot_owner`）或等价条件 `rule(is_group_admin=True)`；经典模式可查询 `api.permission_check("send_message")`
（**只读**，插件无法提权）。**批准机制**：插件在 `manifest.permissions` 声明 → 管理员在 Web UI 按需批准；未批准的动作由引擎在动作层强制拒绝。

| 权限 | 用途 |
| :--- | :--- |
| `read_message` / `send_message` | 收事件 / 回复（**大多数插件的全部所需**）|
| `read_group_info` / `read_user_info` / `read_message_history` | 群 / 成员 / 历史信息 |
| `group_manage` / `delete_message` / `request_handle` | 群管 / 撤回 / 处理申请 |
| `storage` / `scheduler` / `http_request` | KV / 定时 / 出网 |
| `read_memory` / `write_memory` / `ai_chat` / `bot_profile` / `filesystem_read` / `filesystem_write` | 记忆读 / 记忆写 / AI 调用 / 改 Bot 资料 / 插件目录内文件读写 |

只有明确需要才批准 `group_manage` / `storage` / `ai_chat` / `filesystem_write`。

## 15. FAQ 与常见错误

| 症状 | 原因与处理 |
| :--- | :--- |
| 启动后立刻退出 / 引擎报非法行 | 有 `print()` 写到了 stdout；日志一律 `bot.log(...)` 或 `print(..., file=sys.stderr)` |
| 收不到任何事件 | ① `read_message` 未批准；② 该插件注册了 matcher → 只收匹配事件；③ manifest 未声明权限（enable 会被拒）|
| `!hi` 没反应 | matcher 没上报（`on_startup` 里漏了 `bot.attach(api)` / `bot.register()`），或前缀不匹配 |
| `event.flag` 报 AttributeError · `wait_for` 永远超时 | 前者是批准所需的 `flag` 引擎目前不投递（§10 已知缺口）；后者是同一插件注册了 matcher，未匹配的消息不会投递到插件（§7）|
| 只在私聊响应 / 收不到全量通知 | `@command("x", rule=rule(is_private=True))`；全量事件要拆插件 |
| 想用 CQ 码 / 段数组 | `bot.send` 也接受 str（`[CQ:...]` 由平台解析）或段数组 list，但**推荐 BotMessage**（跨后端可移植）|
| 本地怎么测 | 放 `plugins/` → Web UI 启用并批权限 → 群里试；SDK 示例 `tests/plugins/sdk_plugin/`，文档示例 `tests/plugins/doc_example/` |

## 16. 三层架构（改代码时看）

```text
插件（plugin_sdk/flowerie_sdk）→ 中层 src/sdk/（零 OneBot 命名）← 下层 src/adapters/onebot/ → NapCat/OneBot
```
- 新增平台能力 → 只改下层 `onebot/`（dto / transformer / adapter）；新增领域能力（如 Session）→ 加在中层，上层只做 wrapper。
- 依赖倒置验证：`grep -rn "post_type\|sub_type" src/sdk/*.py` 应为空（除注释）；目录与测试约定见 [development.md](development.md)。

## 附录 A：能力与兼容矩阵

> A.1 端点映射与权限、A.2 网关兼容、A.3 v2.1 缺口 SDK 矩阵（历史台账）。端点与权限的**唯一事实来源**是 [api.md](api.md)（自动生成）
> 与 [client-compatibility.md](client-compatibility.md)，本附录只保留速查。

| A.1 SDK 方法 → OneBot 端点（端点只在 Sender/适配层，插件不接触 HTTP）| 权限 | Lagrange |
| --- | --- | --- |
| `user_history` / `bot_user_history` → `/get_friend_msg_history`；`user_forward` → `/send_private_forward_msg`；`user_poke` → `/friend_poke` | read_user_info | ✅ |
| `group_forward` → `/send_group_forward_msg`；`group_notice_delete` → `/_del_group_notice`；`group_portrait` → `/set_group_portrait`；`group_folder_create` / `group_file_delete` / `group_folder_delete` / `group_file_move` / `group_folder_rename` → `/create_group_file_folder` 等 5 个 | group_manage | ✅ |
| `essence_list` → `/get_essence_msg_list`；`group_honor` → `/get_group_honor_info`；`group_info` / `group_list` → `/get_group_info` / `/get_group_list` | read_group_info | ✅ |
| `react`（表情回应）→ `set_react`（NapCat 主）→ `set_group_reaction`（Lagrange 回退，自动激活）| read_message | ✅ |

**网关回退机制**：动作值可为端点方法列表，按 sender 可用方法自动选择（换网关无需改代码）。**A.2 网关兼容矩阵**（OneBot11 标准优先）：

| SDK 能力 | OneBot11 | NapCat / Lagrange | 说明 |
| --- | --- | --- | --- |
| send / reply / recall / get_message · at / 图片 / 语音 / 视频 / 文件 · group_member(s) / mute / kick / admin · login_info / devices / status | ✅ 标准 | ✅/✅ | `send_msg` / `delete_msg` / `get_msg` / `get_group_member_info` / `get_login_info` / `get_online_clients`；段数组 |
| markdown / keyboard / json 富内容 · whole_ban / rename / card / title · 群公告 · 群文件 · pin/unpin · emoji 回应 / tap · like / friends | ⚠️ 扩展 | ✅/✅ | `send_group_notice` / `set_essence_msg` / `set_react` / `send_poke` … |
| profile 修改（`set_self_profile`）| ⚠️ 扩展 | ⚠️/✅ | 自定义协议 |
| group_config 读写 | ❌ 无 | ❌/✅ | **Lagrange 独有** |

**A.3 v2.1 缺口 SDK 矩阵**（历史台账，状态已全部落地）。状态：**可用**（真实现）｜**等价**（转发已有能力）｜**受限**（有明确错误）｜
**NS**（v1 明确不支持，构造即抛 `PluginFeatureError`）。入口：`bot.方法(...)` / `bot.sdk()[分面].方法(...)` / `from flowerie_sdk import 类`。

| 缺口 | 入口 | 状态 |
| --- | --- | --- |
| Message Edit / Search / Segment / Filter | `bot.edit_message`（受限）· `bot.search_message` · `MessageSegment.text/image/at/face/reply` · `MessageFilter(where).apply(list)` | 可用 |
| FriendContext / FriendRequest / GroupRequest / GroupMemberContext / ReactionContext | `FriendContext(bot, user_id=...)`（detail/remark/delete/online）· `FriendRequest(bot, flag=...).approve()/.deny()` · `GroupRequest(...)` · `GroupMemberContext(bot, group_id=...).search()/.title()` · `ReactionContext(bot, message_id=...).react()/.list()`（list 受限）| 可用 |
| SessionContext / Session Manager / Conversation | `SessionContext(bot, group_id=...).remember()/.recall()` · `bot.sdk()["conversation"].session(key)` · `Conversation(bot).add_round/history` | 可用 |
| Matcher OR / NOT / 中间件 / 动态注册 | `rule_or(*rules)` · `rule_not(rule)` · `rule_all(...)` · `bot.matcher_register` | 可用 / 等价 |
| AI / AI Stream / Memory / Memory Context | `bot.sdk()["ai"].chat/vision/embedding/rerank/models/usage/budget` · `bot.ai_stream` · `bot.sdk()["memory"].search/semantic/update/tag`（pin/expire 受限）· `SessionContext.recall/remember` | 可用 |
| MCP / Database / Cache / Task / Runtime | `bot.sdk()["mcp"].servers/tools/call/status`（resource/prompt NS）· `bot.sdk()["db"].query/transaction/migration/index` · `bot.sdk()["cache"].get/set/delete`（KV 域）· `TaskManager` / `bot.sdk()["task"].submit/status/cancel/pause/resume` · `bot.sdk()["runtime"].usage/quota/status` | 可用 / 等价 |
| Metrics / Trace / Health / Debug / Plugin Config / I18n | `bot.sdk()["metrics"]` · `bot.trace` · `bot.health`（debug NS）· `bot.sdk()["config"].get/set` · `I18n` / `bot.sdk()["i18n"].t(key)`（`i18n/<lang>.json`）| 可用 |
| Plugin Service / Discovery / Dependency · FileContext / Media | `bot.sdk()["services"]` / `bot.plugin_*` · `FileContext(bot).upload/download/info/delete`（`web_ui.files` 空间）· `MediaContext(bot).info(name)`（格式识别；时长受限）| 可用 |
| Webhook / WebSocket Server / SSE / Router / Mock | `bot.webhook(url, ...)`（接收注册 NS）· `WebSocketServer` / `SseServer`（**NS**：零 JS + 安全红线，构造即抛）· `bot.router()`（插件 WebUI 路由）· `bot.sdk()["mock"].set/get/clear` | 可用 / **NS** |
