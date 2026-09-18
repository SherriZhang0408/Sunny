"""Control-plane gates: discovery, data_class, side_effects, ticket freshness."""

from __future__ import annotations

from typing import Any, Dict, Optional

DEFAULT_DISCOVERY = "registered_peers"
PEER_VISIBLE_DISCOVERY = "registered_peers"
KNOWN_DISCOVERY = frozenset({"registered_peers", "private", "approval_required"})
SEARCHABLE_DATA_CLASSES = frozenset({"public", "internal"})
BLOCKED_SIDE_EFFECTS = frozenset({"write", "execute_sql"})


def discovery_of(card: Optional[Dict[str, Any]] = None, stored: Optional[str] = None) -> str:
    if stored:
        value = stored
    else:
        value = ((card or {}).get("x-sunny") or {}).get("discovery") or DEFAULT_DISCOVERY
    if value not in KNOWN_DISCOVERY:
        return DEFAULT_DISCOVERY
    return value


def is_peer_visible(discovery: Optional[str]) -> bool:
    return discovery_of(stored=discovery) == PEER_VISIBLE_DISCOVERY


def is_skill_searchable(data_class: Optional[str], side_effects: Optional[str]) -> bool:
    if (side_effects or "read") in BLOCKED_SIDE_EFFECTS:
        return False
    return (data_class or "internal") in SEARCHABLE_DATA_CLASSES


def peer_ticket_denied(skill: Dict[str, Any], discovery: Optional[str]) -> Optional[str]:
    if not is_peer_visible(discovery):
        return "agent is not discoverable by peers"
    effects = skill.get("side_effects") or "read"
    data_class = skill.get("data_class") or "internal"
    if effects in BLOCKED_SIDE_EFFECTS:
        return "write/execute_sql skills are not callable by peers"
    if data_class == "restricted":
        return "restricted skills are not callable by peers"
    return None


def can_view_agent(
    *,
    is_admin: bool,
    is_owner: bool,
    is_self: bool,
    lifecycle: str,
    discovery: Optional[str],
) -> bool:
    if is_admin or is_owner or is_self:
        return True
    if lifecycle != "registered":
        return False
    return is_peer_visible(discovery)


def ticket_version_stale(payload_version: Optional[str], current_version: Optional[str]) -> bool:
    if not payload_version or not current_version:
        return True
    return payload_version != current_version
