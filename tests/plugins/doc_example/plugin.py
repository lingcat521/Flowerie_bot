# -*- coding: utf-8 -*-
"""docs/plugin-developer-guide.md §0「60 秒上手」示例——文档黑盒验证：文档代码可直接运行。"""
from flowerie_sdk import FlowerieBot, command, require_permission

bot = FlowerieBot()


@command("hi")
async def hello(event):
    await event.reply("你好呀")


@command("add")
async def add(event):
    a, b = event.args[:2]
    await event.reply(str(int(a) + int(b)))


@command("ban")
@require_permission("group_admin")
async def ban(event):
    await event.reply("已执行管理操作")


def on_startup(context, api=None):
    bot.attach(api)
    bot.register()


def on_message(event, api=None):
    return bot.route(event)
