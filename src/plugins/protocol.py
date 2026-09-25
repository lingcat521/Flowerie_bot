"""Plugin Protocol v1：语言无关插件协议的形式化定义（任务书第 2 份 §三/§十）。

为什么"形式化"而不是"新造一套"：仓库早就有一个能被任何语言实现的协议 ——
**JSON-Lines over stdio**（`src/plugins/runner/`），13 种语言的最小插件在 CI 里真编译真运行。
本模块把它的**线格式、方法集、错误模型、版本协商、能力握手**写成代码里的单一事实来源，
供引擎（`runtime.py` / `manager.py`）与各语言 SDK 共同引用，避免"文档一套、实现对一套"。

线格式（一行一个 JSON，UTF-8，写完立即 flush）：

    引擎 → 插件   {"id":1,"method":"initialize","params":{...}}
    插件 → 引擎   {"id":1,"result":{"ok":true,...}}
    插件 → 引擎   {"id":1,"error":"原因"}                 # 协议级错误（未知方法/参数非法）
    插件 → 引擎   {"id":1000001,"method":"engine","params":{"op":"config.get","args":{...}}}
    引擎 → 插件   {"id":1000001,"result":{"ok":true,...}}  # 反向通道（插件请求引擎）

方法分两类：
- **必需**（`REQUIRED_METHODS`）：initialize / event / health / shutdown —— 任何插件都要实现；
- **可选**（`OPTIONAL_METHODS` = 核心 + WebUI）：由插件在 initialize 的 `capabilities`
  里声明；**引擎不会调用未声明的方法**（能力矩阵因此不会撒谎）：
  * 核心：context.get / config.get / config.set / permission.check /
    storage.get / storage.set / storage.delete / storage.list；
  * WebUI Protocol（任务书第 3 份 §三）：webui.page / webui.action / webui.asset —— 页面、
    动作、资源三条通道，插件只声明内容，路由/权限/隔离/净化全部由引擎负责。

错误模型（两条通道，别混）：
- 协议级：`{"id":N,"error":"..."}` —— 未知方法、参数类型错、名字非法；
- 操作级：`{"id":N,"result":{"ok":false,"error":"..."}}` —— 方法认识但这次没成功（例如 key 不存在）。

安全不变式（引擎侧强制，插件无法绕过）：
1. 插件**从不**传 plugin_id —— 引擎按连接（进程）识别身份，杜绝身份伪造；
2. `permission.check` 只读查询**已批准**权限，插件无法自行提权；
3. `config.get` 返回操作员配置（只读）；`config.set` 只写**插件自己的覆盖层**，不碰全局配置；
4. `storage.*` 的 key 有严格格式与数量/大小上限，且只落在该插件自己的 data 目录；
5. 未知方法一律 `error`，不静默忽略（便于插件作者早发现拼写错误）。
"""
import json
import re
from typing import Any, Dict, List, Optional, Tuple

PROTOCOL_VERSION = "1"
API_VERSION = "1"

REQUIRED_METHODS = ("initialize", "event", "health", "shutdown")
#: 核心可选能力（任务书第 2 份 §三）
CORE_OPTIONAL_METHODS = (
    "context.get",
    "config.get",
    "config.set",
    "permission.check",
    "storage.get",
    "storage.set",
    "storage.delete",
    "storage.list",
)
#: WebUI Protocol（任务书第 3 份 §三）：插件声明能力后引擎才会调用
WEBUI_METHODS = ("webui.page", "webui.action", "webui.asset")
#: Plugin-to-Plugin 通信（任务书第 4 份 §十/§十六）：插件间 CALL / EVENT / CANCEL 三条方法。
#: 插件只有声明了这些能力，引擎才会把别的插件的调用投递进来（能力矩阵不撒谎）。
PLUGIN_METHODS = ("plugin.call", "plugin.event", "plugin.cancel")
#: 全部可选方法 = 核心 + WebUI + 插件间通信（能力握手比对的就是这个集合）
OPTIONAL_METHODS = CORE_OPTIONAL_METHODS + WEBUI_METHODS + PLUGIN_METHODS
#: 引擎内部方法（插件不实现，由引擎发起）：hook 供控制面调用插件函数
ENGINE_INTERNAL_METHODS = ("hook",)
#: 能力分组：SDK 与文档按组表述，协议按方法名表述（两者在此对齐，避免各写一份）
CAPABILITY_GROUPS = {
    "context": ("context.get",),
    "config": ("config.get", "config.set"),
    "permission": ("permission.check",),
    "storage": ("storage.get", "storage.set", "storage.delete", "storage.list"),
    "webui": WEBUI_METHODS,
    "plugin": PLUGIN_METHODS,
}

