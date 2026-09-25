"""Gate R：Resource 抽象（三种来源 3/3 + Core 去协议 id 依赖）。

覆盖三件事：
1. **3/3 归一**：本地路径 / URL / 协议 resource_id 都能进统一的 `ResourceRef`；
2. **取数分层**：协议差异只在 Adapter 的 fetcher 里（OneBot `/get_file`、Milky `get_resource_temp_url`），
   Core 只做"拿 ref → 交给注入的 fetcher → 把字节交给解码器"；
3. **Core 零协议 id 依赖**：AST 扫描 `src/core` 里不出现 `file_id` / `resource_id`（含字符串字面量，
   但不含注释与文档 —— 那里提到它们是解释，不是依赖）。
"""
import ast
import base64
import os
import re
import tempfile

import pytest

from src.adapters.milky_resource_fetcher import MilkyResourceFetcher
from src.adapters.onebot.resource_fetcher import OneBotResourceFetcher
from src.adapters.resource import (
    CompositeResourceFetcher,
    LocalPathFetcher,
    NullResourceFetcher,
    ProtocolIdFetcher,
    ResourceKind,
    ResourceRef,
    URLFetcher,
    attach_resource,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------- 3/3 归一

def test_three_resource_kinds_are_unified():
    local = ResourceRef.from_local_path("/sdcard/a.txt", name="a.txt")
    url = ResourceRef.from_url("https://example/a.png", name="a.png")
    proto = ResourceRef.from_protocol_id("r-9", origin="milky", name="b.txt")
    assert [local.kind, url.kind, proto.kind] == [ResourceKind.LOCAL_PATH, ResourceKind.URL,
                                                  ResourceKind.PROTOCOL_ID]
    assert (local.is_local_path, url.is_url, proto.is_protocol_id) == (True, True, True)
    assert all(r.fetchable for r in (local, url, proto))
    assert proto.origin == "milky" and proto.name == "b.txt"
    # coerce：字符串按形状判断（三种输入都能归一）
    assert ResourceRef.coerce("/sdcard/a.txt").kind == ResourceKind.LOCAL_PATH
    assert ResourceRef.coerce("file:///sdcard/a.txt").kind == ResourceKind.LOCAL_PATH
    assert ResourceRef.coerce("https://example/a.png").kind == ResourceKind.URL
    assert ResourceRef.coerce("r-9").kind == ResourceKind.PROTOCOL_ID
    # 序列化（诊断/日志用）
    assert ResourceRef.coerce("r-9").as_dict()["kind"] == ResourceKind.PROTOCOL_ID


def test_coerce_handles_dirty_inputs_without_guessing():
    ref = ResourceRef.from_url("https://x/a")
    assert ResourceRef.coerce(ref) is ref                       # 幂等
    assert ResourceRef.coerce({"resource": ref}) is ref         # 嵌套
    assert ResourceRef.coerce({"kind": "url", "ref": "https://x/b"}).ref == "https://x/b"
    assert ResourceRef.coerce({"id": "abc", "origin": "onebot11"}).origin == "onebot11"
    assert ResourceRef.coerce({"url": "https://x/c"}).kind == ResourceKind.URL
    for junk in (None, {}, [], 42, b"x", "", "   "):
        assert ResourceRef.coerce(junk) is None, "不可识别的输入必须返回 None（不猜）"


def test_invalid_kind_is_rejected_loudly():
    with pytest.raises(ValueError):
        ResourceRef(kind="magic", ref="x")
    assert ResourceKind.ALL == ("local_path", "url", "protocol_id")


def test_attach_resource_keeps_original_fields_and_adds_ref():
    notice = attach_resource({"id": "f1", "name": "a.txt", "size": "12"}, "onebot11")
    assert notice["id"] == "f1" and notice["name"] == "a.txt" and notice["size"] == "12"
    assert notice["resource"].is_protocol_id and notice["resource"].origin == "onebot11"
    assert notice["resource"].size == 12                        # 脏 size 也能安全转换
    assert attach_resource({}, "onebot11") == {}                # 没有 id 就不造 ref
    assert attach_resource(None, "milky") == {}


# ---------------------------------------------------------------- 取数实现

@pytest.mark.asyncio
async def test_local_path_fetcher_reads_file_and_enforces_limit():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "hello.txt")
    with open(path, "wb") as fh:
        fh.write(b"hello world")
    content, ok = await LocalPathFetcher(max_bytes=1024).fetch(ResourceRef.from_local_path(path))
    assert ok is True and content == b"hello world"

    small, ok2 = await LocalPathFetcher(max_bytes=4).fetch(ResourceRef.from_local_path(path))
    assert small == b"" and ok2 is False                        # 超上限：明确失败
    missing, ok3 = await LocalPathFetcher().fetch(ResourceRef.from_local_path(os.path.join(tmp, "nope")))
    assert missing == b"" and ok3 is False
    assert await LocalPathFetcher().fetch(ResourceRef.from_url("https://x/a")) == (b"", False)


