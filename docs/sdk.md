# Flowerie Bot SDK 开发手册（v1.3.0）

> 插件面向的统一开发接口。三层架构：插件（上层）→ 领域层（中层，零 OneBot 命名）→
> OneBot 适配层（下层）。本手册为**详细版**：API 参考 + 多媒体/按钮示例 + 日志规范。

## 1. 最小示例

```python
# plugins/myplugin/plugin.py（插件目录需自带 flowerie_sdk/ 副本）
from flowerie_sdk import FlowerieBot, command, keyword, regex, prefix, exact, rule

bot = FlowerieBot()

@command("hello")
async def hello(event):
    await event.reply("你好")            # 自动引用原消息

@keyword("花璃")
async def flowerie(event):
    await event.reply(BotMessage().add_text("怎么啦？").at(event.user_id))

def on_startup(context, api=None):
    bot.attach(api)      # 绑定协议 api
    bot.register()       # 上报 matchers（幂等，一次性）

def on_message(event, api=None):
    return bot.route(event)              # SDK 路由；未匹配自动忽略
```

`manifest.json` 至少声明：`runtime=python` + 权限 `read_message`（接收事件）、
`send_message`（回复）。本地目录 `plugins/myplugin/` 自动发现，Web UI「插件」页启用。

---

## 1.5 30 秒速查（常用 API 一行例）

```python
bot = FlowerieBot()

@command("hi", rule=rule(is_group=True))   # !hi 且仅群聊
async def h(event):
    await event.reply("你好")                # 回复当前消息上下文

# 更多能力（详见对应章节；全部 await、权限自动检查）
await event.reply("hi")                     # §3 消息
await bot.send(("group", 777), "hi")        # 直发群
await bot.send(("private", 1001), "hi")     # 直发私聊
await bot.recall(message_id)                # 撤回
await bot.mute(777, 123, 600)               # 禁言 10 分钟
await bot.kick(777, 123)                    # 踢
await bot.get_context(777, 20)              # 群最近历史
await bot.wait_for(...)                     # 等待下一条（§7 多轮）
await bot.cool_down("k", 60)                # 冷却（§9）
await event.mention_bot()                   # @ 机器人
bot.log("info", "hello")                    # 日志（§6）
```

## 2. Event 完整参考

### 2.1 属性（事件接收时全部可用）

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `kind` | str | 领域事件分类：`message` / `notice` / `request` / `lifecycle` |
| `scope` | str | `group`（群）/ `private`（私聊）/ `""`（无会话） |
| `notice_kind` | str | notice 子类型：`group_increase` / `group_decrease` / `group_upload` / `friend_increase` / `notify`（戳一戳等）等 |
| `request_kind` | str | request 子类型：`friend` / `group` |
| `lifecycle_kind` | str | `enable` / `disable` / `connect` / `heartbeat` 等 |
| `user_id` | int/None | 触发者 QQ |
| `group_id` | int/None | 群号（群消息/群相关事件） |
| `operator_id` | int/None | 操作者（群管变动等）；缺省=user_id |
| `message_id` | int/None | 消息 id（`recall` 需要） |
| `time` | int/None | 事件时间戳 |
| `text` | str | **纯文本**（CQ 码已在下层阉割；上限 4000 字符） |
| `at_list` | list[str] | 被 @ 的 QQ 列表（≤20；`"all"` 表示全体） |
| `images` | list[str] | 图片 URL/路径列表（≤10） |
| `reply_id` | int/None | 若消息是引用回复 → 被引用的 message_id |
| `message` | BotMessage | 结构化消息对象（text/at_list/images 等派生） |
| `matcher_name` | str | 命中的 Matcher 名（SDK 路由后） |
| `matcher_args` | str | 命令参数（`@command` 命中时；如 `!hi 世界` → `"世界"`） |
| `stopped` | bool | 是否已被 `stop()` 标记 |

### 2.2 判定属性（bool）

`is_group` · `is_private` · `is_message` · `is_notice` · `is_request` · `is_lifecycle`

### 2.3 方法

| 方法 | 说明 |
| --- | --- |
| `await event.reply("hi")` | 回复当前事件：群→群（自动引用原消息），私聊→私聊；返回 message_id |
| `await event.recall()` | 撤回本事件消息（需 `message_id`；仅限本 bot 已发送记录） |
| `event.stop()` | 阻断本插件后续 Matcher / Listener |

### 2.4 收到通知/请求事件示例（Listener）

