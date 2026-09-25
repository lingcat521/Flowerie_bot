#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Plugin Python Runner v1：插件 API（Flowerie ↔ Python 插件，子进程隔离）。

用法（由 PluginRuntime 启动，不直接调用）::

    python3 -I python_runner.py --dir <plugin_dir> --entry plugin.py

协议（stdin/stdout JSON Lines，一行一条）：
- Flowerie → runner:
    {"id":1,"method":"initialize","params":{...}}
    {"id":2,"method":"event","params":{"event":"message","payload":{...}}}
    {"id":3,"method":"health"}
    {"id":4,"method":"shutdown"}
- runner → Flowerie:
    {"id":1,"result":{"ok":true}}
    {"id":2,"result":{"actions":[...]}}      # event 处理结果（插件返回的动作）
    {"id":N,"error":"..."}
- 插件 → Flowerie（运行期请求，同步等待响应）:
    {"id":99,"method":"action","params":{"action":"send_message","payload":{...}}}
    Flowerie 回复: {"id":99,"result":{...}}

插件契约（entry 导出的钩子，全部可省略，只在定义时调用）：
- on_startup(context) / on_shutdown(context)
- on_message(event) / on_group_message(event) / on_command(event)
- health_check(event=None)
钩子返回：None（无动作）| {"type": ..., ...}（单个动作）| [ {..}, .. ]（动作列表）
事件参数：event 为 dict；同时传第二个参数 api（可选）：api.send_message(payload) 等。

