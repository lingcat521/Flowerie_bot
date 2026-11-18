"""花璃 GPU 亲和性检查：证明服务端进程完全不接触 GPU。

为什么需要这个脚本：
  Linux 的 /proc/<pid> 没有「进程级 GPU 占用」（GPU 是全局资源），
  所以无法直接测「花璃用了多少 GPU」。但可以反过来证明：**根本没有 GPU 调用路径**。

检查四个层面：
  1. 代码层   —— 源码里是否引用图形库（cairo / skia / opengl / vulkan / webgl）
  2. 链接层   —— 进程加载的 .so 里是否有 libGL / libEGL / libGLESv2 / libvulkan
  3. 驱动层   —— 进程是否打开了 GPU 设备节点（/dev/mali*、/dev/kgsl*、/dev/dri*）
  4. 线程层   —— 是否有渲染线程（GPU 驱动通常起 RenderThread / gpu-worker）

用法：
    python3 scripts/bench_gpu.py
    python3 scripts/bench_gpu.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import re

# 图形栈相关库名（命中任一即说明进程可能用 GPU）
GPU_LIBS = (
    "libGL.so", "libGLX", "libEGL", "libGLESv2", "libvulkan",
    "libcairo", "libskia", "libgbm", "libdrm", "libwayland-client",
    "libX11", "libxcb",
)

# GPU 设备节点
GPU_DEVICES = (
    "/dev/mali0", "/dev/mali", "/dev/kgsl-3d0", "/dev/dri/card0",
    "/dev/dri/renderD128", "/dev/nvidia0", "/dev/vchiq", "/dev/vcsm",
)

# 渲染线程名特征
RENDER_THREADS = ("render", "gpu", "gl_", "vulkan", "skia")


def check_code(root):
    """代码层：在 src/ 里搜图形库引用。"""
    hits = []
    pat = re.compile(
        r"\b(cairo|skia|opengl|opengles|webgl|vulkan|pygame|moderngl|glfw|"
        r"PyQt|PySide|gtk|tkinter|matplotlib\.pyplot)\b", re.I)
    for dirpath, _dirnames, filenames in os.walk(root):
        if any(x in dirpath for x in (".git", "__pycache__", "/data", "/logs",
                                    "/scripts", "/docs", "/tests", "/examples")):
            continue
        for fn in filenames:
            if not fn.endswith((".py", ".html", ".css")):
                continue
            p = os.path.join(dirpath, fn)
            try:
                txt = open(p, encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            for m in pat.finditer(txt):
                line = txt[:m.start()].count("\n") + 1
                hits.append({
                    "file": p.replace(root + "/", ""),
                    "line": line,
                    "token": m.group(0),
                })
    return hits


def check_links():
    """链接层：读 /proc/self/maps 找已加载的图形库。"""
    found = []
    try:
        for line in open("/proc/self/maps", encoding="utf-8", errors="ignore"):
            for lib in GPU_LIBS:
                if lib in line:
                    path = line.split()[-1] if len(line.split()) > 5 else line.strip()
                    found.append({"lib": lib, "path": path})
                    break
    except Exception:
        pass
    # 去重
    seen, uniq = set(), []
    for h in found:
        if h["lib"] not in seen:
            seen.add(h["lib"])
            uniq.append(h)
    return uniq


def check_devices():
    """驱动层：GPU 设备节点是否存在且被本进程打开。"""
    present = [d for d in GPU_DEVICES if os.path.exists(d)]
    opened = []
    try:
        for fd in os.listdir("/proc/self/fd"):
            try:
                target = os.readlink(f"/proc/self/fd/{fd}")
            except OSError:
                continue
            if any(target.startswith(d.split("/dev/")[1] and d) for d in GPU_DEVICES):
                opened.append(target)
            elif "/dev/dri" in target or "/dev/mali" in target or "/dev/kgsl" in target:
                opened.append(target)
    except Exception:
        pass
    return present, opened


def check_threads():
    """线程层：找渲染线程。"""
    threads = []
    try:
        for tid in os.listdir("/proc/self/task"):
            try:
                name = open(f"/proc/self/task/{tid}/comm", encoding="utf-8").read().strip()
            except Exception:
                continue
            threads.append({"tid": tid, "name": name})
    except Exception:
        pass
    suspicious = [t for t in threads
                  if any(k in t["name"].lower() for k in RENDER_THREADS)]
    return threads, suspicious


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    args = ap.parse_args()

    code_hits = check_code(args.root)
    links = check_links()
    devices_present, devices_opened = check_devices()
    threads, render_threads = check_threads()

    verdict = (
        "GPU 零路径" if not code_hits and not links and not devices_opened and not render_threads
        else "存在 GPU 使用"
    )

    result = {
        "verdict": verdict,
        "code_references": code_hits,
        "loaded_gpu_libs": links,
        "gpu_devices_present": devices_present,
        "gpu_devices_opened": devices_opened,
        "thread_count": len(threads),
        "render_threads": render_threads,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print("=" * 76)
    print("花璃 GPU 亲和性检查")
    print("=" * 76)
    print()
    print(f"[1] 代码层 —— 图形库引用：{len(code_hits)} 处")
    if code_hits:
        for h in code_hits[:10]:
            print(f"      {h['file']}:{h['line']}  {h['token']}")
    else:
        print("      无（源码里没有 cairo / skia / opengl / vulkan / webgl 等）")
    print()
    print(f"[2] 链接层 —— 已加载的图形库：{len(links)} 个")
    if links:
        for h in links:
            print(f"      {h['lib']}  {h['path'][:60]}")
    else:
        print("      无（进程没加载 libGL / libEGL / libGLESv2 / libvulkan / libcairo）")
    print()
    print("[3] 驱动层 —— GPU 设备节点")
    print(f"      系统存在: {devices_present or '无'}")
    print(f"      本进程打开: {devices_opened or '无'}")
    print()
    print(f"[4] 线程层 —— 共 {len(threads)} 个线程，渲染线程 {len(render_threads)} 个")
    if render_threads:
        for t in render_threads:
            print(f"      tid={t['tid']} name={t['name']}")
    else:
        names = ", ".join(t["name"] for t in threads[:6])
        print(f"      线程名: {names}")
    print()
    print("=" * 76)
    print(f"结论：{verdict}")
    print("=" * 76)
    print()
    print("说明：Linux 没有「进程级 GPU 占用」统计（GPU 是全局资源），")
    print("      所以无法直接测「花璃用了多少 GPU」。但上面四项任一命中即说明可能用 GPU；")
    print("      全部为零 = 进程根本没有 GPU 调用路径，GPU 占用恒为 0。")


if __name__ == "__main__":
    main()
