"""Web UI 配置分类常量（单源；无 pydantic 依赖——config_schema 与渲染层共用）。"""

CATEGORY_ORDER = [
    "AI", "Bot", "Connection", "Behavior", "Stability", "Memory", "LivingMemory", "Context",
    "Sticker", "MCP", "WebUI", "Logging", "Budget", "ActiveChat", "Repeat",
    "Poke", "FileParse", "Security", "Whitelist", "Archive", "Paths",
    # 注意：Persona/Knowledge/Plugin 分类的配置项已在 SCHEMA 中，但不在配置页展示——
    # 它们由「人格」「群聊知识」「插件」页的专属配置区块管理（见 webui_panels/* 等）
]

CATEGORY_LABELS = {
    "AI": "AI / Provider 配置",
    "Bot": "基础配置",
    "Connection": "QQ / OneBot 连接",
    "Behavior": "行为与回复",
    "Stability": "稳定性与熔断",
    "Memory": "记忆库",
    "LivingMemory": "高级记忆（默认关闭）",
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
    "Security": "安全与资源限制",
    "Whitelist": "白名单与隐私",
    "Archive": "消息存档",
    "Paths": "数据路径",
    "Persona": "人格（Persona）",
    "Knowledge": "群聊知识（Meme）",
    "Plugin": "插件系统",
}
