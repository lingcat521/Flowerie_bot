# 🚀 花璃插件快速开始（10 分钟写出第一个插件）

> 目标：**10 分钟内**从零写到一个能在群里跑的插件。本文只给最短路径；
> 完整参考（Manifest 全字段 / 事件 / 权限 / 打包 / 超时 / 资源限制 / 13 种语言）见 [plugin-developer-guide.md](plugin-developer-guide.md)，
> 方法 × 权限总表见 [api.md](api.md)，SDK 全量见 [sdk.md](sdk.md)。当前版本 **v2.3.0**。

## 0. 准备（1 分钟）

- 花璃能启动（`python main.py`），Web UI 能打开（默认 `http://127.0.0.1:8080/panel`）。
- 插件目录默认 `./plugins`（配置项 `PLUGIN_DIR`，见 [configuration.md](configuration.md)）。

## 1. 建两个文件（1 分钟）

```text
plugins/my_plugin/
├── manifest.json   # 身份证：id / 入口 / 权限
└── plugin.py       # 大脑：钩子 + 命令
```

## 2. 写 manifest.json（2 分钟）

```json
{
  "id": "my_plugin",
  "name": "我的插件",
  "version": "1.0.0",
  "runtime": "python",
  "entry": "plugin.py",
  "api_version": "1",
  "permissions": ["read_message", "send_message"]
}
```

- `id` 小写字母开头（`[a-z0-9_-]`，≤32 字符）；`version` 必须 `x.y.z`。
- `api_version` 与 `permissions` 都是**必填**；**未知字段会被拒绝**（严格 schema）——安装失败时按报错原文改。
- `permissions` 保守写（见第 6 节）：写少了功能静默不生效，写多了管理员批准时看得见。全字段表见指南 §2。

## 3. 写 plugin.py（3 分钟）

```python
from flowerie_sdk import FlowerieBot, command, require_permission

bot = FlowerieBot()

@command("hi")                                  # 群里发 !hi 触发
async def hello(event):
    await event.reply("你好呀")

@command("add")
async def add(event):
    a, b = event.args[:2]                       # !add 1 2 → args = ["1", "2"]
    await event.reply(str(int(a) + int(b)))

@command("ban")
@require_permission("group_admin")              # 仅群管理员/群主可触发
async def ban(event):
    await event.reply("已执行管理操作")

def on_startup(context, api=None):              # 钩子名固定
    bot.attach(api)                             # 绑定能力通道
    bot.register()                              # 上报匹配器（一次）

def on_message(event, api=None):                # 钩子名固定
    return bot.route(event)                     # 路由到上面的 @command
```

| 钩子 | 何时被调用 | 里面写什么 |
| :--- | :--- | :--- |
| `on_startup(context, api)` | 插件进程握手成功后 | `bot.attach(api)` + `bot.register()` |
| `on_message(event, api)` | 收到消息事件 | `return bot.route(event)` |
| `on_schedule(event, api)` | 定时事件（可选） | `return bot.route_schedule(event)` |

## 4. 触发与发送（1 分钟）

| 装饰器 | 触发条件 |
| :--- | :--- |
| `@command("hi")` | 群里发 `!hi 参数…`（额外参数在 `event.args`，list） |
| `@keyword("词")` / `@regex("模式")` | 文本包含关键词 / 命中正则 |
| `@require_permission("group_admin")` | 叠加在命令上做权限门（另支持 `group_owner` / `bot_admin` / `bot_owner`）；未通过则 handler 不触发 |

```python
await event.reply("回复当前消息")                       # 最常用
await bot.send(("group", 123456), "主动发到群")          # 也可 ("private", QQ号)
await event.reply_many(["第一句", "第二句"])             # 一次多条（见指南 §32）
```

## 5. 装上并测试（2 分钟）

**方式 A（推荐）**：Web UI「插件」页 → 上传 ZIP（把 `my_plugin/` 压成 zip；zip 里直接放 `manifest.json` 或整体套一层目录都行，
多层混装会被拒）→ 在列表里**批准权限** → **启用**。
**方式 B**：整个文件夹放进 `plugins/`，重启花璃。

**测试**：群里发 `!hi` → 收到「你好呀」；发 `!add 1 2` → 收到「3」。

> 安装后插件一律是 **disabled**：不批准权限、不点启用，它不会有任何动作（也不会自动执行）。

## 6. 没反应？按这个顺序排查（1 分钟）

| 现象 | 先查 |
| :--- | :--- |
| 命令完全没触发 | Web UI 插件页是否已**启用**且权限已**批准**；`permissions` 是否含 `read_message` |
| 触发了但发不出消息 | `permissions` 是否含 `send_message`（未批准的动作被拒绝，只写 `plugin_permission_denied` 日志） |
| 钩子没被调用 | 钩子必须叫 `on_startup` / `on_message` 且是模块级函数；`on_message` 要 `return bot.route(event)` |
| 其它 | `logs/bot.log` 搜插件 id；对照表见指南 §24.5 |

## 7. 接下来（按需跳转）

| 想做的事 | 看哪里 |
| :--- | :--- |
| 读写记忆（`api.get_memory` / `api.write_memory`，过记忆安全闸门） | 指南 §8 / §11 |
| 请求网页（`api.http_request`：主进程代理 + SSRF 防护，**不能自己开 socket**） | 指南 §8 / §12 |
| 权限清单与运行时强制点 | 指南 §9 |
| 生命周期 / 多轮对话 / 定时任务 / KV / 错误处理 | 指南 §6 / §13-15 / §17 + [sdk.md](sdk.md) |
| 一次发多条（`reply_many` / `send_many`） | 指南 §32 + [sdk.md §4.5](sdk.md#45-多条回复reply_many--send_many) |
| 不用 Python（13 种语言 exec 最小实现，照抄即可） | 指南 §31 |
| 插件自带管理页面（HTML+CSS，零 JS） | [plugin-webui.md](plugin-webui.md) |
| 两个插件互相调用 | [plugin-communication.md](plugin-communication.md) |
| 打包 / 安装方式 / 超时与资源限制 / 保护级别 | 指南 §19 / §21 / §22-24 |

> 可直接跑的示例：`tests/plugins/doc_example/`（本文示例就是它，有黑盒测试锁住）、`examples/`（Python 与多语言）。
