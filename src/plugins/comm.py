"""Plugin-to-Plugin 通信模型（任务书《通信》§五–§二十三）：语言无关的单一事实来源。

任务书要求「插件是什么语言写的，不应该改变 Plugin API 的语义」。要做到这一点，跨语言
通信就必须有一份**可执行的形式化定义**——消息形状、数据类型、错误码、循环保护、路由
策略——由引擎与五种语言的 SDK 共同实现。文档写一套、各语言各写一套是这类系统最常见的
失败模式，本模块就是那份"唯一的一份"。

分层（§二十七 最终架构）：

    Flowerie Core
        Plugin Communication Bus        <- src/plugins/router.py（投递/超时/取消/事件广播）
        Core Router / Permission        <- 本模块的模型 + router.py 的注册表与权限门
        Python / TS / Go / Rust / Java Runtime

五类消息**必须区分**（§十）：CALL / RESPONSE / EVENT / ERROR / CANCEL。
它们映射到既有的 JSON-Lines 线格式（不新造第二套通道，§二十五 同理）：

    CALL      {"id":N,"method":"plugin.call",  "params":{request}}
    EVENT     {"id":N,"method":"plugin.event", "params":{event}}
    CANCEL    {"id":N,"method":"plugin.cancel","params":{"request_id":...,"reason":...}}
    RESPONSE  {"id":N,"result":{"ok":true,"result":<any>}}
    ERROR     {"id":N,"result":{"ok":false,"error":{"code","message","data"}}}
              （协议级错误行 {"id":N,"error":"..."} 仍存在，但只表示"这一行不是合法请求"）

反向通道（插件 -> 引擎）沿用 Plugin Protocol v1 的 engine op：

    {"id":N,"method":"engine","params":{"op":"plugin.call","args":{request}}}
    {"id":N,"method":"engine","params":{"op":"plugin.emit","args":{event}}}
    {"id":N,"method":"engine","params":{"op":"plugin.cancel","args":{"request_id":...}}}

安全不变式：
1. 插件**从不**自报身份：source 由引擎按连接（进程）填写，杜绝身份伪造；
2. 跨语言一律经 Core Router（§十二），SDK 无法私自建 TCP/HTTP 旁路；
3. 每次调用都过权限门（§十四/§十五），同语言直连也一样；
4. 传递的只能是语言无关类型（§十九）；语言内部对象在边界处被**拒绝**而不是被悄悄序列化；
5. 调用链带 trace_id / call_id / hop_count，超 hop 立刻 PLUGIN_CALL_LOOP（§二十二）。
"""
import base64
import binascii
import json
import math
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from src.plugins.protocol import PLUGIN_METHODS, PROTOCOL_VERSION

#: 五类消息（§十）：RPC 与 Event 分开，不得混成一种机制
MESSAGE_KINDS = ("CALL", "RESPONSE", "EVENT", "ERROR", "CANCEL")

#: 插件 -> 引擎 的反向 op（插件只能通过 Core 发起；§十二 不许旁路）。
#: 与引擎 -> 插件 的协议方法名一一对应（发起侧叫 emit，被调侧叫 event）—— 顺序对齐，
#: 由 protocol.PLUGIN_METHODS 提供被调侧名字，杜绝两处各写一份方法名。
PLUGIN_OPS = ("plugin.call", "plugin.emit", "plugin.cancel")
PLUGIN_OP_TO_METHOD = dict(zip(PLUGIN_OPS, PLUGIN_METHODS))
#: 能力分组名（SDK 的 initialize 里可写组名或方法名，两种等价）
PLUGIN_CAPABILITY_GROUP = "plugin"

#: 路由策略（§十一/§十三）：默认 AUTO；测试用 CORE 验证统一协议路径
ROUTE_AUTO = "auto"
ROUTE_CORE = "core"
ROUTE_LOCAL = "local"
ROUTE_POLICIES = (ROUTE_AUTO, ROUTE_CORE, ROUTE_LOCAL)

