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


def _index_vars(context):
    plugin_id = _context_plugin_id(context)
    return {"language": LANGUAGE, "sdk": "%s %s" % (SDK_NAME, SDK_VERSION),
            "plugin_id": plugin_id, "runtime": RUNTIME}


def webui_page(page_id, action, params, values):
    """HTML 文件页的模板变量（manifest 的 web_ui.entry；与其它四种语言同名同义）。"""
    if str(page_id) == "communication":
        return {"vars": _communication_vars(plugin_id=_plugin_id())}
    return {"vars": _index_vars({})}


def webui_render(page, context):
    """webui.page：插件渲染页（引擎要 HTML，插件返回 HTML + 受控模板变量）。"""
    plugin_id = _context_plugin_id(context)
    if _page_id(page) == "communication":
        form = _context_form(context)
        # 引擎在 POST 时也会调本钩子（但不带表单；真正的调用在 webui.action）；
        # 若某种实现把表单放进了 context，这里同样能真调用。
        if _is_call_action(context) and form:
            variables = _apply_call(form, plugin_id)
        else:
            variables = _communication_vars(plugin_id=plugin_id)
        return {"html": _communication_html(variables), "vars": variables}
    return {"html": _webui_html(context), "vars": _index_vars(context)}


# ---------------- WebUI 调用页（任务书《plugin_to_webui》§12/§28） ----------------
# 页面契约见 tests/e2e/README.md §3：元素 id 就是断言契约；零 JS，只有 form POST + 服务端渲染。
# 真调用：plugin.call -> 引擎 Core Router -> **目标插件进程** -> 结果回本页（失败也如实显示）。
# 关联 id：随请求发给目标、由目标原样带回（echo 原样回 params 即往返证明）；拿不到就如实标注。

DEFAULT_REQUEST = '{"hello": "world"}'   # 默认请求（与 tests/e2e 的链路请求同形）
CALL_TIMEOUT_MS = 2500                   # 引擎给 webui.action 的上限是 4s，这里留足余量
TRACE_KEY = "_e2e_trace"                 # 随请求往返的关联 id（与 tests/e2e 夹具插件同一约定）
COMM_METHODS = ("ping", "echo", "get_info", "no_such_method")
COMM_ROUTES = ("auto", "core", "local")
UNRETURNED = "（对端未回传）"


def _new_call_id():
    """本页这次调用的关联 id（插件侧生成；uuid 是标准库）。"""
    import uuid
    return uuid.uuid4().hex[:16]


def _page_id(page):
    if isinstance(page, dict):
        return str(page.get("id") or "index")
    return str(page or "index")


def _context_form(context):
    """引擎若把表单塞进 context（当前版本不塞；webui.action 的 form 才是常规通道）。"""
    form = context.get("form") if isinstance(context, dict) else None
    return form if isinstance(form, dict) else {}


def _is_call_action(context):
    request = context.get("request") if isinstance(context, dict) else None
    action = request.get("action") if isinstance(request, dict) else None
    return str(action or "") == "call"


def _engine_block(result):
    """对端回传的引擎字段：`_engine` 块（夹具约定）与顶层平铺（README §3 约定）都认。"""
    if not isinstance(result, dict):
        return {}
    out = dict(result["_engine"]) if isinstance(result.get("_engine"), dict) else {}
    for key in ("request_id", "trace_id", "route"):
        if not out.get(key) and result.get(key):
            out[key] = result[key]
    return out


def _observed_runtime(api, target, route_policy, result):
    """目标插件**自报**的 runtime：先看回包，再问一次 get_info；都拿不到就留空（不编造）。"""
    if isinstance(result, dict) and result.get("runtime"):
        return str(result["runtime"])
    try:
        info = api.plugin.call(str(target), "get_info", {}, timeout=CALL_TIMEOUT_MS,
                               route=str(route_policy))
    except Exception:  # noqa: BLE001 - 目标没有 get_info 时留空，不编造
        return ""
    return str(info.get("runtime") or "") if isinstance(info, dict) else ""


