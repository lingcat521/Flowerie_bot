"""插件侧 Matcher 装饰器：收集元数据（JSON 可序列化），上报主进程注册。

优先级规则（与主进程一致，见 docs/sdk.md）：数字大者先匹配；
block=True 命中后阻断同插件后续 Matcher。
"""
from typing import Any, Callable, Dict, List

MATCHER_ATTR = "__flowerie_matchers__"


def command(name: str, /, **kw) -> Callable:
    return _mk("command", name, **kw)


def keyword(text: str, /, **kw) -> Callable:
    return _mk("keyword", text, **kw)


def regex(pattern: str, /, **kw) -> Callable:
    return _mk("regex", pattern, **kw)


def prefix(text: str, /, **kw) -> Callable:
    return _mk("prefix", text, **kw)


def exact(text: str, /, **kw) -> Callable:
    return _mk("exact", text, **kw)


def rule_or(*rules):
    """组合器：任一规则匹配即命中（any_of；可混入条件 kwargs）。"""
    return {"any_of": [r if isinstance(r, dict) else rule(**r) for r in rules]}


def rule_all(*rules):
    """组合器：全部规则匹配才命中（all_of）。"""
    return {"all_of": [r if isinstance(r, dict) else rule(**r) for r in rules]}


def rule_not(rules):
    """组合器：取反（not；传入规则/条件 dict）。"""
    return {"not": rules if isinstance(rules, dict) else rule(**rules)}


def rule(**conditions) -> Dict[str, Any]:
    """Rule 条件：is_group/is_private/is_bot_admin/is_bot_owner/
    is_group_admin/is_group_owner/user_id/group_id/自定义谓词（仅服务端支持 key 形式）。"""
    return {"conditions": dict(conditions)}


_REQUIRE_MAP = {
    "group_admin": {"is_group_admin": True},
    "group_owner": {"is_group_owner": True},
    "bot_admin": {"is_bot_admin": True},
    "bot_owner": {"is_bot_owner": True},
}


def require_permission(kind: str) -> Callable:
    """权限门装饰器（与 @command 任意顺序组合）：

    @command("ban")
    @require_permission("group_admin")        # 仅群管理/群主可触发
    async def ban(event): ...

    或（等价）
    @command("ban", rule=require_permission("group_admin"))
    ...
    未通过的 handler 不会触发（主进程按 Rule 过滤，不存在绕过路径）。
    """
    if kind not in _REQUIRE_MAP:
        raise ValueError(f"require_permission 不支持的权限类型: {kind}（支持: {', '.join(_REQUIRE_MAP)}）")

    def deco(func: Callable) -> Callable:
        existing = list(getattr(func, MATCHER_ATTR, []))
        for m in existing:  # require 在 @command 下方（先收集后补齐）
            m["rule"] = {**m.get("rule", {}), **_REQUIRE_MAP[kind]}
        if not existing:    # require 在 @command 上方——标记，_mk 收集时合并
            setattr(func, "__flowerie_require_perm__", kind)
        return func
    return deco


def _conds(fn):
    rp = getattr(fn, "__flowerie_require_perm__", None)
    return _REQUIRE_MAP.get(rp, {}) if rp else {}


def _mk(kind: str, pattern: Any, **kw) -> Callable:
    def wrap(func: Callable) -> Callable:
        matcher = {
            "kind": kind, "pattern": str(pattern), "priority": int(kw.get("priority", 0)),
            "block": bool(kw.get("block", False)),
            "name": str(kw.get("name") or func.__name__),
        }
        r = kw.get("rule")
        if isinstance(r, dict):
            matcher["rule"] = r.get("conditions", {}) if r.get("conditions") else r
        extra = _conds(func)
        if extra:
            matcher["rule"] = {**matcher.get("rule", {}), **extra}
            delattr(func, "__flowerie_require_perm__")
        existing = list(getattr(func, MATCHER_ATTR, []))
        existing.append(matcher)
        setattr(func, MATCHER_ATTR, existing)
        return func
    return wrap

def collect(func) -> List[Dict[str, Any]]:
    return list(getattr(func, MATCHER_ATTR, []))
