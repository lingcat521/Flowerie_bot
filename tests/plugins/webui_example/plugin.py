# -*- coding: utf-8 -*-
"""Plugin WebUI 测试插件：webui_page hook 返回受控 DSL（含注入负载验证）。"""
TASKS = {"running": True, "count": 3}


def webui_page(page, action, params, values):
    if page == "home":
        return {"type": "container", "kind": "stack", "children": [
            {"type": "heading", "text": "示例插件总览"},
            {"type": "stats", "items": [
                {"label": "任务数", "value": str(TASKS["count"])},
                {"label": "状态", "value": "运行时"}]},
            {"type": "alert", "text": "本页由插件返回的 DSL 渲染（受控）", "variant": "ok"},
            {"type": "button", "text": "开始任务", "action": "start"},
        ]}
    if page == "tasks":
        return {"type": "table", "headers": ["id", "名称"],
                "rows": [[1, "同步歌单"], [2, "清理缓存"]]}
    return {"type": "text", "text": "未知页面"}


def on_startup(context, api=None):
    return None
