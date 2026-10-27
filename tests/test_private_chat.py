"""v2.14.0 私聊：按 QQ 号隔离的上下文/记忆/人格/AI，以及 Web UI 面板。"""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.private_chat import allowed_qqs, handle_private_event, is_allowed, private_key  # noqa: E402
from src.services.webui_render.private_chat import render_private_tab  # noqa: E402


class Cfg:
    PRIVATE_CHAT_ENABLED = True
    PRIVATE_CHAT_ALLOWED_QQS = [20001]
    PRIVATE_CHAT_ALLOW_STRANGERS = False
    PRIVATE_CHAT_COOLDOWN_SECONDS = 0
    PRIVATE_CHAT_CONTEXT_SIZE = 40
    PRIVATE_CHAT_MEMORY_ENABLED = True
    ADMIN_QQ_IDS = [999]
    BOT_QQ = 10000


class State:
    def __init__(self):
        self.processed_msg_ids = []


class Policy:
    def __init__(self):
        self.states = {}
        self.context = []

    def get_group_state(self, key):
        return self.states.setdefault(key, State())

    def add_context(self, key, user_id, text, is_bot=False, digest_text=None):
        self.context.append((key, user_id, text, is_bot))

    def get_context_text(self, key, max_messages=150):
        return ""

    def parse_memory_update(self, memory_update, user_id):
        return int(user_id), str(memory_update)


class Sender:
    def __init__(self):
        self.private = []
        self.group = []

    async def send_private_message(self, user_id, message):
        self.private.append((user_id, message))
        return True

    async def send_group_message(self, group_id, message):
        self.group.append((group_id, message))
        return True


class Assembler:
    def __init__(self, text="", images=None):
        self.text = text
        self.images = images or []

    async def assemble(self, event, user_id, group_id, raw_time):
        return self.text or event.text, self.images, False, False, False


class Commands:
    def __init__(self, handled=False):
        self.handled = handled
        self.calls = []

    async def handle(self, text, user_id, group_id, private_user_id=None):
        self.calls.append((text, user_id, group_id, private_user_id))
        return self.handled


class Memory:
    def __init__(self):
        self.notes = {}

    async def append_memory_text(self, user_id, group_id, text, **kw):
        self.notes.setdefault((user_id, group_id), []).append(text)


class Gateway:
    def __init__(self, reply="喵"):
        self.reply = reply
        self.calls = []

    async def precheck_allowed(self, key, uid):
        return True

    async def guarded_chat(self, key, uid, **kwargs):
        self.calls.append((key, uid, kwargs))
        return self.reply, "记忆更新", False


class Host:
    def __init__(self, cfg=None, reply="喵"):
        self.config = cfg or Cfg()
        self.policy_engine = Policy()
        self.sender = Sender()
        self.assembler = Assembler()
        self.commands = Commands()
        self.memory_manager = Memory()
        self.ai_gateway = Gateway(reply)
        self.sent_replies = []

    async def guarded_chat(self, key, uid, **kwargs):
        return await self.ai_gateway.guarded_chat(key, uid, **kwargs)

    async def _send_reply(self, reply, group_id=None, user_id=None, record_key=None):
        self.sent_replies.append((reply, group_id, user_id, record_key))
        return True


def _event(text="你好", uid=20001, scope="private", scene="friend", mid=1):
    return types.SimpleNamespace(kind="message", scope=scope, scene=scene,
                                actor_id=uid, group_id=None, message_id=mid,
                                timestamp=1700000000, text=text,
                                message_segments=[{"type": "text", "data": {"text": text}}],
                                images=[], image_files=[],
                                is_mentioned=False, mentions=[], reply_id=None)


def test_private_key_and_allowlist():
    catalog = Cfg()
    assert private_key(20001) == -20001
    assert is_allowed(catalog, 20001) is True
    assert is_allowed(catalog, 999) is True       # 管理员自动允许
    assert is_allowed(catalog, 12345) is False
    assert allowed_qqs(catalog) == {20001, 999}


@pytest.mark.asyncio
async def test_private_reply_and_memory_isolated():
    host = Host()
    await handle_private_event(host, _event("你好", uid=20001, mid=1))
    # 回复走私聊、记账/记忆用虚拟 key
    assert host.sent_replies == [("喵", None, 20001, -20001)]
    assert host.ai_gateway.calls[0][0] == -20001
    assert host.memory_manager.notes[(20001, -20001)] == ["记忆更新"]
    # 另一个用户：key 不同、记忆互不可见
    host.config.PRIVATE_CHAT_ALLOWED_QQS = [20001, 20002]
    await handle_private_event(host, _event("在吗", uid=20002, mid=2))
    assert host.ai_gateway.calls[1][0] == -20002
    assert host.memory_manager.notes[(20002, -20002)] == ["记忆更新"]
    assert (20001, -20001) in host.memory_manager.notes


@pytest.mark.asyncio
async def test_private_disabled_and_not_allowed():
    host = Host()
    host.config.PRIVATE_CHAT_ENABLED = False
    await handle_private_event(host, _event())
    assert host.sent_replies == []
    host.config.PRIVATE_CHAT_ENABLED = True
    await handle_private_event(host, _event(uid=12345))
    assert host.sent_replies == []


@pytest.mark.asyncio
async def test_private_stranger_gated():
    host = Host()
    await handle_private_event(host, _event(uid=20001, scope="private", scene="temp"))
    assert host.sent_replies == []
    host.config.PRIVATE_CHAT_ALLOW_STRANGERS = True
    await handle_private_event(host, _event(uid=20001, scope="private", scene="temp", mid=9))
    assert len(host.sent_replies) == 1