```python
# 消息事件之外，用监听器接收 notice/request/lifecycle
@bot.listen("notice", priority=10)
async def on_increase(event):
    if event.notice_kind == "group_increase":
        await event.reply(BotMessage().add_text("欢迎新成员！").at(event.user_id))
```
> 注意：`bot.listen` 的 handler 只接收**被主进程投递**的事件——注册了 matcher 的插件
> 只会收到匹配事件；如需全量 notice，请**不要在该插件注册 matcher**（或拆分插件）。

---

## 3. BotMessage 完整参考（消息构造）

### 3.1 属性

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `text` | str | 纯文本 |
| `at_list` | list[str] | @ 的 QQ（`"all"`=全体） |
| `images` | list[str] | 图片：http(s) URL / 本地路径 |
| `videos` | list[str] | 视频 |
| `voices` | list[str] | 语音（OneBot record 段） |
| `files` | list[str] | 文件（可带显示名） |
| `reply_id` | int/None | 引用回复的 message_id |
| `segments` | list | 通用段（高级/平台相关，如键盘） |

### 3.2 Builder（链式，方法返回自身）

| 方法 | 说明 |
| --- | --- |
| `BotMessage()` / `BotMessage("初始文本")` | 构造 |
| `.add_text("x")` | 追加文本（**注意**：读取用 `.text` 属性） |
| `.at(qq)` | @ 某人（可多次）；`.at("all")` 全体 |
| `.image(url)` | 图片 |
| `.video(url)` | 视频 |
| `.voice(url)` | 语音 |
| `.file(url, name="x.pdf")` | 文件（附显示名，平台支持时生效） |
| `.reply(message_id)` | 引用回复 |
| `.add_segment("keyboard", {...})` | 通用段（高级） |
| `.merge(other)` | 合并另一消息（链式组合） |
| `.has(kind)` | 判断：`"text"`/`"at"`/`"image"`/`"video"`/`"voice"`/`"file"`/`"reply"` |
| `iter(msg)` | 产出 `("text", ...)` / `("at", ...)` / `("image", ...)` … 有序元组 |

### 3.3 发送示例

```python
from flowerie_sdk import BotMessage, FlowerieBot, command, BotAPIError

@command("看图")
async def show_image(event):
    msg = (BotMessage("今天的美图：")
           .image("https://example.com/a.png"))          # 远程 URL
    await event.reply(msg)                                # 引用回复（图片+文字）

@command("领文件")
async def send_file(event):
    msg = (BotMessage("文档请查收：")
           .file("https://example.com/report.pdf", name="报告.pdf"))
    await bot.send(("group", event.group_id), msg)

@command("上课打卡")
async def checkin(event):
    await event.reply(BotMessage().add_text("今日任务清单：\n").at("all"))
```

**本地文件**：插件目录内文件用 `file_read` 拿内容、`file_write` 写文件；
图片/语音路径可用绝对路径（`/data/...`/`file:///data/...`，由 NapCat 读取，需平台可访问）。

### 3.4 按钮 / 键盘（平台相关，谨慎使用）

QQ 官方「键盘（Keyboard）/ Markdown」**不在 OneBot11 标准段内**——能力取决于你的
NapCat 版本与后端实现，Flowerie 只做**通用段透传**（兼容性自担兼容性）：

```python
@command("菜单")
async def menu(event):
    msg = (BotMessage("请选择：")
           .add_segment("keyboard", {
               "buttons": [
                   [{"text": "开始", "k": "/start"}],
                   [{"text": "帮助", "k": "/help"}]
               ]
           }))
    await event.reply(msg)
```
> 若平台不支持，该段会被丢弃或整条失败（返回 BotAPIError），建议先小范围验证。

---

## 4. 完整 Bot API

| API | 说明 |
| --- | --- |
| `await bot.send(target, message, reply_id=None)` | target：`("group", 123)` / `("private", 456)` / 群号 int；message：str/BotMessage；返回 message_id |
| `await bot.reply(event, message, reply_id=None)` | 回复事件（自动 target + 引用） |
| `await bot.recall(message_id)` | 撤回（**仅本 bot 已发送记录**） |
| `await bot.get_message(message_id)` | 消息详情 → BotMessage |
| `await bot.get_context(group_id, max_messages=10)` | 近期上下文（复用 ContextManager） |
| `await bot.get_group_member(group_id, user_id)` | 成员信息（role/nickname/card/title） |
| `await bot.get_group_members(group_id)` | 成员列表 |
| `await bot.is_admin(event)` / `is_owner(event)` | bot 管理员（ADMIN_QQ_IDS） |
| `await bot.is_group_admin(gid, uid)` / `is_group_owner(gid, uid)` | 群角色 |
| `await bot.mute(gid, uid, seconds)` / `bot.kick(gid, uid)` | 群管理（需 group_manage 权限） |
| `await bot.check_permission(event, kind)` | 权限检查（见 §7） |
| `bot.log(level, message)` | 插件日志（见 §6） |

