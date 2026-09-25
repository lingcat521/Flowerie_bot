"""Plugin WebUI 专用测试插件（任务书《plugin_to_webui》§4/§5/§10/§11/§12/§14/§16/§17）。

零 JavaScript：页面只有 HTML + CSS，全部交互都是 form POST → webui.action → 服务端重渲染。

本文件只使用插件进程能看到的 runner API（runner 以 python -I 隔离模式启动，插件进程里没有
仓库代码可导入，所以这里不 import 任何 Flowerie 内部模块）：

    api.plugin.call / acall / emit / on / expose / cancel
    api.config_get / config_set        —— 插件覆盖层落到 data/config.json
    api.storage_get / storage_set      —— 落到 data/storage/<key>.json
    api.permission_check / context_info
    api.log

三个页面（manifest.web_ui.pages）：
- index          文件页 pages/index.html；webui_page 数据钩子给插件名/版本/runtime/status/SDK 版本
- settings       文件页 pages/settings.html；webui_page 数据钩子给 name/number/enabled/mode
- communication  插件渲染页 render="plugin"；webui_render 返回 HTML（模板取自 pages/communication.html）

WebUI 协议钩子（引擎调用；钩子内部自己兜住异常，只返回结构化结果，绝不把异常抛成 500）：
    webui_page(page_id, action, params, values)   HTML 文件页的模板变量钩子
    webui_render(page, context)                   webui.page：插件渲染页
    webui_action(page, action, form, context)     webui.action：表单提交
    webui_asset(path)                             webui.asset：webui/static 之外的动态资源
"""
import base64
import json
import os
import re
import time

PLUGIN_ID_FALLBACK = "plugin_webui_test"
PLUGIN_VERSION = "1.0.0"
SDK_VERSION = "v1（Plugin Protocol v1 / Python Runner）"

#: 声明能力组（runner 展开成方法名集合；未声明的能力引擎绝不调用，见 docs/plugin-webui-protocol.md §4）
PLUGIN_CAPABILITIES = ("context", "config", "permission", "storage", "webui", "plugin")

SETTING_KEYS = ("name", "number", "enabled", "mode")
MODES = ("auto", "manual", "debug")
ROUTES = ("auto", "local", "core")
DEFAULT_SETTINGS = {"name": "Flowerie", "number": 123, "enabled": True, "mode": "auto"}
DEFAULT_TIMEOUT_MS = 5000
MIN_TIMEOUT_MS = 100
MAX_TIMEOUT_MS = 30000
MAX_PARAMS_CHARS = 4000
MAX_DISPLAY_CHARS = 2000
MAX_EVENTS = 10
#: 引擎/runner 的结构化错误码；页面只显示这些，其余一律归一成 PLUGIN_ERROR
ERROR_CODES = (
    "PLUGIN_NOT_FOUND", "PLUGIN_NOT_READY", "METHOD_NOT_FOUND", "PERMISSION_DENIED",
    "INVALID_ARGUMENT", "TIMEOUT", "CANCELLED", "SERIALIZATION_ERROR", "PLUGIN_ERROR",
    "INTERNAL_ERROR", "PLUGIN_UNAVAILABLE", "PLUGIN_CALL_LOOP",
)
#: 对端没有回传 request_id / trace_id 时的显示（引擎不把自己的响应模型透给调用方，所以不编造）
NOT_ECHOED = "（对端未回传）"

#: on_startup 注入的 API 句柄：webui_* 钩子没有 api 参数，只能从这里取
_API = {"api": None, "plugin_id": PLUGIN_ID_FALLBACK}

#: 绝对路径抹除：**用字符串扫描而不是正则** —— 正则里 "(?:/[...]+)+" 这类嵌套量词会被仓库的
#: 回溯歧义扫描（tests/test_code_scanning_redos.py）拦下，而这里根本不需要正则。
_PATH_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-\\/+")