#: 循环保护（§二十二）：调用链最大跳数，超过即 PLUGIN_CALL_LOOP
MAX_HOP_COUNT = 8

#: 默认/最大超时（毫秒，§十八）
DEFAULT_TIMEOUT_MS = 5000
MAX_TIMEOUT_MS = 60000

#: §二十一 的十个错误码（跨语言 SDK 必须都能映射成各自语言的异常/Result）
CORE_ERROR_CODES = (
    "PLUGIN_NOT_FOUND",
    "PLUGIN_NOT_READY",
    "METHOD_NOT_FOUND",
    "PERMISSION_DENIED",
    "INVALID_ARGUMENT",
    "TIMEOUT",
    "CANCELLED",
    "SERIALIZATION_ERROR",
    "PLUGIN_ERROR",
    "INTERNAL_ERROR",
)
#: §十七 生命周期要求的第十一个码（目标插件崩溃/不可用）
LIFECYCLE_ERROR_CODE = "PLUGIN_UNAVAILABLE"
#: §二十二 循环调用保护要求的第十二个码
LOOP_ERROR_CODE = "PLUGIN_CALL_LOOP"
#: 全部错误码（十核心 + 生命周期 + 循环）
ERROR_CODES = CORE_ERROR_CODES + (LIFECYCLE_ERROR_CODE, LOOP_ERROR_CODE)

#: 生命周期状态（§十七）
LIFECYCLE_STATES = ("STARTING", "READY", "STOPPING", "STOPPED", "FAILED")

#: 语言无关数据类型（§十九）
DATA_TYPES = ("null", "boolean", "integer", "number", "string", "array", "object", "bytes")
#: 二进制引用（§十九）：JSON 里不能放裸字节，统一用这个形状
BYTES_REF_KEY = "$bytes"
BYTES_MAX = 4 * 1024 * 1024

#: 复杂对象的归一化类型（§二十）
DTO_KINDS = ("message", "user", "group", "file", "image", "event", "context", "segment", "result")
#: 每种 DTO 的字段表（引擎/各语言 SDK 用同一份字段名，保证 Python->Go 与 TS->Java 一致）
DTO_FIELDS: Dict[str, Tuple[str, ...]] = {
    "message": ("message_id", "group_id", "user_id", "sender", "segments", "text", "time"),
    "user": ("user_id", "nickname", "card", "role", "is_bot"),
    "group": ("group_id", "name", "member_count", "max_member_count"),
    "file": ("file_id", "name", "size", "url", "ref", "mime"),
    "image": ("file_id", "url", "width", "height", "ref", "mime"),
    "segment": ("type", "data"),
    "event": ("name", "payload", "trace_id", "hop_count"),
    "context": ("plugin_id", "runtime", "instance_id", "trace_id", "request_id"),
    "result": ("ok", "value", "error"),
}

