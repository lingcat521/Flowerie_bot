"""Zero-JavaScript Web UI builders. Declare render="plugin" in the manifest."""


def field(name, label, kind="text", *, value=None, required=False, options=None):
    result = {"name": name, "label": label, "type": kind, "value": value, "required": required}
    if options is not None:
        result["options"] = options
    return result


def form(action, fields, submit="保存"):
    return {"action": action, "fields": list(fields), "submit": submit}


def table(columns, rows, page_size=20):
    return {"type": "table", "columns": list(columns), "rows": [list(row) for row in rows],
            "page_size": page_size}


def text(content, kind="text"):
    return {"type": kind, "text": content}


def page(*blocks, form=None, message="", storage=None, config=None):
    view = {"blocks": list(blocks)}
    if form is not None:
        view["form"] = form
    result = {"view": view, "message": message}
    if storage is not None:
        result["storage_set"] = storage
    if config is not None:
        result["config_set"] = config
    return result
