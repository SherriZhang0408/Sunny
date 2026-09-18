"""Control-plane observe events. Never store tickets, keys, or passwords."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

KINDS = ("search", "ticket", "invoke", "card")
EVENT_STATUSES = ("ok", "denied", "error", "issued")


def clip(value: Optional[str], limit: int = 200) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def search_detail(
    skill: Optional[str],
    tag: Optional[str],
    workspace: Optional[str],
    q: Optional[str],
    hits: List[str],
    count: int,
) -> Dict[str, Any]:
    return {
        "skill": clip(skill, 80),
        "tag": clip(tag, 80),
        "workspace": clip(workspace, 80),
        "q": clip(q, 200),
        "hits": hits[:20],
        "count": int(count),
    }


def shape_event(
    *,
    event_id: str,
    kind: str,
    status: str,
    actor: str,
    created_at: str,
    caller_id: Optional[str] = None,
    callee_id: Optional[str] = None,
    skill_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    ticket_jti: Optional[str] = None,
    summary: str = "",
    detail: Optional[Dict[str, Any]] = None,
    action: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "id": event_id,
        "kind": kind,
        "action": action or kind,
        "status": status,
        "actor": actor,
        "caller_id": caller_id,
        "callee_id": callee_id,
        "agent_id": agent_id or callee_id or caller_id,
        "skill_id": skill_id,
        "trace_id": trace_id,
        "ticket_jti": ticket_jti,
        "summary": summary,
        "detail": detail or {},
        "created_at": created_at,
    }
