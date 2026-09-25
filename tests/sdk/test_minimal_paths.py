"""跨（同）语言 Plugin Communication 链路实测（任务书《插件测试》§五/§六/§七）。

最低验收路径：**TS → Go、TS → Java、TS → TS**；另外补 Python → Go、Python → TS、Go → Rust、
Rust → Java（任务书说明"如果对应语言 Runtime 已完成，也增加"）。

每条链路都是：真调用方插件（该语言 SDK 写成）-> 引擎 Core Router -> 真被调方插件进程 -> 结果回传。
"""
import pytest

from tests.sdk.harness import LANGUAGES, RigCtx, missing_reason

#: (调用方, 被调方, 是否最低验收路径)
PATHS = [
    ("typescript", "go", True),
    ("typescript", "java", True),
    ("typescript", "typescript", True),
    ("python", "go", False),
    ("python", "typescript", False),
    ("go", "rust", False),
    ("rust", "java", False),
]

SHORT = {"python": "py", "typescript": "ts", "go": "go", "rust": "rust", "java": "java"}
PATH_RESULTS = {}


def _ids(path):
    caller, callee = path[0], path[1]
    if caller == callee:
        return "path_%s_a" % SHORT[caller], "path_%s_b" % SHORT[callee]
    return "path_%s" % SHORT[caller], "path_%s" % SHORT[callee]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PATHS, ids=["%s->%s" % (p[0], p[1]) for p in PATHS])
async def test_plugin_communication_path(tmp_path, path):
    caller, callee, required = path
    reason = missing_reason(caller) or missing_reason(callee)
    if reason:
        pytest.skip(reason)
    async with RigCtx(tmp_path) as rig:
        caller_id, callee_id = _ids(path)
        await rig.load(caller, plugin_id=caller_id)
        await rig.load(callee, plugin_id=callee_id)

        expected = {"ok": True, "plugin": LANGUAGES[callee]["label"], "runtime": callee}

        # §六：plugin.call(target, "ping") 拿到对方的 ping 结果
        pong = await rig.send("/sdk@%s ping %s" % (caller_id, callee_id))
        assert pong == expected, pong

        # §六：echo 必须原样返回数据
        echoed = await rig.send('/sdk@%s call %s echo {"hello":"world"}' % (caller_id, callee_id))
        assert echoed == {"hello": "world"}, echoed

        # §七：AUTO / LOCAL / CORE 三种路由策略，对插件开发者暴露的结果必须一致
        for policy in ("auto", "local", "core"):
            got = await rig.send("/sdk@%s route %s %s ping" % (caller_id, policy, callee_id))
            assert got == expected, (policy, got)

        PATH_RESULTS[(caller, callee)] = "PASS" if required else "PASS(扩展)"
        assert rig.status(caller_id) == "running" and rig.status(callee_id) == "running"


@pytest.mark.asyncio
async def test_typescript_chain_go_and_java(tmp_path):
    """§六 的完整例子：TS 依次调用 Go(ping) -> Java(echo) -> TS2(ping)，三条结果都要对。"""
    for lang in ("typescript", "go", "java"):
        reason = missing_reason(lang)
        if reason:
            pytest.skip(reason)
    async with RigCtx(tmp_path) as rig:
        ts = await rig.load("typescript", plugin_id="chain_ts")
        go = await rig.load("go", plugin_id="chain_go")
        java = await rig.load("java", plugin_id="chain_java")
        ts2 = await rig.load("typescript", plugin_id="chain_ts_2")
        out = await rig.send("/sdk@%s chain %s %s %s" % (ts, go, java, ts2))
        assert out["t1"] == {"ok": True, "plugin": "minimal-go", "runtime": "go"}, out
        assert out["t2"] == {"hello": "world"}, out
        assert out["t3"] == {"ok": True, "plugin": "minimal-ts", "runtime": "typescript"}, out


@pytest.mark.asyncio
async def test_same_language_second_instance(tmp_path):
    """§六 同语言：TS -> TS 必须同样成功（两个真 TS 插件进程，各自独立实例）。"""
    reason = missing_reason("typescript")
    if reason:
        pytest.skip(reason)
    async with RigCtx(tmp_path) as rig:
        first = await rig.load("typescript", plugin_id="same_ts_a")
        second = await rig.load("typescript", plugin_id="same_ts_b")
        out = await rig.send("/sdk@%s ping %s" % (first, second))
        assert out == {"ok": True, "plugin": "minimal-ts", "runtime": "typescript"}, out
        back = await rig.send("/sdk@%s ping %s" % (second, first))
        assert back == out, back


def test_zz_paths_table_is_reported(capsys):
    """把三条最低验收路径的真实结果打印出来（未跑的语言写明环境缺失原因）。"""
    lines = ["§五 跨语言链路（最低验收：TS->Go / TS->Java / TS->TS）"]
    for caller, callee, _required in PATHS:
        key = (caller, callee)
        value = PATH_RESULTS.get(key)
        if value:
            lines.append("  %-11s %s" % ("%s->%s" % (caller, callee), value))
            continue
        reason = missing_reason(caller) or missing_reason(callee)
        lines.append("  %-11s %s" % ("%s->%s" % (caller, callee),
                                     "SKIP（%s）" % reason if reason else "未执行"))
    table = "\n".join(lines)
    print(table)
    assert any(v.startswith("PASS") for v in PATH_RESULTS.values()) or \
        all((missing_reason(c) or missing_reason(d)) for c, d, _ in PATHS), table