PLUGIN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
METHOD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,95}$")
PERMISSION_TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class PluginCommError(Exception):
    """结构化通信错误（§二十一）：跨语言边界上唯一的错误形状。

    SDK 负责把它转换成各自语言的异常/Result；引擎负责保证**任何**失败路径都产出它，
    而不是让一个裸异常变成对面语言里的一句 INTERNAL_ERROR。
    """

    def __init__(self, code: str, message: str, data: Optional[Dict[str, Any]] = None):
        self.code = code if code in ERROR_CODES else "INTERNAL_ERROR"
        self.message = str(message or "")
        self.data: Dict[str, Any] = dict(data or {})
        super().__init__("%s: %s" % (self.code, self.message))

    def to_error(self) -> Dict[str, Any]:
        """-> 响应模型里的 error 段（§七）。"""
        return {"code": self.code, "message": self.message, "data": dict(self.data)}

    def to_response(self, request_id: str) -> Dict[str, Any]:
        return make_error_response(request_id, self)

    @classmethod
    def from_error(cls, raw: Any, fallback_code: str = "PLUGIN_ERROR") -> "PluginCommError":
        """从任意形状恢复（对面语言可能只回了一句字符串）——绝不抛，永远有码。"""
        if isinstance(raw, PluginCommError):
            return raw
        if isinstance(raw, dict):
            code = str(raw.get("code") or fallback_code)
            data = raw.get("data")
            return cls(code, str(raw.get("message") or raw.get("error") or code),
                       data if isinstance(data, dict) else None)
        return cls(fallback_code, str(raw or fallback_code))

    @classmethod
    def not_found(cls, plugin_id: str, instance_id: str = "") -> "PluginCommError":
        return cls("PLUGIN_NOT_FOUND", "目标插件不存在: %s" % plugin_id,
                   {"plugin_id": plugin_id, "instance_id": instance_id})

    @classmethod
    def not_ready(cls, plugin_id: str, state: str) -> "PluginCommError":
        return cls("PLUGIN_NOT_READY", "目标插件未就绪: %s (%s)" % (plugin_id, state),
                   {"plugin_id": plugin_id, "state": state})

    @classmethod
    def unavailable(cls, plugin_id: str, state: str) -> "PluginCommError":
        return cls(LIFECYCLE_ERROR_CODE, "目标插件不可用: %s (%s)" % (plugin_id, state),
                   {"plugin_id": plugin_id, "state": state})

    @classmethod
    def denied(cls, target: str, method: str,
               granted: Optional[List[str]] = None) -> "PluginCommError":
        return cls("PERMISSION_DENIED", "缺少调用权限 plugin.call.%s" % target,
                   {"target": target, "method": method,
                    "required": call_permissions(target, method),
                    "granted": sorted(granted or [])})

    @classmethod
    def method_not_found(cls, plugin_id: str, method: str) -> "PluginCommError":
        return cls("METHOD_NOT_FOUND", "目标插件未暴露方法: %s" % method,
                   {"plugin_id": plugin_id, "method": method})

    @classmethod
    def timeout(cls, target: str, method: str, timeout_ms: int) -> "PluginCommError":
        return cls("TIMEOUT", "调用 %s.%s 超过 %dms" % (target, method, timeout_ms),
                   {"target": target, "method": method, "timeout_ms": timeout_ms})

    @classmethod
    def loop(cls, hop_count: int, trace_id: str) -> "PluginCommError":
        return cls(LOOP_ERROR_CODE,
                   "调用链超过最大跳数 %d（hop_count=%s）" % (MAX_HOP_COUNT, hop_count),
                   {"hop_count": hop_count, "max_hop": MAX_HOP_COUNT, "trace_id": trace_id})

    @classmethod
    def invalid(cls, message: str, data: Optional[Dict[str, Any]] = None) -> "PluginCommError":
        return cls("INVALID_ARGUMENT", message, data)

    @classmethod
    def serialization(cls, message: str, data: Optional[Dict[str, Any]] = None) -> "PluginCommError":
        return cls("SERIALIZATION_ERROR", message, data)

    @classmethod
    def internal(cls, message: str, data: Optional[Dict[str, Any]] = None) -> "PluginCommError":
        return cls("INTERNAL_ERROR", message, data)


# ===================== §十九 数据类型 =====================

def value_type(value: Any) -> str:
    """值的语言无关类型名。语言内部对象返回 type(value).__name__（不属于 DATA_TYPES）。"""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "bytes"
    if isinstance(value, (list, tuple, set, frozenset)):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def is_bytes_ref(value: Any) -> bool:
    return (isinstance(value, dict) and BYTES_REF_KEY in value
            and isinstance(value.get(BYTES_REF_KEY), str))


def bytes_ref(data: Any, mime: str = "") -> Dict[str, Any]:
    """二进制 -> 语言无关引用（§十九 bytes / binary reference）。"""
    raw = bytes(data)
    if len(raw) > BYTES_MAX:
        raise PluginCommError.serialization(
            "二进制数据超过上限 %d 字节" % BYTES_MAX, {"size": len(raw), "max": BYTES_MAX})
    ref: Dict[str, Any] = {BYTES_REF_KEY: base64.b64encode(raw).decode("ascii"), "size": len(raw)}
    if mime:
        ref["mime"] = str(mime)
    return ref


