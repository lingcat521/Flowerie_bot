"""QQ空间服务（发说说 / 删说说 / 本地历史），底层走 OneBot 扩展动作。

NapCat 实测接口（见 docs/reference/napcat-admin-qzone.md）：
- send_qzone_msg   {content, images[], ugc_right, target_uins[]} -> {tid}
- delete_qzone_msg {tid} -> null
- ugc_right: 1 所有人可见 / 4 好友可见 / 16 部分好友可见 / 64 仅自己可见 / 128 部分好友不可见
  16、128 必须带 target_uins（权限作用对象）

图片支持 file:// 本地路径、http(s):// URL、base64:// 数据（由 NapCat 端下载/解码上传）；
也允许直接填**本地绝对路径**（如 /storage/emulated/0/a.jpg 或 ~/a.jpg）——这里会归一化成
file:// URI 再交给 NapCat，因为它的上传器只认 URI 形式（裸路径会被当成非法来源）。
本地历史（data/qzone_history.json）只存 tid/摘要/权限/时间，用于面板列出与删除；
文件采用"写临时文件 + os.replace"原子落盘（与 GroupNicknameStore 同款）。
"""
import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

from src.utils.file_source import to_uri_source
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)

# 权限枚举：值与 NapCat ValidUgcRights 一致（面板下拉也用这份）
UGC_RIGHTS: Dict[int, str] = {
    1: "所有人可见",
    4: "好友可见",
    16: "部分好友可见",
    64: "仅自己可见",
    128: "部分好友不可见",
}

_MAX_CONTENT = 2000      # 说说正文字数上限（面板侧保护，超出直接拒绝而非静默截断）
_MAX_IMAGES = 9          # 单条说说图片上限
_MAX_TARGETS = 100       # 权限对象 QQ 号上限


def _normalize_image(raw: str) -> str:
    """图片输入归一化成 NapCat 认的 URI；不合法返回空串（strict 语义见 utils.file_source）。"""
    return to_uri_source(raw, strict=True)


