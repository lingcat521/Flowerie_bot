"""Exercise the same declarative settings form through five real SDK processes."""
import pytest

from src.plugins.webui_view import WebUIView
from tests.sdk.harness import LANGUAGES, RigCtx, missing_reason


@pytest.mark.asyncio
@pytest.mark.parametrize("lang", LANGUAGES)
async def test_sdk_settings(tmp_path, lang):
    reason = missing_reason(lang)
    if reason:
        pytest.skip(reason)
    async with RigCtx(tmp_path) as rig:
        save_permissions = ["web_ui", "webui.storage.read", "webui.storage.write"]
        pid = await rig.load(lang, approved=save_permissions)
        page = "sdk_settings"
        first, err = await rig.mgr.plugin_webui_render(pid, page)
        assert not err, err
        assert 'value="Flowerie"' in first["html"]
        assert "<td>日报</td>" in first["html"] and "<td>周报</td>" not in first["html"]
        assert f'/panel/plugins/webui/{pid}/{page}?table_1=2' in first["html"]
        second, err = await rig.mgr.plugin_webui_render(pid, page, params={"table_1": "2"})
        assert not err, err
        assert "<td>周报</td>" in second["html"] and "<td>日报</td>" not in second["html"]

        bad, err = await rig.mgr.plugin_webui_render(
            pid, page, "save", values={"nickname": "花语", "limit": "2.5"})
        assert not err, err
        assert 'aria-invalid="true"' in bad["html"]
        assert "请输入有效整数" in bad["html"] and "已保存" not in bad["html"]
        unchanged, err = await rig.mgr.plugin_webui_render(pid, page)
        assert not err and 'value="Flowerie"' in unchanged["html"]

        current, err = await rig.mgr.plugin_webui_render(
            pid, page, "save", values={
                "nickname": '<b>{{plugin_id}}</b>', "limit": "42", "enabled": "true", "extra": "ignored",
            })
        assert not err and not current["warnings"], (err, current)
        assert "已保存" in current["html"]
        assert 'value="&lt;b&gt;{{plugin_id}}&lt;/b&gt;"' in current["html"]
        assert 'value="true" checked' in current["html"]
        stored = await rig.mgr._webui_host._webui_storage_snapshot(pid)
        assert stored["sdk_settings"] == {"nickname": '<b>{{plugin_id}}</b>', "limit": 42, "enabled": True}
        assert type(stored["sdk_settings"]["limit"]) is int

        reloaded, err = await rig.mgr.plugin_webui_render(pid, page)
        assert not err and 'value="42"' in reloaded["html"] and 'value="true" checked' in reloaded["html"]


def test_select_checkbox_and_optional_integer():
    view = WebUIView({"form": {"action": "save", "fields": [
        {"name": "mode", "type": "select", "required": True,
         "options": [{"value": "daily", "label": "每日"}]},
        {"name": "notes", "type": "textarea"},
        {"name": "limit", "type": "integer"},
        {"name": "agreed", "type": "boolean", "required": True},
    ]}})
    values, errors = view.parse("save", {"mode": "weekly", "unused": "ignored"})
    assert values == {"notes": "", "limit": None}
    assert errors == {"mode": "选项无效", "agreed": "必填"}
    values, errors = view.parse("save", {"mode": "daily", "notes": "一\n二", "agreed": "true"})
    assert not errors
    assert values == {"mode": "daily", "notes": "一\n二", "limit": None, "agreed": True}
