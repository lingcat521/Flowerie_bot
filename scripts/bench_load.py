"""花璃负载基准：模拟真实并发场景（多群 / 文档 / 图片 / 插件）。

与 scripts/bench.py 的区别：
  - bench.py       测「单次操作多快」（微基准）
  - bench_load.py  测「持续负载下能扛多少」（档位基准，含内存/背压）

用法：
    python3 scripts/bench_load.py                # 全部档位
    python3 scripts/bench_load.py --tier 3       # 只跑第 3 档
    python3 scripts/bench_load.py --duration 20  # 每档持续 20 秒
    python3 scripts/bench_load.py --json

设计原则：
  - 每档固定「群数 x 每群消息速率 x 附加负载概率」，跑固定时长
  - 测量：吞吐(msg/s) / 延迟分位(p50/p95/p99) / 内存峰值 / CPU 单核当量
  - 附件负载按概率触发，比例贴近真实使用
"""
from __future__ import annotations

import argparse
import asyncio
import gc
import io
import json
import os
import random
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


TIERS = [
    {"id": 1, "name": "轻载(1群私用)", "groups": 1, "rate": 1.0, "duration": 10,
     "file_prob": 0.00, "image_prob": 0.00, "plugin_prob": 0.00},
    {"id": 2, "name": "日常(5群)", "groups": 5, "rate": 2.0, "duration": 10,
     "file_prob": 0.02, "image_prob": 0.05, "plugin_prob": 0.02},
    {"id": 3, "name": "繁忙(10群+附件)", "groups": 10, "rate": 5.0, "duration": 12,
     "file_prob": 0.05, "image_prob": 0.10, "plugin_prob": 0.05},
    {"id": 4, "name": "压力(30群+高频)", "groups": 30, "rate": 10.0, "duration": 12,
     "file_prob": 0.10, "image_prob": 0.20, "plugin_prob": 0.10},
    {"id": 5, "name": "极限(50群刷屏)", "groups": 50, "rate": 20.0, "duration": 10,
     "file_prob": 0.10, "image_prob": 0.25, "plugin_prob": 0.10},
]


