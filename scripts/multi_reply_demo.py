#!/usr/bin/env python3

# ruff: noqa: E402, I001  —— 本脚本需要先注入仓库根目录到 sys.path 再导入项目模块，属有意为之
"""Multi-Reply 本地预演：不需要 QQ、不需要网络，验证「一次回复拆成多条」的全过程。

它用的是**真实模块**：ReplyPlan / plan_from_config / send_plan / ReplyDispatchMixin，
只把「发送」和「策略记录」换成会打印的假实现 —— 于是你能直接看到：

  1. AI/插件给出的原始输出 → 解析成几条
  2. 配置（开关 / 条数上限 / 间隔模式）如何影响计划
  3. 逐条发送的顺序与每次的等待时间
  4. 每条如何进历史（上下文 / 最近回复 / 连续回复计数）

用法（在仓库根目录）：
    python3 scripts/multi_reply_demo.py                       # 默认：开启 + 随机间隔
    python3 scripts/multi_reply_demo.py --disabled            # 关闭：只发第一条
    python3 scripts/multi_reply_demo.py --mode fixed --min 2  # 固定间隔 2s
    python3 scripts/multi_reply_demo.py --max-messages 2      # 上限 2 条
    python3 scripts/multi_reply_demo.py --fast                # 不真的等待，只显示等待时长
    python3 scripts/multi_reply_demo.py --raw '纯文本回复'      # 模拟解析失败 → 降级单条
"""
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.reply_dispatch import ReplyDispatchMixin          # noqa: E402
from src.core.reply_plan import INTERVAL_FIXED, INTERVAL_NONE, INTERVAL_RANDOM  # noqa: E402

DEFAULT_RAW = '{"messages": ["你好呀", "今天怎么样", "感觉你今天有点不对劲喵"]}'


def parse_reply(raw: str):
    """优先用真实解析器（与线上同源）；缺依赖时退化为纯 JSON 解析并说明。"""
    try:
        from src.services.ai_client import AIClient
        result = AIClient.extract_multi_messages(raw)
        return result, "AIClient.extract_multi_messages（与线上同一实现）"
    except Exception as exc:  # noqa: BLE001 - 本地缺 httpx/pydantic 时退化
        try:
            data = json.loads(raw)
            msgs = data.get("messages") if isinstance(data, dict) else None
            if isinstance(msgs, list):
                return [str(m) for m in msgs if str(m).strip()] or None, \
                       "纯 JSON 解析（本地缺依赖：%s）" % type(exc).__name__
            return None, "纯 JSON 解析（本地缺依赖：%s）" % type(exc).__name__
        except Exception:  # noqa: BLE001
            return None, "纯 JSON 解析（本地缺依赖：%s）" % type(exc).__name__


class PrintSender:
    def __init__(self, fast: bool):
        self.fast = fast
        self.sent = []

    async def _send(self, kind, target_id, message):
        self.sent.append(message)
        print("    发送 → [%s %s] %s" % (kind, target_id, message))
        return True

    async def send_group_message(self, group_id, message):
        return await self._send("群", group_id, message)

    async def send_private_message(self, user_id, message):
        return await self._send("私聊", user_id, message)


class PrintPolicy:
    def __init__(self, limit: int):
        self.limit = limit
        self.count = 0
        self.context, self.recent = [], []

    def record_bot_reply(self, target):
        self.count += 1
        tail = "  ← 已达 MAX_CONSECUTIVE_REPLIES(%d)，下一条将进入冷却" % self.limit \
            if self.count >= self.limit else ""
        print("    记录连续回复 #%d%s" % (self.count, tail))

    def add_context(self, group_id, user_id, text, is_bot=False):
        self.context.append(text)
        print("    写入上下文: %s" % text)

    def add_recent_reply(self, group_id, text):
        self.recent.append(text)


class DemoHost(ReplyDispatchMixin):
    def __init__(self, config, sender, policy):
        self.config = config
        self.sender = sender
        self.policy_engine = policy