---

## 5. Matcher / Rule

| 装饰器 | 匹配 |
| --- | --- |
| `@command("hello")` | 自动支持 `/` `!` `.` 前缀与空白参数（`event.matcher_args`） |
| `@keyword("花璃")` | 包含 |
| `@regex(r"^!天气\\s")` | 正则（截断 200 字符；非法正则按不命中） |
| `@prefix("!hi")` | 前缀 |
| `@exact("ping")` | 精确 |

- **priority**：数字大者先匹配（全项目统一，文档固定：50 先于 10）。
- **block=True**：命中后阻断本插件后续 Matcher；`event.stop()` 同义。
- **Rule**（AND 组合）：`rule(is_group=True, user_id=123)`；内置条件
  `is_group` / `is_private` / `is_bot_admin` / `is_bot_owner` / `is_group_admin` /
  `is_group_owner` / `user_id` / `group_id`；自定义谓词
  `rule(custom=lambda ev, bot: ev.text.startswith("x"))`（支持 async）；组合 `r1 + r2`。

```python
@command("禁言", rule=rule(is_group=True, is_group_admin=True), block=True)
async def ban(event):
    await bot.mute(event.group_id, 12345, 600)
    await event.reply("已禁言 10 分钟")
```

---

## 6. 插件日志规范（重要）

**规则一：日志必须走 `bot.log(level, message)`（或经典模式 `api.log`）。**
绝不 `print()` 到 stdout——stdout 是插件与主进程的协议通道，任何打印都会破坏协议
导致插件异常退出。`print(..., file=sys.stderr)` 仅供调试（stderr 由主进程采集尾 4KB，
不落盘、不审计）。

**级别与用法**：

| 级别 | 何时用 | 示例 |
| --- | --- | --- |
| `debug` | 细节排查、入参 | `bot.log("debug", f"收到命令 args={event.matcher_args!r}")` |
| `info` | 关键动作（处理/发送/结果） | `bot.log("info", f"打卡成功 uid={event.user_id}")` |
| `warning` | 可恢复问题（重试/降级/权限不足） | `bot.log("warning", "API 未就绪，跳过")` |
| `error` | 异常/失败（含类型与摘要） | `bot.log("error", f"{type(e).__name__}: {e}")` |

**错误处理模板**：

```python
from flowerie_sdk import BotError, BotAPIError, BotTimeoutError

@command("天气")
async def weather(event):
    try:
        msg = BotMessage("正在查询…")
        # ...网络/查询失败场景
    except BotTimeoutError:
        bot.log("error", "weather timeout")
        await event.reply("查询超时了，稍后再试")
    except BotAPIError as e:
        bot.log("error", f"weather api failed: {e}")
        await event.reply("服务暂不可用")
    except BotError as e:      # 所有 Bot 异常基类
        bot.log("error", f"weather unexpected: {e}")
```

异常体系：`BotError` ← `BotAPIError` / `BotTimeoutError` / `BotPermissionError` /
`MessageNotFoundError` / `UnsupportedOperationError`（详见 §8）。

**日志三要素**（每条日志建议包含）：① 插件前缀（主进程自动加 plugin_id）② 事件标识
（group/user/message_id）③ 结果或异常摘要。长度 ≤500 字符，单行。

---

## 7. 多轮交互与等待（Session）

> 轻量实现：插件进程内「未来 + 条件闭包」——事件到达时先喂等待队列。
> **注意**：同一插件若注册了 Matcher，只会收到匹配事件——等待场景建议拆成
> 独立插件（或该插件不注册 matcher），否则 wait_for 可能永远等不到。

```python
@command("打卡")
async def checkin(event):
    await event.reply("请回复群号：")
    answer = await bot.wait_for(lambda e: e.scope == "group" and e.text.isdigit(), timeout=30)
    if answer is None:
        await event.reply("超时了，打卡作废")
        return
    await event.reply(f"已登记群 {answer.text}")

@command("问卷")
async def survey(event):
    ok = await bot.confirm(event, "确认要执行吗？", timeout=20)
    if ok:
        choice = await bot.select(event, "选择方案：", [
            {"label": "方案A", "answer": "a"}, {"label": "方案B", "answer": "b"}])
        await event.reply(f"你选择了 {choice}" if choice else "未选择")
```

