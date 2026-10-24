"""群友画像（MemberProfileService）：性格 / 喜好 / 个人生活 / 特点的长期记忆。

与既有记忆系统的关系（三层记忆，各司其职）：
- MemoryManager 是「按用户的事实便签」：模型对话中即兴抽取，键值/便签式，短文本
- BlossomMemory 是「按群的语义检索库」：向量召回，按消息原文建索引
- 画像是「按群的结构化人物档案」：每天由 digest 同管线从当天对话里提炼，
  merge 语义更新（保留仍成立的、淘汰过时的），注入本群活跃成员的画像块

存储：SQLite 一张表 profiles(group_id, user_id, nickname, sections, updated_at)，
sections 为 JSON 字符串：{personality: {"text": ..., "ts": ...}, ...}，
每个字段带独立时间戳——merge 时按字段级 TTL 淘汰过时信息（PROFILE_SECTION_TTL_DAYS）。

安全（与 MemoryManager 同一套代码层闸门，P1 边界）：
- 提取来源是模型输出（不可信数据）：落库前每个字段过 _sanitize_section 清洗
  （QQ 号 / 注入句式 / 指令关键词 / 换行 / 超长一律拒收）
- 注入对话时再过一道 sanitize_untrusted_text（兜底手工改库的脏数据）

默认关（PROFILE_ENABLED），开启后 digest 每轮多用一次当天文本跑画像提取。
"""
import json
import os
import re
import sqlite3
import time
from typing import Dict, List, Optional, Tuple

from src.core.sanitizer import sanitize_untrusted_text
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)

#: 画像字段（顺序即展示/注入顺序；中英文标签）
SECTION_ORDER: Tuple[str, ...] = ("personality", "interests", "life", "traits")
SECTION_LABELS: Dict[str, str] = {
    "personality": "性格",
    "interests": "喜好",
    "life": "个人生活",
    "traits": "特点",
}

#: 注入到 system prompt 的画像块上限（字符）
_PROFILE_BLOCK_MAX = 1200
#: 单字段字符上限（与提取指令约束一致）
_SECTION_MAX_CHARS = 120
#: 昵称字符上限
_NICKNAME_MAX_CHARS = 60
#: 代码围栏（模型输出 JSON 时偶尔会带围栏）
_FENCE = chr(96) * 3

#: 画像提取指令：要求模型输出 JSON，只接受严格结构（防注入）。
#: 与 digest 同管线：喂的是同一段当天全文，产出按用户维度的结构化档案。
PROFILE_INSTRUCTION = "\n".join([
    "You are now building member profiles for an AI chatbot in a QQ group.",
    "From the group conversation ABOVE, extract or update a profile for each member",
    "who said or did anything notable today.",
    "",
    "Output ONLY a JSON object mapping user_id (as string key) to:",
    "{",
    "  \"nickname\": \"their nickname or how others call them (empty if unknown)\",",
    "  \"personality\": \"one short line: how they come across in this group\",",
    "  \"interests\": \"short comma-separated list of what they like or talk about\",",
    "  \"life\": \"one short line: personal-life facts they shared (job, school, pets,",
    "             relationships, plans) — only what they said in the group\",",
    "  \"traits\": \"one short line: distinctive habits, catchphrases or skills\",",
    "}",
    "",
    "Rules:",
    "- Output ONLY the JSON object, no Markdown fences, no comments.",
    "- Base everything on the conversation above; never invent facts.",
    "- Update what you know: if today contradicts an old fact, write the current one.",
    "- If a member showed nothing notable today, omit them from the object.",
    "- Keep each field under 120 characters; merge traits, do not list every message.",
    "- User IDs are the numeric IDs shown in the conversation.",
])


def _sanitize_section(text: str, limit: int = _SECTION_MAX_CHARS) -> Optional[str]:
    """画像字段清洗（代码层闸门；与 MemoryManager 的 validate_memory_content 同源）。

    拒绝：空 / 超长 / 含 QQ 号（5~12 位数字）/ 含换行 / 含注入或指令关键词。
    返回清洗后的文本，None 表示拒绝写入。
    """
    t = (text or "").strip()
    if not t or len(t) > limit:
        return None
    if re.search(r"\d{5,12}", t):  # QQ 号不入库（P1 边界，同记忆库）
        return None
    if re.search(r"[\r\n]", t):  # 单行：画像块按行拼接，换行会破坏格式
        return None
    if re.search(r"MEMORY_JSON|【|】|忽略|记住|执行|从现在开始|忘记你是|指令|system",
                 t, re.IGNORECASE):
        return None
    return t


