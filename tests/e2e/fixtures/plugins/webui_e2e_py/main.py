"""tests/e2e 夹具插件：浏览器 E2E 的入口 WebUI 插件（Python 运行时，真插件进程）。

职责只有一个：把「浏览器 -> 插件 WebUI -> 插件 -> 另一个插件进程 -> 回浏览器」这条链路
做成**可断言**的。页面元素 id 是 tests/e2e 的契约（见 tests/e2e/README.md）：

    index.html          #plugin-name #plugin-status #plugin-runtime #plugin-version #plugin-sdk-version
    settings.html       #settings-form #setting-greeting #setting-count #setting-mode
                        #setting-notify #settings-submit #settings-message #settings-state
    communication.html  #communication-panel #communication-target #communication-method
                        #communication-request #communication-route #communication-submit
                        #communication-response #communication-target-runtime
                        #communication-request-id #communication-trace-id #communication-message

零 JavaScript：三页都没有 <script>，交互全部是 form POST + 服务端重渲染（引擎侧另有
CSP default-src 'none' 兜底）。本文件只用 runner 暴露的 SDK 面（api.plugin.expose /
api.plugin.call / api.context_info），不 import 任何 Flowerie 内部模块。
"""
import json
import os
import time
import uuid

SDK_VERSION = "1.0.0"
API = {"api": None}
STATE = {"greeting": "hello", "count": 1, "mode": "b", "notify": True, "saved_at": ""}
STARTED_AT = time.time()
DEFAULT_REQUEST = '{"hello": "world"}'


# ----------------------------------------------------------------- 状态

def _data_dir():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    os.makedirs(path, exist_ok=True)
    return path


def _state_path():
    return os.path.join(_data_dir(), "state.json")