| API | 说明 |
| --- | --- |
| `await bot.wait_for(cond, timeout=60)` | 等待满足 `cond(event)->bool` 的下一条消息；超时/超时返回 None |
| `await bot.ask(event, prompt, timeout=60)` | 发送提问并等待回答（同一会话用户下一条消息） |
| `await bot.confirm(event, prompt, timeout=60)` | 是/否解析（是/好/可以/确定=真；否/不要/取消=假） |
| `await bot.select(event, prompt, options, timeout=60)` | 编号/文本选择；返回选中项 `answer` |

await 语义：handler 为 `async def` 时直接 await；插件运行时内同一次事件处理中
读等待队列仅对**事件消息**生效（notice 不满足消息条件即可忽略）。

## 8. 定时任务（轻量）

```python
@bot.schedule(interval=60)
async def hourly(event):            # event.trigger="interval"；event.name/schedule_id
    bot.log("info", "hourly job")

@bot.schedule(daily="09:30")
async def morning(event):
    await bot.send(("group", 123456), "早安！")

@bot.schedule(delay=10)
async def one_shot(event):          # 一次性延时任务，触发后自动清理
    ...
```

- 三种模式：`interval`（秒，1~86400）/ `delay`（秒，一次性）/ `daily`（"HH:MM"）
- 由主进程轻量调度（asyncio Task；**无完整 cron**——需要 cron 请用多个 daily 或插件内自行组合）
- `await bot.schedule_list()` / `bot.schedule_cancel(schedule_id)`（通过 action 返回的
  schedule_id）；同插件同名注册幂等（覆盖）
- 权限：`scheduler`；handler 建议 `async def job(event)`（event.trigger/name/schedule_id）

## 9. 命令参数 / 子命令 / 冷却

```python
@command("add")          # !add 1 "2 3"
async def add(event):
    print(event.args)    # ['1', '2 3'] —— shlex 拆分（引号/空白处理）

@command("admin.ban")    # 子命令约定：命令名含 "." 即子命令（!admin.ban 123）
async def sub_command(event):
    ...

@command("签到")
async def daily(event):
    if not await bot.cool_down("cmd:signin", 3600):   # 一小时冷却
        await event.reply("今天已签过啦")
        return
    bot.mark_cooled("cmd:signin")
    ...
```

| API | 说明 |
| --- | --- |
| `event.args` | shlex 拆分后的参数列表（`@command` 命中后） |
| `await bot.cool_down(key, seconds)` | 冷却检查+标记一体：冷却中 False；否则标记并 True |
| `bot.is_cooled(key, seconds)` / `bot.mark_cooled(key)` | 手动组合 |

## 10. 请求处理（好友/加群）

```python
@bot.listen("request")
async def on_request(event):
    if event.request_kind == "friend":
        bot.log("info", f"好友申请 {event.user_id}")
        bot.handle_friend_request(event.flag, approve=True, remark="你好")
    elif event.request_kind == "group":
        bot.handle_group_request(event.flag, approve=False, reason="暂不加群")
```

> event.flag：请求唯一标识（approve 必须携带）；权限 `request_handle`。

## 11. AI（受限）/ 记忆 / KV / 网络扩展

```python
reply = await bot.ai_chat("今天花璃怎么样", system="你是花璃的助手")   # 权限 ai_chat

await bot.mem_update(event.user_id, event.group_id, "nick", "小璃")   # 更新记忆
n = await bot.mem_clear(event.user_id, event.group_id)                 # 清除记忆（返回条数）

bot.kv_set("count", 1)                    # 插件私有 KV（跨重启持久）
bot.kv_get("count") / bot.kv_delete("count") / bot.kv_list()

r = bot.http_put("https://api.example.com/x", json={"a": 1})           # 权限 http_request
r = bot.http_delete("https://api.example.com/x/1")
r = bot.http_head("https://api.example.com")
bytes_ = bot.http_download("https://example.com/a.png", save_to="assets/a.png")  # 落插件目录
```

- KV：按插件命名空间隔离（其他插件读不到）；单值 ≤64KB；权限 `storage`
- http_download：SSRF 双闸校验（字面量+DNS）+ ≤10MB + `save_to` 仅限插件目录内相对路径
- AI：**独立于主聊天预算/三层限频**——请务必用命令冷却或自己的频控；权限 `ai_chat`

