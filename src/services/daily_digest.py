"""DailyDigestService：每日凌晨定点把当天的群聊对话压缩成滚动摘要。

移植自 DSH compaction 的核心设计（dsh-compaction-basic 0.2.x）：
  * 结构化摘要指令（小节按群聊场景重写）
  * 嵌套合并语义：已有摘要块是 PRIOR checkpoint，merge 而非照抄
    （连续运行几个月不崩盘的根本——上下文里永远只有一份摘要）
  * "既定背景" preamble：模型把摘要当背景而非要复述的稿子
  * 收敛检查：摘要不得比原文还长，否则拒写（防爆膨）
  * 快照语义：取缓冲期间群照常收消息，摘要只覆盖被取走的范围

数据流与工作上下文分家（对应 DSH 的 log/surface 分离精神）：
  * 每日缓冲（record_message）是摘要的数据源，最多 N 条/群，独立于
    GroupState.context（deque 只装最近上下文，不承担长期记忆）
  * digest 落地 = deque 头部的 compact 标记条目（旧摘要被 merge
    覆盖）+ SQLite 持久化（重启可恢复）+ 指定目录的 txt 导出（人读）

挂载：main.py 在 message_router.start() 之后经
message_router.task_manager.register('daily_digest', run_loop()) 启动；
message_router / config_service 行数已到顶，本功能不进入这两个文件。
"""

import asyncio
import os
import sqlite3
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Deque, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from src.config import Settings
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)

#: 摘要内容外包标记：渲染/持久化/下一轮 merge 识别的唯一信封。
SUMMARY_OPEN_TAG = "<daily-digest>"
SUMMARY_CLOSE_TAG = "</daily-digest>"

#: DSH CHECKPOINT_PREAMBLE 的移植版：让模型把摘要当既定背景而不是
#: 要复述的内容（少这句模型会变成"背摘要机器"）。
CHECKPOINT_PREAMBLE = (
    "This is an automatically generated checkpoint condensing an earlier span"
    " of the group conversation to free up context. Treat the captured context"
    " as established background and build on it without restating it.")

#: 摘要指令（移植 DSH COMPACTION_INSTRUCTION：结构照搬，小节按群聊重写）。
#: 末尾的 PRIOR checkpoint 规则是嵌套合并语义的落点。
DIGEST_INSTRUCTION = "\n".join([
    "You are now acting as a digest engine for an AI chatbot in a QQ group.",
    "Condense the group conversation ABOVE into a structured checkpoint that lets",
    "the bot continue chatting naturally with no loss of essential context.",
    "",
    "Output EXACTLY the Markdown structure below: keep every section, in order.",
    "Use terse bullets, not prose paragraphs. Write \"(none)\" for an empty",
    "section — never drop a section.",
    "",
    "## 群成员与称呼",
    "- [还在活跃的核心成员、他们的称呼与说话风格；不活跃的可略过]",
    "",
    "## 今天发生了什么",
    "- [实质事件、决定、约定；流水账不必记]",
    "",
    "## 与花璃相关的互动",
    "- [谁和花璃聊了什么、玩什么梗、起过什么外号]",
    "",
    "## 未了的事",
    "- [还没结束的话题、谁等谁回复、约好的事]",
    "",
    "## 氛围与情绪",
    "- [群里今天的气氛：开心、争吵、感性、平淡]",
    "",
    "## 花璃自己",
    "- [人设相关的关键表现：被撩、傲娇、接梗成功或翻车]",
    "",
    "## 关键约束与偏好",
    "- [群规、管理员要求、成员明确表达过的喜好或雷区]",
    "",
    "Rules:",
    "- Write concise bullets in the same language as the conversation.",
    "- Preserve exact QQ IDs, nicknames, times, numbers, and promises verbatim",
    "  when they matter (错误的称呼或数字比没有记忆更糟).",
    "- Capture grievances and corrections faithfully — including things the",
    "  members asked the bot to stop doing.",
    "- Do NOT mention this digest request or that the context was compacted.",
    "- Output only the digest text: do not call any tool or take any other action.",
])


