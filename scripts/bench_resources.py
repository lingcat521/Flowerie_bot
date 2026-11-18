"""花璃资源占用分析：除了 CPU 和内存，还吃哪些资源。

回答一个部署问题：搬到树莓派（尤其 SD 卡）时，除了 CPU/内存还要担心什么。

测量维度：
  1. CPU      —— 用户态 / 内核态拆分
  2. 内存      —— RSS / VMS
  3. 磁盘 IO   —— read_bytes / write_bytes（**直接关系 SD 卡寿命**）
  4. 系统调用  —— read/write 次数（小写入多 = fsync 压力大）
  5. 文件描述符 —— fd 峰值
  6. 线程数
  7. 磁盘空间  —— 数据目录实际占用

用法：
    python3 scripts/bench_resources.py            # 跑混合负载并采样
    python3 scripts/bench_resources.py --idle 10  # 只测空闲 10 秒
"""
from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def read_status():
    """读 /proc/self 的全部关键指标。"""
    out = {
        "rss_mb": 0.0, "vms_mb": 0.0, "threads": 0, "fds": 0,
        "utime": 0.0, "stime": 0.0,
        "rchar": 0, "wchar": 0, "read_bytes": 0, "write_bytes": 0,
        "syscr": 0, "syscw": 0,
    }
    try:
        with open("/proc/self/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    out["rss_mb"] = int(line.split()[1]) / 1024
                elif line.startswith("VmSize:"):
                    out["vms_mb"] = int(line.split()[1]) / 1024
                elif line.startswith("Threads:"):
                    out["threads"] = int(line.split()[1])
    except Exception:
        pass
    try:
        out["fds"] = len(os.listdir("/proc/self/fd"))
    except Exception:
        pass
    try:
        with open("/proc/self/io", encoding="utf-8") as f:
            for line in f:
                k, v = line.split(":", 1)
                if k in out:
                    out[k] = int(v.strip())
    except Exception:
        pass
    return out


def dir_size_mb(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return total / 1048576


# ---------- 负载 ----------

async def load_mixed(cfg, stop_at, tmpdir):
    """混合负载：SQLite 高频写 + 文件解析 + 图片 + 消息链。"""
    from src.core.reply_splitter import fragment_split
    from src.core.sanitizer import sanitize_untrusted_text
    from src.repositories.settings_repository import SettingsRepository
    from src.services.multimodal import gif_first_frame_png

    repo = SettingsRepository(os.path.join(tmpdir, "s.db"))
    try:
        from src.services.file_parser import FileParser
        parser = FileParser(cfg)
    except Exception:
        parser = None

    txt = (("文档内容行" * 5) + chr(10)) * 150
    try:
        import io as _io

        from PIL import Image
        frames = [Image.new("P", (80, 60), i * 25) for i in range(3)]
        buf = _io.BytesIO()
        frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:],
                       duration=80, loop=0)
        gif = buf.getvalue()
    except Exception:
        gif = b""

    i = 0
    while time.perf_counter() < stop_at:
        i += 1
        try:
            # SQLite 写（真实 fsync 压力）
            repo.set_pref(f"k{i % 30}", "v" * 120)
            repo.get_pref(f"k{i % 30}")
            # 文本链
            clean, _ = sanitize_untrusted_text("测试消息内容，包含一些标点。")
            fragment_split(clean + "，好的。")
            # 文件解析
            if parser is not None:
                await parser.parse_document("a.txt", txt.encode("utf-8"))
            # 图片
            if gif:
                gif_first_frame_png(gif)
        except Exception:
            pass
        await asyncio.sleep(0.01)


