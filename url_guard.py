#!/usr/bin/env python3
"""SSRF対策の共有ガード。

外部URLをfetchする前に検証する。スキームを http/https に限定し、
ホスト名をDNS解決して private / loopback / link-local / reserved 等の
内部向けIPを全てブロックする。これにより以下を弾く:

- クラウドメタデータ: http://169.254.169.254/ (link-local)
- localhost / 127.0.0.1 / ::1 (loopback)
- LAN: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 (private)
- file:// / ftp:// 等の非HTTPスキーム

注意（残留リスク）: DNS解決時のIPと実接続時のIPがずれる DNS rebinding は
本ガードでは完全には防げない（解決→検査→各ライブラリが再解決して接続するため）。
requests 経路は safe_head() でリダイレクトを手動追跡し各ホップを再検証するが、
trafilatura / playwright / markitdown の内部リダイレクトは入口検証のみ。
"""

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

ALLOWED_SCHEMES = {"http", "https"}


class UnsafeURLError(ValueError):
    """SSRF的に危険なURLを拒否したことを表す例外。"""


def _ip_is_blocked(ip_str):
    ip = ipaddress.ip_address(ip_str)
    # IPv4-mapped IPv6 (::ffff:a.b.c.d) は内側のIPv4で判定する。
    # Python<3.13 では IPv6Address("::ffff:127.0.0.1").is_private が False を返す不備があり、
    # 明示的に展開しないと内部IPを取りこぼす。
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def assert_safe_url(url):
    """url が外部fetch可能か検証する。危険なら UnsafeURLError を送出。

    成功時は (scheme, host, [resolved_ips]) を返す。
    """
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f"許可されないスキーム: {scheme or '(なし)'} ({url})")

    host = parsed.hostname
    if not host:
        raise UnsafeURLError(f"ホスト名がありません: {url}")

    # libc(inet_aton)系クライアント（Chromium/一部HTTPライブラリ）は 8進/16進/10進の
    # 数値IPv4を getaddrinfo と異なる解釈で接続しうる。パーサ差分によるSSRFを塞ぐため、
    # ホストが数値IPv4リテラルとして解釈可能なら、その解釈でのIPもブロック判定する。
    try:
        aton_ip = socket.inet_ntoa(socket.inet_aton(host))
    except OSError:
        aton_ip = None
    if aton_ip and _ip_is_blocked(aton_ip):
        raise UnsafeURLError(f"内部向けIP(数値表記)へのアクセスをブロック: {host} -> {aton_ip}")

    try:
        port = parsed.port
    except ValueError:
        raise UnsafeURLError(f"不正なポート: {url}")
    port = port or (443 if scheme == "https" else 80)

    # ホスト名をDNS解決し、全解決IPを検査（複数A/AAAAレコード対策）
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeURLError(f"ホスト名を解決できません: {host} ({e})")

    ips = sorted({info[4][0] for info in infos})
    for ip in ips:
        if _ip_is_blocked(ip):
            raise UnsafeURLError(f"内部向けIPへのアクセスをブロック: {host} -> {ip}")
    return scheme, host, ips


def safe_head(url, *, max_redirects=5, timeout=10):
    """requests.head 相当。リダイレクトを手動追跡し、各ホップで assert_safe_url する。

    最終的な requests.Response を返す。危険なホップに到達したら UnsafeURLError。
    """
    import requests

    current = url
    for _ in range(max_redirects + 1):
        assert_safe_url(current)
        resp = requests.head(current, allow_redirects=False, timeout=timeout)
        if resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("Location")
            if not loc:
                return resp
            current = urljoin(current, loc)
            continue
        return resp
    raise UnsafeURLError(f"リダイレクトが多すぎます: {url}")
