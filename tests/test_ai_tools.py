"""v2.12.0 AI 内置工具层：QQ空间（识图选图）/ 群管理护栏 / 记忆 / 自主发动态。"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.ai_tools import AiToolRegistry  # noqa: E402
from src.services.qzone_auto import QzoneAutoPoster, extract_json_object  # noqa: E402
from src.services.reply_tool import ReplyToolCapture, make_tool_caller  # noqa: E402


class _Cfg:
    AI_QZONE_ENABLED = True
    AI_QZONE_MAX_PER_DAY = 1
    AI_ADMIN_ENABLED = True
    AI_MEMORY_ENABLED = True
    AI_SEARCH_ENABLED = True
    QZONE_IMAGE_MAX = 50
    QZONE_IMAGE_DESCRIBE_LIMIT = 12
    BOT_QQ = 10000


class _Vision:
    def __init__(self):
        self.calls = []

    async def describe_image_file(self, path):
        self.calls.append(path)
        return "一张%s的图片" % os.path.basename(path).split(".")[0]


class _Qzone:
    def __init__(self):
        self.published = []
        self.deleted = []
        self.items = []

    def default_ugc_right(self):
        return 1

    def history(self):
        return list(self.items)

    async def publish(self, content, images=None, ugc_right=None, target_uins=None):
        self.published.append((content, list(images or []), ugc_right))
        return {"ok": True, "tid": "T-AI"}

    async def delete(self, tid):
        self.deleted.append(tid)
        return {"ok": True, "tid": tid}


class _Admin:
    def __init__(self, bot="admin", caller="admin"):
        self.bot = bot
        self.caller = caller
        self.bans = []

    async def bot_role(self, group_id, fresh=False):
        return self.bot

    async def member_role(self, group_id, user_id, fresh=False):
        return self.caller

    async def ban(self, group_id, user_id, duration=0):
        self.bans.append((group_id, user_id, duration))
        return {"ok": True}


class _Memory:
    def get_user_notes(self, user_id, group_id):
        return ["喜欢喝奶茶", "在学吉他"]


def _registry(tmp_path, **kw):
    cfg = kw.pop("cfg", None) or _Cfg()
    vision = kw.pop("vision", None)
    qzone = kw.pop("qzone", None) or _Qzone()
    admin = kw.pop("admin", None) or _Admin()
    memory = kw.pop("memory", None) or _Memory()
    image_dir = tmp_path / "images"
    image_dir.mkdir(exist_ok=True)
    reg = AiToolRegistry(cfg, qzone_service=qzone, admin_service=admin, memory_manager=memory,
                         vision=vision, image_dir=str(image_dir),
                         index_path=str(tmp_path / "index.json"))
    return reg, qzone, admin, image_dir


def _touch(image_dir, name):
    p = image_dir / name
    p.write_bytes(b"x" * 16)
    return p


# ---------- 开关与 schema ----------
def test_tools_disabled_by_default(tmp_path):
    class Off(_Cfg):
        AI_QZONE_ENABLED = False
        AI_ADMIN_ENABLED = False
        AI_MEMORY_ENABLED = False
    reg, *_ = _registry(tmp_path, cfg=Off())
    assert reg.enabled() is False
    assert reg.schemas() == []
    assert reg.tool_names() == []


def test_tools_schemas_listed(tmp_path):
    reg, *_ = _registry(tmp_path)
    names = [d["function"]["name"] for d in reg.schemas()]
    assert names == ["qzone_list_images", "qzone_post", "qzone_delete",
                     "group_status", "group_mute", "group_unmute", "memory_recall"]
    assert reg.enabled() is True


# ---------- 图片池 + 识图缓存 ----------
@pytest.mark.asyncio
async def test_describe_pool_uses_vision_and_caches(tmp_path):
    vision = _Vision()
    reg, _q, _a, image_dir = _registry(tmp_path, vision=vision)
    _touch(image_dir, "cat.png")
    _touch(image_dir, "coffee.jpg")
    items = await reg.describe_pool()
    assert {it["id"] for it in items} == {"cat.png", "coffee.jpg"}
    assert all(it["desc"] for it in items)
    first_calls = len(vision.calls)
    assert first_calls == 2
    items2 = await reg.describe_pool()
    assert len(vision.calls) == first_calls
    assert {it["id"] for it in items2} == {"cat.png", "coffee.jpg"}
    assert (tmp_path / "index.json").exists()


def test_resolve_images_rejects_traversal(tmp_path):
    reg, _q, _a, image_dir = _registry(tmp_path)
    _touch(image_dir, "ok.png")
    out = reg.resolve_images(["ok.png", "../secret.png", "missing.png", ""])
    assert out == ["file://" + str(image_dir / "ok.png")]


@pytest.mark.asyncio
async def test_qzone_list_images_empty_pool(tmp_path):
    reg, *_ = _registry(tmp_path, vision=_Vision())
    payload = await reg.call_tool("qzone_list_images", {})
    data = json.loads(payload)
    assert data["ok"] is False and "图片池为空" in data["error"]


# ---------- 发说说：成功 / 每日上限 ----------
@pytest.mark.asyncio
async def test_qzone_post_success_and_daily_cap(tmp_path):
    reg, qzone, _a, image_dir = _registry(tmp_path, vision=_Vision())
    _touch(image_dir, "cat.png")
    data = json.loads(await reg.call_tool("qzone_post", {"content": "今天天气不错", "images": ["cat.png"]}))
    assert data == {"ok": True, "tid": "T-AI"}
    assert qzone.published[-1][0] == "今天天气不错"
    assert qzone.published[-1][1] == ["file://" + str(image_dir / "cat.png")]
    qzone.items = [{"tid": "T-AI", "ts": 9e18}]
    data2 = json.loads(await reg.call_tool("qzone_post", {"content": "再来一条"}))
    assert data2["ok"] is False and "额度" in data2["error"]


@pytest.mark.asyncio
async def test_qzone_post_validation(tmp_path):
    reg, qzone, _a, _i = _registry(tmp_path)
    assert json.loads(await reg.call_tool("qzone_post", {"content": ""}))["ok"] is False
    assert json.loads(await reg.call_tool("qzone_post", {"content": "x" * 2001}))["ok"] is False
    assert qzone.published == []


# ---------- 群管理护栏 ----------
@pytest.mark.asyncio
async def test_group_mute_requires_caller_admin(tmp_path):
    reg, _q, admin, _i = _registry(tmp_path, admin=_Admin(bot="admin", caller="member"))
    reg.bind_context(200, 7)
    data = json.loads(await reg.call_tool("group_mute", {"qq": 123456, "minutes": 5}))
    assert data["ok"] is False and "群主/管理员" in data["error"]
    assert admin.bans == []


@pytest.mark.asyncio
async def test_group_mute_requires_bot_admin(tmp_path):
    reg, _q, admin, _i = _registry(tmp_path, admin=_Admin(bot="member", caller="owner"))
    reg.bind_context(200, 7)
    data = json.loads(await reg.call_tool("group_mute", {"qq": 123456}))
    assert data["ok"] is False and "没有管理权限" in data["error"]
    assert admin.bans == []


@pytest.mark.asyncio
async def test_group_mute_success_clamps_minutes(tmp_path):
    reg, _q, admin, _i = _registry(tmp_path)
    reg.bind_context(200, 7)
    data = json.loads(await reg.call_tool("group_mute", {"qq": 123456, "minutes": 5000}))
    assert data["ok"] is True
    assert admin.bans == [(200, 123456, 1440 * 60)]


@pytest.mark.asyncio
async def test_group_mute_refuses_self(tmp_path):
    reg, _q, admin, _i = _registry(tmp_path)
    reg.bind_context(200, 7)
    assert json.loads(await reg.call_tool("group_mute", {"qq": 10000}))["ok"] is False
    assert json.loads(await reg.call_tool("group_mute", {"qq": 7}))["ok"] is False
    assert admin.bans == []


@pytest.mark.asyncio
async def test_group_unmute_zero_duration_and_status(tmp_path):
    reg, _q, admin, _i = _registry(tmp_path, admin=_Admin(bot="admin", caller="owner"))
    reg.bind_context(200, 7)
    assert json.loads(await reg.call_tool("group_unmute", {"qq": 123456}))["ok"] is True
    assert admin.bans == [(200, 123456, 0)]
    status = json.loads(await reg.call_tool("group_status", {}))
    assert status["bot_can_manage"] is True and status["caller_can_manage"] is True


# ---------- 记忆 ----------
@pytest.mark.asyncio
async def test_memory_recall(tmp_path):
    reg, *_ = _registry(tmp_path)
    reg.bind_context(200, 7)
    data = json.loads(await reg.call_tool("memory_recall", {}))
    assert data["ok"] is True and "喜欢喝奶茶" in data["notes"]
    reg.bind_context(0, 0)
    assert json.loads(await reg.call_tool("memory_recall", {}))["ok"] is False


# ---------- 未知工具与工具链 ----------
@pytest.mark.asyncio
async def test_unknown_tool_returns_none(tmp_path):
    reg, *_ = _registry(tmp_path)
    assert await reg.call_tool("mcp_something", {}) is None


@pytest.mark.asyncio
async def test_tool_caller_chain_builtin_then_mcp(tmp_path):
    reg, *_ = _registry(tmp_path)
    reg.bind_context(200, 7)
    capture = ReplyToolCapture()
    calls = []

    async def mcp(name, args):
        calls.append(name)
        return "mcp:%s" % name

    caller = make_tool_caller(capture, mcp, extra=reg.call_tool)
    out = await caller("memory_recall", {})
    assert "喜欢喝奶茶" in out and calls == []
    out2 = await caller("mcp_search", {"q": "x"})
    assert out2 == "mcp:mcp_search" and calls == ["mcp_search"]
    out3 = await caller("reply", {"messages": ["hi"]})
    assert "已记录" in out3




# ---------- 网页搜索工具（v2.15.0） ----------

class _SearchSvc:
    def __init__(self):
        self.queries = []
        self.urls = []

    def enabled(self):
        return True

    async def search(self, query, time_range=None, engine=None):
        self.queries.append((query, time_range, engine))
        return {"ok": True, "sources": [{"url": "https://x.com/1", "title": "T", "snippet": "S"}],
                "engine": "ddg", "engines_used": ["ddg"]}

    async def fetch_page(self, url, max_chars=2000):
        self.urls.append((url, max_chars))
        return {"ok": True, "url": url, "title": "页", "text": "正文", "truncated": False}


def _search_registry(tmp_path, cfg=None):
    from src.services.web_search import WebSearchService
    reg, *_ = _registry(tmp_path, cfg=cfg)
    reg.search = _SearchSvc()
    return reg


def test_search_tools_off_by_default(tmp_path):
    class Off(_Cfg):
        AI_QZONE_ENABLED = False
        AI_ADMIN_ENABLED = False
        AI_MEMORY_ENABLED = False
        AI_SEARCH_ENABLED = False
    reg, *_ = _registry(tmp_path, cfg=Off())
    reg.search = _SearchSvc()
    assert reg.enabled() is False
    assert reg.schemas() == []


def test_search_tools_off_without_service(tmp_path):
    # 无服务注入：即使 AI_SEARCH_ENABLED=true 也不注册（双闸）；其他工具不受影响
    reg, *_ = _registry(tmp_path)
    assert reg.search is None
    assert reg.search_enabled() is False
    names = [d["function"]["name"] for d in reg.schemas()]
    assert "web_search" not in names and "web_fetch" not in names
    assert len(names) == 7  # qzone*3 + admin*3 + memory*1 照常注册


def test_search_schemas_listed(tmp_path):
    reg = _search_registry(tmp_path)
    names = [d["function"]["name"] for d in reg.schemas() if "web_" in d["function"]["name"]]
    assert names == ["web_search", "web_fetch"]
    # schema 必填字段齐备
    schemas = {d["function"]["name"]: d["function"] for d in reg.schemas()}
    assert schemas["web_search"]["parameters"]["required"] == ["query"]
    assert schemas["web_fetch"]["parameters"]["required"] == ["url"]


def test_search_tool_names(tmp_path):
    reg = _search_registry(tmp_path)
    assert "web_search" in reg.tool_names() and "web_fetch" in reg.tool_names()


@pytest.mark.asyncio
async def test_web_search_handler_calls_service(tmp_path):
    reg = _search_registry(tmp_path)
    out = await reg.call_tool("web_search", {"query": "今天天气", "timeRange": "day"})
    import json
    d = json.loads(out)
    assert d["ok"] is True
    assert reg.search.queries == [("今天天气", "day", None)]


@pytest.mark.asyncio
async def test_web_search_handler_rejects_empty(tmp_path):
    reg = _search_registry(tmp_path)
    out = await reg.call_tool("web_search", {"query": "   "})
    import json
    assert json.loads(out)["ok"] is False


@pytest.mark.asyncio
async def test_web_fetch_handler_clamps_chars(tmp_path):
    class C(_Cfg):
        SEARCH_FETCH_MAX_CHARS = 99999
    reg = _search_registry(tmp_path, cfg=C())
    out = await reg.call_tool("web_fetch", {"url": "https://x.com/p"})
    import json
    assert json.loads(out)["ok"] is True
    # clamped 到 8000 上限
    assert reg.search.urls == [("https://x.com/p", 8000)]


@pytest.mark.asyncio
async def test_unknown_search_tool_returns_none(tmp_path):
    reg = _search_registry(tmp_path)
    assert await reg.call_tool("web_search_pro", {}) is None


def test_build_tool_prompt_includes_search(tmp_path):
    from src.services.ai_tools import build_tool_prompt
    reg = _search_registry(tmp_path)
    p = build_tool_prompt(reg)
    assert "web_search" in p and "web_fetch" in p
    assert "不可信" in p  # 外部数据警示


def test_build_tool_prompt_excludes_search_when_off(tmp_path):
    class Off(_Cfg):
        AI_QZONE_ENABLED = False
        AI_ADMIN_ENABLED = False
        AI_MEMORY_ENABLED = False
        AI_SEARCH_ENABLED = False
    from src.services.ai_tools import build_tool_prompt
    reg, *_ = _registry(tmp_path, cfg=Off())
    reg.search = _SearchSvc()
    assert "web_search" not in build_tool_prompt(reg)


# ---------- 自主发动态 ----------
def test_extract_json_object_tolerates_noise():
    assert extract_json_object('好的：{"content":"hi","images":[]} 以上')["content"] == "hi"
    assert extract_json_object("~~~json\n{\"content\": \"x\"}\n~~~")["content"] == "x"
    assert extract_json_object("没有 json") is None
    assert extract_json_object('{"bad": }') is None


class _RegistryForAuto:
    def __init__(self, items):
        self.items = items
        self.published = []

    def qzone_enabled(self):
        return True

    async def describe_pool(self):
        return self.items

    async def call_tool(self, name, payload):
        self.published.append((name, payload))
        return json.dumps({"ok": True, "tid": "T-AUTO"})


@pytest.mark.asyncio
async def test_auto_poster_publishes_parsed_json():
    reg = _RegistryForAuto([{"id": "cat.png", "desc": "一只猫", "size_kb": 1}])

    async def chat(group_id, user_id, user_message="", context="", is_mentioned=False):
        return '好的 {"content": "今天的云很好看", "images": ["cat.png"]}', None, False

    poster = QzoneAutoPoster(_Cfg(), lambda: reg, chat)
    result = await poster.once()
    assert result == {"ok": True, "tid": "T-AUTO"}
    assert reg.published[0] == ("qzone_post", {"content": "今天的云很好看", "images": ["cat.png"]})


@pytest.mark.asyncio
async def test_auto_poster_skips_empty_pool_and_bad_json():
    reg = _RegistryForAuto([])

    async def chat(*a, **k):
        return "hi", None, False

    assert await QzoneAutoPoster(_Cfg(), lambda: reg, chat).once() is None
    reg.items = [{"id": "cat.png", "desc": "猫", "size_kb": 1}]

    async def chat2(*a, **k):
        return "我不想输出 JSON", None, False

    assert await QzoneAutoPoster(_Cfg(), lambda: reg, chat2).once() is None
    assert reg.published == []


@pytest.mark.asyncio
async def test_auto_poster_respects_denied():
    reg = _RegistryForAuto([{"id": "cat.png", "desc": "猫", "size_kb": 1}])

    async def chat(*a, **k):
        return None, None, True

    assert await QzoneAutoPoster(_Cfg(), lambda: reg, chat).once() is None
    assert reg.published == []


class _Tasks:
    def __init__(self):
        self.names = []

    def register(self, name, coro):
        self.names.append(name)
        coro.close()


class _FakeRouter:
    def __init__(self, cfg):
        self.config = cfg
        self.task_manager = _Tasks()
        self.ai_tools = None
        self.policy_engine = None
        self.persona_manager = None

    async def guarded_chat(self, *a, **k):
        return None, None, False


def test_attach_auto_poster_registers_task():
    """回归：attach 必须能拿到 config（曾误写成未定义的 config）。"""
    from src.services.qzone_auto import attach_auto_poster

    router = _FakeRouter(_Cfg())
    poster = attach_auto_poster(router)
    assert router.task_manager.names == ["qzone_auto"]
    assert router._qzone_poster is poster


# ---------- 工具使用说明（v2.12.3） ----------
def test_build_tool_prompt_sections(tmp_path):
    from src.services.ai_tools import build_tool_prompt

    reg, *_ = _registry(tmp_path)
    text = build_tool_prompt(reg)
    assert "可用工具" in text and "group_status" in text
    assert "qzone_list_images" in text and "memory_recall" in text
    assert "ok=false" in text


def test_build_tool_prompt_empty_when_disabled(tmp_path):
    from src.services.ai_tools import build_tool_prompt

    class Off(_Cfg):
        AI_QZONE_ENABLED = False
        AI_ADMIN_ENABLED = False
        AI_MEMORY_ENABLED = False

    reg, *_ = _registry(tmp_path, cfg=Off())
    assert build_tool_prompt(reg) == ""
    assert build_tool_prompt(None) == ""


@pytest.mark.asyncio
async def test_gateway_injects_tool_prompt(tmp_path):
    """网关把工具说明拼进 custom_prompt（低优先级补充），并带上内置工具 schema。"""
    from src.core.ai_gateway import AiGateway

    class Cfg(_Cfg):
        MULTI_REPLY_ENABLED = False
        AI_MAX_RETRIES = 0
        MCP_MAX_TOOL_CALLS = 5
        BUDGET_EXHAUSTED_NOTICE = False
        AI_TOOL_PROMPT = True

    class AI:
        _retryable = True
        _api_backoff = 0.0

        def __init__(self):
            self.seen = None

        async def chat_once(self, **kwargs):
            self.seen = kwargs
            return "好", None

    class Budget:
        def check(self, *a, **k):
            return True, "ok"

    reg, *_ = _registry(tmp_path, cfg=Cfg())
    ai = AI()
    gw = AiGateway(Cfg(), ai, Budget(), persona_manager=lambda: None, ai_tools=lambda: reg)
    reply, _mem, denied = await gw.guarded_chat(200, 7, user_message="hi", context="")
    assert reply == "好" and denied is False
    assert "可用工具" in (ai.seen.get("custom_prompt") or "")
    names = [t["function"]["name"] for t in ai.seen.get("tools", [])]
    assert "group_mute" in names and "qzone_post" in names


@pytest.mark.asyncio
async def test_gateway_skips_tool_prompt_when_disabled(tmp_path):
    from src.core.ai_gateway import AiGateway

    class Cfg(_Cfg):
        MULTI_REPLY_ENABLED = False
        AI_MAX_RETRIES = 0
        MCP_MAX_TOOL_CALLS = 5
        BUDGET_EXHAUSTED_NOTICE = False
        AI_TOOL_PROMPT = False

    class AI:
        _retryable = True
        _api_backoff = 0.0

        def __init__(self):
            self.seen = None

        async def chat_once(self, **kwargs):
            self.seen = kwargs
            return "好", None

    class Budget:
        def check(self, *a, **k):
            return True, "ok"

    reg, *_ = _registry(tmp_path, cfg=Cfg())
    ai = AI()
    gw = AiGateway(Cfg(), ai, Budget(), persona_manager=lambda: None, ai_tools=lambda: reg)
    await gw.guarded_chat(200, 7, user_message="hi", context="")
    assert "可用工具" not in (ai.seen.get("custom_prompt") or "")
