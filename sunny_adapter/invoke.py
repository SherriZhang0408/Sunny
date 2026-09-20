"""Pick a mapping route, validate slots, then run a local handler or HTTP forward."""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from .config import AdapterSettings
from .enroll import load_card
from .mapping import MappingError, load_mapping, route_for
from .proxy import forward
from .skills import dispatch
from .slots import validate_slots


def invoke_skill(
    skill_id: str,
    slots: Dict[str, Any],
    settings: AdapterSettings,
    card: Optional[Dict[str, Any]] = None,
    upstream: Optional[httpx.Client] = None,
) -> Dict[str, Any]:
    card = card if card is not None else load_card(settings)
    known = [skill.get("id") for skill in (card.get("skills") or [])]
    if skill_id not in known:
        raise KeyError(skill_id)
    validate_slots(card, skill_id, slots)

    mapping = None
    if settings.mapping_path and settings.mapping_path.is_file():
        mapping = load_mapping(settings.mapping_path, settings.agent_id)
        route = route_for(mapping, skill_id)
        if route is None:
            raise KeyError(skill_id)
        if route.get("handler") == "http":
            if upstream is None:
                raise MappingError("http route needs an upstream client")
            return forward(route, slots, skill_id, upstream)
        return dispatch(skill_id, slots, settings)

    return dispatch(skill_id, slots, settings)
