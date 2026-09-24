"""Code Scanning #51 (py/full-ssrf) 的证明性测试 —— 三层防线必须在网络请求之前。

背景：CodeQL 对 src/plugins/installer.py:168 的 client.stream("GET", url) 报了
critical 级 py/full-ssrf（"整个 URL 都来自用户输入"）。审计结论是**误报**，理由：
    152-155 行 validate_mcp_server_url(url)      —— 字面量校验（scheme/userinfo/回环/私网/后缀）
    156-159 行 _check_dns(parts)                 —— 解析结果校验（抗 DNS rebinding）
    163    行 follow_redirects=False             —— 拒绝任何 3xx 二次跳转
三层都在 sink 之前，且任一层失败都会抛 PluginInstallError —— URL 无法带着不安全的目标走到请求处。

CodeQL 看不到这层保证，所以用本测试把它固定下来（结构 + 纯函数两层，不依赖网络库）：
- 结构与顺序：源码里两个 sanitizer 出现在 client.stream 之前
- 纯函数：字面量校验确实拒绝各类 SSRF 载荷
"""
import io

from src.core.sanitizer import validate_mcp_server_url

INSTALLER = "src/plugins/installer.py"


def _installer_source() -> str:
    return io.open(INSTALLER, encoding="utf-8").read()


def test_both_ssrf_defenses_precede_the_network_call():
    """两个 sanitizer 必须出现在 client.stream(...) 之前（顺序错了防线就失效）。"""
    src = _installer_source()
    i_literal = src.find("validate_mcp_server_url(url)")
    i_dns = src.find("await self._check_dns(parts)")
    i_sink = src.find('client.stream("GET", url')
    assert i_literal > 0, "找不到字面量校验"
    assert i_dns > 0, "找不到 DNS 解析校验"
    assert i_sink > 0, "找不到网络请求"
    assert i_literal < i_sink and i_dns < i_sink, (
        "SSRF 防线必须在请求之前：literal=%d dns=%d sink=%d" % (i_literal, i_dns, i_sink))


def test_redirects_are_refused():
    """不做二次跳转（redirect SSRF 的关键）。"""
    src = _installer_source()
    assert "follow_redirects=False" in src
    assert "max_redirects=self.download_max_redirects" in src


def test_literal_sanitizer_rejects_classic_ssrf_payloads():
    """字面量校验：回环 / 私网 / 元数据地址 / userinfo / 非 http(s) / 内网后缀 全部拒绝。"""
    for bad in ("http://127.0.0.1/x.zip", "http://localhost/x.zip", "http://[::1]/x.zip",
                "http://0.0.0.0/x.zip", "http://10.0.0.1/x.zip", "http://192.168.1.1/x.zip",
                "http://172.16.0.1/x.zip", "http://169.254.169.254/latest/meta-data/",
                "http://user:pass@example.com/x.zip", "ftp://example.com/x.zip",
                "http://evil.local/x.zip", "file:///etc/passwd", ""):
        ok, reason = validate_mcp_server_url(bad)
        assert ok is False, "应拒绝：%s" % bad
        assert reason, bad


def test_literal_sanitizer_allows_public_https():
    """正常的公网 https 目标必须放行（避免为过扫描而破坏业务，任务书 §13）。"""
    ok, reason = validate_mcp_server_url("https://example.com/plugin.zip")
    assert ok is True, reason
