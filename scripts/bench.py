"""花璃性能基准（本机实测，用于评估硬件可行性，尤其树莓派）。

不依赖 pytest，直接跑：
    python3 scripts/bench.py            # 全部
    python3 scripts/bench.py --quick    # 快速版（迭代次数减半）
    python3 scripts/bench.py --json     # 输出 JSON（便于对比不同机器）

设计原则：
  - 每个用例只测**纯本地计算**（不含网络/LLM），这样换机器才有可比性
  - 同时报告 p50 / p95 / 吞吐，避免只看平均值被离群值骗
  - 内存用 tracemalloc 峰值，CPU 用 process_time 差值
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import statistics
import sys
import tempfile
import time
import tracemalloc

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


_QUIET = False


def log(msg):
    """诊断信息：JSON 模式下走 stderr，避免污染 stdout 的 JSON。"""
    print(msg, file=sys.stderr) if _QUIET else print(msg)


class Bench:
    """单个用例：warmup + N 次迭代，记录每次耗时。"""

    def __init__(self, name, group):
        self.name = name
        self.group = group
        self.times = []
        self.mem_peak = 0

    def run(self, fn, iterations=200, warmup=20, setup=None, teardown=None):
        for _ in range(warmup):
            obj = setup() if setup else None
            fn(obj)
            if teardown and obj is not None:
                teardown(obj)
        gc.collect()
        tracemalloc.start()
        samples = []
        for _ in range(iterations):
            obj = setup() if setup else None
            t0 = time.perf_counter()
            fn(obj)
            samples.append((time.perf_counter() - t0) * 1000)  # ms
            if teardown and obj is not None:
                teardown(obj)
        cur, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.times = samples
        self.mem_peak = peak / 1024  # KB
        return self

    def stats(self):
        if not self.times:
            return {}
        s = sorted(self.times)
        n = len(s)
        return {
            "p50": s[n // 2],
            "p95": s[min(n - 1, int(n * 0.95))],
            "mean": statistics.fmean(s),
            "min": s[0],
            "max": s[-1],
            "mem_kb": self.mem_peak,
            "throughput": 1000.0 / statistics.fmean(s) if statistics.fmean(s) > 0 else 0,
        }


def env_info():
    try:
        cores = os.cpu_count()
    except Exception:
        cores = "?"
    return {
        "python": platform.python_version(),
        "machine": platform.machine(),
        "system": platform.system(),
        "cores": cores,
        "cpu_model": _cpu_model(),
    }


# ARM CPU part 号 → 核心名（Android 上 /proc/cpuinfo 多半没有型号字符串）
_ARM_PARTS = {
    "0xd03": "Cortex-A53", "0xd04": "Cortex-A35", "0xd05": "Cortex-A55",
    "0xd07": "Cortex-A57", "0xd08": "Cortex-A72", "0xd09": "Cortex-A73",
    "0xd0a": "Cortex-A75", "0xd0b": "Cortex-A76", "0xd0c": "Neoverse-N1",
    "0xd0d": "Cortex-A77", "0xd40": "Neoverse-V1", "0xd41": "Cortex-A78",
    "0xd44": "Cortex-X1", "0xd46": "Cortex-A510", "0xd47": "Cortex-A710",
    "0xd48": "Cortex-X2", "0xd4d": "Cortex-A715", "0xd4e": "Cortex-X3",
    "0xd81": "Cortex-A720", "0xd84": "Neoverse-V2", "0xd85": "Cortex-X4",
}


def _cpu_model():
    """尽力读出 CPU 型号：先看文本字段，再回退到 ARM part 号映射。"""
    for path in ("/sys/devices/soc0/machine", "/proc/device-tree/model"):
        try:
            return open(path, encoding="utf-8", errors="ignore").read().strip(" \x00\n")
        except Exception:
            pass
    parts, model_name = set(), None
    try:
        for line in open("/proc/cpuinfo", encoding="utf-8", errors="ignore"):
            low = line.lower()
            if low.startswith("cpu part"):
                parts.add(line.split(":", 1)[1].strip())
            elif low.startswith(("model name", "hardware")):
                v = line.split(":", 1)[1].strip()
                if v and v not in ("0", "unknown"):
                    model_name = v
    except Exception:
        pass
    if model_name:
        return model_name
    named = sorted({_ARM_PARTS.get(x, x) for x in parts})
    return " + ".join(named) if named else "unknown"


# ══════════════════════════════════════════════════════════════
# 用例定义
# ══════════════════════════════════════════════════════════════


def bench_text_pipeline(iters):
    """消息文本处理链：分句 / @ 检测 / 水印 / 消毒。"""
    from src.core.reply_splitter import extract_stickers, fragment_split
    from src.core.sanitizer import sanitize_untrusted_text

    short = "今天天气不错啊，要不要一起出去玩？"
    medium = ("我觉得这个事情吧，其实没有那么复杂。" * 8)
    long = ("这是一段用来测试长文本处理性能的内容，包含标点、数字 3.14 和括号（说明）。" * 40)
    stickered = "给你看看[STICKER:7N07_偷看.gif]这个，很好笑的"

    out = []
    out.append(Bench("分句 · 短句(18字)", "text").run(lambda _: fragment_split(short), iters))
    out.append(Bench("分句 · 中句(160字)", "text").run(lambda _: fragment_split(medium), iters))
    out.append(Bench("分句 · 长句(1600字)", "text").run(lambda _: fragment_split(long), iters // 2))
    out.append(Bench("表情标记提取", "text").run(lambda _: extract_stickers(stickered), iters))
    out.append(Bench("不可信文本消毒(1KB)", "text").run(
        lambda _: sanitize_untrusted_text(medium), iters))
    return out


def bench_mention(iters):
    """@ 检测（群消息热路径，每条消息都会跑一次）。"""
    from src.core.name_mention import detect
    import types

    class M:
        def __init__(self, text):
            self.content = text
            self.sender_id = 10001
            self.group_id = 20001

    cfg = types.SimpleNamespace(BOT_NICKNAME="花璃", BOT_QQ=10000, BOT_ALIASES="")
    msg_hit = M("[CQ:at,qq=10000] 你在吗")
    msg_miss = M("今天群里真热闹，大家都吃了吗")

    return [
        Bench("@ 命中", "mention").run(lambda _: detect(msg_hit, cfg), iters),
        Bench("@ 未命中", "mention").run(lambda _: detect(msg_miss, cfg), iters),
    ]


def bench_detectors(iters):
    """重复检测（每条群消息都过）。"""
    from src.core.repeat_detector import RepeatDetector
    import types

    cfg = types.SimpleNamespace(REPEAT_DETECT_ENABLED=True, REPEAT_THRESHOLD=3,
                                REPEAT_WINDOW=60, REPEAT_COOLDOWN_SECONDS=60, CONTEXT_SIZE=300)

    def make():
        return RepeatDetector(cfg, {})

    def observe(det):
        det.check_and_record_repeat("同一句话内容", 20001)

    return [Bench("重复检测 · 单次", "detect").run(observe, iters, setup=make)]


def bench_file_parse(iters):
    """文件解析（本地库，纯 CPU；按页/按行抽取文本）。"""
    import asyncio
    import types

    try:
        from src.services.file_parser import FileParser
    except Exception as e:
        log(f"  [跳过文件解析] 导入失败: {e}")
        return []

    cfg = types.SimpleNamespace(
        FILE_PARSE_ENABLED=True, FILE_PARSE_FORMATS="txt,pdf,docx,xlsx,csv",
        MAX_FILE_TEXT_CHARS=8000, FILE_PARSE_MAX_BYTES=10 * 1024 * 1024,
        MAX_FILE_BYTES=10 * 1024 * 1024, FILE_PARSE_TEXT_FALLBACK=True)
    try:
        parser = FileParser(cfg)
    except Exception as e:
        log(f"  [跳过文件解析] 构造失败: {e}")
        return []

    txt = ("这是一行测试内容，用来评估文本解析开销。" * 3 + chr(10)) * 200  # ~240KB
    csvb = ("a,b,c,d,e" + chr(10) + "1,2,3,4,5" + chr(10) * 1) * 1
    csvb = ("a,b,c,d,e" + chr(10) + "".join(f"{i},{i},{i},{i},{i}" + chr(10) for i in range(500))).encode("utf-8")
    txtb = txt.encode("utf-8")

    def run_txt(_):
        return asyncio.run(parser.parse_document("t.txt", txtb))

    def run_csv(_):
        return asyncio.run(parser.parse_document("t.csv", csvb))

    out = []
    for label, fn in ((f"解析 txt({len(txtb)//1024}KB)", run_txt), ("解析 csv(500 行)", run_csv)):
        try:
            fn(None)  # 先跑一次确认不炸
            out.append(Bench(label, "file").run(fn, max(20, iters // 4)))
        except Exception as e:
            log(f"  [文件解析 {label} 失败] {type(e).__name__}: {e}")
    return out


def bench_sqlite(iters):
    """SQLite 读写（记忆 / 设置 / 画像都走它）。"""
    import sqlite3

    def make():
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        c = sqlite3.connect(path)
        c.execute("CREATE TABLE t (k TEXT PRIMARY KEY, v TEXT)")
        c.commit()
        return (c, path)

    def cleanup(obj):
        c, path = obj
        try:
            c.close()
            os.unlink(path)
        except Exception:
            pass

    def write1(obj):
        c, _ = obj
        c.execute("INSERT OR REPLACE INTO t VALUES (?, ?)", ("k1", "v" * 100))
        c.commit()

    def read1(obj):
        c, _ = obj
        c.execute("SELECT v FROM t WHERE k = ?", ("k1",)).fetchone()

    out = []
    out.append(Bench("SQLite 写入(100B)", "db").run(write1, iters, setup=make, teardown=cleanup))

    def write100(obj):
        c, _ = obj
        c.executemany("INSERT OR REPLACE INTO t VALUES (?, ?)",
                      [(f"k{i}", "v" * 100) for i in range(100)])
        c.commit()

    out.append(Bench("SQLite 批量写 100 行", "db").run(
        write100, max(20, iters // 10), setup=make, teardown=cleanup))

    # 读：先建好再读
    def make_filled():
        obj = make()
        c, _ = obj
        c.executemany("INSERT OR REPLACE INTO t VALUES (?, ?)",
                      [(f"k{i}", "v" * 100) for i in range(1000)])
        c.commit()
        return obj

    out.append(Bench("SQLite 按主键读(1000 行库)", "db").run(
        lambda o: o[0].execute("SELECT v FROM t WHERE k = ?", ("k500",)).fetchone(),
        iters, setup=make_filled, teardown=cleanup))
    return out


def bench_web_render(iters):
    """Web UI 渲染（模板拼字符串，纯 CPU）。"""
    from src.services.webui_render.pages import render_panel_page

    body = "<div>" + "<p>内容块</p>" * 50 + "</div>"

    def render(_):
        return render_panel_page(theme_class="theme-night", bg_rules="", msg_html="",
                                 body_html=body, active_tab="config")

    return [Bench("面板页渲染(50 块正文)", "webui").run(render, max(20, iters // 4))]


def bench_config(iters):
    """配置读取（ConfigService 每次读都过一遍 SCHEMA）。"""
    try:
        from src.services.config_schema import SCHEMA
    except Exception as e:
        log(f"  [跳过配置] {e}")
        return []

    def iterate(_):
        for k, v in SCHEMA.items():
            _ = (k, v[0])

    return [Bench(f"遍历 SCHEMA({len(SCHEMA)} 键)", "config").run(iterate, iters)]


def bench_memory(iters):
    """整体内存：进程 RSS（常驻）与导入全部模块的增量。"""
    import resource

    def rss_mb():
        try:
            with open("/proc/self/status", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) / 1024
        except Exception:
            pass
        return 0.0

    import importlib
    before = rss_mb()
    mods = [
        "src.core.message_router", "src.core.ai_gateway", "src.core.message_assembler",
        "src.services.ai_client", "src.services.ai_tools", "src.services.web_search",
        "src.services.file_parser", "src.services.memory_manager",
        "src.services.blossom_memory", "src.services.config_service",
        "src.services.web_ui", "src.services.mcp_client",
    ]
    ok, fail = 0, 0
    for m in mods:
        try:
            importlib.import_module(m)
            ok += 1
        except Exception:
            fail += 1
    after = rss_mb()
    log(f"  进程 RSS: {after:.0f} MB（导入 {ok}/{len(mods)} 个核心模块后，"
          f"增量 {after - before:+.0f} MB，失败 {fail}）")
    return []


def bench_e2e_local(iters):
    """端到端（本地部分）：从原始消息到「该不该回 + 回复怎么拆」，不含 LLM。"""
    from src.core.name_mention import detect
    from src.core.reply_splitter import fragment_split
    from src.core.sanitizer import sanitize_untrusted_text
    import types

    cfg = types.SimpleNamespace(BOT_NICKNAME="花璃", BOT_QQ=10000, BOT_ALIASES="")

    class M:
        content = "[CQ:at,qq=10000] 花璃你觉得这个话题怎么样？我最近一直在想这个问题"
        sender_id = 10001
        group_id = 20001

    def pipeline(_):
        msg = M()
        hit = detect(msg, cfg)              # @ 检测
        text, _ = sanitize_untrusted_text(msg.content)  # 消毒
        reply = "我觉得吧，" + text[:60] + "，这个问题挺有意思的，可以再想想。"
        return fragment_split(reply)        # 分句

    return [Bench("本地处理链(@检测→消毒→分句)", "e2e").run(pipeline, iters)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="快速版（迭代减半）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--iter", type=int, default=200, help="基础迭代次数")
    args = ap.parse_args()

    global _QUIET
    _QUIET = args.json
    base = args.iter if not args.quick else max(20, args.iter // 2)
    env = env_info()

    if not args.json:
        print("=" * 78)
        print("花璃性能基准")
        print("=" * 78)
        print(f"  Python  {env['python']}")
        print(f"  平台    {env['system']} / {env['machine']} / {env['cores']} 核")
        print(f"  CPU     {env['cpu_model'][:70]}")
        print(f"  迭代    {base} 次/用例（warmup 20）")
        print()

    suites = [
        ("文本处理", bench_text_pipeline),
        ("@ 检测", bench_mention),
        ("重复检测", bench_detectors),
        ("SQLite", bench_sqlite),
        ("文件解析", bench_file_parse),
        ("Web UI 渲染", bench_web_render),
        ("配置", bench_config),
        ("端到端(本地)", bench_e2e_local),
        ("整体内存", bench_memory),
    ]

    results = []
    for title, fn in suites:
        if not args.json:
            print(f"── {title} " + "─" * (60 - len(title)))
        try:
            benches = fn(base)
        except Exception as e:
            log(f"  [跳过] {type(e).__name__}: {e}")
            continue
        for b in benches:
            st = b.stats()
            if not st:
                continue
            results.append({"group": b.group, "name": b.name, **st})
            if not args.json:
                print(f"  {b.name:<26} p50 {st['p50']:>8.3f} ms   "
                      f"p95 {st['p95']:>8.3f} ms   "
                      f"{st['throughput']:>9.0f} ops/s   "
                      f"mem {st['mem_kb']:>7.0f} KB")
        if not args.json:
            print()

    if args.json:
        print(json.dumps({"env": env, "results": results}, ensure_ascii=False, indent=2))
        return

    print("=" * 78)
    print("说明：以上均为纯本地计算，不含网络与 LLM 调用。")
    print("      消息处理的实际端到端延迟还要加上 LLM 往返（通常 1-5 秒），")
    print("      所以本地这部分在总延迟里占比很小——这也是树莓派可行的原因。")
    print("=" * 78)


if __name__ == "__main__":
    main()
