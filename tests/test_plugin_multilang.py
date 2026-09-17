"""多语言插件黑盒测试：13 种语言各写一个最小插件，真启动子进程跑完整协议。

验证的是「任意语言接入」这件事本身：
- 每种语言只实现 Plugin API v1 的 stdin/stdout JSON-Lines（不依赖任何 SDK）
- exec runtime 直接执行入口（编译产物 / shebang 脚本 / 包装脚本），主进程不假设语言
- 真启动 → initialize 握手 → 发 event → 断言插件返回的动作 → shutdown

环境缺某语言的工具链时**跳过**（CI 上 GCC/Go/Rust/Java/Node/PHP/Ruby/Perl 齐全，
Kotlin/.NET/Lua/R 视镜像而定）。
"""
import os
import shutil
import subprocess

import pytest

from src.plugins.manifest import PluginManifest
from src.plugins.runtime import PluginRuntime

MULTILANG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugins", "multilang")

# 每种语言：工具链 / 编译命令 / 期望标记 / 启动超时 / 额外依赖
SPECS = [
    dict(name="c", tool="gcc", build=["gcc", "-O2", "-o", "plugin", "plugin.c"], marker="c-ok"),
    dict(name="cpp", tool="g++", build=["g++", "-O2", "-std=c++17", "-o", "plugin", "plugin.cpp"],
         marker="cpp-ok"),
    dict(name="go", tool="go", build=["go", "build", "-o", "plugin", "main.go"], marker="go-ok",
         startup=60, build_timeout=180),
    dict(name="rust", tool="rustc", build=["rustc", "-O", "-o", "plugin", "main.rs"], marker="rust-ok",
         startup=60, build_timeout=180),
    dict(name="java", tool="javac", build=["javac", "Plugin.java"], marker="java-ok",
         needs=["java"], startup=30),
    dict(name="csharp", tool="dotnet",
         build=["dotnet", "build", "-c", "Release", "--nologo", "-v", "quiet"], marker="csharp-ok",
         startup=120, build_timeout=420),
    dict(name="kotlin", tool="kotlinc",
         build=["kotlinc", "plugin.kt", "-include-runtime", "-d", "plugin.jar"], marker="kotlin-ok",
         needs=["java"], startup=60, build_timeout=600),
    dict(name="php", tool="php", build=None, marker="php-ok"),
    dict(name="lua", tool="lua", build=None, marker="lua-ok"),
    dict(name="ruby", tool="ruby", build=None, marker="ruby-ok"),
    dict(name="perl", tool="perl", build=None, marker="perl-ok"),
    dict(name="r", tool="Rscript", build=None, marker="r-ok", startup=30),
    dict(name="typescript", tool="tsc",
         build=["tsc", "plugin.ts", "--target", "es2019", "--module", "commonjs"],
         marker="typescript-ok", needs=["node"], build_timeout=180),
]


def _deploy(tmp_path, name):
    dst = tmp_path / name
    shutil.copytree(os.path.join(MULTILANG_DIR, name), dst)
    return str(dst)


def _run_build(spec, plugin_dir):
    proc = subprocess.run(spec["build"], cwd=plugin_dir, capture_output=True, text=True,
                          timeout=spec.get("build_timeout", 120))
    assert proc.returncode == 0, "%s 编译失败：\n%s\n%s" % (spec["name"], proc.stdout[-2000:], proc.stderr[-2000:])


@pytest.mark.asyncio
@pytest.mark.parametrize("spec", SPECS, ids=[s["name"] for s in SPECS])
async def test_multilang_minimal_plugin(tmp_path, spec):
    """最小多语言插件端到端：编译（如需）→ 真启动 → 握手 → 事件 → 断言 → 关闭。"""
    if shutil.which(spec["tool"]) is None:
        pytest.skip("%s 未安装（本环境跳过 %s）" % (spec["tool"], spec["name"]))
    for need in spec.get("needs", []):
        if shutil.which(need) is None:
            pytest.skip("缺少 %s（无法运行 %s）" % (need, spec["name"]))

    plugin_dir = _deploy(tmp_path, spec["name"])
    if spec["build"]:
        _run_build(spec, plugin_dir)

    manifest = PluginManifest.load(os.path.join(plugin_dir, "manifest.json"))
    assert manifest.runtime == "exec", "多语言示例必须走 exec runtime"
    runtime = PluginRuntime(manifest.id, manifest, plugin_dir, protection="normal")
    runtime._limits["event_timeout"] = 30.0
    runtime._limits["startup_timeout"] = float(spec.get("startup", 30))

    received = []
    runtime.set_action_handler(
        lambda pid, action, payload: received.append((pid, action, payload)) or {"ok": True})
    await runtime.start()
    try:
        actions = await runtime.dispatch_event("message", {"text": "hi", "group_id": 1})
        messages = [a.get("message") for a in actions if isinstance(a, dict)]
        assert spec["marker"] in messages, "%s 未返回预期标记 %r，实际: %r" % (
            spec["name"], spec["marker"], actions)
    finally:
        await runtime.shutdown()


def test_multilang_fixtures_are_consistent():
    """夹具自检：14 种语言目录齐全、manifest 合法且 runtime=exec（无需工具链）。"""
    names = sorted(s["name"] for s in SPECS)
    assert len(names) == len(set(names)) == 13
    for name in names:
        d = os.path.join(MULTILANG_DIR, name)
        assert os.path.isdir(d), "缺少夹具目录: %s" % name
        manifest = PluginManifest.load(os.path.join(d, "manifest.json"))
        assert manifest.runtime == "exec"
        entry_ok = (os.path.isfile(os.path.join(d, manifest.entry))
                    or manifest.entry in ("plugin", "plugin.js"))
        assert entry_ok, "%s 的 entry 既不是文件也不是编译产物名: %s" % (name, manifest.entry)