class Loader:
    """构造各类负载所需的真实对象（解析器 / 图片样本）。"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.parser = None
        self.samples = {}
        self._build()

    def _build(self):
        try:
            from src.services.file_parser import FileParser
            self.parser = FileParser(self.cfg)
        except Exception as e:
            print(f"  [警告] FileParser 不可用: {e}", file=sys.stderr)

        self.samples["msg"] = "今天群里的气氛真好，大家聊得挺开心的，你们觉得呢？"
        self.samples["msg_long"] = ("这是一条比较长的群消息，" * 6) + "想看看处理长文本时的开销。"

        self.samples["txt"] = (("这是文档里的一行内容，用来测试解析开销。" * 3) + chr(10)) * 300
        rows = "".join(f"{i},{i*2},{i*3},{i*4},{i*5}" + chr(10) for i in range(400))
        self.samples["csv"] = ("a,b,c,d,e" + chr(10) + rows).encode("utf-8")

        self.samples["png"] = self._make_png(800, 600)
        self.samples["gif"] = self._make_gif()

    @staticmethod
    def _make_png(w, h):
        try:
            from PIL import Image
            im = Image.new("RGB", (w, h), (90, 140, 200))
            buf = io.BytesIO()
            im.save(buf, format="PNG", optimize=True)
            return buf.getvalue()
        except Exception:
            return b""

    @staticmethod
    def _make_gif():
        try:
            from PIL import Image
            frames = [Image.new("P", (120, 90), i * 20) for i in range(4)]
            buf = io.BytesIO()
            frames[0].save(buf, format="GIF", save_all=True,
                           append_images=frames[1:], duration=100, loop=0)
            return buf.getvalue()
        except Exception:
            return b""


async def _image_job(loader):
    from src.services.multimodal import gif_first_frame_png
    data = loader.samples["gif"] or loader.samples["png"]
    if data:
        gif_first_frame_png(data)


async def _plugin_job(worker_id):
    """插件调用桩：JSON 往返 + 结构校验（不真起进程，避免测成进程启动开销）。"""
    payload = {"action": "ping", "id": worker_id, "data": "x" * 256}
    raw = json.dumps(payload)
    back = json.loads(raw)
    if back.get("action") != "ping":
        raise RuntimeError("plugin roundtrip failed")


async def message_worker(worker_id, tier, loader, stats, stop_at):
    from src.core.name_mention import detect
    from src.core.reply_splitter import extract_stickers, fragment_split
    from src.core.sanitizer import sanitize_untrusted_text

    cfg = types.SimpleNamespace(BOT_NICKNAME="花璃", BOT_QQ=10000, BOT_ALIASES="")

    class Msg:
        def __init__(self, text, gid):
            self.content = text
            self.sender_id = 9000 + gid
            self.group_id = gid

    interval = 1.0 / tier["rate"]
    rnd = random.Random(worker_id)
    gid = 10000 + worker_id
    i = 0

    while time.perf_counter() < stop_at:
        t0 = time.perf_counter()
        tasks = []
        try:
            i += 1
            text = loader.samples["msg_long"] if (i % 7 == 0) else loader.samples["msg"]
            msg = Msg(f"[CQ:at,qq=10000] {text}" if (i % 5 == 0) else text, gid)

            detect(msg, cfg)
            clean, _ = sanitize_untrusted_text(msg.content)
            reply = "我觉得吧，" + clean[:80] + "，这个可以再想想。"
            extract_stickers(reply)
            fragment_split(reply)

            if loader.parser is not None and rnd.random() < tier["file_prob"]:
                tasks.append(loader.parser.parse_document(
                    "doc.txt", loader.samples["txt"].encode("utf-8")))
            if loader.parser is not None and rnd.random() < tier["file_prob"] * 0.5:
                tasks.append(loader.parser.parse_document("data.csv", loader.samples["csv"]))
            if rnd.random() < tier["image_prob"]:
                tasks.append(_image_job(loader))
            if rnd.random() < tier["plugin_prob"]:
                tasks.append(_plugin_job(worker_id))
            if tasks:
                await asyncio.gather(*tasks)

            stats["latencies"].append((time.perf_counter() - t0) * 1000)
            stats["done"] += 1
            if tasks:
                stats["with_attach"] += 1
        except Exception as e:
            stats["errors"] += 1
            if stats["errors"] <= 3:
                print(f"  [worker {worker_id}] {type(e).__name__}: {e}", file=sys.stderr)

        wait = interval - (time.perf_counter() - t0)
        if wait > 0:
            await asyncio.sleep(wait)


def current_rss_mb():
    try:
        with open("/proc/self/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except Exception:
        pass
    return 0.0


async def run_tier(tier, loader):
    stats = {"latencies": [], "done": 0, "errors": 0, "with_attach": 0}
    stop_at = time.perf_counter() + tier["duration"]

    gc.collect()
    rss_before = current_rss_mb()
    cpu_before = time.process_time()
    wall_before = time.perf_counter()
    # 不用 tracemalloc：它会拦截每一次内存分配，把延迟放大 10-100 倍，
    # 测出来的 p95 完全失真。改用轻量 RSS 采样（每 0.5s 一次）。
    rss_samples = [rss_before]

    async def _rss_watch():
        while time.perf_counter() < stop_at:
            rss_samples.append(current_rss_mb())
            await asyncio.sleep(0.5)

    workers = [asyncio.create_task(message_worker(i, tier, loader, stats, stop_at))
               for i in range(tier["groups"])]
    watcher = asyncio.create_task(_rss_watch())
    await asyncio.gather(*workers, return_exceptions=True)
    watcher.cancel()

    wall = time.perf_counter() - wall_before
    cpu = time.process_time() - cpu_before
    rss_after = current_rss_mb()
    rss_peak = max(rss_samples) if rss_samples else rss_after

    lat = sorted(stats["latencies"])
    n = len(lat) or 1

    def pct(p):
        return lat[min(n - 1, int(n * p))] if lat else 0.0

    return {
        "tier": tier["id"], "name": tier["name"], "groups": tier["groups"],
        "rate_per_group": tier["rate"],
        "target_throughput": tier["groups"] * tier["rate"],
        "duration_s": round(wall, 1),
        "messages": stats["done"], "attach_messages": stats["with_attach"],
        "errors": stats["errors"],
        "throughput": stats["done"] / wall if wall else 0,
        "p50_ms": pct(0.50), "p95_ms": pct(0.95), "p99_ms": pct(0.99),
        "max_ms": lat[-1] if lat else 0,
        "cpu_ratio": (cpu / wall) if wall else 0,
        "rss_before_mb": rss_before, "rss_after_mb": rss_after,
        "rss_peak_mb": rss_peak,
    }


async def main_async(args):
    from src.config import Settings

    if args.use_env:
        cfg = Settings()
    else:
        # 用代码默认值 + 占位必填项（不读 .env，避免真实 key 参与）
        cfg = Settings(_env_file=None, DEEPSEEK_API_KEY="sk-bench-placeholder-0000",
                       BOT_QQ=10000)
    loader = Loader(cfg)

    tiers = TIERS if args.tier == 0 else [t for t in TIERS if t["id"] == args.tier]
    if not tiers:
        print(f"没有匹配的档位: {args.tier}", file=sys.stderr)
        return []

    results = []
    for tier in tiers:
        if args.duration:
            tier = dict(tier, duration=args.duration)
        if not args.json:
            print()
            print(f">> 档位 {tier['id']} · {tier['name']}")
            print(f"   {tier['groups']} 群 x {tier['rate']} msg/s = 目标 "
                  f"{tier['groups'] * tier['rate']:.0f} msg/s，持续 {tier['duration']}s")
            print(f"   附件概率：文件 {tier['file_prob']:.0%} / 图片 "
                  f"{tier['image_prob']:.0%} / 插件 {tier['plugin_prob']:.0%}")
        r = await run_tier(tier, loader)
        results.append(r)
        if not args.json:
            print(f"   -> 实际 {r['throughput']:.1f} msg/s（{r['messages']} 条），"
                  f"错误 {r['errors']}")
            print(f"      延迟 p50 {r['p50_ms']:.2f} / p95 {r['p95_ms']:.2f} / "
                  f"p99 {r['p99_ms']:.2f} ms")
            print(f"      CPU {r['cpu_ratio']:.0%}（单核当量）  "
                  f"RSS {r['rss_before_mb']:.0f}->{r['rss_after_mb']:.0f} MB  "
                  f"峰值 {r['rss_peak_mb']:.0f} MB")
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", type=int, default=0, help="只跑指定档位（1-5，0=全部）")
    ap.add_argument("--duration", type=int, default=0, help="覆盖每档时长（秒）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--use-env", action="store_true", help="用真实 .env（默认代码默认值）")
    args = ap.parse_args()

    if not args.json:
        print("=" * 80)
        print("花璃负载基准（多群 + 文档 + 图片 + 插件并发）")
        print("=" * 80)

    results = asyncio.run(main_async(args))

    if args.json:
        print(json.dumps({"tiers": results}, ensure_ascii=False, indent=2))
        return

    if len(results) > 1:
        print()
        print("=" * 80)
        print("汇总")
        print("=" * 80)
        print(f"{'档位':<20} {'目标':>8} {'实际':>9} {'p95':>8} {'CPU':>6} {'RSS':>12}")
        for r in results:
            print(f"{r['name']:<20} {r['target_throughput']:>6.0f}/s "
                  f"{r['throughput']:>7.1f}/s {r['p95_ms']:>6.2f}ms "
                  f"{r['cpu_ratio']:>5.0%} {r['rss_before_mb']:>4.0f}->{r['rss_after_mb']:.0f}MB")
        print()
        print("说明：CPU 为「单核当量」（process_time / wall_time），>100% 表示多核并行。")
        print("      真实部署时 LLM 往返会让每群并发低得多，这里的速率是纯本地极限。")


if __name__ == "__main__":
    main()
