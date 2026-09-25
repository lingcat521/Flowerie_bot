"""minimal Python 插件（任务书《插件测试》§二/§三/§四）：与 TS/Go/Rust/Java 最小插件语义完全一致。

只用仓库自带 runner（runtime=python）暴露的 SDK API：plugin.expose / plugin.call / plugin.on，
不 import 任何 Flowerie 内部模块（插件进程是隔离的）。
"""
import json
import time

SDK_VERSION = "1.0.0"
RUNTIME = "python"          # ping / get_info / WebUI 页面上的 runtime
API = {"api": None}
STATE = {"events": [], "logs": []}


def _api():
    return API["api"]


def _plugin_id():
    try:
        raw = _api().context_info() or {}
    except Exception:  # noqa: BLE001 - 引擎不可用时退化为默认 id
        raw = {}
    payload = raw.get("result") if isinstance(raw.get("result"), dict) else raw
    return str((payload or {}).get("plugin_id") or "minimal_py")


def _label():
    return _plugin_id().replace("_", "-")


def on_startup(context, api=None):
    """注册暴露方法（§二：ping / get_info / echo；另有探针方法 slow / boom / seen）。"""
    API["api"] = api
    if api is None:
        return None
    for name, handler in (("ping", _ping), ("get_info", _get_info), ("echo", _echo),
                          ("slow", _slow), ("boom", _boom), ("seen", _seen)):
        api.plugin.expose(name, handler)
    return None


# ---------------- §三 Plugin API ----------------

def _ping(request):
    return {"ok": True, "plugin": _label(), "runtime": RUNTIME}


def _get_info(request):
    return {"plugin_id": _plugin_id(), "runtime": RUNTIME, "sdk_version": SDK_VERSION,
            "protocol_version": "1"}


def _echo(request):
    """原样返回输入数据（§三）：params 是什么就回什么。"""
    return request.get("params") or {}


def _slow(request):
    time.sleep(1.5)
    return {"slept": True}


def _boom(request):
    raise RuntimeError("minimal python plugin boom")


def _seen(request):
    return {"events": list(STATE["events"]), "logs": list(STATE["logs"])}


# ---------------- §四 Event ----------------

def on_test_event(event, api=None):
    """test.event：记录 payload 并打一行 [test.event] <message>（用 SDK 日志，引擎侧可见）。"""
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else None
    if payload is None:                      # 引擎把 payload 平铺进事件对象
        payload = {k: v for k, v in event.items() if k not in ("event", "plugin_id")}
    STATE["events"].append(payload)
    message = str(payload.get("message") or "")
    STATE["logs"].append("[test.event] %s" % message)
    if api is not None:
        try:
            api.log("info", "[test.event] %s" % message)
        except Exception:  # noqa: BLE001 - 日志失败不影响事件处理
            pass
    return None


# ---------------- WebUI 最小页面（任务书《plugin_to_webui》§23） ----------------
# 五种语言共用**同一套** WebUI API：页面由插件经 webui.page 返回 HTML（No-JS：只有 HTML + CSS）。
# 路由 / 权限 / 校验 / 净化 / 隔离全部由引擎负责，插件只负责内容。
# Plugin 与 Runtime 取自受控 context 与 SDK 值，不写死在 HTML 里（部署方改名后页面自动跟随）。

LANGUAGE = "Python"          # 页面上的 Language
SDK_NAME = "python_runner"   # 页面上的 SDK（python 插件的 API 由仓库内置 runner 提供）


def _context_plugin_id(context):
    """受控 context 里的 plugin id（引擎按连接识别身份；拿不到才退回 SDK 的 plugin_id）。"""
    plugin = context.get("plugin") if isinstance(context, dict) else None
    plugin_id = plugin.get("id") if isinstance(plugin, dict) else None
    return str(plugin_id or _plugin_id())


def _escape(value):
    """本语言原生的 HTML 转义（插件不假设引擎一定会替自己转义动态数据）。"""
    import html as _html
    return _html.escape(str(value), quote=True)


def _webui_html(context):
    """最小 WebUI 页面：<h2>插件页</h2> + Language / SDK / Plugin / Runtime 四项。"""
    plugin_id = _context_plugin_id(context)
    style = "/panel/plugins/webui/%s/static/style.css" % plugin_id
    return (
        '<link rel="stylesheet" href="%s">'
        '<h2>插件页</h2>'
        '<dl class="flowerie-webui lang-%s" id="plugin-info">'
        '<dt>Language</dt><dd class="language">%s</dd>'
        '<dt>SDK</dt><dd class="sdk">%s</dd>'
        '<dt>Plugin</dt><dd class="plugin">%s</dd>'
        '<dt>Runtime</dt><dd class="runtime">%s</dd>'
        '</dl>' % (_escape(style), _escape(RUNTIME), _escape(LANGUAGE),
                   _escape("%s %s" % (SDK_NAME, SDK_VERSION)), _escape(plugin_id),
                   _escape(RUNTIME))
    )


