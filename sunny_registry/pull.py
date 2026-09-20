"""Fetch a SUNNY Card from a well-known or Card URL. Never invoke skills."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx

from .probe import reject_url

USER_AGENT = "SUNNY-Registry-Pull/1.0"
MAX_REDIRECTS = 3
MAX_BYTES = 256 * 1024


class PullError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _clip(text: str, limit: int = 200) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def card_fetch_targets(url: str) -> List[str]:
    raw = (url or "").strip()
    if not raw:
        raise PullError(400, "pull url is required")
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        raise PullError(400, "pull url must include scheme and host")
    origin = "{0}://{1}".format(parsed.scheme, parsed.netloc)
    base = raw.rstrip("/")
    path = (parsed.path or "").lower()
    if (
        path.endswith("/.well-known/agent-card.json")
        or path.endswith("/.well-known/agent.json")
        or path.endswith(".json")
    ):
        return [raw]
    ordered = [
        base + "/.well-known/agent-card.json",
        origin + "/.well-known/agent-card.json",
        base + "/.well-known/agent.json",
        origin + "/.well-known/agent.json",
    ]
    seen = set()
    targets: List[str] = []
    for item in ordered:
        if item not in seen:
            seen.add(item)
            targets.append(item)
    return targets


def _follow_location(current: str, location: str) -> str:
    nxt = urljoin(current, location)
    blocked = reject_url(nxt)
    if blocked:
        raise PullError(400, blocked)
    return nxt


def fetch_json_object(
    url: str,
    timeout_s: float,
    transport: Optional[httpx.BaseTransport] = None,
) -> Tuple[Dict[str, Any], str]:
    blocked = reject_url(url)
    if blocked:
        raise PullError(400, blocked)
    current = url
    try:
        with httpx.Client(
            timeout=timeout_s,
            transport=transport,
            follow_redirects=False,
        ) as client:
            for _hop in range(MAX_REDIRECTS + 1):
                res = client.get(
                    current,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "application/json, application/agent-card+json, text/plain, */*",
                    },
                )
                if res.status_code in {301, 302, 303, 307, 308}:
                    location = res.headers.get("location")
                    if not location:
                        raise PullError(502, "redirect without location from {0}".format(current))
                    current = _follow_location(current, location)
                    continue
                if res.status_code != 200:
                    raise PullError(502, "http {0} from {1}".format(res.status_code, current))
                body = res.content or b""
                if len(body) > MAX_BYTES:
                    raise PullError(400, "card body exceeds {0} bytes".format(MAX_BYTES))
                try:
                    parsed = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise PullError(400, "response from {0} is not JSON".format(current))
                if not isinstance(parsed, dict):
                    raise PullError(400, "card must be a JSON object")
                return parsed, current
    except PullError:
        raise
    except httpx.HTTPError as exc:
        raise PullError(502, _clip(str(exc)))
    raise PullError(502, "too many redirects from {0}".format(url))


def fetch_sunny_card(
    url: str,
    timeout_s: float,
    transport: Optional[httpx.BaseTransport] = None,
) -> Dict[str, Any]:
    last_error: Optional[PullError] = None
    for target in card_fetch_targets(url):
        try:
            card, fetched = fetch_json_object(target, timeout_s, transport)
            return {"card": card, "source_url": fetched, "tried": target}
        except PullError as exc:
            last_error = exc
            if exc.status_code == 400 and "not JSON" not in exc.detail and "http " not in exc.detail:
                raise
            continue
    if last_error:
        raise last_error
    raise PullError(502, "no well-known card at {0}".format(url))


def apply_agent_id(card: Dict[str, Any], agent_id: Optional[str]) -> Dict[str, Any]:
    prepared = json.loads(json.dumps(card))
    overlay = (agent_id or "").strip()
    if overlay:
        sunny = prepared.setdefault("x-sunny", {})
        if not isinstance(sunny, dict):
            raise PullError(400, "x-sunny must be an object")
        sunny["agent_id"] = overlay
    return prepared
