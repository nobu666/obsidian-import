import socket
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from url_guard import UnsafeURLError, assert_safe_url, safe_head


def _gai(ip):
    """socket.getaddrinfo のモック戻り値（family, type, proto, canon, (ip, port)）"""
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 0))]


@pytest.mark.parametrize("url", [
    "ftp://example.com/x",
    "file:///etc/passwd",
    "gopher://example.com/",
    "javascript:alert(1)",
    "http://",        # ホストなし
    "https://",
])
def test_scheme_or_host_blocked(url):
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",  # クラウドメタデータ
    "http://127.0.0.1/",
    "http://10.0.0.1/",
    "http://172.16.0.1/",
    "http://192.168.1.1/",
    "http://[::1]/",
    "http://0.0.0.0/",
])
def test_literal_internal_ip_blocked(url):
    # リテラルIPは getaddrinfo がそのIPをそのまま返すのでモック不要
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


@pytest.mark.parametrize("url", [
    "http://0177.0.0.1/",   # 8進 -> 127.0.0.1
    "http://0x7f.0.0.1/",   # 16進 -> 127.0.0.1
    "http://2130706433/",   # 10進 -> 127.0.0.1
])
def test_numeric_ipv4_parser_differential_blocked(url):
    # getaddrinfo と inet_aton の解釈差を突く数値IP表記をブロック
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


def test_public_host_allowed():
    with patch("url_guard.socket.getaddrinfo", return_value=_gai("93.184.216.34")):
        scheme, host, ips = assert_safe_url("https://example.com/page")
    assert scheme == "https"
    assert host == "example.com"
    assert ips == ["93.184.216.34"]


@pytest.mark.parametrize("ip", ["::1", "fe80::1", "::", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "::ffff:169.254.169.254"])
def test_getaddrinfo_resolved_ipv6_internal_blocked(ip):
    # ホストが内部向けIPv6(IPv4-mapped含む)に解決されたらブロック
    with patch("url_guard.socket.getaddrinfo", return_value=_gai(ip)):
        with pytest.raises(UnsafeURLError):
            assert_safe_url("http://evil.example.test/")


def test_hostname_resolving_to_private_blocked():
    # 公開ドメインに見えても内部IPに解決されたらブロック（DNS仕込み対策）
    with patch("url_guard.socket.getaddrinfo", return_value=_gai("10.1.2.3")):
        with pytest.raises(UnsafeURLError):
            assert_safe_url("http://internal.example.test/")


def test_unresolvable_host_blocked():
    with patch("url_guard.socket.getaddrinfo", side_effect=socket.gaierror("nope")):
        with pytest.raises(UnsafeURLError):
            assert_safe_url("http://no-such-host.invalid/")


class _Resp:
    def __init__(self, status, location=None, url=None):
        self.status_code = status
        self.headers = {"Location": location} if location else {}
        self.url = url


def _host_aware_gai(host, *a, **k):
    # 内部IPホストはそのIPを、それ以外は公開IPを返す
    internal = {"169.254.169.254"}
    return _gai(host if host in internal else "93.184.216.34")


def test_safe_head_blocks_redirect_to_internal():
    # 公開URLから 302 で 169.254.169.254 へリダイレクト → 各ホップ検証でブロック
    with patch("url_guard.socket.getaddrinfo", side_effect=_host_aware_gai), \
         patch("requests.head", return_value=_Resp(302, location="http://169.254.169.254/")):
        with pytest.raises(UnsafeURLError):
            safe_head("https://start.example/")


def test_safe_head_follows_public_redirect():
    seq = [
        _Resp(302, location="/article"),  # 相対Location
        _Resp(200, url="https://start.example/article"),
    ]
    with patch("url_guard.socket.getaddrinfo", return_value=_gai("93.184.216.34")), \
         patch("requests.head", side_effect=seq):
        resp = safe_head("https://start.example/")
    assert resp.status_code == 200
    assert resp.url == "https://start.example/article"


def test_safe_head_redirect_loop_aborts():
    # 同一URLへの302ループは max_redirects で打ち切る
    with patch("url_guard.socket.getaddrinfo", return_value=_gai("93.184.216.34")), \
         patch("requests.head", return_value=_Resp(302, location="https://loop.example/")):
        with pytest.raises(UnsafeURLError):
            safe_head("https://loop.example/")