def _redact_paths(text):
    """把 "/a/b/c" 这类绝对路径换掉（§16：错误展示里不泄露文件系统路径）。

    线性扫描（正则版会被回溯歧义扫描拦下）：遇到 "/" 且后面还有一个 "/"，就吞掉整段路径字符。
    """
    out = []
    i = 0
    while i < len(text):
        if text[i] == "/":
            j = i + 1
            while j < len(text) and text[j] in _PATH_CHARS:
                j += 1
            if text.find("/", i + 1, j) != -1 and j - i >= 3:
                out.append("[path]")
                i = j
                continue
        out.append(text[i])
        i += 1
    return "".join(out)


# ---------------------------------------------------------------- 基础工具

def _api():
    return _API["api"]


def _plugin_id(context=None):
    if isinstance(context, dict):
        plugin = context.get("plugin")
        if isinstance(plugin, dict) and plugin.get("id"):
            return _text(plugin.get("id"), 64)
    return _API["plugin_id"] or PLUGIN_ID_FALLBACK


def _page_id(page):
    return _text(page.get("id"), 32) if isinstance(page, dict) else ""


def _plugin_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _page_url(page_id):
    return "/panel/plugins/webui/%s/%s" % (_plugin_id(), page_id)


def _asset_url(path):
    return "/panel/plugins/webui/%s/asset/%s" % (_plugin_id(), path)


def _static_url(path):
    return "/panel/plugins/webui/%s/static/%s" % (_plugin_id(), path)


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _text(value, limit):
    return str(value if value is not None else "")[:limit]


def _bool(value):
    return str(value).strip().lower() in ("1", "true", "on", "yes", "checked")


def _int(value, default, low, high):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _clip(text, limit=MAX_DISPLAY_CHARS):
    text = str(text if text is not None else "")
    return text if len(text) <= limit else text[:limit] + "…（已截断）"


def _json_text(value, limit=MAX_DISPLAY_CHARS):
    try:
        text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    except (TypeError, ValueError):
        text = json.dumps(str(value), ensure_ascii=False)
    return _clip(text, limit)


def _display(value, empty="（无）"):
    """响应体可能是对象、字符串或 None；统一成可展示、且大小有界的文本。"""
    if value is None:
        return empty
    if isinstance(value, str):
        return _clip(value)
    return _json_text(value)


def _redact(message):
    """错误信息只保留可展示的部分：截断、去换行、抹掉 Traceback 尾巴与绝对路径。"""
    text = _text(message, 300).replace("\r", " ").replace("\n", " ").strip()
    cut = text.find("Traceback")
    if cut >= 0:
        text = text[:cut].strip()
    return _redact_paths(text)


def _bounded(value, limit=MAX_DISPLAY_CHARS):
    """落盘前把值限制在可展示大小内（storage 单值上限 64KB，超限降级成截断字符串）。"""
    try:
        text = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return _clip(str(value), limit)
    return value if len(text) <= limit else _clip(text, limit)


def _read_file(*parts):
    path = os.path.join(_plugin_dir(), *parts)
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


# ---------------------------------------------------------------- API 包装（全部自己兜异常）

def _plugin_info():
    """引擎侧上下文：plugin_id / name / version / runtime / protocol_version / permissions。"""
    info = {"plugin_id": _API["plugin_id"], "name": PLUGIN_ID_FALLBACK, "version": PLUGIN_VERSION,
            "runtime": "python", "protocol_version": "1", "permissions": []}
    api = _api()
    if api is None:
        return info
    try:
        got = api.context_info()
    except Exception:
        return info
    if isinstance(got, dict):
        for key in ("plugin_id", "name", "version", "runtime", "protocol_version", "permissions"):
            if got.get(key) not in (None, ""):
                info[key] = got[key]
    return info


def _granted(permission):
    """只读查询管理员是否批准了某权限（api.permission_check，无法提权）。"""
    api = _api()
    if api is None:
        return False
    try:
        return bool(api.permission_check(permission))
    except Exception:
        return False


