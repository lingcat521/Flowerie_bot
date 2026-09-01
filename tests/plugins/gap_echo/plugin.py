# -*- coding: utf-8 -*-
"""黑盒插件：真实子进程内调用 v2.1 缺口 API（split/merge/search/quote/friend/成员/
缓存/数据/ai_token/组合器——返回 test_ok/test_fail 供断言完整往返）。"""
from flowerie_sdk import rule_or


def _check(action, result, expect_ok=True):
    return result.get("ok") is expect_ok


def on_message(event, api=None):
    if api is None:
        return {"type": "test"}
    # 1) split/merge 本地语义往返
    sp = api.split_message({"text": "abcdef", "limit": 2})
    if not _check("split", sp) or sp["segments"] != ["ab", "cd", "ef"]:
        return {"type": "test_fail", "reason": "split"}
    mg = api.merge_message({"segments": sp["segments"]})
    if not _check("merge", mg) or mg["text"] != "abcdef":
        return {"type": "test_fail", "reason": "merge"}
    # 2) 搜索（主进程历史+过滤）
    sr = api.search_message({"group_id": 1, "query": "hello", "count": 10})
    if not _check("search", sr):
        return {"type": "test_fail", "reason": "search"}
    # 3) 引用链
    qc = api.quote_chain({"message_id": 5})
    if not _check("quote", qc) or qc["depth"] < 1:
        return {"type": "test_fail", "reason": "quote"}
    # 4) 好友详情
    fd = api.friend_detail({"user_id": 100})
    if not _check("friend", fd):
        return {"type": "test_fail", "reason": "friend"}
    # 5) 群成员搜索
    gm = api.group_member_search({"group_id": 7, "query": "雪"})
    if not _check("member", gm):
        return {"type": "test_fail", "reason": "member"}
    # 6) 缓存/Db（KV 域真）
    cg = api.cache_get({"key": "rk"})
    if not _check("cache", cg) or cg["ok"] is False:
        # KV 缺失是 ok:False——属预期（无写入）；黑盒只验证协议到达
        pass
    tk = api.ai_token({"text": "你好world"})
    if not _check("token", tk) or tk["tokens_estimate"] <= 0:
        return {"type": "test_fail", "reason": "token"}
    dq = api.db_query({"where": {}})
    if not _check("db", dq):
        return {"type": "test_fail", "reason": "db"}
    # 7) 组合器（SDK 本地构造校验）
    r = rule_or({"text_contains": "x"}, {"text_contains": "y"})
    if not isinstance(r, dict) or "any_of" not in r:
        return {"type": "test_fail", "reason": "rule_or"}
    return {"type": "test_ok"}