def _seconds_to_next(hour: int, minute: int, tz_name: str,
                     now: Optional[float] = None) -> float:
    """到本地时区下一个 hour:minute 的秒数（正数；中国无 DST）。"""
    tz = ZoneInfo(tz_name or "Asia/Shanghai")
    ts = datetime.fromtimestamp(now if now is not None else time.time(), tz=tz)
    nxt = ts.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if nxt <= ts:
        nxt = nxt + timedelta(days=1)
    return max(1.0, (nxt - ts).total_seconds())


def _digest_day_key(ts: float, tz_name: str) -> str:
    """摘要的日期键（本地时区 YYYY-MM-DD），用于 txt 文件名与去重。"""
    tz = ZoneInfo(tz_name or "Asia/Shanghai")
    return datetime.fromtimestamp(ts, tz=tz).strftime("%Y-%m-%d")


def frame_summary(text: str) -> str:
    """把摘要正文包进 checkpoint 信封（deque 标记条目 / txt 导出共用）。"""
    return CHECKPOINT_PREAMBLE + "\n\n" + SUMMARY_OPEN_TAG + "\n" \
        + (text or "").strip() + "\n" + SUMMARY_CLOSE_TAG


def is_shrunk(summary_text: str, source_chars: int) -> bool:
    """收敛检查（DSH 同款护栏）：摘要不得比被压缩的原文还长。"""
    return len((summary_text or "").strip()) < max(1, int(source_chars))


class DigestStore:
    """摘要持久化：每群一行（last_date / checkpoint / updated_at），SQLite。"""

    def __init__(self, db_path: Optional[str]):
        self._path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def _ensure(self) -> Optional[sqlite3.Connection]:
        if self._path is None:
            return None
        if self._conn is None:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            self._conn = sqlite3.connect(self._path, check_same_thread=False)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS digest ("
                " group_id INTEGER PRIMARY KEY, last_date TEXT NOT NULL,"
                " checkpoint TEXT NOT NULL, updated_at REAL NOT NULL)")
            self._conn.commit()
        return self._conn

    def load(self, group_id: int) -> Optional[Tuple[str, str]]:
        conn = self._ensure()
        if conn is None:
            return None
        row = conn.execute(
            "SELECT last_date, checkpoint FROM digest WHERE group_id = ?",
            (group_id,)).fetchone()
        return (row[0], row[1]) if row else None

    def load_all(self) -> Dict[int, Tuple[str, str]]:
        """全部群的 (last_date, checkpoint)，启动恢复用。"""
        conn = self._ensure()
        if conn is None:
            return {}
        return {row[0]: (row[1], row[2]) for row in conn.execute(
            "SELECT group_id, last_date, checkpoint FROM digest")}

    def save(self, group_id: int, last_date: str, checkpoint: str) -> None:
        conn = self._ensure()
        if conn is None:
            return
        conn.execute(
            "INSERT OR REPLACE INTO digest (group_id, last_date, checkpoint, updated_at)"
            " VALUES (?, ?, ?, ?)", (group_id, last_date, checkpoint, time.time()))
        conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