def _load_state():
    try:
        with open(_state_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            merged = dict(STATE)
            merged.update(data)
            return merged
    except (OSError, ValueError):
        pass
    return dict(STATE)


def _save_state(state):
    try:
        with open(_state_path(), "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ----------------------------------------------------------------- SDK 面

def _api():
    return API["api"]


def _engine_context():
    """引擎给出的**真实**身份（plugin_id / name / version / runtime / protocol_version / 权限）。"""
    api = _api()
    if api is None:
        return {}
    try:
        raw = api.context_info() or {}
    except Exception:  # noqa: BLE001 - 引擎不可用时页面仍要能渲染
        return {}
    payload = raw.get("result") if isinstance(raw.get("result"), dict) else raw
    return payload if isinstance(payload, dict) else {}


def _status_text():
    return "running" if _api() is not None else "unknown"


def on_startup(context=None, api=None):
    """真插件进程启动：注册被调方法（供其它语言插件经 Core Router 调用本插件）。"""
    API["api"] = api
    if api is None:
        return None
    for name, handler in (("ping", _ping), ("echo", _echo), ("get_info", _get_info)):
        try:
            api.plugin.expose(name, handler)
        except Exception:  # noqa: BLE001 - SDK 没有 expose 时不影响 WebUI 页面
            pass
    return None


def _ping(request):
    return {"ok": True, "plugin": "webui-e2e-py", "runtime": "python"}


def _observed(request):
    """被调方看到的**引擎侧**调用上下文（request_id / trace_id / route / source）。

    引擎把整条 forward 请求交给被调 handler，所以被调方可以把这几个字段**原样回传**给调用方 ——
    调用方自己的 SDK 只拿得到 result，这是它唯一能看到引擎 id 的途径（页面会如实标注来源）。
    """
    source = request.get("source") if isinstance(request.get("source"), dict) else {}
    return {"request_id": str(request.get("request_id") or ""),
            "trace_id": str(request.get("trace_id") or ""),
            "route": str(request.get("route") or ""),
            "method": str(request.get("method") or ""),
            "hop_count": int(request.get("hop_count") or 0),
            "source": str(source.get("plugin_id") or ""),
            "source_runtime": str(source.get("runtime") or "")}


def _echo(request):
    """原样回显 params（跨语言对端的通用语义），并附上被调方观测到的引擎上下文。

    引擎字段同时以两种形状回传（互操作约定，见 tests/e2e/README.md §3）：
      * 顶层 request_id / trace_id / route —— 与 examples/plugin-webui-test 的 echo 约定一致；
      * 嵌套 "_engine" 块 —— 本夹具自己的完整观测（含 source / hop_count）。
    """
    out = dict(request.get("params") or {})
    observed = _observed(request)
    out["_engine"] = observed
    for key in ("request_id", "trace_id", "route"):
        out.setdefault(key, observed[key])
    return out


def _get_info(request):
    return {"plugin_id": _engine_context().get("plugin_id") or "webui_e2e_py",
            "runtime": "python", "sdk_version": SDK_VERSION, "protocol_version": "1"}


# ----------------------------------------------------------------- 页面变量

def _base_vars():
    ctx = _engine_context()
    return {
        "status": _status_text(),
        "runtime": str(ctx.get("runtime") or "python"),
        "plugin_version": str(ctx.get("version") or "1.0.0"),
        "sdk_version": SDK_VERSION,
        "protocol_version": str(ctx.get("protocol_version") or "1"),
        "permissions": ", ".join(sorted(ctx.get("permissions") or [])) or "（无）",
        "uptime_seconds": "%d" % int(time.time() - STARTED_AT),
        "message": "",
    }


def _settings_vars(state, message=""):
    out = _base_vars()
    out.update({
        "greeting": str(state.get("greeting") or ""),
        "count": str(state.get("count") if state.get("count") is not None else 1),
        "mode": str(state.get("mode") or "b"),
        "notify_text": "on" if state.get("notify") else "off",
        "saved_at": str(state.get("saved_at") or "（尚未保存）"),
        "message": message,
    })
    return out


def _communication_vars(message="", target="", method="echo", request=DEFAULT_REQUEST,
                        response="", response_ok="", error="", target_runtime="",
                        request_id="", trace_id="", route="core", route_policy="auto",
                        request_id_source="", trace_id_source="", route_source=""):
    out = _base_vars()
    out.update({
        "target": str(target),
        "method": str(method),
        "request": str(request),
        "route_policy": str(route_policy),
        "response": str(response),
        "response_ok": str(response_ok),
        "error": str(error),
        "target_runtime": str(target_runtime),
        "request_id": str(request_id),
        "trace_id": str(trace_id),
        "route": str(route),
        "request_id_source": str(request_id_source),
        "trace_id_source": str(trace_id_source),
        "route_source": str(route_source),
        "message": message,
    })
    return out


def webui_page(page, action="get", params=None, values=None):
    """GET 渲染钩子（manifest web_ui.entry）：返回受控模板变量。"""
    page_id = str(page or "")
    if page_id == "settings":
        return {"vars": _settings_vars(_load_state())}
    if page_id == "communication":
        return {"vars": _communication_vars()}
    return {"vars": _base_vars()}


def _call_target(target, method, request_text, route_policy):
    """真调用：SDK -> 引擎 Core Router -> 目标插件进程 -> 回到这里。

    诚实说明（写进 tests/e2e 报告）：runner 的 plugin.call() 只把 **result** 交给插件，
    引擎侧的 request_id / trace_id 不进插件进程 —— 所以本页显示的 request_id 是**插件侧
    call id**（页面上如实标注），trace_id 是随请求发给目标又原样回来的关联 id（可验证往返）。
    失败一律显示真实的错误码/消息，绝不伪造成功。
    """
    try:
        payload = json.loads(request_text) if str(request_text or "").strip() else {}
    except ValueError as exc:
        return {"error": "request 不是合法 JSON: %s" % exc}
    if not isinstance(payload, dict):
        return {"error": "request 必须是 JSON 对象"}
    call_id = uuid.uuid4().hex[:16]
    params = dict(payload)
    params["_e2e_trace"] = call_id
    api = _api()
    if api is None:
        return {"error": "插件 API 不可用（引擎未注入）", "request_id": call_id, "trace_id": call_id}
    try:
        result = api.plugin.call(str(target), str(method), params, route=str(route_policy))
    except Exception as exc:  # noqa: BLE001 - 跨语言错误必须转成本页可观察的结果
        code = str(getattr(exc, "code", "") or type(exc).__name__)
        body = {"ok": False, "error": {"code": code, "message": str(exc)}}
        return {"response": json.dumps(body, ensure_ascii=False, sort_keys=True),
                "response_ok": "error", "error": "%s: %s" % (code, exc),
                "request_id": call_id, "request_id_source": "插件侧 call id",
                "trace_id": call_id, "trace_id_source": "插件侧（调用失败，无回包）",
                "route": "core", "route_source": "引擎侧路径约定（跨语言恒为 core）"}
    runtime = ""
    if isinstance(result, dict):
        runtime = str(result.get("runtime") or "")
        trace_back = str(result.get("_e2e_trace") or "")
    else:
        trace_back = ""
    if not runtime:
        # 目标不是 echo（例如 ping）：再问一次 get_info，拿到**观察到的**目标 runtime
        try:
            info = api.plugin.call(str(target), "get_info", {})
            runtime = str(info.get("runtime") or "") if isinstance(info, dict) else ""
        except Exception:  # noqa: BLE001 - 目标没有 get_info 时留空，不编造
            runtime = ""
    engine = result.get("_engine") if isinstance(result, dict) else None
    engine = engine if isinstance(engine, dict) else {}
    engine_request_id = str(engine.get("request_id") or "")
    engine_trace_id = str(engine.get("trace_id") or "")
    engine_route = str(engine.get("route") or "")
    body = {"ok": True, "result": result}
    return {"response": json.dumps(body, ensure_ascii=False, sort_keys=True),
            "response_ok": "ok", "target_runtime": runtime,
            "request_id": engine_request_id or call_id,
            "request_id_source": "引擎（目标插件回传）" if engine_request_id else "插件侧 call id",
            "trace_id": engine_trace_id or trace_back or call_id,
            "trace_id_source": "引擎（目标插件回传）" if engine_trace_id else "插件侧（随请求往返）",
            "route": engine_route or "core",
            "route_source": "引擎（目标插件回传）" if engine_route else "引擎侧路径约定（跨语言恒为 core）"}


def webui_action(page, action="submit", form=None, context=None):
    """POST 钩子（webui.action 能力）：设置页保存 + 通信页真调用。"""
    page_id = ""
    if isinstance(page, dict):
        page_id = str(page.get("id") or "")
    elif page is not None:
        page_id = str(page)
    form = form if isinstance(form, dict) else {}
    action = str(action or "")
    if page_id == "settings":
        state = _load_state()
        if action == "save":
            try:
                count = int(str(form.get("count") or state.get("count") or 1))
            except ValueError:
                count = int(state.get("count") or 1)
            state["greeting"] = str(form.get("greeting") or "")[:80]
            state["count"] = max(0, min(999, count))
            state["mode"] = str(form.get("mode") or "b")[:8]
            state["notify"] = str(form.get("notify") or "") in ("1", "on", "true", "yes")
            state["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _save_state(state)
            return {"vars": _settings_vars(state, "设置已保存"), "message": "设置已保存"}
        return {"vars": _settings_vars(state)}
    if page_id == "communication":
        if action != "call":
            return {"vars": _communication_vars(message="未知动作: %s" % action)}
        target = str(form.get("target") or "").strip()
        method = str(form.get("method") or "ping").strip()
        request_text = str(form.get("request") or DEFAULT_REQUEST)
        route_policy = str(form.get("route") or "auto").strip() or "auto"
        if not target:
            return {"vars": _communication_vars(message="请填写目标插件 id")}
        try:
            call = _call_target(target, method, request_text, route_policy)
        except Exception as exc:  # noqa: BLE001 - 页面永远要能渲染出结果
            call = {"error": "%s: %s" % (type(exc).__name__, exc)}
        out = _communication_vars(target=target, method=method, request=request_text,
                                  route_policy=route_policy)
        out.update(call)
        out["message"] = "调用完成" if not out.get("error") else "调用失败"
        return {"vars": out, "message": out["message"]}
    return {"vars": _base_vars()}


def on_shutdown(context=None, api=None):
    return None