def _storage_get(key, default=None):
    api = _api()
    if api is None:
        return default
    try:
        value = api.storage_get(key)
    except Exception:
        return default
    return default if value is None else value


def _storage_set(key, value):
    api = _api()
    if api is None:
        return False
    try:
        result = api.storage_set(key, _bounded(value))
    except Exception:
        return False
    return not (isinstance(result, dict) and result.get("ok") is False)


def _config_values():
    api = _api()
    if api is None:
        return {}
    try:
        got = api.config_get(list(SETTING_KEYS))
    except Exception:
        return {}
    if not isinstance(got, dict):
        return {}
    return {key: got[key] for key in SETTING_KEYS if key in got}


def _log(level, message):
    api = _api()
    if api is None:
        return
    try:
        api.log(level, _text(message, 300))
    except Exception:
        pass


# ---------------------------------------------------------------- 设置（§11 config round-trip）

def _normalize_settings(raw):
    """表单字符串 / config JSON / 默认值 → {name, number, enabled, mode}。"""
    values = dict(DEFAULT_SETTINGS)
    if isinstance(raw, dict):
        for key in SETTING_KEYS:
            if raw.get(key) is not None:
                values[key] = raw[key]
    enabled = values.get("enabled")
    mode = str(values.get("mode") or "").strip().lower()
    return {
        "name": _text(values.get("name"), 64).strip() or DEFAULT_SETTINGS["name"],
        "number": _int(values.get("number"), DEFAULT_SETTINGS["number"], -1000000, 1000000),
        "enabled": enabled if isinstance(enabled, bool) else _bool(enabled),
        "mode": mode if mode in MODES else DEFAULT_SETTINGS["mode"],
    }


def _settings_from_form(form):
    """表单 → 设置：HTML checkbox 未勾选时字段根本不出现，所以 enabled 显式补 False。"""
    form = form if isinstance(form, dict) else {}
    raw = {key: form.get(key) for key in SETTING_KEYS}
    raw["enabled"] = _bool(form.get("enabled"))
    return _normalize_settings(raw)


def _load_settings():
    """读当前设置：config_get()（插件覆盖层，data/config.json）优先，storage 快照兜底。"""
    raw = _config_values()
    if not raw:
        stored = _storage_get("settings")
        if isinstance(stored, dict) and isinstance(stored.get("values"), dict):
            raw = {key: stored["values"].get(key) for key in SETTING_KEYS}
    return _normalize_settings(raw)


def _save_settings(form):
    """settings 页提交：api.config_set() 落盘 → api.storage_set() 存快照；返回 (设置, 问题列表)。"""
    settings = _settings_from_form(form)
    problems = []
    api = _api()
    if api is None:
        return settings, ["插件 API 未注入（runner 未完成 on_startup）"]
    try:
        result = api.config_set(dict(settings))
        if isinstance(result, dict) and result.get("ok") is False:
            problems.append("config_set 失败：%s" % _redact(result.get("error") or ""))
    except Exception as exc:
        problems.append("config_set 异常：%s" % type(exc).__name__)
    if not _storage_set("settings", {"values": dict(settings), "saved_at": _now()}):
        problems.append("storage_set 失败")
    _log("info", "settings saved: name=%s number=%s enabled=%s mode=%s"
         % (settings["name"], settings["number"], settings["enabled"], settings["mode"]))
    return settings, problems


