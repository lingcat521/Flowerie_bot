"""多语言 SDK 最小化插件实测（任务书《插件测试》§一–§十八）。

**这不是"SDK 代码存在"的证明，而是"开发者真能用这个 SDK 写出能跑的插件"的证明**：
每种语言的最小插件都由该语言 SDK 写成，真 build、真启动、真收事件、真跨插件调用、真关闭。

只用公开面：真仓库 + PluginManager 的公开方法（discover/enable/start_all/dispatch_event/shutdown）
+ 真插件进程；测试不手写协议行、不直接调 PluginRuntime、不 Mock 插件。
"""
import asyncio
import json
import logging

import pytest

from tests.sdk.harness import LANGUAGES, RigCtx, missing_reason

LANGS = ["python", "typescript", "go", "rust", "java"]
#: §十七 验收表：只有真跑过的行才会写 PASS（环境缺失写 SKIP 原因）
RESULTS = {}


def _record(lang, row, value):
    RESULTS[(lang, row)] = value


def _caller_id(lang):
    """调用方插件 id（python 行要跟"被验证的对端"区分开）。"""
    short = {"python": "py_caller", "typescript": "ts", "go": "go",
             "rust": "rust", "java": "java"}[lang]
    return "minimal_%s" % short


@pytest.mark.asyncio
@pytest.mark.parametrize("lang", LANGS)
async def test_build_load_ready_and_api(tmp_path, lang):
    """§二/§三/§十/§十七：Build -> Load -> READY -> ping/get_info/echo。"""
    reason = missing_reason(lang)
    if reason:
        pytest.skip(reason)
    async with RigCtx(tmp_path) as rig:
        plugin_id = await rig.load(lang)
        assert rig.status(plugin_id) == "running", "插件没有进入 READY"
        _record(lang, "Build", "PASS")
        _record(lang, "Load", "PASS")
        _record(lang, "Ready", "PASS")

        pong = await rig.send("/sdk@%s ping %s" % (plugin_id, plugin_id))
        assert pong == {"ok": True, "plugin": LANGUAGES[lang]["label"], "runtime": lang}, pong
        _record(lang, "Ping", "PASS")

        info = await rig.send("/sdk@%s info" % plugin_id)
        assert info["plugin_id"] == plugin_id and info["runtime"] == lang, info
        assert info["protocol_version"] == "1" and info["sdk_version"], info
        _record(lang, "Info", "PASS")

        echoed = await rig.send('/sdk@%s echo {"hello":"world"}' % plugin_id)
        assert echoed == {"hello": "world"}, echoed
        _record(lang, "Echo", "PASS")


@pytest.mark.asyncio
@pytest.mark.parametrize("lang", LANGS)
async def test_event_is_received_and_logged(tmp_path, lang, caplog):
    """§四：test.event 必须真的收到并记录，且用 SDK 日志打出来（引擎侧可见）。"""
    reason = missing_reason(lang)
    if reason:
        pytest.skip(reason)
    caplog.set_level(logging.INFO)
    async with RigCtx(tmp_path) as rig:
        plugin_id = await rig.load(lang)
        await rig.emit("test.event", {"message": "hello"})
        seen = await rig.send("/sdk@%s seen %s" % (plugin_id, plugin_id))
        assert {"message": "hello"} in seen["events"], seen
        assert seen["logs"] == ["[test.event] hello"], seen
        _record(lang, "Event", "PASS")


@pytest.mark.asyncio
@pytest.mark.parametrize("lang", LANGS)
async def test_calls_another_plugin(tmp_path, lang):
    """§五/§六/§七：真调用另一个插件；AUTO/LOCAL/CORE 三种策略结果必须一致。"""
    reason = missing_reason(lang)
    if reason:
        pytest.skip(reason)
    async with RigCtx(tmp_path) as rig:
        plugin_id = await rig.load(lang, plugin_id=_caller_id(lang))
        peer = await rig.load("python", plugin_id="minimal_py")
        out = await rig.send("/sdk@%s ping %s" % (plugin_id, peer))
        assert out == {"ok": True, "plugin": "minimal-py", "runtime": "python"}, out
        results = []
        for policy in ("auto", "local", "core"):
            results.append(await rig.send("/sdk@%s route %s %s ping" % (plugin_id, policy, peer)))
        assert results[0] == results[1] == results[2] == out, results
        _record(lang, "Call", "PASS")


@pytest.mark.asyncio
@pytest.mark.parametrize("lang", LANGS)
async def test_error_model_is_native(tmp_path, lang):
    """§九：六种错误码在每种 SDK 里都必须映射成本语言原生错误模型（错误码原样保留）。"""
    reason = missing_reason(lang)
    if reason:
        pytest.skip(reason)
    async with RigCtx(tmp_path) as rig:
        granted = await rig.load("python", plugin_id="minimal_py")
        denied = await rig.load("python", plugin_id="minimal_py_2")
        narrow = ["read_message", "send_message", "plugin.call.%s" % granted]
        caller = await rig.load(lang, plugin_id=_caller_id(lang), declared=narrow,
                                approved=narrow)
        out = await rig.send("/sdk@%s errors %s %s" % (caller, granted, denied))
        expected = {"METHOD_NOT_FOUND", "PLUGIN_NOT_FOUND", "PERMISSION_DENIED",
                    "INVALID_ARGUMENT", "TIMEOUT", "PLUGIN_ERROR"}
        assert set(out) == expected, out
        for code, native in out.items():
            assert native.get("code") == code, (code, native)
            assert native.get("native"), "没有给出原生错误类型名：%s" % (native,)
            assert native.get("message"), native
        _record(lang, "Error", "PASS")


