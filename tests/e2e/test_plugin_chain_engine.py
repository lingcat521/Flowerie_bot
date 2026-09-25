"""§28 的引擎侧验证（不需要浏览器、不需要 HTTP 服务器）。

只用真仓库 + 真 `PluginManager` + 真插件子进程 + 真 Core Router：

* 夹具插件的三个页面 / 表单 / 跨插件调用钩子在**真插件进程**里跑通；
* `plugin_webui_render(action=…)` 真的把请求送到另一个插件进程并把结果带回来；
* Core Router 的统计（`comm_snapshot()`）给出真实数字：`calls_ok` / `by_route["core"]`。

这一层在装不上浏览器的最小环境里也能跑 —— 本机（Termux/Android 沙箱）实测就是如此；
浏览器层（`test_plugin_webui_browser.py` / `test_plugin_webui_chains.py`）才是 §8/§28 的最终证据。
缺工具链的语言按 `BLOCKED BY ENVIRONMENT` skip（写清缺什么）。
"""
import os
import shutil

import pytest

from tests.e2e import _harness as H

#: 页面/插件自报的 runtime = 语言名
TARGET_RUNTIME = {"go": "go", "java": "java", "rust": "rust", "typescript": "typescript",
                  "python": "python"}
#: 注册表里的 runtime = manifest 的 runtime（exec runtime 的语言插件都写 "exec"）
MANIFEST_RUNTIME = {"go": "exec", "java": "exec", "rust": "exec", "typescript": "exec",
                   "python": "python"}


async def _deploy_fixture(rig):
    """把 tests/e2e 自带入口插件铺进真插件目录并启用（真子进程）。"""
    pid = H.FIXTURE_PLUGIN_ID
    dest = os.path.join(rig.plugin_dir, pid)
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    shutil.copytree(os.path.join(H.FIXTURE_PLUGINS_DIR, pid), dest)
    rig.mgr.discover()
    row = rig.mgr.get_plugin(pid) or {}
    ok, why = await rig.mgr.enable(pid, approved_permissions=list(row.get("declared_permissions") or []))
    assert ok, why
    return pid


async def _load_entry(rig, chain, ids):
    """装载链路入口插件；入口插件缺 communication 页面时 skip（写明缺什么）。"""
    spec = H.CHAINS[chain]
    if spec["entry_lang"] is None:
        return await _deploy_fixture(rig)
    entry_dir = os.path.join(H.MULTILANG_DIR, spec["entry_lang"])
    pages = H.plugin_webui_pages(entry_dir)
    if "communication" not in pages:
        pytest.skip("%s入口插件 %s 没有声明 communication 页面（当前 pages=%s）—— %s 需要入口插件"
                    "自带 WebUI 页面，契约见 tests/e2e/README.md"
                    % (H.BLOCKED, ids["entry"], pages or "无", spec["name"]))
    return await rig.load(spec["entry_lang"], ids["entry"])


async def test_three_pages_render_with_contract_ids(rig_ctx, tmp_path):
    """夹具插件的三个页面在真插件进程里渲染，契约里的元素 id 一个都不少，且没有 JS。"""
    async with rig_ctx(str(tmp_path)) as rig:
        pid = await _deploy_fixture(rig)
        for page_id in H.PAGE_IDS:
            result, err = await rig.mgr.plugin_webui_render(pid, page_id, "get", {}, {})
            assert not err, "%s: %s" % (page_id, err)
            html = str(result.get("html") or "")
            assert html, "%s 渲染为空" % page_id
            for el_id in H.REQUIRED_IDS[page_id]:
                assert ('id="%s"' % el_id) in html, "%s 缺少 #%s" % (page_id, el_id)
            assert "<script" not in html.lower()


async def test_settings_action_persists_inside_plugin_process(rig_ctx, tmp_path):
    """表单 POST -> 插件 webui.action -> 真插件进程写状态 -> 重新渲染读回（Round-trip）。"""
    async with rig_ctx(str(tmp_path)) as rig:
        pid = await _deploy_fixture(rig)
        result, err = await rig.mgr.plugin_webui_render(pid, "settings", "save", {}, {
            "greeting": "引擎侧 round-trip", "count": "42", "mode": "a", "notify": "1"})
        assert not err, err
        values = result.get("vars") or {}
        assert values.get("message") == "设置已保存"
        assert values.get("greeting") == "引擎侧 round-trip"
        assert values.get("count") == "42"
        assert values.get("mode") == "a"
        assert values.get("notify_text") == "on"
        # 再 GET 一次：状态来自插件进程（不是本次请求的变量残留）
        again, err2 = await rig.mgr.plugin_webui_render(pid, "settings", "get", {}, {})
        assert not err2, err2
        assert (again.get("vars") or {}).get("greeting") == "引擎侧 round-trip"


async def test_communication_action_reaches_another_plugin_process(rig_ctx, tmp_path):
    """Python 入口插件 -> Core Router -> 另一个真插件进程 -> 结果回到页面变量（任何环境都能跑）。"""
    async with rig_ctx(str(tmp_path)) as rig:
        entry = await _deploy_fixture(rig)
        target = await rig.load("python", "minimal_py")
        result, err = await rig.mgr.plugin_webui_render(entry, "communication", "call", {}, {
            "target": target, "method": "echo", "request": '{"hello": "world"}', "route": "auto"})
        assert not err, err
        values = result.get("vars") or {}
        assert values.get("response_ok") == "ok", values.get("error")
        assert values.get("target_runtime") == "python"
        assert '"hello"' in values.get("response", "")
        assert values.get("trace_id") and values["trace_id"] in values["response"], values
        snapshot = rig.mgr.comm_snapshot()
        assert snapshot["calls_ok"] >= 1, snapshot
        assert snapshot["by_route"].get("core", 0) >= 1, snapshot
        instances = {i["plugin_id"]: i for i in snapshot["instances"]}
        assert instances[target]["state"] == "READY"
        assert instances[target]["runtime"] == "python"


@pytest.mark.parametrize("chain", sorted(H.CHAINS))
async def test_engine_chain(chain, rig_ctx, tmp_path):
    """§28 三条链路的引擎侧版本：入口插件 -> 目标语言插件（真跨语言进程）。"""
    spec = H.CHAINS[chain]
    for lang in H.chain_languages(chain):
        reason = H.language_blocked_reason(lang)
        if reason:
            pytest.skip("%s%s 不可跑 —— %s" % (H.BLOCKED, spec["name"], reason))
    ids = H.chain_plugin_ids(chain)
    async with rig_ctx(str(tmp_path)) as rig:
        entry = await _load_entry(rig, chain, ids)
        await rig.load(spec["target_lang"], ids["target"])
        result, err = await rig.mgr.plugin_webui_render(entry, "communication", "call", {}, {
            "target": ids["target"], "method": spec["method"], "request": spec["request"],
            "route": "auto"})
        assert not err, err
        values = result.get("vars") or {}
        assert values.get("response_ok") == "ok", values.get("error")
        assert values.get("target_runtime") == TARGET_RUNTIME[spec["target_lang"]], values
        assert values.get("trace_id") and values["trace_id"] in values.get("response", ""), values
        snapshot = rig.mgr.comm_snapshot()
        assert snapshot["calls_ok"] >= 1, snapshot
        assert snapshot["by_route"].get("core", 0) >= 1, snapshot
        instances = {i["plugin_id"]: i for i in snapshot["instances"]}
        assert instances[ids["target"]]["state"] == "READY"
        assert instances[ids["target"]]["runtime"] == MANIFEST_RUNTIME[spec["target_lang"]]
