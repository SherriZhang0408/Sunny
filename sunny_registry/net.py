"""Listen vs advertise: bind 0.0.0.0, never publish 0.0.0.0 as a client URL."""

from __future__ import annotations

import socket
from typing import List, Optional


def guess_lan_ipv4() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 80))
        ip = sock.getsockname()[0]
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    finally:
        sock.close()
    return "127.0.0.1"


def _is_rfc1918(ip: str) -> bool:
    if ip.startswith("10.") or ip.startswith("192.168."):
        return True
    if ip.startswith("172."):
        try:
            second = int(ip.split(".")[1])
        except (IndexError, ValueError):
            return False
        return 16 <= second <= 31
    return False


def _is_preferred_lan(ip: str) -> bool:
    return ip.startswith("10.") or ip.startswith("192.168.")


def list_lan_ipv4s() -> List[str]:
    found = []
    guessed = guess_lan_ipv4()
    if guessed and not guessed.startswith("127."):
        found.append(guessed)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and _is_rfc1918(ip) and ip not in found:
                found.append(ip)
    except OSError:
        pass
    preferred = [ip for ip in found if _is_preferred_lan(ip)]
    return preferred or found


def host_from_header(host_header: str) -> str:
    raw = (host_header or "").strip()
    if raw.startswith("["):
        end = raw.find("]")
        return raw[1:end] if end > 0 else raw
    return raw.rsplit(":", 1)[0] if raw.count(":") == 1 else raw


def is_unusable_advertise_host(host: str) -> bool:
    value = host_from_header(host).lower().strip("[]")
    return value in {"", "0.0.0.0", "::", "*"}


def advertise_host(listen_host: str, explicit: str = "") -> str:
    if explicit:
        return explicit
    if is_unusable_advertise_host(listen_host):
        return guess_lan_ipv4()
    return listen_host


def resolve_public_url(public_url: str, listen_host: str, listen_port: int, request: Optional[object] = None) -> str:
    if public_url:
        return public_url.rstrip("/")
    host = advertise_host(listen_host)
    return "http://{0}:{1}".format(host, listen_port)


def request_origin(request: object) -> str:
    host = ""
    scheme = "http"
    headers = getattr(request, "headers", None)
    if headers is not None:
        host = headers.get("host") or ""
        scheme = headers.get("x-forwarded-proto") or getattr(getattr(request, "url", None), "scheme", None) or "http"
    if not host or is_unusable_advertise_host(host):
        return ""
    return "{0}://{1}".format(scheme, host).rstrip("/")