## 12. 工具类（内建，无权限）

```python
bot.random_choice(["a", "b", "c"])      # 随机选一个
bot.random_int(1, 100)                  # 随机整数
bot.now()                               # {timestamp, iso}
bot.format_time(1700000000, "%Y-%m-%d %H:%M:%S")
```

## 13. 社交与群管（Flowerie 语义 API）

> 特色：操作对象是一等公民——`bot.group(gid)` / `bot.user(uid)` / `bot.me`；
> 方法名取社交直觉（tap=戳、pin=精华、like=点赞），**不暴露任何网关端点名**；
> 底层端点只存在于适配层，网关支持度见 §14 兼容矩阵。

### 13.1 群操作（GroupContext）

```python
g = bot.group(123456)

await g.members()                    # 成员列表
await g.member(10001)                # 成员信息（role/card/nickname）
await g.mute(10001, 600)             # 禁言 10 分钟
await g.kick(10002)                  # 踢人
await g.set_admin(10001, on=True)    # 设为管理员
await g.whole_ban(on=True)           # 全体禁言
await g.rename("新群名")              # 改群名
await g.set_card(10001, "新名片")     # 成员名片
await g.set_title(10001, "队长")      # 成员头衔
await g.send_notice("明天升级维护")    # 发群公告（QQ 官方公告）
notice = await g.get_notice()        # 读最新公告
await g.pin(123) / g.unpin(123)      # 精华消息 / 取消精华
await g.config_set(welcome_text="欢迎")   # 群配置（部分网关支持）
conf = await g.config()              # 读群配置
files = await g.files()              # 群文件（根目录）
files = await g.files_in("folder_id")
url = await g.file_url("file_id", busid=0)
```

### 13.2 用户与自我（UserContext / MeContext）

```python
u = bot.user(10001)
await u.like()                       # 点赞
await u.tap(123456)                  # 戳一戳（群内）
await u.card(123456, "名片")          # 设名片

await bot.me.info()                  # 登录信息（昵称/QQ）
await bot.me.devices()               # 在线设备
await bot.me.status()                # 网关状态
await bot.me.profile(nickname="花璃") # 改 Bot 资料（权限 bot_profile）
```

### 13.3 顶层语义动作

```python
bot.tap(group_id, user_id)       # 戳
bot.emoji(message_id, emoji_id)  # 消息表情回应
bot.pin(message_id) / bot.unpin(message_id)
bot.like(user_id)
bot.friends()                    # 好友列表（list[dict]）
```

## 14. v2.0.1 拉格朗日补齐（并入上方语义表；端点仅 Sender/适配层）

| SDK 方法 | OneBot 端点（仅 Sender，开发者不接触） | 权限 | Lagrange |
| --- | --- | --- | --- |
| `bot_user_history` / `user_history` | `/get_friend_msg_history` | read_user_info | ✅ |
| `user_forward` | `/send_private_forward_msg` | read_user_info | ✅ |
| `user_poke` | `/friend_poke` | read_user_info | ✅ |
| `group_forward` | `/send_group_forward_msg` | group_manage | ✅ |
| `essence_list` | `/get_essence_msg_list` | read_group_info | ✅ |
| `group_honor` | `/get_group_honor_info` | read_group_info | ✅ |
| `group_notice_delete` | `/_del_group_notice` | group_manage | ✅ |
| `group_portrait` | `/set_group_portrait` | group_manage | ✅ |
| `group_folder_create` | `/create_group_file_folder` | group_manage | ✅ |
| `group_file_delete` | `/delete_group_file` | group_manage | ✅ |
| `group_folder_delete` | `/delete_group_folder` | group_manage | ✅ |
| `group_file_move` | `/move_group_file` | group_manage | ✅ |
| `group_folder_rename` | `/rename_group_file_folder` | group_manage | ✅ |
| `group_info` / `group_list` | `/get_group_info` / `/get_group_list` | read_group_info | ✅ |
| `react`（表情回应） | `set_react`（NapCat 主）→ `set_group_reaction`（Lagrange 回退，自动激活） | read_message | ✅ |

**网关回退机制**：动作值可为端点方法列表，按 sender 可用方法自动选择（换网关无需改代码）。

## 14. 底层兼容矩阵（内部文档）

> 能力清单对齐主流网关（OneBot11 标准 + 社区通用 + 扩展）；**OneBot11 标准优先**。
> 在当前网关（NapCat）与 Lagrange 均支持的项目打 ✅；仅特定网关支持的打 ⚠️
> （调用返回明确错误），换网关即激活。