class DailyDigestService:
    """每日凌晨滚动摘要：缓冲 → 一次 AI/群 → merge → 落地三处（deque/SQLite/txt）。"""

    def __init__(self, config: Settings, ai_client, store: DigestStore,
                 context_manager=None, tz_name: str = ""):
        self.config = config
        self.ai = ai_client
        self.store = store
        self.context = context_manager  # 落地 deque 头部 compact 标记条目
        self.tz = tz_name or "Asia/Shanghai"
        self.at_hour = int(getattr(config, "DIGEST_AT_HOUR", 0) or 0)
        self.at_minute = int(getattr(config, "DIGEST_AT_MINUTE", 0) or 0)
        self.min_messages = int(getattr(config, "DIGEST_MIN_MESSAGES", 10) or 10)
        self.max_chars = int(getattr(config, "DIGEST_MAX_CHARS", 12000) or 12000)
        self.max_groups = int(getattr(config, "DIGEST_MAX_GROUPS_PER_RUN", 20) or 20)
        self.export_dir: Optional[str] = getattr(config, "DIGEST_EXPORT_DIR", "") or None
        self._buffers: Dict[int, Deque[Tuple[float, int, str]]] = {}
        self._running = False

    # ---------- 数据源（由 ContextManager.add_context 调用，全量文本） ----------
    def record_message(self, group_id: int, user_id: int, text: str,
                       ts: Optional[float] = None) -> None:
        """记录一条群消息进缓冲（与工作 deque 独立；有界防膨胀）。"""
        text = (text or "").strip()
        if not text:
            return
        buf = self._buffers.get(group_id)
        if buf is None:
            cap = int(getattr(self.config, "DIGEST_BUFFER_PER_GROUP", 1000) or 1000)
            buf = deque(maxlen=max(10, cap))
            self._buffers[group_id] = buf
        buf.append((ts if ts is not None else time.time(), int(user_id or 0), text))

    def buffered_groups(self) -> List[int]:
        return [g for g, b in self._buffers.items() if len(b) >= self.min_messages]

    def buffered_count(self, group_id: int) -> int:
        b = self._buffers.get(group_id)
        return len(b) if b else 0

    def _render_day(self, buf) -> Tuple[str, int]:
        """把缓冲渲染成对话文本（总字符上限内），返回 (文本, 字符数)。"""
        lines, total = [], 0
        for _ts, uid, text in list(buf):
            t = text.replace("\n", " ")[:200]
            if not t:
                continue
            who = "花璃" if uid == 0 else "用户" + str(uid)
            line = "[" + who + "] " + t
            if total + len(line) > self.max_chars:
                break
            lines.append(line)
            total += len(line)
        return "\n".join(lines), total

    async def _summarize(self, group_id: int, day_text: str,
                   prior: Optional[str]) -> Optional[str]:
        """一次 AI 调用生成摘要（prior 存在则作为既往 checkpoint 一并 merge）。"""
        parts = []
        if prior:
            parts.append("既往摘要（合并到新摘要里，不要照抄）：\n" + prior)
        parts.append("今天的群聊：\n" + day_text)
        parts.append(DIGEST_INSTRUCTION)
        user_message = "\n\n".join(parts)
        try:
            reply, _ = await self.ai.chat_once(
                user_message, context="（摘要任务，无历史上下文）", custom_prompt="digest")
        except Exception as exc:  # noqa: BLE001 - 调用失败按"放弃本轮"处理
            logger.warning("digest_ai_failed group=%s: %s", group_id, exc,
                           extra={"event": "digest_ai_failed", "group": group_id})
            return None
        return (reply or "").strip() or None

    def _export_txt(self, group_id: int, day_key: str,
                    digest_text: str) -> Optional[str]:
        """摘要导出到配置目录的 txt（人读副本；失败只告警不影响主流程）。"""
        if not self.export_dir:
            return None
        try:
            os.makedirs(self.export_dir, exist_ok=True)
            path = os.path.join(self.export_dir, str(group_id) + "_" + day_key + ".txt")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(frame_summary(digest_text) + "\n")
            return path
        except OSError as exc:
            logger.warning("digest_export_failed group=%s: %s", group_id, exc,
                           extra={"event": "digest_export_failed", "group": group_id})
            return None

    def _land_checkpoint(self, group_id: int, digest_text: str) -> None:
        """落地：deque 头部 compact 标记条目（旧摘要先移除保持唯一）+ SQLite。"""
        checkpoint = frame_summary(digest_text)
        if self.context is not None:
            try:
                self.context.set_digest_checkpoint(group_id, checkpoint)
            except Exception as exc:  # noqa: BLE001 - 落地失败不丢摘要本身
                logger.warning("digest_land_failed group=%s: %s", group_id, exc,
                               extra={"event": "digest_land_failed", "group": group_id})
        self.store.save(group_id, _digest_day_key(time.time(), self.tz), checkpoint)

    # ---------- 单轮（可测试入口） ----------
    async def run_once(self, now: Optional[float] = None) -> dict:
        """处理所有够量的群（按每轮上限），返回统计。失败的群保留缓冲下轮再试。"""
        if self._running:
            return {"status": "skipped", "reason": "already_running"}
        self._running = True
        result = {"status": "done", "groups_processed": 0, "groups_skipped": 0,
                  "groups_failed": 0, "exported": 0}
        try:
            now = now if now is not None else time.time()
            targets = [g for g, b in self._buffers.items()
                       if len(b) >= self.min_messages]
            for gid in targets[: self.max_groups]:
                outcome = await self._digest_group(gid, now)
                if outcome is True:
                    result["groups_processed"] += 1
                    if self.export_dir:
                        result["exported"] += 1
                elif outcome is None:
                    result["groups_skipped"] += 1
                else:
                    result["groups_failed"] += 1
        finally:
            self._running = False
        return result

    async def _digest_group(self, group_id: int, now: float) -> Optional[bool]:
        """单群摘要：True=完成 / None=跳过 / False=失败（缓冲保留）。"""
        buf = self._buffers.get(group_id)
        if buf is None or len(buf) < self.min_messages:
            return None
        # 快照选择区间（对应 DSH 语义）：取走期间群照常收新消息，
        # 新消息不进本轮摘要、留在缓冲下一轮——绝不锁群
        day_text, chars = self._render_day(buf)
        if chars < self.min_messages * 2:
            return None
        prior_row = self.store.load(group_id)
        prior = prior_row[1] if prior_row else None
        digest = await self._summarize(group_id, day_text, prior)
        if digest is None:
            return False
        if not is_shrunk(digest, chars):
            logger.warning("digest_not_smaller group=%s (%d >= %d), skipped",
                           group_id, len(digest), chars,
                           extra={"event": "digest_not_smaller", "group": group_id})
            return False
        # 成功才清缓冲（失败保留下轮重试，与 MemeSummary 同款降级）
        self._buffers.pop(group_id, None)
        self._land_checkpoint(group_id, digest)
        exported = self._export_txt(group_id, _digest_day_key(now, self.tz), digest)
        logger.info("digest_done group=%s chars=%d->%d export=%s",
                    group_id, chars, len(digest), exported or "(off)",
                    extra={"event": "digest_done", "group": group_id})
        return True

    def catch_up_pending(self, now: Optional[float] = None) -> List[int]:
        """启动时的补跑判定：上次摘要日期不是今天且缓冲够量的群（冷启动不拖慢）。"""
        now = now if now is not None else time.time()
        today = _digest_day_key(now, self.tz)
        pending = []
        for gid, b in list(self._buffers.items()):
            row = self.store.load(gid)
            if len(b) >= self.min_messages and (row is None or row[0] != today):
                pending.append(gid)
        return pending

    # ---------- 定点循环 ----------
    async def run_loop(self) -> None:
        """每天定点（本地时区 DIGEST_AT_HOUR:MINUTE，默认 00:00）执行一轮。"""
        while True:
            try:
                delay = _seconds_to_next(self.at_hour, self.at_minute, self.tz)
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                break
            try:
                stats = await self.run_once()
                logger.info("digest_run %s", stats, extra={"event": "digest_run"})
            except Exception as exc:  # noqa: BLE001 - 单轮失败不杀循环
                logger.error("digest_loop_error: %s", exc,
                             extra={"event": "digest_error"})
