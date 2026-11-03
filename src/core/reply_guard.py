import random


def mention_gate_allows(config) -> bool:
    """@ 门：默认关（真实 @ 必回）；开启后按 REPLY_PROBABILITY 概率放行。

    官方桥接部署下桥接器对每条消息都注入 @，必须开此门 + 低概率才能限频。
    """
    if not getattr(config, "MENTION_REPLY_GATE_ENABLED", False):
        return True
    prob = float(getattr(config, "REPLY_PROBABILITY", 1.0) or 1.0)
    return prob >= 1.0 or random.random() < prob


"""回复前守卫（v2.18.0）：从 message_router 拆出的判定小工具。

只做纯判断，不碰发送与状态，便于单测与复用。
"""

# 图片占位标记（解析层写入的「主模型直看」与「外部识图」两种形态）
IMAGE_MARKS = ("[native_vision_image]", "[用户发送了一张图片")


def is_image_only_message(full_text: str, clean_text: str) -> bool:
    """纯图片消息（有图无文本）——默认不触发回复，防刷屏。"""
    if str(clean_text or "").strip():
        return False
    body = str(full_text or "")
    return any(mark in body for mark in IMAGE_MARKS)


def is_summoned(is_mentioned: bool, is_reply_to_bot: bool) -> bool:
    """@ 或直接回复 bot = 明确召唤，绕过节流（连回上限只约束自发接话）。"""
    return bool(is_mentioned or is_reply_to_bot)
