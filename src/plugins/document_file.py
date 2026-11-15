"""Bounded reads from a plugin's existing data directory."""

import os
import stat
from contextlib import ExitStack


def read_plugin_document(root, plugin_id, path, limit):
    if not isinstance(path, str) or not path or len(path) > 512 or "\\" in path or "\x00" in path:
        raise ValueError("path 必须是插件 data 目录内的相对路径")
    components = path.split("/")
    if len(components) > 12 or any(part in ("", ".", "..") for part in components):
        raise ValueError("path 必须是插件 data 目录内的相对路径")
    if os.open not in os.supports_dir_fd or not hasattr(os, "O_NOFOLLOW"):
        raise NotImplementedError("本机不支持安全的插件目录读取，请使用内联解析或 HTTP API")

    safe_flags = os.O_RDONLY | os.O_NOFOLLOW
    try:
        with ExitStack() as opened:
            directory = os.open(root, safe_flags | os.O_DIRECTORY)
            opened.callback(os.close, directory)
            for name in (plugin_id, "data", *components[:-1]):
                directory = os.open(name, safe_flags | os.O_DIRECTORY, dir_fd=directory)
                opened.callback(os.close, directory)
            fd = os.open(components[-1], safe_flags | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(fd, "rb") as file:
                info = os.fstat(file.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError("只支持插件目录内的普通文件")
                if info.st_size > limit:
                    return None, components[-1]
                content = file.read(limit + 1)
                return (content if len(content) <= limit else None), components[-1]
    except OSError:
        raise ValueError("无法读取文件，请确认路径及文件权限") from None
