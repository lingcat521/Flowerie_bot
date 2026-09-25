# -*- coding: utf-8 -*-
"""§6 HTTP 页面测试：真服务器 + 真插件进程，三个页面全部黑盒 HTTP 打。

覆盖：HTTP 200 / Content-Type / HTML 完整 / 页面标题 / Plugin 信息 /
无模板异常 / 无内部异常堆栈 / 无路径泄露（任务书 §6 逐条）。

**已知引擎限制（如实记录，不掩盖也不放宽）**：插件页由引擎渲染成 /panel 的**子页面片段**
（src/services/webui_render/plugin_webui.py 只输出页壳 + 内容区；净化器白名单不含
html/head/body/title），所以响应里没有 <!DOCTYPE html> 与 <title>。任务书 §6 的
「页面标题」由页壳 <h1 class="page-title"> 承担（test_page_titles_from_manifest_rendered），
「<title> 元素」用 xfail 单列，供报告里作为引擎限制说明。
"""
import re

import pytest

PAGES = ("index", "settings", "communication")

#: 页壳必须存在的结构（render_plugin_webui_page 的输出）
SHELL_MARKERS = ('<div class="page">', 'class="page-title"', 'class="breadcrumb"',
                 'flowerie-plugin-webui')

#: 模板/内部异常特征（出现任意一个即 FAIL）
EXCEPTION_MARKERS = ("Traceback (most recent call last)", "jinja2", "UndefinedError",
                     "TemplateNotFound", "TemplateSyntaxError", "插件数据钩子异常",
                     "插件未返回页面内容")

#: 路径泄露特征（出现任意一个即 FAIL）
PATH_MARKERS = ("/storage/emulated/0", "/data/data", "/etc/passwd", "/usr/lib/python",
                "site-packages")


def _titles(stack):
    pages = (stack.manifest_a.get("web_ui") or {}).get("pages") or []
    return {str(p.get("id")): str(p.get("title") or "") for p in pages}


@pytest.mark.parametrize("page", PAGES)
def test_pages_return_200_with_html_content_type(web, page):
    resp = web.get(web.page_url(web.plugin_a, page))
    assert resp.status == 200, "HTTP %s（期望 200）：%s" % (resp.status, resp.text[:200])
    assert resp.content_type.split(";")[0].strip() == "text/html", resp.content_type
    assert "charset=utf-8" in resp.content_type.lower(), resp.content_type
    assert "</div>" in resp.text, "HTML 被截断（没有闭合标签）"


@pytest.mark.parametrize("page", PAGES)
def test_pages_have_complete_page_shell(web, page):
    resp = web.get(web.page_url(web.plugin_a, page))
    text = resp.text
    assert len(resp.body) > 400, "页面过短（%d 字节），疑似渲染失败" % len(resp.body)
    for marker in SHELL_MARKERS:
        assert marker in text, "页壳缺少 %r：%s" % (marker, text[:300])
    assert text.count("<div") >= text.count("</div>") - 1, "标签不成对，HTML 不完整"
    assert "{{" not in text and "}}" not in text, "存在未替换的模板占位符：%s" % \
        re.findall(r"\{\{[^}]{0,40}\}\}", text)[:5]


@pytest.mark.parametrize("page", PAGES)
def test_page_titles_from_manifest_rendered(web, page):
    title = _titles(web).get(page, "")
    assert title, "manifest 未声明 %s 页标题" % page
    resp = web.get(web.page_url(web.plugin_a, page))
    assert title in resp.text, "页面标题 %r 未出现在响应里" % title
    assert 'class="page-title"' in resp.text


def test_plugin_information_present_on_index(web):
    resp = web.get(web.page_url(web.plugin_a, "index"))
    text = resp.text
    manifest = web.manifest_a
    assert manifest["name"] in text, "插件名未出现"
    assert manifest["version"] in text, "插件版本未出现"
    assert manifest["runtime"] in text, "runtime 未出现"
    assert web.plugin_a in text, "插件 id 未出现"
    # §5 要求的五项：Plugin Name / Version / Runtime / Status / SDK Version
    for elem_id in ("plugin-name", "plugin-version", "plugin-runtime", "plugin-status",
                    "plugin-sdk-version"):
        value = web.element_text(text, elem_id)
        assert value, "缺少插件信息项 #%s" % elem_id
    assert web.element_text(text, "plugin-status").lower().startswith("running"), \
        web.element_text(text, "plugin-status")


@pytest.mark.parametrize("page", PAGES)
def test_no_template_exception_or_internal_stack(web, page):
    text = web.get(web.page_url(web.plugin_a, page)).text
    hits = [m for m in EXCEPTION_MARKERS if m in text]
    assert not hits, "页面出现异常特征 %s" % hits
    assert "hook_error" not in text


@pytest.mark.parametrize("page", PAGES)
def test_no_filesystem_path_leak(web, page):
    text = web.get(web.page_url(web.plugin_a, page)).text
    hits = [m for m in PATH_MARKERS if m in text]
    assert not hits, "页面泄露文件系统路径 %s" % hits
    assert web.root not in text and web.plugin_dir not in text, "泄露了夹具临时目录"


def test_unknown_page_renders_error_page_not_stack(web):
    resp = web.get(web.page_url(web.plugin_a, "definitely_missing_page"))
    assert resp.status in (200, 302, 404), resp.status
    assert "Traceback" not in resp.text
    assert "/storage/emulated/0" not in resp.text


def test_pages_require_authentication(web):
    resp = web.get(web.page_url(web.plugin_a, "index"), auth=False)
    assert resp.status in (302, 401), "未认证访问未被拒绝：HTTP %s" % resp.status
    if resp.status == 302:
        assert "/panel" in resp.header("location")


def test_response_security_headers_present(web):
    resp = web.get(web.page_url(web.plugin_a, "index"))
    csp = resp.header("content-security-policy")
    assert "default-src 'none'" in csp, "缺少 CSP 兜底：%r" % csp
    assert resp.header("x-content-type-options") == "nosniff"


@pytest.mark.xfail(reason="已知引擎限制：插件页渲染为 /panel 子页面片段，无 <html>/<head>/<title>"
                          "（任务书 §6 的标题由 h1.page-title 承担）", strict=False)
def test_document_title_element_is_present(web):
    text = web.get(web.page_url(web.plugin_a, "index")).text
    assert "<title>" in text.lower(), "响应里没有 <title> 元素（引擎只输出页壳片段）"