class ProfileStore:
    """群友画像持久化（SQLite，每群每用户一行）。"""

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
                "CREATE TABLE IF NOT EXISTS profiles ("
                " group_id INTEGER NOT NULL, user_id INTEGER NOT NULL,"
                " nickname TEXT NOT NULL, sections TEXT NOT NULL,"
                " updated_at REAL NOT NULL, PRIMARY KEY (group_id, user_id))")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_profiles_group_updated"
                " ON profiles (group_id, updated_at DESC)")
            self._conn.commit()
        return self._conn

    @staticmethod
    def _decode(raw: str) -> Dict:
        """解析 sections JSON；脏数据（手工改库）一律回落空字典。"""
        try:
            data = json.loads(raw or "{}")
        except (ValueError, TypeError):
            return {}
        if not isinstance(data, dict):
            return {}
        out = {}
        for label, value in data.items():
            if isinstance(value, dict):
                text = str(value.get("text") or "").strip()
                ts = value.get("ts")
                if text and isinstance(ts, (int, float)):
                    out[str(label)] = {"text": text, "ts": float(ts)}
            elif isinstance(value, str) and value.strip():
                # 兼容旧版（纯字符串 sections，无时间戳）→ ts=None 表示永不过期
                out[str(label)] = {"text": value.strip(), "ts": None}
        return out

    def load(self, group_id: int, user_id: int) -> Optional[Dict]:
        conn = self._ensure()
        if conn is None:
            return None
        row = conn.execute(
            "SELECT nickname, sections FROM profiles WHERE group_id = ? AND user_id = ?",
            (group_id, user_id)).fetchone()
        if row is None:
            return None
        return {"nickname": row[0], "sections": self._decode(row[1])}

    def upsert(self, group_id: int, user_id: int, nickname: str, sections: Dict) -> None:
        conn = self._ensure()
        if conn is None:
            return
        conn.execute(
            "INSERT OR REPLACE INTO profiles (group_id, user_id, nickname, sections, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (group_id, user_id, nickname, json.dumps(sections, ensure_ascii=False), time.time()))
        conn.commit()

    def group_profiles(self, group_id: int, limit: int = 8) -> List[Tuple[int, Dict]]:
        """群里最近更新的画像（注入用；limit 控制块大小）。"""
        conn = self._ensure()
        if conn is None:
            return []
        rows = conn.execute(
            "SELECT user_id, nickname, sections FROM profiles WHERE group_id = ?"
            " ORDER BY updated_at DESC LIMIT ?", (group_id, limit)).fetchall()
        out = []
        for uid, nick, secs in rows:
            out.append((uid, {"nickname": nick, "sections": self._decode(secs)}))
        return out

    def list_groups(self) -> List[int]:
        """有画像的群号（Web UI 群选择器用）。"""
        conn = self._ensure()
        if conn is None:
            return []
        return [row[0] for row in conn.execute(
            "SELECT DISTINCT group_id FROM profiles ORDER BY group_id")]

    def count_group(self, group_id: int) -> int:
        conn = self._ensure()
        if conn is None:
            return 0
        row = conn.execute(
            "SELECT COUNT(*) FROM profiles WHERE group_id = ?", (group_id,)).fetchone()
        return int(row[0]) if row else 0

    def delete_profile(self, group_id: int, user_id: int) -> bool:
        conn = self._ensure()
        if conn is None:
            return False
        cur = conn.execute(
            "DELETE FROM profiles WHERE group_id = ? AND user_id = ?", (group_id, user_id))
        conn.commit()
        return cur.rowcount > 0

    def clear_group(self, group_id: int) -> int:
        conn = self._ensure()
        if conn is None:
            return 0
        cur = conn.execute("DELETE FROM profiles WHERE group_id = ?", (group_id,))
        conn.commit()
        return int(cur.rowcount)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def merge_sections(old: Optional[Dict], new: Dict,
                   ttl_days: int = 0, now: Optional[float] = None) -> Dict:
    """画像 merge：新字段覆盖旧字段，空值不动；超过 ttl_days 没更新的字段淘汰。

    - old/new 的 sections 结构：{label: {"text": ..., "ts": ...}}（ts=None 永不过期）
    - new 里的字段一律按「当前时间」刷新（今天又被提及 = 仍然成立）
    - ttl_days<=0 时关闭淘汰（与旧版行为一致）；否则老字段到期直接丢弃——
      「他上个月说喜欢玩 X，但一个月没再提也没更新」就不再当作画像
    """
    merged: Dict[str, Dict] = {}
    cur = now if now is not None else time.time()
    for label, value in (old or {}).items():
        if not isinstance(value, dict):
            continue
        text = str(value.get("text") or "").strip()
        if not text:
            continue
        ts = value.get("ts")
        if ttl_days > 0 and isinstance(ts, (int, float)) and (cur - float(ts)) > ttl_days * 86400:
            continue  # 过时淘汰
        merged[label] = {"text": text, "ts": ts}
    for label, value in (new or {}).items():
        text = str(value or "").strip()
        if not text:
            continue
        merged[label] = {"text": text[:_SECTION_MAX_CHARS], "ts": cur}
    return merged


def build_profile_block(rows: List[Tuple[int, Dict]]) -> str:
    """把画像列表渲染成注入用的文本块（空列表返回空串）。

    渲染为「用户123（小花）— 性格: ...; 喜好: ...」的单行格式，
    与群聊记录同处不可信数据区。
    """
    if not rows:
        return ""
    lines = []
    for uid, profile in rows:
        secs = profile.get("sections") or {}
        nick = str(profile.get("nickname") or "").strip()
        head = "用户" + str(uid) + ("（" + nick + "）" if nick else "")
        parts = []
        for label in SECTION_ORDER:
            value = secs.get(label)
            if isinstance(value, dict):
                v = str(value.get("text") or "").strip()
            else:
                v = str(value or "").strip()
            if v:
                parts.append(SECTION_LABELS.get(label, label) + ": " + v)
        if parts:
            lines.append(head + " — " + "; ".join(parts))
    text = "\n".join(lines)
    return text[:_PROFILE_BLOCK_MAX] if text else ""


class MemberProfileService:
    """群友画像服务：提取（digest 复用当天文本）+ 存储 + 注入 + 管理。"""

    def __init__(self, config, ai_client, store: ProfileStore):
        self.config = config
        self.ai = ai_client
        self.store = store
        self.max_members = int(getattr(config, "PROFILE_MAX_MEMBERS", 8) or 8)
        self.ttl_days = int(getattr(config, "PROFILE_SECTION_TTL_DAYS", 0) or 0)

    # ---------- 提取（digest 同管线，复用当天文本） ----------
    async def extract_from_day(self, group_id: int, day_text: str) -> int:
        """从当天对话文本提取画像并 merge 入库；返回更新的人数。

        失败一律返回 0（画像绝不影响摘要主流程）：AI 调用失败 / JSON 解析失败 /
        全部字段被清洗闸门拒收都走这条路。
        """
        if not day_text or not day_text.strip():
            return 0
        prompt = day_text + "\n\n" + PROFILE_INSTRUCTION
        try:
            reply, _ = await self.ai.chat_once(
                prompt, context="（画像任务，无历史上下文）", custom_prompt="profile",
                max_tokens=int(getattr(self.config, "PROFILE_MAX_TOKENS", 2048) or 2048))
        except Exception as exc:  # noqa: BLE001 - 画像失败不影响摘要主流程
            logger.warning("profile_ai_failed group=%s: %s", group_id, exc,
                           extra={"event": "profile_ai_failed", "group": group_id})
            return 0
        data = self._parse_profile_json(reply)
        if not isinstance(data, dict):
            return 0
        updated = 0
        for uid_key, fields in data.items():
            try:
                uid = int(str(uid_key).strip())
            except (TypeError, ValueError):
                continue
            if not isinstance(fields, dict) or uid <= 0:
                continue
            nickname = _sanitize_section(fields.get("nickname"), limit=_NICKNAME_MAX_CHARS)
            sections = {}
            for label in SECTION_ORDER:
                if label not in fields:
                    continue
                clean = _sanitize_section(fields.get(label))
                if clean:
                    sections[label] = clean
            old = self.store.load(group_id, uid) or {"nickname": "", "sections": {}}
            merged = merge_sections(old.get("sections"), sections, ttl_days=self.ttl_days)
            if not merged:
                continue
            nickname = nickname or old.get("nickname") or ""
            self.store.upsert(group_id, uid, nickname, merged)
            updated += 1
            logger.info("profile_member_updated group=%s user=%s fields=%s",
                        group_id, uid, sorted(sections.keys()),
                        extra={"event": "profile_member_updated", "group": group_id,
                               "user": uid})
        if updated:
            logger.info("profile_updated group=%s members=%d", group_id, updated,
                        extra={"event": "profile_updated", "group": group_id,
                               "members": updated})
        return updated

    @staticmethod
    def _parse_profile_json(reply: Optional[str]) -> Optional[Dict]:
        """解析模型输出的画像 JSON；容错代码围栏/尾随文本，非法一律 None。"""
        raw = (reply or "").strip()
        if not raw:
            return None
        if raw.startswith(_FENCE):
            raw = raw.strip(chr(96))
            if raw[:4].lower() == "json":
                raw = raw[4:]
            raw = raw.strip()
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            # 尾随解释文本：截到最后一个右花括号再试一次（模型偶尔会多说一句话）
            tail = raw.rfind("}")
            if tail > 0:
                try:
                    data = json.loads(raw[: tail + 1])
                except (ValueError, TypeError):
                    return None
            else:
                return None
        return data if isinstance(data, dict) else None

    # ---------- 注入 ----------
    def build_context_block(self, group_id: int) -> str:
        """注入用：本群最近活跃成员画像块（空=不注入）。"""
        rows = self.store.group_profiles(group_id, limit=self.max_members)
        return build_profile_block(rows)

    # ---------- 管理（Web UI / 命令） ----------
    def enabled(self) -> bool:
        return bool(getattr(self.config, "PROFILE_ENABLED", False))

    def list_group_profiles(self, group_id: int) -> List[Dict]:
        """群里全部画像（Web UI 展示用；带字段级时间戳）。"""
        rows = self.store.group_profiles(group_id, limit=500)
        out = []
        for uid, profile in rows:
            secs = profile.get("sections") or {}
            sections = []
            for label in SECTION_ORDER:
                value = secs.get(label)
                text = str((value or {}).get("text") or "") if isinstance(value, dict) else ""
                ts = (value or {}).get("ts") if isinstance(value, dict) else None
                if text:
                    sections.append({
                        "label": label, "name": SECTION_LABELS.get(label, label),
                        "text": text, "ts": ts,
                    })
            if not sections:
                continue
            out.append({
                "user_id": uid,
                "nickname": str(profile.get("nickname") or ""),
                "sections": sections,
            })
        return out

    def profile_of(self, group_id: int, user_id: int) -> Optional[Dict]:
        """单人画像（/profile 命令）。"""
        return self.store.load(group_id, user_id)

    def set_section(self, group_id: int, user_id: int, label: str, text: str,
                    nickname: str = "") -> Tuple[bool, str]:
        """手工写画像字段（Web UI）；label 必须在 SECTION_ORDER 内。"""
        if label not in SECTION_ORDER:
            return False, "未知画像字段：" + label
        clean = _sanitize_section(text)
        if clean is None:
            return False, "画像内容被拒绝（可能含 QQ 号 / 指令关键词 / 过长）"
        old = self.store.load(group_id, user_id) or {"nickname": "", "sections": {}}
        merged = merge_sections(old.get("sections"), {label: clean}, ttl_days=self.ttl_days)
        nick = _sanitize_section(nickname, limit=_NICKNAME_MAX_CHARS) or old.get("nickname") or ""
        self.store.upsert(group_id, user_id, nick, merged)
        return True, "已更新"

    def delete_profile(self, group_id: int, user_id: int) -> bool:
        return self.store.delete_profile(group_id, user_id)

    def clear_group(self, group_id: int) -> int:
        return self.store.clear_group(group_id)

    def describe(self, group_id: int, user_id: int) -> str:
        """/profile 命令的人类可读输出（空画像返回空串）。"""
        profile = self.profile_of(group_id, user_id)
        if not profile:
            return ""
        secs = profile.get("sections") or {}
        parts = []
        for label in SECTION_ORDER:
            value = secs.get(label)
            text = str((value or {}).get("text") or "") if isinstance(value, dict) else ""
            if text:
                parts.append(SECTION_LABELS.get(label, label) + "：" + text)
        if not parts:
            return ""
        nick = str(profile.get("nickname") or "").strip()
        head = ("「" + nick + "」" if nick else "用户" + str(user_id)) + "的画像："
        return head + "；".join(parts)

    def close(self) -> None:
        self.store.close()


def sanitize_profile_block(text: str) -> str:
    """注入前二次清洗（兜底手工改库的脏数据；与 prompt_builder 同闸门）。"""
    return sanitize_untrusted_text(text or "")[0]
