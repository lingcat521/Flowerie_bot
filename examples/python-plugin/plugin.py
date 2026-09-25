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


def on_command(event, api=None):
    """命令事件：/ping → pong（与其它语言示例同一语义，跨语言契约测试比对）。"""
    if str(event.get("text") or "") == "/ping":
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


# ---------------- Plugin WebUI Protocol（任务书第 3 份 §六） ----------------
# 三个钩子对应三条协议方法：webui.page / webui.action / webui.asset。
# 路由、权限、校验、净化、隔离全部由引擎负责 —— 插件只提供内容。

def _storage_read(key):
    """读本插件自己的 storage（data/storage/<key>.json，与 SDK 的 storage.get 同一份文件）。"""
    try:
        import json
        import os
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "storage",
                            "%s.json" % key)
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return ""


def _settings_form(plugin_id):
    """插件渲染页的 HTML：{{ nickname }} 由引擎 escape 后替换（受控模板变量）。"""
    return ("<h2>插件渲染页</h2>"
            "<p class=\"who\">这份 HTML 来自插件进程（webui.page），不是磁盘文件。</p>"
            "<form class=\"card\" method=\"post\" action=\"/panel/plugins/webui/%s/dynamic\">"
            "<input type=\"hidden\" name=\"plugin_action\" value=\"save\">"
            "<label>昵称 <input name=\"nickname\" value=\"{{ nickname }}\""
            " maxlength=\"64\"></label>"
            "<button type=\"submit\">保存</button></form>"
            "<p class=\"msg\">{{ message }}</p>" % plugin_id)


def webui_page(page_id, action, params, values):
    """HTML 文件页的模板变量（走 web_ui.entry 数据钩子，与其它语言同名同义）。"""
    return {"vars": {"nickname": _storage_read("nickname")}}


def webui_render(page, context):
    """webui.page：插件渲染页（引擎要 HTML，插件返回 HTML + 变量）。"""
    plugin_id = str((context.get("plugin") or {}).get("id") or "")
    return {"html": _settings_form(plugin_id),
            "vars": {"nickname": _storage_read("nickname")}}


def webui_action(page, action, form, context):
    """webui.action：同一个 save settings Action（五种语言语义完全一致）。"""
    if action != "save":
        return {"ok": False, "error": "未知动作: %s" % action}
    plugin_id = str((context.get("plugin") or {}).get("id") or "")
    nickname = str(form.get("nickname") or "")[:64]
    return {"html": _settings_form(plugin_id),
            "vars": {"nickname": nickname},
            "message": "已保存",
            "config_set": {"nickname": nickname},
            "storage_set": {"nickname": nickname}}


def webui_asset(path):
    """webui.asset：插件进程生成的资源（这里是动态 CSS；No-JS，没有 .js）。"""
    if path == "theme.css":
        return {"content_type": "text/css", "body": "body { color: #1f6feb; }"}
    return {"ok": False, "error": "资源不存在: %s" % path}
