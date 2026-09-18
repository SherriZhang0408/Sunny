"""Forward a mapped skill to an existing HTTP endpoint. URL comes from the mapping file, not slots."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx

from .mapping import MappingError, apply_map, expand_env


def _trace(slots: dict) -> str:
    return str(slots.get("trace_id") or "sid-{0}".format(uuid.uuid4().hex[:12]))


def _safe_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise MappingError("route url must be http(s) with a host")
    return url


def forward(
    route: Dict[str, Any],
    slots: Dict[str, Any],
    skill_id: str,
    client: httpx.Client,
    environ: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    trace = _trace(slots)
    url = _safe_url(expand_env(route["url"], environ))
    method = (route.get("method") or "POST").upper()
    timeout = float(route.get("timeout_s") or 15)
    headers = {}
    for key, value in (route.get("headers") or {}).items():
        headers[key] = expand_env(value, environ)
    body = apply_map(slots, skill_id, route.get("map"))
    try:
        res = client.request(method, url, json=body, headers=headers, timeout=timeout)
    except httpx.HTTPError:
        return {
            "ready": False,
            "mock": False,
            "trace_id": trace,
            "message": "upstream request failed",
        }
    if res.status_code >= 400:
        return {
            "ready": False,
            "mock": False,
            "trace_id": trace,
            "message": "upstream HTTP {0}".format(res.status_code),
        }
    try:
        payload = res.json()
    except Exception:
        return {
            "ready": True,
            "mock": False,
            "trace_id": trace,
            "data": None,
        }
    if isinstance(payload, dict) and "ready" in payload:
        payload.setdefault("trace_id", trace)
        return payload
    return {
        "ready": True,
        "mock": False,
        "trace_id": trace,
        "data": payload,
    }


def probe_downstream(url: str, client: httpx.Client, environ: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    try:
        target = _safe_url(expand_env(url, environ))
    except MappingError as exc:
        return {"configured": True, "ok": False, "error": str(exc)}
    try:
        res = client.get(target, timeout=3.0)
        return {"configured": True, "ok": res.status_code < 400, "status": res.status_code}
    except httpx.HTTPError:
        return {"configured": True, "ok": False, "error": "unreachable"}
