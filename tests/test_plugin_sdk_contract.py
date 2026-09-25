"""跨语言 SDK 契约测试（任务书第 2 份 §十二 / 第 3 份 §十三）。

同一批向量（`tests/fixtures/plugin_protocol_vectors.json`）跑在**真子进程**上：
每种语言的示例插件都是独立进程，用真管道说 Plugin Protocol v1；引擎侧由本测试实现
（含反向 engine op）——**不 mock 协议、不 mock 语言**。

语言可用性：
- 本机缺工具链 / 示例尚未落地 → **skip 并打印原因**（既不是 pass 也不是 fail）；
- CI 装了 go / rustc / javac / node，会真跑，Capability Matrix 只采信这里的结果。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(ROOT, "src/plugins/runner/python_runner.py")
VECTORS = json.load(open(os.path.join(ROOT, "tests/fixtures/plugin_protocol_vectors.json"),
                         encoding="utf-8"))

#: 语言清单：kind=runner 表示用仓库自带 runner（Python），kind=exec 表示入口即进程
LANGUAGES = {
    "python": {"example": "examples/python-plugin", "kind": "runner", "entry": "plugin.py",
               "needs": []},
    "typescript": {"example": "examples/typescript-plugin", "kind": "exec", "entry": "run.sh",
                   "needs": ["node"]},
    "go": {"example": "examples/go-plugin", "kind": "exec", "entry": "run.sh", "needs": ["go"]},
    "rust": {"example": "examples/rust-plugin", "kind": "exec", "entry": "run.sh",
             "needs": ["rustc"]},
    "java": {"example": "examples/java-plugin", "kind": "exec", "entry": "run.sh",
             "needs": ["javac", "java"]},
}


def _missing_reason(lang: str):
    spec = LANGUAGES[lang]
    example = os.path.join(ROOT, spec["example"])
    if not os.path.isdir(example):
        return "示例未落地：%s（Phase 2 计划内）" % spec["example"]
    entry = os.path.join(example, spec["entry"])
    if not os.path.isfile(entry):
        return "入口缺失：%s" % entry
    missing = [b for b in spec["needs"] if shutil.which(b) is None]
    if missing:
        return "本机缺工具链 %s（CI 有）" % ", ".join(missing)
    return None


class _Peer:
    """测试里的引擎侧：起真示例进程，按向量回答反向 op。"""

    def __init__(self, lang: str):
        spec = LANGUAGES[lang]
        self.lang = lang
        self.example = os.path.join(ROOT, spec["example"])
        self.data_dir = tempfile.mkdtemp()
        self.proc_dir = self.example
        if spec["kind"] == "runner":
            # Python：runner 用 --dir 定位插件与数据目录 → 复制到临时目录跑，避免污染仓库
            self.proc_dir = os.path.join(tempfile.mkdtemp(), lang)
            shutil.copytree(self.example, self.proc_dir)
            cmd = [sys.executable, "-I", RUNNER, "--dir", self.proc_dir,
                   "--entry", spec["entry"], "--plugin-id", lang + "_demo"]
            self.data_dir = os.path.join(self.proc_dir, "data")
        else:
            cmd = ["/bin/sh", os.path.join(self.example, spec["entry"])]
        self.cmd = cmd
        self.proc = subprocess.Popen(cmd, cwd=self.proc_dir, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, bufsize=1)
        self.seq = 0
        self.engine_ops = []

    # ---- 引擎侧 ----
    def _answer(self, msg):
        op = (msg.get("params") or {}).get("op")
        args = (msg.get("params") or {}).get("args") or {}
        self.engine_ops.append(op)
        if op == "permission.check":
            want = str(args.get("permission") or "")
            result = {"ok": True, "permission": want, "granted": want == VECTORS["permission"]["granted"]}
        elif op == "config.get":
            result = {"ok": True, "values": dict(VECTORS["engine_values"])}
        elif op == "context.get":
            result = {"ok": True, "result": {"plugin_id": self.lang + "_demo",
                                             "protocol_version": VECTORS["protocol_version"]}}
        else:
            result = {"ok": False, "error": "unknown op"}
        self.proc.stdin.write(json.dumps({"id": msg["id"], "result": result}) + "\n")
        self.proc.stdin.flush()

    def call(self, method, params=None):
        self.seq += 1
        self.proc.stdin.write(json.dumps({"id": self.seq, "method": method,
                                          "params": params or {}}) + "\n")
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            assert line, "示例进程提前退出（%s）：%s" % (self.lang, self.proc.stderr.read()[-400:])
            msg = json.loads(line)
            if msg.get("method") == "engine":
                self._answer(msg)
                continue
            assert msg.get("id") == self.seq, msg
            return msg

    def initialize(self):
        return self.call("initialize", {"context": {"plugin_dir": self.proc_dir,
                                                    "data_dir": self.data_dir,
                                                    "protocol_version": VECTORS["protocol_version"]}})

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        self.proc.wait(timeout=10)


@pytest.fixture
def peer(request):
    lang = request.param
    reason = _missing_reason(lang)
    if reason:
        pytest.skip(reason)
    p = _Peer(lang)
    try:
        yield p
    finally:
        p.close()


@pytest.mark.parametrize("peer", sorted(LANGUAGES), indirect=True)
def test_handshake_declares_protocol_and_capabilities(peer):
    result = peer.initialize()["result"]
    assert result["ok"] is True
    assert result["protocol_version"] == VECTORS["protocol_version"]
    assert result["api_version"] == "1"
    caps = set(result.get("capabilities") or [])
    missing = sorted(set(VECTORS["required_capabilities"]) - caps)
    assert missing == [], "%s 少声明能力：%s" % (peer.lang, missing)


@pytest.mark.parametrize("peer", sorted(LANGUAGES), indirect=True)
def test_event_yields_vector_action(peer):
    peer.initialize()
    actions = peer.call("event", VECTORS["event"])["result"]["actions"]
    assert actions, "%s 没有返回动作" % peer.lang
    assert actions[0] == VECTORS["expected_action"], "%s 的动作与向量不一致：%s" % (peer.lang, actions[0])


@pytest.mark.parametrize("peer", sorted(LANGUAGES), indirect=True)
def test_non_matching_event_yields_no_action(peer):
    peer.initialize()
    actions = peer.call("event", VECTORS["non_matching_event"])["result"]["actions"]
    assert actions == [], "%s 对不匹配事件也返回了动作：%s" % (peer.lang, actions)


@pytest.mark.parametrize("peer", sorted(LANGUAGES), indirect=True)
def test_storage_roundtrip_matches_vector(peer):
    peer.initialize()
    key, value = VECTORS["storage"]["key"], VECTORS["storage"]["value"]
    assert peer.call("storage.set", {"key": key, "value": value})["result"]["ok"] is True
    assert peer.call("storage.get", {"key": key})["result"]["value"] == value
    assert peer.call("storage.list", {})["result"]["keys"] == [key]
    assert peer.call("storage.get", {"key": VECTORS["storage"]["bad_key"]})["result"]["ok"] is False
    assert peer.call("storage.delete", {"key": key})["result"]["deleted"] is True


@pytest.mark.parametrize("peer", sorted(LANGUAGES), indirect=True)
def test_hook_status_reads_storage(peer):
    peer.initialize()
    key, value = VECTORS["storage"]["key"], VECTORS["storage"]["value"]
    peer.call("storage.set", {"key": key, "value": value})
    hook = VECTORS["hook"]
    result = peer.call("hook", {"name": hook["name"], "args": hook["args"]})["result"]
    assert result["ok"] is True
    assert result["result"] == hook["expected_result"], "%s 的 hook 结果不一致：%s" % (peer.lang, result)


@pytest.mark.parametrize("peer", sorted(LANGUAGES), indirect=True)
def test_permission_check_uses_reverse_channel(peer):
    peer.initialize()
    granted = peer.call("permission.check", {"permission": VECTORS["permission"]["granted"]})["result"]
    denied = peer.call("permission.check", {"permission": VECTORS["permission"]["denied"]})["result"]
    assert granted["granted"] is True and denied["granted"] is False
    assert "permission.check" in peer.engine_ops


@pytest.mark.parametrize("peer", sorted(LANGUAGES), indirect=True)
def test_unknown_method_is_protocol_error(peer):
    peer.initialize()
    msg = peer.call("definitely.not.a.method")
    assert "error" in msg and msg["error"], "%s 未对未知方法报协议级错误" % peer.lang


@pytest.mark.parametrize("peer", sorted(LANGUAGES), indirect=True)
def test_shutdown_is_clean(peer):
    peer.initialize()
    assert peer.call("shutdown")["result"]["ok"] is True
    peer.proc.stdin.close()
    assert peer.proc.wait(timeout=10) == 0


def test_availability_table_is_reported(capsys):
    """把可用性打印出来（skip 不等于 pass，报告里要能看到谁真的跑了）。"""
    table = []
    for lang in sorted(LANGUAGES):
        reason = _missing_reason(lang)
        table.append("%s=%s" % (lang, "SKIP(%s)" % reason if reason else "RUNNABLE"))
    print("跨语言 SDK 可用性：" + " | ".join(table))
    assert any(_missing_reason(lang) is None for lang in LANGUAGES), \
        "没有任何语言可跑 —— CI 至少要能跑起来（本机允许只有 python/node）"
