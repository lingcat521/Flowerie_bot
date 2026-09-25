"""Plugin WebUI Protocol 多语言一致性（任务书第 3 份 §十三）。

同一套 WebUI Protocol 请求跑在**五种语言的示例插件真进程**上（真管道、真协议），
断言语义完全一致：Register Page / Load HTML / Load Asset / Receive Context /
Submit Action / Receive Result / Handle Error / Shutdown。

与 tests/test_plugin_sdk_contract.py 共用同一套进程夹具（`_Peer`）与可用性口径：
本机缺工具链 → skip 并打印原因（不是 pass）；CI 装了 go/rustc/javac → 五种语言全跑。
"""
import pytest

from tests.test_plugin_sdk_contract import LANGUAGES, _missing_reason, _Peer

WEBUI_CAPS = ("webui.page", "webui.action", "webui.asset")

#: 引擎侧发给插件的受控 context（只有协议 §七 允许的 6 个顶层键）
CTX = {
    "plugin": {"id": "multilang_demo", "name": "多语言示例"},
    "page": {"id": "dynamic", "title": "插件渲染页"},
    "request": {"method": "GET", "action": "get"},
    "user": {"authenticated": True, "role": "admin"},
    "config": {"nickname": "cfg-nick"},
    "data": {},
}
SAVE_FORM = {"nickname": "花语"}
PAGE = {"id": "dynamic", "title": "插件渲染页"}


@pytest.fixture
def peer(request):
    lang = request.param
    reason = _missing_reason(lang)
    if reason:
        pytest.skip(reason)
    p = _Peer(lang)
    p.init_result = p.initialize()["result"]
    try:
        yield p
    finally:
        p.close()


@pytest.mark.parametrize("peer", sorted(LANGUAGES), indirect=True)
def test_webui_capabilities_are_declared(peer):
    """五语言都必须声明同一批 WebUI 能力（与核心 8 项一起构成 11 项）。"""
    caps = set(peer.init_result.get("capabilities") or [])
    for method in WEBUI_CAPS:
        assert method in caps, "%s 未声明 %s（实际：%s）" % (peer.lang, method, sorted(caps))


@pytest.mark.parametrize("peer", sorted(LANGUAGES), indirect=True)
def test_webui_page_receives_engine_context(peer):
    """webui.page：插件拿到的 context 真的被用上（表单 action 里是引擎给的 plugin id）。"""
    result = peer.call("webui.page", {"page": PAGE, "context": CTX})["result"]
    assert result.get("ok") is True, "%s 的 webui.page 返回：%s" % (peer.lang, result)
    html = str(result.get("html") or "")
    assert "插件渲染页" in html, "%s 的 HTML 不含页面标题：%s" % (peer.lang, html[:120])
    assert "/panel/plugins/webui/multilang_demo/dynamic" in html, (
        "%s 没有使用引擎给的 context.plugin.id：%s" % (peer.lang, html[:200]))
    assert isinstance(result.get("vars"), dict), result


@pytest.mark.parametrize("peer", sorted(LANGUAGES), indirect=True)
def test_webui_action_save_is_identical(peer):
    """webui.action：同一个 save settings Action，五语言返回同一批字段。"""
    peer.call("storage.set", {"key": "nickname", "value": SAVE_FORM["nickname"]})
    result = peer.call("webui.action", {"page": PAGE, "action": "save",
                                        "form": SAVE_FORM, "context": CTX})["result"]
    assert result.get("ok") is True, "%s 的 webui.action 返回：%s" % (peer.lang, result)
    assert result.get("message") == "已保存"
    assert (result.get("vars") or {}).get("nickname") == SAVE_FORM["nickname"]
    assert (result.get("config_set") or {}).get("nickname") == SAVE_FORM["nickname"]
    assert (result.get("storage_set") or {}).get("nickname") == SAVE_FORM["nickname"]


@pytest.mark.parametrize("peer", sorted(LANGUAGES), indirect=True)
def test_webui_action_unknown_is_operation_error(peer):
    """Handle Error：未知动作回操作级错误（不是协议级 error，也不是假装成功）。"""
    result = peer.call("webui.action", {"page": PAGE, "action": "definitely-not-an-action",
                                        "form": {}, "context": CTX})["result"]
    assert result.get("ok") is False, result
    assert result.get("error"), result


@pytest.mark.parametrize("peer", sorted(LANGUAGES), indirect=True)
def test_webui_asset_is_identical(peer):
    """Load Asset：动态 CSS 由插件进程生成；未知路径如实报错。"""
    result = peer.call("webui.asset", {"path": "theme.css"})["result"]
    assert result.get("ok") is True, "%s 的 webui.asset 返回：%s" % (peer.lang, result)
    assert result.get("content_type") == "text/css"
    assert "1f6feb" in str(result.get("body") or "")
    missing = peer.call("webui.asset", {"path": "nope.css"})["result"]
    assert missing.get("ok") is False and missing.get("error")


@pytest.mark.parametrize("peer", sorted(LANGUAGES), indirect=True)
def test_webui_file_page_data_hook(peer):
    """Register Page / Load HTML：HTML 文件页的模板变量通道（web_ui.entry 数据钩子）。"""
    result = peer.call("hook", {"name": "webui_page",
                                "args": ["index", "get", {}, {}]})["result"]
    assert result.get("ok") is True, "%s 的 webui_page 钩子返回：%s" % (peer.lang, result)
    payload = result.get("result") or {}
    assert "vars" in payload and "nickname" in payload["vars"], payload


def test_webui_capability_matrix_is_reported(capsys):
    """把 WebUI 能力矩阵打印出来（skip 不等于 pass，报告里要能看到谁真的跑了）。"""
    rows = []
    for lang in sorted(LANGUAGES):
        reason = _missing_reason(lang)
        rows.append("%s=%s" % (lang, "SKIP(%s)" % reason if reason else "RUNNABLE"))
    print("WebUI Protocol 多语言矩阵：" + " | ".join(rows))
    assert any(_missing_reason(lang) is None for lang in LANGUAGES), \
        "没有任何语言可跑 —— CI 至少要能跑起来"