@pytest.mark.asyncio
@pytest.mark.parametrize("lang", LANGS)
async def test_permission_and_target_lifecycle(tmp_path, lang):
    """§八：允许 / 拒绝 / 目标不存在 / 目标未启动 —— 四种都必须结构化，不是 timeout。"""
    reason = missing_reason(lang)
    if reason:
        pytest.skip(reason)
    async with RigCtx(tmp_path) as rig:
        peer = await rig.load("python", plugin_id="minimal_py")
        other = await rig.load("python", plugin_id="minimal_py_2")
        narrow = ["read_message", "send_message", "plugin.call.%s" % peer]
        caller = await rig.load(lang, plugin_id=_caller_id(lang), declared=narrow,
                                approved=narrow)
        allowed = await rig.send("/sdk@%s ping %s" % (caller, peer))
        assert allowed["ok"] is True, allowed

        denied = await rig.send("/sdk@%s ping %s" % (caller, other))
        assert denied.get("code") == "PERMISSION_DENIED", denied
        assert "TIMEOUT" not in json.dumps(denied, ensure_ascii=False), denied

        missing = await rig.send("/sdk@%s ping no_such_plugin" % caller)
        assert missing.get("code") == "PLUGIN_NOT_FOUND", missing

        await rig.stop(peer)
        stopped = await rig.send("/sdk@%s ping %s" % (caller, peer))
        assert stopped.get("code") == "PLUGIN_UNAVAILABLE", stopped
        _record(lang, "Permission", "PASS")


@pytest.mark.asyncio
@pytest.mark.parametrize("lang", LANGS)
async def test_shutdown_is_clean(tmp_path, lang):
    """§十：正常关闭（协议 shutdown + SIGTERM）后不能留下僵尸进程。"""
    reason = missing_reason(lang)
    if reason:
        pytest.skip(reason)
    from tests.sdk.harness import Rig

    rig = Rig(tmp_path)
    try:
        plugin_id = await rig.load(lang)
        assert rig.plugin_processes(), "插件进程应该正在运行"
        await rig.stop(plugin_id)
        for _ in range(50):
            if not rig.plugin_processes():
                break
            await asyncio.sleep(0.1)
        assert rig.plugin_processes() == [], "停用后仍有进程：%s" % rig.plugin_processes()
    finally:
        await rig.close()
    for _ in range(50):
        if not rig.plugin_processes():
            break
        await asyncio.sleep(0.1)
    assert rig.plugin_processes() == [], "引擎关闭后仍有插件进程：%s" % rig.plugin_processes()
    _record(lang, "Shutdown", "PASS")


def test_zzz_acceptance_table_is_reported(capsys):
    """§十七：把验收表打印出来（skip 不等于 pass：没跑过的语言要写清缺什么）。"""
    rows = ["Build", "Load", "Ready", "Ping", "Info", "Echo", "Event", "Call", "Error",
            "Permission", "Shutdown"]
    lines = ["§十七 最小插件验收表（只写真实结果）",
             "| 测试 | " + " | ".join(LANGS) + " |",
             "| --- | " + " | ".join(["---"] * len(LANGS)) + " |"]
    for row in rows:
        cells = []
        for lang in LANGS:
            value = RESULTS.get((lang, row))
            if value:
                cells.append(value)
            else:
                reason = missing_reason(lang)
                cells.append("SKIP（%s）" % reason if reason else "未执行")
        lines.append("| %s | %s |" % (row, " | ".join(cells)))
    table = "\n".join(lines)
    print(table)
    assert any(RESULTS.get((lang, "Ping")) == "PASS" for lang in LANGS), \
        "至少要有一种语言真的跑完（本机至少 python；CI 上五种语言全跑）"


@pytest.mark.asyncio
@pytest.mark.parametrize("lang", LANGS)
async def test_minimal_plugin_starts_standalone(lang):
    """§十八 问题 2：最小插件能不能独立启动（协议握手 + health + 干净退出，不经引擎）。"""
    reason = missing_reason(lang)
    if reason:
        pytest.skip(reason)
    from tests.sdk.harness import build_minimal, standalone_probe

    built = build_minimal(lang)
    probe = standalone_probe(lang, built["dir"])
    assert probe["ok"], "独立启动失败：%s\nstderr=%s" % (probe.get("error"), probe.get("stderr"))
    assert probe["exit"] == 0, probe
    assert len(probe["capabilities"]) == 14, probe["capabilities"]
