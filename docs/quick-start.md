# 🚀 花璃插件快速开始（小白版）

> 目标：**10 分钟写出你的第一个插件并上线**。
> 完整参考（Manifest/事件/权限/打包/限制）→ [plugin-developer-guide.md](plugin-developer-guide.md)；
> API 速查表（全部方法×权限）→ [api.md](api.md)。

---

## 1. 插件是什么

插件是**独立小程序**：它能收到群消息、自己发消息、读写记忆、请求网页，全由主进程
(花璃) 统一管理。你只需要写好**两个文件**：

```
my_plugin/
├── manifest.json   ← 插件的"身份证"（名字/入口/权限）
└── plugin.py       ← 插件的"大脑"（代码）
```

## 2. 怎么创建插件

新建文件夹 `plugins/my_plugin/`（放花璃根目录的 plugins 文件夹里），里面放上面的两个文件。

## 3. manifest.json 怎么写

```json
{
  "id": "my_plugin",
  "name": "我的插件",
  "version": "1.0.0",
  "runtime": "python",
  "entry": "plugin.py",
  "permissions": ["read_message", "send_message", "read_memory"]
}
```

- `id`：唯一标识（字母/下划线）；`permissions`：**能做什么的清单**（见第 9 节）。
- 写少了→功能不生效；写多了→审核会看到（按需最小声明）。

## 4. plugin.py 怎么写

```python
# 固定开头三行（插件模板）：
from flowerie_sdk import FlowerieBot, command, rule

bot = FlowerieBot()

@command("hi")                        # 当群里发 !hi 时触发
async def hello(event):
    await event.reply("你好呀")        # 回复一句

def on_startup(context, api=None):    # 启动钩子（固定）
    bot.attach(api)                   # 绑定能力
    bot.register()                    # 上报命令（一次）

def on_message(event, api=None):      # 消息钩子（固定）
    return bot.route(event)           # 路由到上面的 @command
```

## 5. 怎么收消息

`@command("名字")` 收命令（用户发 `!名字 参数` 触发）；`@keyword("词")` 收关键词；
`@regex("模式")` 收正则。命令的附加参数在 `event.args`：

```python
@command("add")
async def add(event):
    a, b = event.args[:2]
    await event.reply(str(int(a) + int(b)))   # !add 1 2 → 3
```

## 6. 怎么发消息

- **回复当前消息**：`await event.reply("内容")`（最常用）
- **主动发到群**：`await bot.send(("group", 群号), "内容")`
- **私聊**：`await bot.send(("private", QQ号), "内容")`

## 7. 怎么读写记忆

```python
# 读：查这位用户的记忆（在主进程给过 user_id 的上下文里）
notes = await bot.get_memory(("get", user_id, group_id))   # 或查某个 key
# 写：
await bot.write_memory(("set", user_id, group_id, "key", "值"))
```

> 完整记忆 API（mem_update / mem_clear / 语义版"花语记忆"）见完整参考 §11 与 sdk.md。

## 8. 怎么请求网页

```python
resp = await bot.http_request({
    "method": "GET",
    "url": "https://api.github.com/zen",
    "timeout": 10,
})
text = resp.get("text", "")
```

> 只能走后门（主进程统一代理）——**不能自己开 socket**：这层已带 SSRF 防护。

## 9. 权限是什么

每个动作都要在 `permissions` 里声明过才会执行：`send_message`（发消息）、
`read_message`（收消息）、`read_memory`（读记忆）、`http_request`（请求网页）……
**漏声明 = 功能毫无反应（只写日志）**。排查口诀：没反应先查权限→再查钩子名→再看日志。

## 10. 一个完整例子（抄这个就行）

`plugins/my_plugin/manifest.json` 见第 3 节；`plugin.py`：

```python
from flowerie_sdk import FlowerieBot, command, require_permission

bot = FlowerieBot()

@command("hello")
async def hello(event):
    await event.reply("你好呀")

@command("add")
async def add(event):
    a, b = event.args[:2]
    await event.reply(str(int(a) + int(b)))

@command("ban")
@require_permission("group_admin")          # 只有群管理员能用
async def ban(event):
    await event.reply("已执行管理操作")

def on_startup(context, api=None):
    bot.attach(api)
    bot.register()

def on_message(event, api=None):
    return bot.route(event)
```

## 11. 怎么安装测试

**第 1 种（推荐）：Web UI 上传**
1. 把 `my_plugin/` 压成 `my_plugin.zip`（**zip 里直接是 manifest.json 和 plugin.py**，别再套一层目录也行，会自动剥离）
2. 打开花璃的 Web UI → 「插件」页 → 上传 ZIP
3. 在插件列表里**批准权限** → **启用**

**第 2 种：手动放入**：整个文件夹放进花璃根目录 `plugins/`，重启。

**测试**：群里发 `!hello` → 收到"你好呀"；发 `!add 1 2` → 收到"3"。

---

> 做得不错？下一步：到 [quick 完整参考](plugin-developer-guide.md) 看生命周期 / 多轮对话 / 定时任务 / 打包发布。
