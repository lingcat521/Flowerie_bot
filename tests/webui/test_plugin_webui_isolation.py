# -*- coding: utf-8 -*-
"""§19 跨插件文件访问 + §22 多插件隔离（页面 / CSS / 配置 / API / Session / 文件 / Plugin ID）。

同时挂三个**真插件进程**：A=plugin_webui_test、B=minimal_py、C=minimal_py_c（B 的第二份部署）。
两个带 web_ui.files 的变体用来验证上传/下载空间互不可见（真文件、真子进程，不是 Mock）。
"""
import os

import pytest


@pytest.fixture(scope="module")
def peer_with_files(web):
    """B 的再部署：补上 web_ui.files（B 原样只声明 web_ui），用于文件通道隔离。"""
    plugin_id = web.plugin_b + "_files"
    web.deploy_variant(web.src_b, plugin_id,
                       permissions=["web_ui", "web_ui.files", "read_message",
                                    "plugin.call.*", "plugin.emit"])
    return plugin_id


def test_all_three_plugins_serve_their_own_pages(web):
    for plugin_id, marker in ((web.plugin_a, web.plugin_a), (web.plugin_b, web.plugin_b),
                              (web.plugin_c, web.plugin_c)):
        resp = web.get(web.page_url(plugin_id, "index"))
        assert resp.status == 200, "%s HTTP %s" % (plugin_id, resp.status)
        assert marker in resp.text, "%s 的页面没有出现自己的 id" % plugin_id


def test_pages_do_not_mix_content(web):
    """页面内容不串：A 的页面不得出现 B 的页面结构/名字，反之亦然。

    注意：A 的「最近一次调用」摘要里**可以**出现 B 的 plugin id（那是真实的调用记录，
    不是串页）——所以这里断言的是页面身份标记（B 的最小页面结构、插件名），而不是裸 id。
    """
    page_a = web.get(web.page_url(web.plugin_a, "index")).text
    page_b = web.get(web.page_url(web.plugin_b, "index")).text
    assert "Minimal Python Plugin" not in page_a, "A 的页面串了 B 的插件名"
    assert 'id="plugin-info"' not in page_a, "A 的页面串了 B 的页面结构"
    assert "lang-python" not in page_a, "A 的页面串了 B 的 CSS 作用域标记"
    assert "Plugin WebUI 测试插件" not in page_b, "B 的页面串了 A 的插件名"
    assert 'id="plugin-overview"' not in page_b, "B 的页面串了 A 的页面结构"
    assert web.element_text(page_b, "plugin-info") or "Language" in page_b


def test_css_is_per_plugin(web):
    css_a = web.get(web.static_url(web.plugin_a, "style.css")).text
    css_b = web.get(web.static_url(web.plugin_b, "style.css")).text
    assert css_a and css_b
    assert css_a != css_b, "两个插件的 CSS 内容相同（无法证明不串）"
    assert "lang-python" in css_b, "B 的 CSS 里没有 B 自己的作用域标记"
    assert "lang-python" not in css_a, "A 的 CSS 里出现 B 的作用域标记（CSS 串了）"
    assert ".flowerie-plugin-webui h1" in css_a, "A 的 CSS 内容不符合 A 的页面"


def test_static_file_of_other_plugin_is_not_reachable(web):
    """用 A 的 static 通道取 B 的文件（同名/不同名都不行）。"""
    probes = ("../%s/webui/static/style.css" % web.plugin_b,
              "../../%s/webui/static/style.css" % web.plugin_b,
              "%s.css" % web.plugin_b,
              "style.css")
    for probe in probes:
        resp = web.get(web.static_url(web.plugin_a, probe))
        if probe == "style.css":
            continue
        assert resp.status == 404, "%s 竟然可通过 A 的通道访问（HTTP %s）" % (probe, resp.status)