@pytest.mark.asyncio
async def test_url_fetcher_uses_injected_downloader():
    calls = []

    async def http_get(url, max_bytes):
        calls.append((url, max_bytes))
        return b"downloaded", True

    content, ok = await URLFetcher(http_get, max_bytes=99).fetch(ResourceRef.from_url("https://x/a"))
    assert (content, ok) == (b"downloaded", True) and calls == [("https://x/a", 99)]
    assert await URLFetcher().fetch(ResourceRef.from_url("https://x/a")) == (b"", False)


@pytest.mark.asyncio
async def test_protocol_fetcher_dispatches_by_origin_and_reports_unwired():
    seen = []

    async def ob(ref):
        seen.append(ref.origin)
        return b"ob-bytes", True

    fetcher = ProtocolIdFetcher({"onebot11": ob})
    assert fetcher.origins == ("onebot11",)
    assert await fetcher.fetch(ResourceRef.from_protocol_id("f1", origin="onebot11")) == (b"ob-bytes", True)
    assert seen == ["onebot11"]
    # 未接线的协议：明确失败（不抛、不借用别的协议实现）
    assert await fetcher.fetch(ResourceRef.from_protocol_id("r1", origin="milky")) == (b"", False)
    assert await fetcher.fetch(ResourceRef.from_protocol_id("x")) == (b"", False)


@pytest.mark.asyncio
async def test_composite_dispatches_by_kind():
    fetcher = CompositeResourceFetcher(local=LocalPathFetcher(), url=URLFetcher(),
                                       protocol=ProtocolIdFetcher())
    assert fetcher.kinds == ("local_path", "protocol_id", "url")
    assert await fetcher.fetch(ResourceRef.from_url("https://x/a")) == (b"", False)   # 未注入下载器
    assert await fetcher.fetch(None) == (b"", False)
    null = NullResourceFetcher("测试用")
    assert await null.fetch(ResourceRef.from_url("https://x/a")) == (b"", False)


