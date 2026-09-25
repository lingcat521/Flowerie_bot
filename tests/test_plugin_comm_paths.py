"""跨语言插件间通信验收路径（任务书《通信》§十二/§二十四）：Python→Go、TS→Java、TS→TS。

**真进程、真管道、真 Core Router**：每种语言的插件都是 examples/ 下真实的 SDK 示例插件，
经 `runtime=exec` 在本机编译/解释执行；调用从语言 A 的 SDK 出发，穿过 Core，到达语言 B。
本机缺工具链时 skip 并打印原因（不是 pass）；CI 上 go / rustc / javac / node 齐全，三条路径全跑。
"""
import asyncio
import json
import os
import shutil

import pytest

from src.plugins import comm
from src.plugins.manager import PluginManager
from src.plugins.manifest import PluginManifest
from src.plugins.runtime import _ENV_WHITELIST as ENGINE_ENV_WHITELIST

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 语言 → 示例目录 / 需要的工具链 / 目标插件里应出现的 runtime 标记
LANGS = {
    "python": {"example": "examples/python-plugin", "needs": [], "runtime": "python"},
    "rust": {"example": "examples/rust-plugin", "needs": ["rustc"], "runtime": "rust"},
    "typescript": {"example": "examples/typescript-plugin", "needs": ["node"],
                   "runtime": "typescript"},
    "go": {"example": "examples/go-plugin", "needs": ["go"], "runtime": "go"},
    "java": {"example": "examples/java-plugin", "needs": ["javac", "java"], "runtime": "java"},
}


def _sandbox_exec_blocked(lang):
    """Termux 沙箱专属：引擎按白名单裁剪环境变量后，前缀里的二进制无法 exec。

    Termux 的 node/go/java 都需要 libtermux-exec 的 LD_PRELOAD 才能启动，而
    PluginRuntime 的环境变量白名单（安全不变式，不该为测试放宽）里没有它 —— 于是
    exec runtime 的插件在本机会卡在 initialize。这是**本机沙箱限制**，不是代码问题；
    CI（Ubuntu）没有这个限制，三条路径全跑。
    """
    if "LD_PRELOAD" in ENGINE_ENV_WHITELIST:
        return None
    if LANGS[lang]["needs"] and "termux-exec" in os.environ.get("LD_PRELOAD", ""):
        return ("本机 Termux 沙箱：白名单环境变量不含 LD_PRELOAD，%s 无法被 exec runtime 启动"
                "（CI 无此限制）" % LANGS[lang]["needs"][0])
    return None


def _missing(lang):
    need = [b for b in LANGS[lang]["needs"] if shutil.which(b) is None]
    if need:
        return "本机缺工具链 %s（CI 有）" % ", ".join(need)
    return _sandbox_exec_blocked(lang)


class _Repo:
    def __init__(self):
        self.rows = {}

    def get_plugin(self, plugin_id):
        return self.rows.get(plugin_id)

    def list_plugins(self):
        return list(self.rows.values())

    def upsert_plugin(self, row):
        self.rows[row["id"]] = row


class _Cfg:
    def __init__(self, plugin_dir):
        self.PLUGIN_DIR = plugin_dir


