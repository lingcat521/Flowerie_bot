"""最小插件实测夹具（任务书《插件测试》§十三/§十四/§十六）。

只用**公开面**驱动，不碰 Core 内部 API：
- 真仓库：src/repositories/settings_repository.py:SettingsRepository
- 真引擎：PluginManager.discover / enable / start_all / dispatch_event / shutdown
- 真插件进程：每种语言的最小插件都由各自的 SDK 写成，build.sh 真编译、run.sh 真启动
- 协议端替身：只记录插件发出来的消息（这不是 Mock 插件 —— 插件全是真的）

链路：dispatch_event("message", "/sdk …") -> 引擎投递 -> 插件 SDK -> plugin.call ->
Core Router -> 另一个真插件进程 -> 结果回到动作 -> 测试断言消息内容。
"""
import asyncio
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile

from src.plugins.manager import PluginManager
from src.repositories.settings_repository import SettingsRepository

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLES = os.path.join(ROOT, "examples", "multilang-sdk")

#: 语言 -> 最小插件目录 / 需要的工具链 / 运行时 / 入口 / ping 里的 label
LANGUAGES = {
    "python": {"dir": "python", "needs": [], "runtime": "python", "entry": "plugin.py",
               "label": "minimal-py"},
    "typescript": {"dir": "typescript", "needs": ["node"], "runtime": "exec", "entry": "run.sh",
                   "label": "minimal-ts"},
    "go": {"dir": "go", "needs": ["go"], "runtime": "exec", "entry": "run.sh",
           "label": "minimal-go"},
    "rust": {"dir": "rust", "needs": ["rustc"], "runtime": "exec", "entry": "run.sh",
             "label": "minimal-rust"},
    "java": {"dir": "java", "needs": ["javac", "java"], "runtime": "exec", "entry": "run.sh",
             "label": "minimal-java"},
}


def missing_reason(lang):
    """None = 可以真跑；否则是 SKIPPED 的原因（环境缺失必须说清缺什么，§十三）。"""
    need = [b for b in LANGUAGES[lang]["needs"] if shutil.which(b) is None]
    if need:
        return "BLOCKED BY ENVIRONMENT：本机缺 %s（CI 有）" % ", ".join(need)
    # Termux 沙箱专属：前缀里的 node/go/java 需要 libtermux-exec 的 LD_PRELOAD 才能启动，
    # 而引擎按白名单裁剪插件进程的环境变量（安全不变式，不为测试放宽）—— 这是环境限制。
    if LANGUAGES[lang]["needs"] and "termux-exec" in os.environ.get("LD_PRELOAD", ""):
        return ("BLOCKED BY ENVIRONMENT：Termux 沙箱下引擎按白名单裁剪插件进程环境变量（不含 "
                "LD_PRELOAD），前缀内的 %s 无法被启动（CI 无此限制）" % LANGUAGES[lang]["needs"][0])
    source = os.path.join(EXAMPLES, LANGUAGES[lang]["dir"])
    if not os.path.isdir(source):
        return "最小插件尚未落地：%s" % source
    return None


class CapturingSender:
    """协议端替身：只记录插件发出的消息（没有 Mock 插件，插件全是真的）。"""

    def __init__(self):
        self.sent = []

    async def send_msg_raw(self, target, target_id, message, reply_id=None):
        self.sent.append({"target": target, "target_id": target_id, "message": message})
        return {"ok": True, "message_id": len(self.sent)}

    # 引擎其它动作路径可能用到的最小面（不参与本任务书验收）
    async def get_group_msg_history(self, group_id, count=15):
        return {"messages": []}

    async def get_friend_msg_history(self, user_id, count=20):
        return {"messages": []}


#: 构建缓存（模块级）：编译型语言每个 session 只构建一次，多个用例共用同一份产物
_BUILD_CACHE = {}
_BUILD_ROOT = None


