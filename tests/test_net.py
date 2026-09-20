from __future__ import annotations

from sunny_registry.net import (
    advertise_host,
    host_from_header,
    is_unusable_advertise_host,
    list_lan_ipv4s,
    request_origin,
    resolve_public_url,
)


class _Req(object):
    def __init__(self, headers, scheme="http"):
        self.headers = headers
        self.url = type("U", (), {"scheme": scheme})()


def test_host_from_header_strips_port_and_brackets():
    assert host_from_header("10.1.2.3:8088") == "10.1.2.3"
    assert host_from_header("[2001:db8::1]:8088") == "2001:db8::1"
    assert host_from_header("registry.local") == "registry.local"
    assert host_from_header("") == ""


def test_unusable_advertise_hosts():
    assert is_unusable_advertise_host("0.0.0.0") is True
    assert is_unusable_advertise_host("[::]") is True
    assert is_unusable_advertise_host("*") is True
    assert is_unusable_advertise_host("10.63.117.37") is False


def test_advertise_host_prefers_explicit_then_lan():
    assert advertise_host("0.0.0.0", explicit="hub.example") == "hub.example"
    assert advertise_host("127.0.0.1") == "127.0.0.1"
    guessed = advertise_host("0.0.0.0")
    assert guessed
    assert guessed != "0.0.0.0"


def test_list_lan_ipv4s_never_includes_loopback():
    for ip in list_lan_ipv4s():
        assert not ip.startswith("127.")


def test_resolve_public_url_strips_slash_and_ignores_wildcard_listen():
    assert resolve_public_url("http://hub.example:8088/", "0.0.0.0", 8088) == "http://hub.example:8088"
    built = resolve_public_url("", "127.0.0.1", 8088)
    assert built == "http://127.0.0.1:8088"


def test_request_origin_uses_forwarded_proto():
    origin = request_origin(_Req({"host": "hub.example:8088", "x-forwarded-proto": "https"}))
    assert origin == "https://hub.example:8088"
    assert request_origin(_Req({"host": "0.0.0.0:8088"})) == ""
    assert request_origin(_Req({})) == ""