class QzoneService:
    """QQ空间门面：校验 + 调用 + 历史记录。所有方法返回 {ok, ...}。"""

    def __init__(self, adapter, config=None, history_path: Optional[str] = None):
        self._adapter = adapter
        self.config = config
        self._path = str(history_path or getattr(config, "QZONE_HISTORY_PATH", "./data/qzone_history.json"))
        self._max = max(1, int(getattr(config, "QZONE_MAX_HISTORY", 100) or 100))
        self._lock = threading.Lock()
        self._items: List[Dict[str, Any]] = []
        self._load()

    # ---------- 开关与默认值 ----------
    def enabled(self) -> bool:
        return bool(getattr(self.config, "QZONE_ENABLED", True))

    def default_ugc_right(self) -> int:
        try:
            value = int(getattr(self.config, "QZONE_DEFAULT_UGC_RIGHT", 1) or 1)
        except (TypeError, ValueError):
            value = 1
        return value if value in UGC_RIGHTS else 1

    def rights(self) -> List[Dict[str, Any]]:
        """权限清单（面板下拉/文档共用）。"""
        return [{"value": v, "label": label} for v, label in UGC_RIGHTS.items()]

    # ---------- 校验 ----------
    def validate(self, content: str, images: Optional[List[str]] = None,
                 ugc_right: int = 1, target_uins: Optional[List[int]] = None):
        """返回 (ok, error, 归一化后的 images / targets)。"""
        text = str(content or "")
        if not text.strip():
            return False, "说说正文不能为空", [], []
        if len(text) > _MAX_CONTENT:
            return False, f"说说正文超过 {_MAX_CONTENT} 字上限", [], []
        try:
            right = int(ugc_right)
        except (TypeError, ValueError):
            return False, "权限值必须是数字", [], []
        if right not in UGC_RIGHTS:
            return False, "权限值不合法，可选：1 / 4 / 16 / 64 / 128", [], []
        imgs = [str(x).strip() for x in (images or []) if str(x).strip()]
        if len(imgs) > _MAX_IMAGES:
            return False, f"图片数量超过 {_MAX_IMAGES} 张上限", [], []
        normalized: List[str] = []
        for img in imgs:
            item = _normalize_image(img)
            if not item:
                return (False,
                        "图片来源只支持 file:// / http(s):// / base64:// / 本地绝对路径"
                        "（相对路径不受支持，请填绝对路径或 file:// 链接）", [], [])
            normalized.append(item)
        imgs = normalized
        targets: List[int] = []
        for raw in (target_uins or []):
            try:
                value = int(str(raw).strip())
            except (TypeError, ValueError):
                return False, "target_uins 里存在非法 QQ 号", [], []
            if value > 0:
                targets.append(value)
        if len(targets) > _MAX_TARGETS:
            return False, f"权限对象超过 {_MAX_TARGETS} 个上限", [], []
        if right in (16, 128) and not targets:
            return False, "权限为 16/128 时必须提供 target_uins", [], []
        if right not in (16, 128):
            targets = []
        return True, "", imgs, targets

    # ---------- 发布 / 删除 ----------
    async def publish(self, content: str, images: Optional[List[str]] = None,
                      ugc_right: Optional[int] = None,
                      target_uins: Optional[List[int]] = None) -> Dict[str, Any]:
        """发表说说：校验 → NapCat send_qzone_msg → 记录历史。"""
        right = self.default_ugc_right() if ugc_right is None else ugc_right
        ok, err, imgs, targets = self.validate(content, images, right, target_uins)
        if not ok:
            return {"ok": False, "error": err}
        try:
            result = await self._adapter.qzone_publish(
                str(content).strip(), imgs, int(right), targets)
        except Exception as e:  # noqa: BLE001 —— 网络/平台异常不打崩调用方
            logger.warning("qzone_publish_failed err=%s: %s", type(e).__name__, e,
                           extra={"event": "qzone_publish_failed"})
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        if isinstance(result, dict) and result.get("ok") is False:
            return {"ok": False, "error": str(result.get("error") or "平台返回失败")}
        tid = ""
        if isinstance(result, dict):
            tid = str(result.get("tid") or (result.get("data") or {}).get("tid") or "")
        if not tid:
            return {"ok": False, "error": "平台未返回 tid（说说可能未发布成功）"}
        self._record(tid, str(content).strip(), int(right), len(imgs))
        logger.info("qzone_publish_done tid=%s images=%d right=%s", tid, len(imgs), right,
                    extra={"event": "qzone_publish_done"})
        return {"ok": True, "tid": tid}

    async def delete(self, tid: str) -> Dict[str, Any]:
        """删除说说（按 tid）。"""
        clean = str(tid or "").strip()
        if not clean:
            return {"ok": False, "error": "tid 不能为空"}
        try:
            result = await self._adapter.qzone_delete(clean)
        except Exception as e:  # noqa: BLE001
            logger.warning("qzone_delete_failed tid=%s err=%s: %s", clean, type(e).__name__, e,
                           extra={"event": "qzone_delete_failed"})
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        if isinstance(result, dict) and result.get("ok") is False:
            return {"ok": False, "error": str(result.get("error") or "平台返回失败")}
        self._drop(clean)
        logger.info("qzone_delete_done tid=%s", clean, extra={"event": "qzone_delete_done"})
        return {"ok": True, "tid": clean}

    # ---------- 本地历史 ----------
    def history(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._items]

    def _load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as f:  # noqa: PTH123
                raw = json.load(f)
        except (OSError, ValueError):
            raw = []
        items: List[Dict[str, Any]] = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and str(item.get("tid") or "").strip():
                    items.append({
                        "tid": str(item["tid"]).strip(),
                        "content": str(item.get("content") or "")[:80],
                        "ugc_right": int(item.get("ugc_right") or 1),
                        "images": int(item.get("images") or 0),
                        "ts": float(item.get("ts") or 0),
                    })
        self._items = items[: self._max]

    def _persist(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:  # noqa: PTH123
                json.dump(self._items, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        except OSError as e:  # 历史只是附加信息，落盘失败不影响已完成的发布
            logger.warning("qzone_history_persist_failed err=%s", e)

    def _record(self, tid: str, content: str, ugc_right: int, images: int) -> None:
        with self._lock:
            self._items = [it for it in self._items if it["tid"] != tid]
            self._items.insert(0, {"tid": tid, "content": content[:80], "ugc_right": ugc_right,
                                   "images": images, "ts": time.time()})
            self._items = self._items[: self._max]
            self._persist()

    def _drop(self, tid: str) -> None:
        with self._lock:
            before = len(self._items)
            self._items = [it for it in self._items if it["tid"] != tid]
            if len(self._items) != before:
                self._persist()