def _settings_vars(settings=None, message=""):
    settings = settings or _load_settings()
    stored = _storage_get("settings")
    # 引擎的模板替换只发生在文本和属性值里：裸属性占位符（checked/selected）会被 HTML 净化器
    # 当成未知属性丢掉（见 README「已知引擎限制」）。所以这里用 class 标记 + 显式读回值表达状态。
    state = {mode: "is-selected" if settings["mode"] == mode else "is-unselected" for mode in MODES}
    return {
        "name": settings["name"],
        "number": str(settings["number"]),
        "enabled": "true" if settings["enabled"] else "false",
        "enabled_text": "true" if settings["enabled"] else "false",
        "enabled_state": "is-on" if settings["enabled"] else "is-off",
        "mode": settings["mode"],
        "mode_auto_state": state["auto"],
        "mode_manual_state": state["manual"],
        "mode_debug_state": state["debug"],
        "settings_json": _json_text(settings, 600),
        "config_json": _json_text(_config_values(), 600) if _config_values() else "（config_get() 还没有值）",
        "stored_json": _json_text(stored, 600) if isinstance(stored, dict) else "（storage 里还没有快照）",
        "message": message,
        "settings_url": _page_url("settings"),
        "index_url": _page_url("index"),
        "communication_url": _page_url("communication"),
    }


# ---------------------------------------------------------------- 插件能力（§10 get_info / echo / set_config）

def _info_payload():
    info = _plugin_info()
    permissions = info.get("permissions")
    return {
        "plugin_id": str(info.get("plugin_id") or ""),
        "name": str(info.get("name") or ""),
        "version": str(info.get("version") or PLUGIN_VERSION),
        "runtime": str(info.get("runtime") or "python"),
        "status": "running",
        "sdk_version": SDK_VERSION,
        "protocol_version": str(info.get("protocol_version") or "1"),
        "permissions": sorted(_text(item, 64) for item in permissions) if isinstance(permissions, list) else [],
        "capabilities": list(PLUGIN_CAPABILITIES),
        "time": _now(),
    }


def _echo_payload(request):
    """echo：原样回显 params，并把 Core 给的 request_id / trace_id / route / source 一起回传。

    这是本插件的**对端契约范例**：目标插件若同样回传这几个字段，communication 页就能显示
    真实的 request_id / trace_id / route。引擎不会把响应模型透给调用方（插件看不到自己那次
    调用的 id），所以对端不回传时页面如实显示「对端未回传」，不编造。
    """
    request = request if isinstance(request, dict) else {}
    source = request.get("source") if isinstance(request.get("source"), dict) else {}
    return {
        "echo": request.get("params") if isinstance(request.get("params"), dict) else {},
        "plugin_id": _plugin_id(),
        "runtime": "python",
        "request_id": _text(request.get("request_id"), 96),
        "trace_id": _text(request.get("trace_id"), 96),
        "route": _text(request.get("route"), 16),
        "hop_count": _int(request.get("hop_count"), 0, 0, 64),
        "source": _text(source.get("plugin_id"), 96),
        "time": _now(),
    }


def _set_config_payload(payload):
    """set_config：写插件自己的配置覆盖层（用独立键，不动 settings 页的四个键）。"""
    values = {"self_test": {"text": _text((payload or {}).get("text"), 200), "at": _now()}}
    result = {"ok": False, "keys": sorted(values), "time": _now()}
    api = _api()
    if api is None:
        result["error"] = "插件 API 未注入"
        return result
    try:
        written = api.config_set(values)
        result["ok"] = not (isinstance(written, dict) and written.get("ok") is False)
    except Exception as exc:
        result["error"] = type(exc).__name__
    return result


def _slow_handler(_request=None):
    """故意慢：配合 WebUI 的 timeout_ms 验证 TIMEOUT 结构化错误。"""
    time.sleep(1.5)
    return {"slept_ms": 1500, "plugin_id": _plugin_id(), "time": _now()}


def _boom_handler(_request=None):
    """故意抛异常：Core 会把它归一成结构化 PLUGIN_ERROR（不是 500，也没有堆栈）。"""
    raise RuntimeError("boom: plugin_webui_test 故意抛出的异常（验证结构化错误）")


