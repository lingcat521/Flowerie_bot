"""花璃全功能极限压测：所有子系统同时运行，找真正的饱和点。

与 bench_load.py 的区别：
  - bench_load.py  : 消息链 + 附件，模拟真实群聊节奏
  - bench_stress.py: **所有子系统同时满速运转**，看会不会崩 / 会不会 OOM / 谁先饱和

同时运行的子系统：
  1. 消息处理链（@检测 / 消毒 / 分句 / 表情提取）
  2. 文档解析（FileParser，持续高频）
  3. 图片转码（Pillow GIF→PNG）
  4. Web UI 渲染（面板页模板）
  5. SQLite 高频读写（真实 repository：设置 / 记忆 / 画像）
  6. 记忆写入（MemoryManager）
  7. 表情包索引查询
  8. 插件 JSON 往返
  9. 定时任务模拟（摘要拼装）

用法：
    python3 scripts/bench_stress.py               # 三档（约 90 秒）
    python3 scripts/bench_stress.py --tier 3      # 只跑极限档
    python3 scripts/bench_stress.py --json
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
import tempfile
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# 每个档位：并发路数（每路子系统各多少个 worker）
TIERS = [
    {"id": 1, "name": "全功能 x1", "lanes": 1, "duration": 20},
    {"id": 2, "name": "全功能 x3", "lanes": 3, "duration": 25},
    {"id": 3, "name": "全功能 x6(极限)", "lanes": 6, "duration": 30},
]


class Env:
    """构造所有子系统的真实实例（一次性，复用）。"""

    def __init__(self, cfg, tmpdir):
        self.cfg = cfg
        self.tmpdir = tmpdir
        self.errors = {}
        self._build()

    def _err(self, name, e):
        self.errors[name] = f"{type(e).__name__}: {e}"
        print(f"  [子系统不可用] {name}: {e}", file=sys.stderr)

    def _build(self):
        cfg = self.cfg
        td = self.tmpdir

        # 1) 文件解析
        self.parser = None
        try:
            from src.services.file_parser import FileParser
            self.parser = FileParser(cfg)
        except Exception as e:
            self._err("FileParser", e)

        # 2) SQLite repositories（真实）
        self.settings_repo = None
        self.sqlite_repo = None
        try:
            from src.repositories.settings_repository import SettingsRepository
            self.settings_repo = SettingsRepository(os.path.join(td, "settings.db"))
        except Exception as e:
            self._err("SettingsRepository", e)
        try:
            from src.repositories.sqlite_repository import SQLiteMemoryRepository
            self.sqlite_repo = SQLiteMemoryRepository(os.path.join(td, "memory.db"))
        except Exception as e:
            self._err("SQLiteRepository", e)

        # 3) 记忆
        self.memory = None
        try:
            from src.services.memory_manager import MemoryManager
            self.memory = MemoryManager(os.path.join(td, "memory.json"))
        except Exception as e:
            self._err("MemoryManager", e)

        # 4) 表情包 repository
        self.sticker_repo = None
        try:
            from src.repositories.sticker_repository import StickerRepository
            self.sticker_repo = StickerRepository(os.path.join(td, "stickers.db"))
        except Exception as e:
            self._err("StickerRepository", e)

        # 样本
        self.txt = (("文档里的一行内容，用来压测解析。" * 3) + chr(10)) * 200
        rows = "".join(f"{i},{i},{i},{i},{i}" + chr(10) for i in range(300))
        self.csv = ("a,b,c,d,e" + chr(10) + rows).encode("utf-8")
        self.gif = self._make_gif()
        self.png = self._make_png()

    @staticmethod
    def _make_png():
        try:
            from PIL import Image
            buf = io.BytesIO()
            Image.new("RGB", (640, 480), (100, 150, 200)).save(buf, "PNG", optimize=True)
            return buf.getvalue()
        except Exception:
            return b""

    @staticmethod
    def _make_gif():
        try:
            from PIL import Image
            frames = [Image.new("P", (100, 80), i * 30) for i in range(4)]
            buf = io.BytesIO()
            frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:],
                           duration=80, loop=0)
            return buf.getvalue()
        except Exception:
            return b""


def rss_mb():
    try:
        with open("/proc/self/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except Exception:
        pass
    return 0.0


# ---------- 各子系统 worker ----------

async def lane_messages(env, stop_at, stats, lane):
    from src.core.name_mention import detect
    from src.core.reply_splitter import extract_stickers, fragment_split
    from src.core.sanitizer import sanitize_untrusted_text

    cfg = types.SimpleNamespace(BOT_NICKNAME="花璃", BOT_QQ=10000, BOT_ALIASES="")

    class M:
        def __init__(self, t):
            self.content = t
            self.sender_id = 9000
            self.group_id = 10000 + lane

    n = 0
    while time.perf_counter() < stop_at:
        t0 = time.perf_counter()
        try:
            n += 1
            txt = f"[CQ:at,qq=10000] 测试消息 {n}，今天群里聊得挺热闹的"
            m = M(txt)
            detect(m, cfg)
            clean, _ = sanitize_untrusted_text(txt)
            rep = "我觉得，" + clean[:60] + "，可以再想想。"
            extract_stickers(rep)
            fragment_split(rep)
            stats["msg"] += 1
            stats["lat_msgs"].append((time.perf_counter() - t0) * 1000)
        except Exception as e:
            stats["err_msg"] += 1
            if stats["err_msg"] <= 2:
                print(f"  [msg lane{lane}] {e}", file=sys.stderr)
        await asyncio.sleep(0.005)  # 约 200 msg/s/路


async def lane_files(env, stop_at, stats, lane):
    if env.parser is None:
        return
    while time.perf_counter() < stop_at:
        t0 = time.perf_counter()
        try:
            await env.parser.parse_document("a.txt", env.txt.encode("utf-8"))
            await env.parser.parse_document("b.csv", env.csv)
            stats["file"] += 2
            stats["lat_files"].append((time.perf_counter() - t0) * 1000)
        except Exception as e:
            stats["err_file"] += 1
            if stats["err_file"] <= 2:
                print(f"  [file lane{lane}] {e}", file=sys.stderr)
        await asyncio.sleep(0.01)


async def lane_images(env, stop_at, stats, lane):
    from src.services.multimodal import gif_first_frame_png
    data = env.gif or env.png
    if not data:
        return
    while time.perf_counter() < stop_at:
        t0 = time.perf_counter()
        try:
            gif_first_frame_png(data)
            stats["img"] += 1
            stats["lat_imgs"].append((time.perf_counter() - t0) * 1000)
        except Exception as e:
            stats["err_img"] += 1
            if stats["err_img"] <= 2:
                print(f"  [img lane{lane}] {e}", file=sys.stderr)
        await asyncio.sleep(0.01)


async def lane_render(env, stop_at, stats, lane):
    try:
        from src.services.webui_render.pages import render_panel_page
    except Exception:
        return
    body = "<section>" + "<p>内容块</p>" * 30 + "</section>"
    while time.perf_counter() < stop_at:
        t0 = time.perf_counter()
        try:
            render_panel_page(theme_class="theme-night", bg_rules="", msg_html="",
                              body_html=body, active_tab="config")
            stats["render"] += 1
            stats["lat_renders"].append((time.perf_counter() - t0) * 1000)
        except Exception as e:
            stats["err_render"] += 1
            if stats["err_render"] <= 2:
                print(f"  [render lane{lane}] {e}", file=sys.stderr)
        await asyncio.sleep(0.01)


async def lane_db(env, stop_at, stats, lane):
    repo = env.settings_repo
    if repo is None:
        return
    i = 0
    while time.perf_counter() < stop_at:
        t0 = time.perf_counter()
        try:
            i += 1
            key = f"bench_key_{i % 50}"
            repo.set_pref(key, f"value-{i}-" + "x" * 80)
            repo.get_pref(key)
            stats["db"] += 2
            stats["lat_dbs"].append((time.perf_counter() - t0) * 1000)
        except Exception as e:
            stats["err_db"] += 1
            if stats["err_db"] <= 2:
                print(f"  [db lane{lane}] {type(e).__name__}: {e}", file=sys.stderr)
        await asyncio.sleep(0.005)


async def lane_memory(env, stop_at, stats, lane):
    mem = env.memory
    if mem is None:
        return
    i = 0
    while time.perf_counter() < stop_at:
        t0 = time.perf_counter()
        try:
            i += 1
            gid = 20000 + (i % 20)
            add = (getattr(mem, "add_message", None) or getattr(mem, "append", None)
                   or getattr(mem, "save_message", None) or getattr(mem, "add", None))
            if add is None:
                return
            try:
                add(gid, {"role": "user", "content": f"压测消息 {i}"})
            except TypeError:
                add(gid, 9000 + i % 100, "压测消息", "user")
            stats["mem"] += 1
            stats["lat_mems"].append((time.perf_counter() - t0) * 1000)
        except Exception as e:
            stats["err_mem"] += 1
            if stats["err_mem"] <= 2:
                print(f"  [mem lane{lane}] {type(e).__name__}: {e}", file=sys.stderr)
        await asyncio.sleep(0.005)


async def lane_stickers(env, stop_at, stats, lane):
    repo = env.sticker_repo
    if repo is None:
        return
    i = 0
    while time.perf_counter() < stop_at:
        t0 = time.perf_counter()
        try:
            i += 1
            fn = getattr(repo, "list_all", None) or getattr(repo, "all", None)
            if fn is not None:
                fn()
            stats["sticker"] += 1
            stats["lat_stickers"].append((time.perf_counter() - t0) * 1000)
        except Exception as e:
            stats["err_sticker"] += 1
            if stats["err_sticker"] <= 2:
                print(f"  [sticker lane{lane}] {type(e).__name__}: {e}", file=sys.stderr)
        await asyncio.sleep(0.02)


async def lane_plugin(env, stop_at, stats, lane):
    while time.perf_counter() < stop_at:
        t0 = time.perf_counter()
        try:
            payload = {"action": "call", "id": lane, "data": "y" * 512}
            back = json.loads(json.dumps(payload))
            if back["action"] != "call":
                raise RuntimeError("bad roundtrip")
            stats["plugin"] += 1
            stats["lat_plugins"].append((time.perf_counter() - t0) * 1000)
        except Exception as e:
            stats["err_plugin"] += 1
            if stats["err_plugin"] <= 2:
                print(f"  [plugin lane{lane}] {e}", file=sys.stderr)
        await asyncio.sleep(0.01)


async def lane_digest(env, stop_at, stats, lane):
    """定时摘要模拟：读一批消息 + 拼装提示词（纯 CPU）。"""
    while time.perf_counter() < stop_at:
        t0 = time.perf_counter()
        try:
            msgs = [f"用户{i}说：今天天气不错" for i in range(200)]
            joined = chr(10).join(msgs)
            prompt = "请总结以下群聊：" + chr(10) + joined[:4000]
            stats["digest"] += 1
            stats["lat_digests"].append((time.perf_counter() - t0) * 1000)
        except Exception as e:
            stats["err_digest"] += 1
            if stats["err_digest"] <= 2:
                print(f"  [digest lane{lane}] {e}", file=sys.stderr)
        await asyncio.sleep(0.05)


LANES = [
    ("消息链", lane_messages),
    ("文档解析", lane_files),
    ("图片转码", lane_images),
    ("UI 渲染", lane_render),
    ("SQLite", lane_db),
    ("记忆写入", lane_memory),
    ("表情索引", lane_stickers),
    ("插件往返", lane_plugin),
    ("摘要拼装", lane_digest),
]


async def run_tier(tier, env):
    stats = {
        "msg": 0, "file": 0, "img": 0, "render": 0, "db": 0,
        "mem": 0, "sticker": 0, "plugin": 0, "digest": 0,
    }
    for k in list(stats):
        stats[f"err_{k}"] = 0
        stats[f"lat_{k}s"] = []

    duration = tier["duration"]
    stop_at = time.perf_counter() + duration

    gc.collect()
    rss_before = rss_mb()
    cpu_before = time.process_time()
    wall_before = time.perf_counter()
    rss_samples = [rss_before]

    tasks = []
    for lane in range(tier["lanes"]):
        for name, fn in LANES:
            tasks.append(asyncio.create_task(fn(env, stop_at, stats, lane)))

    async def watch():
        while time.perf_counter() < stop_at:
            rss_samples.append(rss_mb())
            await asyncio.sleep(0.5)

    watcher = asyncio.create_task(watch())
    await asyncio.gather(*tasks, return_exceptions=True)
    watcher.cancel()

    wall = time.perf_counter() - wall_before
    cpu = time.process_time() - cpu_before

    def pct(key, p):
        arr = sorted(stats.get(key) or [])
        if not arr:
            return 0.0
        return arr[min(len(arr) - 1, int(len(arr) * p))]

    detail = {}
    for name, key in (("消息链", "msg"), ("文档解析", "file"), ("图片转码", "img"),
                      ("UI 渲染", "render"), ("SQLite", "db"), ("记忆写入", "mem"),
                      ("表情索引", "sticker"), ("插件往返", "plugin"), ("摘要拼装", "digest")):
        detail[name] = {
            "count": stats[key],
            "per_sec": round(stats[key] / wall, 1) if wall else 0,
            "p50_ms": round(pct(f"lat_{key}s", 0.50), 2),
            "p95_ms": round(pct(f"lat_{key}s", 0.95), 2),
            "errors": stats[f"err_{key}"],
        }

    total_ops = sum(stats[k] for k in ("msg", "file", "img", "render", "db", "mem", "sticker", "plugin", "digest"))
    total_err = sum(stats[f"err_{k}"] for k in ("msg", "file", "img", "render", "db", "mem", "sticker", "plugin", "digest"))

    return {
        "tier": tier["id"], "name": tier["name"], "lanes": tier["lanes"],
        "duration_s": round(wall, 1),
        "total_ops": total_ops,
        "ops_per_sec": round(total_ops / wall, 1) if wall else 0,
        "total_errors": total_err,
        "cpu_ratio": (cpu / wall) if wall else 0,
        "rss_before_mb": round(rss_before, 1),
        "rss_peak_mb": round(max(rss_samples), 1),
        "rss_after_mb": round(rss_mb(), 1),
        "detail": detail,
    }


async def main_async(args):
    from src.config import Settings

    tmpdir = tempfile.mkdtemp(prefix="flowerie_stress_")
    cfg = Settings(_env_file=None,
                   DEEPSEEK_API_KEY="sk-bench-placeholder-0000", BOT_QQ=10000)
    env = Env(cfg, tmpdir)

    if env.errors and not args.json:
        print("不可用的子系统：")
        for k, v in env.errors.items():
            print(f"  - {k}: {v}")
        print()

    tiers = TIERS if args.tier == 0 else [t for t in TIERS if t["id"] == args.tier]
    results = []
    for tier in tiers:
        if args.duration:
            tier = dict(tier, duration=args.duration)
        if not args.json:
            print()
            print(f">> {tier['name']} · {tier['lanes']} 路 × 9 个子系统 · {tier['duration']}s")
        r = await run_tier(tier, env)
        results.append(r)
        if not args.json:
            print(f"   总计 {r['total_ops']} 次操作 / {r['ops_per_sec']:.0f} ops/s，"
                  f"错误 {r['total_errors']}")
            print(f"   CPU {r['cpu_ratio']:.0%}（单核当量）  "
                  f"RSS {r['rss_before_mb']:.0f}→{r['rss_after_mb']:.0f} MB"
                  f"（峰值 {r['rss_peak_mb']:.0f}）")
            for name, d in r["detail"].items():
                if d["count"]:
                    print(f"     {name:<8} {d['per_sec']:>8.1f}/s  "
                          f"p50 {d['p50_ms']:>6.2f}ms  p95 {d['p95_ms']:>6.2f}ms  "
                          f"err {d['errors']}")
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", type=int, default=0)
    ap.add_argument("--duration", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not args.json:
        print("=" * 84)
        print("花璃全功能极限压测（9 个子系统同时满速运转）")
        print("=" * 84)

    results = asyncio.run(main_async(args))

    if args.json:
        print(json.dumps({"tiers": results}, ensure_ascii=False, indent=2))
        return

    if len(results) > 1:
        print()
        print("=" * 84)
        print("汇总")
        print("=" * 84)
        print(f"{'档位':<18} {'ops/s':>9} {'错误':>5} {'CPU':>6} {'RSS 峰值':>10}")
        for r in results:
            print(f"{r['name']:<18} {r['ops_per_sec']:>9.0f} {r['total_errors']:>5} "
                  f"{r['cpu_ratio']:>5.0%} {r['rss_peak_mb']:>8.0f}MB")

    print()
    print("说明：这是**所有功能同时满速**的合成压力，远超真实使用。")
    print("      真实场景每个群同一时刻通常只有 1 个 LLM 请求在等。")
    print("      关注点：错误数是否 0、内存是否线性增长、哪个子系统先饱和。")


if __name__ == "__main__":
    main()
