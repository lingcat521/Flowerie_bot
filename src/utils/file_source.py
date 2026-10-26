"""文件来源归一化（图片/头像等「本地路径或 URI」参数的统一入口）。

背景（同一类 bug 的根因）：面板/插件允许填「本地绝对路径」，但协议端的上传器
（如 NapCat 的 uriToLocalFile）只认 file:// / http(s):// / base64:// 这类 URI；
把裸路径原样转发过去会被当成非法来源。所有面向用户的「路径或 URI」参数必须先经
to_uri_source() 归一化，再进 Sender/Adapter。

约定：
- 已带 scheme（file:// / http:// / https:// / base64://）→ 原样返回
- 本地绝对路径（含 ~ 展开）→ 补 file:// 前缀
- 相对路径：
   * strict=True  → 返回空串（让调用方明确报错「请填绝对路径」）
   * strict=False → 原样返回（兼容 base64 裸串等调用方自有语义）
"""
import os

SCHEMES = ("file://", "http://", "https://", "base64://")


def has_scheme(value: str) -> bool:
    return str(value or "").startswith(SCHEMES)


def to_uri_source(raw: str, strict: bool = False) -> str:
    """把「路径 / URI / base64」归一成协议端认识的来源字符串。"""
    value = str(raw or "").strip()
    if not value:
        return ""
    if has_scheme(value):
        return value
    path = os.path.expanduser(value)
    if os.path.isabs(path):
        return "file://" + path
    return "" if strict else value