def decode_bytes_ref(ref: Any) -> bytes:
    """引用 -> 二进制；形状非法一律 SERIALIZATION_ERROR（不猜）。"""
    if not is_bytes_ref(ref):
        raise PluginCommError.serialization("不是合法的二进制引用（需要 $bytes 字段）")
    try:
        return base64.b64decode(str(ref[BYTES_REF_KEY]), validate=True)
    except (binascii.Error, ValueError):
        raise PluginCommError.serialization("二进制引用不是合法 base64") from None


def sanitize_value(value: Any, depth: int = 0) -> Any:
    """把值归一成可跨语言传输的形状；遇到语言内部对象 -> SERIALIZATION_ERROR。

    - bytes/bytearray/memoryview -> {"$bytes": base64, "size": N}
    - tuple/set/frozenset -> list
    - dict 的键必须是字符串（Python 允许 int 键，Java/Go 不允许 —— 在这里就拦下来）
    - 其它自定义类型（插件自己的类实例）-> 拒绝，而不是 json.dumps(default=str) 悄悄变字符串
    """
    if depth > 32:
        raise PluginCommError.serialization("嵌套层级过深（>32）")
    kind = value_type(value)
    if kind in ("null", "boolean", "integer", "string"):
        return value
    if kind == "bytes":
        return bytes_ref(value)
    if kind == "number":
        num = float(value)
        if math.isnan(num) or math.isinf(num):
            raise PluginCommError.serialization("NaN/Infinity 不能跨语言传输（JSON 无此类型）")
        return num
    if kind == "array":
        return [sanitize_value(v, depth + 1) for v in value]
    if kind == "object":
        out: Dict[str, Any] = {}
        for key, val in value.items():
            if not isinstance(key, str):
                raise PluginCommError.serialization(
                    "对象键必须是字符串（收到 %s）" % type(key).__name__, {"key": repr(key)[:80]})
            out[key] = sanitize_value(val, depth + 1)
        return out
    raise PluginCommError.serialization(
        "语言内部对象不能跨插件边界: %s（§十九 只允许 %s）" % (kind, "/".join(DATA_TYPES)),
        {"actual_type": kind})


def validate_value(value: Any) -> Optional[PluginCommError]:
    """只检查、不转换；返回 None 表示合法。"""
    try:
        sanitize_value(value)
    except PluginCommError as e:
        return e
    return None


# ===================== §二十 复杂对象的 Normalized DTO =====================

def dto(kind: str, **fields: Any) -> Dict[str, Any]:
    """构造归一化 DTO：{"type": kind, ...字段}。未知字段一律拒绝（防两种语言各写一套）。"""
    if kind not in DTO_KINDS:
        raise PluginCommError.invalid("未知 DTO 类型: %r（允许：%s）" % (kind, list(DTO_KINDS)))
    allowed = DTO_FIELDS[kind]
    unknown = [k for k in fields if k not in allowed]
    if unknown:
        raise PluginCommError.invalid("DTO %s 不认识的字段: %s" % (kind, sorted(unknown)),
                                      {"allowed": list(allowed)})
    out: Dict[str, Any] = {"type": kind}
    for key in allowed:
        if key in fields:
            out[key] = sanitize_value(fields[key])
    return out


