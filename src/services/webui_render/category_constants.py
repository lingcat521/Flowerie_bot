"""Web UI 配置分类常量（单源；无 pydantic 依赖——config_schema 与渲染层共用）。"""

CATEGORY_GROUPS = (
    ("接入与模型", ("Bot", "Connection", "AI")),
    ("回复与互动", ("Behavior", "ActiveChat", "Repeat", "Poke", "Sticker", "PrivateChat")),
    ("内容处理", ("FileParse", "Vision", "Forward", "MCP", "Search")),
    ("上下文与数据", ("Context", "Memory", "BlossomMemory", "Archive", "Paths")),
    ("权限与运行维护", ("Whitelist", "Admin", "Budget", "Stability", "Security", "Logging", "WebUI")),
)
# 专页管理的 Persona / Knowledge / Plugin / Automation 不在通用配置区展示。
CATEGORY_ORDER = [category for _, categories in CATEGORY_GROUPS for category in categories]

CATEGORY_LABELS = {
    "AI": "AI / Provider 配置",
    "Bot": "基础配置",
    "Connection": "QQ / OneBot 连接",
    "Behavior": "行为与回复",
    "Stability": "稳定性与熔断",
    "Memory": "记忆库",
    "BlossomMemory": "花语记忆（默认关闭）",
    "Context": "上下文",
    "Sticker": "表情包",
    "MCP": "MCP 工具",
    "WebUI": "Web UI",
    "Logging": "日志",
    "Budget": "预算与限额",
    "ActiveChat": "主动聊天",
    "Repeat": "复读与防刷",
    "Poke": "戳戳",
    "FileParse": "文件解析",
    "Vision": "识图与图片限制",
    "Forward": "合并转发",
    "Security": "安全与资源限制",
    "Whitelist": "白名单与隐私",
    "Archive": "消息存档",
    "Paths": "数据路径",
    "Persona": "人格（Persona）",
    "Knowledge": "群聊知识（Meme）",
    "Plugin": "插件系统",
    "Admin": "群管理控制台",
    "Qzone": "QQ空间",
    "PrivateChat": "私聊",
    "Search": "网页搜索",
    "Automation": "自动化",
}
