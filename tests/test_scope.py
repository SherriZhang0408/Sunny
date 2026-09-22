from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from sunny_registry.app import create_app
from sunny_registry.config import Settings
from sunny_registry import policy

ROOT = Path(__file__).resolve().parents[1]


def _base() -> dict:
    return json.loads((ROOT / "cards" / "aidata.hermes.sample.json").read_text(encoding="utf-8"))


def _card(agent_id: str, workspace: str, scope: str = "") -> dict:
    card = json.loads(json.dumps(_base()))
    card["name"] = agent_id
    card["description"] = agent_id + " 的说明"
    card["x-sunny"]["agent_id"] = agent_id
    card["x-sunny"]["workspace"] = workspace
    if scope:
        card["x-sunny"]["scope"] = scope
    else:
        card["x-sunny"].pop("scope", None)
    return card


def _client(tmp_path) -> TestClient:
    settings = Settings()
    settings.db_path = tmp_path / "scope.db"
    settings.admin_token = "admin-test"
    settings.enroll_token = "enroll-test"
    settings.ticket_secret = "ticket-test"
    settings.seed_on_empty = False
    return TestClient(create_app(settings))


def _admin(client: TestClient, method: str, url: str, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = "Bearer admin-test"
    return getattr(client, method)(url, headers=headers, **kwargs)


def _register(client: TestClient, card: dict) -> dict:
    res = client.post(
        "/api/v1/agents",
        json={"card": card, "enrollment_source": "self"},
        headers={"X-Sunny-Enroll": "enroll-test"},
    )
    assert res.status_code == 200, res.text
    _admin(client, "post", "/api/v1/agents/{0}/heartbeat".format(res.json()["agent_id"]))
    return res.json()


def _peer(key: str) -> dict:
    return {"X-Sunny-Agent-Key": key}


def test_scope_helpers():
    assert policy.scope_of({}) == ""
    assert policy.scope_of({"x-sunny": {"scope": "household"}}) == "household"
    assert policy.scope_visible("", "home.a", "home.b") is True
    assert policy.scope_visible("household", "home.a", "home.b") is False
    assert policy.scope_visible("household", "home.a", "home.a") is True
    assert policy.scope_visible("cohort", "home.a", "home.b", by_skill_or_tag=False) is False
    assert policy.scope_visible("cohort", "home.a", "home.b", by_skill_or_tag=True) is True
    assert policy.scope_ticket_denied("household", "home.a", "home.b")
    assert policy.scope_ticket_denied("cohort", "home.a", "home.b") is None


def test_household_stays_in_workspace_and_cohort_crosses_on_skill(tmp_path):
    client = _client(tmp_path)
    door = _register(client, _card("door.home", "home.a", "household"))
    mate = _register(client, _card("mate.home", "home.a"))
    guest = _register(client, _card("guest.home", "home.b"))
    strategy = _register(client, _card("strategy.fleet", "ecovacs.strategy", "cohort"))
    skill = "collect.volume.query"
    tag = _base()["skills"][0]["tags"][0]

    guest_headers = _peer(guest["agent_key"])
    mate_headers = _peer(mate["agent_key"])

    def ids(res):
        assert res.status_code == 200, res.text
        return {item["agent_id"] for item in res.json()["items"]}

    guest_skill = ids(client.get("/api/v1/search", params={"skill": skill}, headers=guest_headers))
    assert "strategy.fleet" in guest_skill
    assert "mate.home" in guest_skill
    assert "door.home" not in guest_skill

    guest_tag = ids(client.get("/api/v1/search", params={"tag": tag}, headers=guest_headers))
    assert "strategy.fleet" in guest_tag
    assert "door.home" not in guest_tag

    guest_bare = ids(client.get("/api/v1/search", headers=guest_headers))
    assert "strategy.fleet" not in guest_bare
    assert "door.home" not in guest_bare
    assert "mate.home" in guest_bare

    guest_list = ids(client.get("/api/v1/agents", headers=guest_headers))
    assert guest_list == {"guest.home", "mate.home"}

    mate_list = ids(client.get("/api/v1/agents", headers=mate_headers))
    assert "door.home" in mate_list
    assert "strategy.fleet" not in mate_list

    assert client.get("/api/v1/agents/door.home", headers=guest_headers).status_code == 404
    assert client.get("/api/v1/agents/door.home", headers=mate_headers).status_code == 200
    assert client.get("/api/v1/agents/strategy.fleet", headers=guest_headers).status_code == 200

    admin_ids = ids(_admin(client, "get", "/api/v1/agents"))
    assert {"door.home", "strategy.fleet"} <= admin_ids
    assert _admin(client, "get", "/api/v1/agents/door.home").json()["collab_scope"] == "household"

    blocked = client.post(
        "/api/v1/tickets",
        json={"callee_id": "door.home", "skill_id": skill},
        headers=guest_headers,
    )
    assert blocked.status_code == 403
    assert "household" in blocked.json()["detail"]

    allowed = client.post(
        "/api/v1/tickets",
        json={"callee_id": "door.home", "skill_id": skill},
        headers=mate_headers,
    )
    assert allowed.status_code == 200, allowed.text
    token = allowed.json()["ticket"]

    crossed = client.post(
        "/api/v1/tickets",
        json={"callee_id": "strategy.fleet", "skill_id": skill},
        headers=guest_headers,
    )
    assert crossed.status_code == 200, crossed.text

    updated = json.loads(json.dumps(_card("door.home", "home.a", "cohort")))
    put = _admin(client, "put", "/api/v1/agents/door.home", json={"card": updated})
    assert put.status_code == 200, put.text
    assert put.json()["collab_scope"] == "cohort"
    revoked = client.post(
        "/api/v1/tickets/verify",
        json={"ticket": token, "callee_id": "door.home", "skill_id": skill},
        headers=_peer(door["agent_key"]),
    )
    assert revoked.status_code == 401
    assert revoked.json()["detail"] == "ticket revoked"

    bad = _card("nope.scope", "home.a", "fleet")
    rejected = client.post(
        "/api/v1/agents",
        json={"card": bad, "enrollment_source": "self"},
        headers={"X-Sunny-Enroll": "enroll-test"},
    )
    assert rejected.status_code == 400
    assert "scope" in rejected.json()["detail"]
