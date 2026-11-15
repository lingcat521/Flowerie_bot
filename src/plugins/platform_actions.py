"""Permission-gated actions backed by the platform's shared domain services."""

import asyncio
import base64
from pathlib import Path

from src.core.sanitizer import sanitize_untrusted_text
from src.plugins.document_file import read_plugin_document
from src.plugins.http_action import plugin_http_request
from src.services.automation_config import AUTOMATION_KEYS
from src.services.file_parser import file_parse_error
from src.services.web_search import ENGINE_IDS, _extract_main_text, _extract_title

_AUTOMATION_FLAGS = tuple(key for key in AUTOMATION_KEYS if key.endswith("_ENABLED"))


def _number(payload, name, default=None, maximum=None):
    value = payload.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{name} 必须是正整数")
    if isinstance(value, str) and (not value.isascii() or not value.isdecimal()):
        raise ValueError(f"{name} 必须是正整数")
    value = int(value)
    if not 0 < value <= (maximum if maximum is not None else (1 << 63) - 1):
        raise ValueError(f"{name} 超出范围")
    return value


def _text(payload, name, limit, *, required=False):
    value = payload.get(name, "")
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f"{name} 格式不合法（最多 {limit} 字符）")
    return value.strip()


def _unavailable():
    return {"ok": False, "error": "平台服务未启用或未接入", "code": "unavailable"}


