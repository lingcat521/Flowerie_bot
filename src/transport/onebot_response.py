"""OneBot 11 响应包封解析（纯 stdlib，**不依赖 aiohttp**）。

为什么单独成模块：响应模型是**协议事实**（跨客户端差异就在这几个字段上），
而 `action_channels.py` 要 import aiohttp 才能建连接 —— 把协议解析留在通道模块里，
测试就得连网络库一起装。这里只做纯函数，HTTP / WS 两个通道共用同一实现。

证据：
- `[DOC]` OneBot 11 spec `communication/http.md L50-70`：
  `status="ok"` → `retcode==0`；`status="async"` → `retcode==1`（已受理，**成败未知**，`data` 恒 `null`）；
  `status="failed"` → `retcode ∉ {0,1}`（详情看实现日志）。
- `[CODE]` go-cqhttp `coolq/api.go L2141-2155`：成功 `{data,retcode:0,status:"ok",message:""}`；
  失败 `{data:null,retcode,msg,wording,message,status:"failed"}`（三个消息字段同时出现，`message==wording`）。
- `[CODE]` NapCat `packages/napcat-onebot/action/OneBotAction.ts L20-41`：
  `createResponse(data, status, retcode, message, echo)`，错误走 `status:"failed"`。
"""
from typing import Any

#: 规范里的三种 status（空字符串 = 客户端没给，按 retcode 判定）
ONEBOT_OK_STATUSES = ("ok", "")
ONEBOT_ASYNC_STATUS = "async"
ONEBOT_ASYNC_RETCODE = 1


def parse_onebot_response(body: Any) -> dict:
    """OneBot 11 响应包封 → `{"ok": bool, "data": …, ["async": True], ["error": str]}`。

    - `async`（retcode 1）视为**已受理**：`ok=True` + `async=True` + `data=None`（规范如此）；
    - `status` 缺省时按 `retcode` 判定（0/1 成功）；
    - `status="ok"` 但 `retcode` 非 0/空 = 畸形：按失败处理 —— 没有证据时**不声称成功**；
    - 失败时把 `wording / msg / message` 里最有信息量的一条带进 `error`（三个字段的客户端差异见模块 docstring）。
    """
    if not isinstance(body, dict):
        return {"ok": False, "error": "非法响应（不是对象）"}
    status = str(body.get("status") or "").lower()
    retcode = body.get("retcode")
    if status == ONEBOT_ASYNC_STATUS or (not status and retcode == ONEBOT_ASYNC_RETCODE):
        return {"ok": True, "async": True, "data": None}
    if status in ONEBOT_OK_STATUSES and retcode in (0, None):
        return {"ok": True, "data": body.get("data")}
    detail = body.get("wording") or body.get("msg") or body.get("message") or ""
    if status == "failed" or retcode not in (0, None):
        return {"ok": False,
                "error": ("retcode=%s %s" % (retcode, detail)) if detail else "retcode=%s" % retcode}
    return {"ok": False, "error": "非法 status: %r" % body.get("status")}
