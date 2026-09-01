"""Plugin Permission System：权限枚举 + 运行时强制检查。

设计原则（requirement 1.4）：
- 插件默认权限 = 0；manifest 声明权限；管理员启用时批准（可批准子集）
- 权限不是提示文字：**所有 Action 在执行前必须过 PermissionManager.check()**，
  拒绝一律记日志（plugin_permission_denied），由管理员决定是否放开
- 插件永远无法自己决定权限（本模块是唯一检查点，副作用在 manager 执行）

权限集（v1）：
- send_message       发送群/私聊消息
- read_message       接收消息事件（未批准则事件不投递给插件）
- read_group_info    读取群信息（get_group）
- read_user_info     读取用户信息（get_user）
- read_memory        读取记忆（get_memory）
- write_memory       写入记忆（write_memory）
- http_request       发起受限 HTTP 请求（SSRF 防护）
- filesystem_read    插件目录只读访问（file_read）
- filesystem_write   插件目录写访问（file_write）
- execute_process    执行进程 —— **保留定义，v1 无对应 Action**（一律拒绝）
- webhook            外部 Webhook —— **保留定义，v1 无对应 Action**（一律拒绝）

保留权限说明：为 API 兼容而定义并参与校验，但 v1 未实现任何执行路径；
即使管理员批准，运行时 Action 检查也会返回 "not supported in v1"。
"""
from typing import Dict, Optional

# 完整权限集（manifest 校验 + 运行时检查共用）
ALL_PERMISSIONS = frozenset({
    "send_message",
    "read_message",
    "read_group_info",
    "read_user_info",
    "read_memory",
    "write_memory",
    "http_request",
    "filesystem_read",
    "filesystem_write",
    "execute_process",
    "webhook",
    "delete_message",        # 撤回（仅限本 bot 发送过的消息）
    "read_message_history",  # 消息详情/群历史/上下文读取
    "group_manage",          # 群管理写操作（禁言/踢人/管理员）
    "request_handle",        # 好友/加群请求处理（approve/deny）
    "scheduler",             # 定时任务（interval/delay/daily）
    "storage",               # 插件 KV 存储
    "ai_chat",               # 受限 AI 对话（独立于聊天预算，务必自限频）
    "bot_profile",           # 修改 Bot 自身资料（昵称/签名）
    "plugin_admin",          # 插件运行时管理（调用/事件/服务/重载/发现/健康/配置）
    "web_ui",                # Plugin WebUI：插件自有管理页面（管理员批准后才能访问）
    "web_ui.files",          # Plugin WebUI 文件能力（上传/下载，仅插件自身空间）
})

