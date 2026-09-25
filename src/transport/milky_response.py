"""Milky 响应包封解析（纯 stdlib，不依赖 aiohttp）。

证据 `[CODE]` LLBot `src/milky/common/api.ts L4-39`：
  `Ok(data)`     → `{status: "ok", retcode: 0, data}`
  `Failed(code,msg)` → `{status: "failed", retcode, message}`
**没有** OneBot 11 那种 `msg`/`wording` 字段 —— 两套响应模型不通用，所以两个解析器分开。
"""
from typing import Any


def parse_milky_response(body: Any) -> dict:
    """Milky 响应 → `{"ok": bool, "data": …, ["error": str]}`（与 OneBot 版同口径，字段不同）。"""
    if not isinstance(body, dict):
        return {"ok": False, "error": "非法响应（不是对象）"}
    status = str(body.get("status") or "").lower()
    retcode = body.get("retcode")
    if status == "ok" or (not status and retcode in (0, None)):
        return {"ok": True, "data": body.get("data")}
    detail = body.get("message") or body.get("error") or ""
    return {"ok": False,
            "error": ("retcode=%s %s" % (retcode, detail)) if detail else "retcode=%s" % retcode}