def _self_test(action, values):
    """§10：WebUI → 插件能力自检（get_info / echo / set_config 三个动作）。"""
    values = values if isinstance(values, dict) else {}
    if action == "get_info":
        return _info_payload()
    if action == "echo":
        return _echo_payload({"params": {"text": _text(values.get("echo_text"), 200), "from": "webui"},
                              "source": {"plugin_id": _plugin_id()}, "method": "echo"})
    if action == "set_config":
        return _set_config_payload({"text": _text(values.get("echo_text"), 200)})
    return None


def _on_event(event):
    """订阅全部事件（api.plugin.on("*")）：最近 MAX_EVENTS 条记进 storage，页面显示 Event received。"""
    event = event if isinstance(event, dict) else {}
    source = event.get("source") if isinstance(event.get("source"), dict) else {}
    items = _events()
    items.insert(0, {
        "name": _text(event.get("name"), 96),
        "source": _text(source.get("plugin_id"), 96),
        "trace_id": _text(event.get("trace_id"), 96),
        "payload": _bounded(event.get("payload"), 400),
        "received_at": _now(),
    })
    _storage_set("events", items[:MAX_EVENTS])
    return {"ok": True}


def _events():
    stored = _storage_get("events")
    if not isinstance(stored, list):
        return []
    return [item for item in stored if isinstance(item, dict)][:MAX_EVENTS]


# ---------------------------------------------------------------- 跨插件调用（§12 / §14 / §15 / §16）

def _parse_params(text):
    if not text:
        return {}, None
    try:
        value = json.loads(text)
    except ValueError as exc:
        return {}, {"code": "INVALID_ARGUMENT", "message": "params 不是合法 JSON：%s" % _redact(exc)}
    if not isinstance(value, (dict, list)):
        return {}, {"code": "INVALID_ARGUMENT", "message": "params 必须是 JSON 对象或数组"}
    return value, None


def _comm_error(error):
    if isinstance(error, dict):
        code = _text(error.get("code"), 64)
        if code not in ERROR_CODES:
            code = "PLUGIN_ERROR"
        return {"code": code, "message": _redact(error.get("message") or code)}
    return {"code": "PLUGIN_ERROR", "message": _redact(error) or "插件调用失败"}


def _error_of(exc):
    """runner 的 PluginCommError 带 code/message（跨语言结构）；本地异常只暴露异常类型名。"""
    code = _text(getattr(exc, "code", ""), 64)
    if code in ERROR_CODES:
        return code, _redact(getattr(exc, "message", "") or code)
    return "PLUGIN_ERROR", "插件内部异常：%s（详情见日志；页面不显示堆栈/路径）" % type(exc).__name__


def _save_last_call(record):
    payload = dict(record)
    for key in ("request", "response"):
        if key in payload:
            payload[key] = _bounded(payload[key])
    _storage_set("last_call", payload)


def _last_call():
    stored = _storage_get("last_call")
    return stored if isinstance(stored, dict) else {}


