
"""请求级 Persona 缓存（fix.txt ④）：一次逻辑请求内只解析一次，且不跨请求共享。

覆盖：群人格 / 全局人格 / 默认人格回退 / 不同群互不干扰 / 不同用户共享同一解析 /
不传 cache 时保持旧行为 / 新请求立刻读到 Web UI 的新配置 / 配置缺失时回退快照 /
查询次数从「每次 resolve 一轮」降到「每请求一轮」。
"""
import unittest
from types import SimpleNamespace

from src.services.persona_manager import DEFAULT_PERSONA_ID, PersonaManager


class _Repo:
    """计数用假 repository：只实现 resolve_persona 会用到的四个方法。"""

    def __init__(self, group_persona=None, global_persona=None, personas=None):
        self.group_persona = dict(group_persona or {})
        self.global_pid = global_persona
        self.personas = dict(personas or {})
        self.calls = []

    def get_group_persona_id(self, group_id):
        self.calls.append(("get_group_persona_id", group_id))
        return self.group_persona.get(group_id)

    def get_global_persona_id(self):
        self.calls.append(("get_global_persona_id",))
        return self.global_pid

    def get_persona(self, pid):
        self.calls.append(("get_persona", pid))
        return self.personas.get(pid)

    def list_personas(self):
        self.calls.append(("list_personas",))
        return list(self.personas.values())

    def upsert_persona(self, data):
        self.calls.append(("upsert_persona", data.get("id")))
        self.personas.setdefault(data["id"], data)


def _persona(pid, name=None):
    return {"id": pid, "name": name or pid, "system_prompt": "sp-" + pid,
            "builtin": pid.startswith("builtin")}


def _manager(repo, default=DEFAULT_PERSONA_ID):
    pm = PersonaManager(repo, default_persona_id=default,
                        config=SimpleNamespace(PERSONA_DEFAULT=default))
    repo.calls.clear()          # 只统计解析阶段的查询（构造时会播种内置预设）
    return pm


class TestPersonaRequestCache(unittest.TestCase):
    def test_group_persona_resolved_once_per_request(self):
        repo = _Repo(group_persona={10: "p10"}, personas={"p10": _persona("p10")})
        pm = _manager(repo)
        cache = {}
        first = pm.resolve_persona(10, cache=cache)
        queries_after_first = len(repo.calls)
        self.assertGreater(queries_after_first, 0)
        self.assertEqual(pm.resolve_persona(10, cache=cache), first)
        self.assertEqual(len(repo.calls), queries_after_first)      # 第二次零查询

    def test_global_persona_resolved_once_per_request(self):
        repo = _Repo(global_persona="pg", personas={"pg": _persona("pg")})
        pm = _manager(repo)
        cache = {}
        pm.resolve_persona(10, cache=cache)
        queries = len(repo.calls)
        pm.resolve_persona(10, cache=cache)
        pm.resolve_persona_id(10, cache=cache)
        self.assertEqual(len(repo.calls), queries)

    def test_default_persona_fallback_resolved_once(self):
        repo = _Repo(personas={DEFAULT_PERSONA_ID: _persona(DEFAULT_PERSONA_ID)})
        pm = _manager(repo)
        cache = {}
        self.assertEqual(pm.resolve_persona(10, cache=cache)["id"], DEFAULT_PERSONA_ID)
        queries = len(repo.calls)
        self.assertEqual(pm.resolve_persona_name(10, cache=cache), DEFAULT_PERSONA_ID)
        self.assertEqual(len(repo.calls), queries)

    def test_different_groups_are_separate_keys(self):
        repo = _Repo(group_persona={10: "p10", 20: "p20"},
                     personas={"p10": _persona("p10"), "p20": _persona("p20")})
        pm = _manager(repo)
        cache = {}
        self.assertEqual(pm.resolve_persona(10, cache=cache)["id"], "p10")
        self.assertEqual(pm.resolve_persona(20, cache=cache)["id"], "p20")
        queries = len(repo.calls)
        pm.resolve_persona(10, cache=cache)
        pm.resolve_persona(20, cache=cache)
        self.assertEqual(len(repo.calls), queries)

    def test_same_group_different_users_share_one_resolution(self):
        repo = _Repo(group_persona={10: "p10"}, personas={"p10": _persona("p10")})
        pm = _manager(repo)
        cache = {}
        pm.resolve_persona(10, cache=cache)                          # 用户 A
        queries = len(repo.calls)
        self.assertEqual(pm.resolve_persona_id(10, cache=cache), "p10")   # 用户 B 复用
        self.assertEqual(len(repo.calls), queries)

    def test_without_cache_behaviour_is_unchanged(self):
        repo = _Repo(group_persona={10: "p10"}, personas={"p10": _persona("p10")})
        pm = _manager(repo)
        pm.resolve_persona(10)
        queries = len(repo.calls)
        pm.resolve_persona(10)
        self.assertGreater(len(repo.calls), queries)                 # 旧行为：每次都查

    def test_cache_is_not_shared_across_requests(self):
        repo = _Repo(group_persona={10: "p10"},
                     personas={"p10": _persona("p10", "旧名"), "p10b": _persona("p10b", "新名")})
        pm = _manager(repo)
        self.assertEqual(pm.resolve_persona_name(10, cache={}), "旧名")
        repo.group_persona[10] = "p10b"                              # 模拟 Web UI 改配置
        self.assertEqual(pm.resolve_persona_name(10, cache={}), "新名")

    def test_missing_config_falls_back_to_snapshot(self):
        repo = _Repo(personas={DEFAULT_PERSONA_ID: _persona(DEFAULT_PERSONA_ID)})
        pm = PersonaManager(repo, default_persona_id=DEFAULT_PERSONA_ID)
        cache = {}
        self.assertEqual(pm.resolve_persona(None, cache=cache)["id"], DEFAULT_PERSONA_ID)
        self.assertEqual(pm.resolve_persona(None, cache=cache)["id"], DEFAULT_PERSONA_ID)

    def test_query_count_drops_to_one_round_per_request(self):
        repo = _Repo(group_persona={10: "p10"}, personas={"p10": _persona("p10")})
        pm = _manager(repo)
        pm._resolve_persona_uncached(10)
        per_resolve = len(repo.calls)                                # 旧：每次 resolve 一轮查询
        self.assertGreater(per_resolve, 0)
        repo.calls.clear()
        cache = {}
        pm.resolve_persona(10, cache=cache)
        pm.resolve_persona(10, cache=cache)
        pm.resolve_persona_id(10, cache=cache)
        self.assertEqual(len(repo.calls), per_resolve)               # 新：三次调用仍只查一轮