| SDK 能力 | OneBot11 | 社区通用（NapCat/Lagrange） | 说明 |
| --- | --- | --- | --- |
| send/reply/recall/get_message | ✅ 标准 | ✅/✅ | send_msg/delete_msg/get_msg |
| at/图片/语音/视频/文件 | ✅ 标准 | ✅/✅ | 段数组 |
| markdown/keyboard/json 富内容 | ⚠️ 扩展 | ✅/✅ | QQ 官方 Bot 能力 |
| group_member(s)/mute/kick/admin | ✅ 标准 | ✅/✅ | get_group_member_info 等 |
| whole_ban/rename/card/title | ⚠️ 扩展 | ✅/✅ | set_group_* 系列 |
| 群公告 send/get | ⚠️ 扩展 | ✅/✅ | send_group_notice |
| 群文件 list/url | ⚠️ 扩展 | ✅/✅ | get_group_root_files 等 |
| pin/unpin（精华） | ⚠️ 扩展 | ✅/✅ | set_essence_msg |
| emoji 回应 / tap（戳） | ⚠️ 扩展 | ✅/✅ | set_react / send_poke |
| like / friends | ⚠️ 扩展 | ✅/✅ | set_friend_profile_like / get_friend_list |
| login_info/devices/status | ✅ 标准 | ✅/✅ | get_login_info / get_online_clients |
| profile 修改 | ⚠️ 扩展 | ⚠️/✅ | set_self_profile（自定义协议） |
| group_config 读写 | ❌ 无 | ❌/✅ | **Lagrange 独有** |

## 15. 权限与安全





**角色判定**（`await bot.check_permission(event, kind)`）：

| kind | 语义 |
| --- | --- |
| `user` | 任意 QQ 用户 |
| `group_member` | 任意群成员（事件上下文保证） |
| `group_admin` | 群管理/群主（经成员角色查询） |
| `group_owner` | 群主 |
| `bot_admin` / `bot_owner` | 管理员（**ADMIN_QQ_IDS** 配置；owner 与 admin 同源） |

**装饰器**：`@require_permission("group_admin")`（未通过抛 BotPermissionError）。

**管理员批准机制**：插件声明 `manifest.permissions` → 管理员在 Web UI 按需批准；
未批准的动作在协议层强制拒绝（不是提示文字）。权限清单：
`send_message` / `read_message` / `read_group_info` / `read_user_info` /
`read_memory` / `write_memory` / `http_request` / `filesystem_read` /
`filesystem_write` / `delete_message` / `read_message_history` / `group_manage` /
`request_handle` / `scheduler` / `storage` / `ai_chat` / `bot_profile`（v1.5 新增）。
建议最小授权：只有明确需要才批准 `group_manage` / `storage` / `ai_chat` /
`filesystem_write`。

---

## 16. 常见问题（FAQ）

**Q: 如何只在私聊响应？**
`@command("x", rule=rule(is_private=True))`

**Q: 如何给某个命令加冷却？**
当前版本命令冷却由主进程策略层统一管理；插件侧可自行缓存最近调用时间（插件目录
文件用 `file_read/file_write` 或内存 dict）。

**Q: 为什么收不到事件？**
① 权限未批准 `read_message`（Web UI 检查）② 插件注册了 matcher → 只收匹配事件
③ manifest 声明权限未包含批准项（enable 会拒绝）。

**Q: 如何本地测试？**
把插件放入 `plugins/` 目录（或 Web UI 上传），`read_message`+`send_message` 批准后
启用；用最小示例骨架逐步加功能；测试插件见 `tests/plugins/sdk_plugin/`。

**Q: 想直接用 OneBot 段数组/CQ 码？**
`bot.send` 的 message 也接受 str（含 `[CQ:...]` 由平台解析）或段数组 list——
但**推荐 BotMessage**（平台无关、跨后端可移植）。

---

## 17. 三层架构与扩展

```text
插件（plugin_sdk/） → 中层 src/sdk/（零 OneBot） ← 下层 src/sdk/onebot/ → NapCat/OneBot
```

- 新增平台能力 → 只改下层 `onebot/`（dto / transformer / adapter）
- 新增领域能力（如 Session）→ 加在中层，上层只做 wrapper
- 依赖倒置验证：`grep -rn "post_type\|sub_type" src/sdk/*.py`（除 onebot/ 与注释）应为空