def _run_comm(action, form, context=None):
    """§12/§14：webui.action=call/emit → api.plugin.call / api.plugin.emit，失败也是结构化返回。"""
    api = _api()
    form = form if isinstance(form, dict) else {}
    target = _text(form.get("target"), 96).strip()
    method = _text(form.get("method"), 96).strip()
    route = _text(form.get("route"), 16).strip().lower()
    route = route if route in ROUTES else "auto"
    timeout_ms = _int(form.get("timeout_ms"), DEFAULT_TIMEOUT_MS, MIN_TIMEOUT_MS, MAX_TIMEOUT_MS)
    params_text = _text(form.get("params"), MAX_PARAMS_CHARS).strip()
    record = {"kind": action, "source": _plugin_id(context), "target": target, "method": method,
              "route": route, "timeout_ms": timeout_ms, "params_text": params_text,
              "called_at": _now(), "ok": None}

    def _fail(code, message):
        record["ok"] = False
        record["error"] = {"code": code, "message": _redact(message)}
        _save_last_call(record)
        return record

    params, parse_error = _parse_params(params_text)
    if parse_error is not None:
        return _fail(parse_error["code"], parse_error["message"])
    record["request"] = {"target": target, "method": method, "params": params,
                         "route": route, "timeout_ms": timeout_ms}
    if api is None:
        return _fail("INTERNAL_ERROR", "插件 API 未注入（runner 未完成 on_startup）")
    if not method:
        return _fail("INVALID_ARGUMENT", "method 不能为空")
    if action == "call" and not target:
        return _fail("INVALID_ARGUMENT", "plugin.call 的 target 不能为空（emit 只按事件名广播）")
    try:
        if action == "emit":
            result = api.plugin.emit(method, params)
            result = result if isinstance(result, dict) else {}
            record["ok"] = result.get("ok") is not False
            record["delivered"] = _int(result.get("delivered"), 0, 0, 10000)
            record["failed_count"] = len(result.get("failed") or [])
            record["trace_id"] = _text(result.get("trace_id"), 96)
            record["response"] = result
            if not record["ok"]:
                record["error"] = _comm_error(result.get("error"))
        else:
            result = api.plugin.call(target, method, params, timeout=timeout_ms, route=route)
            record["ok"] = True
            record["response"] = result
            echoed = result if isinstance(result, dict) else {}
            record["request_id"] = _text(echoed.get("request_id"), 96)
            record["trace_id"] = _text(echoed.get("trace_id"), 96)
            if _text(echoed.get("route"), 16):
                record["route"] = _text(echoed.get("route"), 16)
    except Exception as exc:
        code, message = _error_of(exc)
        return _fail(code, message)
    _save_last_call(record)
    return record


def _record_message(record):
    if record.get("ok") is True:
        return "事件已广播（plugin.emit）" if record.get("kind") == "emit" else "调用成功（plugin.call）"
    if record.get("ok") is False:
        return "调用失败：结构化错误见下方"
    return ""


def _communication_vars(record, message="", context=None):
    record = record if isinstance(record, dict) else {}
    events = _events()
    kind = _text(record.get("kind"), 16) or "-"
    ok = record.get("ok")
    if ok is True:
        status, status_class = "OK", "ok"
    elif ok is False:
        status, status_class = "Failed", "failed"
    else:
        status, status_class = "Idle", "idle"
    error = record.get("error") if isinstance(record.get("error"), dict) else {}
    route = _text(record.get("route"), 16) or "auto"
    delivery = "-"
    if kind == "emit":
        delivery = "delivered=%s failed=%s" % (_text(record.get("delivered", 0), 8),
                                               _text(record.get("failed_count", 0), 8))
    return {
        "call_status": status,
        "call_status_class": status_class,
        "error_code": _text(error.get("code"), 64) or "—",
        "error_message": _redact(error.get("message") or "") if error else "",
        "source": _text(record.get("source"), 96) or _plugin_id(context),
        "target": _text(record.get("target"), 96) or "（未指定）",
        "method": _text(record.get("method"), 96) or "（未指定）",
        "route": route,
        "request_id": _text(record.get("request_id"), 96) or NOT_ECHOED,
        "trace_id": _text(record.get("trace_id"), 96) or NOT_ECHOED,
        "kind": kind,
        "delivery": delivery,
        "called_at": _text(record.get("called_at"), 32) or "—",
        "request_json": _display(record.get("request"), "（尚未发起调用）"),
        "response_json": _display(record.get("response"), "（无响应体）"),
        "message": message,
        "form_action": _page_url("communication"),
        "form_target": _text(record.get("target"), 96) or _plugin_id(context),
        "form_method": _text(record.get("method"), 96) or "echo",
        "form_params": _text(record.get("params_text"), MAX_PARAMS_CHARS) or '{"text": "hello"}',
        "form_timeout": str(_int(record.get("timeout_ms"), DEFAULT_TIMEOUT_MS, MIN_TIMEOUT_MS,
                                 MAX_TIMEOUT_MS)),
        "route_auto_state": "is-selected" if route == "auto" else "is-unselected",
        "route_local_state": "is-selected" if route == "local" else "is-unselected",
        "route_core_state": "is-selected" if route == "core" else "is-unselected",
        "event_count": str(len(events)),
        "events_json": _json_text(events, 900) if events else "（尚未收到事件）",
        "static_url": _static_url("style.css"),
        "asset_theme_url": _asset_url("theme.css"),
        "asset_info_url": _asset_url("info.json"),
        "asset_logo_url": _asset_url("logo.txt"),
        "index_url": _page_url("index"),
        "settings_url": _page_url("settings"),
        "communication_url": _page_url("communication"),
    }