# Action 类型 → 所需权限（None = 无需权限：log / test 等无害动作）
ACTION_PERMISSIONS: Dict[str, Optional[str]] = {
    "send_message": "send_message",
    "send_reply": "send_message",
    "delete_message": "delete_message",
    "get_message": "read_message_history",
    "get_group_history": "read_message_history",
    "get_context": "read_message_history",
    "get_group_member": "read_group_info",
    "get_group_members": "read_group_info",
    "group_ban": "group_manage",
    "group_kick": "group_manage",
    "group_admin": "group_manage",
    "matcher_register": "read_message",
    "is_group_admin": "read_group_info",
    "is_group_owner": "read_group_info",
    "handle_friend_request": "request_handle",
    "handle_group_request": "request_handle",
    "schedule_register": "scheduler",
    "schedule_cancel": "scheduler",
    "schedule_list": "scheduler",
    "kv_get": "storage",
    "kv_set": "storage",
    "kv_delete": "storage",
    "kv_list": "storage",
    "ai_chat": "ai_chat",
    "mem_update": "read_memory",
    "mem_clear": "read_memory",
    "random_choice": None,
    "random_int": None,
    "now": None,
    "format_time": None,
    "tap": "read_group_info",          # 戳一戳（对群成员）
    "react": "read_message",           # 表情回应（需消息 id）
    "pin": "group_manage",             # 精华消息
    "unpin": "group_manage",
    "like": "read_user_info",          # 点赞
    "friends": "read_user_info",       # 好友列表
    "login_info": "read_user_info",    # 登录信息
    "devices": "read_user_info",       # 在线设备
    "status": "read_user_info",        # 运行状态
    "db_query": "storage",
    "db_transaction": "storage",
    "db_migration": "storage",
    "db_index": "storage",
    "cache_get": "storage",
    "cache_set": "storage",
    "cache_delete": "storage",
    "task_status": "plugin_admin",
    "task_cancel": "plugin_admin",
    "task_pause": "plugin_admin",
    "task_resume": "plugin_admin",
    "resource_usage": "plugin_admin",
    "resource_quota": "plugin_admin",
    "runtime_status": "plugin_admin",
    "metrics": "plugin_admin",
    "trace": "plugin_admin",
    "health": "plugin_admin",
    "debug": "plugin_admin",
    "plugin_test": "plugin_admin",
    "mock_api": "plugin_admin",
    "plugin_call": "plugin_admin",
    "plugin_event": "plugin_admin",
    "plugin_service": "plugin_admin",
    "plugin_discovery": "plugin_admin",
    "plugin_dependency": "plugin_admin",
    "plugin_health": "plugin_admin",
    "plugin_reload": "plugin_admin",
    "plugin_config": "plugin_admin",
    "router": "plugin_admin",
    "ws": "plugin_admin",
    "sse": "plugin_admin",
    "http_middleware": "plugin_admin",
    "static_file": "plugin_admin",
    "memory_get": "read_memory",
    "memory_search": "read_memory",
    "memory_semantic": "read_memory",
    "memory_update": "write_memory",
    "memory_delete": "write_memory",
    "memory_tag": "storage",
    "memory_pin": "write_memory",
    "memory_expire": "read_memory",
    "mcp_server": "http_request",
    "mcp_tools": "http_request",
    "mcp_call": "http_request",
    "mcp_resource": "http_request",
    "mcp_prompt": "http_request",
    "mcp_status": "http_request",
    "ai_stream": "ai_chat",
    "ai_vision": "ai_chat",
    "ai_embedding": "ai_chat",
    "ai_rerank": "ai_chat",
    "ai_token": "ai_chat",
    "ai_models": "ai_chat",
    "ai_model_info": "ai_chat",
    "ai_usage": "ai_chat",
    "ai_budget": "ai_chat",
    "reaction": "send_message",
    "poke": "send_message",
    "emoji": "send_message",
    "emoji_list": "read_message_history",
    "file_upload": "filesystem_write",
    "file_download": "filesystem_read",
    "file_info": "filesystem_read",
    "file_delete": "filesystem_write",
    "file_convert": "filesystem_read",
    "image_compress": "filesystem_read",
    "image_resize": "filesystem_read",
    "image_screenshot": "filesystem_read",
    "audio_info": "filesystem_read",
    "video_info": "filesystem_read",
    "group_member_search": "read_group_info",
    "group_member_update": "group_manage",
    "group_mute_status": "read_group_info",
    "group_notice_create": "group_manage",
    "group_notice_update": "group_manage",
    "group_file_upload": "group_manage",
    "group_file_rename": "group_manage",
    "group_essence": "read_group_info",
    "group_invite": "group_manage",
    "group_apply": "request_handle",
    "group_admins": "read_group_info",
    "edit_message": "delete_message",      # 编辑消息（同撤回级敏感）
    "forward_message": "send_message",     # 转发（发送动作）
    "split_message": "read_message",       # 拆段（纯本地）
    "merge_message": "send_message",       # 合并（发送动作）
    "favorite_message": "read_message_history",
    "mark_message": "delete_message",      # 标记（同消息管理级）
    "read_status": "read_message_history",
    "search_message": "read_message_history",
    "quote_chain": "read_message_history",
    "friend_detail": "read_user_info",
    "friend_remark": "read_user_info",     # 备注（写；同用户信息级）
    "friend_delete": "read_user_info",
    "friend_group": "read_user_info",
    "friend_category": "read_user_info",
    "friend_online": "read_user_info",
    "profile_set": "bot_profile",      # 改 Bot 资料
    "group_whole_ban": "group_manage",
    "group_rename": "group_manage",
    "group_card": "group_manage",
    "group_title": "group_manage",
    "group_notice_send": "group_manage",
    "group_notice_get": "read_group_info",
    "group_files": "read_group_info",
    "group_files_in": "read_group_info",
    "group_file_url": "read_group_info",
    "group_config": "read_group_info",
    "group_config_set": "group_manage",
    "group_res": "read_group_info",
    # v1.7.0 拉格朗日补齐（读→read_*，写→group_manage）
    "user_history": "read_user_info",        # 好友/私聊消息历史
    "user_forward": "read_user_info",        # 私聊合并转发
    "user_poke": "read_user_info",           # 私聊戳
    "essence_list": "read_group_info",       # 精华列表
    "group_honor": "read_group_info",        # 群荣誉
    "group_notice_delete": "group_manage",   # 删公告
    "group_portrait": "group_manage",        # 改群头像
    "group_info": "read_group_info",
    "group_list": "read_group_info",
    "group_forward": "group_manage",         # 群合并转发
    "group_folder_create": "group_manage",
    "group_file_delete": "group_manage",
    "group_folder_delete": "group_manage",
    "group_file_move": "group_manage",
    "group_folder_rename": "group_manage",
    "http_put": "http_request",
    "http_delete": "http_request",
    "http_head": "http_request",
    "http_download": "http_request",
    "send_private_message": "send_message",
    "get_group": "read_group_info",
    "get_group_info": "read_group_info",
    "get_user": "read_user_info",
    "get_memory": "read_memory",
    "write_memory": "write_memory",
    "http_request": "http_request",
    "file_read": "filesystem_read",
    "file_write": "filesystem_write",
    "execute_process": "execute_process",
    "webhook": "webhook",
    "log": None,
    "test": None,
}

