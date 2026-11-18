# 性能基线（树莓派可行性评估）

> 对应 **v2.19.3**。本文回答一个问题：**花璃能不能跑在树莓派上，开销多大。**

## 先跑一遍

```bash
python3 scripts/bench.py          # 全部用例
python3 scripts/bench.py --quick  # 快速版（迭代减半）
python3 scripts/bench.py --json   # JSON 输出，便于跨机器对比
```

脚本只测**纯本地计算**（不含网络与 LLM），这样换机器才有可比性。

---

## 参考实测（Android 手机，Dimensity 700）

测试机：MT6833V/ZA（2×Cortex-A76 @2.2GHz + 6×Cortex-A55 @2.0GHz），8 核，Python 3.14.8。

| 用例 | p50 | p95 | 吞吐 | 峰值内存 |
| :--- | ---: | ---: | ---: | ---: |
| 分句 · 短句(18字) | 0.019 ms | 0.022 ms | 48,876 ops/s | 5 KB |
| 分句 · 中句(160字) | 0.046 ms | 0.064 ms | 21,040 ops/s | 6 KB |
| 分句 · 长句(1600字) | 1.194 ms | 1.252 ms | 834 ops/s | 19 KB |
| 表情标记提取 | 0.025 ms | 0.027 ms | 38,154 ops/s | 5 KB |
| 不可信文本消毒(1KB) | 0.095 ms | 0.107 ms | 10,276 ops/s | 5 KB |
| @ 检测（命中/未命中） | 0.003 ms | 0.004 ms | ~350,000 ops/s | 3 KB |
| 重复检测 · 单次 | 0.067 ms | 0.094 ms | 14,249 ops/s | 7 KB |
| SQLite 写入(100B) | 3.406 ms | 4.666 ms | 300 ops/s | 7 KB |
| SQLite 批量写 100 行 | 5.289 ms | 8.972 ms | 190 ops/s | 15 KB |
| SQLite 按主键读(1000 行库) | 0.352 ms | 0.455 ms | 2,823 ops/s | 122 KB |
| 解析 txt(35KB) | 5.831 ms | 7.489 ms | 170 ops/s | 84 KB |
| 解析 csv(500 行) | 7.125 ms | 9.512 ms | 136 ops/s | 79 KB |
| 面板页渲染(50 块正文) | 4.545 ms | 7.121 ms | 203 ops/s | 167 KB |
| 遍历 SCHEMA(256 键) | 0.088 ms | 0.092 ms | 11,170 ops/s | 4 KB |
| **本地处理链**（@检测→消毒→分句） | **0.128 ms** | 0.157 ms | 7,574 ops/s | 6 KB |

**整体内存**：进程 RSS **85 MB**（导入 12 个核心模块后增量 +15 MB）。

---

## 关键结论：本地开销可以忽略

一条群消息的本地处理链（@ 检测 → 消毒 → 分句）**0.128 毫秒**。

而一次 LLM 往返通常要 **1000~5000 毫秒**。也就是说：

```
总延迟 ≈ 10 ms（网络收发） + 1500 ms（LLM） + 0.13 ms（花璃本地）
                                    ↑ 占 0.009%
```

**本地处理再慢 20 倍，也才刚刚到 2.5 毫秒 —— 感知不到。**
这是树莓派能跑的根本原因：花璃不是计算密集型，它是 IO 等待型（等 API 返回）。

---

## 各代树莓派估算

按上表实测值，以 Cortex-A76（测试机大核）为基准折算。树莓派单核性能大致是它的：

| 机型 | CPU | 单核相对性能 | 本地处理链 p50 | 判断 |
| :--- | :--- | ---: | ---: | :--- |
| **Pi 5** | Cortex-A76 @2.4GHz | ~1.1× | ~0.12 ms | ✅ 毫无压力 |
| **Pi 4** | Cortex-A72 @1.5GHz | ~0.55× | ~0.23 ms | ✅ 完全够用 |
| **Pi 3B+** | Cortex-A53 @1.4GHz | ~0.25× | ~0.51 ms | ⚠️ 能用，但内存吃紧 |
| Pi Zero 2 W | Cortex-A53 @1GHz | ~0.15× | ~0.85 ms | ⚠️ 单条能跑，并发悬 |
| Pi Zero W | ARM11 @1GHz | ~0.03× | ~4 ms | ❌ 不建议（512MB 内存也不够） |