def _communication_result(record, message="", context=None):
    """render="plugin" 的 communication 页：模板来自磁盘，变量由引擎 escape 后替换。"""
    template = _read_file("webui", "pages", "communication.html")
    if not template:
        return {"ok": False, "error": "communication.html 模板不可读（插件 webui/pages/ 内）"}
    return {"html": template, "vars": _communication_vars(record, message, context), "message": message}


# ---------------------------------------------------------------- 页面数据（index）

def _index_vars(message="", self_test=None):
    info = _plugin_info()
    events = _events()
    permissions = info.get("permissions")
    last = _last_call()
    if isinstance(last, dict) and last:
        summary = "%s %s → %s:%s（route=%s）" % (
            _text(last.get("called_at"), 32), _text(last.get("kind"), 16),
            _text(last.get("target"), 96), _text(last.get("method"), 96),
            _text(last.get("route"), 16))
        if last.get("ok") is False:
            summary += "（失败）"
    else:
        summary = "（尚未发起跨插件调用）"
    return {
        "plugin_id": str(info.get("plugin_id") or ""),
        "plugin_name": str(info.get("name") or ""),
        "plugin_version": str(info.get("version") or PLUGIN_VERSION),
        "runtime": str(info.get("runtime") or "python"),
        "status": "running",
        "sdk_version": SDK_VERSION,
        "api_version": str(info.get("protocol_version") or "1"),
        "permissions": ", ".join(sorted(_text(item, 64) for item in permissions)) if isinstance(permissions, list) else "",
        "server_time": _now(),
        "call_summary": summary,
        "event_count": str(len(events)),
        "self_test_json": _json_text(self_test, 900) if self_test is not None else "（尚未运行自检）",
        "echo_text": "hello",
        "message": message,
        "index_url": _page_url("index"),
        "settings_url": _page_url("settings"),
        "communication_url": _page_url("communication"),
        "asset_theme_url": _asset_url("theme.css"),
        "asset_info_url": _asset_url("info.json"),
        "asset_logo_url": _asset_url("logo.txt"),
        "static_url": _static_url("style.css"),
    }


# ---------------------------------------------------------------- WebUI 协议钩子

def webui_page(page_id, action, params, values):
    """HTML 文件页的模板变量钩子（manifest web_ui.entry）：GET 与「未声明 webui.action」的 POST 都走这里。"""
    page_id = _text(page_id, 32)
    action = _text(action, 32) or "get"
    values = values if isinstance(values, dict) else {}
    if page_id == "settings":
        if action in ("save", "submit"):
            settings, problems = _save_settings(values)
            message = "设置已保存" if not problems else "保存遇到问题：" + "；".join(problems)
            return {"vars": _settings_vars(settings, message), "message": message}
        return {"vars": _settings_vars(), "message": ""}
    if page_id == "index":
        self_test = _self_test(action, values) if action in ("get_info", "echo", "set_config") else None
        message = "自检动作 %s 已执行" % action if self_test is not None else ""
        return {"vars": _index_vars(message, self_test), "message": message}
    return {"vars": {}, "message": ""}


def webui_render(page, context):
    """webui.page：render="plugin" 的 communication 页（最近一次调用的详情 + 表单）。"""
    page_id = _page_id(page)
    if page_id != "communication":
        return {"ok": False, "error": "本插件只有 communication 页由插件渲染（收到 %r）" % page_id}
    return _communication_result(_last_call(), "", context)


