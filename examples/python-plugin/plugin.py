"""Python 示例插件：与 TypeScript/Go/Rust/Java 示例**语义完全一致**（跨语言契约测试对照）。

协议与钩子说明见 docs/plugin-protocol.md；本文件只用到最朴素的钩子（无第三方依赖）。
"""


def on_startup(context, api=None):
    """握手后调用；异常会阻止插件启动（runner 会把异常回报引擎）。"""
    return None


def on_message(event, api=None):
    """收到消息 → 回 pong（与其它语言示例同一语义）。"""
    if str(event.get("text") or "") == "ping":
        return {"type": "send_group_msg",
                "params": {"group_id": event.get("group_id"), "message": "pong"}}
    return None


def status(*_args):
    """控制面 hook（插件 WebUI 的数据钩子走同一条通道）：返回 storage 里的计数器。"""
    try:
        import json
        import os
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "storage", "counter.json")
        with open(path, encoding="utf-8") as fh:
            value = json.load(fh)
        return {"counter": value.get("n") if isinstance(value, dict) else None}
    except (OSError, ValueError):
        return {"counter": None}


def on_shutdown(context, api=None):
    return None
