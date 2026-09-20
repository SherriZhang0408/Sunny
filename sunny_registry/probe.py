"""Card interface URL probe. Control-plane liveness only — never invoke skills."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

USER_AGENT = "SUNNY-Registry-Probe/1.0"
BLOCKED_HOSTS = frozenset(
    {
        "0.0.0.0",
        "::",
        "[::]",
        "169.254.169.254",
        "metadata.google.internal",
        "metadata.google.internal.",
    }
)
REACHABLE_STATUSES = frozenset(list(range(200, 400)) + [401, 403, 404])


def card_interface_urls(card: Optional[Dict[str, Any]]) -> List[str]:
    urls: List[str] = []
    for item in (card or {}).get("supportedInterfaces") or []:
        url = (item or {}).get("url")
        if url:
            urls.append(str(url).strip())
    top = (card or {}).get("url")
    if top:
        urls.append(str(top).strip())
    seen = set()
    unique: List[str] = []
    for url in urls:
        if url and url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def probe_targets(interface_url: str) -> List[str]:
    parsed = urlparse(interface_url)
    if not parsed.scheme or not parsed.netloc:
        return [interface_url]
    origin = "{0}://{1}".format(parsed.scheme, parsed.netloc)
    base = interface_url.rstrip("/")
    ordered = [
        origin + "/health",
        base + "/health",
        origin + "/.well-known/agent-card.json",
        base,
    ]
    seen = set()
    targets: List[str] = []
    for url in ordered:
        if url not in seen:
            seen.add(url)
            targets.append(url)
    return targets


def reject_url(url: str) -> Optional[str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "only http/https urls are allowed"
    if parsed.username or parsed.password:
        return "url must not contain credentials"
    host = (parsed.hostname or "").lower()
    if not host:
        return "url host is empty"
    if host in BLOCKED_HOSTS or host.startswith("169.254."):
        return "url host is blocked"
    return None


def _clip(text: str, limit: int = 200) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def classify_probe(result: Dict[str, Any]) -> str:
    if result.get("ok"):
        return "OK"
    error = str(result.get("error") or "").lower()
    status = result.get("status_code")
    if "blocked" in error or "only http/https" in error or "must not contain credentials" in error:
        return "BLOCKED"
    if "timeout" in error or "timed out" in error:
        return "TIMEOUT"
    if "ssl" in error or "tls" in error or "certificate" in error:
        return "TLS"
    if status == 404:
        return "404"
    if status:
        return "HTTP"
    if "no supportedinterfaces" in error or "no probe target" in error:
        return "NO_INTERFACE"
    return "UNREACHABLE"


def _with_category(result: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(result)
    out["category"] = classify_probe(out)
    return out


def probe_url(
    url: str,
    timeout_s: float,
    transport: Optional[httpx.BaseTransport] = None,
) -> Dict[str, Any]:
    blocked = reject_url(url)
    if blocked:
        return _with_category({"ok": False, "url": url, "status_code": None, "error": blocked})
    try:
        with httpx.Client(
            timeout=timeout_s,
            transport=transport,
            follow_redirects=False,
        ) as client:
            res = client.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*"},
            )
        ok = res.status_code in REACHABLE_STATUSES
        return _with_category(
            {
                "ok": ok,
                "url": url,
                "status_code": res.status_code,
                "error": None if ok else "http {0}".format(res.status_code),
            }
        )
    except httpx.TimeoutException as exc:
        return _with_category(
            {"ok": False, "url": url, "status_code": None, "error": _clip(str(exc) or "timeout")}
        )
    except httpx.HTTPError as exc:
        return _with_category({"ok": False, "url": url, "status_code": None, "error": _clip(str(exc))})


def probe_card(
    card: Optional[Dict[str, Any]],
    timeout_s: float,
    transport: Optional[httpx.BaseTransport] = None,
) -> Dict[str, Any]:
    interfaces = card_interface_urls(card)
    if not interfaces:
        return _with_category(
            {
                "ok": False,
                "url": None,
                "status_code": None,
                "error": "card has no supportedInterfaces url",
            }
        )
    last: Optional[Dict[str, Any]] = None
    for iface in interfaces:
        blocked = reject_url(iface)
        if blocked:
            last = _with_category({"ok": False, "url": iface, "status_code": None, "error": blocked})
            continue
        for target in probe_targets(iface):
            result = probe_url(target, timeout_s, transport)
            last = result
            if result["ok"]:
                return result
    return last or _with_category(
        {
            "ok": False,
            "url": None,
            "status_code": None,
            "error": "no probe target",
        }
    )