def to_dto(kind: str, obj: Any) -> Dict[str, Any]:
    """任意对象 -> Normalized DTO：**只取 DTO_FIELDS 里声明的字段**（鸭子类型）。

    这是引擎侧（Message/User/Group 等内部对象）与跨语言边界之间唯一的桥：
    内部对象永远不会被直接送出去，插件也永远拿不到对方语言的类实例。
    """
    if kind not in DTO_KINDS:
        raise PluginCommError.invalid("未知 DTO 类型: %r" % (kind,))
    if obj is None:
        return {"type": kind}
    if isinstance(obj, dict):
        return dto(kind, **{k: v for k, v in obj.items() if k in DTO_FIELDS[kind]})
    fields: Dict[str, Any] = {}
    for key in DTO_FIELDS[kind]:
        if hasattr(obj, key):
            fields[key] = getattr(obj, key)
    if not fields:
        raise PluginCommError.serialization(
            "无法把 %s 归一成 %s DTO（没有任何已知字段）" % (type(obj).__name__, kind),
            {"actual_type": type(obj).__name__})
    return dto(kind, **fields)


def is_dto(value: Any, kind: str = "") -> bool:
    if not isinstance(value, dict) or value.get("type") not in DTO_KINDS:
        return False
    return (not kind) or value.get("type") == kind


# ===================== Trace / 循环保护（§二十二/§二十三） =====================

def new_trace_id() -> str:
    """优先复用 Flowerie 既有的 trace 上下文（src/utils/trace.py），没有则新生成。

    任务书 §二十三 要求与既有 Trace 系统整合 —— 所以这里**不另造**一套 trace id 空间。
    """
    try:
        from src.utils.trace import get_trace_id
        current = str(get_trace_id() or "")
        if current:
            return current
    except Exception:  # noqa: BLE001 - trace 模块不可用时退化为新 id，不阻断通信
        pass
    return uuid.uuid4().hex


def new_call_id() -> str:
    return uuid.uuid4().hex


def hop_exceeded(hop_count: Any) -> bool:
    try:
        return int(hop_count) >= MAX_HOP_COUNT
    except (TypeError, ValueError):
        return False


def next_hop(hop_count: Any) -> int:
    try:
        return int(hop_count) + 1
    except (TypeError, ValueError):
        return 1


# ===================== 身份与目标（§四/§十六） =====================

def format_instance_id(plugin_id: str, instance_id: str = "") -> str:
    """实例的全名：plugin.a + instance1 -> "plugin.a#instance1"。"""
    return "%s#%s" % (plugin_id, instance_id) if instance_id else str(plugin_id)


def split_instance_id(spec: str) -> Tuple[str, str]:
    """把 "plugin.a#instance1" 拆成 (plugin_id, instance_id)；无 # 时 instance_id 为空。"""
    text = str(spec or "").strip()
    if "#" in text:
        plugin_id, _, instance_id = text.partition("#")
        return plugin_id.strip(), instance_id.strip()
    return text, ""


def parse_target(spec: Any) -> Tuple[str, str]:
    """目标解析：字符串（plugin_id / plugin_id#instance）/ 对象 {plugin_id, instance_id}。

    返回 (plugin_id, instance_id)；instance_id 为空表示「任意健康实例」（§十六）。
    """
    if isinstance(spec, dict):
        plugin_id = str(spec.get("plugin_id") or spec.get("id") or "").strip()
        instance_id = str(spec.get("instance_id") or "").strip()
        if not instance_id and "#" in plugin_id:
            plugin_id, instance_id = split_instance_id(plugin_id)
        return plugin_id, instance_id
    return split_instance_id(str(spec or ""))


def valid_plugin_id(plugin_id: str) -> bool:
    return bool(PLUGIN_ID_RE.match(str(plugin_id or "")))


def valid_method(method: str) -> bool:
    return bool(METHOD_RE.match(str(method or "")))


def valid_permission_target(target: str) -> bool:
    return bool(PERMISSION_TARGET_RE.match(str(target or "")))


def call_permissions(target: str, method: str = "") -> List[str]:
    """一次调用可接受的授权串，从细到粗（§十四）。

    plugin.call.weather.get_status  >  plugin.call.weather  >  plugin.call.*  >  plugin.call
    """
    plugin_id, _instance = parse_target(target)
    out: List[str] = []
    if plugin_id and method:
        out.append("plugin.call.%s.%s" % (plugin_id, method))
    if plugin_id:
        out.append("plugin.call.%s" % plugin_id)
    out.extend(["plugin.call.*", "plugin.call"])
    return out


