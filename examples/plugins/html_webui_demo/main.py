"""HTML WebUI 示例插件（任务书第 1 份 §20 的完整示例，可直接复制运行）。

页面结构在 webui/pages/*.html（真实 HTML），样式在 webui/static/style.css；
本文件只提供**受控模板变量**：返回 {"vars": {...}, "message": "..."}，
没有这个钩子页面也能渲染（静态 HTML 是合法用法）。

禁止事项（由 Flowerie 的安全边界强制，不靠自觉）：
- 不能返回 DSL 组件树（那是旧兼容层，HTML 页面里会被拒绝）
- 不能输出 <script>/on*/javascript: 等构造（净化器会丢弃并记录）
- 不能读写其他插件或主程序的文件（路径校验 + 权限边界）
"""
import json
import os
import time

STATE_FILE = "state.json"
DEFAULT_STATE = {"greeting": "你好，花璃", "notify": True, "saved_at": ""}


def _state_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", STATE_FILE)


def _load_state():
    try:
        with open(_state_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return {**DEFAULT_STATE, **data} if isinstance(data, dict) else dict(DEFAULT_STATE)
    except (OSError, ValueError):
        return dict(DEFAULT_STATE)


def _save_state(state):
    path = _state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)


def webui_page(page, action, params, values):
    """四种参数与旧 DSL 时代完全一致（page, action, params, values）——外部契约不变。

    返回 {"vars": {...}}：这些变量会被安全地替换进 HTML 的 {{ 占位符 }}（值一律 HTML escape）。
    """
    state = _load_state()
    message = ""
    if action == "save":
        state["greeting"] = str(values.get("greeting") or state["greeting"])[:80]
        state["notify"] = str(values.get("notify") or "") in ("1", "true", "on", "yes")
        state["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_state(state)
        message = "设置已保存"
    return {
        "vars": {
            "greeting": state["greeting"],
            "notify": "已开启" if state["notify"] else "已关闭",
            "notify_checked": "checked" if state["notify"] else "",
            "saved_at": state["saved_at"] or "（尚未保存）",
            "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "page_id": page,
        },
        "message": message,
    }


def on_startup(context=None, api=None):
    """插件启动钩子（可选）：确保 data 目录存在。"""
    os.makedirs(os.path.dirname(_state_path()), exist_ok=True)
    return None