#: 插件 → 引擎 的反向 op（引擎按 op 分派；未知 op 一律拒绝）。
#: plugin.call / plugin.emit / plugin.cancel 是插件间通信的唯一发起路径（§十二 不许旁路）。
ENGINE_OPS = ("context.get", "config.get", "permission.check",
              "plugin.call", "plugin.emit", "plugin.cancel")

ACTION_ID_BASE = 1_000_000        # 插件 → 引擎 请求 id 偏移（与引擎请求 id 不共用命名空间）
STORAGE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_STORAGE_KEYS = 200
MAX_STORAGE_VALUE_BYTES = 64 * 1024
MAX_CONFIG_KEYS = 64
MAX_CONFIG_VALUE_BYTES = 8 * 1024


def all_methods() -> Tuple[str, ...]:
    return REQUIRED_METHODS + OPTIONAL_METHODS + ENGINE_INTERNAL_METHODS


def valid_storage_key(key: Any) -> bool:
    """存储键：字母数字开头，≤64，允许 . _ -；不允许斜杠、点段或隐藏段（防穿越）。"""
    return bool(STORAGE_KEY_RE.match(str(key or "")))


def valid_config_key(key: Any) -> bool:
    return bool(STORAGE_KEY_RE.match(str(key or "")))


def encode_line(obj: Dict[str, Any]) -> str:
    """编码一行协议消息（统一 ensure_ascii=False + 单行）。"""
    return json.dumps(obj, ensure_ascii=False).replace("\n", " ") + "\n"


def decode_line(raw: Any) -> Optional[Dict[str, Any]]:
    """解析一行协议消息；非 JSON / 非对象 → None（调用方跳过该行，不崩）。"""
    try:
        obj = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8", errors="replace"))
    except (ValueError, AttributeError):
        return None
    return obj if isinstance(obj, dict) else None


def normalize_capabilities(raw: Any) -> List[str]:
    """把插件声明的能力归一成**协议里存在的可选方法名**（未知项丢弃，不报错）。

    两种写法都接受，效果等价：
    - 方法名列表：`["config.get", "storage.set"]`
    - 能力分组（SDK 更常用）：`{"config": true, "storage": true}` → 展开成上面的方法名
    """
    if isinstance(raw, dict):
        raw = [k for k, v in raw.items() if v]
    if not isinstance(raw, (list, tuple)):
        return []
    out: List[str] = []
    for item in raw:
        name = str(item or "").strip()
        if name in OPTIONAL_METHODS:
            out.append(name)
        elif name in CAPABILITY_GROUPS:
            out.extend(CAPABILITY_GROUPS[name])
    seen = []
    for name in out:
        if name not in seen:
            seen.append(name)
    return sorted(seen)


def group_of(method: str) -> str:
    """方法名 → 能力分组（Capability Matrix 按分组统计时用）。"""
    for group, methods in CAPABILITY_GROUPS.items():
        if method in methods:
            return group
    return "core" if method in REQUIRED_METHODS else "unknown"


def negotiate_initialize(result: Any) -> Tuple[bool, str, List[str]]:
    """校验 initialize 的返回：返回 (ok, error, capabilities)。

    - 必须 `{"ok": true}`；
    - `protocol_version` 缺省视为 "1"（老插件只回 api_version）；
    - 主版本不同 → 拒绝启动（宁可明确失败，也不猜兼容）。
    """
    if not isinstance(result, dict):
        return False, "initialize 必须返回对象", []
    if not result.get("ok", False):
        return False, str(result.get("error") or "initialize 返回 ok=false"), []
    version = str(result.get("protocol_version") or PROTOCOL_VERSION)
    if version.split(".")[0] != PROTOCOL_VERSION.split(".")[0]:
        return False, "协议主版本不兼容：插件 %s / 引擎 %s" % (version, PROTOCOL_VERSION), []
    return True, "", normalize_capabilities(result.get("capabilities"))


def value_size(value: Any) -> int:
    """序列化后的字节数（用于存储/配置的大小上限）。"""
    try:
        return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        return MAX_STORAGE_VALUE_BYTES + 1
