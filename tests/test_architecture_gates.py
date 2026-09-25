"""架构 Gate 静态审计（任务书 B 部分 Gate A / B / P / T）——把"低耦合"变成可执行检查。

约定与 tests/test_milky_mapping.py 的 KNOWN_BYPASS 一致：**基线只允许缩小**。
实际值 > 基线 → 失败（新增耦合）；实际值 < 基线 → 也失败（提示更新基线，避免"悄悄变好没人知道"）。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN_DIRS = ("src/core", "src/services", "src/sdk", "src/plugins")
PROTOCOL_WORDS = r"(onebot|milky|napcat|lagrange|snowluma|llbot|koishi|nonebot|shamrock)"

# ---- Gate A：Core/Services/SDK/Plugins 里的具体协议/客户端 import（基线，只许减少）----
# 剩余项都是已知待拆：src/sdk/onebot/ 子树（Gate T/§34）与 plugins/manager 对它的引用。
KNOWN_PROTOCOL_IMPORTS = {
    "src/plugins/manager.py|from src.sdk.onebot.adapter import OneBotAdapter",
    "src/sdk/onebot/adapter.py|from src.sdk.onebot.transformer import to_bot_message_payload",
    "src/sdk/onebot/transformer.py|from src.sdk.onebot.dto import EventDTO",
}

# ---- Gate B：协议分支（Core 应为 0；sender.py 是待下沉到 Adapter 的出口）----
KNOWN_PROTOCOL_BRANCHES = {
    "src/services/sender.py:115|if self._milky:",
    "src/services/sender.py:148|if self._use_ws:",
    "src/services/sender.py:288|if self._milky:",
}

# ---- Gate P：services 层的 aiohttp 使用（Web UI 应用服务器 + 消息发送出口；core 必须为 0）----
KNOWN_SERVICES_AIOHTTP = {
    "src/services/sender.py",
    "src/services/web_ui.py",
    "src/services/webui_static.py",
    "src/services/webui_panels/account_panel.py",
    "src/services/webui_panels/appearance_panel.py",
    "src/services/webui_panels/auth_panel.py",
    "src/services/webui_panels/config_panel.py",
    "src/services/webui_panels/knowledge_panel.py",
    "src/services/webui_panels/mcp_panel.py",
    "src/services/webui_panels/nickname_panel.py",
    "src/services/webui_panels/persona_panel.py",
    "src/services/webui_panels/plugin_panel.py",
    "src/services/webui_panels/prompt_panel.py",
}


def _py_files(*dirs):
    for d in dirs:
        base = os.path.join(ROOT, d)
        for dirpath, _dirnames, filenames in os.walk(base):
            for name in filenames:
                if name.endswith(".py"):
                    yield os.path.relpath(os.path.join(dirpath, name), ROOT)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def test_gate_a_core_services_sdk_plugins_have_no_new_protocol_imports():
    found = set()
    pattern = re.compile(r"^\s*(?:import|from)\s+\S*" + PROTOCOL_WORDS, re.IGNORECASE)
    for rel in _py_files(*SCAN_DIRS):
        for line in _read(rel).splitlines():
            if pattern.match(line):
                found.add(rel + "|" + line.strip())
    grew = sorted(found - KNOWN_PROTOCOL_IMPORTS)
    assert grew == [], "新增了协议/客户端 import（应放进 Adapter/Transport）：%s" % grew
    shrank = sorted(KNOWN_PROTOCOL_IMPORTS - found)
    assert shrank == [], "基线已过期（这些耦合已消失，请更新 KNOWN_PROTOCOL_IMPORTS）：%s" % shrank


def test_gate_b_protocol_branches_baseline_only_shrinks():
    found = set()
    pattern = re.compile(r"if\s+(?:self\._milky|self\._use_ws|protocol\s*==|qq_protocol\s*==)")
    for rel in _py_files(*SCAN_DIRS):
        for lineno, line in enumerate(_read(rel).splitlines(), start=1):
            if pattern.search(line):
                found.add("%s:%d|%s" % (rel, lineno, line.strip()))
    grew = sorted(found - KNOWN_PROTOCOL_BRANCHES)
    assert grew == [], "新增协议分支（应移到 Adapter/Capability Resolver）：%s" % grew
    shrank = sorted(KNOWN_PROTOCOL_BRANCHES - found)
    assert shrank == [], "基线已过期（协议分支已减少，请更新 KNOWN_PROTOCOL_BRANCHES）：%s" % shrank


def test_gate_p_core_has_no_transport_imports():
    offenders = []
    for rel in _py_files("src/core"):
        for lineno, line in enumerate(_read(rel).splitlines(), start=1):
            if re.match(r"^\s*(?:import|from)\s+(websockets|aiohttp)\b", line):
                offenders.append("%s:%d" % (rel, lineno))
    assert offenders == [], "Core 不得 import 传输库：%s" % offenders


def test_gate_p_services_transport_usage_baseline_only_shrinks():
    found = {rel for rel in _py_files("src/services")
             if re.search(r"^\s*(?:import|from)\s+(websockets|aiohttp)\b",
                          _read(rel), re.MULTILINE)}
    grew = sorted(found - KNOWN_SERVICES_AIOHTTP)
    assert grew == [], "services 层新增传输依赖（协议传输应放 src/transport/）：%s" % grew
    shrank = sorted(KNOWN_SERVICES_AIOHTTP - found)
    assert shrank == [], "基线已过期（请更新 KNOWN_SERVICES_AIOHTTP）：%s" % shrank


def test_gate_a_core_has_no_client_named_modules():
    names = [os.path.basename(p) for p in _py_files("src/core")]
    bad = sorted(n for n in names if re.search(PROTOCOL_WORDS, n, re.IGNORECASE))
    assert bad == [], "Core 中不得有以客户端/协议命名的模块（应放 Adapter/Transport）：%s" % bad


def test_transport_package_exists_and_is_the_only_websockets_user():
    # Gate P 的收敛方向：传输库只应出现在 src/transport/（与基线白名单）
    users = {rel for rel in _py_files("src")
             if re.search(r"^\s*(?:import|from)\s+websockets\b", _read(rel), re.MULTILINE)}
    outside = sorted(u for u in users if not u.startswith("src/transport/"))
    assert outside == [], "websockets 只允许出现在 src/transport/：%s" % outside
    assert users, "src/transport/ 应当包含 websockets 使用者（否则本检查失去意义）"
