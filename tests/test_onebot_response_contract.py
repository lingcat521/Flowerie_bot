"""OneBot 11 响应包封契约（任务书 §十三/§十四/§十七：Action 与 Response 两个方向）。

被测代码是**生产路径**：`src/transport/action_channels.py::parse_onebot_response`，
HTTP 通道与 WS 通道都走它。语料来自 `tests/fixtures/go-cqhttp/actions/`（带 provenance）。

证据：
- `[DOC]` OneBot 11 spec `communication/http.md L50-70`：ok=retcode 0 / async=retcode 1（data 恒 null）/ failed=retcode ∉ {0,1}；
- `[CODE]` go-cqhttp `coolq/api.go L2141-2155`（OK/Failed 包封，失败带 msg+wording+message）；
- `[CODE]` NapCat `OneBotAction.ts L20-41`（同构包封）。
"""
import json
import os

import pytest

from src.transport.onebot_response import parse_onebot_response

ACTIONS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fixtures", "go-cqhttp", "actions")


def _load(name: str) -> dict:
    with open(os.path.join(ACTIONS, name), encoding="utf-8") as fh:
        return json.load(fh)


def test_gocqhttp_success_envelope():
    """go-cqhttp 成功包封：{data, retcode:0, status:"ok", message:""}（[CODE] api.go L2141）。"""
    body = _load("action_get_msg_response.json")
    assert body["_provenance"]["client"] == "go-cqhttp"
    result = parse_onebot_response(body)
    assert result["ok"] is True and "async" not in result
    data = result["data"]
    assert data["message_id"] == 900001 and data["message_seq"] == 77123
    assert data["group"] is True and data["sender"]["user_id"] == 456789
    assert data["message"][0]["type"] == "text"


def test_gocqhttp_failure_envelope_carries_wording():
    """失败包封三字段（msg/wording/message）都要能进错误文案，不能只剩 retcode。"""
    body = _load("action_failed_response.json")
    result = parse_onebot_response(body)
    assert result["ok"] is False
    assert "100" in result["error"]
    assert "MSG_NOT_FOUND" in result["error"] or "消息不存在" in result["error"]


@pytest.mark.parametrize("body,expect_ok,extra", [
    # [DOC] spec：async（retcode 1）= 已受理，成败未知，data 恒 null
    ({"status": "async", "retcode": 1, "data": None}, True, "async"),
    # [DOC] spec：status 缺省时按 retcode 判定
    ({"retcode": 0, "data": {"x": 1}}, True, None),
    # [CODE] NapCat error()：status=failed + retcode
    ({"status": "failed", "retcode": 1404, "message": "不存在的 API"}, False, None),
    # 畸形组合：声称 ok 却给非 0 retcode —— 没有证据时**不声称成功**
    ({"status": "ok", "retcode": 1404, "data": None}, False, None),
    # 非对象
    ("not-a-dict", False, None),
])
def test_envelope_matrix(body, expect_ok, extra):
    result = parse_onebot_response(body)
    assert result["ok"] is expect_ok, result
    if extra:
        assert result.get(extra) is True, result
    if not expect_ok:
        assert result.get("error"), result