def webui_action(page, action, form, context):
    """webui.action：表单提交（call / emit / save / 自检三动作）。"""
    page_id = _page_id(page)
    action = _text(action, 32)
    form = form if isinstance(form, dict) else {}
    if action == "save":
        settings, problems = _save_settings(form)
        message = "设置已保存" if not problems else "保存遇到问题：" + "；".join(problems)
        return {"ok": True, "vars": _settings_vars(settings, message), "message": message}
    if action in ("call", "emit"):
        record = _run_comm(action, form, context)
        return _communication_result(record, _record_message(record), context)
    if page_id == "index" and action in ("get_info", "echo", "set_config"):
        message = "自检动作 %s 已执行" % action
        return {"ok": True, "vars": _index_vars(message, _self_test(action, form)), "message": message}
    return {"ok": False, "error": "未知动作: %s" % (action or "(空)")}


def webui_asset(path):
    """webui.asset：webui/static 之外的动态资源（CSS 生成 / JSON / assets 目录里的文件）。"""
    rel = _text(path, 96).strip()
    if rel == "theme.css":
        settings = _load_settings()
        accent = {"auto": "#5b8def", "manual": "#2f9e44", "debug": "#e8590c"}.get(settings["mode"], "#5b8def")
        body = ("/* webui.asset 动态生成：随 settings.mode 变化（服务端还会再净化一次 CSS） */\n"
                ".flowerie-plugin-webui .lead { color: %s; }\n"
                ".flowerie-plugin-webui .status.ok { color: #2f9e44; }\n"
                ".flowerie-plugin-webui .status.failed { color: #c92a2a; }\n"
                ".flowerie-plugin-webui .status.idle { color: #868e96; }\n" % accent)
        return {"content_type": "text/css", "body": body}
    if rel == "info.json":
        payload = json.dumps(_info_payload(), ensure_ascii=False, indent=2, sort_keys=True)
        return {"content_type": "application/json",
                "base64": base64.b64encode(payload.encode("utf-8")).decode("ascii")}
    if rel == "logo.txt":
        body = _read_file("webui", "assets", "logo.txt")
        if body:
            return {"content_type": "text/plain", "body": body}
    return {"ok": False, "error": "资源不存在: %s" % (rel or "(空)")}


# ---------------------------------------------------------------- 生命周期

def on_startup(context=None, api=None):
    """握手后调用：注入 API、暴露被调方法、订阅事件（异常会阻止插件启动，所以这里自己兜住）。"""
    _API["api"] = api
    if isinstance(context, dict) and context.get("plugin_id"):
        _API["plugin_id"] = _text(context.get("plugin_id"), 64)
    if api is None:
        return None
    try:
        api.plugin.expose("get_info", lambda _request=None: _info_payload())
        api.plugin.expose("echo", _echo_payload)
        api.plugin.expose("set_config", lambda request=None: _set_config_payload(
            (request or {}).get("params") if isinstance(request, dict) else None))
        api.plugin.expose("ping", lambda _request=None: {"pong": True, "plugin_id": _plugin_id(),
                                                         "time": _now()})
        api.plugin.expose("slow", _slow_handler)
        api.plugin.expose("boom", _boom_handler)
        api.plugin.on("*", _on_event)
    except Exception as exc:
        _log("error", "on_startup 注册失败：%s" % type(exc).__name__)
    _log("info", "plugin_webui_test 已启动：三页 WebUI；被调方法 get_info/echo/set_config/ping/slow/boom；订阅全部事件")
    return None


def health_check(event=None):
    """引擎 health 方法：插件自述状态。"""
    return {"ok": True, "status": "running", "plugin_id": _plugin_id(), "time": _now()}


def on_shutdown(context=None, api=None):
    _log("info", "plugin_webui_test 已停止")
    return None