class PathRig:
    """把示例插件按真实布局铺开：<tmp>/sdk + <tmp>/plugins/<plugin_id>。"""

    def __init__(self, tmp_path):
        self.root = str(tmp_path)
        self.plugin_dir = os.path.join(self.root, "plugins")
        os.makedirs(self.plugin_dir, exist_ok=True)
        shutil.copytree(os.path.join(ROOT, "sdk"), os.path.join(self.root, "sdk"))
        self.repo = _Repo()
        self.mgr = PluginManager(config=_Cfg(self.plugin_dir), repository=self.repo, sender=None)
        self.manifests = {}
        self.runtimes = {}
        self.approved = {}
        self.mgr._manifest_of = lambda row: self.manifests.get(row["id"])

    def deploy(self, lang):
        """复制示例插件目录到 <plugins>/<plugin_id>（run.sh 里的 ../../sdk 因此可解析）。"""
        src = os.path.join(ROOT, LANGS[lang]["example"])
        raw = json.load(open(os.path.join(src, "manifest.json"), encoding="utf-8"))
        plugin_id = str(raw["id"])
        dst = os.path.join(self.plugin_dir, plugin_id)
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        # 测试用：授权插件间通信（权限来自批准集，不是代码里的开关）
        raw = dict(raw)
        perms = list(raw.get("permissions") or [])
        for extra in ("plugin.call.*", "plugin.emit"):
            if extra not in perms:
                perms.append(extra)
        raw["permissions"] = perms
        with open(os.path.join(dst, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(raw, fh)
        return plugin_id, dst, perms, raw

    async def start(self, lang):
        plugin_id, directory, perms, raw = self.deploy(lang)
        manifest = PluginManifest.load(os.path.join(directory, "manifest.json"))
        self.manifests[plugin_id] = manifest
        self.approved[plugin_id] = list(perms)
        self.repo.rows[plugin_id] = {
            "id": plugin_id, "manifest_json": json.dumps(raw, ensure_ascii=False),
            "enabled": True, "approved_permissions": ",".join(perms),
            "protection": "normal", "status": "running", "install_source": "test",
        }
        rt = self.mgr._start_runtime(plugin_id, manifest, list(perms), "normal")
        # 编译发生在 initialize 之前（exec runtime 直接跑 run.sh）：给足 CI 时间
        rt._limits["startup_timeout"] = 300.0
        rt._limits["event_timeout"] = 60.0
        await rt.start()
        self.runtimes[plugin_id] = rt
        return plugin_id

    async def hook(self, plugin_id, name, *args, timeout=30.0):
        return await asyncio.wait_for(
            PluginManager._runtime_hook_call(self.runtimes[plugin_id], name, *args),
            timeout=timeout)

    async def close(self):
        for rt in list(self.runtimes.values()):
            try:
                await rt.shutdown()
            except Exception:  # noqa: BLE001
                pass
        self.runtimes.clear()


class _Ctx:
    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.rig = None

    async def __aenter__(self):
        self.rig = PathRig(self.tmp_path)
        return self.rig

    async def __aexit__(self, *exc):
        await self.rig.close()
        return False


async def _cross_language_path(tmp_path, caller_lang, callee_lang):
    reason = _missing(caller_lang) or _missing(callee_lang)
    if reason:
        pytest.skip(reason)
    async with _Ctx(tmp_path) as rig:
        caller = await rig.start(caller_lang)
        callee = await rig.start(callee_lang)
        out = await rig.hook(caller, "comm_call", callee, "get_status", {"ping": 1})
        assert out.get("ok") is True, "%s -> %s 调用失败：%r" % (caller_lang, callee_lang, out)
        result = out["result"]
        assert result["plugin_id"] == callee, result
        assert result["runtime"] == LANGS[callee_lang]["runtime"], result
        assert result["echo"] == {"ping": 1}
        assert result["hop_count"] == 1, "跨语言也必须 hop+1（§二十二）"
        assert isinstance(result["trace_id"], str) and result["trace_id"]
        stats = rig.mgr.comm_snapshot()
        assert stats["by_route"] == {"core": 1}, "跨语言必须经 Core Router（§十二）"
        return result


@pytest.mark.asyncio
async def test_python_to_go(tmp_path):
    """验收路径 1：Python 插件 -> Core Router -> Go 插件。"""
    result = await _cross_language_path(tmp_path, "python", "go")
    assert result["runtime"] == "go"


@pytest.mark.asyncio
async def test_typescript_to_java(tmp_path):
    """验收路径 2：TypeScript 插件 -> Core Router -> Java 插件。"""
    result = await _cross_language_path(tmp_path, "typescript", "java")
    assert result["runtime"] == "java"


@pytest.mark.asyncio
async def test_python_to_rust(tmp_path):
    """扩展路径（§二十四：框架必须可扩展，不限于三条核心路径）：Python -> Core -> Rust。"""
    result = await _cross_language_path(tmp_path, "python", "rust")
    assert result["runtime"] == "rust"


@pytest.mark.asyncio
async def test_go_to_python(tmp_path):
    """扩展路径：Go -> Core -> Python（反向也走同一条 Core Router，协议对称）。"""
    result = await _cross_language_path(tmp_path, "go", "python")
    assert result["runtime"] == "python"


@pytest.mark.asyncio
async def test_typescript_to_typescript(tmp_path):
    """验收路径 3：TS -> TS。当前引擎一个插件一个进程，实际走 Core Router（§十一 允许），
    语义与跨语言完全一致 —— 这条用例同时是"同语言不得有特殊语义"的证据。"""
    result = await _cross_language_path(tmp_path, "typescript", "typescript")
    assert result["runtime"] == "typescript"


@pytest.mark.asyncio
async def test_route_policy_core_is_the_unified_path(tmp_path):
    """§十三：SDK 可以显式要求 route=core 验证统一协议路径 —— 同语言也一样。"""
    reason = _missing("typescript")
    if reason:
        pytest.skip(reason)
    async with _Ctx(tmp_path) as rig:
        caller = await rig.start("typescript")
        callee = await rig.start("typescript")
        request = comm.make_request(callee, "get_status", {"via": "core"}, route=comm.ROUTE_CORE)
        resp = await rig.mgr._comm_bus.call(caller, request, approved=rig.approved[caller])
        assert resp["ok"] is True, resp
        assert resp["result"]["echo"] == {"via": "core"}
        assert rig.mgr.comm_snapshot()["by_route"] == {"core": 1}


def test_acceptance_paths_are_declared(tmp_path, capsys):
    """把三条验收路径与各自的工具链可用性打印出来（skip 不等于 pass，报告要能看到谁真跑了）。"""
    table = []
    for caller, callee in (("python", "go"), ("typescript", "java"), ("typescript", "typescript"),
                           ("python", "rust"), ("go", "python")):
        reason = _missing(caller) or _missing(callee)
        table.append("%s->%s=%s" % (caller, callee, "SKIP(%s)" % reason if reason else "RUNNABLE"))
    print("验收路径可用性：" + " | ".join(table))
    assert LANGS["typescript"]["needs"] == ["node"], "TS 路径至少要有 node（CI 与本机都有）"