def normalize_timeout_ms(value: Any, default: int = DEFAULT_TIMEOUT_MS) -> int:
    """超时归一：非法值 -> 默认值；超上限 -> 上限（宁可有界，也不无限等待）。"""
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return int(default)
    if ms <= 0:
        return int(default)
    return min(ms, MAX_TIMEOUT_MS)


# ===================== §六/§七 消息构造 =====================

def make_identity(plugin_id: str, runtime: str, version: str = "",
                  protocol_version: str = PROTOCOL_VERSION,
                  instance_id: str = "") -> Dict[str, Any]:
    """§四 Plugin Identity：plugin_id / runtime / version / protocol_version / instance_id。"""
    return {
        "plugin_id": str(plugin_id or ""),
        "runtime": str(runtime or ""),
        "version": str(version or ""),
        "protocol_version": str(protocol_version or PROTOCOL_VERSION),
        "instance_id": str(instance_id or ""),
    }


def make_request(target: Any, method: str, params: Any = None, *,
                 source: Optional[Any] = None,
                 timeout_ms: Any = DEFAULT_TIMEOUT_MS,
                 trace_id: str = "",
                 call_id: str = "",
                 hop_count: int = 0,
                 request_id: str = "",
                 route: str = ROUTE_AUTO,
                 metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """§六 请求模型（内部统一表示，五种语言 SDK 产出完全相同的形状）。"""
    plugin_id, instance_id = parse_target(target)
    if isinstance(source, dict):
        source_obj: Dict[str, Any] = {"plugin_id": str(source.get("plugin_id") or ""),
                                      "runtime": str(source.get("runtime") or "")}
        if source.get("instance_id"):
            source_obj["instance_id"] = str(source["instance_id"])
    elif source:
        src_pid, src_iid = parse_target(source)
        source_obj = {"plugin_id": src_pid, "runtime": ""}
        if src_iid:
            source_obj["instance_id"] = src_iid
    else:
        source_obj = {"plugin_id": "", "runtime": ""}
    target_obj: Dict[str, Any] = {"plugin_id": plugin_id, "runtime": ""}
    if instance_id:
        target_obj["instance_id"] = instance_id
    return {
        "request_id": str(request_id or new_call_id()),
        "source": source_obj,
        "target": target_obj,
        "method": str(method or ""),
        "params": sanitize_value(params if params is not None else {}),
        "timeout": normalize_timeout_ms(timeout_ms),
        "trace_id": str(trace_id or new_trace_id()),
        "call_id": str(call_id or new_call_id()),
        "hop_count": int(hop_count or 0),
        "route": route if route in ROUTE_POLICIES else ROUTE_AUTO,
        "metadata": sanitize_value(metadata or {}),
    }


def validate_request(req: Any) -> Optional[PluginCommError]:
    """§六 请求模型校验：**必须支持** request_id/source/target/method/params/timeout/metadata。"""
    if not isinstance(req, dict):
        return PluginCommError.invalid("request 必须是对象")
    for key in ("request_id", "source", "target", "method", "params", "timeout", "metadata"):
        if key not in req:
            return PluginCommError.invalid("request 缺少必需字段: %s" % key, {"request": _brief(req)})
    plugin_id, _instance = parse_target(req.get("target"))
    if not valid_plugin_id(plugin_id):
        return PluginCommError.invalid("target.plugin_id 非法: %r" % (plugin_id,),
                                       {"plugin_id": plugin_id})
    method = str(req.get("method") or "")
    if not valid_method(method):
        return PluginCommError.invalid("method 非法: %r" % (method,), {"method": method})
    if not isinstance(req.get("params"), (dict, list)):
        return PluginCommError.invalid("params 必须是对象或数组")
    if not isinstance(req.get("metadata"), dict):
        return PluginCommError.invalid("metadata 必须是对象")
    return validate_value(req.get("params"))


def make_response(request_id: str, result: Any = None) -> Dict[str, Any]:
    """§七 成功响应。"""
    return {"request_id": str(request_id), "ok": True, "result": sanitize_value(result)}


def make_error_response(request_id: str, error: Any) -> Dict[str, Any]:
    """§七 失败响应（error 永远是 {code,message,data} 三件套）。"""
    return {"request_id": str(request_id), "ok": False,
            "error": PluginCommError.from_error(error).to_error()}


def make_event(name: str, payload: Any = None, *, source: Optional[Dict[str, Any]] = None,
               trace_id: str = "", event_id: str = "", hop_count: int = 0,
               metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """§九 事件模型：广播用，不是 RPC（没有 request_id/response）。"""
    if not valid_method(name):
        raise PluginCommError.invalid("事件名非法: %r" % (name,))
    src = source if isinstance(source, dict) else {}
    return {
        "event_id": str(event_id or new_call_id()),
        "name": str(name),
        "payload": sanitize_value(payload if payload is not None else {}),
        "source": {"plugin_id": str(src.get("plugin_id") or ""),
                   "runtime": str(src.get("runtime") or "")},
        "trace_id": str(trace_id or new_trace_id()),
        "hop_count": int(hop_count or 0),
        "metadata": sanitize_value(metadata or {}),
    }


def validate_event(ev: Any) -> Optional[PluginCommError]:
    if not isinstance(ev, dict):
        return PluginCommError.invalid("event 必须是对象")
    # source 故意**不要求**：它是引擎按连接填写的（插件自报无效，§四 安全不变式）
    for key in ("name", "payload"):
        if key not in ev:
            return PluginCommError.invalid("event 缺少必需字段: %s" % key)
    if not valid_method(str(ev.get("name") or "")):
        return PluginCommError.invalid("事件名非法: %r" % (ev.get("name"),))
    if not isinstance(ev.get("payload"), (dict, list)):
        return PluginCommError.invalid("payload 必须是对象或数组")
    return validate_value(ev.get("payload"))


def make_cancel(request_id: str, reason: str = "", *,
                source: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """§十八 CANCEL request_id：目标插件收到后应尽可能停止任务。"""
    src = source if isinstance(source, dict) else {}
    return {
        "kind": "CANCEL",
        "request_id": str(request_id),
        "reason": str(reason or "")[:200],
        "source": {"plugin_id": str(src.get("plugin_id") or ""),
                   "runtime": str(src.get("runtime") or "")},
        "trace_id": str(src.get("trace_id") or new_trace_id()),
    }


def classify_message(msg: Any) -> str:
    """线格式消息 -> 五类之一（§十 的机器可检验版本）。

    协议级错误行（{"id":N,"error":"..."}）也是 ERROR；无法分类 -> "UNKNOWN"。
    """
    if not isinstance(msg, dict):
        return "UNKNOWN"
    method = str(msg.get("method") or "")
    if method == "plugin.call":
        return "CALL"
    if method == "plugin.event":
        return "EVENT"
    if method == "plugin.cancel":
        return "CANCEL"
    if "error" in msg and "result" not in msg:
        return "ERROR"
    if "result" in msg:
        result = msg.get("result")
        if isinstance(result, dict) and result.get("ok") is False and "error" in result:
            return "ERROR"
        return "RESPONSE"
    return "UNKNOWN"


def _brief(obj: Any) -> Dict[str, Any]:
    """日志/错误里回显请求时的安全摘要（不泄露 params 内容，只给键名）。"""
    if not isinstance(obj, dict):
        return {"repr": repr(obj)[:120]}
    return {"keys": sorted(str(k) for k in obj.keys())[:16]}


def json_roundtrip(value: Any) -> Any:
    """模拟「跨语言边界」：序列化再反序列化。测试用它证明载荷确实是语言无关的。"""
    return json.loads(json.dumps(sanitize_value(value), ensure_ascii=False))