@pytest.mark.asyncio
async def test_private_command_routed_with_private_channel():
    host = Host()
    host.commands.handled = True
    await handle_private_event(host, _event("/memory", uid=20001, mid=3))
    assert host.commands.calls == [("/memory", 20001, -20001, 20001)]
    assert host.ai_gateway.calls == []          # 指令已被处理，不再调 AI


@pytest.mark.asyncio
async def test_private_dedup_and_cooldown():
    host = Host()
    await handle_private_event(host, _event("第一次", mid=7))
    await handle_private_event(host, _event("重复", mid=7))
    assert len(host.sent_replies) == 1
    host.config.PRIVATE_CHAT_COOLDOWN_SECONDS = 60
    await handle_private_event(host, _event("太快了", mid=8))
    assert len(host.sent_replies) == 1


@pytest.mark.asyncio
async def test_private_memory_disabled():
    host = Host()
    host.config.PRIVATE_CHAT_MEMORY_ENABLED = False
    await handle_private_event(host, _event(mid=11))
    assert host.memory_manager.notes == {}


@pytest.mark.asyncio
async def test_private_budget_denied_silent():
    host = Host()

    async def denied(*a, **k):
        return None, None, True

    host.guarded_chat = denied
    await handle_private_event(host, _event(mid=12))
    assert host.sent_replies == []


# ---------- Web UI 面板渲染 ----------
def test_private_tab_renders_zero_js():
    html = render_private_tab(enabled=True, allowed=[20001], admins=[999], cooldown=3,
                              context_size=40, memory_enabled=True,
                              users=[{"qq": 20001, "notes": 4}])
    assert "已开启" in html
    assert "/panel/private/allowlist" in html and "/panel/private/clear" in html
    assert "20001" in html and "999" in html
    assert "<script" not in html.lower()
    assert "onclick=" not in html.lower()


def test_private_tab_disabled_state():
    html = render_private_tab(enabled=False, allowed=[], admins=[], cooldown=0,
                              context_size=40, memory_enabled=True, users=[])
    assert "未开启" in html


def test_private_tab_escapes_message():
    html = render_private_tab(enabled=True, allowed=[], admins=[], cooldown=0,
                              context_size=0, memory_enabled=False, users=[],
                              msg="<script>x</script>")
    assert "<script>" not in html


# ---------- Web UI 面板处理器（允许名单 / 清空记忆） ----------
class _FakeConfigService:
    def __init__(self):
        self.updates = []

    def update(self, key, raw):
        self.updates.append((key, raw))
        return True, ""


class _FakeRequest:
    def __init__(self, form):
        self._form = form

    async def post(self):
        return self._form


class _FakeMemoryStore:
    def __init__(self):
        self.cleared = []

    async def clear_user_memory(self, user_id, group_id):
        self.cleared.append((user_id, group_id))
        return 5


class _Panel:
    def __init__(self):
        self.config = Cfg()
        self.config_service = _FakeConfigService()
        self._memory_manager = _FakeMemoryStore()

    def _check_token(self, request):
        return True


@pytest.mark.asyncio
async def test_panel_private_allowlist_parses_and_persists():
    from aiohttp.web import HTTPFound

    from src.services.webui_panels.private_panel import PrivateChatPanelMixin

    panel = _Panel()
    req = _FakeRequest({"qqs": "20001, 20002\n20003"})
    resp = await PrivateChatPanelMixin._handle_panel_private_allowlist(panel, req)
    assert isinstance(resp, HTTPFound)
    assert panel.config_service.updates == [("PRIVATE_CHAT_ALLOWED_QQS", "20001,20002,20003")]


@pytest.mark.asyncio
async def test_panel_private_allowlist_rejects_bad_value():
    from aiohttp.web import HTTPFound

    from src.services.webui_panels.private_panel import PrivateChatPanelMixin

    panel = _Panel()
    resp = await PrivateChatPanelMixin._handle_panel_private_allowlist(panel, _FakeRequest({"qqs": "abc"}))
    assert isinstance(resp, HTTPFound)
    assert "err=1" in resp.location
    assert panel.config_service.updates == []


@pytest.mark.asyncio
async def test_panel_private_clear_memory():
    from aiohttp.web import HTTPFound

    from src.services.webui_panels.private_panel import PrivateChatPanelMixin

    panel = _Panel()
    resp = await PrivateChatPanelMixin._handle_panel_private_clear(panel, _FakeRequest({"qq": "20001"}))
    assert isinstance(resp, HTTPFound)
    assert panel._memory_manager.cleared == [(20001, -20001)]


def test_config_parses_empty_and_csv_allowlist(monkeypatch):
    """回归：.env 里 PRIVATE_CHAT_ALLOWED_QQS= 空值不能让 Settings 启动失败。"""
    from src.config import Settings

    monkeypatch.setenv("BOT_QQ", "10001")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("PRIVATE_CHAT_ALLOWED_QQS", "")
    assert Settings(_env_file=None).PRIVATE_CHAT_ALLOWED_QQS == []
    monkeypatch.setenv("PRIVATE_CHAT_ALLOWED_QQS", "20001, 20002")
    assert Settings(_env_file=None).PRIVATE_CHAT_ALLOWED_QQS == [20001, 20002]