def test_upload_and_download_space_is_isolated(web, peer_with_files):
    name_a = "iso_probe_a.txt"
    name_b = "iso_probe_b.txt"
    body_a, ctype_a = web.multipart({}, [("file", name_a, b"content-from-plugin-a")])
    resp = web.request("POST", web.upload_url(web.plugin_a, "index"), body=body_a,
                       content_type=ctype_a)
    assert resp.status in (302, 303), "上传到 A 失败：HTTP %s" % resp.status
    body_b, ctype_b = web.multipart({}, [("file", name_b, b"content-from-plugin-b")])
    resp = web.request("POST", web.upload_url(peer_with_files, "index"), body=body_b,
                       content_type=ctype_b)
    assert resp.status in (302, 303), "上传到 B' 失败：HTTP %s" % resp.status

    got_a = web.get(web.file_url(web.plugin_a, name_a))
    assert got_a.status == 200 and got_a.body == b"content-from-plugin-a", \
        "A 取不回自己的文件：HTTP %s" % got_a.status
    got_b = web.get(web.file_url(peer_with_files, name_b))
    assert got_b.status == 200 and got_b.body == b"content-from-plugin-b", \
        "B' 取不回自己的文件：HTTP %s" % got_b.status

    cross_1 = web.get(web.file_url(web.plugin_a, name_b))
    assert cross_1.status != 200 or cross_1.body != b"content-from-plugin-b", \
        "A 读到了 B 的文件（跨插件文件泄漏）"
    cross_2 = web.get(web.file_url(peer_with_files, name_a))
    assert cross_2.status != 200 or cross_2.body != b"content-from-plugin-a", \
        "B 读到了 A 的文件（跨插件文件泄漏）"


def test_upload_dir_is_per_plugin_on_disk(web, peer_with_files):
    """黑盒之外的结构性证据：两个插件的 webui 空间是不同目录。"""
    dir_a = os.path.realpath(os.path.join(web.plugin_dir, web.plugin_a, "webui"))
    dir_b = os.path.realpath(os.path.join(web.plugin_dir, peer_with_files, "webui"))
    assert dir_a != dir_b
    assert os.path.isfile(os.path.join(dir_a, "iso_probe_a.txt"))
    assert not os.path.exists(os.path.join(dir_a, "iso_probe_b.txt"))
    assert os.path.isfile(os.path.join(dir_b, "iso_probe_b.txt"))
    assert not os.path.exists(os.path.join(dir_b, "iso_probe_a.txt"))


def test_config_does_not_leak_between_plugins(web):
    marker = "IsolationMarker-A-4711"
    web.post(web.page_url(web.plugin_a, "settings"),
             data={"plugin_action": "save", "name": marker, "number": "4711",
                   "enabled": "1", "mode": "debug"})
    try:
        page_a = web.get(web.page_url(web.plugin_a, "settings")).text
        page_b = web.get(web.page_url(web.plugin_b, "index")).text
        page_c = web.get(web.page_url(web.plugin_c, "index")).text
        assert marker in page_a, "A 自己的配置没有读回"
        assert marker not in page_b, "A 的配置串到了 B"
        assert marker not in page_c, "A 的配置串到了 C"
    finally:
        web.post(web.page_url(web.plugin_a, "settings"),
                 data={"plugin_action": "save", "name": "Flowerie", "number": "123",
                       "enabled": "1", "mode": "auto"})


def test_page_id_isolation(web):
    """用 B 的 pid 请求 A 独有的页面 id / 反过来，都不能串内容。"""
    resp = web.get(web.page_url(web.plugin_b, "communication"))
    assert "communication-panel" not in resp.text, "B 竟然渲染出 A 的 communication 页面"
    assert web.plugin_b in resp.text or "页面不存在" in resp.text or "不存在" in resp.text
    page_a = web.get(web.page_url(web.plugin_a, "communication")).text
    assert "communication-panel" in page_a
    assert "flowerie-webui lang-python" not in page_a, "A 的页面串了 B 的最小页面内容"


def test_session_token_is_not_leaked_to_pages(web):
    token = web.cookie.split("=", 1)[-1]
    assert token, "夹具没有登录态"
    for path in (web.page_url(web.plugin_a, "index"),
                 web.page_url(web.plugin_a, "communication"),
                 web.page_url(web.plugin_b, "index")):
        assert token not in web.get(path).text, "会话 token 泄漏到插件页面：%s" % path