class PlatformActions:
    def __init__(self, config, *, profiles=None, search=None, qzone=None, knowledge=None,
                 personas=None, nicknames=None, prompts=None, rules=None, memory=None,
                 digest=None, stickers=None, sender=None, tasks=None, settings=None, task_services=None,
                 file_parser=None):
        self.config = config
        self.file_parser = file_parser
        self.profiles = profiles
        self.search = search
        self.qzone = qzone
        self.knowledge = knowledge
        self.personas = personas
        self.nicknames = nicknames
        self.prompts = prompts
        self.rules = rules
        self.memory = memory
        self.digest = digest
        self.stickers = stickers
        self.sender = sender
        self.tasks = tasks
        self.settings = settings
        self.task_services = task_services or {}

    async def run(self, action, payload):
        try:
            if action in ("file_parse", "file_parse_status"):
                return await self._file_parse(action, payload)
            if action.startswith("profile_"):
                return self._profile(action, payload)
            if action.startswith("private_"):
                return await self._private(action, payload)
            if action.startswith("sticker_"):
                return await self._sticker(action, payload)
            if action in ("web_search", "web_fetch"):
                if self.search is None or not self.search.enabled():
                    return _unavailable()
                if action == "web_fetch":
                    return await self._fetch(payload)
                query = _text(payload, "query", 500, required=True)
                limit = _number(payload, "limit", 5, 10)
                options = {}
                engine = _text(payload, "engine", 24)
                if engine:
                    if engine not in ENGINE_IDS:
                        raise ValueError("不支持的搜索引擎")
                    options["engine"] = engine
                time_range = _text(payload, "time_range", 16)
                if time_range:
                    if time_range not in ("day", "week", "month", "year"):
                        raise ValueError("time_range 必须是 day/week/month/year")
                    options["time_range"] = time_range
                return await self.search.search(query, max_results=limit, **options)
            if action.startswith("qzone_"):
                if self.qzone is None or not self.qzone.enabled():
                    return _unavailable()
                if action == "qzone_rights":
                    return {"ok": True, "rights": self.qzone.rights(),
                            "default_ugc_right": self.qzone.default_ugc_right()}
                return {"ok": True, "items": self.qzone.history()[:_number(payload, "limit", 20, 100)]}
            if action == "automation_status":
                return {"ok": True, "features": {key: bool(getattr(self.config, key, False))
                                                  for key in _AUTOMATION_FLAGS}}
            if action == "automation_tasks":
                if self.tasks is None:
                    return _unavailable()
                tasks = self.tasks.status()
                return {"ok": True, "tasks": {key: {**value, "last_run": getattr(
                    self.task_services.get(key), "last_run", None)} for key, value in tasks.items()}}
            if action == "automation_set_flags":
                if self.settings is None:
                    return _unavailable()
                flags = payload.get("flags")
                if (not isinstance(flags, dict) or not flags or any(
                        key not in _AUTOMATION_FLAGS or type(value) is not bool for key, value in flags.items())):
                    raise ValueError("flags 只能包含自动化面板中的布尔开关")
                return _result(self.settings.update_many(
                    {key: str(value).lower() for key, value in flags.items()}))
            if action.startswith("global_prompt_"):
                if self.prompts is None:
                    return _unavailable()
                if action == "global_prompt_get":
                    return {"ok": True, "content": self.prompts.get_global_prompt()}
                if action == "global_prompt_reset":
                    return {"ok": True, "deleted": self.prompts.reset_global_prompt()}
                return {"ok": True, "content": self.prompts.set_global_prompt(_text(payload, "content", 2000))}
            if action in ("persona_get", "persona_create", "persona_update", "persona_delete", "persona_set_global"):
                return self._manage_persona(action, payload)
            if action == "persona_list":
                return ({"ok": True, "items": [_persona_metadata(item) for item in self.personas.list_personas()]}
                        if self.personas is not None else _unavailable())
            group_id = _number(payload, "group_id")
            if action == "digest_get":
                if self.digest is None or not getattr(self.config, "DIGEST_ENABLED", False):
                    return _unavailable()
                row = self.digest.store.load(group_id)
                return {"ok": True, "digest": {"date": row[0], "text": row[1]} if row else None}
            if action.startswith("knowledge_"):
                return self._knowledge(action, payload, group_id)
            if action.startswith(("group_prompt_", "group_rules_")):
                return self._group_text(action, payload, group_id)
            if action in ("persona_bind", "persona_unbind"):
                if self.personas is None:
                    return _unavailable()
                if action == "persona_bind":
                    return _result(self.personas.set_group(group_id, _text(payload, "persona_id", 64, required=True)))
                return _result(self.personas.clear_group(group_id))
            if action in ("nickname_set", "nickname_list"):
                if self.nicknames is None:
                    return _unavailable()
                if action == "nickname_list":
                    return {"ok": True, "items": [{"persona_id": pid, "nickname": name}
                                                  for pid, name in self.nicknames.entries_for(group_id)]}
                pid = _text(payload, "persona_id", 64) or None
                if pid and (self.personas is None or self.personas.get_persona(pid) is None):
                    raise ValueError("未知 persona_id")
                self.nicknames.set(group_id, pid, _text(payload, "nickname", 60))
                return {"ok": True, "nickname": self.nicknames.get(group_id, pid)}
            if action == "persona_resolve":
                if self.personas is None:
                    return _unavailable()
                persona = self.personas.resolve_persona(group_id)
                return {"ok": True, "persona": _persona_metadata(persona) if persona is not None else None}
            if action == "nickname_resolve":
                if self.nicknames is None:
                    return _unavailable()
                persona_id = self.personas.resolve_persona_id(group_id) if self.personas else None
                return {"ok": True, "nickname": self.nicknames.get(group_id, persona_id)}
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "code": "invalid_argument"}
        return {"ok": False, "error": "未知平台 action"}

    async def _file_parse(self, action, payload):
        if self.file_parser is None:
            return _unavailable()
        status = self.file_parser.status()
        if action == "file_parse_status":
            return status
        if not status["enabled"]:
            return file_parse_error("unavailable", "文件解析已关闭")
        data = payload.get("content_base64")
        if not isinstance(data, str) or not data:
            raise ValueError("content_base64 必须是非空 Base64 字符串")
        limit = status["plugin_max_bytes"]
        if len(data) > ((limit + 2) // 3) * 4:
            return file_parse_error("file_too_large", f"插件单次解析上限为 {limit} 字节")
        try:
            content = base64.b64decode(data, validate=True)
        except ValueError:
            raise ValueError("content_base64 不是合法 Base64") from None
        if len(content) > limit:
            return file_parse_error("file_too_large", f"插件单次解析上限为 {limit} 字节")
        return await self.file_parser.parse_document(payload.get("filename"), content, plugin=True)

    async def parse_local_file(self, root, plugin_id, path):
        if self.file_parser is None or not (status := self.file_parser.status())["enabled"]:
            return _unavailable()
        limit = status["max_bytes"]
        try:
            content, filename = await asyncio.to_thread(read_plugin_document, root, plugin_id, path, limit)
        except NotImplementedError as exc:
            return file_parse_error("unavailable", str(exc))
        except ValueError as exc:
            return file_parse_error("invalid_argument", str(exc))
        if content is None:
            return file_parse_error("file_too_large", f"文件超过 {limit} 字节")
        return await self.file_parser.parse_document(filename, content, plugin=True)

    def _profile(self, action, payload):
        if self.profiles is None or not self.profiles.enabled():
            return _unavailable()
        group_id = _number(payload, "group_id")
        if action == "profile_list":
            limit = _number(payload, "limit", 20, 100)
            page = _number(payload, "page", 1, 500)
            start = (page - 1) * limit
            rows = self.profiles.list_group_profiles(group_id, limit=limit, offset=start)
            return {"ok": True, "items": rows,
                    "count": self.profiles.store.count_group(group_id), "page": page}
        if action == "profile_clear":
            return {"ok": True, "deleted": self.profiles.clear_group(group_id)}
        user_id = _number(payload, "user_id")
        if action == "profile_get":
            return {"ok": True, "profile": self.profiles.profile_of(group_id, user_id)}
        if action == "profile_delete":
            return {"ok": True, "deleted": self.profiles.delete_profile(group_id, user_id)}
        label = _text(payload, "label", 32, required=True)
        text = _text(payload, "text", 120)
        nickname = _text(payload, "nickname", 60)
        ok, message = self.profiles.set_section(group_id, user_id, label, text, nickname=nickname)
        return {"ok": True, "message": message} if ok else {"ok": False, "error": message}

    def _knowledge(self, action, payload, group_id):
        service = self.knowledge
        if service is None:
            return _unavailable()
        if action == "knowledge_list":
            query = _text(payload, "query", 200)
            return {"ok": True, "items": service.list_for_group(group_id, search=query,
                                                              limit=_number(payload, "limit", 20, 100))}
        if action == "knowledge_match":
            text = _text(payload, "text", 4000, required=True)
            return {"ok": True, "items": service.retrieve_matches(group_id, text, _number(payload, "limit", 10, 50))}
        if action == "knowledge_add":
            return _result(service.add_knowledge(
                group_id, _text(payload, "term", 200, required=True), _text(payload, "meaning", 2000, required=True),
                examples=_text(payload, "examples", 400), source="manual",
                confidence=_text(payload, "confidence", 10) or "medium"))
        if action == "knowledge_clear":
            return _result(service.clear_group(group_id))
        item_id = _number(payload, "knowledge_id")
        if action == "knowledge_get":
            return {"ok": True, "item": service.get_by_id(item_id, group_id)}
        if action == "knowledge_delete":
            return _result(service.delete_knowledge(item_id, group_id))
        limits = {"meaning": 2000, "examples": 400, "confidence": 10, "status": 10}
        changes = {name: _text(payload, name, limit) for name, limit in limits.items() if name in payload}
        return _result(service.update_knowledge(item_id, group_id, **changes))

    def _manage_persona(self, action, payload):
        service = self.personas
        if service is None:
            return _unavailable()
        pid = _text(payload, "persona_id", 64, required=True)
        if action == "persona_get":
            return {"ok": True, "persona": service.get_persona(pid)}
        if action == "persona_delete":
            return _result(service.delete_persona(pid))
        if action == "persona_set_global":
            return _result(service.set_global(pid))
        limits = {"name": 50, "description": 200, "system_prompt": service.max_system_prompt_length,
                  "vocabulary": 4000, "behavior_rules": 4000, "response_style": 4000}
        fields = {key: _text(payload, key, limit) for key, limit in limits.items() if key in payload}
        if action == "persona_create":
            if not fields.get("name"):
                raise ValueError("name 不能为空")
            return _result(service.create_persona(pid, **fields))
        if not fields:
            raise ValueError("没有可更新的人格字段")
        return _result(service.update_persona(pid, **fields))

    def _group_text(self, action, payload, group_id):
        if action.startswith("group_prompt_"):
            service = self.prompts
            if service is None:
                return _unavailable()
            if action == "group_prompt_get":
                return {"ok": True, "content": service.get_group_prompt(group_id)}
            if action == "group_prompt_reset":
                return {"ok": True, "deleted": service.reset_group_prompt(group_id)}
            return {"ok": True, "content": service.set_group_prompt(group_id, _text(payload, "content", 2000))}
        if self.rules is None:
            return _unavailable()
        if action == "group_rules_set":
            return {"ok": True, "content": self.rules.set(group_id, _text(payload, "content", 4000))}
        return {"ok": True, "content": self.rules.get(group_id)}

    async def _private(self, action, payload):
        if action == "private_policy":
            return {"ok": True, "enabled": bool(getattr(self.config, "PRIVATE_CHAT_ENABLED", False)),
                    "allowed_qqs": list(getattr(self.config, "PRIVATE_CHAT_ALLOWED_QQS", None) or [])}
        if action == "private_allowlist_set":
            if self.settings is None:
                return _unavailable()
            ids = payload.get("user_ids")
            if not isinstance(ids, list) or len(ids) > 200:
                raise ValueError("user_ids 必须是最多 200 项的数组")
            values = dict.fromkeys(_number({"user_id": item}, "user_id") for item in ids)
            return _result(self.settings.update("PRIVATE_CHAT_ALLOWED_QQS", ",".join(map(str, values))))
        if self.memory is None:
            return _unavailable()
        if action == "private_memory_clear":
            user_id = _number(payload, "user_id")
            return {"ok": True, "deleted": await self.memory.clear_user_memory(user_id, -user_id)}
        limit = _number(payload, "limit", 20, 100)
        rows = [{"user_id": int(uid), "notes": len(self.memory.get_user_notes(int(uid), int(gid)) or [])}
                for uid, gid in self.memory.iter_user_groups() if int(gid) < 0 and int(uid) == -int(gid)]
        return {"ok": True, "items": sorted((row for row in rows if row["notes"]),
                                            key=lambda row: (-row["notes"], row["user_id"]))[:limit]}

    async def _sticker(self, action, payload):
        if self.stickers is None or not self.stickers.is_enabled():
            return _unavailable()
        if action == "sticker_search":
            keyword = _text(payload, "keyword", 100).casefold()
            limit = _number(payload, "limit", 8, 50)
            rows = self.stickers.repository.list_ok(limit=500)
            matched = [row for row in rows if keyword in
                       f"{row['filename']} {row.get('description') or ''}".casefold()]
            return {"ok": True, "stickers": [{"filename": row["filename"],
                                              "description": str(row.get("description") or "")[:120]}
                                             for row in matched[:limit]]}
        if self.sender is None:
            return _unavailable()
        group_id = _number(payload, "group_id")
        filename = _text(payload, "filename", 255, required=True)
        text = _text(payload, "text", 2000)
        if any(char in filename for char in "/\\[]") or filename in (".", ".."):
            raise ValueError("filename 必须是表情包文件名")
        candidate = self.stickers.extract_sticker(f"[STICKER:{filename}]")
        if not candidate or Path(candidate).resolve().parent != Path(self.config.STICKER_DIR).resolve():
            return {"ok": False, "error": "找不到表情包"}
        item = self.stickers.repository.get_by_path(candidate)
        if not item or item.get("status") != "ok":
            return {"ok": False, "error": "找不到已索引的表情包"}
        if not self.stickers.can_send(group_id):
            return {"ok": False, "error": "表情包冷却中"}
        if not await self.sender.send_group_message_with_image(group_id, text or None, candidate):
            return {"ok": False, "error": "表情包发送失败"}
        self.stickers.mark_sent(group_id)
        return {"ok": True, "filename": filename}

    async def _fetch(self, payload):
        url = _text(payload, "url", 800, required=True)
        maximum = _number(payload, "max_chars", 2000, 4000)
        response = await plugin_http_request({"url": url, "method": "GET"})
        if not response.get("ok") or response.get("status") != 200:
            return {"ok": False, "error": response.get("error") or f"HTTP {response.get('status')}"}
        raw = response.get("body") or ""
        if response.get("content_type", "").startswith("text/plain"):
            title, text = "", raw
        elif response.get("content_type", "").startswith(("text/html", "application/xhtml+xml")):
            title, text = _extract_title(raw), _extract_main_text(raw)
        else:
            return {"ok": False, "error": "仅支持 HTML 与纯文本页面"}
        text, _ = sanitize_untrusted_text(text)
        return {"ok": True, "url": url, "title": title, "text": text[:maximum],
                "truncated": len(text) > maximum}


def _persona_metadata(item):
    return {key: item.get(key) for key in ("id", "name", "description")}


def _result(outcome):
    ok, message = outcome
    return {"ok": ok, "message" if ok else "error": message}