def webui_page(page_id, action, params, values):
    """HTML 文件页的模板变量（manifest 的 web_ui.entry；与其它四种语言同名同义）。"""
    return {"vars": {"language": LANGUAGE, "sdk": "%s %s" % (SDK_NAME, SDK_VERSION),
                     "plugin_id": _plugin_id(), "runtime": RUNTIME}}


def webui_render(page, context):
    """webui.page：插件渲染页（引擎要 HTML，插件返回 HTML + 受控模板变量）。"""
    plugin_id = _context_plugin_id(context)
    return {"html": _webui_html(context),
            "vars": {"language": LANGUAGE, "sdk": "%s %s" % (SDK_NAME, SDK_VERSION),
                     "plugin_id": plugin_id, "runtime": RUNTIME}}


# ---------------- §五/§六 Plugin-to-Plugin（经 SDK 的统一抽象） ----------------

def _call(target, method, params=None, timeout=None, route=None):
    kwargs = {}
    if timeout is not None:
        kwargs["timeout"] = int(timeout)
    if route is not None:
        kwargs["route"] = str(route)
    return _api().plugin.call(str(target), str(method), params if params is not None else {}, **kwargs)


def _native(exc):
    """错误必须转换成**本语言原生**模型（§九）：类型名 + 错误码 + 消息，一个都不能少。"""
    return {"native": type(exc).__name__, "code": getattr(exc, "code", "PLUGIN_ERROR"),
            "message": str(exc)}


def _errors(granted, denied):
    """六种错误一次性触发（§九）：每一种都返回原生观察结果。"""
    probes = (
        ("METHOD_NOT_FOUND", lambda: _call(granted, "no_such_method")),
        ("PLUGIN_NOT_FOUND", lambda: _call("no_such_plugin", "ping")),
        ("PERMISSION_DENIED", lambda: _call(denied, "ping")),
        ("INVALID_ARGUMENT", lambda: _call("", "ping")),
        ("TIMEOUT", lambda: _call(granted, "slow", {}, timeout=200)),
        ("PLUGIN_ERROR", lambda: _call(granted, "boom")),
    )
    out = {}
    for code, probe in probes:
        try:
            probe()
            out[code] = {"native": None, "code": "NO_ERROR", "message": "预期失败但调用成功了"}
        except Exception as exc:  # noqa: BLE001
            out[code] = _native(exc)
    return out


def _run_command(text):
    parts = text.split(" ", 2)
    if len(parts) < 2:
        raise ValueError("空命令")
    head = parts[1]
    rest = parts[2] if len(parts) > 2 else ""
    argv = rest.split(" ") if rest else []
    if head == "ping":
        return _call(argv[0], "ping")
    if head == "info":
        return _get_info({})
    if head == "echo":
        return _echo({"params": json.loads(rest) if rest else {}})
    if head == "seen":
        return _call(argv[0], "seen")
    if head == "call":
        params = json.loads(argv[2]) if len(argv) > 2 and argv[2] else {}
        return _call(argv[0], argv[1], params)
    if head == "route":
        return _call(argv[1], argv[2], {}, route=argv[0])
    if head == "chain":
        return {"t1": _call(argv[0], "ping"),
                "t2": _call(argv[1], "echo", {"hello": "world"}),
                "t3": _call(argv[2], "ping")}
    if head == "errors":
        return _errors(argv[0], argv[1])
    raise ValueError("未知命令: %s" % head)


def _addressed_to_me(text):
    """命令是否发给本插件：/sdk@<id> ... （事件是广播的，不寻址会多插件同时回包）。"""
    if text.startswith("/sdk@"):
        head, _, rest = text[len("/sdk@"):].partition(" ")
        if head != _plugin_id():
            return None
        return "/sdk " + rest
    return text if text.startswith("/sdk ") else None


def on_message(event, api=None):
    """message 事件：/sdk@<自己> 命令 -> 执行 -> 用动作把结果回给引擎（§六）。"""
    text = _addressed_to_me(str(event.get("text") or ""))
    if text is None:
        return None
    try:
        message = json.dumps(_run_command(text), ensure_ascii=False, sort_keys=True)
    except Exception as exc:  # noqa: BLE001 - 结构化失败，不把异常抛给事件层
        message = json.dumps({"ok": False, "code": getattr(exc, "code", "PLUGIN_ERROR"),
                              "message": str(exc)}, ensure_ascii=False, sort_keys=True)
    return {"type": "send_message",
            "payload": {"group_id": event.get("group_id"), "message": message}}


def on_shutdown(context, api=None):
    return None