@pytest.mark.asyncio
async def test_onebot_resource_fetcher_base64_local_path_and_failures():
    payload = base64.b64encode(b"napcat file content").decode()
    calls = []

    async def call_api(endpoint, params):
        calls.append((endpoint, params))
        return {"ok": True, "data": {"base64": payload}}

    fetcher = OneBotResourceFetcher(call_api, max_bytes=1024)
    content, ok = await fetcher.fetch(ResourceRef.from_protocol_id("f1", origin="onebot11"))
    assert (content, ok) == (b"napcat file content", True)
    assert calls == [("get_file", {"file_id": "f1"})]

    # 协议端回本地路径：按 local_path 资源读
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "on-disk.txt")
    with open(path, "wb") as fh:
        fh.write(b"from disk")

    async def call_api_path(endpoint, params):
        return {"ok": True, "data": {"file": path}}

    got, ok2 = await OneBotResourceFetcher(call_api_path).fetch(
        ResourceRef.from_protocol_id("f2", origin="onebot11"))
    assert (got, ok2) == (b"from disk", True)

    # 失败面：ok=False / 非 dict / 超大 base64 / 无内容 / 非协议 id
    async def call_api_fail(endpoint, params):
        return {"ok": False, "error": "retcode=1"}

    async def call_api_junk(endpoint, params):
        return {"ok": True, "data": "not-a-dict"}

    async def call_api_empty(endpoint, params):
        return {"ok": True, "data": {"file_name": "x.txt"}}

    async def call_api_huge(endpoint, params):
        return {"ok": True, "data": {"base64": "A" * 100000}}

    ref = ResourceRef.from_protocol_id("f3", origin="onebot11")
    assert await OneBotResourceFetcher(call_api_fail).fetch(ref) == (b"", False)
    assert await OneBotResourceFetcher(call_api_junk).fetch(ref) == (b"", False)
    assert await OneBotResourceFetcher(call_api_empty).fetch(ref) == (b"", False)
    assert await OneBotResourceFetcher(call_api_huge, max_bytes=16).fetch(ref) == (b"", False)
    # 非协议 id 的资源（例如 URL）不属于本 fetcher 的职责：明确拒绝，不误发协议请求
    assert await OneBotResourceFetcher(call_api, max_bytes=1024).fetch(
        ResourceRef.from_url("https://x/a")) == (b"", False)


@pytest.mark.asyncio
async def test_milky_resource_fetcher_two_steps_with_evidence_backed_params():
    """[CODE] LagrangeV2 GetResourceTempUrlHandler.cs L8-27：参数 resource_id、结果 url。"""
    calls = []

    async def call_api(action, params):
        calls.append((action, params))
        return {"ok": True, "data": {"url": "https://temp/x.bin"}}

    async def http_get(url, max_bytes):
        return b"milky-bytes", True

    fetcher = MilkyResourceFetcher(call_api, url_fetcher=URLFetcher(http_get))
    content, ok = await fetcher.fetch(ResourceRef.from_protocol_id("r1", origin="milky"))
    assert (content, ok) == (b"milky-bytes", True)
    assert calls == [("get_resource_temp_url", {"resource_id": "r1"})]

    async def call_api_no_url(action, params):
        return {"ok": True, "data": {}}

    assert await MilkyResourceFetcher(call_api_no_url, url_fetcher=URLFetcher(http_get)).fetch(
        ResourceRef.from_protocol_id("r2", origin="milky")) == (b"", False)
    # 未注入下载器：明确失败（不静默返回空）
    assert await MilkyResourceFetcher(call_api).fetch(
        ResourceRef.from_protocol_id("r3", origin="milky")) == (b"", False)


# ---------------------------------------------------------------- Core 零依赖

def _referenced_names(tree):
    names = set()
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            names.add(node.value)
    return names


def test_core_never_references_protocol_resource_id_fields():
    pattern = re.compile(r"^(file_id|resource_id)$")
    offenders = []
    for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "src", "core")):
        if "__pycache__" in dirpath:
            continue
        for name in sorted(files):
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for ref in sorted(_referenced_names(tree)):
                if pattern.match(ref):
                    offenders.append("%s -> %s" % (os.path.relpath(path, ROOT), ref))
    assert offenders == [], "Core 不得直接依赖协议侧资源 id 字段：%s" % offenders
    # 反向对照：扫描确实抓得到（否则就是"永远为空的假绿"）
    planted = ast.parse("def f(file_info):\n    return file_info['file_id'], resource_id\n")
    assert {n for n in _referenced_names(planted) if pattern.match(n)} == {"file_id", "resource_id"}


# ---------------------------------------------------------------- 端到端（进程内）

class _Cfg:
    VISION_ENABLED = False
    MAX_IMAGES_PER_MESSAGE = 1
    VISION_FORWARD_IMAGES = False
    MAX_FILE_DOWNLOAD_BYTES = 1024 * 1024


