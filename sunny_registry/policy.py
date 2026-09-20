"""Control-plane gates: discovery, data_class, side_effects, ticket freshness."""

from __future__ import annotations

from typing import Any, Dict, Optional

DEFAULT_DISCOVERY = "registered_peers"
PEER_VISIBLE_DISCOVERY = "registered_peers"
KNOWN_DISCOVERY = frozenset({"registered_peers", "private", "approval_required"})
APPROVAL_NONE = "none"
APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"
KNOWN_APPROVAL = frozenset({APPROVAL_NONE, APPROVAL_PENDING, APPROVAL_APPROVED, APPROVAL_REJECTED})
SEARCHABLE_DATA_CLASSES = frozenset({"public", "internal"})
BLOCKED_SIDE_EFFECTS = frozenset({"write", "execute_sql"})
LIFECYCLE_REGISTERED = "registered"
LIFECYCLE_DISABLED = "disabled"
LIFECYCLE_DEPRECATED = "deprecated"
KNOWN_LIFECYCLES = frozenset({LIFECYCLE_REGISTERED, LIFECYCLE_DISABLED, LIFECYCLE_DEPRECATED})
PEER_READABLE_LIFECYCLES = frozenset({LIFECYCLE_REGISTERED, LIFECYCLE_DEPRECATED})


def is_peer_readable_lifecycle(lifecycle: Optional[str]) -> bool:
    return (lifecycle or "") in PEER_READABLE_LIFECYCLES


def can_issue_ticket(lifecycle: Optional[str]) -> bool:
    return lifecycle == LIFECYCLE_REGISTERED


def can_verify_ticket(lifecycle: Optional[str]) -> bool:
    return is_peer_readable_lifecycle(lifecycle)


def ticket_denied_for_lifecycle(lifecycle: Optional[str]) -> Optional[str]:
    if can_issue_ticket(lifecycle):
        return None
    if lifecycle == LIFECYCLE_DEPRECATED:
        return "callee is deprecated"
    return "callee is not registered"


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


def approval_status_of(stored: Optional[str], discovery: Optional[str] = None) -> str:
    value = stored or ""
    if value in KNOWN_APPROVAL:
        return value
    return APPROVAL_PENDING if discovery_of(stored=discovery) == "approval_required" else APPROVAL_NONE


def initial_approval_status(discovery: Optional[str]) -> str:
    return APPROVAL_PENDING if discovery_of(stored=discovery) == "approval_required" else APPROVAL_NONE


def is_awaiting_approval(discovery: Optional[str], approval_status: Optional[str]) -> bool:
    status = approval_status_of(approval_status, discovery)
    if status == APPROVAL_PENDING:
        return True
    if status == APPROVAL_REJECTED:
        return True
    return discovery_of(stored=discovery) == "approval_required"


def next_approval_status(
    old_discovery: Optional[str],
    old_status: Optional[str],
    new_discovery: Optional[str],
    allow_promote: bool,
) -> str:
    old_disc = discovery_of(stored=old_discovery)
    new_disc = discovery_of(stored=new_discovery)
    old = approval_status_of(old_status, old_disc)
    if new_disc == "approval_required":
        return APPROVAL_PENDING
    if new_disc == "private":
        return APPROVAL_NONE
    if old_disc == "approval_required" or old in {APPROVAL_PENDING, APPROVAL_REJECTED, APPROVAL_APPROVED}:
        return APPROVAL_APPROVED if allow_promote else APPROVAL_NONE
    return APPROVAL_NONE


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
    if not is_peer_readable_lifecycle(lifecycle):
        return False
    return is_peer_visible(discovery)


def can_read_full_card(*, is_admin: bool, is_owner: bool, is_self: bool) -> bool:
    """Default GET /agents/{id} full card: admin, creator, or the agent itself."""
    return bool(is_admin or is_owner or is_self)


def ticket_version_stale(payload_version: Optional[str], current_version: Optional[str]) -> bool:
    if not payload_version or not current_version:
        return True
    return payload_version != current_version
