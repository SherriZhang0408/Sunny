"""Public / A2A card views and HTTP cache headers. Never signs tickets."""

from __future__ import annotations

import copy
from typing import Any, Dict, Optional

from fastapi import Request
from fastapi.responses import JSONResponse, Response

CACHE_PUBLIC = "public, max-age=60"
CACHE_PRIVATE = "private, max-age=30"


def skill_data_class(skill: Any) -> str:
    if not isinstance(skill, dict):
        return "internal"
    ext = skill.get("x-sunny") if isinstance(skill.get("x-sunny"), dict) else {}
    value = ext.get("data_class") or skill.get("data_class") or "internal"
    return str(value)


def is_restricted_skill(skill: Any) -> bool:
    return skill_data_class(skill) == "restricted"


def has_restricted_skills(card: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(card, dict):
        return False
    skills = card.get("skills")
    if not isinstance(skills, list):
        return False
    return any(is_restricted_skill(skill) for skill in skills)


def mark_extended_card(card: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    exported = copy.deepcopy(card) if isinstance(card, dict) else {}
    if has_restricted_skills(exported):
        caps = exported.get("capabilities")
        if not isinstance(caps, dict):
            caps = {}
            exported["capabilities"] = caps
        caps["extendedAgentCard"] = True
    return exported


def public_card(card: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Drop restricted skills; keep x-sunny. Advertise extendedAgentCard when any were hidden."""
    exported = mark_extended_card(card)
    skills = exported.get("skills")
    if isinstance(skills, list):
        exported["skills"] = [skill for skill in skills if not is_restricted_skill(skill)]
    return exported


def card_etag(card: Optional[Dict[str, Any]]) -> str:
    version = ""
    if isinstance(card, dict):
        version = str(card.get("version") or "").strip()
    if not version:
        version = "empty"
    return '"{0}"'.format(version.replace('"', ""))


def etag_matches(if_none_match: Optional[str], etag: str) -> bool:
    if not if_none_match:
        return False
    for part in if_none_match.split(","):
        token = part.strip()
        if token == "*":
            return True
        if token.startswith("W/"):
            token = token[2:].strip()
        if token == etag:
            return True
    return False


def cached_json(
    request: Request,
    payload: Any,
    etag: str,
    cache_control: str,
    vary: Optional[str] = None,
) -> Response:
    headers = {"ETag": etag, "Cache-Control": cache_control}
    if vary:
        headers["Vary"] = vary
    if etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return JSONResponse(payload, headers=headers)


def _is_sunny_extension(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    uri = str(item.get("uri") or "").lower()
    return "sunny.local" in uri or "sunny.internal" in uri or "/sunny/" in uri


def strip_sunny_extensions(card: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    exported = copy.deepcopy(card) if isinstance(card, dict) else {}
    _drop_x_sunny(exported)
    caps = exported.get("capabilities")
    if isinstance(caps, dict):
        extensions = caps.get("extensions")
        if isinstance(extensions, list):
            kept = [item for item in extensions if not _is_sunny_extension(item)]
            if kept:
                caps["extensions"] = kept
            else:
                caps.pop("extensions", None)
    return exported


def _drop_x_sunny(obj: Any) -> None:
    if isinstance(obj, dict):
        obj.pop("x-sunny", None)
        for value in obj.values():
            _drop_x_sunny(value)
    elif isinstance(obj, list):
        for item in obj:
            _drop_x_sunny(item)