# v1 未实现的保留 Action（即使权限已批准也拒绝执行）
_UNIMPLEMENTED = frozenset({"execute_process", "webhook"})
# 内建无副作用动作：任何权限组合下都允许（仅日志/测试探针，无外部副作用）
_BUILTIN_ACTIONS = frozenset({"log", "test"})


class PermissionDeniedError(Exception):
    """权限被拒绝（含拒绝原因，供日志/测试断言）。"""

    def __init__(self, action: str, permission: str, plugin_id: str = ""):
        self.action = action
        self.permission = permission
        self.plugin_id = plugin_id
        super().__init__(
            f"plugin {plugin_id or '?'} action {action!r} requires permission {permission!r} (denied)"
        )


class PermissionManager:
    """单个插件的运行时权限门（管理员批准集 + 保护级别）。

    保护级别只影响**资源限制与预留动作**，不影响权限强制：
    - normal：默认（完整限制）
    - relaxed：放宽非必要限制（超时/输出/动作数）
    - unsafe：管理员明确确认，保留全部安全不变式（安装完整性/manifest 校验/
      管理员权限/进程隔离/日志/崩溃保护/资源限制/权限检查），仅更宽限制
    """

    PROTECTION_LEVELS = ("normal", "relaxed", "unsafe")

    def __init__(self, approved_permissions, protection: str = "normal"):
        self.approved = frozenset(str(p).strip().lower() for p in (approved_permissions or []) if p)
        self.protection = protection if protection in self.PROTECTION_LEVELS else "normal"

    def has(self, permission: str) -> bool:
        return permission in self.approved

    def check(self, action: str) -> bool:
        """Action 能否执行（运行时唯一检查点）。"""
        if action in _UNIMPLEMENTED:
            return False  # v1 不支持：即使批准也拒绝（诚实接口）
        permission = ACTION_PERMISSIONS.get(action)
        if permission is None:
            # 白名单原则：内建动作（log/test/工具类：随机/时间）放行；未知 action 一律拒绝
            return action in _BUILTIN_ACTIONS or action in ACTION_PERMISSIONS
        return permission in self.approved

    def denied_reason(self, action: str) -> str:
        if action in _UNIMPLEMENTED:
            return f"action {action!r} 在 Plugin API v1 未实现（保留权限）"
        permission = ACTION_PERMISSIONS.get(action)
        if permission is None:
            return "" if (action in _BUILTIN_ACTIONS or action in ACTION_PERMISSIONS) \
                else "未知 action，不允许执行（白名单外）"
        return f"需要权限 {permission!r}（管理员未批准）"

    # ---------- 保护级别对应的资源限制 ----------
    @staticmethod
    def limits(protection: str) -> Dict[str, float]:
        """保护级别 → 资源限制表（不同级别放宽限制，不变式保持）。"""
        if protection == "unsafe":
            # 仅可信插件：超时/输出/动作数放宽；仍过权限检查与日志
            return {"event_timeout": 120.0, "startup_timeout": 30.0,
                    "max_actions": 32, "max_output_bytes": 4 * 1024 * 1024}
        if protection == "relaxed":
            return {"event_timeout": 60.0, "startup_timeout": 20.0,
                    "max_actions": 16, "max_output_bytes": 1024 * 1024}
        return {"event_timeout": 15.0, "startup_timeout": 10.0,
                "max_actions": 8, "max_output_bytes": 256 * 1024}