async def main_async(args):
    from src.config import Settings

    cfg = Settings(_env_file=None,
                   DEEPSEEK_API_KEY="sk-bench-placeholder-0000", BOT_QQ=10000)
    tmpdir = tempfile.mkdtemp(prefix="flowerie_res_")

    gc.collect()
    if not args.json:
        print("=" * 78)
        print("花璃资源占用分析")
        print("=" * 78)
        print()

    base = read_status()

    if args.idle:
        if not args.json:
            print(f"[空闲] 静置 {args.idle}s，期间无任何操作...")
        await asyncio.sleep(args.idle)
        idle = read_status()
        delta_disk = (idle["write_bytes"] - base["write_bytes"]) / 1048576
        if not args.json:
            print(f"  磁盘写入 {delta_disk:.2f} MB（{delta_disk / args.idle:.3f} MB/s）")
            print(f"  wchar {idle['wchar'] - base['wchar']:,}  系统调用 write "
                  f"{idle['syscw'] - base['syscw']:,}")
        if not args.json:
            print()
        base = idle

    if not args.json:
        print("[负载] 混合负载 15s：SQLite 高频写 + 文件解析 + 图片 + 文本链")
    stop_at = time.perf_counter() + 15
    cpu0 = time.process_time()
    t0 = time.perf_counter()
    await load_mixed(cfg, stop_at, tmpdir)
    wall = time.perf_counter() - t0
    cpu_used = time.process_time() - cpu0
    after = read_status()

    w_bytes = after["write_bytes"] - base["write_bytes"]
    r_bytes = after["read_bytes"] - base["read_bytes"]
    w_char = after["wchar"] - base["wchar"]
    r_char = after["rchar"] - base["rchar"]
    syscw = after["syscw"] - base["syscw"]
    syscr = after["syscr"] - base["syscr"]

    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    disk_data = dir_size_mb(data_dir) if os.path.isdir(data_dir) else 0.0

    result = {
        "duration_s": round(wall, 1),
        "cpu_ratio": round(cpu_used / wall, 3) if wall else 0,
        "rss_mb": round(after["rss_mb"], 1),
        "vms_mb": round(after["vms_mb"], 1),
        "threads": after["threads"],
        "fds": after["fds"],
        "disk_write_mb": round(w_bytes / 1048576, 3),
        "disk_read_mb": round(r_bytes / 1048576, 3),
        "write_mb_per_s": round(w_bytes / 1048576 / wall, 4) if wall else 0,
        "write_chars": w_char,
        "read_chars": r_char,
        "syscw": syscw,
        "syscr": syscr,
        "avg_write_bytes_per_call": round(w_char / syscw, 1) if syscw else 0,
        "data_dir_mb": round(disk_data, 1),
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print()
    print("-" * 78)
    print(f"{'指标':<26} {'数值':>20}")
    print("-" * 78)
    print(f"{'CPU（单核当量）':<24} {result['cpu_ratio']:>18.0%}")
    print(f"{'内存 RSS':<24} {result['rss_mb']:>16.0f} MB")
    print(f"{'内存 VMS（虚拟）':<24} {result['vms_mb']:>16.0f} MB")
    print(f"{'线程数':<26} {result['threads']:>19}")
    print(f"{'文件描述符':<24} {result['fds']:>19}")
    print("-" * 78)
    print(f"{'磁盘写入（物理）':<22} {result['disk_write_mb']:>14.2f} MB")
    print(f"{'磁盘读取（物理）':<22} {result['disk_read_mb']:>14.2f} MB")
    print(f"{'写入速率':<25} {result['write_mb_per_s']:>16.3f} MB/s")
    print(f"{'写入字符数':<24} {result['write_chars']:>19,}")
    print(f"{'write 系统调用':<23} {result['syscw']:>19,}")
    print(f"{'平均每次写':<25} {result['avg_write_bytes_per_call']:>15.0f} B")
    print("-" * 78)
    print(f"{'数据目录占用':<24} {result['data_dir_mb']:>16.1f} MB")
    print()
    print("解读：")
    print("  · 物理写 << 字符数 说明走了页缓存（批量刷盘），对小文件友好")
    print("  · 平均每次写越小，说明 fsync 压力越大 —— 这才是 SD 卡的杀手")
    print("  · fd 数量反映并发连接上限，1100 左右会碰到默认 ulimit")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--idle", type=int, default=0, help="额外测 N 秒空闲")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