> 折算只是量级参考。真实差异受内存带宽、SD 卡 IO、Python 版本影响，
> 拿到机器后请自己跑一次 `python3 scripts/bench.py --json` 对比。

---

## 内存是真正的门槛

性能不是问题，**内存才是**：

| 组件 | 常驻内存 |
| :--- | ---: |
| Python 进程 + 核心模块 | ~85 MB |
| SQLite（含记忆/画像/知识库增长） | 10~100 MB |
| 表情包索引（几千张的元数据） | 5~30 MB |
| 插件进程（每个独立进程） | 20~50 MB/个 |
| **典型总计** | **150~300 MB** |

| 机型 | 内存 | 结论 |
| :--- | ---: | :--- |
| Pi 5 / Pi 4 (4GB·8GB) | 4–8 GB | ✅ 充裕 |
| Pi 4 (2GB) | 2 GB | ✅ 够用 |
| Pi 3B+ (1GB) | 1 GB | ⚠️ 能跑，别装重插件 |
| Pi Zero 2 W (512MB) | 512 MB | ❌ 会 OOM |

---

## 其他注意事项

### SD 卡是最大隐患

SQLite 写入在测试机上是 **3.4 ms/次**（这已经是 DDR 内存的速度）。
换成 SD 卡（尤其 Class 10 低端卡）可能慢 10~50 倍，且寿命有限——
SQLite 频繁写会加速磨损。

**建议**：
- 用 **USB 3.0 SSD** 而非 SD 卡（Pi 4/5 支持 USB 启动）
- 或至少 A2 级 microSD
- 开启 SQLite WAL 模式（花璃已默认开启）

### 无头浏览器跑不了

`tests/e2e/` 需要 Chromium。树莓派上要通过 `apt install chromium-browser`
（Pi OS 有 ARM 版），能跑但很慢（单次 E2E 可能 30 秒+）。CI 里跑就行，本地可以 skip。

### NapCat / OneBot 端的开销

这部分**不在花璃进程内**，但同样占资源：
NapCat 是 Node.js，空载约 **150~250 MB**。所以：

```
树莓派总占用 ≈ 花璃 200 MB + NapCat 200 MB ≈ 400 MB
```

### 无 GPU 需求

花璃不跑本地模型，识图/搜索/对话全走 DeepSeek API。**GPU 完全不需要**，
Pi 5 的 VideoCore VII 闲着就闲着。

---

## 推荐配置

| 用途 | 推荐 |
| :--- | :--- |
| 1~3 个群，轻度使用 | **Pi 4 (2GB) + A2 microSD** |
| 5~10 个群 + 插件 + 表情包多 | **Pi 4 (4GB) 或 Pi 5 + USB SSD** |
| 多实例 | Pi 5 (8GB) + SSD |

**不推荐**：Pi Zero 系列（内存/IO 双重瓶颈）、Pi 3B+ 以下。

---

## 怎么在你自己的机器上对比

```bash
# 树莓派上
git clone <repo> && cd Flowerie_bot
python3 scripts/bench.py --json > pi.json

# 对比两台机器的结果
python3 - <<'EOF'
import json
a = json.load(open('pi.json')); b = json.load(open('phone.json'))
for ra, rb in zip(a['results'], b['results']):
    ratio = ra['p50'] / rb['p50'] if rb['p50'] else 0
    print(f"{ra['name']:<28} {ra['p50']:8.3f} vs {rb['p50']:8.3f} ms  ({ratio:.2f}x)")
EOF
```

---

## 相关文档

[development.md](../guides/development.md)（测试分层与命令）、
[install-termux.md](../guides/install-termux.md)（Termux 部署，与树莓派 Linux 环境相近）、
[install-release-guide.md](../guides/install-release-guide.md)（Release 资产，含 arm64 Linux 二进制）。
