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
import sys
import traceback
from typing import Any, Dict, List, Optional


class PluginApi:
    """同步插件 API：每个方法向 Flowerie 发 action 请求并等待响应（阻塞读取 stdin）。"""

    def __init__(self, send_action, plugin_id: str):
        self._send_action = send_action
        self.plugin_id = plugin_id

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
        self.entry = entry
        self.plugin_id = plugin_id
        self.module = None
        self._req_id = 0
        self.api = PluginApi(self._send_action_inner, plugin_id)

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
                       "api_version": "1", **params.get("context", {})}
                hook_err = self._call_hook("on_startup", ctx, self.api)
                if isinstance(hook_err, dict) and "__error__" in hook_err:
                    self._error(req_id, f"on_startup 异常: {hook_err['__error__']}")
                    return
                self._emit({"id": req_id, "result": {"ok": True, "api_version": "1"}})
            elif method == "event":
                event = params.get("event", "")
                payload = params.get("payload", {})
                self._emit({"id": req_id, "result": {"actions": self._dispatch_event(event, payload)}})
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
            return []
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
