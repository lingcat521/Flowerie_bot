"""实机（real-device）测试的公共助手 —— 任务书 §13 / §14。

**三层测试必须分清**（§13）：
- `unit test`：`tests/test_*.py` —— 纯静态/进程内，CI 每次都跑；
- `integration test`：`tests/integration/` 里**能自动判定**的用例（本目录，默认 skip，需环境变量指向真实客户端）；
- `manual real-device test`：需要人工触发（如"让另一个号发一条戳一戳"）的步骤，写在 README 的流程里，
  **不写成自动用例**，也绝不假装 CI 能跑。

本模块只做三件事：探测环境、给出跳过原因（附 §8.3 要求的"缺失条件"）、按 §14 记录证据。
"""
import json
import os
import time
from typing import Any, Dict, Optional

# 环境变量约定（不写进仓库、不打印）：端点 + 测试群 + 可选媒体素材
ENV_ONEBOT_HTTP = "FLOWERIE_REAL_ONEBOT_HTTP"     # 例：http://127.0.0.1:3000
ENV_ONEBOT_TOKEN = "FLOWERIE_REAL_ONEBOT_TOKEN"   # 可选
ENV_MILKY_API = "FLOWERIE_REAL_MILKY_API"         # 例：http://127.0.0.1:3010
ENV_MILKY_TOKEN = "FLOWERIE_REAL_MILKY_TOKEN"     # 可选
ENV_GROUP = "FLOWERIE_REAL_GROUP"                 # 测试群号
ENV_IMAGE = "FLOWERIE_REAL_IMAGE"                 # 可选：一张可发送的图片（URL 或本地路径）
ENV_RECORD = "FLOWERIE_REAL_RECORD"               # 可选：一段可发送的语音
ENV_FILE = "FLOWERIE_REAL_FILE"                   # 可选：一个可发送的文件
EVIDENCE_DIR = os.environ.get("FLOWERIE_REAL_EVIDENCE_DIR",
                              os.path.join(os.path.dirname(os.path.abspath(__file__)), "evidence"))

#: 跳过时必须说清的缺失条件（§8.3：阻塞原因 / 已验证的源码证据 / 已尝试步骤 / 缺失条件）
MISSING_CONDITIONS = (
    "缺失条件：① 一个运行中的协议端（NapCat / Lagrange / LLBot）② " + ENV_ONEBOT_HTTP +
    " 或 " + ENV_MILKY_API + " 指向它 ③ " + ENV_GROUP + " 为测试群号 ④ 账号具备发言权限。"
    "已尝试步骤与真实返回见 docs/protocol-gap-closure.md §6（设备控制授权两条路径均 denied）。"
)


def client_config(kind: str) -> Optional[Dict[str, Any]]:
    """读取实机环境配置；未配置返回 None（调用方据此 skip，而不是失败）。"""
    if kind == "onebot11":
        base, token = os.environ.get(ENV_ONEBOT_HTTP, ""), os.environ.get(ENV_ONEBOT_TOKEN, "")
    else:
        base, token = os.environ.get(ENV_MILKY_API, ""), os.environ.get(ENV_MILKY_TOKEN, "")
    group = os.environ.get(ENV_GROUP, "")
    if not base or not group:
        return None
    return {"base": base.rstrip("/"), "token": token, "group": int(group)}


def skip_message(kind: str) -> str:
    return ("实机用例未配置环境（%s）：%s" % (kind, MISSING_CONDITIONS))


def media_path(env_name: str) -> Optional[str]:
    return os.environ.get(env_name) or None


def record_evidence(case: str, protocol: str, payload: Dict[str, Any]) -> str:
    """按任务书 §14 记录一次实机证据（不含 token/cookie/私人内容）。

    字段：client / version / protocol / commit/version / environment / date / test case /
          input / expected / actual / result
    """
    record = {
        "client": payload.get("client", ""),
        "version": payload.get("version", "unknown"),
        "protocol": protocol,
        "commit": os.environ.get("FLOWERIE_REAL_CLIENT_COMMIT", "unknown"),
        "environment": payload.get("environment", "real device"),
        "date": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "test_case": case,
        "input": payload.get("input", ""),
        "expected": payload.get("expected", ""),
        "actual": payload.get("actual", ""),
        "result": payload.get("result", "UNKNOWN"),
    }
    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    path = os.path.join(EVIDENCE_DIR, "%s-%s.json" % (protocol, case.replace(" ", "_")))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2)
    return path