def build_minimal(lang):
    """真构建最小插件（§十七 Build 行）：build.sh 真编译，产物进 .build/；失败即断言失败。"""
    if lang in _BUILD_CACHE:
        return _BUILD_CACHE[lang]
    global _BUILD_ROOT
    source = os.path.join(EXAMPLES, LANGUAGES[lang]["dir"])
    script = os.path.join(source, "build.sh")
    if _BUILD_ROOT is None:
        _BUILD_ROOT = tempfile.mkdtemp(prefix="flowerie-sdk-build-")
    # 复制成与仓库一致的布局：<work>/examples/multilang-sdk/<lang> + <work>/sdk
    # （各语言 build.sh 用 ../../../sdk/... 定位 SDK，本机与 CI 行为因此一致）
    work = os.path.join(_BUILD_ROOT, "repo", "examples", "multilang-sdk", lang)
    if os.path.isdir(work):
        shutil.rmtree(work)
    os.makedirs(os.path.dirname(work), exist_ok=True)
    shutil.copytree(source, work)
    sdk_root = os.path.join(_BUILD_ROOT, "repo", "sdk")
    if not os.path.isdir(sdk_root):
        shutil.copytree(os.path.join(ROOT, "sdk"), sdk_root)
    if not os.path.isfile(script):
        _BUILD_CACHE[lang] = {"ok": True, "dir": work, "note": "python runner 直接加载源码，无需构建"}
        return _BUILD_CACHE[lang]
    proc = subprocess.run(["/bin/sh", "build.sh"], cwd=work, capture_output=True, text=True,
                          timeout=1800)
    if proc.returncode != 0:
        # 失败**不进缓存**：否则后续用例会拿着半成品目录继续跑，把"编译失败"伪装成"启动超时"
        _BUILD_CACHE.pop(lang, None)
        raise AssertionError("%s 最小插件构建失败（exit=%s）：%s%s" % (
            lang, proc.returncode, proc.stdout[-2000:], proc.stderr[-2000:]))
    _BUILD_CACHE[lang] = {"ok": True, "returncode": 0, "stdout": proc.stdout[-4000:],
                          "stderr": proc.stderr[-4000:], "dir": work}
    return _BUILD_CACHE[lang]


class _Cfg:
    def __init__(self, plugin_dir):
        self.PLUGIN_DIR = plugin_dir


class Rig:
    """一套真实验收环境：临时插件目录 + 真 SQLite 仓库 + 真引擎。"""

    def __init__(self, tmp_path):
        self.root = str(tmp_path)
        self.plugin_dir = os.path.join(self.root, "plugins")
        os.makedirs(self.plugin_dir, exist_ok=True)
        self.repo = SettingsRepository(os.path.join(self.root, "settings.db"))
        self.sender = CapturingSender()
        self.mgr = PluginManager(config=_Cfg(self.plugin_dir), repository=self.repo,
                                 sender=self.sender)
        self.built = {}
        self.loaded = {}

    # ---------- §十七 Build 行：真编译（模块级缓存，编译型语言只构建一次） ----------
    def build(self, lang):
        if lang not in self.built:
            self.built[lang] = build_minimal(lang)
        return self.built[lang]

    def deploy(self, lang, plugin_id, declared=None):
        """把插件铺进真插件目录（构建产物一起带过去）。

        declared：按需改写 manifest 声明的权限 —— 权限测试要构造「只申请了某个目标调用权」的
        插件包（管理员只能批准 manifest 声明过的权限，这是仓库既有规则，不能绕过）。
        """
        built = self.built.get(lang) or {}
        source = built.get("dir") or os.path.join(EXAMPLES, LANGUAGES[lang]["dir"])
        dst = os.path.join(self.plugin_dir, plugin_id)
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        shutil.copytree(source, dst)
        manifest_path = os.path.join(dst, "manifest.json")
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        manifest["id"] = plugin_id
        if declared is not None:
            manifest["permissions"] = list(declared)
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)
        return dst

    # ---------- 装载（真引擎的公开 API） ----------
    async def load(self, lang, plugin_id=None, approved=None, declared=None):
        reason = missing_reason(lang)
        if reason:
            raise RuntimeError(reason)
        plugin_id = plugin_id or "minimal_%s" % ("py" if lang == "python" else
                                                 {"typescript": "ts"}.get(lang, lang))
        self.build(lang)
        self.deploy(lang, plugin_id, declared=declared)
        self.mgr.discover()                      # 幂等：扫描插件目录并把新插件登记为未启用
        approved = approved if approved is not None else [
            "read_message", "send_message", "plugin.call.*", "plugin.emit"]
        ok, why = await self.mgr.enable(plugin_id, approved_permissions=list(approved))
        assert ok, "启用 %s 失败：%s" % (plugin_id, why)
        self.loaded[plugin_id] = lang
        return plugin_id

    def status(self, plugin_id):
        row = self.mgr.get_plugin(plugin_id) or {}
        return str(row.get("status") or "")

    # ---------- 发送与断言 ----------
    async def emit(self, event, payload):
        return await self.mgr.dispatch_event(event, dict(payload))

    async def raw(self, text, group_id=10001):
        """发一条 message 事件，返回插件通过动作回出来的原始 message 文本。"""
        before = len(self.sender.sent)
        await self.mgr.dispatch_event("message", {"text": text, "group_id": group_id,
                                                  "user_id": 20002})
        assert len(self.sender.sent) > before, "插件没有回任何动作（命令：%s）" % text
        return str(self.sender.sent[-1]["message"])

    async def send(self, text, group_id=10001):
        """发命令并解析回包 JSON。"""
        return json.loads(await self.raw(text, group_id))

    # ---------- 生命周期与收尾 ----------
    async def stop(self, plugin_id):
        ok, why = self.mgr.disable(plugin_id)
        assert ok, "停用 %s 失败：%s" % (plugin_id, why)
        await asyncio.sleep(0.2)
        return why

    def plugin_processes(self):
        """当前还活着的、属于本夹具插件目录的进程（收尾时必须是空的）。"""
        alive = []
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open("/proc/%s/cmdline" % pid, "rb") as fh:
                    cmdline = fh.read().decode("utf-8", "replace")
            except OSError:
                continue
            if self.plugin_dir in cmdline:
                alive.append((pid, cmdline.replace("\x00", " ").strip()[:200]))
        return alive

    async def close(self):
        try:
            await self.mgr.shutdown()
        finally:
            await asyncio.sleep(0.3)


