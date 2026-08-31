"""插件侧消息模型：BotMessage（领域语义 + Builder，与中层对称）。

插件构造：msg = BotMessage().text("hi").at(123).image(url)
"""
from typing import Any, Iterator, List, Optional


class BotMessage:
    def __init__(self, text: str = "", *, at_list: Optional[List] = None,
                 images: Optional[List[str]] = None, reply_id: Optional[int] = None,
                 videos: Optional[List[str]] = None, voices: Optional[List[str]] = None,
                 files: Optional[List[str]] = None):
        self.text = str(text or "")
        self.at_list: List[str] = [str(a) for a in (at_list or [])]
        self.images: List[str] = [str(i) for i in (images or [])]
        self.videos: List[str] = [str(v) for v in (videos or [])]
        self.voices: List[str] = [str(v) for v in (voices or [])]
        self.files: List[str] = [str(f) for f in (files or [])]
        self.segments = []   # 进阶段（平台相关）
        self.reply_id = int(reply_id) if reply_id is not None else None

    def add_text(self, value: Any) -> "BotMessage":
        """Builder：追加文本（读取请用 .text 属性）。"""
        self.text = str(self.text or "") + str(value or "")
        return self

    def at(self, user_id: Any) -> "BotMessage":
        self.at_list.append(str(user_id))
        return self

    def image(self, url_or_file: str) -> "BotMessage":
        self.images.append(str(url_or_file))
        return self

    def video(self, url_or_file: str) -> "BotMessage":
        self.videos.append(str(url_or_file))
        return self

    def voice(self, url_or_file: str) -> "BotMessage":
        self.voices.append(str(url_or_file))
        return self

    def file(self, url_or_file: str, name: Optional[str] = None) -> "BotMessage":
        self.files.append(str(url_or_file))
        if name:
            self._file_names = dict(getattr(self, "_file_names", {}) or {})
            self._file_names[str(url_or_file)] = str(name)
        return self

    def add_segment(self, seg_type: str, data) -> "BotMessage":
        self.segments.append({"type": str(seg_type), "data": dict(data or {})})
        return self

    # ---------- 富内容 Builder（Flowerie 语义；底层转 markdown/keyboard/json 段） ----------
    def card(self, app_data: dict) -> "BotMessage":
        """卡片消息（QQ 原生 JSON 卡片；底部转 json 段，适配层透传）。"""
        self.segments.append({"type": "json", "data": {"data": app_data}})
        return self

    def markdown(self, text: str, style: str = "default") -> "BotMessage":
        """Markdown 富文本（底层转 markdown 段；网关不支持时主进程返回明确错误）。"""
        self.segments.append({"type": "markdown", "data": {"content": str(text), "style": str(style)}})
        return self

    def button(self, label: str, action: str = "", style: int = 1) -> "BotMessage":
        """交互按钮（底层合并为 keyboard 段；QQ 官方 Bot 能力，兼容性以网关为准）。"""
        # 找到最近的 keyboard 段，追加按钮；否则新建
        for seg in self.segments:
            if seg.get("type") == "keyboard":
                seg["data"].setdefault("buttons", []).append(
                    {"text": str(label)[:20], "k": str(action)[:64], "style": int(style)})
                return self
        self.segments.append({"type": "keyboard",
                              "data": {"buttons": [{"text": str(label)[:20],
                                                    "k": str(action)[:64],
                                                    "style": int(style)}]}})
        return self

    def reply(self, message_id: int) -> "BotMessage":
        self.reply_id = int(message_id)
        return self

    def has(self, kind: str) -> bool:
        alias = {"at": "at_list", "mention": "at_list", "image": "images",
                 "img": "images", "video": "videos", "voice": "voices",
                 "record": "voices", "file": "files", "reply": "_reply_flag",
                 "text": "text"}
        key = alias.get(kind)
        if key == "_reply_flag":
            return self.reply_id is not None
        if key == "text":
            return bool(self.text)
        if key and getattr(self, key, None) is not None:
            return bool(getattr(self, key))
        return False

    def __bool__(self) -> bool:
        return bool(self.text or self.at_list or self.images or self.videos or
                    self.voices or self.files or self.reply_id)

    def __iter__(self) -> Iterator[Any]:
        if self.text:
            yield ("text", self.text)
        for a in self.at_list:
            yield ("at", a)
        for img in self.images:
            yield ("image", img)
        for v in self.videos:
            yield ("video", v)
        for v in self.voices:
            yield ("voice", v)
        for f in self.files:
            yield ("file", f)

    def merge(self, other: "BotMessage") -> "BotMessage":
        """合并另一消息（链式组合）。"""
        self.text = str(self.text or "") + str(other.text or "")
        self.at_list.extend(other.at_list)
        self.images.extend(other.images)
        return self