class _FileParser:
    """只实现 Core 用到的纯解码那一步（取数由 fetcher 负责）。"""

    def __init__(self, text="解析后的文件文本", ok=True):
        self.text = text
        self.ok = ok
        self.calls = []

    def decode_bytes(self, content_bytes, file_name):
        self.calls.append((content_bytes, file_name))
        return self.text, self.ok


class _Fetcher:
    def __init__(self, content=b"raw-bytes", ok=True):
        self.content = content
        self.ok = ok
        self.refs = []

    async def fetch(self, ref):
        self.refs.append(ref)
        return self.content, self.ok


class _GS:
    def __init__(self):
        self.pending_files = {}


class _CacheRouter:
    """只借 MessageRouter._handle_group_upload 一步（其余流程与本 Gate 无关）。"""

    def __init__(self, group_state):
        self.config = _Cfg()
        self.global_state = group_state

    def _in_whitelist(self, group_id):
        return True

    def _prune_pending_files(self):
        return None


@pytest.mark.asyncio
async def test_notice_to_core_pending_file_uses_resource_ref_end_to_end():
    # message_router 依赖链里有 aiohttp（budget_manager → sender）；本地无该依赖时如实跳过，
    # CI（装了 requirements）会真实执行这条端到端链路。
    pytest.importorskip("aiohttp")
    from src.adapters.onebot_parser import OneBotEventParser
    from src.core.message_assembler import MessageAssembler
    from src.core.message_router import MessageRouter

    raw_notice = {"post_type": "notice", "notice_type": "group_upload", "group_id": 1, "user_id": 2,
                  "file": {"id": "file-abc", "name": "note.txt", "size": 20, "busid": 1}}
    event = OneBotEventParser(bot_qq=10001).parse(raw_notice)

    group_state = _GS()
    MessageRouter._handle_group_upload(_CacheRouter(group_state), event)
    entry = group_state.pending_files["2_1"]
    assert entry["resource"].kind == ResourceKind.PROTOCOL_ID
    assert entry["resource"].origin == "onebot11" and entry["resource"].ref == "file-abc"
    assert "file_id" not in entry                        # 缓存里不再有协议字段
    assert entry["file_name"] == "note.txt"

    fetcher = _Fetcher(b"raw-bytes", ok=True)
    parser = _FileParser(text="文件正文", ok=True)
    assembler = MessageAssembler(_Cfg(), None, parser, group_state, resource_fetcher=fetcher)
    out = await assembler._assemble_pending_file(2, 1)
    assert "文件正文" in out and "用户上传了一个文件" in out
    assert fetcher.refs and fetcher.refs[0].ref == "file-abc"
    assert parser.calls == [(b"raw-bytes", "note.txt")]


@pytest.mark.asyncio
async def test_unwired_or_failing_fetcher_never_fakes_content():
    from src.core.message_assembler import MessageAssembler

    group_state = _GS()
    group_state.pending_files["2_1"] = {"file_name": "a.txt", "resource": None, "file_size": 10}
    assembler = MessageAssembler(_Cfg(), None, _FileParser(), group_state, resource_fetcher=_Fetcher())
    assert await assembler._assemble_pending_file(2, 1) == ""      # 没有 resource：明确跳过

    group_state.pending_files["2_1"] = {
        "file_name": "a.txt", "file_size": 10,
        "resource": ResourceRef.from_protocol_id("f1", origin="onebot11")}
    failing = MessageAssembler(_Cfg(), None, _FileParser(), group_state,
                               resource_fetcher=_Fetcher(b"", ok=False))
    assert await failing._assemble_pending_file(2, 1) == ""        # 取数失败：不产出内容

    group_state.pending_files["2_1"] = {
        "file_name": "a.txt", "file_size": 10,
        "resource": ResourceRef.from_protocol_id("f1", origin="onebot11")}
    unwired = MessageAssembler(_Cfg(), None, _FileParser(), group_state)   # resource_fetcher=None
    assert await unwired._assemble_pending_file(2, 1) == ""
