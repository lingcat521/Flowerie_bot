import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.config import Settings
from src.core.sanitizer import sanitize_untrusted_text
from src.models import GlobalState
from src.services.ai_client import AIClient
from src.services.file_parser import FileParser
from src.utils.logging_setup import get_logger

logger = get_logger(__name__)


class MessageAssembler:
    """消息组装：把原始 message_array 拼成 AI 能看懂的完整文本。

    负责：文本提取、图片识图、回复/@ 扫描、转发解析（含转发内图片）、
    卡片解析、待解析文件配对、消息存档。Router 只负责流程决策。
    注意：辅助方法返回"要追加的文本块"（字符串不可变，不能原地改外层变量）。
    """

    def __init__(self, config: Settings, ai_client: AIClient, file_parser: FileParser,
                 global_state: GlobalState, resource_fetcher: Optional[Any] = None):
        self.config = config
        self.ai_client = ai_client
        self.file_parser = file_parser
        self.global_state = global_state
        # 资源取数（Gate R）：**协议无关**的取数出口，由组合根注入（OneBot/Milky 各自的实现在 Adapter 层）。
        # Core 只做"拿资源引用 -> 交给 fetcher -> 把字节交给解码器"，不认识协议侧的 id 字段名。
        self.resource_fetcher = resource_fetcher

    async def assemble(
        self,
        event,
        user_id: int,
        group_id: int,
        raw_time: int,
    ) -> Tuple[str, List[str], bool, bool, bool]:
        """组装消息，返回 (full_text, 顶层图片描述列表, is_reply_to_bot, has_reply_to_other, has_at_others)。"""
        message_array = event.message_segments or []   # 组装配件可读段（boundary 已规范化）
        # 纯文本与@机器人：来自边界解析（与 file_parser 同规则，快照断言保障等价）
        clean_text = event.text
        full_text = clean_text

        # 顶层图片识图（边界语义：images=url-or-file；历史行为仅描述 url）
        image_descriptions = await self._describe_images(event)
        if image_descriptions:
            # 图片描述也按不可信数据处理（图片里可能被塞文字指令）
            cleaned_descs, _ = sanitize_untrusted_text("；".join(image_descriptions))
            full_text += f"\n[用户发送了一张图片，内容如下：]\n{cleaned_descs}\n[图片内容结束]"
            logger.debug(f"Image descriptions: {image_descriptions}")

        # 表情（QQ 表情 / 商城表情）：Adapter 已归一化，这里只做语义化（证据见 docs/message-model.md §3）
        full_text += self._assemble_faces(event)
        full_text += self._assemble_media(event)
        full_text += self._assemble_quote(event)

        # 回复与@：边界语义字段（parser 与旧 _scan_reply_and_at 同规则）
        is_reply_to_bot = event.is_reply_to_bot
        has_reply_to_other = event.has_reply_to_other
        has_at_others = event.has_at_others

        # 合并转发（含转发内图片，由 VISION_FORWARD_IMAGES 控制）
        full_text += await self._assemble_forward(message_array)

        # JSON 卡片
        full_text += await self._assemble_card(message_array)

        # 待解析文件配对（NapCat 先发上传通知，消息过来后再取内容）
        full_text += await self._assemble_pending_file(user_id, group_id)

        # 存档
        self._archive(group_id, user_id, full_text, raw_time)
        return full_text, image_descriptions, is_reply_to_bot, has_reply_to_other, has_at_others

    # ---------- 顶层图片识图 ----------
    async def _describe_images(self, event) -> List[str]:
        if not getattr(self.config, "VISION_ENABLED", True):
            return []  # 图片识图总开关：关闭 → 不调用视觉模型（省 token）
        descriptions = []
        max_images = max(1, self.config.MAX_IMAGES_PER_MESSAGE)
        # OneBot 全实现兼容：本地 file 字段优先（任何实现都会给；绕开 CDN/UA/过期），
        # URL 仅兜底（file 缺失或不可读时）。
        file_paths = [f for f in (getattr(event, "image_files", None) or []) if f]
        urls = [i for i in (event.images or [])
                if str(i).startswith(("http://", "https://"))]
        pending = [("file", f) for f in file_paths]
        pending += [("url", u) for u in urls if u not in file_paths]
        for kind, src in pending[:max_images]:
            try:
                if kind == "file":
                    desc = await self.ai_client.describe_image_file(src)
                else:
                    desc = await self.ai_client.describe_image(src)
            except Exception as e:  # noqa: BLE001 - 描述失败不阻断组装
                logger.warning(f"Vision describe failed for image {kind}: {src[:80]} ({e})")
                desc = ""
            if desc:
                descriptions.append(desc)
            else:
                logger.warning(f"Vision describe failed for image {kind}: {src[:80]}")
        return descriptions

    # ---------- 回复/@ 扫描 ----------
    # ---------- 合并转发 ----------
    async def _assemble_forward(self, message_array: List[Dict]) -> str:
        forward_text, forward_image_urls, has_forward = await self.file_parser.extract_forward_messages(message_array)
        if not has_forward:
            return ""
        block = ""
        if forward_text:
            # 代码层防注入：转发文本清洗后再进上下文
            forward_text, inject_hit = sanitize_untrusted_text(forward_text)
            if inject_hit:
                logger.warning("疑似提示词注入已过滤（转发内容）")
            block += f"\n[用户转发了多条消息，内容如下：]\n{forward_text}\n[转发内容结束]"
        # 转发里的图片：由 VISION_FORWARD_IMAGES 开关控制（默认关，省视觉 token）
        if (forward_image_urls and self.config.VISION_FORWARD_IMAGES
                and getattr(self.config, "VISION_ENABLED", True)):
            forward_image_descriptions = []
            max_images = max(1, self.config.MAX_IMAGES_PER_MESSAGE)
            for fwd_url in forward_image_urls[:max_images]:
                fwd_desc = await self.ai_client.describe_image(fwd_url)
                if fwd_desc:
                    forward_image_descriptions.append(fwd_desc)
                else:
                    logger.warning(f"Vision describe failed for forward image url: {fwd_url[:80]}")
            if len(forward_image_urls) > max_images:
                logger.warning(f"转发图片超过上限({max_images}张)，仅识别前 {max_images} 张")
            if forward_image_descriptions:
                # 图片描述同样按不可信数据处理
                cleaned_descs, _ = sanitize_untrusted_text("；".join(forward_image_descriptions))
                block += f"\n[用户转发的消息中包含图片，内容如下：]\n{cleaned_descs}\n[图片内容结束]"
                logger.debug(f"Forward image descriptions: {forward_image_descriptions}")
        return block

    # ---------- JSON 卡片 ----------
    def _assemble_quote(self, event) -> str:
        """引用消息的**内联内容**（G4）。

        证据：[DOC] Milky 规范 `common.ts` L327-333（`reply.segments` 内联被引段）；
        OneBot 的 reply 段只有 `id`（`event/message.md` / NapCat `types/message.ts`）——
        因此 OneBot 侧本函数返回空串：**不编造引用内容，也不假装拿到了**。
        """
        text = getattr(event, "reply_text", "") or ""
        if not text:
            return ""
        note, _hit = sanitize_untrusted_text(text[:200])
        return chr(10) + "[引用的消息：" + note + "]"

    def _assemble_media(self, event) -> str:
        """把语音/视频/XML 归一化字段变成 AI 能理解的一句话（G3）。

        证据：
        - [CODE] NapCat `napcat-onebot/types/message.ts` L106-115（`record`/`video` 均用
          `FileBaseDataSchema`）、L228-233（`xml{data}`）；
        - [DOC] Milky 规范 `common.ts` L342-353（`record`/`video` 字段）、L377-380（`xml{service_id,xml_payload}`）。
        XML **只报告存在与长度、不解析内容**（任务书 §5.3：先保真保存，再考虑高级解析）。
        上限各 3 条：与图片/表情/转发一致，防单条消息刷屏。
        """
        parts = []
        for rec in (getattr(event, "records", None) or [])[:3]:
            if not isinstance(rec, dict):
                continue
            dur = rec.get("duration")
            parts.append("[语音%s]" % (("，%s 秒" % dur) if dur else ""))
        for vid in (getattr(event, "videos", None) or [])[:3]:
            if not isinstance(vid, dict):
                continue
            extra = []
            if vid.get("duration"):
                extra.append("%s 秒" % vid["duration"])
            if vid.get("width") and vid.get("height"):
                extra.append("%sx%s" % (vid["width"], vid["height"]))
            parts.append("[视频%s]" % (("（" + "，".join(extra) + "）") if extra else ""))
        for xml in (getattr(event, "xmls", None) or [])[:3]:
            if not isinstance(xml, dict):
                continue
            raw = str(xml.get("raw_xml") or "")
            sid = str(xml.get("service_id") or "")
            parts.append("[XML 卡片（%s已保真保存，未解析；%d 字符）]"
                         % (("service_id=" + sid + "，") if sid else "", len(raw)))
        if not parts:
            return ""
        note, _hit = sanitize_untrusted_text(" ".join(parts))
        return chr(10) + "[用户发送了媒体：" + note + "]"

    def _assemble_faces(self, event) -> str:
        """把表情归一化字段变成 AI 能理解的一句话。

        证据：
        - [CODE] NapCat napcat-onebot/types/message.ts：face{id,resultId?,chainCount?}、
          mface{emoji_package_id,emoji_id,key,summary}；
        - [CODE] LagrangeV2 的 Lagrange.Milky/Entity/Segment/FaceSegment.cs（face{face_id}，
          **无** is_large）、MarketFaceSegment.cs（market_face{url}，**仅 url**）；LLBot market_face{summary,url}；
        - [DOC] Milky 规范 common.ts L323-326 的 face 另有 is_large（since 1.1）、L366-372 的 market_face
          另有 emoji_id/emoji_package_id/key/summary —— **规范字段比实现宽**，故下面一律逐字段兜底。
        - [INFERENCE] 统一表达成文本提示；Core 只读 Adapter 归一化结果，不读协议字段。

        上限 3 条：与图片/转发一致，防单条消息刷屏。
        """
        faces = getattr(event, "faces", None) or []
        if not faces:
            return ""
        parts = []
        for f in faces[:3]:
            if not isinstance(f, dict):
                continue
            if f.get("kind") == "market_face":
                # 实现（V2）的 market_face 只有 url，无 summary/emoji_id → 不能退化成
                # 「[商城表情 商城表情]」，无描述时如实说明
                desc = str(f.get("summary") or f.get("emoji_id") or "无描述")
                parts.append("[商城表情 " + desc + "]")
            else:
                fid = str(f.get("face_id") or "?")
                extra = []
                if f.get("chain_count"):
                    extra.append("连击 x%s" % f["chain_count"])
                if f.get("is_large"):
                    extra.append("大表情")
                suffix = ("，" + "，".join(extra)) if extra else ""
                parts.append("[QQ 表情 id=" + fid + suffix + "]")
        if not parts:
            return ""
        # 表情摘要来自 QQ/客户端，按不可信数据处理
        note, _hit = sanitize_untrusted_text(" ".join(parts))
        return chr(10) + "[用户发送了表情：" + note + "]"

    def _multimsg_as_forward(self, message_array: List[Dict]):
        """把 app=com.tencent.multimsg 的 json 卡片转成等价的 forward 段；无则 None。

        证据：NapCat SendMsg.ts L289-297 判定 arkElement JSON 的 app == com.tencent.multimsg，
        取 meta.detail.resid 拉取内层；LLBot 同样判定（milky/transform/message/incoming.ts L210-235）。
        即：这种卡片不是普通卡片，而是合并转发 —— 必须走拉取内层，否则内层消息全丢。
        """
        for seg in message_array or []:
            if not isinstance(seg, dict) or seg.get("type") != "json":
                continue
            data = seg.get("data") if isinstance(seg.get("data"), dict) else {}
            payload = data.get("data")
            if payload is None:
                payload = data.get("content") or data.get("text")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (ValueError, TypeError):
                    continue
            if not isinstance(payload, dict) or payload.get("app") != "com.tencent.multimsg":
                continue
            detail = (payload.get("meta") or {}).get("detail") or {}
            resid = detail.get("resid")
            if resid:
                return [{"type": "forward", "data": {"id": str(resid)}}]
        return None

    async def _assemble_card(self, message_array: List[Dict]) -> str:
        # multimsg 卡片 = 合并转发（证据见 _multimsg_as_forward）：优先按转发拉内层
        # 优先级（多卡片同条消息时，P4 决策 + 测试锁定 test_multimsg_card.py）：
        #   1) 第一个 app=com.tencent.multimsg 的卡片 -> 拉内层转发（内层即消息本体）
        #   2) 拉取失败 -> 退回卡片文本路径
        #   3) 其余普通卡片 -> 文本合并由 file_parser.extract_json_card_content 内部完成
        #   4) multimsg 成功时，同条消息里的其它卡片**不**再渲染（实践中一条消息只有一个卡片）
        fwd = self._multimsg_as_forward(message_array)
        if fwd is not None:
            block = await self._assemble_forward(fwd)
            if block:
                return block
            logger.debug('multimsg 卡片拉取内层失败，退回卡片文本路径')
        card_text, has_card = self.file_parser.extract_json_card_content(message_array)
        if has_card and card_text:
            # 代码层防注入：卡片文本清洗后再进上下文
            card_text, inject_hit = sanitize_untrusted_text(card_text)
            if inject_hit:
                logger.warning("疑似提示词注入已过滤（卡片内容）")
            return f"\n[用户分享了一个卡片，内容如下：]\n{card_text}\n[卡片内容结束]"
        return ""

    # ---------- 待解析文件 ----------
    async def _assemble_pending_file(self, user_id: int, group_id: int) -> str:
        pending_key = f"{user_id}_{group_id}"
        if pending_key not in self.global_state.pending_files:
            return ""
        file_info = self.global_state.pending_files.pop(pending_key)
        resource = file_info.get("resource")          # 边界层给的统一资源引用（协议中立）
        file_name = file_info.get("file_name", "未命名文件")
        try:
            file_size = int(file_info.get("file_size") or 0)
        except (TypeError, ValueError):
            file_size = 0  # 上传通知缺大小/脏数据：按小文件走解析，解码层还有兜底上限

        # 大小门槛与解码兜底上限对齐（MAX_FILE_DOWNLOAD_BYTES），避免"通知说 1MB 内但实际超限"
        size_limit = max(1, int(getattr(self.config, "MAX_FILE_DOWNLOAD_BYTES", 2 * 1024 * 1024)))

        if resource is not None and file_size <= size_limit:
            content_bytes, fetched = await self._fetch_resource(resource)
            file_content, success = ("", False)
            if fetched and content_bytes:
                file_content, success = self.file_parser.decode_bytes(content_bytes, file_name)
            if success and file_content:
                # 代码层防注入：文件内容清洗后再进上下文（文件是最高危注入载体）
                file_content, inject_hit = sanitize_untrusted_text(file_content)
                if inject_hit:
                    logger.warning(f"疑似提示词注入已过滤（文件内容: {file_name}）")
                logger.debug(f"File parsed: {file_name} ({len(file_content)} chars)")
                return f"\n[用户上传了一个文件，内容如下：]\n{file_content}\n[文件内容结束]"
            logger.warning(f"Failed to parse file: {file_name}")
        elif file_size > size_limit:
            logger.warning(f"File too large, skipped: {file_name} ({file_size} bytes)")
        else:
            logger.debug(f"No resource for pending file: {file_name}")
        return ""

    async def _fetch_resource(self, resource: Any) -> Tuple[bytes, bool]:
        """取资源字节（Gate R）：**Core 不认识协议**——取数由注入的 fetcher 完成。

        未接线 fetcher 时明确失败并留日志（不静默返回空内容，也不去猜协议）。
        """
        if self.resource_fetcher is None:
            logger.warning("resource_fetcher 未接线，跳过资源取数")
            return b"", False
        try:
            return await self.resource_fetcher.fetch(resource)
        except Exception as exc:  # noqa: BLE001 - 取数失败不得打断消息组装
            logger.warning(f"Resource fetch failed: {exc}")
            return b"", False

    # ---------- 存档（ARCHIVE_ENABLED 开关，默认关——隐私优先） ----------
    def _archive(self, group_id: int, user_id: int, text: str, raw_time: int) -> None:
        if not getattr(self.config, "ARCHIVE_ENABLED", False):
            return
        if not text:
            return
        try:
            base = self.config.ARCHIVE_BASE_DIR
            if not os.path.exists(base):
                os.makedirs(base, exist_ok=True)
            group_dir = os.path.join(base, str(group_id))
            if not os.path.exists(group_dir):
                os.makedirs(group_dir, exist_ok=True)
            filename = os.path.join(group_dir, f"{datetime.now().strftime('%Y-%m-%d')}.txt")
            time_str = datetime.fromtimestamp(raw_time).strftime("%H:%M:%S")
            line = f"[{time_str}] 用户{user_id}：{text}\n"
            with open(filename, "a", encoding="utf-8") as f:
                f.write(line)
            # 存档治理：保留天数 + 每群目录大小上限（隐私数据不是无限堆积）
            self._archive_cleanup(group_dir)
        except Exception as e:
            logger.error(f"Archive error: {e}")

    def _archive_cleanup(self, group_dir: str) -> None:
        """按 ARCHIVE_RETENTION_DAYS（保留天数）与 ARCHIVE_MAX_SIZE_MB（每群大小上限）清理存档。"""
        try:
            retention_days = getattr(self.config, "ARCHIVE_RETENTION_DAYS", 0)
            max_size_mb = getattr(self.config, "ARCHIVE_MAX_SIZE_MB", 0)
            if not retention_days and not max_size_mb:
                return
            files = [os.path.join(group_dir, f) for f in os.listdir(group_dir)
                     if os.path.isfile(os.path.join(group_dir, f))]
            # 1) 按保留天数清理过期文件
            if retention_days and retention_days > 0:
                cutoff = time.time() - retention_days * 86400
                for fp in files:
                    try:
                        if os.path.getmtime(fp) < cutoff:
                            os.remove(fp)
                    except OSError:
                        pass
            # 2) 按目录大小上限删最旧（从旧到新删到不超限）
            if max_size_mb and max_size_mb > 0:
                limit = max_size_mb * 1024 * 1024
                files = [os.path.join(group_dir, f) for f in os.listdir(group_dir)
                         if os.path.isfile(os.path.join(group_dir, f))]
                files.sort(key=os.path.getmtime)
                total = sum(os.path.getsize(fp) for fp in files)
                for fp in files:
                    if total <= limit:
                        break
                    try:
                        total -= os.path.getsize(fp)
                        os.remove(fp)
                        logger.debug(f"Archive pruned (size cap): {os.path.basename(fp)}")
                    except OSError:
                        pass
        except Exception as e:
            logger.error(f"Archive cleanup error: {e}")