class RigCtx:
    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.rig = None

    async def __aenter__(self):
        self.rig = Rig(self.tmp_path)
        return self.rig

    async def __aexit__(self, *exc):
        await self.rig.close()
        return False


def standalone_probe(lang, plugin_dir, plugin_id="minimal_probe", timeout=120):
    """§十八 问题 2：最小插件能不能**独立启动**（不走引擎，直接按协议握手 + 干净退出）。

    这是诊断用的旁证：§十七 验收表的每一行仍然由真引擎驱动；这一条只回答
    「插件自己能不能被拉起来并说协议」，失败时把子进程 stderr 带回来便于定位。
    """
    spec = LANGUAGES[lang]
    if spec["runtime"] == "python":
        runner = os.path.join(ROOT, "src", "plugins", "runner", "python_runner.py")
        cmd = [sys.executable, "-I", runner, "--dir", plugin_dir, "--entry", spec["entry"],
               "--plugin-id", plugin_id]
    else:
        cmd = ["/bin/sh", spec["entry"]]
    proc = subprocess.Popen(cmd, cwd=plugin_dir, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, bufsize=1)
    out = {"ok": False, "steps": [], "stderr": ""}

    def call(mid, method, params=None, wait=timeout):
        proc.stdin.write(json.dumps({"id": mid, "method": method, "params": params or {}}) + "\n")
        proc.stdin.flush()
        ready, _, _ = select.select([proc.stdout], [], [], wait)
        assert ready, "等 %s 的应答超时（%ss）" % (method, wait)
        line = proc.stdout.readline()
        assert line, "连接提前关闭（%s）" % method
        msg = json.loads(line)
        assert msg.get("id") == mid, msg
        out["steps"].append(method)
        return msg

    try:
        init = call(1, "initialize", {"context": {"plugin_dir": plugin_dir,
                                                  "data_dir": os.path.join(plugin_dir, "data"),
                                                  "protocol_version": "1",
                                                  "plugin_id": plugin_id}})
        assert init["result"]["ok"] is True, init
        out["capabilities"] = sorted(init["result"].get("capabilities") or [])
        assert call(2, "health")["result"].get("ok") is True
        assert call(3, "shutdown")["result"].get("ok") is True
        proc.stdin.close()
        proc.wait(timeout=15)
        out["exit"] = proc.returncode
        out["ok"] = True
    except Exception as exc:  # noqa: BLE001 - 诊断信息要带回去
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
    finally:
        try:
            if proc.poll() is None:
                proc.kill()
        except OSError:
            pass
        try:
            out["stderr"] = (proc.stderr.read() or "")[-1500:]
        except (OSError, ValueError):
            pass
    return out
