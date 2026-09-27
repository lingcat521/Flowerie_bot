import random
import time
from typing import Dict

from src.config import Settings
from src.core.context_backup import ContextBackupStore
from src.core.sanitizer import sanitize_untrusted_text
from src.models import GlobalState, GroupState
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)


class ContextManager:
    """群的上下文管理：GroupState 生命周期、上下文读写、崩溃备份、接话概率、重复回复过滤。"""

    def __init__(self, config: Settings, groups: Dict[int, GroupState], global_state: GlobalState):
        self.config = config
        self.groups = groups
        self.global_state = global_state
        self._backup = ContextBackupStore(config)

    def get_group_state(self, group_id: int) -> GroupState:
        if group_id not in self.groups:
            self.groups[group_id] = GroupState(context_size=getattr(self.config, "CONTEXT_SIZE", 300))
        return self.groups[group_id]

    # ---------- 上下文 ----------
    def add_context(self, group_id: int, user_id: int, message: str, is_bot: bool = False) -> None:
        state = self.get_group_state(group_id)
        state.context.append({
            "user_id": user_id,
            "message": message,
            "is_bot": is_bot,
            "time": time.time()
        })

    def get_context_text(self, group_id: int, max_messages: int = 150) -> str:
        state = self.get_group_state(group_id)
        msgs = list(state.context)[-max_messages:]
        lines = []
        for idx, m in enumerate(msgs, 1):
            who = "机器人(花璃)" if m.get("is_bot", False) else f"用户{m.get('user_id', 0)}"
            # 代码层防注入：历史消息按不可信数据处理，清洗后再进上下文
            msg_text, _ = sanitize_untrusted_text(str(m.get("message", "")))
            lines.append(f"[{idx}] {who}: {msg_text}")
        return "\n".join(lines)

    # ---------- 回复概率（主动发言概率全部配置化，默认值=原硬编码，行为零变化） ----------
    @staticmethod
    def _prob(value, default: float) -> float:
        """防御性取值：非法配置（NaN/Inf/越界）兜底为默认值，不抛异常（运行期不炸）。"""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return default
        if v != v or v in (float("inf"), float("-inf")):  # NaN / Inf
            return default
        if not (0.0 <= v <= 1.0):
            return default
        return v

    def should_reply_by_context(self, group_id: int) -> bool:
        state = self.get_group_state(group_id)
        cfg = self.config
        recent_msgs = list(state.context)[-5:]
        if not recent_msgs:
            prob = self._prob(
                getattr(cfg, "PROACTIVE_MESSAGE_EMPTY_CONTEXT_PROBABILITY", 0.02), 0.02)
            return random.random() < prob
        user_msgs = [m for m in recent_msgs if not m["is_bot"]]
        if not user_msgs:
            return False
        prob = self._prob(getattr(cfg, "PROACTIVE_MESSAGE_BASE_PROBABILITY", 0.03), 0.03)
        if len(user_msgs) >= 2:
            prob += self._prob(getattr(cfg, "PROACTIVE_MESSAGE_USER_BOOST", 0.01), 0.01)
        if len(set(m["user_id"] for m in user_msgs)) == 1:
            prob = self._prob(
                getattr(cfg, "PROACTIVE_MESSAGE_SINGLE_USER_PROBABILITY", 0.02), 0.02)
        last_msg = recent_msgs[-1]
        if last_msg and not last_msg.get("is_bot", False) and len(str(last_msg.get("message", ""))) < 2:
            prob = self._prob(
                getattr(cfg, "PROACTIVE_MESSAGE_SHORT_MESSAGE_PROBABILITY", 0.02), 0.02)
        bot_count = sum(1 for m in recent_msgs[-3:] if m.get("is_bot", False))
        if bot_count >= 2:
            prob *= self._prob(getattr(cfg, "PROACTIVE_MESSAGE_BOT_MULTIPLIER", 0.3), 0.3)
        prob = max(
            self._prob(getattr(cfg, "PROACTIVE_MESSAGE_MIN_PROBABILITY", 0.01), 0.01),
            min(self._prob(getattr(cfg, "PROACTIVE_MESSAGE_MAX_PROBABILITY", 0.05), 0.05), prob),
        )
        roll = random.random()
        logger.debug(f"Context reply prob for group {group_id}: {prob:.2f}, roll={roll:.2f}")
        return roll < prob

    # ---------- 重复回复检测 ----------
    def is_duplicate_reply(self, group_id: int, reply: str) -> bool:
        state = self.get_group_state(group_id)
        recent = state.recent_bot_replies
        if not recent:
            return False
        if reply in recent:
            return True
        words = set(reply)
        for old in recent:
            old_words = set(old)
            if not old_words:
                continue
            overlap = len(words & old_words) / len(old_words)
            # 字符集覆盖 ≥90% **且** 长度比值 ≥0.5（防"你好"→"你好呀"这类短句误杀）
            if overlap >= 0.9 and min(len(reply), len(old)) / max(1, max(len(reply), len(old))) >= 0.5:
                return True
        return False

    def add_recent_reply(self, group_id: int, reply: str) -> None:
        state = self.get_group_state(group_id)
        state.recent_bot_replies.append(reply)

    # ---------- 上下文崩溃持久化（SQLite，存储层见 context_backup.py） ----------
    def load_context_backup(self) -> None:
        """启动时从 SQLite 读取上次保存的上下文备份（每群最多恢复最近 50 条 + 最近 200 条已处理消息 id）。"""
        restored = 0
        restored_ids = 0
        try:
            rows, id_rows = self._backup.load()
            for group_id, user_id, message, is_bot, ts in rows:
                state = self.get_group_state(group_id)
                state.context.append({
                    "user_id": user_id,
                    "message": message,
                    "is_bot": bool(is_bot),
                    "time": ts or 0.0,
                })
                restored += 1
            for group_id, message_id in id_rows:
                self.get_group_state(group_id).processed_msg_ids.append(message_id)
                restored_ids += 1
            if restored or restored_ids:
                logger.info(f"上下文备份已恢复: {restored} 条消息, {restored_ids} 条已处理消息 id")
        except Exception as e:
            logger.error(f"加载上下文备份失败: {e}")

    async def save_context_backup(self) -> None:
        """把每群最近 50 条上下文 + 最近 200 条已处理消息 id 写入 SQLite（单事务全量重写）。

        已处理消息 id 一起持久化：崩溃重启后 NapCat 重投旧消息时不会重复回复。
        """
        try:
            snapshot = {gid: (list(st.context)[-50:], list(st.processed_msg_ids)[-200:])
                        for gid, st in self.groups.items()}
            if self._backup.save(snapshot):
                logger.debug(f"上下文备份已保存: {len(self.groups)} 个群")
        except Exception as e:
            logger.error(f"保存上下文备份失败: {e}")