def _call_target(target, method, request_text, route_policy):
    """真调用目标插件；任何失败都变成页面可渲染的结构化结果。"""
    try:
        payload = json.loads(request_text) if str(request_text or "").strip() else {}
    except ValueError as exc:
        return {"response_ok": "error", "error_code": "INVALID_ARGUMENT",
                "error": "INVALID_ARGUMENT: request 不是合法 JSON: %s" % exc}
    if not isinstance(payload, dict):
        return {"response_ok": "error", "error_code": "INVALID_ARGUMENT",
                "error": "INVALID_ARGUMENT: request 必须是 JSON 对象"}
    call_id = _new_call_id()
    params = dict(payload)
    params[TRACE_KEY] = call_id        # 发给目标；echo 原样带回 -> 证明回包来自目标进程
    api = _api()
    if api is None:
        return {"response_ok": "error", "error_code": "INTERNAL_ERROR",
                "error": "INTERNAL_ERROR: 插件 API 不可用（引擎未注入）",
                "request_id": call_id, "request_id_source": "插件侧 call id",
                "trace_id": call_id, "trace_id_source": "插件侧（无回包）"}
    try:
        result = api.plugin.call(str(target), str(method), params, timeout=CALL_TIMEOUT_MS,
                                 route=str(route_policy))
    except Exception as exc:  # noqa: BLE001 - 跨语言错误 -> 本页可观察的结构化结果
        code = str(getattr(exc, "code", "") or type(exc).__name__)
        body = {"ok": False, "error": {"code": code, "message": str(exc)}}
        return {"response": json.dumps(body, ensure_ascii=False, sort_keys=True),
                "response_ok": "error", "error_code": code, "error": "%s: %s" % (code, exc),
                "request_id": call_id, "request_id_source": "插件侧 call id（调用失败）",
                "trace_id": call_id, "trace_id_source": "插件侧（调用失败，无回包）"}
    trace_back = ""
    if isinstance(result, dict):
        trace_back = str(result.get(TRACE_KEY) or "") or str(result.get("trace_id") or "")
    engine = _engine_block(result)
    engine_request_id = str(engine.get("request_id") or "")
    engine_trace_id = str(engine.get("trace_id") or "")
    engine_route = str(engine.get("route") or "")
    if engine_trace_id:
        trace_source = "引擎（目标插件回传）"
    elif trace_back:
        trace_source = "目标插件原样回传（随请求往返）"
    else:
        trace_source = "插件侧（无回包）"
    return {"response": json.dumps({"ok": True, "result": result}, ensure_ascii=False,
                                   sort_keys=True),
            "response_ok": "ok",
            "target_runtime": _observed_runtime(api, target, route_policy, result),
            "request_id": engine_request_id or call_id,
            "request_id_source": "引擎（目标插件回传）" if engine_request_id else "插件侧 call id",
            "trace_id": engine_trace_id or trace_back or call_id,
            "trace_id_source": trace_source,
            "route": engine_route or str(route_policy),
            "route_source": "引擎（目标插件回传）" if engine_route else "调用方请求的路由策略"}


# ---------------- §五/§六 Plugin-to-Plugin（经 SDK 的统一抽象） ----------------

def _communication_vars(plugin_id="", target="", method="echo", request=DEFAULT_REQUEST,
                        route_policy="auto", response="", response_ok="", error="",
                        error_code="", target_runtime="", request_id="", request_id_source="",
                        trace_id="", trace_id_source="", route="", route_source="", message=""):
    """调用页的全部模板变量（名字与引擎侧断言一致：response_ok / target_runtime / trace_id …）。"""
    return {
        "plugin_name": str(plugin_id), "plugin_id": str(plugin_id), "plugin_status": "running",
        "plugin_runtime": RUNTIME, "plugin_sdk_version": SDK_VERSION,
        "target": str(target), "method": str(method), "request": str(request),
        "route_policy": str(route_policy), "response": str(response),
        "response_ok": str(response_ok), "error": str(error), "error_code": str(error_code),
        "target_runtime": str(target_runtime), "request_id": str(request_id),
        "request_id_source": str(request_id_source), "trace_id": str(trace_id),
        "trace_id_source": str(trace_id_source), "route": str(route),
        "route_source": str(route_source), "message": str(message),
    }


def _apply_call(form, plugin_id=""):
    """把表单变成一次真调用 + 一页可渲染的变量（任何分支都必须渲染得出来）。"""
    target = str(form.get("target") or "").strip()
    method = str(form.get("method") or "ping").strip() or "ping"
    request_text = str(form.get("request") or form.get("params") or DEFAULT_REQUEST)
    route_policy = str(form.get("route") or "auto").strip() or "auto"
    variables = _communication_vars(plugin_id=plugin_id, target=target, method=method,
                                    request=request_text, route_policy=route_policy)
    if not target:
        variables.update({"response_ok": "error", "error_code": "INVALID_ARGUMENT",
                          "error": "INVALID_ARGUMENT: 请填写目标插件 id"})
    else:
        try:
            variables.update(_call_target(target, method, request_text, route_policy))
        except Exception as exc:  # noqa: BLE001 - 页面永远要渲染得出来
            variables.update({"response_ok": "error", "error_code": type(exc).__name__,
                              "error": "%s: %s" % (type(exc).__name__, exc)})
    if variables.get("response_ok") == "ok":
        variables["message"] = "Status: OK · 调用完成"
    else:
        variables["message"] = "Status: Failed · Code: %s" % (
            variables.get("error_code") or "PLUGIN_ERROR")
    return variables


