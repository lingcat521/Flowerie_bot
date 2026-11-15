"""Host rendering and input parsing for SDK WebUI views."""
import re
from html import escape
from urllib.parse import urlencode

_NAME = re.compile(r"[a-zA-Z][a-zA-Z0-9_.-]{0,63}\Z")
_INTEGER = re.compile(r"[+-]?[0-9]{1,16}\Z")
_MAX_INTEGER = 9_007_199_254_740_991


class WebUIViewError(ValueError):
    pass


def _check(condition, message):
    if not condition:
        raise WebUIViewError(message)


def _escape(value, limit=4000):
    return escape(str(value if value is not None else "")[:limit], quote=True)


def _valid_name(value):
    return isinstance(value, str) and _NAME.fullmatch(value) and not value.startswith("plugin_")


class WebUIView:
    """A validated, bounded view. Every displayed value is escaped by the host."""

    def __init__(self, data):
        _check(isinstance(data, dict), "view 必须是对象")
        self.data = data
        self.form = data.get("form")
        self.fields = []
        if self.form is not None:
            _check(isinstance(self.form, dict), "form 必须是对象")
            action = self.form.get("action")
            _check(_valid_name(action) and action != "get", "无效表单动作")
            fields = self.form.get("fields")
            _check(isinstance(fields, list) and 0 < len(fields) <= 32, "表单字段数必须在 1–32")
            names = set()
            for field in fields:
                _check(isinstance(field, dict), "字段必须是对象")
                name = field.get("name")
                kind = field.get("type")
                _check(_valid_name(name) and name not in names, "字段名无效或重复")
                _check(kind in ("text", "textarea", "integer", "boolean", "select"), "不支持的字段类型")
                _check(type(field.get("required", False)) is bool, "required 必须为布尔值")
                if kind == "select":
                    self._choices(field)
                names.add(name)
                self.fields.append(field)
        blocks = data.get("blocks", [])
        _check(isinstance(blocks, list) and len(blocks) <= 16, "blocks 最多 16 项")
        self.blocks = blocks

    @staticmethod
    def _choices(field):
        choices = field.get("options")
        _check(isinstance(choices, list) and 0 < len(choices) <= 50, "下拉选项数必须在 1–50")
        result = {}
        for item in choices:
            _check(isinstance(item, dict), "下拉选项必须是对象")
            value = item.get("value")
            _check(isinstance(value, str) and len(value) <= 120 and value not in result, "下拉选项值无效或重复")
            result[value] = item.get("label", value)
        return result

    def parse(self, action, values):
        """Return typed values and per-field errors. Undeclared fields never reach the handler."""
        _check(self.form is not None and self.form["action"] == action, "当前页面未声明该表单动作")
        parsed, errors = {}, {}
        for field in self.fields:
            name, kind = field["name"], field["type"]
            value = values.get(name, "")
            if not isinstance(value, str):
                errors[name] = "字段值无效"
            elif kind == "boolean":
                if value not in ("", "true"):
                    errors[name] = "复选框值无效"
                elif field.get("required") and value != "true":
                    errors[name] = "必填"
                else:
                    parsed[name] = value == "true"
            elif not value.strip():
                if field.get("required"):
                    errors[name] = "必填"
                else:
                    parsed[name] = None if kind == "integer" else ""
            elif kind == "integer":
                if not _INTEGER.fullmatch(value) or abs(int(value)) > _MAX_INTEGER:
                    errors[name] = "请输入有效整数"
                else:
                    parsed[name] = int(value)
            elif kind == "select" and value not in self._choices(field):
                errors[name] = "选项无效"
            elif len(value) > 2000:
                errors[name] = "最多 2000 字符"
            else:
                parsed[name] = value
        return parsed, errors

    def render(self, url, query, *, submitted=None, errors=None, message=""):
        parts = []
        if message:
            parts.append(f'<p class="plugin-view-feedback">{_escape(message)}</p>')
        for i, block in enumerate(self.blocks):
            parts.append(self._block(block, i, url, query))
        if self.form is not None:
            submit = _escape(self.form.get("submit", "保存"))
            action = _escape(self.form["action"])
            parts.append(f'<form method="post" action="{_escape(url)}" class="plugin-view-form">')
            parts.extend(self._field(field, i, submitted, errors or {}) for i, field in enumerate(self.fields))
            parts.append(f'<button class="btn" name="plugin_action" value="{action}">{submit}</button></form>')
        html = "".join(parts)
        _check(len(html.encode("utf-8")) <= 512 * 1024, "页面超过 512 KiB")
        return html

    def _field(self, field, index, submitted, errors):
        name, kind = field["name"], field["type"]
        value = field.get("value", "") if submitted is None else submitted.get(name, "")
        identity = f"plugin-view-field-{index}"
        attr = f'id="{identity}" name="{_escape(name)}"'
        required = " required" if field.get("required") else ""
        label = _escape(field.get("label", name))
        error = errors.get(name, "")
        if error:
            attr += f' aria-invalid="true" aria-describedby="{identity}-error"'
        if kind == "boolean":
            checked = ' checked' if value is True or value == "true" else ""
            control = f'<label for="{identity}"><input type="checkbox" {attr} value="true"{checked}{required}> {label}</label>'
        else:
            if kind == "textarea":
                element = f'<textarea {attr} maxlength="2000"{required}>\n{_escape(value)}</textarea>'
            elif kind == "select":
                options = []
                choices = self._choices(field)
                if "" not in choices:
                    choices = {"": "请选择", **choices}
                for option, title in choices.items():
                    selected = " selected" if option == str(value if value is not None else "") else ""
                    options.append(f'<option value="{_escape(option)}"{selected}>{_escape(title)}</option>')
                element = f'<select {attr}{required}>{"".join(options)}</select>'
            else:
                typ = "number" if kind == "integer" else "text"
                bounds = f' step="1" min="-{_MAX_INTEGER}" max="{_MAX_INTEGER}"' if kind == "integer" else ' maxlength="2000"'
                element = f'<input type="{typ}" {attr} value="{_escape(value)}"{bounds}{required}>'
            control = f'<label for="{identity}">{label}</label>{element}'
        if error:
            control += f'<p id="{identity}-error" class="plugin-view-error">{_escape(error)}</p>'
        return f'<div class="plugin-view-field">{control}</div>'

    @staticmethod
    def _block(block, index, url, query):
        _check(isinstance(block, dict), "组件必须是对象")
        kind = block.get("type")
        if kind in ("text", "status", "log"):
            tag = "pre" if kind == "log" else "p"
            return f'<{tag} class="plugin-view-{kind}">{_escape(block.get("text"))}</{tag}>'
        _check(kind == "table", "不支持的页面组件")
        columns, rows = block.get("columns"), block.get("rows")
        size = block.get("page_size", 20)
        _check(isinstance(columns, list) and 0 < len(columns) <= 12, "表格列数必须在 1–12")
        _check(isinstance(rows, list) and len(rows) <= 500, "本地分页表格最多 500 行")
        _check(type(size) is int and 1 <= size <= 50, "每页行数必须在 1–50")
        _check(all(isinstance(row, list) and len(row) == len(columns) for row in rows), "表格行列数不匹配")
        count = max(1, (len(rows) + size - 1) // size)
        key = f"table_{index}"
        raw = str(query.get(key, "1"))
        page = min(count, max(1, int(raw))) if _INTEGER.fullmatch(raw) else 1
        heading = "".join(f'<th scope="col">{_escape(col)}</th>' for col in columns)
        body = "".join("<tr>" + "".join(f"<td>{_escape(cell, 200)}</td>" for cell in row) + "</tr>"
                       for row in rows[(page - 1) * size:page * size])
        if not body:
            body = f'<tr><td colspan="{len(columns)}">暂无数据</td></tr>'
        nav = ""
        if count > 1:
            links = []
            for title, target in (("上一页", page - 1), ("下一页", page + 1)):
                if 1 <= target <= count:
                    kept = {k: v for k, v in query.items() if re.fullmatch(r"table_\d{1,2}", k)
                            and _INTEGER.fullmatch(str(v))}
                    href = url + "?" + urlencode({**kept, key: target})
                    links.append(f'<a href="{_escape(href)}">{title}</a>')
            nav = f'<nav class="plugin-view-pages">{" ".join(links)} <span>第 {page} / {count} 页</span></nav>'
        return f'<div class="plugin-view-table"><table><thead><tr>{heading}</tr></thead><tbody>{body}</tbody></table></div>{nav}'