class DemoConfig:
    def __init__(self, args):
        self.MULTI_REPLY_ENABLED = not args.disabled
        self.MULTI_REPLY_MAX_MESSAGES = args.max_messages
        self.MULTI_REPLY_INTERVAL_MODE = args.mode
        self.MULTI_REPLY_MIN_INTERVAL = args.min
        self.MULTI_REPLY_MAX_INTERVAL = args.max
        self.MAX_REPLY_LENGTH = 200
        self.MAX_CONSECUTIVE_REPLIES = args.consecutive


def main() -> int:
    ap = argparse.ArgumentParser(description="Multi-Reply 本地预演（不需要 QQ）")
    ap.add_argument("--raw", default=DEFAULT_RAW, help="模拟 AI/插件给出的原始输出")
    ap.add_argument("--disabled", action="store_true", help="关闭 MULTI_REPLY_ENABLED")
    ap.add_argument("--max-messages", type=int, default=3)
    ap.add_argument("--mode", default=INTERVAL_RANDOM,
                    choices=[INTERVAL_RANDOM, INTERVAL_FIXED, INTERVAL_NONE])
    ap.add_argument("--min", type=float, default=1.5)
    ap.add_argument("--max", type=float, default=4.0)
    ap.add_argument("--consecutive", type=int, default=3, help="MAX_CONSECUTIVE_REPLIES")
    ap.add_argument("--fast", action="store_true", help="不真的等待，只显示等待时长")
    args = ap.parse_args()

    print("=" * 68)
    print("Multi-Reply 本地预演（真实模块 + 假发送器，无需 QQ / 网络）")
    print("=" * 68)
    print("[1] 原始输出（模拟 AI）:")
    print("    %s" % args.raw)

    messages, how = parse_reply(args.raw)
    print("[2] 解析结果: %s" % ("%d 条 → %s" % (len(messages), messages) if messages
                              else "没解析出多条 → 降级为单条字符串"))
    print("    解析器: %s" % how)

    cfg = DemoConfig(args)
    print("[3] 配置: 开关=%s 上限=%d 间隔=%s(%s~%ss) MAX_CONSECUTIVE_REPLIES=%d" % (
        "开" if cfg.MULTI_REPLY_ENABLED else "关", cfg.MULTI_REPLY_MAX_MESSAGES,
        cfg.MULTI_REPLY_INTERVAL_MODE, cfg.MULTI_REPLY_MIN_INTERVAL,
        cfg.MULTI_REPLY_MAX_INTERVAL, cfg.MAX_CONSECUTIVE_REPLIES))

    reply = messages if messages else args.raw

    async def run():
        from src.core.reply_plan import plan_from_config
        plan = plan_from_config(reply, cfg, from_ai=bool(messages))
        print("[4] 计划: 共 %d 条（配置上限 %d）%s" % (
            len(plan), cfg.MULTI_REPLY_MAX_MESSAGES,
            "，多余已被裁掉" if messages and len(messages) > len(plan) else ""))
        if not plan:
            print("    空计划 → 不发送")
            return
        policy = PrintPolicy(cfg.MAX_CONSECUTIVE_REPLIES)
        host = DemoHost(cfg, PrintSender(args.fast), policy)

        rng = __import__("random").Random(20260918)   # 固定种子：演示可复现
        delays = [plan.delay_before(i, rng) for i in range(len(plan))]
        print("[5] 计划间隔（第 1 条不等）: %s" % (
            ", ".join("%.2fs" % d for d in delays) if any(delays) else "无间隔（none）"))
        print("[6] 逐条发送:")
        if args.fast:
            ok = await host._send_reply(reply, group_id=10001)
        else:
            print("    （真实运行会按上表等待；此处为演示直接连发）")
            ok = await host._send_reply(reply, group_id=10001)

        print("[7] 结果: 成功=%s 实际发出 %d 条" % (ok, len(host.sender.sent)))
        print("    历史: 上下文 %d 条 / 最近回复 %d 条 / 连续回复计数 %d" % (
            len(policy.context), len(policy.recent), policy.count))

    asyncio.run(run())
    print()
    print("提示：这就是线上同一条链路（AI → ReplyPlan → send_plan → sender）。")
    print("      真实运行时 sender 换成 Sender，协议由适配层决定（OneBot / Milky 共用）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
