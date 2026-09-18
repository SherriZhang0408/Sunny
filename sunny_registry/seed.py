"""Load sample cards when the database is empty."""

from __future__ import annotations

import json

from . import security
from .config import ROOT
from .security import ADMIN_USER_ID, DEVELOPER_USER_ID
from .store import Store


def _load(name: str) -> dict:
    return json.loads((ROOT / "cards" / name).read_text(encoding="utf-8"))


def seed_users(store: Store) -> None:
    if store.count_users() > 0:
        return
    store.create_user("admin", store.settings.admin_token, "admin", user_id=ADMIN_USER_ID)
    store.create_user("developer", store.settings.developer_password, "developer", user_id=DEVELOPER_USER_ID)


def seed_if_empty(store: Store) -> None:
    seed_users(store)
    if store.count_agents() > 0:
        return
    aidata = store.register(
        _load("aidata.hermes.sample.json"),
        "hub",
        "admin:admin",
        lifecycle="registered",
        created_by=ADMIN_USER_ID,
    )
    inspector = store.register(
        _load("lab.inspector.sample.json"),
        "self",
        "agent:self",
        lifecycle="registered",
        created_by=None,
    )
    store.heartbeat(aidata["agent_id"], "agent:{0}".format(aidata["agent_id"]))
    issued = security.issue_ticket(
        store.settings.ticket_secret,
        inspector["agent_id"],
        aidata["agent_id"],
        "collect.volume.query",
        store.settings.ticket_ttl_s,
    )
    store.record_ticket(issued["payload"])
    store.record_invocation(
        inspector["agent_id"],
        aidata["agent_id"],
        "collect.volume.query",
        "ok",
        "seed-trace-001",
        issued["payload"]["jti"],
        "agent:{0}".format(inspector["agent_id"]),
    )