安全边界：本进程只读 stdin/stdout 与自己的插件目录；没有任何 Flowerie 内部
类可导入（独立进程 + python -I 隔离模式）。
"""
import argparse
import importlib.util
import inspect
import json
import os
import re
import sys
import traceback
from typing import Any, Dict, List, Optional

# ---------------- Plugin Protocol v1 常量（与 src/plugins/protocol.py 保持一致） ----------------
# runner 由 PluginRuntime 以 `python -I`（隔离模式）启动，sys.path 里没有仓库代码，
# 因此这里内联一份最小副本；tests/test_plugin_protocol.py 会逐项比对两份常量，防止悄悄漂移。
PROTOCOL_VERSION = "1"
#: 全部可选方法（**字面量**：tests/test_plugin_protocol.py 会用 ast 逐项比对引擎侧常量）
OPTIONAL_METHODS = (
    "context.get", "config.get", "config.set", "permission.check",
    "storage.get", "storage.set", "storage.delete", "storage.list",
    "webui.page", "webui.action", "webui.asset",
    "plugin.call", "plugin.event", "plugin.cancel",
)
#: 核心可选能力（前 8 项，任务书第 2 份）
CORE_OPTIONAL_METHODS = OPTIONAL_METHODS[:8]
#: WebUI Protocol 方法（第 9-11 项，任务书第 3 份 §三）：与其它语言 SDK 同名同义
WEBUI_METHODS = OPTIONAL_METHODS[8:11]
#: Plugin-to-Plugin 通信（第 12-14 项，任务书第 4 份 §十）：CALL / EVENT / CANCEL 三条方法
PLUGIN_METHODS = OPTIONAL_METHODS[11:14]
#: 五类消息必须区分（§十）：RPC 与 Event 不共用一套语义
MESSAGE_KINDS = ("CALL", "RESPONSE", "EVENT", "ERROR", "CANCEL")
#: 路由策略（§十三）：默认 AUTO；测试用 CORE 验证统一协议路径
ROUTE_POLICIES = ("auto", "core", "local")
#: 循环保护（§二十二）：调用链最大跳数
MAX_HOP_COUNT = 8
#: 结构化错误码（§二十一 十个 + §十七 生命周期 + §二十二 循环）
ERROR_CODES = (
    "PLUGIN_NOT_FOUND", "PLUGIN_NOT_READY", "METHOD_NOT_FOUND", "PERMISSION_DENIED",
    "INVALID_ARGUMENT", "TIMEOUT", "CANCELLED", "SERIALIZATION_ERROR", "PLUGIN_ERROR",
    "INTERNAL_ERROR", "PLUGIN_UNAVAILABLE", "PLUGIN_CALL_LOOP",
)
CAPABILITY_GROUPS = {
    "context": ("context.get",),
    "config": ("config.get", "config.set"),
    "permission": ("permission.check",),
    "storage": ("storage.get", "storage.set", "storage.delete", "storage.list"),
    "webui": ("webui.page", "webui.action", "webui.asset"),
    "plugin": ("plugin.call", "plugin.event", "plugin.cancel"),
}
STORAGE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_STORAGE_KEYS = 200
MAX_STORAGE_VALUE_BYTES = 64 * 1024
MAX_CONFIG_KEYS = 64
MAX_CONFIG_VALUE_BYTES = 8 * 1024


class PluginCommError(Exception):
    """插件间通信失败（任务书第 4 份 §二十一）：Python 侧的原生异常形态。

    引擎返回的永远是响应模型（跨语言没有异常这个东西）；SDK 负责把它转成本语言的异常。
    """

    def __init__(self, code: str, message: str, data=None):
        self.code = code if code in ERROR_CODES else "INTERNAL_ERROR"
        self.message = str(message or "")
        self.data = dict(data or {})
        super().__init__("%s: %s" % (self.code, self.message))


#: Normalized DTO 字段表（§二十）：与 src/plugins/comm.py 同源，tests 会逐项比对两份
DTO_FIELDS = {
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


def dto(kind: str, **fields):
    """构造 Normalized DTO（§二十）：跨插件传 Message/User/Group/... 用它，别传语言对象。"""
    if kind not in DTO_FIELDS:
        raise PluginCommError("INVALID_ARGUMENT", "未知 DTO 类型: %r" % (kind,))
    unknown = [k for k in fields if k not in DTO_FIELDS[kind]]
    if unknown:
        raise PluginCommError("INVALID_ARGUMENT",
                              "DTO %s 不认识的字段: %s" % (kind, sorted(unknown)))
    out = {"type": kind}
    for key in DTO_FIELDS[kind]:
        if key in fields:
            out[key] = fields[key]
    return out


class PluginCommApi:
    """统一抽象 plugin.call() / plugin.emit() / plugin.on()（§二十七，各语言语义一致）。

    插件作者不需要知道实际走的是 LOCAL 还是 CORE_ROUTED（§十一）：route 只是**策略**，
    引擎侧目前一律经 Core Router（跨语言必须经 Core，§十二）。
    """

    def __init__(self, runner):
        self._runner = runner

    # ---- RPC（§五/§六/§七/§八） ----
    def call(self, target: str, method: str, params=None, timeout: int = 5000,
             route: str = "auto"):
        """调用其它插件；成功返回 result，失败抛 PluginCommError（结构化错误码）。"""
        if self._runner is None:
            raise PluginCommError("INTERNAL_ERROR", "runner 未注入（插件 API 不可用）")
        return self._runner.comm_call(target, method, params, timeout, route)

    async def acall(self, target: str, method: str, params=None, timeout: int = 5000,
                    route: str = "auto"):
        """异步写法（§八）：语义与 call() 完全一致（runner 是单线程循环，内部同步执行）。"""
        return self.call(target, method, params, timeout, route)

    def cancel(self, request_id: str, reason: str = ""):
        """取消自己发起的一次调用（§十八）；目标插件收到 CANCEL 后应尽可能停止。"""
        if self._runner is None:
            raise PluginCommError("INTERNAL_ERROR", "runner 未注入")
        return self._runner.comm_cancel(request_id, reason)

    def is_cancelled(self, request_id: str) -> bool:
        """该请求是否已被调用方取消（§十八）：长任务在步骤之间查一下，能停就停。

        诚实说明：Python runner 是单线程的，**阻塞中的 handler 无法被立刻打断** ——
        CANCEL 会在 handler 返回后才被处理。所以这是"尽可能停止"而不是"强制中断"。
        """
        if self._runner is None:
            return False
        return str(request_id or "") in self._runner._cancelled

    def cancelled_requests(self):
        """已收到的 CANCEL 请求 id 列表（有界；供插件自查与测试断言）。"""
        if self._runner is None:
            return []
        return sorted(self._runner._cancelled)

    # ---- Event（§九） ----
    def emit(self, name: str, payload=None):
        """广播事件给所有订阅者（需要 plugin.emit 权限）；返回 {ok, delivered, failed}。"""
        if self._runner is None:
            raise PluginCommError("INTERNAL_ERROR", "runner 未注入")
        return self._runner.comm_emit(name, payload)

    def on(self, event: str, handler):
        """订阅事件（§九）。event 传 "*" 表示订阅全部。"""
        if self._runner is None:
            raise PluginCommError("INTERNAL_ERROR", "runner 未注入")
        return self._runner.register_event_handler(event, handler)

    # ---- 作为被调方 ----
    def expose(self, method: str, handler):
        """暴露一个可被其它插件调用的方法（§五 CALL 的被调方）。"""
        if self._runner is None:
            raise PluginCommError("INTERNAL_ERROR", "runner 未注入")
        return self._runner.register_handler(method, handler)


class PluginApi:
    """同步插件 API：每个方法向 Flowerie 发 action 请求并等待响应（阻塞读取 stdin）。"""

    def __init__(self, send_action, plugin_id: str, runner=None):
        self._send_action = send_action
        self.plugin_id = plugin_id
        #: 与其它语言 SDK 对齐的 API（storage/config/permission/context）需要 runner 的本地实现
        self._runner = runner
        #: 统一抽象 plugin.call() / plugin.emit() / plugin.on()（§二十七）
        self.plugin = PluginCommApi(runner)

    # ---------- Plugin Protocol v1：与其它语言 SDK 对齐的 API ----------
    def storage_get(self, key: str) -> Any:
        """读取本插件存储（与 TypeScript/Go/Rust/Java 的 ctx.storageGet 同名同义）。"""
        return (self._runner._storage_get(key) or {}).get("value")

    def storage_set(self, key: str, value: Any) -> Dict[str, Any]:
        return self._runner._storage_set(key, value)

    def storage_delete(self, key: str) -> Dict[str, Any]:
        return self._runner._storage_delete(key)

    def storage_list(self, prefix: str = "") -> Any:
        return (self._runner._storage_list(prefix) or {}).get("keys") or []

    def config_get(self, keys=None) -> Dict[str, Any]:
        """操作员配置 + 插件覆盖层（操作员的值优先）。"""
        return (self._runner._op_config_get(keys) or {}).get("values") or {}

    def config_set(self, values: Dict[str, Any]) -> Dict[str, Any]:
        return self._runner._op_config_set(values)

    def permission_check(self, permission: str) -> bool:
        """查询管理员是否批准了某权限（只读；无法提权）。"""
        res = self._runner._op_permission_check(permission) or {}
        return bool(res.get("granted"))

    def context_info(self) -> Dict[str, Any]:
        """拉取引擎侧上下文（插件名/版本/已批准权限）。"""
        res = self._runner._op_context() or {}
        return res.get("result") if isinstance(res.get("result"), dict) else res

    def send_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("send_message", payload)

    def send_private_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("send_private_message", payload)

    def get_group(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("get_group", payload)

    def get_user(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("get_user", payload)

    def get_memory(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("get_memory", payload)

    def write_memory(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("write_memory", payload)

    def http_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("http_request", payload)

    def log(self, level: str, message: str) -> Dict[str, Any]:
        return self._send_action("log", {"level": level, "message": message})

    # ---------- v2.1 缺口池：消息 ----------
    def edit_message(self, payload):
        """编辑消息（网关需支持；不支持时返回 not supported in v1）"""
        return self._send_action("edit_message", payload)

    def forward_message(self, payload):
        """转发消息（payload 含 group_id/user_id + message_id；自动选群/私聊）"""
        return self._send_action("forward_message", payload)

    def split_message(self, payload):
        """消息拆段（payload.text；按段/长度拆分，纯本地语义）"""
        return self._send_action("split_message", payload)

    def merge_message(self, payload):
        """消息合并（payload 段列表 → 单条消息负载；纯本地语义）"""
        return self._send_action("merge_message", payload)

    def favorite_message(self, payload):
        """收藏消息（网关需支持；当前 v1 无端点→not supported）"""
        return self._send_action("favorite_message", payload)

    def mark_message(self, payload):
        """标记消息（已读/未读；v1 无端点→not supported）"""
        return self._send_action("mark_message", payload)

    def read_status(self, payload):
        """消息已读状态查询（v1 无端点→not supported）"""
        return self._send_action("read_status", payload)

    def search_message(self, payload):
        """消息搜索（user_id/group_id + query + count：拉取历史并在本地过滤）"""
        return self._send_action("search_message", payload)

    def quote_chain(self, payload):
        """引用链解析（message_id 逐条回溯引用，≤3 层，纯本地语义）"""
        return self._send_action("quote_chain", payload)

    # ---------- v2.1 缺口池：数据 ----------
    def db_query(self, payload):
        """数据查询（插件数据域 JSON 过滤）"""
        return self._send_action("db_query", payload)

    def db_transaction(self, payload):
        """事务（原子写；全成或全滚）"""
        return self._send_action("db_transaction", payload)

    def db_migration(self, payload):
        """迁移（插件数据域 schema 版本）"""
        return self._send_action("db_migration", payload)

    def db_index(self, payload):
        """索引（字段索引加速查询）"""
        return self._send_action("db_index", payload)

    def cache_get(self, payload):
        """缓存读（等价 KV 读取）"""
        return self._send_action("cache_get", payload)

    def cache_set(self, payload):
        """缓存写（等价 KV 写入）"""
        return self._send_action("cache_set", payload)

    def cache_delete(self, payload):
        """缓存删（等价 KV 删除）"""
        return self._send_action("cache_delete", payload)

    # ---------- v2.1 缺口池：运行时 ----------
    def task_status(self, payload):
        """任务状态（任务运行在插件进程内；v1 主进程无句柄→not supported）"""
        return self._send_action("task_status", payload)

    def task_cancel(self, payload):
        """任务取消（v1 主进程无句柄→not supported；SDK TaskManager 提供）"""
        return self._send_action("task_cancel", payload)

    def task_pause(self, payload):
        """任务暂停（同上）"""
        return self._send_action("task_pause", payload)

    def task_resume(self, payload):
        """任务恢复（同上）"""
        return self._send_action("task_resume", payload)

    def resource_usage(self, payload):
        """资源占用（插件进程 CPU/内存；/proc 读取）"""
        return self._send_action("resource_usage", payload)

    def resource_quota(self, payload):
        """资源配额（保护级别映射）"""
        return self._send_action("resource_quota", payload)

    def runtime_status(self, payload):
        """运行状态（pid/uptime/版本）"""
        return self._send_action("runtime_status", payload)

    # ---------- v2.1 缺口池：开发工具 ----------
    def metrics(self, payload):
        """指标快照（全量注册表）"""
        return self._send_action("metrics", payload)

    def trace(self, payload):
        """链路追踪（trace_id 查近期日志）"""
        return self._send_action("trace", payload)

    def health(self, payload):
        """健康检查（进程信息）"""
        return self._send_action("health", payload)

    def debug(self, payload):
        """调试通道（v1 不支持→not supported）"""
        return self._send_action("debug", payload)

    def plugin_test(self, payload):
        """自测（运行插件 on_plugin_test 钩子）"""
        return self._send_action("plugin_test", payload)

    def mock_api(self, payload):
        """Mock（SDK 本地测试工具；API 层→not supported）"""
        return self._send_action("mock_api", payload)

    # ---------- v2.1 缺口池：插件 ----------
    def plugin_call(self, payload):
        """插件间调用（投递事件给目标插件；目标需启用）"""
        return self._send_action("plugin_call", payload)

    def plugin_event(self, payload):
        """插件事件广播（所有启用插件可订阅）"""
        return self._send_action("plugin_event", payload)

    def plugin_service(self, payload):
        """插件服务（注册/发现/调用插件服务总线）"""
        return self._send_action("plugin_service", payload)

    def plugin_discovery(self, payload):
        """插件发现（已启用插件列表与元数据）"""
        return self._send_action("plugin_discovery", payload)

    def plugin_dependency(self, payload):
        """插件依赖（自身 manifest 权限/声明）"""
        return self._send_action("plugin_dependency", payload)

    def plugin_health(self, payload):
        """插件健康（当前插件运行状态）"""
        return self._send_action("plugin_health", payload)

    def plugin_reload(self, payload):
        """插件重载（自身；停止并重载）"""
        return self._send_action("plugin_reload", payload)

    def plugin_config(self, payload):
        """插件配置读取（自身 manifest config）"""
        return self._send_action("plugin_config", payload)

    # ---------- v2.1 缺口池：Web ----------
    def router(self, payload):
        """路由列表（自身 Plugin WebUI 页面）"""
        return self._send_action("router", payload)

    def ws(self, payload):
        """WebSocket 通道（v1 明确不支持→not supported）"""
        return self._send_action("ws", payload)

    def sse(self, payload):
        """SSE 通道（v1 明确不支持→not supported）"""
        return self._send_action("sse", payload)

    def webhook(self, payload):
        """Webhook 发送（等价 http_request）；接收注册 v1 不支持"""
        return self._send_action("webhook", payload)

    def http_middleware(self, payload):
        """HTTP 中间件（主进程专属→not supported）"""
        return self._send_action("http_middleware", payload)

    def static_file(self, payload):
        """静态文件（插件 WebUI 空间；列/取链接）"""
        return self._send_action("static_file", payload)

    # ---------- v2.1 缺口池：Memory ----------
    def memory_get(self, payload):
        """记忆读取（等价 get_memory）"""
        return self._send_action("memory_get", payload)

    def memory_search(self, payload):
        """语义记忆检索（花语记忆；相似度召回，返回回忆文本）"""
        return self._send_action("memory_search", payload)

    def memory_semantic(self, payload):
        """语义检索（等价 memory_search）"""
        return self._send_action("memory_semantic", payload)

    def memory_update(self, payload):
        """记忆更新（等价 write_memory）"""
        return self._send_action("memory_update", payload)

    def memory_delete(self, payload):
        """记忆删除（插件 KV 域删除）"""
        return self._send_action("memory_delete", payload)

    def memory_tag(self, payload):
        """记忆标签（插件 KV 域 tag: 前缀）"""
        return self._send_action("memory_tag", payload)

    def memory_pin(self, payload):
        """记忆置顶（v1 花语无置顶域→not supported）"""
        return self._send_action("memory_pin", payload)

    def memory_expire(self, payload):
        """记忆过期查询（v1 无 TTL 域→not supported）"""
        return self._send_action("memory_expire", payload)

    # ---------- v2.1 缺口池：MCP ----------
    def mcp_server(self, payload):
        """MCP 服务器列表（已配置；含测试状态）"""
        return self._send_action("mcp_server", payload)

    def mcp_tools(self, payload):
        """MCP 工具列表（配置声明与在线工具）"""
        return self._send_action("mcp_tools", payload)

    def mcp_call(self, payload):
        """MCP 工具调用（管理员配置服务器；工具白名单）"""
        return self._send_action("mcp_call", payload)

    def mcp_resource(self, payload):
        """MCP 资源读取（v1 未实现→not supported）"""
        return self._send_action("mcp_resource", payload)

    def mcp_prompt(self, payload):
        """MCP Prompt 模板（v1 未实现→not supported）"""
        return self._send_action("mcp_prompt", payload)

    def mcp_status(self, payload):
        """MCP 服务器状态（在线探测）"""
        return self._send_action("mcp_status", payload)

    # ---------- v2.1 缺口池：AI ----------
    def ai_stream(self, payload):
        """AI 流式对话（收集 chunks 返回；主进程流式请求）"""
        return self._send_action("ai_stream", payload)

    def ai_vision(self, payload):
        """AI 视觉识图（图片地址/描述；主进程 vision 客户端，敏感图不可见跳转）"""
        return self._send_action("ai_vision", payload)

    def ai_embedding(self, payload):
        """AI 向量化（文本→向量；复用花语向量模型客户端）"""
        return self._send_action("ai_embedding", payload)

    def ai_rerank(self, payload):
        """AI 重排（query+documents→相关性得分）"""
        return self._send_action("ai_rerank", payload)

    def ai_token(self, payload):
        """Token 统计（文本→token 估算）"""
        return self._send_action("ai_token", payload)

    def ai_models(self, payload):
        """模型列表（已配置 AI 模型）"""
        return self._send_action("ai_models", payload)

    def ai_model_info(self, payload):
        """模型信息（名称/地址/类型）"""
        return self._send_action("ai_model_info", payload)

    def ai_usage(self, payload):
        """用量统计（调用次数/费用指标）"""
        return self._send_action("ai_usage", payload)

    def ai_budget(self, payload):
        """预算/限额（配置的每日限额与剩余）"""
        return self._send_action("ai_budget", payload)

    # ---------- v2.1 缺口池：社交互动 ----------
    def reaction(self, payload):
        """表情回应（message_id + react_type；等价 react）"""
        return self._send_action("reaction", payload)

    def poke(self, payload):
        """戳一戳（user_id→好友戳；group_id+user_id→群戳，群戳 v1 无端点）"""
        return self._send_action("poke", payload)

    def like(self, payload):
        """点赞（user_id；等价点赞好友资料）"""
        return self._send_action("like", payload)

    def emoji(self, payload):
        """Emoji 回应（message_id + emoji；等价反应）"""
        return self._send_action("emoji", payload)

    def emoji_list(self, payload):
        """表情回应列表（v1 无查询端点→not supported）"""
        return self._send_action("emoji_list", payload)

    # ---------- v2.1 缺口池：文件/媒体 ----------
    def file_upload(self, payload):
        """文件上传到插件 WebUI 空间（web_ui.files 权限；安全校验）"""
        return self._send_action("file_upload", payload)

    def file_download(self, payload):
        """文件下载（仅插件空间）"""
        return self._send_action("file_download", payload)

    def file_info(self, payload):
        """文件信息（大小/类型/图片尺寸；插件空间）"""
        return self._send_action("file_info", payload)

    def file_delete(self, payload):
        """删除插件空间文件"""
        return self._send_action("file_delete", payload)

    def file_convert(self, payload):
        """文件转换（v1 无转换器→not supported）"""
        return self._send_action("file_convert", payload)

    def image_compress(self, payload):
        """图片压缩（v1 无图像库→not supported）"""
        return self._send_action("image_compress", payload)

    def image_resize(self, payload):
        """图片缩放（v1 无图像库→not supported）"""
        return self._send_action("image_resize", payload)

    def image_screenshot(self, payload):
        """图片截图（v1 无图像能力→not supported）"""
        return self._send_action("image_screenshot", payload)

    def audio_info(self, payload):
        """音频信息（大小/格式；时长需网关辅助）"""
        return self._send_action("audio_info", payload)

    def video_info(self, payload):
        """视频信息（大小/格式；时长需网关辅助）"""
        return self._send_action("video_info", payload)

    # ---------- v2.1 缺口池：群 ----------
    def group_member_search(self, payload):
        """群成员搜索（group_id + query；成员列表本地过滤）"""
        return self._send_action("group_member_search", payload)

    def group_member_update(self, payload):
        """群成员信息更新（user_id + card；等价设置群名片）"""
        return self._send_action("group_member_update", payload)

    def group_mute_status(self, payload):
        """群成员禁言状态（v1 无查询端点→not supported）"""
        return self._send_action("group_mute_status", payload)

    def group_title(self, payload):
        """群成员头衔（group_id/user_id/title；等价 set_group_special_title）"""
        return self._send_action("group_title", payload)

    def group_notice_create(self, payload):
        """创建群公告（等价发送公告）"""
        return self._send_action("group_notice_create", payload)

    def group_notice_update(self, payload):
        """更新群公告（删除旧公告+发送新公告组合）"""
        return self._send_action("group_notice_update", payload)

    def group_file_upload(self, payload):
        """上传群文件（v1 无专用端点→not supported）"""
        return self._send_action("group_file_upload", payload)

    def group_file_rename(self, payload):
        """重命名群文件（v1 无端点→not supported）"""
        return self._send_action("group_file_rename", payload)

    def group_essence(self, payload):
        """群精华消息列表（等价 essence_list）"""
        return self._send_action("group_essence", payload)

    def group_invite(self, payload):
        """群邀请（v1 无端点→not supported）"""
        return self._send_action("group_invite", payload)

    def group_apply(self, payload):
        """群申请处理（等价 handle_group_request）"""
        return self._send_action("group_apply", payload)

    def group_admins(self, payload):
        """群管理员列表（成员列表本地过滤 admin/owner）"""
        return self._send_action("group_admins", payload)

    # ---------- v2.1 缺口池：好友 ----------
    def friend_detail(self, payload):
        """好友详细信息（user_id；列表内匹配详情）"""
        return self._send_action("friend_detail", payload)

    def friend_remark(self, payload):
        """设置好友备注（网关需支持；v1 无端点→not supported）"""
        return self._send_action("friend_remark", payload)

    def friend_delete(self, payload):
        """删除好友（v1 无端点→not supported）"""
        return self._send_action("friend_delete", payload)

    def friend_group(self, payload):
        """好友分组管理（v1 无端点→not supported）"""
        return self._send_action("friend_group", payload)

    def friend_category(self, payload):
        """好友分类（等价 friend_group；v1 无端点→not supported）"""
        return self._send_action("friend_category", payload)

    def friend_online(self, payload):
        """好友在线状态（v1 无端点→not supported）"""
        return self._send_action("friend_online", payload)

    def call(self, action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """通用语义化动作调用（v1.5；封装唯一，动作名白名单由主进程校验）。"""
        return self._send_action(str(action), dict(payload or {}))

    # ---------- SDK 动作（消息/群管/匹配注册；无需插件感知 OneBot payload） ----------
    def send_reply(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("send_reply", payload)

    def send_many(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """多条发送：条数/间隔由主进程 Core 统一控制。"""
        return self._send_action("send_many", payload)

    def delete_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("delete_message", payload)

    def get_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("get_message", payload)

    def get_group_history(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("get_group_history", payload)

    def get_context(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("get_context", payload)

    def get_group_member(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("get_group_member", payload)

    def group_ban(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("group_ban", payload)

    def group_kick(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("group_kick", payload)

    def is_group_admin(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("is_group_admin", payload)

    def is_group_owner(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("is_group_owner", payload)

    def matcher_register(self, matchers: list) -> Dict[str, Any]:
        """批量注册 Matcher（SDK 启动时调用；返回注册摘要）。"""
        return self._send_action("matcher_register", {"matchers": list(matchers or [])})

    # ---------- v1.4 扩展（请求处理/调度/存储/AI/记忆/工具/HTTP 扩展） ----------
    def handle_friend_request(self, flag: str, approve: bool, remark: str = "") -> Dict[str, Any]:
        return self._send_action("handle_friend_request",
                                 {"flag": flag, "approve": bool(approve), "remark": remark})

    def handle_group_request(self, flag: str, approve: bool, reason: str = "") -> Dict[str, Any]:
        return self._send_action("handle_group_request",
                                 {"flag": flag, "approve": bool(approve), "reason": reason})

    def schedule_register(self, kind: str, when, name: str = "") -> Dict[str, Any]:
        return self._send_action("schedule_register",
                                 {"kind": kind, "when": when, "name": name})

    def schedule_cancel(self, schedule_id: str) -> Dict[str, Any]:
        return self._send_action("schedule_cancel", {"schedule_id": schedule_id})

    def schedule_list(self) -> Dict[str, Any]:
        return self._send_action("schedule_list", {})

    def kv_get(self, key: str) -> Dict[str, Any]:
        return self._send_action("kv_get", {"key": key})

    def kv_set(self, key: str, value) -> Dict[str, Any]:
        return self._send_action("kv_set", {"key": key, "value": value})

    def kv_delete(self, key: str) -> Dict[str, Any]:
        return self._send_action("kv_delete", {"key": key})

    def kv_list(self) -> Dict[str, Any]:
        return self._send_action("kv_list", {})

    def ai_chat(self, message: str, system: str = "") -> Dict[str, Any]:
        return self._send_action("ai_chat", {"message": message, "system": system})

    def mem_update(self, user_id: int, group_id: int, key: str, value: str) -> Dict[str, Any]:
        return self._send_action("mem_update",
                                 {"user_id": user_id, "group_id": group_id,
                                  "key": key, "value": value})

    def mem_clear(self, user_id: int, group_id: int) -> Dict[str, Any]:
        return self._send_action("mem_clear", {"user_id": user_id, "group_id": group_id})

    def random_choice(self, choices: list) -> Dict[str, Any]:
        return self._send_action("random_choice", {"choices": list(choices or [])})

    def random_int(self, low: int, high: int) -> Dict[str, Any]:
        return self._send_action("random_int", {"low": int(low), "high": int(high)})

    def now(self) -> Dict[str, Any]:
        return self._send_action("now", {})

    def format_time(self, timestamp: float = 0, fmt: str = "%Y-%m-%d %H:%M:%S") -> Dict[str, Any]:
        return self._send_action("format_time", {"timestamp": timestamp, "format": fmt})

    def http_put(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("http_put", payload)

    def http_delete(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("http_delete", payload)

    def http_head(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("http_head", payload)

    def http_download(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("http_download", payload)

    def get_group_members(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("get_group_members", payload)

    def get_group_info(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("get_group_info", payload)

    def group_admin(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._send_action("group_admin", payload)


    # ---------- v1.7.0 语义能力（看一眼就会；底层同 call 白名单/权限/回退） ----------
    def react(self, message_id: int, react_type: int) -> Dict[str, Any]:
        """消息表情回应（NapCat/Lagrange 自动适配）。"""
        return self._send_action("react", {"message_id": message_id, "react_type": react_type})

    def tap(self, group_id: int, user_id: int) -> Dict[str, Any]:
        """群内戳一戳。"""
        return self._send_action("tap", {"group_id": group_id, "user_id": user_id})

    def user_history(self, user_id: int, count: int = 20) -> Dict[str, Any]:
        """好友/私聊消息历史。"""
        return self._send_action("user_history", {"user_id": user_id, "count": count})

    def user_poke(self, user_id: int) -> Dict[str, Any]:
        """私聊戳一戳。"""
        return self._send_action("user_poke", {"user_id": user_id})

    def user_forward(self, user_id: int, messages: list) -> Dict[str, Any]:
        """私聊合并转发。"""
        return self._send_action("user_forward", {"user_id": user_id, "messages": messages})

    def group_forward(self, group_id: int, messages: list) -> Dict[str, Any]:
        """群合并转发。"""
        return self._send_action("group_forward", {"group_id": group_id, "messages": messages})

    def essence_list(self, group_id: int) -> Dict[str, Any]:
        """群精华消息列表。"""
        return self._send_action("essence_list", {"group_id": group_id})

    def group_honor(self, group_id: int, honor_type: str = "") -> Dict[str, Any]:
        """群荣誉信息。"""
        return self._send_action("group_honor", {"group_id": group_id, "honor_type": honor_type})

    def group_notice_delete(self, group_id: int, notice_id: str) -> Dict[str, Any]:
        """删除群公告。"""
        return self._send_action("group_notice_delete", {"group_id": group_id, "notice_id": notice_id})

    def group_portrait(self, group_id: int, file: str) -> Dict[str, Any]:
        """修改群头像。"""
        return self._send_action("group_portrait", {"group_id": group_id, "file": file})

    def group_info(self, group_id: int, no_cache: bool = False) -> Dict[str, Any]:
        """群信息。"""
        return self._send_action("group_info", {"group_id": group_id, "no_cache": no_cache})

    def group_list(self, no_cache: bool = False) -> Dict[str, Any]:
        """群列表。"""
        return self._send_action("group_list", {"no_cache": no_cache})

    def group_folder_create(self, group_id: int, name: str) -> Dict[str, Any]:
        """创建群文件文件夹。"""
        return self._send_action("group_folder_create", {"group_id": group_id, "name": name})

    def group_file_delete(self, group_id: int, file_id: str, busid: int = 0) -> Dict[str, Any]:
        """删除群文件。"""
        return self._send_action("group_file_delete",
                                 {"group_id": group_id, "file_id": file_id, "busid": busid})

    def group_folder_delete(self, group_id: int, folder_id: str) -> Dict[str, Any]:
        """删除群文件文件夹。"""
        return self._send_action("group_folder_delete", {"group_id": group_id, "folder_id": folder_id})

    def group_file_move(self, group_id: int, file_id: str, busid: int = 0,
                        target_folder_id: str = "") -> Dict[str, Any]:
        """移动群文件。"""
        return self._send_action("group_file_move", {"group_id": group_id, "file_id": file_id,
                                                     "busid": busid, "target_folder_id": target_folder_id})

    def group_folder_rename(self, group_id: int, folder_id: str, name: str) -> Dict[str, Any]:
        """重命名群文件文件夹。"""
        return self._send_action("group_folder_rename",
                                 {"group_id": group_id, "folder_id": folder_id, "name": name})

class PluginRunner:
    """协议主体：初始化模块 → 分发事件 → 处理 action 请求（请求-响应嵌套循环）。"""

    def __init__(self, plugin_dir: str, entry: str, plugin_id: str):
        self.plugin_dir = os.path.abspath(plugin_dir)
        # 插件数据目录：plugins/<plugin_id>/data/（自动创建；位于插件目录内，防穿越）
        self.data_dir = os.path.join(self.plugin_dir, "data")
        try:
            os.makedirs(self.data_dir, exist_ok=True)
        except OSError:
            self.data_dir = self.plugin_dir
        self.entry = entry
        self.plugin_id = plugin_id
        self.module = None
        self._req_id = 0
        #: 被调方：method -> handler（plugin.expose 注册，§五）
        self._handlers: Dict[str, Any] = {}
        #: 订阅方：event 名 -> [handler]（plugin.on 注册，§九）
        self._event_handlers: Dict[str, List[Any]] = {}
        #: 入站消息栈（trace/hop 传递，§二十二/§二十三）：嵌套调用时链路连续
        self._inbound: List[Dict[str, Any]] = []
        #: 已被取消的 request_id（§十八）
        self._cancelled: set = set()
        self.api = PluginApi(self._send_action_inner, plugin_id, self)

    # ---------- 基础 ----------
    def _emit(self, obj: Dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def _error(self, req_id, message: str) -> None:
        self._emit({"id": req_id, "error": str(message)[:800]})

    def _readline(self) -> Optional[str]:
        line = sys.stdin.readline()
        if not line:
            return None
        return line.strip()

    # 插件 → Flowerie 的 action 请求 id 偏移（与响应请求 id = 1,2,3... 不共用命名空间，
    # 防止 id 碰撞导致错配/卡死）
    _ACTION_ID_BASE = 1_000_000

    def _send_action_inner(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """发 action 请求并阻塞等待对应响应（同步 API 的底层实现）。"""
        self._req_id += 1
        my_id = self._ACTION_ID_BASE + self._req_id
        self._emit({"id": my_id, "method": "action",
                    "params": {"action": action, "payload": payload or {}}})
        while True:
            line = self._readline()
            if line is None:
                return {"ok": False, "error": "connection closed"}
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("id") == my_id:
                return msg.get("result") or {"ok": False, "error": "empty result"}
            # 不是我在等的那条：可能是引擎投递进来的 plugin.call / plugin.event / plugin.cancel
            self._pump_nested(msg)

    def _send_action_safe(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return self._send_action_inner(action, payload)
        except Exception as e:  # noqa: BLE001 - 插件 API 异常不得拖死 runner
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ---------- 模块加载 ----------
    def _load_module(self) -> Optional[str]:
        entry_path = os.path.join(self.plugin_dir, self.entry)
        if not os.path.isfile(entry_path):
            return f"入口文件不存在: {self.entry}"
        if os.path.islink(entry_path):
            return "入口文件不能是符号链接"
        try:
            # 插件目录加入 sys.path：插件可 import 同目录模块与自带的 flowerie_sdk 包
            # （python -I 只清初始化路径，运行时 sys.path 修改仍有效）
            plugin_dir = self.plugin_dir
            if plugin_dir not in sys.path:
                sys.path.insert(0, plugin_dir)
            spec = importlib.util.spec_from_file_location(
                f"flowerie_plugin_{self.plugin_id}", entry_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            # 注册到 sys.modules（供插件 SDK 与其他模块识别；隔离不影响）
            sys.modules[module.__name__] = module
            self.module = module
            return None
        except Exception as e:  # noqa: BLE001
            return f"插件加载失败: {type(e).__name__}: {e}"

    def _call_hook(self, name: str, *args):
        if self.module is None:
            return None
        hook = getattr(self.module, name, None)
        if hook is None:
            return None
        # 按签名决定传参个数（避免 TypeError 重试歧义：插件内部 TypeError 不会误判为签名问题）
        try:
            sig = inspect.signature(hook)
            n_args = len([p for p in sig.parameters.values()
                          if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)])
            call_args = args[:n_args] if n_args < len(args) else args
        except (TypeError, ValueError):  # 内置函数等无签名：按 2 参调用
            call_args = args
        try:
            result = hook(*call_args)
            # SDK 模式：async handler（如 bot.route）——runner 无事件循环，
            # 用 asyncio.run 执行；await 语义保证 reply/recall 等在钩子内完成
            if inspect.isawaitable(result):
                import asyncio
                try:
                    result = asyncio.run(result)
                except Exception as e:  # noqa: BLE001
                    return {"__error__": f"{type(e).__name__}: {e}"}
            return result
        except Exception as e:  # noqa: BLE001
            return {"__error__": f"{type(e).__name__}: {e}"}

    # ---------- Plugin Protocol v1：可选方法（引擎不会调用未声明的） ----------
    def _send_engine_op(self, op: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """反向通道：向引擎发 engine op 并等响应（与 action 同一套 id 命名空间）。"""
        self._req_id += 1
        my_id = self._ACTION_ID_BASE + self._req_id
        self._emit({"id": my_id, "method": "engine",
                    "params": {"op": op, "args": dict(args or {})}})
        while True:
            line = self._readline()
            if line is None:
                return {"ok": False, "error": "connection closed"}
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("id") == my_id:
                if msg.get("error"):
                    return {"ok": False, "error": str(msg["error"])}
                result = msg.get("result")
                return result if isinstance(result, dict) else {"ok": False, "error": "empty result"}
            self._pump_nested(msg)

    # ---------- Plugin-to-Plugin 通信（任务书第 4 份 §五/§九/§十八/§二十二） ----------
    @staticmethod
    def _valid_comm_name(name: str) -> bool:
        return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,95}", str(name or "")))

    def register_handler(self, method: str, handler) -> Dict[str, Any]:
        """暴露方法给其它插件（§五 CALL 的被调方）；handler 传 None 表示注销。"""
        name = str(method or "")
        if not self._valid_comm_name(name):
            return {"ok": False, "error": "方法名非法（字母/下划线开头，允许 . _，≤96）"}
        if handler is None:
            self._handlers.pop(name, None)
            return {"ok": True, "removed": name}
        if not callable(handler):
            return {"ok": False, "error": "handler 必须可调用"}
        self._handlers[name] = handler
        return {"ok": True, "exposed": name}

    def register_event_handler(self, event: str, handler) -> Dict[str, Any]:
        """订阅事件（§九）；event 传 * 表示订阅全部。"""
        name = str(event or "")
        if name != "*" and not self._valid_comm_name(name):
            return {"ok": False, "error": "事件名非法（字母/下划线开头，允许 . _，≤96）"}
        if not callable(handler):
            return {"ok": False, "error": "handler 必须可调用"}
        self._event_handlers.setdefault(name, []).append(handler)
        return {"ok": True, "subscribed": name}

    def comm_context(self) -> Dict[str, Any]:
        """当前入站消息的 trace/hop（嵌套调用时链路连续，§二十二/§二十三）。"""
        return dict(self._inbound[-1]) if self._inbound else {}

    def comm_call(self, target, method, params=None, timeout=5000, route="auto"):
        """plugin.call 的底层：反向 op（插件 -> Core -> 目标插件），返回 result 或抛错。"""
        ctx = self.comm_context()
        request = {
            "target": str(target or ""),
            "method": str(method or ""),
            "params": params if params is not None else {},
            "timeout": int(timeout or 5000),
            "route": str(route or "auto"),
            "trace_id": str(ctx.get("trace_id") or ""),
            "hop_count": int(ctx.get("hop_count") or 0),
        }
        res = self._send_engine_op("plugin.call", request)
        if not isinstance(res, dict) or res.get("ok") is not True:
            error = res.get("error") if isinstance(res, dict) else None
            code, message, data = self._error_tuple(error)
            raise PluginCommError(code, message, data)
        return res.get("result")

    @staticmethod
    def _error_tuple(error):
        if isinstance(error, dict):
            code = str(error.get("code") or "PLUGIN_ERROR")
            data = error.get("data") if isinstance(error.get("data"), dict) else {}
            return code, str(error.get("message") or code), data
        return "PLUGIN_ERROR", str(error or "插件调用失败"), {}

    def comm_emit(self, name, payload=None) -> Dict[str, Any]:
        ctx = self.comm_context()
        res = self._send_engine_op("plugin.emit", {
            "name": str(name or ""),
            "payload": payload if payload is not None else {},
            "trace_id": str(ctx.get("trace_id") or ""),
            "hop_count": int(ctx.get("hop_count") or 0)})
        return res if isinstance(res, dict) else {"ok": False, "error": "empty result"}

    def comm_cancel(self, request_id, reason="") -> Dict[str, Any]:
        res = self._send_engine_op("plugin.cancel", {"request_id": str(request_id or ""),
                                                     "reason": str(reason or "")})
        return res if isinstance(res, dict) else {"ok": False, "error": "empty result"}

    def _pump_nested(self, msg: Dict[str, Any]) -> None:
        """等待响应期间引擎投递进来的请求：必须原地处理，不能丢。

        插件是单线程的（读写 stdio 的循环）。若这里把消息丢掉，A 调用 B、B 又回调 A 时
        A 永远收不到回调 —— 任务书 §二十二 的环保护也就没有真实链路可观察了。
        """
        if len(self._inbound) > 16:            # 防退化递归（正常链路远小于此）
            return
        method = str(msg.get("method") or "")
        if method in PLUGIN_METHODS or method in ("hook", "health"):
            self.handle(msg)

    def _handle_plugin_comm(self, req_id, method: str, params: Dict[str, Any]) -> None:
        if method == "plugin.call":
            self._handle_inbound_call(req_id, params)
        elif method == "plugin.event":
            self._handle_inbound_event(req_id, params)
        else:
            self._handle_inbound_cancel(req_id, params)

    def _emit_comm_result(self, req_id, payload: Dict[str, Any]) -> None:
        """回一条插件间通信应答；语言内部对象在这里被拦下（§十九/§二十）。"""
        try:
            self._emit({"id": req_id, "result": payload})
        except TypeError as e:
            self._emit({"id": req_id, "result": {"ok": False, "error": {
                "code": "SERIALIZATION_ERROR",
                "message": "返回值不是语言无关类型: %s" % e,
                "data": {}}}})

    def _handle_inbound_call(self, req_id, params: Dict[str, Any]) -> None:
        request_id = str(params.get("request_id") or "")
        method = str(params.get("method") or "")
        source = params.get("source") if isinstance(params.get("source"), dict) else {}
        self._inbound.append({"trace_id": str(params.get("trace_id") or ""),
                              "hop_count": int(params.get("hop_count") or 0),
                              "source": source, "request_id": request_id})
        try:
            if request_id and request_id in self._cancelled:
                self._cancelled.discard(request_id)
                self._emit_comm_result(req_id, {"ok": False, "error": {
                    "code": "CANCELLED", "message": "调用已被取消", "data": {}}})
                return
            handler = self._handlers.get(method)
            if handler is None:
                self._emit_comm_result(req_id, {"ok": False, "error": {
                    "code": "METHOD_NOT_FOUND",
                    "message": "插件未暴露方法: %s" % method,
                    "data": {"method": method, "exposed": sorted(self._handlers)}}})
                return
            result = self._invoke_comm_handler(handler, params)
            if isinstance(result, dict) and "__error__" in result:
                self._emit_comm_result(req_id, {"ok": False, "error": {
                    "code": str(result.get("__code__") or "PLUGIN_ERROR"),
                    "message": str(result["__error__"]), "data": {}}})
                return
            self._emit_comm_result(req_id, {"ok": True, "result": result})
        finally:
            self._inbound.pop()

    def _handle_inbound_event(self, req_id, params: Dict[str, Any]) -> None:
        name = str(params.get("name") or "")
        source = params.get("source") if isinstance(params.get("source"), dict) else {}
        self._inbound.append({"trace_id": str(params.get("trace_id") or ""),
                              "hop_count": int(params.get("hop_count") or 0),
                              "source": source, "request_id": ""})
        try:
            handlers = list(self._event_handlers.get(name, []))
            if name != "*":
                handlers += list(self._event_handlers.get("*", []))
            handled = 0
            for handler in handlers:
                res = self._invoke_comm_handler(handler, params)
                if not (isinstance(res, dict) and "__error__" in res):
                    handled += 1
            self._emit({"id": req_id, "result": {"ok": True, "handled": handled}})
        finally:
            self._inbound.pop()

    def _handle_inbound_cancel(self, req_id, params: Dict[str, Any]) -> None:
        request_id = str(params.get("request_id") or "")
        if request_id:
            self._cancelled.add(request_id)
            if len(self._cancelled) > 256:      # 有界：取消记录不无限增长
                self._cancelled.clear()
        self._emit({"id": req_id, "result": {"ok": True, "cancelled": bool(request_id)}})

    def _invoke_comm_handler(self, handler, params: Dict[str, Any]):
        """按签名调用 handler（兼容 (params) 与 (params, api)），支持 async handler。"""
        try:
            sig = inspect.signature(handler)
            n_args = len([p for p in sig.parameters.values()
                          if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)])
            call_args = (params, self.api)[:n_args]
        except (TypeError, ValueError):
            call_args = (params, self.api)
        try:
            result = handler(*call_args)
            if inspect.isawaitable(result):
                import asyncio
                result = asyncio.run(result)
            return result
        except PluginCommError as e:
            # 嵌套调用链上的错误必须**保住错误码**（否则 A→B→A 的 PLUGIN_CALL_LOOP 会被
            # 中间层降级成 PLUGIN_ERROR，插件作者再也看不到真实原因）
            return {"__error__": "%s: %s" % (e.code, e.message), "__code__": e.code}
        except Exception as e:  # noqa: BLE001 - handler 异常 -> 结构化 PLUGIN_ERROR（不杀进程）
            return {"__error__": "%s: %s" % (type(e).__name__, e)}

    # ---- storage：只落在本插件自己的 data 目录（进程级隔离，天然不跨插件） ----
    def _storage_dir(self) -> str:
        d = os.path.join(self.data_dir, "storage")
        os.makedirs(d, exist_ok=True)
        return d

    def _storage_path(self, key: str) -> str:
        if not STORAGE_KEY_RE.match(str(key or "")):
            raise ValueError("存储键非法（字母数字开头 ≤64，允许 . _ -）")
        return os.path.join(self._storage_dir(), key + ".json")

    def _storage_get(self, key):
        try:
            path = self._storage_path(key)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if not os.path.isfile(path):
            return {"ok": True, "value": None}
        try:
            with open(path, encoding="utf-8") as fh:
                return {"ok": True, "value": json.load(fh)}
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": "读取失败: %s" % exc}

    def _storage_set(self, key, value):
        try:
            path = self._storage_path(key)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        size = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        if size > MAX_STORAGE_VALUE_BYTES:
            return {"ok": False, "error": "值超过 %d 字节上限" % MAX_STORAGE_VALUE_BYTES}
        keys = [f for f in os.listdir(self._storage_dir()) if f.endswith(".json")]
        if len(keys) >= MAX_STORAGE_KEYS and not os.path.isfile(path):
            return {"ok": False, "error": "存储键数量超过 %d 上限" % MAX_STORAGE_KEYS}
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(value, fh, ensure_ascii=False)
            os.replace(tmp, path)
            return {"ok": True, "size": size}
        except OSError as exc:
            return {"ok": False, "error": "写入失败: %s" % exc}

    def _storage_delete(self, key):
        try:
            path = self._storage_path(key)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if not os.path.isfile(path):
            return {"ok": True, "deleted": False}
        try:
            os.remove(path)
            return {"ok": True, "deleted": True}
        except OSError as exc:
            return {"ok": False, "error": "删除失败: %s" % exc}

    def _storage_list(self, prefix):
        out = []
        for name in sorted(os.listdir(self._storage_dir())):
            if not name.endswith(".json"):
                continue
            key = name[:-5]
            if prefix and not key.startswith(str(prefix)):
                continue
            out.append(key)
        return {"ok": True, "keys": out[:MAX_STORAGE_KEYS]}

    # ---- config：操作员配置（引擎只读）+ 插件自己的覆盖层（本地） ----
    def _config_path(self) -> str:
        return os.path.join(self.data_dir, "config.json")

    def _config_overlay(self) -> Dict[str, Any]:
        try:
            with open(self._config_path(), encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    # ---------- 可选方法的**计算**部分（协议分派与插件 API 共用同一实现，避免两套逻辑漂移） ----------
    def _op_context(self) -> Dict[str, Any]:
        return self._send_engine_op("context.get", {})

    def _op_permission_check(self, permission: str) -> Dict[str, Any]:
        return self._send_engine_op("permission.check", {"permission": str(permission or "")})

    def _op_config_get(self, keys=None) -> Dict[str, Any]:
        res = self._send_engine_op("config.get", {})
        values = res.get("values") if isinstance(res, dict) and res.get("ok") else {}
        if not isinstance(values, dict):
            values = {}
        merged = dict(self._config_overlay())
        merged.update(values)              # 操作员配置优先（插件不能覆盖管理员的值）
        if isinstance(keys, list) and keys:
            wanted = [str(x) for x in keys]
            merged = {k: v for k, v in merged.items() if k in wanted}
        return {"ok": True, "values": merged}

    def _op_config_set(self, values) -> Dict[str, Any]:
        if not isinstance(values, dict):
            return {"ok": False, "error": "config.set 需要 values 对象"}
        overlay = self._config_overlay()
        for k, v in values.items():
            key = str(k)
            if not STORAGE_KEY_RE.match(key):
                return {"ok": False, "error": "配置键非法: %s" % key}
            if len(json.dumps(v, ensure_ascii=False).encode("utf-8")) > MAX_CONFIG_VALUE_BYTES:
                return {"ok": False,
                        "error": "配置值超过 %d 字节上限: %s" % (MAX_CONFIG_VALUE_BYTES, key)}
            overlay[key] = v
        if len(overlay) > MAX_CONFIG_KEYS:
            return {"ok": False, "error": "配置键数量超过 %d 上限" % MAX_CONFIG_KEYS}
        try:
            with open(self._config_path(), "w", encoding="utf-8") as fh:
                json.dump(overlay, fh, ensure_ascii=False)
        except OSError as exc:
            return {"ok": False, "error": "写入失败: %s" % exc}
        return {"ok": True, "saved": sorted(str(k) for k in values)}

    def _handle_optional(self, req_id, method: str, params: Dict[str, Any]) -> None:
        if method == "context.get":
            self._emit({"id": req_id, "result": self._op_context()})
            return
        if method == "permission.check":
            self._emit({"id": req_id,
                        "result": self._op_permission_check(params.get("permission"))})
            return
        if method == "config.get":
            self._emit({"id": req_id, "result": self._op_config_get(params.get("keys"))})
            return
        if method == "config.set":
            self._emit({"id": req_id, "result": self._op_config_set(params.get("values"))})
            return
        if method == "storage.get":
            self._emit({"id": req_id, "result": self._storage_get(params.get("key"))})
            return
        if method == "storage.set":
            self._emit({"id": req_id,
                        "result": self._storage_set(params.get("key"), params.get("value"))})
            return
        if method == "storage.delete":
            self._emit({"id": req_id, "result": self._storage_delete(params.get("key"))})
            return
        if method == "storage.list":
            self._emit({"id": req_id, "result": self._storage_list(params.get("prefix"))})
            return
        if method == "webui.page":
            page = params.get("page") if isinstance(params.get("page"), dict) else {}
            context = params.get("context") if isinstance(params.get("context"), dict) else {}
            self._emit_webui(req_id, self._call_hook("webui_render", page, context))
            return
        if method == "webui.action":
            page = params.get("page") if isinstance(params.get("page"), dict) else {}
            form = params.get("form") if isinstance(params.get("form"), dict) else {}
            context = params.get("context") if isinstance(params.get("context"), dict) else {}
            self._emit_webui(req_id, self._call_hook("webui_action", page,
                                                     str(params.get("action") or ""), form, context))
            return
        if method == "webui.asset":
            self._emit_webui(req_id, self._call_hook("webui_asset", str(params.get("path") or "")))
            return
        self._error(req_id, "未知方法: %r" % method)

    def _emit_webui(self, req_id, res) -> None:
        """把插件的 WebUI 钩子返回值归一成协议应答。

        三种合法返回（与其它语言 SDK 语义一致）：
        - 字符串 → 直接当页面 HTML（`{"ok": true, "html": ...}` 的简写）；
        - 对象 → 透传受支持字段（html / vars / message / content_type / body / base64 /
          config_set / storage_set），其余字段一律丢弃（不把插件内部对象塞进协议）；
        - `{"__error__": ...}`（钩子缺失或抛异常）→ 操作级错误，不是协议级错误。
        """
        if isinstance(res, dict) and "__error__" in res:
            self._emit({"id": req_id, "result": {"ok": False, "error": str(res["__error__"])}})
            return
        if isinstance(res, str):
            self._emit({"id": req_id, "result": {"ok": True, "html": res}})
            return
        if isinstance(res, dict):
            if res.get("ok") is False:
                self._emit({"id": req_id, "result": {
                    "ok": False, "error": str(res.get("error") or "插件返回 ok=false")}})
                return
            payload = {"ok": True}
            for key in ("html", "vars", "context", "message", "content_type", "body", "base64",
                        "config_set", "storage_set"):
                if key in res:
                    payload[key] = res[key]
            self._emit({"id": req_id, "result": payload})
            return
        if res is None:
            self._emit({"id": req_id, "result": {"ok": False,
                                                 "error": "插件未实现该 WebUI 钩子（返回 None）"}})
            return
        self._emit({"id": req_id, "result": {"ok": False,
                                             "error": "WebUI 钩子返回了非法类型: %s"
                                                      % type(res).__name__}})

    # ---------- 请求处理 ----------
    def handle(self, msg: Dict[str, Any]) -> None:
        req_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}
        try:
            if method == "initialize":
                err = self._load_module()
                if err:
                    self._error(req_id, err)
                    return
                ctx = {"plugin_id": self.plugin_id, "plugin_dir": self.plugin_dir,
                       "data_dir": self.data_dir,
                       "api_version": "1", **params.get("context", {})}
                hook_err = self._call_hook("on_startup", ctx, self.api)
                if isinstance(hook_err, dict) and "__error__" in hook_err:
                    self._error(req_id, f"on_startup 异常: {hook_err['__error__']}")
                    return
                caps = []
                declared = getattr(self.module, "PLUGIN_CAPABILITIES", None)
                for group in (declared if isinstance(declared, (list, tuple)) else
                              ("context", "config", "permission", "storage", "webui", "plugin")):
                    caps.extend(CAPABILITY_GROUPS.get(str(group), ()))
                self._emit({"id": req_id, "result": {
                    "ok": True, "api_version": "1", "protocol_version": PROTOCOL_VERSION,
                    "capabilities": sorted(set(caps)),
                }})
            elif method == "event":
                event = params.get("event", "")
                payload = params.get("payload", {})
                self._emit({"id": req_id, "result": {"actions": self._dispatch_event(event, payload)}})
            elif method in PLUGIN_METHODS:
                self._handle_plugin_comm(req_id, method, params)
            elif method in OPTIONAL_METHODS:
                self._handle_optional(req_id, method, params)
            elif method == "hook":
                hook_name = str(params.get("name") or "")
                args = params.get("args") or []
                if not re.fullmatch(r"[a-z_][a-z0-9_]{0,63}", hook_name):
                    self._error(req_id, "hook 名非法")
                    return
                res = self._call_hook(hook_name, *args)
                if isinstance(res, dict) and "__error__" in res:
                    self._emit({"id": req_id, "result": {"ok": False, "error": res["__error__"]}})
                else:
                    self._emit({"id": req_id, "result": {"ok": True, "result": res}})
            elif method == "health":
                hook = self._call_hook("health_check", {"plugin_id": self.plugin_id}, self.api)
                if isinstance(hook, dict) and "__error__" in hook:
                    self._emit({"id": req_id, "result": {"ok": False, "error": hook["__error__"]}})
                else:
                    self._emit({"id": req_id, "result": {"ok": True}})
            elif method == "shutdown":
                self._call_hook("on_shutdown", {"plugin_id": self.plugin_id}, self.api)
                self._emit({"id": req_id, "result": {"ok": True}})
            else:
                self._error(req_id, f"未知方法: {method!r}")
        except Exception as e:  # noqa: BLE001 - runner 自身异常按请求级别报告
            self._error(req_id, f"runner 异常: {type(e).__name__}: {e}")

    def _dispatch_event(self, event: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        event_obj = {"event": event, "plugin_id": self.plugin_id, **payload}
        hook_name = None
        if event == "message":
            hook_name = "on_message"
        elif event == "command":
            hook_name = "on_command"
        elif event == "notice":
            hook_name = "on_notice"
        elif event == "request":
            hook_name = "on_request"
        elif event == "lifecycle":
            hook_name = "on_lifecycle"
        elif event == "schedule":
            hook_name = "on_schedule"
        if hook_name is None:
            # 任意事件类型（任务书《插件测试》§四 的 test.event 这类自定义事件）：
            # 先试事件名派生的钩子（test.event -> on_test_event），再试通用 on_event；
            # 两个都没有时返回空动作 —— 未知事件不是错误，只是没人订阅。
            derived = "on_" + re.sub(r"[^a-z0-9_]", "_", str(event).lower())
            generic = self._call_hook(derived, event_obj, self.api)
            if generic is None:
                generic = self._call_hook("on_event", event_obj, self.api)
            return self._normalize_actions(generic)
        result = self._call_hook(hook_name, event_obj, self.api)
        return self._normalize_actions(result)

    @staticmethod
    def _normalize_actions(result) -> List[Dict[str, Any]]:
        if result is None:
            return []
        if isinstance(result, dict):
            if "__error__" in result:
                traceback.print_exc(file=sys.stderr)
                return []
            return [dict(result)]
        if isinstance(result, list):
            actions = []
            for item in result:
                if isinstance(item, dict) and "__error__" not in item:
                    actions.append(dict(item))
            return actions
        return []

    # ---------- 主循环 ----------
    def run(self) -> int:
        while True:
            line = self._readline()
            if line is None:
                return 0
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            try:
                self.handle(msg)
            except SystemExit:  # noqa: BLE001
                return 0
            except Exception:  # noqa: BLE001 - 顶级兜底：单条消息失败不退出进程
                self._error(msg.get("id"), "runner 未处理异常")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True, help="插件目录")
    parser.add_argument("--entry", default="plugin.py", help="入口文件")
    parser.add_argument("--plugin-id", default="unknown", help="插件 id（日志/API 透传）")
    args = parser.parse_args()
    runner = PluginRunner(args.dir, args.entry, args.plugin_id)
    return runner.run()


if __name__ == "__main__":
    sys.exit(main())