def _selected(value, option):
    return " selected" if str(value) == option else ""


def _options(values, current):
    html = "".join("<option value=\"%s\"%s>%s</option>"
                   % (_escape(v), _selected(current, v), _escape(v)) for v in values)
    if str(current) and str(current) not in values:
        # 自定义方法名也要能原样回填提交
        html += "<option value=\"%s\" selected>%s</option>" % (_escape(current), _escape(current))
    return html


def _communication_html(v):
    """调用页 HTML（零 JS）：表单 + 结果区；元素 id 见 tests/e2e/README.md §3。"""
    base = "/panel/plugins/webui/%s" % _escape(v["plugin_id"])
    return (
        '<link rel="stylesheet" href="%s/static/style.css">'
        '<h1 id="plugin-name">%s</h1>'
        '<p id="plugin-status" class="status">状态：%s</p>'
        '<section id="communication-panel" class="card">'
        '<h2>跨插件调用（Browser → %s 插件 → Core Router → 目标插件 → 回本页）</h2>'
        '<form id="communication-form" method="post" action="%s/communication">'
        '<label for="communication-target">目标插件（target plugin）</label>'
        '<input type="text" id="communication-target" name="target" value="%s"'
        ' placeholder="minimal_go">'
        '<label for="communication-method">方法（method）</label>'
        '<select id="communication-method" name="method">%s</select>'
        '<label for="communication-route">路由策略（route）</label>'
        '<select id="communication-route" name="route">%s</select>'
        '<label for="communication-request">请求参数（request，JSON 对象）</label>'
        '<textarea id="communication-request" name="request" rows="3">%s</textarea>'
        '<button type="submit" id="communication-submit" name="plugin_action" value="call">'
        '调用</button>'
        '</form>'
        '<table id="communication-result">'
        '<tr><th>target plugin</th><td id="communication-target-out">%s</td></tr>'
        '<tr><th>method</th><td id="communication-method-out">%s</td></tr>'
        '<tr><th>request</th><td><pre id="communication-request-out">%s</pre></td></tr>'
        '<tr><th>response</th><td><pre id="communication-response">%s</pre></td></tr>'
        '<tr><th>request_id</th><td id="communication-request-id">%s '
        '<small id="communication-request-id-source">%s</small></td></tr>'
        '<tr><th>trace_id</th><td id="communication-trace-id">%s '
        '<small id="communication-trace-id-source">%s</small></td></tr>'
        '<tr><th>route</th><td id="communication-route-out">%s '
        '<small id="communication-route-source">%s</small></td></tr>'
        '<tr><th>目标运行时（观察值）</th><td id="communication-target-runtime">%s</td></tr>'
        '<tr><th>结果</th><td id="communication-response-ok">%s</td></tr>'
        '<tr><th>错误</th><td id="communication-error">%s</td></tr>'
        '</table>'
        '<p id="communication-message">%s</p>'
        '</section>'
        '<nav id="plugin-nav"><a id="nav-index" href="%s/index">Index</a>'
        '<a id="nav-communication" href="%s/communication">Communication</a></nav>'
        % (base, _escape(v["plugin_name"]), _escape(v["plugin_status"]), _escape(LANGUAGE), base,
           _escape(v["target"]), _options(COMM_METHODS, v["method"]),
           _options(COMM_ROUTES, v["route_policy"]), _escape(v["request"]),
           _escape(v["target"]), _escape(v["method"]), _escape(v["request"]),
           _escape(v["response"]), _escape(v["request_id"]), _escape(v["request_id_source"]),
           _escape(v["trace_id"]), _escape(v["trace_id_source"]), _escape(v["route"]),
           _escape(v["route_source"]), _escape(v["target_runtime"] or UNRETURNED),
           _escape(v["response_ok"]), _escape(v["error"]), _escape(v["message"]), base, base)
    )


def webui_action(page, action, form, context):
    """webui.action：调用页的 POST（按钮 name=plugin_action value=call）-> 真调用 -> 重渲染。"""
    plugin_id = _context_plugin_id(context)
    form = form if isinstance(form, dict) else {}
    if _page_id(page) != "communication":
        return {"ok": False, "error": "未知动作: %s" % (action or "")}
    if str(action or "") == "call" or str(form.get("plugin_action") or "") == "call":
        variables = _apply_call(form, plugin_id)
    else:
        variables = _communication_vars(plugin_id=plugin_id,
                                        message="未知动作: %s" % (action or ""))
    return {"html": _communication_html(variables), "vars": variables,
            "message": variables["message"]}

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

